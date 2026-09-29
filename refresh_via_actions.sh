#!/bin/bash
# 供原生 App 调用：触发 GitHub Actions 云端增量采集，并等待站点更新完成。
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

BEFORE="$("$GH" api "repos/$REPO/commits/main" --jq .sha 2>/dev/null)"

echo "正在触发云端采集任务…"
if ! "$GH" workflow run "$WF" --repo "$REPO" >/dev/null 2>&1; then
  echo "FAILED 无法触发云端任务（gh 未登录或无 workflow 权限）"
  exit 1
fi

sleep 6
info=""; st=""; concl=""
for i in $(seq 1 70); do
  info="$("$GH" run list --repo "$REPO" --workflow="$WF" --limit 1 \
          --json status,conclusion,databaseId --jq '.[0] | "\(.status) \(.conclusion)"' 2>/dev/null)"
  st="$(echo "$info" | awk '{print $1}')"
  concl="$(echo "$info" | awk '{print $2}')"
  if [ "$st" = "completed" ]; then break; fi
  echo "云端任务进行中…（$st）"
  sleep 8
done

if [ "$st" != "completed" ]; then
  echo "FAILED 云端任务超时未完成"
  exit 1
fi
if [ "$concl" != "success" ]; then
  echo "FAILED 云端任务结束：$concl"
  exit 1
fi

echo "采集完成，等待站点发布…"
for i in $(seq 1 30); do
  NOW="$("$GH" api "repos/$REPO/commits/main" --jq .sha 2>/dev/null)"
  if [ -n "$NOW" ] && [ "$NOW" != "$BEFORE" ]; then break; fi
  sleep 5
done
sleep 6
echo "OK 已更新"
