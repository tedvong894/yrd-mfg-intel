#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
长三角中小制造业案例情报平台 — 核心处理器（问题解剖版）
定位：搜集「问题分析类案例」→ 自动解剖（企业存在哪些问题 / 从哪些视角拆）→ 生成案例综述（摘要 + 分析 + 风险研判）。
约束：仅保留 2026 年案例；短视频脚本框架 / 底稿 / 口播稿模块已取消（2026-10）。
数据流：
  raw_YYYYMMDD.json        采集层（每日自动化 WebSearch 后写入，含 problems/problem_type）
        │ manifest.json 记录已处理文件，保证幂等
        ▼
  intel_db.jsonl          累积解剖卡（每行一张，渲染时按 date 过滤 2026）
  index.html              可视化解剖看板（GitHub Pages 入口 + 本地预览）
  dashboard.html          index.html 的同 contents 副本（本地兼容）
  daily_report.md         当日增量摘要
依赖：仅 Python 标准库 + 同目录 dissect.py（解剖引擎）
"""
import os
import sys
import json
import re
import hashlib
import glob
import datetime
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import dissect  # 自动解剖引擎

REGIONS = ["浙江", "江苏", "上海", "安徽", "长三角"]

# 已从系统中删除的问题类型：不再入库、不再渲染、不再采集
SKIP_TYPES = {"质量事故", "欠款劳资"}
SKIP_LABELS = {"质量事故 / 召回", "欠款 / 劳资纠纷"}


def is_skipped_type(item):
    """判断条目是否属于已下线的问题类型（兼容 problem_type_key / label / raw key 三种形态）。"""
    pkey = item.get("problem_type_key") or ""
    plabel = item.get("problem_type") or ""
    return pkey in SKIP_TYPES or plabel in SKIP_TYPES or plabel in SKIP_LABELS


SOURCE_WEIGHT = {
    "gov.cn": 1.0, "gov": 0.95, "xinhua": 1.0, "people": 0.9,
    "stats": 0.95, "21jingji": 0.85, "yicai": 0.85, "stcn": 0.8,
    "cls": 0.8, "36kr": 0.8, "qq.com": 0.7, "sina": 0.7,
    "toutiao": 0.6, "weixin": 0.6, "zhihu": 0.6, "douyin": 0.6,
    "hailuoshe": 0.7, "hidou": 0.65, "wenwuzx": 0.6, "xusuna": 0.6,
    "cqxyw": 0.6, "chinatradenews": 0.8, "comnews": 0.8, "sina": 0.7,
}
DEFAULT_SOURCE_WEIGHT = 0.5


# ── 工具 ──────────────────────────────────────────────
def norm_url(u):
    if not u:
        return ""
    u = u.strip().lower()
    u = re.sub(r'^https?://', '', u)
    u = re.sub(r'^www\.', '', u)
    u = re.sub(r'[?#].*$', '', u)
    return u.rstrip('/')


def norm_title(t):
    if not t:
        return ""
    t = t.strip().lower()
    t = re.sub(r'\s+', '', t)
    t = re.sub(r'[^\w\u4e00-\u9fff]', '', t)
    return t


def dedup_key(item):
    u = norm_url(item.get("url", ""))
    return "url:" + u if u else "title:" + norm_title(item.get("title", ""))


def card_id(item):
    return hashlib.md5(dedup_key(item).encode("utf-8")).hexdigest()[:10]


# ── 质量筛查（采集端与入库端共用这一份规则）─────────────────────
# 目标：只留"能进入深入分析、对中小制造老板有参考价值"的案例。
#   ① 商业广告 / 卖系统软文      ② 上市公司·资本市场财报体
#   ③ 表面事件卡（几句话讲完、无多因素拆解、无生产管理落点）
PM_DEEP_WORDS = [
    "产能利用率", "稼动率", "oee", "良率", "合格率", "返工", "报废", "不良率", "排产", "插单",
    "交期", "在制品", "半成品", "库存周转", "呆滞", "积压", "工艺", "技改", "爬坡", "成本结构",
    "供应链", "人机料法环", "质量成本", "沉没成本", "重资产", "毛利率", "净利率", "单位成本",
    "固定成本", "变动成本", "停产待料", "缺料", "断供", "台班", "人均产出", "隐性产能",
    "设备空转", "产能闲置", "产能空转", "盲目扩张", "激进扩张", "新厂投产", "产线投产",
    "降本", "提效", "精益", "诊断", "改善",
]
ANALYTIC_WORDS = [
    "成本", "库存", "采购", "供应链", "毛利", "良率", "产能利用率", "工艺", "排产", "账期",
    "应收", "商业模式", "盈利", "定价", "稼动", "质量成本", "单位成本", "固定成本", "变动成本",
    "呆滞", "积压", "在制品", "交期", "生产管理", "重资产", "沉没成本", "成本结构", "成本倒挂",
    "现金流", "资金链", "回款", "坏账", "存货", "周转天数",
]
AD_CTA = [
    "免费试用", "立即咨询", "获取报价", "在线询价", "厂家直销", "限时优惠", "优惠活动",
    "预约演示", "申请试用", "领取资料", "白皮书", "点击购买", "立即购买", "促销", "抢购",
    "扫码", "添加微信", "商务合作", "联系我们购买", "免费领取", "在线演示", "点击咨询",
    "电话咨询", "留资", "下载试用", "获取白皮书", "解决方案提供商", "获取方案", "定制方案",
]
AD_SYSTEM = [
    "mes系统", "erp系统", "mes软件", "erp软件", "工业软件", "wms系统", "aps排产",
    "数字化解决方案", "智能工厂方案", "低代码", "saas平台", "生产管理软件", "mes厂商",
    "erp厂商", "mes供应商", "erp供应商", "mes报价", "erp报价", "成本核算系统", "用友", "金蝶",
]
AD_SELL = [
    "报价", "价格", "购买", "咨询", "试用", "方案", "厂商", "销售", "定制", "多少钱", "费用",
    "报价单", "优惠", "促销", "代理", "加盟", "招商",
]
LISTED_MARK = [
    "上市公司", "a股", "主板", "创业板", "科创板", "北交所", "上交所", "深交所", "港股上市",
    "招股书", "招股说明书", "业绩预告", "业绩快报", "业绩说明会", "股东大会", "独立董事",
    "董秘", "投资者关系", "定增", "非公开发行", "可转债", "募集资金", "募投", "总市值",
    "股票代码", "证券代码", "公告编号", "上市以来", "上市首亏", "涨停", "跌停", "回购股份",
    "配股", "送转",
    # 注："ipo" 不列入——"冲刺IPO"的仍是专精特新/中小民企（正是目标读者），且这类报道
    # 常带应收/现金流/产能等可分析数据；只有"已上市"或募资动作才按资本市场内容剔除。
]
LISTED_WEAK = ["年报", "半年报", "季报", "财报", "预亏", "预减"]
LISTED_FIN = ["归母净利", "扣非", "每股收益", "每股净资产", "总资产", "净资产收益率", "毛利率为"]
# 民企口吻保护词：正文出现这些说明讲的是中小/民营/老字号，不是资本市场
LISTED_GUARD = [
    "中小企业", "中小制造", "中小厂", "民营", "民企", "专精特新", "小巨人", "老字号", "国货",
    "品牌", "工厂", "车间", "老板", "班组", "工友", "手艺", "作坊", "门店", "夫妻店",
]
# 大型企业/巨头（与"聚焦中小制造业"方向相悖）；命中需无民企口吻才剔除
BIG_MARK = [
    "千亿", "百亿", "万亿", "世界500强", "民企500强", "行业龙头", "中国首", "全球首",
    "跻身", "头部企业", "巨头", "独角兽",
]
SURFACE_TYPES = {"倒闭 / 关停", "订单流失 / 外贸下滑"}
MACRO_TAGS = {"宏观", "微利", "内卷", "行业"}


def card_text(c):
    return " ".join([c.get("title", "") or "", c.get("summary", "") or "",
                     c.get("snippet", "") or "", c.get("content", "") or ""] +
                    (c.get("problems") or []))


def is_ad_card(c):
    """明显是卖系统/卖软件的广告软文。"""
    t = card_text(c).lower()
    if any(w in t for w in AD_CTA):
        return True
    return any(s in t for s in AD_SYSTEM) and any(w in t for w in AD_SELL)


def is_listed_card(c):
    """上市公司 / 资本市场财报体（两级判定，正文提上市公司但通篇民企口吻的保留）。"""
    title = (c.get("title") or "").lower()
    t = card_text(c).lower()
    if any(m in title for m in LISTED_MARK):
        return True
    if any(w in title for w in LISTED_WEAK) and any(f in t for f in LISTED_FIN):
        return True
    return any(m in t for m in LISTED_MARK) and not any(g in t for g in LISTED_GUARD)


def is_big_card(c):
    """大型企业/巨头案例（与"聚焦中小制造业"方向相悖）。"""
    title = (c.get("title") or "").lower()
    t = card_text(c).lower()
    if not any(m in title for m in BIG_MARK):
        return False
    return not any(g in t for g in LISTED_GUARD)


def is_surface_card(c):
    """表面事件卡：篇幅单薄、无多因素拆解、无生产管理/经营分析落点。"""
    t = card_text(c).lower()
    problems = c.get("problems") or []
    summary = (c.get("summary") or "").strip()
    # 脏数据：摘要/标题带 HTML 残渣或站点后缀（非案例正文）
    if "<font" in t or "&nbsp;" in t or "&amp;" in t or "_新闻" in t or " - 中国" in t:
        return True
    pm = sum(1 for k in PM_DEEP_WORDS if k in t)
    has_pct = bool(re.search(r"[0-9]+(\.[0-9]+)?\s?%", t))
    if pm == 0 and any(k in t for k in ANALYTIC_WORDS):
        return False          # 有经营分析落点 → 保留
    ptype = c.get("problem_type") or ""
    if ptype in SURFACE_TYPES and pm == 0 and len(problems) <= 2 and not has_pct:
        return True
    if (set(c.get("tags") or []) & MACRO_TAGS) and pm == 0 and len(problems) <= 1:
        return True
    if len(summary) < 35 and pm == 0 and not has_pct:
        return True
    return False


def screen_reason(c):
    """返回剔除原因；空字符串表示通过。"""
    if is_ad_card(c):
        return "AD"
    if is_listed_card(c):
        return "LISTED"
    if is_big_card(c):
        return "BIG"
    if is_surface_card(c):
        return "SURFACE"
    return ""


def detect_region(item):
    text = item.get("title", "") + " " + item.get("snippet", "") + " " + item.get("summary", "")
    for r in ["浙江", "江苏", "上海", "安徽"]:
        if r in text:
            return r
    return "长三角" if "长三角" in text else item.get("region", "长三角")


def build_card(item):
    text = item.get("title", "") + " " + item.get("snippet", "") + " " + item.get("summary", "")
    ptype = item.get("problem_type") or dissect.infer_type(text)
    region = detect_region(item)
    script = dissect.build_script(item, ptype, region)
    return {
        "card_id": card_id(item),
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source": item.get("source", norm_url(item.get("url", "")).split("/")[0]),
        "region": region,
        "problem_type": dissect.PROBLEM_TYPES.get(ptype, dissect.PROBLEM_TYPES[dissect.DEFAULT_TYPE])["label"],
        "problem_type_key": ptype,
        "tags": item.get("tags", []),
        "summary": item.get("summary", item.get("snippet", "")),
        "content": item.get("content", ""),
        "problems": item.get("problems", []),
        "script": script,
        "query": item.get("query", ""),
        "date": item.get("date", datetime.date.today().isoformat()),
        "added": datetime.date.today().isoformat(),   # 入库日期（用于"今日新增"统计，区别于文章发布时间）
    }


# ── 主流程 ────────────────────────────────────────────
def load_manifest(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"processed": []}
    return {"processed": []}


def load_db_keys(db_path):
    keys = set()
    if os.path.exists(db_path):
        with open(db_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    keys.add(json.loads(line).get("card_id"))
                except Exception:
                    continue
    return keys


def process(intel_dir):
    os.makedirs(intel_dir, exist_ok=True)
    manifest_path = os.path.join(intel_dir, "manifest.json")
    db_path = os.path.join(intel_dir, "intel_db.jsonl")

    manifest = load_manifest(manifest_path)
    processed = set(manifest.get("processed", []))
    existing_keys = load_db_keys(db_path)
    # 主动剔除的表面/简单案例黑名单（与 push_pages/sync_cloud 共用），保证渲染与入库都排除。
    del_path = os.path.join(intel_dir, "deleted_ids.json")
    deleted_keys = set()
    if os.path.exists(del_path):
        try:
            deleted_keys = set(json.load(open(del_path, encoding="utf-8")))
        except Exception:
            deleted_keys = set()
    existing_keys |= deleted_keys

    raw_files = sorted(glob.glob(os.path.join(intel_dir, "raw_*.json")))
    new_items = []
    for rf in raw_files:
        base = os.path.basename(rf)
        # 注意：按「条目 card_id」去重，而不是按文件名跳过——
        # 同名 raw 文件会被增量采集不断追加，按文件名跳过会导致新条目永远不入库。
        try:
            with open(rf, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[warn] 跳过无法解析的 {base}: {e}")
            continue
        items = data if isinstance(data, list) else data.get("items", [])
        added = 0
        skipped = 0
        screened = 0
        for it in items:
            if is_skipped_type(it):
                skipped += 1
                continue
            cid = card_id(it)
            if cid in existing_keys:
                continue
            card = build_card(it)
            # 质量闸门：广告 / 上市公司财报体 / 表面事件卡 一律不入库
            reason = screen_reason(card)
            if reason:
                screened += 1
                existing_keys.add(cid)
                continue
            new_items.append(card)
            existing_keys.add(cid)
            added += 1
        processed.add(base)
        print(f"[ok] {base}: 解析 {len(items)} 条，新增 {added} 条，"
              f"跳过已下线类型 {skipped} 条，质量筛除 {screened} 条")

    if new_items:
        with open(db_path, "a", encoding="utf-8") as f:
            for c in new_items:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
    else:
        print("[info] 无新增情报，仅重新渲染看板。")

    manifest["processed"] = sorted(processed)
    manifest["last_run"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    all_cards = []
    with open(db_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    all_cards.append(json.loads(line))
                except Exception:
                    continue

    # 仅保留 2026 年案例（按文章发布日期 date 过滤；无日期或非 2026 一律剔除）
    all_cards = [c for c in all_cards
                 if str(c.get("date", "")).startswith("2026")
                 and c.get("card_id") not in deleted_keys]

    today = datetime.date.today().isoformat()
    # "今日新增"按入库日期统计（增量采集会把旧文章也新增进来）
    today_cards = [c for c in all_cards if c.get("added", c.get("date")) == today]

    render_dashboard(intel_dir, all_cards, today_cards, today)
    render_daily_report(intel_dir, today_cards, today)
    print(f"[done] 总解剖卡 {len(all_cards)} 张，今日新增 {len(today_cards)} 张")
    return len(all_cards), len(today_cards)


# ── 渲染 ──────────────────────────────────────────────
PT_COLORS = {
    "倒闭关停": "#dc2626", "亏损": "#ea580c", "订单流失": "#d97706",
    "转型失败": "#7c3aed", "库存积压": "#0891b2", "现金流断裂": "#b91c1c",
}
REG_COLORS = {"浙江": "#dc2626", "江苏": "#16a34a", "上海": "#2563eb",
              "安徽": "#d97706", "长三角": "#7c3aed"}


def bar(label, value, maxv, color, clickable=False, data_pt=""):
    pct = (value / maxv * 100) if maxv else 0
    cls = "row clickable" if clickable else "row"
    attr = f' data-pt="{data_pt}"' if clickable else ""
    return (f'<div class="{cls}"{attr}><span class="rk">{label}</span>'
            f'<span class="barwrap"><span class="bar" style="width:{pct:.1f}%;background:{color}"></span></span>'
            f'<span class="val">{value}</span></div>')


def render_workshop(intel_dir):
    """读取 workshop/index.json，渲染「短视频工坊」区块。与情报采集解耦：文件不在就静默跳过。"""
    idx_path = os.path.join(intel_dir, "workshop", "index.json")
    if not os.path.exists(idx_path):
        return "", {}
    try:
        with open(idx_path, "r", encoding="utf-8") as f:
            idx = json.load(f)
    except Exception:
        return "", {}

    items = idx.get("items", [])
    if not items:
        return "", {}

    PREVIEW_ROWS = 14
    script_map = {}
    kw_map = {}
    cards_html = []

    for it in items:
        cid = it.get("card_id", "")
        pcolor = PT_COLORS.get(it.get("problem_type_key"), "#6b7280")
        rows = it.get("beats", [])

        # 五段式口播文案（合并连续同段名，供人直接读 / 复制）
        seg_lines, last_seg = [], None
        for r in rows:
            if r["段落"] != last_seg:
                seg_lines.append([r["段落"], [r["口播文案"]]])
                last_seg = r["段落"]
            else:
                seg_lines[-1][1].append(r["口播文案"])
        seg_html = "".join(
            f'<div class="wseg"><span class="wsegtag">{s}</span>'
            f'<span class="wsegtxt">{"，".join(txts)}</span></div>'
            for s, txts in seg_lines)
        script_map[cid] = "".join(t + "。" for _, txts in seg_lines for t in ["，".join(txts)])

        # 素材采集单（可勾选）：机器出清单，人去挑素材。勾选进度存在浏览器本地。
        mats = it.get("materials", [])
        kw_lines = []
        mrows = []
        for m in mats:
            layer = m.get("层级", "")
            lc = "l1" if layer.startswith("L1") else ("l2" if layer.startswith("L2") else "l3")
            if layer.startswith("L2"):
                kw_lines.append(f'{m.get("场景","")}: {m.get("怎么做","")}')
            cover = f'镜次 {m["覆盖镜次"]}' if m.get("覆盖镜次") else "全程备用"
            mrows.append(
                f'<label class="mrow" data-n="{m.get("序号","")}">'
                f'<input type="checkbox" onchange="wsToggle(this)">'
                f'<div class="mmain">'
                f'<div class="mhead"><span class="mtag {lc}">{layer}</span>'
                f'<span class="mscene">{m.get("场景","")}</span>'
                f'<span class="mcover">{cover}</span></div>'
                f'<div class="mline"><b>怎么做</b>{m.get("怎么做","")}</div>'
                f'<div class="mline"><b>去哪找</b>{m.get("去哪找","")}</div>'
                f'<div class="mline"><b>备注</b>{m.get("备注","")}</div>'
                f'</div><span class="mqty">{m.get("要几条","")} 条</span></label>')
        kw_map[cid] = "\n".join(kw_lines)
        mats_html = f'''
  <details class="wdet wmats" data-cid="{cid}"><summary>素材采集单 · {len(mats)} 条（找完打勾，进度自动存）</summary>
    <div class="wmah"><span class="wmt">照着办 → 先从浅黄的 L1 开始（自己拍 / 自己出图）</span>
      <span class="wmprog">0 / {len(mats)} 条已办</span></div>
    <div class="mrows">{"".join(mrows)}</div>
    <div class="mfoot"><button class="wbtn" onclick="wsCopyKw('{cid}', this)">复制检索词（{len(kw_lines)} 组）</button>
      <span class="wtools-hint">粘到 Pexels / Pixabay 逐个搜；一次下满 30-50 条再动剪</span></div>
  </details>'''

        # 镜次表预览
        trs = "".join(
            f'<tr><td class="c">{r["镜次"]}</td><td class="c">{r["起"]}</td><td class="c">{r["止"]}</td>'
            f'<td class="c">{r["时长"]}</td><td class="l">{r["口播文案"]}</td><td class="c">{r["节奏/情绪"]}</td>'
            f'<td class="c">{r["画面类型"]}</td><td class="l sm">{r["画面素材"]}</td>'
            f'<td class="l sm">{r["字幕/图示"]}</td><td class="c sm">{r["音效"]}</td>'
            f'<td class="c sm">{r["BGM段"]}</td><td class="c">{r["转场"]}</td></tr>'
            for r in rows[:PREVIEW_ROWS])

        dl = (f'<a class="wbtn primary" href="workshop/{it["file"]}" '
              f'download="{it["dl_name"]}">⬇ 下载剪辑底稿 .xlsx</a>') if it.get("file") else \
             '<span class="wbtn disabled">底稿生成中</span>'

        cards_html.append(f"""
