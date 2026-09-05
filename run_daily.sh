#!/usr/bin/env bash
set -uo pipefail

cd "$(dirname "$0")" || exit 1

export TZ=Asia/Taipei

UV="$HOME/.local/bin/uv"
KEYWORDS=(backend full-stack "software engineer" "ai engineer")
PAGES=4

if [[ ! -x "$UV" ]]; then
    echo "找不到 uv（$UV）—— cron 的 PATH 是空的，這裡要絕對路徑" >&2
    exit 1
fi

mkdir -p logs
LOG="logs/$(date +%Y%m%d).log"

{
    echo "########## $(date '+%F %T') 開始 ##########"
    for kw in "${KEYWORDS[@]}"; do
        echo
        echo "===== $kw（$PAGES 頁）====="
        "$UV" run pipeline.py "$kw" "$PAGES"
    done
    echo
    echo "########## $(date '+%F %T') 結束 ##########"
} >> "$LOG" 2>&1

# log 留 30 天
find logs -name '*.log' -mtime +30 -delete
