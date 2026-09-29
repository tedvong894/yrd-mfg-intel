# -*- coding: utf-8 -*-
"""
长三角中小制造业案例情报平台 — 问题导向采集查询矩阵
定位：搜集「问题分析类案例」用作短视频素材（企业踩了哪些坑、怎么解剖）。
仅使用公开网络可检索关键词，不假设任何付费 API / 登录数据源。
"""

REGIONS = ["浙江", "江苏", "上海", "安徽", "长三角"]

# 问题导向查询模板（{r}=地区前缀）
# 覆盖 8 类典型经营问题，供短视频"解剖"选题
QUERY_TEMPLATES = [
    "{r} 制造企业 倒闭 关停 清盘 老板 案例",
    "{r} 工厂 亏损 增收不增利 原因 复盘",
    "{r} 制造业 订单流失 外贸下滑 应对 分析",
    "{r} 制造企业 转型失败 智能化 踩坑 教训",
    "{r} 工厂 质量事故 召回 客户投诉 问题",
    "{r} 制造企业 欠款 欠薪 劳资纠纷 跑路",
    "{r} 工厂 库存积压 资金链 现金流 断裂",
    "{r} 中小企业 经营困难 倒闭 深度 复盘",
]


def build_daily_queries():
    qs, seen = [], set()
    for tpl in QUERY_TEMPLATES:
        if "{r}" in tpl:
            for r in REGIONS:
                q = tpl.replace("{r}", r)
                if q not in seen:
                    seen.add(q)
                    qs.append(q)
        else:
            if tpl not in seen:
                seen.add(tpl)
                qs.append(tpl)
    return qs


if __name__ == "__main__":
    for i, q in enumerate(build_daily_queries(), 1):
        print(f"{i:2d}. {q}")