<div class="wcard" id="ws-{cid}">
  <div class="whead">
    <span class="pt" style="background:{pcolor}">{it.get('problem_type','')}</span>
    <span class="wmeta">{it.get('region','')} · ★{it.get('score',0)} · {it.get('shots',0)} 镜 · {it.get('duration',0)} 秒</span>
  </div>
  <a class="wtitle" href="{it.get('url','#')}" target="_blank" rel="noopener">{it.get('title','')}</a>
  <div class="wsegs">{seg_html}</div>
  <details class="wdet"><summary>镜次表预览（前 {min(PREVIEW_ROWS, len(rows))} 镜 / 共 {len(rows)} 镜）</summary>
    <div class="wtablewrap"><table class="wtable"><thead><tr>
      <th>镜次</th><th>起</th><th>止</th><th>时长</th><th>口播文案</th><th>节奏</th><th>画面类型</th>
      <th>画面素材（待挑）</th><th>字幕/图示</th><th>音效</th><th>BGM</th><th>转场</th>
    </tr></thead><tbody>{trs}</tbody></table></div>
    <div class="wnote">完整 {len(rows)} 镜请看下载的底稿文件（含素材采集单 + 节奏与声音标准）。</div>
  </details>
  {mats_html}
  <div class="wbtns">
    {dl}
    <button class="wbtn" onclick="copyScript('{cid}', this)">复制口播文案</button>
  </div>
