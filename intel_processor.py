#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
长三角中小制造业案例情报平台 — 核心处理器（问题解剖版）
定位：搜集「问题分析类案例」→ 自动解剖（企业存在哪些问题 / 从哪些视角拆）→ 产出短视频脚本框架。
数据流：
  raw_YYYYMMDD.json        采集层（每日自动化 WebSearch 后写入，含 problems/problem_type）
        │ manifest.json 记录已处理文件，保证幂等
        ▼
  intel_db.jsonl          累积解剖卡（每行一张）
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


def detect_region(item):
    text = item.get("title", "") + " " + item.get("snippet", "") + " " + item.get("summary", "")
    for r in ["浙江", "江苏", "上海", "安徽"]:
        if r in text:
            return r
    return "长三角" if "长三角" in text else item.get("region", "长三角")


def score_item(item, ptype):
    """内容价值评分（短视频素材视角）：冲突性/普遍性/可解剖性/可拍性。"""
    t = dissect.PROBLEM_TYPES.get(ptype, dissect.PROBLEM_TYPES[dissect.DEFAULT_TYPE])
    conflict = t["severity"] * 30
    universal = t["universal"] * 25
    problems = item.get("problems", [])
    body = item.get("summary", "") or item.get("snippet", "")
    analysable = min((len(problems) + (1 if body else 0)) / 4, 1) * 25
    text = (item.get("title", "") + " " + body).lower()
    film = 0
    if any(k in text for k in ["厂", "公司", "集团", "企业", "老板"]):
        film += 10
    if re.search(r"\d", text):
        film += 10
    film = min(film, 20)
    total = conflict + universal + analysable + film
    return round(total, 1), {
        "conflict": round(conflict, 1), "universal": round(universal, 1),
        "analysable": round(analysable, 1), "filmable": round(film, 1),
    }


def build_card(item):
    text = item.get("title", "") + " " + item.get("snippet", "") + " " + item.get("summary", "")
    ptype = item.get("problem_type") or dissect.infer_type(text)
    region = detect_region(item)
    angles = dissect.get_angles(ptype)
    script = dissect.build_script(item, ptype, region)
    sc, detail = score_item(item, ptype)
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
        "problems": item.get("problems", []),
        "angles": angles,
        "script": script,
        "query": item.get("query", ""),
        "date": item.get("date", datetime.date.today().isoformat()),
        "added": datetime.date.today().isoformat(),   # 入库日期（用于"今日新增"统计，区别于文章发布时间）
        "score": sc,
        "score_detail": detail,
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
        for it in items:
            cid = card_id(it)
            if cid in existing_keys:
                continue
            new_items.append(build_card(it))
            existing_keys.add(cid)
            added += 1
        processed.add(base)
        print(f"[ok] {base}: 解析 {len(items)} 条，新增 {added} 条")

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
    "转型失败": "#7c3aed", "质量事故": "#be123c", "欠款劳资": "#db2777",
    "库存积压": "#0891b2", "现金流断裂": "#b91c1c",
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
    <div class="wnote">完整 {len(rows)} 镜请看下载的底稿文件（含素材检索词清单 + 节奏与声音标准）。</div>
  </details>
  <div class="wbtns">
    {dl}
    <button class="wbtn" onclick="copyScript('{cid}', this)">复制口播文案</button>
  </div>
</div>""")

    html = f"""
<div class="section" id="sec-workshop"><h2>🎬 短视频工坊 · 解剖卡 → 可直接开剪的底稿（{len(items)} 张）</h2>
  <div class="wlead">机器负责「文案 + 底稿」，人负责「画面 + 声音」——这条线就是标准化的边界。<br>
  每张底稿 = 五段式口播文案 + 12 列剪辑底稿（镜次/时间码/口播/节奏/画面类型/素材建议/字幕/音效/BGM/转场）+ 素材检索词清单 + 节奏与声音标准。
  画面素材列留空并附检索词，请人工从素材仓库挑好后替换为实际文件名。</div>
  <div class="wtools">
    <a class="wbtn" href="workshop-template.xlsx" download="剪辑底稿模板.xlsx">⬇ 空白模板</a>
    <a class="wbtn" href="video-SOP.md" target="_blank" rel="noopener">📄 完整 SOP</a>
    <span class="wtools-hint">底稿随云端采集自动更新，只对内容价值最高的 {len(items)} 张生成</span>
  </div>
  <div class="wgrid">{''.join(cards_html)}</div>
