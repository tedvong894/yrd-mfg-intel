# -*- coding: utf-8 -*-
"""
长三角中小制造业案例情报平台 — 问题导向采集查询矩阵
定位：搜集「问题分析类案例」用作短视频素材（企业踩了哪些坑、怎么解剖）。
仅使用公开网络可检索关键词，不假设任何付费 API / 登录数据源。
"""

REGIONS = ["浙江", "江苏", "上海", "安徽", "长三角"]

# 搜集角度查询模板（{r}=地区前缀）
# 2026-10-15 改：从 6 个经营分析角度寻找案例
QUERY_TEMPLATES = [
    "{r} 企业 经营状况 变化 盈亏 业绩 下滑 案例",
    "{r} 企业 扩产 设备投资 产能过剩 盲目扩张 失误",
    "{r} 企业 应收账款 资金压力 账期 回款 困难",
    "{r} 企业 库存 成本管理 损耗 呆滞 占用",
    "{r} 企业 转型 经营决策 收缩 多元化 失误",
    "{r} 企业 经营困难 原因 复盘 困境 案例",
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