</div>""")

    html = f"""
<div class="section" id="sec-workshop"><h2>🎬 短视频工坊 · 解剖卡 → 可直接开剪的底稿（{len(items)} 张）</h2>
  <div class="wlead">机器负责「文案 + 底稿 + 素材采集单」，人负责「画面 + 声音」——这条线就是标准化的边界。<br>
  每张底稿 = 五段式口播文案 + 12 列剪辑底稿（镜次/时间码/口播/节奏/画面类型/素材建议/字幕/音效/BGM/转场）+ <b>素材采集单（可勾选）</b> + 节奏与声音标准。
  采集单按 <b>L1 自己拍/自己出图 → L2 免费站下载 → L3 AI 兜底</b> 分好层，每条都写明覆盖哪几个镜次、要几条、去哪找；找完打勾，进度存在本机浏览器里。</div>
  <div class="wtools">
    <a class="wbtn" href="workshop-template.xlsx" download="剪辑底稿模板.xlsx">⬇ 空白模板</a>
    <a class="wbtn" href="video-SOP.md" target="_blank" rel="noopener">📄 完整 SOP</a>
    <span class="wtools-hint">底稿随云端采集自动更新，只对内容价值最高的 {len(items)} 张生成</span>
  </div>
  <div class="wgrid">{''.join(cards_html)}</div>
