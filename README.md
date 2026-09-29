# 长三角中小制造业·问题解剖情报平台

公开网络采集长三角（浙江 / 江苏 / 上海 / 安徽）中小制造业的**问题分析类案例**，
自动解剖「企业存在哪些问题 → 从哪些视角拆 → 怎么拍成短视频」，作为短视频选题素材库。

> 定位：不是成功/转型新闻，而是**踩坑、失败、经营困境**类案例，供短视频创作者做"解剖"内容。

## 核心能力

- **自动采集**：两条通道
  - 云端（GitHub Actions，每日 08:10 北京）：`collect.py` 免密钥采集器，Google News RSS 搜索 → Bing 兜底 → 36氪补充
  - 本地（Agent WebSearch，每日 08:00）：质量更高的人工式检索，与云端按 `card_id` 自动去重
- **手动刷新**：看板导航区「⟳ 立即刷新」按钮 → 触发云端采集工作流 → 只加新案例，完成后页面自动重载
- **自动解剖**：`dissect.py` 规则引擎按问题类型挂 4 个标准分析视角 + 短视频脚本框架（零密钥、可重跑）
- **自动评分**：内容价值评分（冲突性 + 普遍性 + 可解剖性 + 可拍性）
- **可视看板**：`index.html` 导航区 5 卡片可点击联动，问题类型柱可点选过滤
- **🎬 短视频工坊（第二模块）**：`workshop.py` 把解剖卡自动转成
  ① 五段式口播文案（钩子 / 定题 / 事实 / 翻译比喻 / 解剖 / 收尾，按 4.8 字/秒排到 60-90 秒）
  ② 12 列标准化剪辑底稿（镜次 · 起 · 止 · 时长 · 口播 · 节奏 · 画面类型 · 画面素材 · 字幕 · 音效 · BGM · 转场）
  ③ 素材检索词清单 + 节奏与声音标准
  每张底稿导出为可下载 xlsx，看板内可直接看文案、点「复制口播文案」、展开镜次表预览。

> **标准化的边界**：文案与底稿由机器生成，「画面素材」与「配音音色」留给人来挑——
> 画面素材列只给「场景建议 + Pexels/Pixabay 英文检索词」，挑好后替换为实际文件名。

## 8 类问题类型

倒闭关停 · 亏损/增收不增利 · 订单流失/外贸下滑 · 转型失败/智能化踩坑 ·
质量事故/召回 · 欠款/劳资纠纷 · 库存积压/资金占用 · 现金流断裂/资金链

## 目录结构

```
dissect.py              自动解剖引擎（问题类型 → 视角 + 脚本模板）
workshop.py             短视频工坊（解剖卡 → 五段式文案 + 12 列剪辑底稿 + xlsx 导出）
queries.py              问题导向采集查询矩阵（build_daily_queries()）
collect.py              免密钥增量采集器（Google News RSS / Bing / 36氪，只取新增）
intel_processor.py      去重 + 评分 + 解剖卡 + 看板/日报渲染（逐条 card_id 去重，幂等）
sync_cloud.py           从云端拉取权威数据并做并集（防本地旧数据覆盖云端新增）
push_pages.py           通过 gh api Contents API 发布到 GitHub Pages（带并集保护）
refresh_via_actions.sh  触发云端采集工作流并等待站点更新（App 内「立即刷新」调用）
.github/workflows/refresh.yml  每日 08:10 云端采集 + 工坊 + workflow_dispatch 手动
workshop/               TOP 12 解剖卡的底稿 xlsx（{card_id}.xlsx）+ index.json
workshop-template.xlsx  空白剪辑底稿模板（7 表，人工开新选题时用）
video-SOP.md            短视频转化 SOP 全文（风格范式 / 文案模板 / 素材渠道 / 声音标准 / 剪辑工序）
raw_YYYYMMDD.json       每日采集原始数据（含 problems / problem_type 标注）
intel_db.jsonl          累积解剖卡（每行一张）
index.html              可视化解剖看板（GitHub Pages 入口）
daily_report_*.md       当日增量日报
```

## 本地运行

```bash
cd intel

# 1) 免密钥增量采集（只写新增条目，自动与 intel_db 去重）
python3 collect.py --dry-run        # 先看不写
python3 collect.py                  # 实际采集

# 2) 同步云端权威数据（避免覆盖云端新增）
python3 sync_cloud.py

# 3) 短视频工坊：给评分最高的 12 张卡生成底稿 xlsx
python3 workshop.py --top 12

# 4) 解剖入库 + 重渲染看板/日报（会读取 workshop/index.json 渲染工坊区块）
python3 intel_processor.py
```

> 底稿导 xlsx 需要 `openpyxl`；未安装时 `workshop.py` 会跳过分步导出、只在看板内保留文案与镜次预览，不报错。

## 手动刷新（点刷新按钮背后的动作）

1. 看板导航区点「⟳ 立即刷新」
2. 在「长三角制造业情报」App 内 → 触发 GitHub Actions 云端采集（`refresh_via_actions.sh`）
3. 云端跑 `collect.py` → `workshop.py` → `intel_processor.py` → 提交回仓库 → Pages 重建
4. 完成后 App 自动重载，只显示新增案例（底稿也一并更新）

浏览器里点该按钮不会静默失败，会提示到 App 内操作并给出 Actions 页面入口。

## 部署

仓库已开启 GitHub Pages（分支 `main`，根目录 `/`），线上地址：

`https://tedvong894.github.io/yrd-mfg-intel/`

数据全部来自公开网络，仅作短视频选题参考。
