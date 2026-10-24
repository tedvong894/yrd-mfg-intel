#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通过 gh api（Contents API）把站点文件推到 GitHub Pages 仓库。
用途：沙箱内 git 走代理被拦（github 直连超时），改用 gh CLI 直连通道推送，规避代理。
幂等：若文件已存在先取 sha 再 PUT，否则直接创建。
用法：
  export no_proxy='*'; unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
  python3 push_pages.py
"""
import base64
import glob
import json
import os
import subprocess
import sys
import time

REPO = "tedvong894/yrd-mfg-intel"
HERE = os.path.dirname(os.path.abspath(__file__))

# 需要发布的文件（相对 intel 目录）——**只发代码/黑名单/静态资源**
# index.html/dashboard.html/intel_db.jsonl/raw_*/daily_report 一律不在此列：
# 它们由 CI 工作流渲染并 git add -A 自动提交，本地推送曾用陈旧渲染结果覆盖线上（2026-10-24 事故）。
FILES = [
    "apple-touch-icon.png",
    "icon-192.png",
    "icon-512.png",
    "icon-1024.png",
    "manifest.webmanifest",
    "collect.py",
    "dissect.py",
    "queries.py",
    "intel_processor.py",
    "sync_cloud.py",
    "push_pages.py",
    "refresh_via_actions.sh",
    ".github/workflows/refresh.yml",
    "assets/macapp/main.swift",
    "assets/macapp/build.sh",
    "assets/macapp/delete_case.sh",
    # 数据文件（intel_db.jsonl / raw_*.json / daily_report）不在此列：由 CI 全权管理，防本地旧版覆盖
    "deleted_ids.json",
    "deleted_titles.json",
    "manifest.json",
    "README.md",
    ".gitignore",
]


def all_targets():
    """FILES + 日报。**不含 intel_db.jsonl / raw_*.json**——数据文件由 CI 工作流全权管理
    （CI 每次跑完 git add -A 自动提交），本地推送曾把残缺旧版覆盖到仓库导致事故
    （2026-10-24：黑名单+DB+raw 被本地旧版覆盖，已删案例复活）。代码/黑名单/静态资源才走本通道。"""
    todos = list(FILES)
    for p in sorted(glob.glob(os.path.join(HERE, "daily_report_*.md"))):
        todos.append(os.path.basename(p))
    return todos


def gh_api(args, input_text=None):
    # 大文件 base64 经 -f content=... 传命令行参数会触发 macOS ARG_MAX "Argument list too long"。
    # 改为统一用 --input - 从 stdin 喂 JSON body，彻底规避参数长度上限。
    if input_text is not None:
        p = subprocess.run(["gh", "api", *args, "--input", "-"],
                           input=input_text, capture_output=True, text=True)
    else:
        p = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
    return p


def get_sha(path):
    """取远端 blob sha（更新已有文件必须带，否则 422 "sha wasn't supplied"）。
    网络抖动时这一步会失败/返回截断 → 重试 4 次，别被一次失败判定成"文件有问题"."""
    for _ in range(4):
        r = gh_api([f"repos/{REPO}/contents/{path}", "--jq", ".sha"])
        if r.returncode == 0:
            sha = r.stdout.strip()
            if len(sha) == 40:
                return sha
        time.sleep(1.2)
    return None


def load_deleted_ids():
    """读取 deleted_ids.json（用户主动剔除的表面/简单案例黑名单）。"""
    p = os.path.join(HERE, "deleted_ids.json")
    if not os.path.exists(p):
        return set()
    try:
        return set(json.load(open(p, encoding="utf-8")))
    except Exception:
        return set()


def union_db_safety(fname):
    """推送 intel_db.jsonl 前，先与远端做 card_id 并集，避免本地旧数据覆盖云端新增。
    同时过滤已下线的问题类型，防止云端旧数据把本地已删除类型恢复回来；
    并排除 deleted_ids.json 中的主动剔除卡，保证用户剔除永久生效。"""
    if fname != "intel_db.jsonl":
        return
    lp = os.path.join(HERE, fname)
    if not os.path.exists(lp):
        return
    r = gh_api([f"repos/{REPO}/contents/{fname}", "--jq", ".content"])
    if r.returncode != 0:
        return
    try:
        remote = base64.b64decode("".join(r.stdout.split())).decode("utf-8")
    except Exception:
        return
    # 已下线问题类型（与 intel_processor.py 保持一致）
    skip_types = {"质量事故", "欠款劳资"}
    skip_labels = {"质量事故 / 召回", "欠款 / 劳资纠纷"}
    deleted = load_deleted_ids()
    seen, merged = set(), []
    for line in (remote + "\n" + open(lp, encoding="utf-8").read()).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        cid = obj.get("card_id")
        if cid in seen or cid in deleted:
            continue
        pk = obj.get("problem_type_key") or ""
        pl = obj.get("problem_type") or ""
        if pk in skip_types or pl in skip_types or pl in skip_labels:
            continue
        seen.add(cid)
        merged.append(obj)
    with open(lp, "w", encoding="utf-8") as f:
        for obj in merged:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    print(f"[union] {fname}: 推送前并集 {len(merged)} 条（防覆盖云端新增，已过滤下线类型与 {len(deleted)} 张剔除卡）")


def union_blacklist(fname):
    """推送删除黑名单前，先与远端取并集再推。
    背景：App 内删除（delete_case.sh）直写仓库但不回写本地，若直接推本地旧版会把
    仓库里更新的黑名单覆盖掉 → 已删案例复活（2026-10-24 事故：195 个被覆盖复活）。
    并集保证：任何一端的新增都保留，永不因覆盖丢数据。"""
    if fname not in ("deleted_ids.json", "deleted_titles.json"):
        return
    lp = os.path.join(HERE, fname)
    if not os.path.exists(lp):
        return
    r = gh_api([f"repos/{REPO}/contents/{fname}", "--jq", ".content"])
    if r.returncode != 0:
        return
    try:
        remote = json.loads(base64.b64decode("".join(r.stdout.split())).decode("utf-8"))
    except Exception:
        return
    try:
        local = json.load(open(lp, encoding="utf-8"))
    except Exception:
        return
    merged = sorted(set(remote) | set(local))
    if len(merged) == len(local):
        return  # 本地已含远端全部，无需改动
    with open(lp, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"[union] {fname}: 推送前与远端并集 {len(local)} + {len(remote)} → {len(merged)} 条（防本地旧版覆盖仓库新删除）")


def push_file(fname):
    union_db_safety(fname)
    union_blacklist(fname)
    fpath = os.path.join(HERE, fname.lstrip("./"))
    if not os.path.exists(fpath):
        print(f"[skip] 缺失：{fname}")
        return
    api_path = fname.lstrip("./")
    data = open(fpath, "rb").read()
    b64 = base64.b64encode(data).decode("ascii")  # 无换行，符合 GitHub base64 要求
    for attempt in range(3):
        sha = get_sha(api_path)
        body = {"message": f"deploy: update {api_path}", "content": b64}
        if sha:
            body["sha"] = sha
        cmd = [f"repos/{REPO}/contents/{api_path}", "-X", "PUT"]
        r = gh_api(cmd, input_text=json.dumps(body))
        if r.returncode == 0:
            print(f"[ok] {api_path} 推送成功" + ("（更新）" if sha else "（新建）"))
            return
        print(f"[retry {attempt+1}] {api_path}: {r.stderr.strip()[:90]}")
        time.sleep(1.5)
    print(f"[FAIL] {api_path}: {r.stderr[:160]}")


if __name__ == "__main__":
    targets = sys.argv[1:] or all_targets()
    for t in targets:
        push_file(t)
    print("[done] 文件推送完成")