</div>"""

    return html, script_map, kw_map


# 案例综述的 6 个整理方向（与搜集方向一致）+ 每个方向的原文命中关键词。
# 仅用关键词把「原文句子」归入对应方向，保留原句、不做改写评价；无命中的句子丢弃（多为套话/导流语）。
REVIEW_ANGLES = [
    ("经营状况变化", ["营收", "营业收入", "销售额", "利润", "盈利", "亏损", "由盈转亏", "业绩", "毛利",
                  "净利", "增收不增利", "下滑", "暴跌", "增长", "订单", "开工", "产能利用率", "停工", "半停"]),
    ("扩产与设备投资", ["扩产", "扩建", "投产", "新建", "产线", "生产线", "设备", "投资", "技改", "产能",
                   "智能化", "数字化", "自动化", "机器换人", "厂房", "用地", "重资产"]),
    ("应收账款与资金压力", ["应收", "账款", "账期", "回款", "坏账", "资金", "现金流", "融资", "贷款", "借款",
                    "负债", "债务", "垫资", "抵押", "资金链", "欠款", "拖欠", "断供", "发不出工资"]),
    ("库存和成本管理", ["库存", "存货", "呆滞", "积压", "成本", "原料", "原材料", "采购", "损耗", "仓储",
                   "涨价", "降价", "价格", "用工", "人工", "工资"]),
    ("企业转型与经营决策", ["转型", "升级", "跨境", "电商", "内销", "转内", "多元化", "收缩", "剥离", "战略",
                    "布局", "决策", "裁员", "关停", "搬迁", "出海", "并购", "外迁"]),
    ("企业经营困难的原因", ["困难", "困境", "原因", "倒闭", "破产", "清算", "重整", "危机", "风险", "内卷",
                    "竞争", "需求", "寒冬", "疲软", "压力", "夹击"]),
]


def _classify_sentence(s):
    """句子 → 命中关键词最多的方向；无命中返回 None。"""
    best, best_n = None, 0
    for name, kws in REVIEW_ANGLES:
        n = sum(1 for k in kws if k in s)
        if n > best_n:
            best, best_n = name, n
    return best


def _add_unique(bucket, s):
    """按包含关系去重：新句是已有句的子串、或已有句是新句的子串，都不重复加。"""
    for x in bucket:
        if s in x or x in s:
            return
    bucket.append(s)


def build_review(c):
    """案例综述：把原素材句子按 6 个搜集方向归类展示，只保留原文内容、不做归因评价。
    素材池：content（采集层完整摘录，新卡才有）优先；旧卡退回 summary；problems 始终并入。"""
    content = (c.get("content") or "").strip()
    if content:
        pool = [s.strip() for s in re.split(r"[。；;！!？?\n]", content) if len(s.strip()) >= 8]
    else:
        summary = (c.get("summary", "") or "").strip()
        pool = [s.strip() for s in re.split(r"[。；;！!？?\n]", summary) if len(s.strip()) >= 8]

    for p in c.get("problems", []) or []:
        p = p.strip()
        if p and p not in pool:
            pool.append(p)

    buckets = {name: [] for name, _ in REVIEW_ANGLES}
    for s in pool:
        if len(s) > 110:
            s = s[:110] + "…"
        name = _classify_sentence(s)
        if name:
            _add_unique(buckets[name], s)

    secs = []
    for name, _ in REVIEW_ANGLES:
        items = buckets[name][:8]
        if not items:
            continue
        lis = "".join(f"<li>{x}</li>" for x in items)
        secs.append(f'<div class="rev-sec"><b>{name}</b></div><ul class="rev-list">{lis}</ul>')
    if not secs:
        secs.append('<div class="rev-list">（原文未提取到可用要点，可点击标题查看原文）</div>')
    return ('<div class="blk review"><div class="blkh">案例综述</div>' + "".join(secs) + "</div>")


# 涉事公司背景字段顺序与中文标签（公开渠道检索填充，无则留空）
BG_FIELDS = [
    ("company", "公司名称"),
    ("location", "所在地"),
    ("scale", "企业规模"),
    ("employees", "员工数量"),
    ("founded", "经营年限"),
    ("products", "主营产品"),
    ("revenue", "营收规模"),
]


def render_company_bg(bg):
    """渲染「涉事公司背景」块。bg 为 dict，字段无值则跳过；全空显示占位说明。
    支持结构化字段（company/location/scale/employees/founded/products/revenue）
    与自由文本 text（叙事式背景）；sources 为来源链接列表（可空）。"""
    if not isinstance(bg, dict):
        bg = {}
    rows = []
    for key, label in BG_FIELDS:
        val = (bg.get(key) or "").strip()
        if val:
            rows.append(f'<div class="bgrow"><span class="bgl">{label}</span><span class="bgv">{val}</span></div>')
    text = (bg.get("text") or "").strip()
    if text:
        rows.append(f'<div class="bgtext">{text}</div>')
    srcs = bg.get("sources") or []
    if isinstance(srcs, list) and srcs:
        links = "".join(
            f'<a class="bgsrc" href="{s}" target="_blank" rel="noopener">来源</a>' for s in srcs[:3] if s)
        if links:
            rows.append(f'<div class="bgrow"><span class="bgl">信息来源</span><span class="bgv">{links}</span></div>')
    if not rows:
        return ""   # 没有背景信息就不渲染该板块，避免占视线
    return '<div class="blk bgblk"><div class="blkh">涉事公司背景</div>' + "".join(rows) + '</div>'


def render_dashboard(intel_dir, cards, today_cards, today):
    pt_counter = Counter(c.get("problem_type", "其他") for c in cards)

    pt_max = max(pt_counter.values()) if pt_counter else 1
    pt_html = "".join(bar(p, n, pt_max, PT_COLORS.get(p, "#6b7280"), clickable=True, data_pt=p)
                      for p, n in sorted(pt_counter.items(), key=lambda x: x[1], reverse=True))

    # 按月份分组（月度时间分类，可折叠）——取入库日期 added（无则文章 date），格式 YYYY-MM
    month_groups = {}
    for c in cards:
        d = c.get("added", c.get("date", ""))
        m = d[:7] if len(d) >= 7 else "未知月份"
        month_groups.setdefault(m, []).append(c)
    months_sorted = sorted(month_groups.keys(), reverse=True)  # 最新月在前
    if months_sorted:
        items = []
        for m in months_sorted:
            grp = sorted(month_groups[m], key=lambda x: x.get("date", ""), reverse=True)
            rows = "".join(
                f'<div class="mrow2"><span class="mtag2" style="background:{PT_COLORS.get(x.get("problem_type"),"#6b7280")}">{x.get("problem_type","")}</span>'
                f'<a class="mtitle" href="#dc-{x.get("card_id","")}" onclick="scrollToDc(event,this)">{x.get("title","")}</a>'
                f'<span class="mdate">{x.get("date","")}</span></div>'
                for x in grp)
            items.append(
                f'<details class="wdet wmonth"><summary>{m} · {len(grp)} 张</summary>'
                f'<div class="mrows2">{rows}</div></details>')
        month_html = "".join(items)
    else:
        month_html = ""

    # 短视频工坊已取消（2026-10）：不再渲染底稿 / 口播模块
    workshop_html = ""

    def dissect_block(c):
        pcolor = PT_COLORS.get(c.get("problem_type"), "#6b7280")
        cid = c.get("card_id", "")
        bg = render_company_bg(c.get("company_bg"))
        return f"""
