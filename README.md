# 长三角中小制造业·问题解剖情报平台

公开网络采集长三角（浙江 / 江苏 / 上海 / 安徽）中小制造业的**问题分析类案例**，
自动解剖「企业存在哪些问题 → 从哪些视角拆 → 怎么拍成短视频」，作为短视频选题素材库。

> 定位：不是成功/转型新闻，而是**踩坑、失败、经营困境**类案例，供短视频创作者做"解剖"内容。

## 核心能力

- **自动采集**：每日定时用 WebSearch 跑 8 类问题 × 5 地区 = 40 条查询矩阵
- **自动解剖**：`dissect.py` 规则引擎按问题类型挂 4 个标准分析视角 + 短视频脚本框架（零密钥、可重跑）
- **自动评分**：内容价值评分（冲突性 + 普遍性 + 可解剖性 + 可拍性）
- **可视看板**：`index.html` 导航区 4 卡片可点击联动，问题类型柱可点选过滤

## 8 类问题类型

倒闭关停 · 亏损/增收不增利 · 订单流失/外贸下滑 · 转型失败/智能化踩坑 ·
质量事故/召回 · 欠款/劳资纠纷 · 库存积压/资金占用 · 现金流断裂/资金链

## 目录结构

```
dissect.py         自动解剖引擎（问题类型 → 视角 + 脚本模板）
queries.py         问题导向采集查询矩阵（build_daily_queries()）
intel_processor.py 去重 + 评分 + 解剖卡 + 看板/日报渲染（纯标准库，幂等）
raw_YYYYMMDD.json  每日采集原始数据（含 problems / problem_type 标注）
intel_db.jsonl     累积解剖卡（每行一张）
index.html         可视化解剖看板（GitHub Pages 入口）
daily_report_*.md  当日增量日报
```

## 本地运行

```bash
cd intel
python3 intel_processor.py          # 用 raw_*.json 重新生成看板
```

采集（每日自动化执行，无需手工）：

1. `queries.py` 的 `build_daily_queries()` 展开查询矩阵
2. 对每条查询 WebSearch，结果编译为 `raw_YYYYMMDD.json`
3. 运行 `intel_processor.py` 生成 `index.html` + 日报
4. 推送本仓库（GitHub Pages 自动更新）

## 部署

仓库已开启 GitHub Pages（分支 `main`，根目录 `/`），线上地址：

https://tedvong894.github.io/yrd-mfg-intel/

数据全部来自公开网络，仅作短视频选题参考。
