#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把「云端的权威数据」同步到本地，避免本地用旧数据覆盖云端新增（防数据回退）。
同步内容：intel_db.jsonl（按 card_id 并集）、manifest.json（processed 并集）、缺失的 raw_*.json。
用法：export no_proxy='*'; unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
      python3 sync_cloud.py
"""
import base64
import json
import os
import subprocess
import sys

REPO = "tedvong894/yrd-mfg-intel"
HERE = os.path.dirname(os.path.abspath(__file__))


def gh(args):
    return subprocess.run(["gh", "api", *args], capture_output=True, text=True)


def list_remote(path=""):
    r = gh([f"repos/{REPO}/contents/{path}", "--jq", ".[].name"])
    if r.returncode != 0:
        return []
    return [x for x in r.stdout.split("\n") if x.strip()]


def fetch_text(path):
    r = gh([f"repos/{REPO}/contents/{path}", "--jq", ".content"])
    if r.returncode != 0:
        return None
    b64 = "".join(r.stdout.split())
    try:
        return base64.b64decode(b64).decode("utf-8")
    except Exception:
        return None


def union_jsonl(fname):
    remote = fetch_text(fname)
    if remote is None:
        print(f"[skip] 云端无 {fname}，保留本地")
        return
    seen, merged = set(), []
    for line in (remote + "\n" + (open(os.path.join(HERE, fname), encoding="utf-8").read()
                                  if os.path.exists(os.path.join(HERE, fname)) else "")).splitlines():
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
    with open(os.path.join(HERE, fname), "w", encoding="utf-8") as f:
        for obj in merged:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    print(f"[sync] {fname}: 并集 {len(merged)} 条")


def union_manifest():
    fname = "manifest.json"
    remote = fetch_text(fname)
    lp = os.path.join(HERE, fname)
    local = {}
    if os.path.exists(lp):
        try:
            local = json.load(open(lp, encoding="utf-8"))
        except Exception:
            local = {}
    remote_obj = {}
    if remote:
        try:
            remote_obj = json.loads(remote)
        except Exception:
            remote_obj = {}
    processed = sorted(set(local.get("processed", [])) | set(remote_obj.get("processed", [])))
    out = {"processed": processed, "last_run": local.get("last_run") or remote_obj.get("last_run")}
    json.dump(out, open(lp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[sync] {fname}: 已处理文件 {len(processed)} 个")


def pull_missing_raw():
    import intel_processor as ipro
    names = [n for n in list_remote() if n.startswith("raw_") and n.endswith(".json")]
    for n in names:
        lp = os.path.join(HERE, n)
        remote = fetch_text(n)
        if remote is None:
            continue
        try:
            remote_items = json.loads(remote)
        except Exception:
            continue
        if not os.path.exists(lp):
            json.dump(remote_items, open(lp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            print(f"[sync] 拉取缺失 {n}（{len(remote_items)} 条）")
            continue
        # 已存在则并集
        try:
            local_items = json.load(open(lp, encoding="utf-8"))
        except Exception:
            local_items = []
        seen = {ipro.card_id(x) for x in local_items}
        added = 0
        for it in remote_items:
            if ipro.card_id(it) not in seen:
                local_items.append(it)
                seen.add(ipro.card_id(it))
                added += 1
        if added:
            json.dump(local_items, open(lp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            print(f"[sync] 合并 {n}：云端补入 {added} 条")


if __name__ == "__main__":
    print("[sync] 开始从云端同步权威数据…")
    union_jsonl("intel_db.jsonl")
    union_manifest()
    pull_missing_raw()
    print("[sync] 完成")
    sys.exit(0)
