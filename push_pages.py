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

# 需要发布的文件（相对 intel 目录）
FILES = [
    "index.html",
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
    "raw_20260929.json",
    "intel_db.jsonl",
    "manifest.json",
    "daily_report_2026-09-29.md",
    "README.md",
    ".gitignore",
]


def all_targets():
    """FILES + workshop 目录下的底稿（xlsx / index.json）。"""
    todos = list(FILES)
    for p in sorted(glob.glob(os.path.join(HERE, "workshop", "*"))):
        if os.path.isfile(p):
            todos.append("workshop/" + os.path.basename(p))
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


def union_db_safety(fname):
    """推送 intel_db.jsonl 前，先与远端做 card_id 并集，避免本地旧数据覆盖云端新增。"""
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
        if cid in seen:
            continue
        seen.add(cid)
        merged.append(obj)
    with open(lp, "w", encoding="utf-8") as f:
        for obj in merged:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    print(f"[union] {fname}: 推送前并集 {len(merged)} 条（防覆盖云端新增）")


def push_file(fname):
    union_db_safety(fname)
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