</div>"""

    return html, script_map


def render_dashboard(intel_dir, cards, today_cards, today):
    pt_counter = Counter(c.get("problem_type", "其他") for c in cards)
    reg_counter = Counter(c.get("region", "其他") for c in cards)
    top = sorted(cards, key=lambda x: x.get("score", 0), reverse=True)[:12]

    pt_max = max(pt_counter.values()) if pt_counter else 1
    reg_max = max(reg_counter.values()) if reg_counter else 1
    pt_html = "".join(bar(p, n, pt_max, PT_COLORS.get(p, "#6b7280"), clickable=True, data_pt=p)
                      for p, n in sorted(pt_counter.items(), key=lambda x: x[1], reverse=True))
    reg_html = "".join(bar(r, n, reg_max, REG_COLORS.get(r, "#6b7280")) for r, n in
                       sorted(reg_counter.items(), key=lambda x: x[1], reverse=True))

    hi = sum(1 for c in cards if c.get("score", 0) >= 80)

    # 短视频工坊（第二模块）：先算，解剖卡里才能挂「查看底稿」跳转
    workshop_html, script_map = render_workshop(intel_dir)
    ws_count = len(script_map)

    def dissect_block(c):
        pcolor = PT_COLORS.get(c.get("problem_type"), "#6b7280")
        problems = "".join(f"<li>{p}</li>" for p in c.get("problems", [])) or "<li>（采集层未标注具体问题）</li>"
        angles = "".join(f"<li><b>{a['视角']}</b>：{a['要点']}</li>" for a in c.get("angles", []))
        sc = c.get("script", {})
        points = "".join(f"<li>{p}</li>" for p in sc.get("points", []))
        return f"""
<div class="dcard" data-pt="{c.get('problem_type','')}" data-score="{c.get('score',0)}" data-date="{c.get('added', c.get('date',''))}">
  <div class="dcard-head">
    <span class="pt" style="background:{pcolor}">{c.get('problem_type','')}</span>
    <span class="dscore">内容价值 ★ {c.get('score',0)}</span>
  </div>
  <a class="dtitle" href="{c.get('url','#')}" target="_blank" rel="noopener">{c.get('title','')}</a>
  <div class="dmeta">{c.get('region','')} · {c.get('source','')} · {c.get('date','')}</div>
  <div class="dsum">{c.get('summary','')}</div>
  <div class="blk"><div class="blkh">企业存在哪些问题</div><ul class="iss">{problems}</ul></div>
  <div class="blk"><div class="blkh">解剖视角（自动挂接）</div><ul class="ang">{angles}</ul></div>
    <div class="blk script">
    <div class="blkh">短视频脚本框架</div>
    <div class="sh">🎬 开场钩子：{sc.get('hook','')}</div>
    <ul class="pts">{points}</ul>
    <div class="se">💡 结尾避坑：{sc.get('ending','')}</div>
    <div class="smeta">时长 {sc.get('duration','')} · {sc.get('style','')}
      {"· <a class='wlink' href='#ws-" + c.get("card_id","") + "'>查看已生成底稿 ↓</a>" if c.get("card_id") in script_map else ""}</div>
  </div>
