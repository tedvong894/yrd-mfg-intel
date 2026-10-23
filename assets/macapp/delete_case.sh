#!/bin/bash
# 供原生 App 调用：把案例登记到仓库的「永久删除名单」，并触发云端流水线物理清除。
#   用法：delete_case.sh <card_id>
# 输出约定（App 逐行读取）：
#   普通行 → 进度提示
#   OK ...     → 成功
#   FAILED ... → 失败
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
GH="$(command -v gh || echo /opt/homebrew/bin/gh)"
REPO="tedvong894/yrd-mfg-intel"
WF="refresh.yml"

# 直连（绕开本机代理，否则 github 被拦）
export no_proxy='*'
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

CID="$1"
if [ -z "$CID" ]; then
  echo "FAILED 缺少案例 ID"
  exit 1
fi

export CID GH_BIN="$GH" REPO_NAME="$REPO" WF_NAME="$WF"
python3 <<'PY'
import base64, json, os, re, subprocess, sys, time

REPO = os.environ.get("REPO_NAME", "tedvong894/yrd-mfg-intel")
WF = os.environ.get("WF_NAME", "refresh.yml")
GH = os.environ.get("GH_BIN", "gh")
CID = os.environ.get("CID", "").strip()


def gh(args, input_text=None, raw=False):
    cmd = [GH, "api"]
    if raw:
        cmd += ["-H", "Accept: application/vnd.github.raw"]
    cmd += args
    if input_text is not None:
        cmd += ["--input", "-"]
        return subprocess.run(cmd, input=input_text, capture_output=True, text=True)
    return subprocess.run(cmd, capture_output=True, text=True)


def get_json(path):
    r = gh([f"repos/{REPO}/contents/{path}", "--jq", ".content"])
    if r.returncode != 0:
        return None, None
    try:
        txt = base64.b64decode("".join(r.stdout.split())).decode("utf-8")
        obj = json.loads(txt)
    except Exception:
        return None, None
    s = gh([f"repos/{REPO}/contents/{path}", "--jq", ".sha"]).stdout.strip()
    return obj, (s or None)


def put_json(path, obj, sha):
    body = {
        "message": f"del: 永久删除案例 {CID}",
        "content": base64.b64encode(json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")).decode("ascii"),
    }
    if sha:
        body["sha"] = sha
    r = gh([f"repos/{REPO}/contents/{path}", "-X", "PUT"], input_text=json.dumps(body))
    return r.returncode == 0, r.stderr


def norm_title(t):
    return re.sub(r"[^\w一-鿿]", "", (t or "").lower())


if not CID:
    print("FAILED 缺少案例 ID")
    sys.exit(1)

print(f"正在永久删除案例 {CID}…")

# ① 取出该卡标题（用于连带清除同题转载版）
title_raw = ""
r = gh([f"repos/{REPO}/contents/intel_db.jsonl"], raw=True)
if r.returncode == 0:
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("card_id") == CID:
            title_raw = o.get("title") or ""
            break
if not title_raw:
    print("未在案例库中找到该 ID（可能已被删除）")

# ② 写入删除名单（cid + 标题）
ids, sha_ids = get_json("deleted_ids.json")
if ids is None:
    ids = []
if CID not in ids:
    ids.append(CID)
ok, err = put_json("deleted_ids.json", sorted(ids), sha_ids)
if not ok:
    print(f"FAILED 无法写入删除名单：{err[:120]}")
    sys.exit(1)
print("已登记删除名单（card_id）")

tids, sha_t = get_json("deleted_titles.json")
if tids is None:
    tids = []
tkey = norm_title(title_raw)
if tkey and tkey not in tids:
    tids.append(tkey)
    ok, err = put_json("deleted_titles.json", sorted(tids), sha_t)
    if not ok:
        print(f"FAILED 无法写入标题黑名单：{err[:120]}")
        sys.exit(1)
    print("已登记标题黑名单（连带同题转载版）")

# ③ 触发云端流水线：物理清除（库 + 原始池）并重建站点
print("正在触发云端永久清除…")
if subprocess.run([GH, "workflow", "run", WF, "--repo", REPO],
                  capture_output=True, text=True).returncode != 0:
    print("FAILED 无法触发云端任务（gh 未登录或无权限）")
    sys.exit(1)

st = concl = ""
for _ in range(70):
    info = subprocess.run([GH, "run", "list", "--repo", REPO, "--workflow", WF, "--limit", "1",
                           "--json", "status,conclusion", "--jq", '.[0] | "\(.status) \(.conclusion)"'],
                          capture_output=True, text=True).stdout.strip()
    parts = info.split()
    st = parts[0] if parts else ""
    concl = parts[1] if len(parts) > 1 else ""
    if st == "completed":
        break
    print("云端清除进行中…")
    time.sleep(8)

if st != "completed":
    print("FAILED 云端任务超时")
    sys.exit(1)
if concl != "success":
    print(f"FAILED 云端任务结束：{concl}")
    sys.exit(1)

print("OK 已从数据源永久删除（库与原始池均已清除）")
PY
