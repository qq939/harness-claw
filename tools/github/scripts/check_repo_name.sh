#!/usr/bin/env bash
# 校验当前仓库的远程名是否符合平台约定：必须以 harness 开头。
#   用法：bash tools/github/scripts/check_repo_name.sh [remote]   # 默认 origin
#   退出码：0 合规 / 1 不合规 / 2 没有该远程
set -u

remote="${1:-origin}"
url="$(git remote get-url "$remote" 2>/dev/null || true)"

if [ -z "$url" ]; then
  echo "没有远程 $remote" >&2
  exit 2
fi

name="$(printf '%s' "$url" | sed -E 's#.*/##; s#\.git$##')"

case "$name" in
  harness*)
    echo "OK: $remote -> $name"
    exit 0
    ;;
  *)
    echo "不合规: $remote -> $name（远程仓库名必须以 harness 开头，例如 harness-xxx）" >&2
    echo "改名后执行: git remote set-url $remote <新地址>" >&2
    exit 1
    ;;
esac