</div>"""

    top_html = "".join(
        f'<tr><td>{i+1}</td><td><a href="{c.get("url","#")}" target="_blank" rel="noopener">{c.get("title","")}</a></td>'
        f'<td><span class="pill" style="background:{PT_COLORS.get(c.get("problem_type"),"#6b7280")}">{c.get("problem_type","")}</span></td>'
        f'<td>{c.get("region","")}</td><td class="num">★ {c.get("score",0)}</td></tr>'
        for i, c in enumerate(top))

    # 解剖卡全量渲染（供筛选），按评分降序
    dissect_all = sorted(cards, key=lambda x: x.get("score", 0), reverse=True)
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
td.num{{font-weight:700;color:#dc2626}}
.pill{{color:#fff;font-size:11px;padding:2px 8px;border-radius:20px}}
.dissect-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:16px}}
.dcard{{background:#f8fafc;border:1px solid #e5e7eb;border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:8px}}
.dcard-head{{display:flex;justify-content:space-between;align-items:center}}
.pt{{color:#fff;font-size:12px;font-weight:600;padding:3px 10px;border-radius:20px}}
.dscore{{font-size:13px;font-weight:700;color:#dc2626}}
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
</style></head>
<body><div class="wrap">
<header>
  <h1>长三角制造业 · 问题解剖情报平台</h1>
  <div class="sub">公开网络采集问题企业案例 → 自动解剖（问题清单+分析视角+短视频脚本）· 更新于 {today}</div>
  <div class="stats">
    <div class="stat" onclick="goDissect('all')"><div class="n">{len(cards)}</div><div class="l">累积解剖卡</div></div>
    <div class="stat" onclick="goDissect('today')"><div class="n">{len(today_cards)}</div><div class="l">今日新增</div></div>
    <div class="stat" onclick="goTypes()"><div class="n">{len(pt_counter)}</div><div class="l">问题类型</div></div>
    <div class="stat" onclick="goDissect('high')"><div class="n">{hi}</div><div class="l">高分素材(≥80)</div></div>
    <div class="stat" onclick="goWorkshop()"><div class="n">{ws_count}</div><div class="l">可开剪底稿</div></div>
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
<div class="section" id="sec-regions"><h2>覆盖地区分布</h2>{reg_html or '<div class="empty">暂无数据</div>'}</div>

<div class="section" id="sec-top"><h2>内容价值评分 Top 12</h2>
<table><thead><tr><th>#</th><th>标题</th><th>问题类型</th><th>地区</th><th>评分</th></tr></thead>
<tbody>{top_html or '<tr><td colspan="5" class="empty">暂无数据</td></tr>'}</tbody></table></div>

<div class="section" id="sec-dissect"><h2>自动解剖卡（全部 {len(cards)} 张，可筛选）</h2>
<div class="dissect-grid">{dissect_html}</div></div>

{workshop_html}

<footer>由 intel_processor.py + dissect.py + workshop.py 自动生成 · 数据源：公开网络 WebSearch · 仅作短视频选题参考</footer>
</div>
<script>
var TODAY = "{today}";
var WS = {json.dumps(script_map, ensure_ascii=False)};
function copyScript(cid, btn){{
  var t = WS[cid] || "";
  var old = btn.textContent;
  function done(ok){{
    btn.textContent = ok ? "已复制 ✓" : "复制失败";
    setTimeout(function(){{ btn.textContent = old; }}, 1400);
  }}
  if(navigator.clipboard && navigator.clipboard.writeText){{
    navigator.clipboard.writeText(t).then(function(){{ done(true); }}, function(){{ done(false); }});
  }} else {{
    var ta=document.createElement("textarea"); ta.value=t; document.body.appendChild(ta);
    ta.select(); var ok=false; try{{ ok=document.execCommand("copy"); }}catch(e){{}}
    document.body.removeChild(ta); done(ok);
  }}
}}
function goWorkshop(){{ scrollToId("sec-workshop"); }}
function scrollToId(id){{ var el=document.getElementById(id); if(el) el.scrollIntoView({{behavior:"smooth",block:"start"}}); }}
function showFilter(text){{ var b=document.getElementById("filterbar"); document.getElementById("filtertxt").textContent=text; b.classList.add("show"); }}
function applyFilter(opt){{
  var pt=opt.pt||null, minScore=opt.minScore||0, todayOnly=opt.todayOnly||false, shown=0;
  document.querySelectorAll(".dcard").forEach(function(c){{
    var okPt=!pt||c.dataset.pt===pt;
    var okScore=parseFloat(c.dataset.score)>=minScore;
    var okToday=!todayOnly||c.dataset.date===TODAY;
    var ok=okPt&&okScore&&okToday;
    c.style.display=ok?"":"none"; if(ok) shown++;
  }});
  return shown;
}}
function goDissect(kind){{
  scrollToId("sec-dissect");
  if(kind==="all"){{ applyFilter({{}}); document.getElementById("filterbar").classList.remove("show"); }}
  else if(kind==="today"){{ var n=applyFilter({{todayOnly:true}}); showFilter("筛选：今日新增（"+n+" 张）"); }}
  else if(kind==="high"){{ var n=applyFilter({{minScore:80}}); showFilter("筛选：高分素材 ≥80（"+n+" 张）"); }}
}}
function goTypes(){{ scrollToId("sec-types"); }}
function clearFilter(){{ applyFilter({{}}); document.getElementById("filterbar").classList.remove("show"); }}
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
            for c in sorted(items, key=lambda x: x.get("score", 0), reverse=True):
                lines.append(f"### {c.get('title','')} ★{c.get('score',0)}\n"
                             f"- 地区：{c.get('region','')} · 来源：{c.get('source','')}\n"
                             f"- 背景：{c.get('summary','')}\n"
                             f"- 企业问题：{'；'.join(c.get('problems',[])) or '（未标注）'}\n"
                             f"- 解剖视角：{'; '.join(a['视角'] for a in c.get('angles',[]))}\n"
                             f"- 脚本钩子：{c.get('script',{}).get('hook','')}\n"
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