<div class="dcard" id="dc-{cid}" data-pt="{c.get('problem_type','')}" data-date="{c.get('added', c.get('date',''))}">
  <div class="dcard-head">
    <span class="pt" style="background:{pcolor}">{c.get('problem_type','')}</span>
    <span class="dctrls">
      <button class="dfav" type="button" onclick="favCard('{cid}')" title="收藏此案例（仅本浏览器标记）">☆</button>
      <button class="ddel" type="button" onclick="delCard('{cid}')" title="删除此案例（仅本浏览器隐藏）">✕</button>
    </span>
  </div>
  <a class="dtitle" href="{c.get('url','#')}" target="_blank" rel="noopener">{c.get('title','')}</a>
  <div class="dmeta">{c.get('region','')} · {c.get('source','')} · {c.get('date','')}</div>
  <div class="dsum">{c.get('summary','')}</div>
  {bg}
  {build_review(c)}
</div>"""

    # 解剖卡全量渲染（供筛选），按文章发布日期降序
    dissect_all = sorted(cards, key=lambda x: x.get("date", ""), reverse=True)
    dissect_html = "".join(dissect_block(c) for c in dissect_all) or '<div class="empty">暂无数据</div>'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>长三角制造业·问题解剖情报平台</title>
<link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png">
<link rel="icon" type="image/png" sizes="192x192" href="icon-192.png">
<link rel="manifest" href="manifest.webmanifest">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="制造业情报">
<meta name="theme-color" content="#0f172a">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f5f7fa;color:#1f2937;padding:24px;line-height:1.55}}
.wrap{{max-width:1180px;margin:0 auto}}
header{{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:22px 26px;margin-bottom:18px}}
header h1{{font-size:22px;font-weight:700}}
header .sub{{color:#6b7280;font-size:13px;margin-top:6px}}
.stats{{display:flex;gap:12px;margin-top:16px;flex-wrap:wrap}}
.stat{{flex:1;min-width:120px;background:#f8fafc;border:1px solid #e5e7eb;border-radius:10px;padding:14px;cursor:pointer;transition:.15s}}
.stat:hover{{border-color:#dc2626;box-shadow:0 2px 10px rgba(220,38,38,.08)}}
.stat.favon{{border-color:#e3c25a;background:#fffdf4}}
.stat .n{{font-size:24px;font-weight:700;color:#111827}}
.stat .l{{font-size:12px;color:#6b7280;margin-top:4px}}
.section{{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:20px 24px;margin-bottom:18px;scroll-margin-top:16px}}
.section h2{{font-size:16px;font-weight:700;margin-bottom:14px;display:flex;align-items:center;gap:8px}}
.section h2::before{{content:"";width:4px;height:16px;background:#dc2626;border-radius:2px;display:inline-block}}
.row{{display:flex;align-items:center;gap:10px;margin:7px 0;font-size:13px}}
.row.clickable{{cursor:pointer;border-radius:6px;padding:2px 4px;transition:.15s}}
.row.clickable:hover{{background:#fef2f2}}
.rk{{width:120px;color:#374151;flex-shrink:0}}
.barwrap{{flex:1;background:#eef2f7;border-radius:6px;height:14px;overflow:hidden}}
.bar{{display:block;height:100%;border-radius:6px}}
.val{{width:36px;text-align:right;color:#6b7280}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{text-align:left;padding:9px 8px;border-bottom:1px solid #f0f2f5}}
th{{color:#6b7280;font-weight:600;font-size:12px}}
.pill{{color:#fff;font-size:11px;padding:2px 8px;border-radius:20px}}
.dissect-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:16px}}
.dcard{{background:#f8fafc;border:1px solid #e5e7eb;border-radius:12px;padding:18px;display:flex;flex-direction:column;gap:10px}}
.dcard-head{{display:flex;justify-content:flex-start;align-items:center;gap:10px}}
.pt{{color:#fff;font-size:12px;font-weight:600;padding:3px 10px;border-radius:20px;white-space:nowrap}}
.dtitle{{font-size:15px;font-weight:600;color:#111827;text-decoration:none;line-height:1.4}}
.dtitle:hover{{text-decoration:underline}}
.dmeta{{font-size:11px;color:#9ca3af}}
.dsum{{font-size:12px;color:#4b5563;line-height:1.5}}
.blk{{background:#fff;border:1px solid #eef2f7;border-radius:8px;padding:10px 12px}}
.blkh{{font-size:12px;font-weight:700;color:#374151;margin-bottom:6px}}
.iss,.ang,.pts{{margin:0;padding-left:18px;font-size:12px;color:#4b5563;line-height:1.6}}
.script{{border-color:#fde68a;background:#fffdf5}}
.sh{{font-size:12px;color:#92400e;font-weight:600;margin-bottom:4px}}
.se{{font-size:12px;color:#15803d;font-weight:600;margin-top:4px}}
.smeta{{font-size:11px;color:#9ca3af;margin-top:6px}}
/* ── 案例综述 ── */
.review{{border-color:#e0e7ff;background:#f8faff}}
.rev-gist{{font-size:12.5px;color:#374151;line-height:1.7;margin-bottom:8px}}
.rev-sec{{font-size:12.5px;color:#4b5563;line-height:1.7;margin-top:6px}}
.rev-sec b{{color:#1f2937}}
.rev-list{{margin:6px 0 0 18px;padding-left:18px;font-size:12.5px;color:#4b5563;line-height:1.7}}
/* ── 涉事公司背景 ── */
.bgblk{{border-color:#e7f0e9;background:#f6fbf7}}
.bgrow{{display:flex;gap:8px;font-size:12px;line-height:1.6;margin:3px 0}}
.bgl{{flex-shrink:0;width:62px;color:#6b7280;font-weight:600}}
.bgv{{color:#374151;word-break:break-word}}
.bgnone{{font-size:12px;color:#9ca3af;line-height:1.6}}
.bgsrc{{color:#2f5597;text-decoration:none;font-weight:600;margin-right:8px}}
.bgsrc:hover{{text-decoration:underline}}
/* ── 卡片收藏 / 删除复合键 ── */
.dctrls{{display:flex;align-items:center;gap:6px;flex-shrink:0}}
.dfav{{border:1px solid #d9e2ef;background:#f4f8fd;color:#2f5597;width:26px;height:26px;border-radius:6px;font-size:14px;line-height:1;cursor:pointer;font-family:inherit;transition:.15s;flex-shrink:0}}
.dfav:hover{{background:#e7f0fa;border-color:#c2d4ea}}
.dfav:active{{transform:translateY(1px)}}
.dfav.on{{color:#e6a700;border-color:#f0d68a;background:#fff9ec}}
.dcard.faved{{border-color:#f0d68a;box-shadow:0 0 0 2px rgba(230,167,0,.10)}}
/* ── 卡片删除按钮 ── */
.ddel{{border:1px solid #f0c9c9;background:#fff5f5;color:#c0392b;width:26px;height:26px;border-radius:6px;font-size:14px;line-height:1;cursor:pointer;font-family:inherit;transition:.15s;flex-shrink:0}}
.ddel:hover{{background:#fdeaea;border-color:#e3a3a3}}
.ddel:active{{transform:translateY(1px)}}
.filterbar{{display:none;align-items:center;gap:10px;background:#fff7ed;border:1px solid #fed7aa;border-radius:10px;padding:10px 14px;margin-bottom:14px;font-size:13px}}
.filterbar.show{{display:flex}}
.filterbar .ftxt{{color:#9a3412;font-weight:600}}
.filterbar .clear{{margin-left:auto;color:#dc2626;cursor:pointer;font-weight:600;text-decoration:underline}}
footer{{text-align:center;color:#9ca3af;font-size:12px;padding:10px}}
.empty{{color:#9ca3af;font-size:13px}}
.refbar{{display:flex;align-items:center;gap:12px;margin-top:12px;flex-wrap:wrap}}
.refbtn{{height:32px;padding:0 14px;border:1px solid #e5e7eb;border-radius:8px;background:#fafafa;color:#4b5563;font-size:13px;font-weight:500;cursor:pointer;transition:.15s;font-family:inherit}}
.refbtn:hover{{background:#f1f3f5;border-color:#d8dde3;color:#374151}}
.refbtn:active{{transform:translateY(1px)}}
.refbtn:disabled{{background:#fafafa;color:#b6bcc4;border-color:#eceef1;cursor:default}}
.refstatus{{font-size:12px;color:#9ca3af;flex:1;min-width:220px}}
.refstatus.err{{color:#c2603c;font-weight:500}}
.refstatus.ok{{color:#5c8a6a;font-weight:500}}
/* ── 短视频工坊 ── */
.wlead{{font-size:12.5px;color:#6b7280;line-height:1.7;background:#f8fafc;border:1px solid #eef2f7;border-radius:10px;padding:12px 14px;margin-bottom:14px}}
.wtools{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:16px}}
.wtools-hint{{font-size:11.5px;color:#9ca3af}}
.wgrid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(430px,1fr));gap:16px}}
.wcard{{background:#f8fafc;border:1px solid #e5e7eb;border-radius:12px;padding:15px;display:flex;flex-direction:column;gap:9px}}
.whead{{display:flex;justify-content:space-between;align-items:center;gap:8px}}
.wmeta{{font-size:11.5px;color:#9ca3af}}
.wtitle{{font-size:14.5px;font-weight:600;color:#111827;text-decoration:none;line-height:1.45}}
.wtitle:hover{{text-decoration:underline}}
.wsegs{{background:#fff;border:1px solid #fde68a;border-radius:8px;padding:10px 12px;display:flex;flex-direction:column;gap:6px}}
.wseg{{display:flex;gap:8px;font-size:12.5px;line-height:1.65;align-items:flex-start}}
.wsegtag{{flex-shrink:0;font-size:11px;color:#92400e;background:#fef3c7;border-radius:4px;padding:1px 6px;margin-top:1px}}
.wsegtxt{{color:#374151}}
.wdet{{font-size:12.5px;color:#4b5563}}
.wdet summary{{cursor:pointer;color:#2f5597;font-weight:600;padding:4px 0;outline:none}}
.wtablewrap{{overflow-x:auto;margin-top:8px;border:1px solid #eef2f7;border-radius:8px;background:#fff}}
.wtable{{width:100%;border-collapse:collapse;font-size:11.5px;min-width:1000px}}
.wtable th{{background:#f1f5f9;color:#64748b;font-weight:600;font-size:11px;padding:6px 7px;white-space:nowrap;text-align:left;border-bottom:1px solid #e5e7eb}}
.wtable td{{padding:6px 7px;border-bottom:1px solid #f4f6f9;color:#374151;vertical-align:top}}
.wtable td.c{{text-align:center;white-space:nowrap}}
.wtable td.l{{line-height:1.5}}
.wtable td.sm{{color:#6b7280;font-size:11px}}
.wtable tbody tr:nth-child(-n+2){{background:#fbfcfe}}
.wnote{{font-size:11.5px;color:#9ca3af;margin-top:8px}}
.wbtns{{display:flex;gap:8px;flex-wrap:wrap;margin-top:2px}}
.wbtn{{display:inline-flex;align-items:center;height:30px;padding:0 12px;border:1px solid #e5e7eb;border-radius:8px;background:#fafafa;color:#4b5563;font-size:12.5px;font-weight:500;cursor:pointer;text-decoration:none;font-family:inherit;transition:.15s}}
.wbtn:hover{{background:#f1f3f5;border-color:#d8dde3;color:#374151}}
.wbtn:active{{transform:translateY(1px)}}
.wbtn.primary{{background:#eef4fb;border-color:#cfe0f2;color:#2f5597}}
.wbtn.primary:hover{{background:#e6effa}}
.wbtn.disabled{{color:#b6bcc4;border-color:#eceef1;cursor:default}}
.wlink{{color:#2f5597;text-decoration:none;font-weight:600}}
.wlink:hover{{text-decoration:underline}}
.wcard:target{{border-color:#cfe0f2;box-shadow:0 0 0 3px rgba(47,85,151,.09)}}
.wmats{{border:1px solid #e8eef6;border-radius:10px;background:#fff;padding:11px 13px}}
.wmats summary{{color:#2f5597}}
.wmah{{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;
 margin:6px 0 2px;padding-bottom:7px;border-bottom:1px solid #eef2f7}}
.wmt{{font-size:12px;color:#6b7280}}
.wmprog{{font-size:11.5px;color:#2f5597;font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap}}
.mrows{{display:flex;flex-direction:column}}
.mrow{{display:grid;grid-template-columns:auto 1fr auto;gap:9px;padding:9px 4px;border-top:1px solid #f6f8fb;
 cursor:pointer;align-items:start}}
.mrow:first-child{{border-top:none}}
.mrow:hover{{background:#fbfcfe}}
.mrow input{{margin:2px 0 0;width:15px;height:15px;accent-color:#2f5597;cursor:pointer;flex:none}}
.mrow.done .mscene{{text-decoration:line-through;color:#b6bcc4}}
.mrow.done .mline,.mrow.done .mcover,.mrow.done .mqty{{opacity:.45}}
.mmain{{min-width:0;display:flex;flex-direction:column;gap:2px}}
.mhead{{display:flex;align-items:baseline;gap:7px;flex-wrap:wrap}}
.mscene{{font-size:12.5px;font-weight:600;color:#374151;line-height:1.45}}
.mcover{{font-size:11px;color:#9ca3af;white-space:nowrap}}
.mline{{font-size:11.5px;color:#6b7280;line-height:1.6;word-break:break-word}}
.mline b{{color:#4b5563;font-weight:600;margin-right:6px}}
.mqty{{font-size:11.5px;color:#9ca3af;white-space:nowrap;padding-top:1px}}
.mtag{{font-size:10.5px;border-radius:4px;padding:1px 6px;white-space:nowrap;font-weight:600}}
.mtag.l1{{background:#fef3c7;color:#92400e}}
.mtag.l2{{background:#eef4fb;color:#2f5597}}
.mtag.l3{{background:#f3f4f6;color:#6b7280}}
.mfoot{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:9px;padding-top:9px;border-top:1px solid #eef2f7}}
.wmonth{{margin:6px 0;border:1px solid #e8eef6;border-radius:10px;background:#fff;padding:9px 14px}}
.wmonth summary{{color:#2f5597;font-weight:600;cursor:pointer;outline:none;font-size:13.5px}}
.mrows2{{margin-top:8px;display:flex;flex-direction:column}}
.mrow2{{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center;padding:6px 2px;border-top:1px solid #f6f8fb;font-size:12.5px}}
.mrow2:first-child{{border-top:none}}
.mtag2{{color:#fff;font-size:10.5px;padding:1px 7px;border-radius:20px;white-space:nowrap}}
.mtitle{{color:#374151;text-decoration:none;line-height:1.45}}
.mtitle:hover{{color:#2f5597;text-decoration:underline}}
.mdate{{font-size:11px;color:#9ca3af;white-space:nowrap;font-variant-numeric:tabular-nums}}
.dcard.flash{{box-shadow:0 0 0 3px rgba(220,38,38,.18);border-color:#fca5a5;transition:.2s}}
@media(max-width:560px){{.mrow{{grid-template-columns:auto 1fr}}.mqty{{grid-column:2;padding-top:2px}}}}
</style></head>
<body><div class="wrap">
<header>
  <h1>长三角制造业 · 问题解剖情报平台</h1>
  <div class="sub">公开网络采集问题企业案例 → 原文要点按 6 个经营角度整理 · 更新于 {today}</div>
  <div class="stats">
    <div class="stat" onclick="goDissect('all')"><div class="n">{len(cards)}</div><div class="l">累积解剖卡</div></div>
    <div class="stat" onclick="goDissect('today')"><div class="n">{len(today_cards)}</div><div class="l">今日新增</div></div>
    <div class="stat" onclick="goTypes()"><div class="n">{len(pt_counter)}</div><div class="l">问题类型</div></div>
    <div class="stat" id="favstat" onclick="goFavOnly()"><div class="n" id="favstatn">0</div><div class="l">我的收藏</div></div>
  </div>
  <div class="refbar">
    <button id="refbtn" class="refbtn" onclick="doRefresh()">刷新</button>
    <span id="refstatus" class="refstatus">每日 08:10 云端自动采集；也可点左侧按钮随时增量搜索（只加新案例）</span>
  </div>
</header>

<div class="filterbar" id="filterbar">
  <span class="ftxt" id="filtertxt"></span>
  <span class="clear" onclick="clearFilter()">清除筛选</span>
</div>

<div class="section" id="sec-types"><h2>问题类型分布（点击柱状条可筛选下方解剖卡）</h2>{pt_html or '<div class="empty">暂无数据</div>'}</div>
<div class="section" id="sec-months"><h2>按时间分类 · 月度（点击月份展开，共 {len(months_sorted)} 个月）</h2>{month_html or '<div class="empty">暂无数据</div>'}</div>

<div class="section" id="sec-dissect"><h2>自动解剖卡（全部 {len(cards)} 张，可筛选）</h2>
<div class="dissect-grid">{dissect_html}</div></div>

<footer>由 intel_processor.py + dissect.py 自动生成 · 数据源：公开网络 WebSearch · 仅作制造业案例研究参考</footer>
</div>
<script>
var TODAY = "{today}";
/* ── 卡片删除（仅本浏览器 localStorage 隐藏，不改源数据）── */
var DEL_KEY = "yrd_deleted_cards";
function getDel(){{ try{{ return JSON.parse(localStorage.getItem(DEL_KEY) || "[]"); }}catch(e){{ return []; }} }}
function saveDel(a){{ localStorage.setItem(DEL_KEY, JSON.stringify(a)); }}
function delCard(cid){{
  var a = getDel(); if(a.indexOf(cid) < 0) a.push(cid); saveDel(a);
  var el = document.getElementById("dc-" + cid); if(el) el.style.display = "none";
}}
function applyDel(){{
  getDel().forEach(function(cid){{ var el = document.getElementById("dc-" + cid); if(el) el.style.display = "none"; }});
}}
/* ── 卡片收藏（仅本浏览器 localStorage 标记，不改源数据）── */
var FAV_KEY = "yrd_fav_cards";
function getFav(){{ try{{ return JSON.parse(localStorage.getItem(FAV_KEY) || "[]"); }}catch(e){{ return []; }} }}
function saveFav(a){{ localStorage.setItem(FAV_KEY, JSON.stringify(a)); }}
function favCard(cid){{
  var a = getFav(), i = a.indexOf(cid);
  var el = document.getElementById("dc-" + cid), b = el ? el.querySelector(".dfav") : null;
  if(i < 0){{ a.push(cid); if(el) el.classList.add("faved"); if(b){{ b.textContent = "★"; b.classList.add("on"); }} }}
  else {{ a.splice(i,1); if(el) el.classList.remove("faved"); if(b){{ b.textContent = "☆"; b.classList.remove("on"); }} }}
  saveFav(a); updFavStat();
}}
var FAV_ONLY=false;
function resetFavOnly(){{ FAV_ONLY=false; var s=document.getElementById("favstat"); if(s) s.classList.remove("favon"); }}
function goFavOnly(){{
  FAV_ONLY=!FAV_ONLY;
  var s=document.getElementById("favstat");
  if(s) s.classList.toggle("favon",FAV_ONLY);
  var n=FAV_ONLY?applyFilter({{favOnly:true}}):applyFilter({{}});
  if(FAV_ONLY) scrollToId("sec-dissect");
}}
function applyFav(){{
  getFav().forEach(function(cid){{
    var el = document.getElementById("dc-" + cid);
    if(el){{ el.classList.add("faved"); var b = el.querySelector(".dfav"); if(b){{ b.textContent = "★"; b.classList.add("on"); }} }}
  }});
  updFavStat();
}}
function updFavStat(){{
  var n = getFav().length, el = document.getElementById("favstatn");
  if(el) el.textContent = n;
}}
function scrollToId(id){{ var el=document.getElementById(id); if(el) el.scrollIntoView({{behavior:"smooth",block:"start"}}); }}
function scrollToDc(e, a){{
  e.preventDefault();
  clearFilter();
  var id=a.getAttribute("href").slice(1);
  var el=document.getElementById(id);
  if(el){{ el.scrollIntoView({{behavior:"smooth",block:"center"}}); el.classList.add("flash"); setTimeout(function(){{ el.classList.remove("flash"); }},1200); }}
}}
function showFilter(text){{ var b=document.getElementById("filterbar"); document.getElementById("filtertxt").textContent=text; b.classList.add("show"); }}
function applyFilter(opt){{
  var pt=opt.pt||null, todayOnly=opt.todayOnly||false, favOnly=opt.favOnly||false, shown=0;
  var del=getDel(), fav=getFav();
  document.querySelectorAll(".dcard").forEach(function(c){{
    var cid=c.id.slice(3);
    var okPt=!pt||c.dataset.pt===pt;
    var okToday=!todayOnly||c.dataset.date===TODAY;
    var okFav=!favOnly||fav.indexOf(cid)>=0;
    var okDel=del.indexOf(cid)<0;
    var ok=okPt&&okToday&&okFav&&okDel;
    c.style.display=ok?"":"none"; if(ok) shown++;
  }});
  return shown;
}}
function goDissect(kind){{
  scrollToId("sec-dissect");
  resetFavOnly();
  if(kind==="all"){{ applyFilter({{}}); document.getElementById("filterbar").classList.remove("show"); }}
  else if(kind==="today"){{ var n=applyFilter({{todayOnly:true}}); showFilter("筛选：今日新增（"+n+" 张）"); }}
}}
function goTypes(){{ scrollToId("sec-types"); }}
function clearFilter(){{ resetFavOnly(); applyFilter({{}}); document.getElementById("filterbar").classList.remove("show"); }}
var REF_BUSY=false;
function setRef(msg,cls){{var s=document.getElementById("refstatus");s.textContent=msg;s.className="refstatus"+(cls?(" "+cls):"");}}
function doRefresh(){{
  if(REF_BUSY) return;
  if(window.__YRD_NATIVE__){{
    REF_BUSY=true;
    var b=document.getElementById("refbtn"); b.disabled=true; b.textContent="刷新中…";
    setRef("正在云端搜索新增案例…");
    if(window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.yrdRefresh){{
      window.webkit.messageHandlers.yrdRefresh.postMessage("refresh");
    }} else {{
      location.href="yrdintel://refresh";
    }}
  }} else {{
    setRef("请在桌面「长三角制造业情报」App 内点击刷新；浏览器中可打开 GitHub Actions 手动运行。");
    window.open("https://github.com/tedvong894/yrd-mfg-intel/actions/workflows/refresh.yml","_blank");
  }}
}}
window.__yrdRefreshStatus=function(m){{ setRef(m); }};
window.__yrdRefreshDone=function(m){{ setRef(m,"ok"); setTimeout(function(){{ location.reload(); }},900); }};
window.__yrdRefreshFail=function(m){{ REF_BUSY=false; var b=document.getElementById("refbtn"); b.disabled=false; b.textContent="刷新"; setRef(m,"err"); }};
document.querySelectorAll(".row.clickable").forEach(function(r){{
  r.addEventListener("click", function(){{
    var pt=r.dataset.pt; scrollToId("sec-dissect");
    var n=applyFilter({{pt:pt}}); showFilter("筛选：问题类型 = "+pt+"（"+n+" 张）");
  }});
}});
applyDel();
applyFav();
</script>
</body></html>"""

    out = os.path.join(intel_dir, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    # 兼容本地旧引用
    with open(os.path.join(intel_dir, "dashboard.html"), "w", encoding="utf-8") as f:
        f.write(html)

    # PWA 清单（iPhone/安卓主屏幕图标与全屏模式依赖它）
    manifest = {
        "name": "长三角制造业问题解剖情报平台",
        "short_name": "制造业情报",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "background_color": "#f5f7fa",
        "theme_color": "#0f172a",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    with open(os.path.join(intel_dir, "manifest.webmanifest"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[ok] 看板已生成：{out}")


def render_daily_report(intel_dir, today_cards, today):
    if not today_cards:
        md = f"# 长三角制造业问题解剖日报（{today}）\n\n今日无新增。\n"
    else:
        lines = [f"# 长三角制造业问题解剖日报（{today}）\n",
                 f"今日新增 **{len(today_cards)}** 张解剖卡。\n"]
        by_pt = {}
        for c in today_cards:
            by_pt.setdefault(c.get("problem_type", "其他"), []).append(c)
        for pt, items in by_pt.items():
            lines.append(f"\n## {pt}（{len(items)}）\n")
            for c in sorted(items, key=lambda x: x.get("date", ""), reverse=True):
                lines.append(f"### {c.get('title','')}\n"
                             f"- 地区：{c.get('region','')} · 来源：{c.get('source','')} · 日期：{c.get('date','')}\n"
                             f"- 背景：{c.get('summary','')}\n"
                             f"- 企业问题：{'；'.join(c.get('problems',[])) or '（未标注）'}\n"
                             f"- 链接：{c.get('url','')}\n")
        lines.append("\n---\n_由 intel_processor.py 自动汇总，完整解剖看板见 index.html_")
        md = "\n".join(lines)
    out = os.path.join(intel_dir, f"daily_report_{today}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[ok] 日报已生成：{out}")


if __name__ == "__main__":
    intel_dir = sys.argv[sys.argv.index("--intel-dir") + 1] if "--intel-dir" in sys.argv else os.path.dirname(os.path.abspath(__file__))
    process(intel_dir)
