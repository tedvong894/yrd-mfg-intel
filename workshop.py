#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
长三角制造业案例情报平台 — 短视频工坊（第二模块 / 庖丁解牛下游）

职责：把一张「解剖卡」自动转成
  ① 五段式口播文案（钩子 / 定题 / 事实 / 翻译 / 解剖 / 收尾）
  ② 12 列标准化剪辑底稿（可导 xlsx）
  ③ workshop/index.json（供看板渲染「短视频工坊」区块 + 下载链接）

边界（标准化分界线，不要越界）：
  文案与底稿 = 机器生成
  画面素材与配音 = 人工挑（画面素材列留空，只给「场景建议 + 检索词」）

依赖：仅标准库 + dissect.py；导出 xlsx 需 openpyxl（缺失时自动降级为纯 json）。
"""
import os
import re
import sys
import json
import glob
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import dissect  # noqa: E402

SPEED = 4.8          # 语速 字/秒（知识类黄金区 4.5-5.5）
TOP_N = 12           # 默认给评分最高的 12 张卡生成底稿文件
DEFAULT_TYPE = dissect.DEFAULT_TYPE


# ══════════════════════════════════════════════════════════
# 固定比喻体系（对标小Lin说：同一套比喻反复用，形成记忆点）
# ══════════════════════════════════════════════════════════
ASSOC = {
    "倒闭关停": [
        "厂子就是一口锅——订单是火，现金是锅里的水。火一停，水凉得飞快。",
        "关门不是哪一天的决定，是每一次「再撑撑」的累加。",
    ],
    "亏损": [
        "营收是身高，利润是体重——身高长得快，人却在虚胖。",
        "订单是把货送出去，利润才是把钱留下来，这两件事经常不是一回事。",
    ],
    "订单流失": [
        "客户不是走了，是把你那把椅子让给了别人——椅子只有一把。",
        "订单变薄，就像饭量没变、碗变小了，饿是必然的。",
    ],
    "转型失败": [
        "买了台跑步机，身体没练好，分期还得月月还。",
        "上系统像装中央空调：房子没封顶，装得越贵漏得越狠。",
    ],
    "质量事故": [
        "木桶漏水，补哪块板都不如先换最短的那块。",
        "质量事故不是概率问题，是时间问题——体系有洞，它一定会来。",
    ],
    "欠款劳资": [
        "工资是厂子的心跳，一天不跳，人心就散了。",
        "欠款是一条链：上游晚一个月，下游就敢晚三个月。",
    ],
    "库存积压": [
        "仓库里堆的不是货，是冻起来的现金。",
        "库存像冰箱：放久了不会消失，只会变成你不想认的损失。",
    ],
    "现金流断裂": [
        "利润是体检报告，现金是呼吸——报告好看，也得先能喘气。",
        "账面利润是画在纸上的饼，银行只收真钱。",
    ],
}

# 结尾避坑（每条必须带动作，≤3 条，≤16 字）
TIPS = {
    "倒闭关停": ["留足 6 个月现金安全垫再扩张", "砍掉不赚钱的低端红海单", "每年固定比例投技改"],
    "亏损": ["建成本传导机制，敢跟着涨价", "往高附加值走，保住毛利", "算清单笔订单真实成本"],
    "订单流失": ["老客户做深，别只做一单", "市场分散，别系在一个客户上", "用微创新打样替代降价"],
    "转型失败": ["从最痛的那个单点切入", "先打通数据再谈智能", "算清回本周期再上重资产"],
    "质量事故": ["建批次溯源，出事秒定位", "品控前置到首检过程检", "危机第一时间透明沟通"],
    "欠款劳资": ["现金流排期先于扩张", "合规红线不能碰", "账期写进合同，别用感情做信用"],
    "库存积压": ["按单生产加安全库存", "定期清呆滞，别心疼", "周转天数做成月度必看指标"],
    "现金流断裂": ["永远留 3-6 个月安全垫", "短贷不能长投", "周转比规模重要"],
}

# 钩子短句（≤18 字成句）：强词 + 疑问
HOOK_SHORT = {
    "倒闭关停": ("说关就关", "钱到底卡在哪"),
    "亏损": ("订单没少接", "钱到底去哪了"),
    "订单流失": ("订单一年比一年薄", "是被替代了吗"),
    "转型失败": ("砸钱上了系统", "为啥反而更亏"),
    "质量事故": ("一批货出了事", "怎么差点被拖垮"),
    "欠款劳资": ("厂子还在转", "工资为啥发不出"),
    "库存积压": ("仓库堆成山", "账面为啥没钱"),
    "现金流断裂": ("账上数字好看", "付款为啥抓瞎"),
}

# 定题段病症句（无关键数字时兜底）
DISEASE = {
    "倒闭关停": "症结在订单依赖、账期拉长、成本上升三头一起压",
    "亏损": "症结在增收不增利，收入涨了利润没跟上",
    "订单流失": "症结在客户外迁、单一市场依赖太重",
    "转型失败": "症结在系统上了、人和流程没跟上",
    "质量事故": "症结在品控体系有洞、批次溯源缺失",
    "欠款劳资": "症结在现金流排期失序、合规红线被踩",
    "库存积压": "症结在推式生产、凭经验备货",
    "现金流断裂": "症结在短贷长投、安全垫太薄",
}

# 事实段/解剖段画面建议：场景 + 英文检索词（Pexels/Pixabay 英文命中率远高于中文）
SCENE_HINTS = {
    "倒闭关停": [("厂房外景", "abandoned warehouse / factory closed / shutter door"),
                 ("车间内景", "empty factory / idle production line"),
                 ("仓库", "empty warehouse / cleared shelves"),
                 ("货车物流", "empty loading dock / idle truck")],
    "亏损": [("办公室", "empty office / empty meeting room"),
             ("账本单据", "financial report / calculator / loss chart"),
             ("数据图表", "declining bar chart / downward arrow"),
             ("设备特写", "industrial machine closeup")],
    "订单流失": [("厂房外景", "factory exterior / industrial park"),
                 ("货车物流", "empty container yard / shipping container / idle truck"),
                 ("仓库", "empty warehouse / cleared loading dock"),
                 ("数据图表", "declining line chart / export data")],
    "转型失败": [("设备特写", "old machinery / dusty equipment / outdated machine"),
                 ("车间内景", "automated production line / robotic arm"),
                 ("办公室", "empty office / staff meeting"),
                 ("数据图表", "cost curve / investment chart")],
    "质量事故": [("车间内景", "quality control / inspection line"),
                 ("设备特写", "caliper closeup / measuring instrument"),
                 ("仓库", "defective products / rework boxes"),
                 ("数据图表", "defect rate chart")],
    "欠款劳资": [("办公室", "empty office / signing contract"),
                 ("账本单据", "contract signing closeup / bank statement"),
                 ("法院大楼", "court building / legal documents"),
                 ("厂房外景", "closed factory gate / workers walking out")],
    "库存积压": [("仓库", "full warehouse / stacked boxes / inventory shelves"),
                 ("货车物流", "warehouse aisle / forklift"),
                 ("账本单据", "inventory ledger / calculator"),
                 ("数据图表", "inventory turnover chart")],
    "现金流断裂": [("账本单据", "cash register / counting money / ledger red ink"),
                 ("办公室", "worried businessman / empty office"),
                 ("数据图表", "cash flow chart / downward arrow"),
                 ("厂房外景", "factory exterior / for lease sign")],
}

INDUSTRY_KW = [
    ("纺织印染", ["纺织", "面料", "印染", "织造", "服装", "家纺", "纱"]),
    ("五金机械", ["五金", "机械", "模具", "机床", "轴承", "紧固件", "铸造", "锻造", "金属制品", "配件"]),
    ("化工材料", ["化工", "涂料", "树脂", "化纤", "新材料", "橡塑"]),
    ("电子信息", ["电子", "电路", "半导体", "光电", "元器件"]),
    ("食品饮料", ["食品", "饮料", "粮油", "饲料", "调味"]),
    ("家居木业", ["家具", "木业", "板材", "地板", "门业"]),
    ("包装印刷", ["包装", "印刷", "纸箱", "标签"]),
    ("汽车零部件", ["汽车", "零部件", "汽配", "座椅"]),
    ("塑料制品", ["塑料", "注塑", "薄膜", "管材"]),
    ("建材建工", ["建材", "水泥", "砌块", "加气", "管桩", "玻璃"]),
]


# ══════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════
def pick_industry(title, summary=""):
    """行业识别：标题优先（最准），标题识别不出再看摘要。"""
    for scope in (title, summary):
        for name, kws in INDUSTRY_KW:
            if any(k in (scope or "") for k in kws):
                return name
    return "制造"


NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:亿元|亿|万元|万|千万元|%|％|元|人|家|条|吨|台|个月|年|天)")
# 只看「有分量」的数字：金额/比例/人数/规模；纯年限（1年、3年）不算
BIG_NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:亿元|亿|万元|万|千万元|%|％|元|人|家|条|吨|台)")
# 中档：排除纯时间量级（年/个月/天），但保留其他带单位数字
MID_NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:亿元|亿|万元|万|千万元|%|％|元|人|家|条|吨|台|元/|人次)")


def pick_numbers(text, pattern=None, limit=5):
    """抽出数字（默认全部带单位），去重保序。"""
    rx = pattern or NUM_RE
    seen, out = set(), []
    for m in rx.findall(text or ""):
        m = m.strip()
        if m in seen:
            continue
        seen.add(m)
        out.append(m)
        if len(out) >= limit:
            break
    return out


def clip(s, n, tail=""):
    """按自然停顿截断到 n 字以内（尽量不切在词中间、不留半截括号）。"""
    s = (s or "").strip().rstrip("。；，、 ")
    if len(s) > n:
        cut = max(s.rfind("，", 0, n), s.rfind("、", 0, n), s.rfind("；", 0, n))
        if cut < n * 0.55:
            cut = n
        s = s[:cut].rstrip("，、； ")
    # 括号不成对时，从「（」处截断
    if "（" in s and "）" not in s[s.rfind("（"):]:
        s = s[:s.rfind("（")].rstrip("，、； ")
    return s + tail


def clean_summary(s, limit=110):
    s = re.sub(r"\s+", "", s or "")
    s = re.sub(r"^(据|根据)?[^，。]{0,12}(报道|消息|显示)[，,：:]*", "", s)
    s = s.strip("，。、 ")
    if len(s) > limit:
        cut = max(s.rfind("。", 0, limit), s.rfind("，", 0, limit), s.rfind("；", 0, limit))
        s = s[:cut] if cut > limit * 0.5 else s[:limit]
    return s.rstrip("，。、 ") + "。"


STRONG_RE = re.compile(r"[。；！？!?—]+")   # 强断句：绝不跨此合并（保证「①/②/③ 逐条」不被并进上一条）
WEAK_RE = re.compile(r"[，、：:,]+")        # 弱停顿：可合并成一条呼吸句
# 硬拆时优先选择的断点（避免把「江苏一家五金机械厂」拆成「江苏一家 / 五金机械 / 厂」）
SAFE_START = set("不没很更最也都就还又把被在是和与而但要会能有为对从向再才只")
SAFE_END = set("的了地得上中下里后前时个")


def split_breaths(text, target_chars):
    """按「呼吸句」拆行：强断句处必断，弱停顿处按目标字数合并；只有超长句才按语义边界硬拆。
    返回 [(片段, 是否句末)]，一句一行 = 一个镜次。句末标记供配音脚本还原「整段全文」。"""
    out = []
    for sent in STRONG_RE.split(text or ""):
        sent = (sent or "").strip()
        if not sent:
            continue
        clauses = [c.strip() for c in WEAK_RE.split(sent) if c.strip()]
        merged = []
        for c in clauses:
            if merged and len(merged[-1]) < target_chars * 0.6:
                merged[-1] = merged[-1] + "，" + c
            else:
                merged.append(c)
        soft = max(target_chars * 2.0, 12)
        pieces = []
        for c in merged:
            if len(c) <= soft:
                pieces.append(c)
                continue
            pos = 0
            while len(c) - pos > soft:
                nxt = pos + int(round(target_chars))
                best = None
                for off in range(0, 6):
                    for p in (nxt - off, nxt + off):
                        if pos + 6 <= p <= len(c) - 5 and (c[p] in SAFE_START or c[p - 1] in SAFE_END):
                            best = p
                            break
                    if best is not None:
                        break
                if best is None:
                    best = min(len(c) - 5, nxt)
                pieces.append(c[pos:best])
                pos = best
            pieces.append(c[pos:])

        # 句内后处理：① 括号没闭合的相邻片段必须合并 ② 过短碎片（≤4 字）并入前一片段
        fixed = []
        for f in pieces:
            if fixed:
                prev = fixed[-1]
                joined = prev + "，" + f
                if prev.count("（") > prev.count("）") and len(joined) <= target_chars * 2.6:
                    fixed[-1] = joined
                    continue
                if len(f) < 5 and len(joined) <= target_chars * 1.6:
                    fixed[-1] = joined
                    continue
            fixed.append(f)
        fixed = [o.strip("，、 ") for o in fixed if o.strip("，、 ")]
        for i, f in enumerate(fixed):
            out.append((f, i == len(fixed) - 1))   # 每句最后一片标为句末
    return out


# 各段的目标单镜时长（秒）→ 换算成目标字数
SEG_TARGET_DUR = {"钩子": 1.15, "定题": 1.7, "事实": 2.4, "翻译": 2.6, "解剖": 2.5, "收尾": 3.2}
SEG_SHOT_TYPE = {"钩子": "空镜快切", "定题": "空镜", "事实": "图表+实拍",
                 "翻译": "素材(比喻画面)", "解剖": "图表+文字卡", "收尾": "实拍+文字卡"}
SEG_BGM = {"钩子": "开场悬念", "定题": "开场悬念", "事实": "中段推进",
           "翻译": "中段推进", "解剖": "中段推进", "收尾": "结尾收束"}
SEG_MOOD = {"钩子": "快切/冲突", "定题": "推进", "事实": "陈述/数字重音",
            "翻译": "转折/停顿", "解剖": "逐条拆解", "收尾": "落点/留白"}
SEG_DUR_RANGE = {"钩子": (0.9, 1.9), "定题": (1.2, 2.6), "事实": (1.6, 3.4),
                 "翻译": (1.8, 3.6), "解剖": (1.8, 3.4), "收尾": (2.4, 4.2)}


# ══════════════════════════════════════════════════════════
# ① 五段式口播文案
# ══════════════════════════════════════════════════════════
def build_copywriting(card):
    """产出 [(段名, 文本), ...]，顺序即口播顺序。总时长按 4.8 字/秒控制在 60-90 秒。"""
    ptype = card.get("problem_type_key") or dissect.infer_type(
        (card.get("title", "") + card.get("summary", "")))
    angles = card.get("angles") or dissect.get_angles(ptype)
    problems = card.get("problems") or []
    region = card.get("region") or "长三角"
    blob = card.get("title", "") + " " + card.get("summary", "")

    industry = pick_industry(card.get("title", ""), card.get("summary", ""))
    big = pick_numbers(blob, BIG_NUM_RE, 3)
    nums = pick_numbers(blob, MID_NUM_RE, 5)
    assoc = ASSOC.get(ptype, ASSOC[DEFAULT_TYPE])
    tips = TIPS.get(ptype, TIPS[DEFAULT_TYPE])
    strong, question = HOOK_SHORT.get(ptype, ("出了大问题", "问题出在哪"))

    segs = []

    # ── 钩子｜0-3s｜12-18 字｜必须带强词（关停/欠薪/断供/跑路…）
    segs.append(("钩子", clip(f"{strong}——{question}", 18) + "？"))

    # ── 定题｜3-8s｜20-30 字｜哪里的什么厂、得什么病
    if big:
        tail = f"公开报道里的关键数字：{'、'.join(big)}"
    else:
        tail = DISEASE.get(ptype, "症结在经营结构本身")
    segs.append(("定题", f"{region}一家{industry}厂，{clip(tail, 22)}。"))

    # ── 事实｜8-30s｜80-110 字｜时间线 + 数字
    fact = f"先把事实说清楚。{clean_summary(card.get('summary', ''), 84)}"
    if not big and nums:
        fact += f"公开信息里出现过的数字：{'、'.join(nums[:3])}。"
    segs.append(("事实", fact))

    # ── 翻译（比喻 1）｜穿插
    segs.append(("翻译", f"打个比方。{assoc[0]}"))

    # ── 解剖｜30-65s｜130-180 字｜4 个视角一个不能少
    cnum = "①②③④⑤⑥"
    parts = []
    for i, a in enumerate(angles[:4]):
        parts.append(f"{cnum[i]}{a['视角']}。{clip(a['要点'], 24)}。")
    if problems:
        parts.append(f"公开信息点名的问题：{'；'.join(clip(p, 20) for p in problems[:2])}。")
    segs.append(("解剖", "".join(parts)))

    # ── 翻译（比喻 2）｜落点
    segs.append(("翻译", assoc[1] if len(assoc) > 1 else "这笔账，最后都要有人来付。"))

    # ── 收尾｜65-90s｜40-60 字｜≤3 条可执行避坑
    segs.append(("收尾", "最后给同类厂三句话。" +
                 "；".join(f"{cnum[i]}{clip(t, 16)}" for i, t in enumerate(tips[:3])) + "。"))

    return ptype, segs


# ══════════════════════════════════════════════════════════
# ② 12 列剪辑底稿
# ══════════════════════════════════════════════════════════
def build_segments(card, rows):
    """把「连续的同类镜次」归成一个配音段（注意：按连续段归并，不能按名字全局归并——
    脚本里「翻译(比喻)」出现两次、中间夹着解剖，全局归并把两处合成一段会打乱顺序）。
    给出每段的「整段全文」：配音脚本按整段一次合成时用它，再配合 TTS 逐句时间戳，
    就能把实测时间码精确回填到每个镜次。"""
    segs, seen = [], {}
    for r in rows:
        if not segs or segs[-1]["段落"] != r["段落"]:
            n = seen.get(r["段落"], 0) + 1
            seen[r["段落"]] = n
            segs.append({"段落": r["段落"], "出现序": n,
                         "标签": r["段落"] if n == 1 else f"{r['段落']}·{n}",
                         "全文": "", "镜次": []})
        segs[-1]["镜次"].append(r["镜次"])
        segs[-1]["全文"] += r["口播文案"] + ("。" if r.get("句末") else "，")
    for s in segs:
        s["全文"] = s["全文"].rstrip("，。")
    return segs


def build_beats(card):
    ptype, segs = build_copywriting(card)
    scenes = SCENE_HINTS.get(ptype, SCENE_HINTS[DEFAULT_TYPE])
    rows, t, idx, scene_i, tt = [], 0.0, 0, 0, 0.0

    for seg_name, text in segs:
        target_chars = SEG_TARGET_DUR[seg_name] * SPEED
        lo, hi = SEG_DUR_RANGE[seg_name]
        frags = split_breaths(text, target_chars)
        for j, (frag, is_end) in enumerate(frags):
            idx += 1
            dur = round(max(lo, min(hi, len(frag) / SPEED)), 1)
            scene, kw = scenes[scene_i % len(scenes)]
            scene_i += 1
            # 画面素材列：留空给人工，只给场景建议 + 检索词（标准化分界线）
            shot = f"【待挑】{ptype}_{scene}_{(idx):03d}　搜：{kw}"
            # 字幕/图示
            if re.search(r"\d", frag):
                sub = "数字上大字幕：" + "，".join(pick_numbers(frag) or [frag[:8]])
            elif seg_name == "解剖" and frag[:1] in "①②③④⑤⑥":
                sub = "视角卡：" + frag[1:5]
            elif seg_name == "收尾":
                sub = "避坑清单上屏（≤3 条）"
            else:
                sub = ""
            # 音效
            if seg_name == "钩子":
                sfx = "重音咚 / 唰" if j == len(frags) - 1 else "快切提示音"
            elif sub.startswith("数字上大字幕"):
                sfx = "数字叮"
            elif seg_name == "收尾":
                sfx = "结论咚"
            else:
                sfx = ""
            trans = "硬切" if seg_name in ("钩子", "事实", "解剖", "翻译") else "叠化"
            rows.append({
                "镜次": f"{idx:03d}",
                "起": round(t, 1), "止": round(t + dur, 1), "时长": dur,
                "口播文案": frag, "节奏/情绪": SEG_MOOD[seg_name],
                "画面类型": SEG_SHOT_TYPE[seg_name], "画面素材": shot,
                "字幕/图示": sub, "音效": sfx, "BGM段": SEG_BGM[seg_name],
                "转场": trans, "段落": seg_name, "句末": is_end,
            })
            t = round(t + dur, 1)

    return ptype, rows, round(t, 1)


def build_material_list(ptype, rows):
    scenes = SCENE_HINTS.get(ptype, SCENE_HINTS[DEFAULT_TYPE])
    out = []
    for i, (scene, kw) in enumerate(scenes, 1):
        out.append({"序号": f"{i}", "场景": scene, "检索词（英文，主用）": kw,
                    "建议条数": "2-3", "来源": "Pexels / Pixabay（免署名可商用）"})
    return out


# ══════════════════════════════════════════════════════════
# ③ 导出 xlsx
# ══════════════════════════════════════════════════════════
def export_xlsx(card, ptype, rows, total, out_path):
    """生成单卡底稿 xlsx：剪辑底稿 + 素材清单 + 节奏规范。失败返回 False。"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("[warn] 未安装 openpyxl，跳过 xlsx 导出（仅生成 json/看板内预览）")
        return False

    thin = Side(style="thin", color="FFBFBFBF")
    BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)
    F_HEAD = Font(bold=True, color="FFFFFFFF", size=10)
    F_BODY = Font(size=10)
    FILL_HEAD = PatternFill("solid", fgColor="FF4472C4")
    FILL_LIGHT = PatternFill("solid", fgColor="FFD9E2F3")
    CENT = Alignment(horizontal="center", vertical="center", wrap_text=True)
    LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)

    wb = Workbook()
    wb.properties.title = "短视频剪辑底稿"

    # ── 表1 剪辑底稿
    ws = wb.active
    ws.title = "剪辑底稿"
    ws["A1"] = f"{card.get('title','')} · 短视频剪辑底稿"
    ws["A1"].font = Font(bold=True, size=13, color="FF1F3864")
    ws.merge_cells("A1:L1")
    ws["A2"] = (f"问题类型：{card.get('problem_type','')}　地区：{card.get('region','')}　"
                f"内容价值：★{card.get('score',0)}　总时长：{total} 秒　镜次：{len(rows)}")
    ws["A2"].font = Font(size=9, color="FF7F7F7F")
    ws.merge_cells("A2:L2")
    ws["A3"] = "⚠️「画面素材」列为机器给出的场景建议 + 检索词，请人工从素材仓库挑好文件后替换为实际文件名。"
    ws["A3"].font = Font(size=9, color="FFC2603C")
    ws.merge_cells("A3:L3")

    COLS = ["镜次", "起(s)", "止(s)", "时长(s)", "口播文案", "节奏/情绪", "画面类型",
            "画面素材（文件名）", "字幕/图示", "音效", "BGM段", "转场"]
    WIDTHS = [7, 8, 8, 9, 42, 12, 14, 40, 24, 12, 12, 8]
    HR = 4
    for i, h in enumerate(COLS, 1):
        c = ws.cell(row=HR, column=i, value=h)
        c.font = F_HEAD
        c.fill = FILL_HEAD
        c.alignment = CENT
        c.border = BORDER
    for i, w in enumerate(WIDTHS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[HR].height = 26

    for k, r in enumerate(rows):
        rr = HR + 1 + k
        vals = [r["镜次"], r["起"], r["止"], r["时长"], r["口播文案"], r["节奏/情绪"],
                r["画面类型"], r["画面素材"], r["字幕/图示"], r["音效"], r["BGM段"], r["转场"]]
        for i, v in enumerate(vals, 1):
            c = ws.cell(row=rr, column=i, value=v)
            c.font = F_BODY
            c.border = BORDER
            c.alignment = LEFT if i in (5, 8, 9) else CENT
        if r["段落"] == "钩子":
            for i in range(1, 13):
                ws.cell(row=rr, column=i).fill = FILL_LIGHT
        ws.row_dimensions[rr].height = 30
    ws.freeze_panes = "A5"

    # ── 表2 素材清单
    ws2 = wb.create_sheet("素材清单（人工去挑）")
    M_COLS = ["序号", "场景", "检索词（英文，主用）", "建议条数", "来源"]
    M_WIDTHS = [7, 14, 52, 10, 30]
    for i, h in enumerate(M_COLS, 1):
        c = ws2.cell(row=1, column=i, value=h)
        c.font = F_HEAD
        c.fill = FILL_HEAD
        c.alignment = CENT
        c.border = BORDER
    for i, w in enumerate(M_WIDTHS, 1):
        ws2.column_dimensions[get_column_letter(i)].width = w
    ws2.row_dimensions[1].height = 26
    for k, m in enumerate(build_material_list(ptype, rows)):
        rr = 2 + k
        for i, key in enumerate(M_COLS, 1):
            c = ws2.cell(row=rr, column=i, value=list(m.values())[i - 1])
            c.font = F_BODY
            c.border = BORDER
            c.alignment = LEFT
        ws2.row_dimensions[rr].height = 26
    note_r = 2 + len(SCENE_HINTS.get(ptype, SCENE_HINTS[DEFAULT_TYPE])) + 1
    ws2.cell(row=note_r, column=1,
             value="Pexels/Pixabay 免署名可商用（注意顶部「赞助」行是 iStock 付费位）；"
                   "Videvo 逐条协议不同需逐条看；央视/央视频/他人成片一律别用。"
                   "下载后按「问题类型_场景_序号.mp4」命名，并记入素材台账。")
    ws2.cell(row=note_r, column=1).font = Font(size=9, color="FF7F7F7F")
    ws2.merge_cells(start_row=note_r, start_column=1, end_row=note_r, end_column=5)
    ws2.row_dimensions[note_r].height = 32

    # ── 表3 节奏规范
    ws3 = wb.create_sheet("节奏与声音标准")
    R_COLS = ["项目", "标准", "说明"]
    for i, h in enumerate(R_COLS, 1):
        c = ws3.cell(row=1, column=i, value=h)
        c.font = F_HEAD
        c.fill = FILL_HEAD
        c.alignment = CENT
        c.border = BORDER
    ws3.column_dimensions["A"].width = 20
    ws3.column_dimensions["B"].width = 34
    ws3.column_dimensions["C"].width = 52
    STD = [
        ("语速", "4.5-5.5 字/秒", "本稿按 4.8 字/秒排时长；口播快于 6 字/秒观众跟不上"),
        ("钩子 (0-3s)", "0.9-1.9 秒/镜，2-3 镜快切", "这 3 秒决定完播，画面要「炸」，配重音效。⚠️别再切碎到 0.8 秒——TTS/真人都会读得发赶，听着假"),
        ("定题 (3-8s)", "1.2-2.6 秒/镜", "交代环境，节奏稍缓"),
        ("事实段", "1.6-3.4 秒/镜", "数字必须上大字幕，配「叮」音效"),
        ("解剖段", "1.8-3.4 秒/镜", "4 个视角逐条上文字卡，图表与空镜交替"),
        ("收尾", "2.4-4.2 秒/镜", "放慢留白，避坑清单上屏，给落点"),
        ("BGM", "固定 3 段，压到人声 -18~-22dB", "开场悬念 / 中段推进 / 结尾收束，每期不换"),
        ("音效", "固定 3-5 个", "数字叮 / 转场唰 / 结论咚；不可盖过人声"),
        ("声音标识", "一个声音贯穿所有视频", "换成两个声音 = 两个账号；真人录音首选"),
        ("总时长", "60-90 秒", "爆款选题可再扩成 3 分钟深度版"),
    ]
    for k, (a, b, c_) in enumerate(STD):
        rr = 2 + k
        for i, v in enumerate((a, b, c_), 1):
            cc = ws3.cell(row=rr, column=i, value=v)
            cc.font = Font(bold=(i == 1), size=10)
            cc.border = BORDER
            cc.alignment = LEFT
        ws3.row_dimensions[rr].height = 26

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    wb.save(out_path)
    return True


# ══════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════
def load_cards(intel_dir):
    cards = []
    db = os.path.join(intel_dir, "intel_db.jsonl")
    if not os.path.exists(db):
        return cards
    with open(db, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                cards.append(json.loads(line))
            except Exception:
                continue
    return cards


def generate(intel_dir, top_n=TOP_N):
    cards = load_cards(intel_dir)
    out_dir = os.path.join(intel_dir, "workshop")
    os.makedirs(out_dir, exist_ok=True)

    ranked = sorted(cards, key=lambda x: x.get("score", 0), reverse=True)
    picked = [c for c in ranked if c.get("score", 0) > 0][:top_n]

    items = []
    xlsx_ok = 0
    for c in picked:
        ptype, rows, total = build_beats(c)
        cid = c.get("card_id", "")
        # 文件名走纯 ASCII（避免中文路径在 Contents API / URL 编码上出坑），
        # 下载时的中文文件名由页面 <a download="..."> 指定。
        fname = f"{cid}.xlsx"
        fpath = os.path.join(out_dir, fname)
        ok = export_xlsx(c, ptype, rows, total, fpath)
        xlsx_ok += 1 if ok else 0
        pt_short = ptype.replace("/", "").replace(" ", "")
        items.append({
            "card_id": cid,
            "title": c.get("title", ""),
            "problem_type": c.get("problem_type", ""),
            "problem_type_key": ptype,
            "region": c.get("region", ""),
            "source": c.get("source", ""),
            "url": c.get("url", ""),
            "score": c.get("score", 0),
            "shots": len(rows),
            "duration": total,
            "file": fname if ok else "",
            "dl_name": f"底稿_{pt_short}_{cid}.xlsx",
            "beats": rows,   # 看板内预览用（同一份数据，页面直接渲染成表）
            "segments": build_segments(c, rows),   # 配音脚本按整段合成 + 回填实测时间码用
        })

    idx = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "date": datetime.date.today().isoformat(),
        "count": len(items),
        "xlsx_ok": xlsx_ok,
        "items": items,
    }
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)

    print(f"[ok] 短视频工坊：生成 {len(items)} 张底稿（xlsx {xlsx_ok} 个）→ {out_dir}")
    for it in items[:5]:
        print(f"     · {it['problem_type']} | {it['shots']} 镜 | {it['duration']}s | {it['title'][:28]}")
    return idx


if __name__ == "__main__":
    d = HERE
    if "--intel-dir" in sys.argv:
        d = sys.argv[sys.argv.index("--intel-dir") + 1]
    n = TOP_N
    if "--top" in sys.argv:
        n = int(sys.argv[sys.argv.index("--top") + 1])
    generate(d, n)
