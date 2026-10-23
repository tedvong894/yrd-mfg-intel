#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
长三角制造业问题解剖情报 — 增量采集器（免密钥）
数据源（按优先级自动降级）：
  1) Google News RSS 搜索（news.google.com/rss/search）— 质量最好，GitHub Actions 上稳定可用
  2) Bing 网页搜索 HTML 解析（www.bing.com/search）— 兜底
  3) 36氪 RSS 快讯（www.36kr.com/feed）— 通用商业资讯补充
流程：批量检索（6 个搜集角度 × 4 地区）→ 相关性过滤（必须同时命中"问题词"与"制造/企业词"）
      → **时效性过滤（只保留近 N 年，更早的旧案例丢弃）** → 与 intel_db.jsonl 及当日 raw 去重
      → **只产出新增案例** → 合并写回 raw_YYYYMMDD.json。
用法：
  python3 collect.py [--limit N] [--dry-run] [--workers 6] [--intel-dir DIR]
依赖：仅 Python 标准库，不需要任何 API Key。
"""
import argparse
import datetime
import email.utils
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import dissect  # noqa: E402
import intel_processor as ipro  # noqa: E402

# ── 查询矩阵：6 个搜集角度 × 4 地区 ─────────────────────────
# 搜集方向（2026-10-21 改，偏"生产管理深挖"）：只搜集能进入深入原因剖析、对中小制造
# 老板有参考价值的案例，少收"一句话讲清、表面原因"的快讯/事件卡。6 个角度均指向
# 生产运营层面的可拆解问题，而非泛泛的经营困境。
REFRESH_REGIONS = ["浙江", "江苏", "上海", "安徽"]
REFRESH_TEMPLATES = [
    "{r} 中小制造企业 经营困难 订单 成本 复盘 案例",
    "{r} 中小企业 生产管理 排产 库存 成本 诊断 案例",
    "{r} 专精特新 小巨人 制造业 经营 问题 深度报道",
    "{r} 民营中小工厂 亏损 停产 债务 深度 调查",
    "{r} 管理咨询 制造业 诊断案例 成本改善 效率提升",
    "{r} 咨询公司 制造业 客户案例 产线 精益 降本",
    "{r} 数字化转型 中小制造企业 车间 改造 案例 咨询",
    "{r} 工厂 成本管控 库存 呆滞 采购 改善 案例",
    "{r} 制造企业 成本 库存 采购 专项改善 咨询 案例",
    "{r} 中小制造企业 精益生产 现场改善 诊断 报告 案例",
]

# 相关性过滤词：原有「问题词」+ 生产管理深挖角度的补充词，确保深挖类案例能进库、
# 同时不误收纯宏观述评/单一事件快讯（那些靠 intel_processor 的 deleted_ids 与表层过滤处理）。
ANGLE_WORDS = {
    # 生产计划 / 排产 / 交期
    "生产管理", "生产计划", "排产", "插单", "交期", "在制品", "半成品", "缺料停线", "停产待料",
    # 产能 / 设备效率
    "产能利用率", "稼动率", "OEE", "设备空转", "产能闲置", "隐性产能", "新线爬坡", "爬坡失败",
    # 质量 / 成本
    "良率", "合格率", "返工", "报废", "不良率", "质量成本", "成本结构", "隐性成本", "成本倒挂",
    "单位成本", "固定成本", "变动成本", "人机料法环", "沉没成本", "重资产",
    # 库存 / 周转 / 采购
    "库存周转", "呆滞", "积压", "资金占用", "台班", "人均产出", "采购成本", "供应商管理", "账期",
    # 工艺 / 技改
    "工艺", "技改", "自动化回报", "智能化踩坑",
    # 供应链
    "供应链断点", "断供", "供应商", "精益生产",
}
# 中小制造业 / 咨询诊断类补充词：让这类深度案例能通过相关性过滤。
SME_WORDS = {
    "中小企业", "中小制造", "中小厂", "民营企业", "民营经济", "专精特新", "小巨人",
    "小微企业", "个体工商户", "中小老板", "中小企业协会",
}
CONSULT_WORDS = {
    "诊断", "改善", "精益", "降本", "提效", "驻厂", "陪跑", "专项改善", "标杆",
    "咨询案例", "服务案例", "客户案例", "诊断报告", "改善案例", "转型案例", "降本增效",
}
PROBLEM_WORDS = sorted({w for kws in dissect.TYPE_KEYWORDS.values() for w in kws} |
                       {"停产", "裁员", "缩减", "爆雷", "失信", "降薪", "清退", "烂尾", "暴雷", "重整", "拍卖",
                        "降本", "提效", "增效", "亏损", "订单下滑", "经营困难"} |
                       ANGLE_WORDS | SME_WORDS | CONSULT_WORDS |
                       set(ipro.ANALYTIC_WORDS))   # 成本/库存/采购/应收 等分析类落点
BIZ_WORDS = ["制造", "工厂", "企业", "公司", "集团", "厂", "加工", "生产", "产能", "车间",
             "民企", "中小", "实业", "供应链", "代工", "订单", "产线", "设备", "产业园"]
BLOCK_DOMAINS = {"baike.baidu.com", "zhidao.baidu.com", "wikipedia.org", "dict.youdao.com",
                 "wiki.mbalib.com", "book.douban.com", "zhihu.com", "so.com"}

# 质量筛查规则统一放在 intel_processor（采集端与入库端共用同一份，避免规则漂移）：
#   ipro.is_ad_card / ipro.is_listed_card / ipro.is_surface_card
# AD_CTA / AD_SYSTEM / AD_SELL / LISTED_* 词表见 intel_processor.py。

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_UA_GOOGLE = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"


def build_queries():
    return [tpl.replace("{r}", r) for tpl in REFRESH_TEMPLATES for r in REFRESH_REGIONS]


def fetch(url, timeout=25, ua=UA):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "zh-CN,zh;q=0.9",
                                              "Accept": "application/rss+xml,application/xml,text/html,*/*"})
    with _OPENER.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def domain_of(url):
    m = re.match(r"https?://([^/]+)", url or "")
    return (m.group(1) if m else "").lower()


def to_iso(pub):
    try:
        return email.utils.parsedate_to_datetime(pub).date().isoformat()
    except Exception:
        return datetime.date.today().isoformat()


# ── 时效性：只保留近 N 年的材料，过早的旧案例不入库 ──
# 用户要求：素材搜集时间限定在近 3 年，不要搜集过早的材料。
RECENCY_YEARS = 3  # 若想放宽/收紧，改这里，或用命令行 --max-age-years 覆盖


def _cutoff_date(today):
    """近 N 年的起始日期；处理闰年 2/29 → 回退到 3/1，避免 replace 抛错。"""
    y = today.year - RECENCY_YEARS
    try:
        return today.replace(year=y)
    except ValueError:
        return today.replace(year=y, month=3, day=1)


def recent_enough(it, cutoff):
    """item 是否不早于 cutoff（近 N 年窗口）。无明确发布日期（Bing 等）按最新处理，保留。"""
    d = it.get("date", "")
    if len(d) < 10:
        return True  # 没有可解析日期 → 视为近期，保留
    try:
        pub = datetime.date.fromisoformat(d)
    except Exception:
        return True
    return pub >= cutoff


# ── 源 1：Google News RSS ──────────────────────────────
def src_google_news(q):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"})
    xml = fetch(url, ua=_UA_GOOGLE)
    rows = []
    for blk in re.findall(r"<item>(.*?)</item>", xml, re.S):
        def pick(tag):
            m = re.search(rf"<{tag}>(.*?)</{tag}>", blk, re.S)
            return strip_tags(m.group(1)) if m else ""
        title, link, pub = pick("title"), pick("link"), pick("pubDate")
        desc = re.sub(r"<a[^>]*>.*?</a>", "", pick("description"), flags=re.S)
        if title and link:
            # Google News 标题常带 " - 来源"，去掉尾巴
            title = re.sub(r"\s+-\s+[^-]{1,20}$", "", title).strip()
            rows.append({"title": title, "url": link, "desc": desc, "pub": pub})
    return rows


# ── 源 2：Bing 网页搜索 HTML ──────────────────────────
def src_bing_web(q):
    url = "https://www.bing.com/search?" + urllib.parse.urlencode(
        {"q": q, "setlang": "zh-CN", "cc": "CN", "count": "20"})
    doc = fetch(url)
    rows = []
    for blk in re.split(r'<li class="b_algo"', doc)[1:]:
        blk = blk[:6000]
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', blk, re.S)
        if not m:
            continue
        link, title = m.group(1), strip_tags(m.group(2))
        p = re.search(r"<p[^>]*>(.*?)</p>", blk, re.S)
        desc = strip_tags(p.group(1)) if p else ""
        if title and link.startswith("http"):
            rows.append({"title": title, "url": link, "desc": desc, "pub": ""})
    return rows


# ── 源 3：36氪 RSS（通用商业资讯） ────────────────────
def src_36kr():
    xml = fetch("https://www.36kr.com/feed", timeout=20)
    rows = []
    for blk in re.findall(r"<item>(.*?)</item>", xml, re.S):
        def pick(tag):
            m = re.search(rf"<{tag}>(.*?)</{tag}>", blk, re.S)
            return strip_tags(m.group(1)) if m else ""
        title, link, pub = pick("title"), pick("link"), pick("pubDate")
        desc = strip_tags(re.sub(r"<!\[CDATA\[|\]\]>", "", pick("description")))
        if title and link:
            rows.append({"title": title, "url": link, "desc": desc, "pub": pub, "query": "36氪快讯"})
    return rows


def scan_one(q):
    """按优先级尝试多个源，取第一个有结果的。"""
    for name, fn in (("google", src_google_news), ("bing", src_bing_web)):
        try:
            rows = fn(q)
            if rows:
                for r in rows:
                    r.setdefault("query", q)
                return q, rows, name
        except Exception as e:
            print(f"[warn] {name} 查询失败：{q}（{type(e).__name__}）")
    return q, [], "none"


# ── 相关性与构造 ──────────────────────────────────────
def extract_problems(text, limit=3):
    hits = []
    for s in re.split(r"[。；;!！?？\n]", text or ""):
        s = s.strip()
        if 4 <= len(s) <= 90 and any(w in s for w in PROBLEM_WORDS):
            hits.append(s)
        if len(hits) >= limit:
            break
    return hits


def relevant(it):
    """相关性 + 质量筛查（广告 / 上市公司财报体 / 表面事件卡 一律丢弃）。"""
    text = (it["title"] + " " + it.get("snippet", "")).lower()
    dom = domain_of(it["url"])
    if any(b in dom for b in BLOCK_DOMAINS):
        return False
    if ipro.is_ad_card(it):
        return False
    if ipro.is_listed_card(it):
        return False
    if not any(w in text for w in PROBLEM_WORDS):
        return False
    if not any(w in text for w in BIZ_WORDS):
        return False
    if len(it["title"]) < 8:
        return False
    if ipro.is_surface_card(it):
        return False
    return True


def build_item(row, q):
    text = row["title"] + "。" + row.get("desc", "")
    return {
        "title": row["title"],
        "url": row["url"],
        "snippet": row.get("desc", "")[:300],
        "summary": row.get("desc", "")[:220],
        "content": text[:1500],   # 完整原文摘录（供案例综述按 6 角度归类，尽量多保留）
        "source": domain_of(row["url"]),
        "query": q,
        "date": to_iso(row.get("pub", "")),
        "region": next((r for r in REFRESH_REGIONS if r in text), "长三角"),
        "problems": extract_problems(text),
        "problem_type": dissect.infer_type(text),
        "tags": [],
    }


def load_known(intel_dir, today):
    known = set()
    db = os.path.join(intel_dir, "intel_db.jsonl")
    if os.path.exists(db):
        with open(db, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        known.add(json.loads(line).get("card_id"))
                    except Exception:
                        pass
    raw = os.path.join(intel_dir, f"raw_{today.replace('-', '')}.json")
    existing = []
    if os.path.exists(raw):
        try:
            with open(raw, "r", encoding="utf-8") as f:
                existing = json.load(f)
            for it in existing:
                known.add(ipro.card_id(it))
        except Exception:
            existing = []
    return known, existing, raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intel-dir", default=HERE)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-age-years", type=int, default=RECENCY_YEARS,
                    help=f"只保留近 N 年的材料（默认 {RECENCY_YEARS}）；更早的旧案例丢弃")
    args = ap.parse_args()

    intel_dir = args.intel_dir
    today_date = datetime.date.today()
    today = today_date.isoformat()  # 路径/文件名用字符串
    # 时效窗口（近 N 年）；--max-age-years 可临时覆盖，不改全局常量
    if args.max_age_years != RECENCY_YEARS:
        y = today_date.year - args.max_age_years
        try:
            cutoff = today_date.replace(year=y)
        except ValueError:
            cutoff = today_date.replace(year=y, month=3, day=1)
    else:
        cutoff = _cutoff_date(today_date)
    queries = build_queries()
    if args.limit:
        queries = queries[:args.limit]

    known, existing, raw_path = load_known(intel_dir, today)
    scanned, kept, new_items, source_hits, old_dropped = 0, 0, [], {}, 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for q, rows, src in ex.map(scan_one, queries):
            scanned += len(rows)
            source_hits[src] = source_hits.get(src, 0) + 1
            for row in rows:
                it = build_item(row, row.get("query", q))
                if not relevant(it):
                    continue
                if not recent_enough(it, cutoff):
                    old_dropped += 1
                    continue
                kept += 1
                cid = ipro.card_id(it)
                if cid in known:
                    continue
                known.add(cid)
                new_items.append(it)

    # 36氪补充源（通用商业资讯，按关键词过滤）
    try:
        for row in src_36kr():
            it = build_item(row, "36氪快讯")
            if relevant(it) and recent_enough(it, cutoff) and ipro.card_id(it) not in known:
                known.add(ipro.card_id(it))
                new_items.append(it)
        source_hits["36kr"] = source_hits.get("36kr", 0) + 1
    except Exception as e:
        print(f"[warn] 36氪源不可用：{type(e).__name__}")

    if new_items and not args.dry_run:
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(existing + new_items, f, ensure_ascii=False, indent=2)
        action = f"写入 {os.path.basename(raw_path)}"
    else:
        action = "dry-run" if args.dry_run else "无新增（未写文件）"

    print(f"[collect] 查询 {len(queries)} 条 · 命中网页 {scanned} 条 · 相关 {kept} 条 · 超龄丢弃 {old_dropped} 条 · 新增 {len(new_items)} 条 · {action}")
    print(f"[collect] 源命中：{source_hits}")
    print(f"[collect] 时效窗口：保留 >= {cutoff.isoformat()}（近 {RECENCY_YEARS} 年）")
    for it in new_items[:10]:
        print(f"   + [{it['problem_type']}] {it['region']} {it['title'][:44]}")
    print("__YRD_SUMMARY__ " + json.dumps(
        {"queries": len(queries), "scanned": scanned, "kept": kept, "old_dropped": old_dropped,
         "new": len(new_items), "date": today, "sources": source_hits, "action": action}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
