#!/bin/zsh
# notify.sh <title> <message> [priority]
# macOS banner (always) + ntfy.sh phone push (if a topic is configured).
emulate -L zsh
set -u

TITLE=${1:-"Portfolio Watcher"}
MSG=${2:-""}
PRIO=${3:-default}
DIR=${0:A:h}

# macOS banner — strip double-quotes so the AppleScript string can't break.
SAFE_TITLE=${TITLE//\"/}
SAFE_MSG=${MSG//\"/}
/usr/bin/osascript -e "display notification \"${SAFE_MSG}\" with title \"${SAFE_TITLE}\"" 2>/dev/null || true

# ntfy.sh push
TOPIC_FILE="$DIR/secrets/ntfy-topic"
if [[ -f "$TOPIC_FILE" ]]; then
  TOPIC="$(< "$TOPIC_FILE")"
  if [[ -n "$TOPIC" ]]; then
    /usr/bin/curl -fsS --max-time 10 \
      -H "Title: ${TITLE}" -H "Priority: ${PRIO}" -H "Tags: chart_with_upwards_trend,moneybag" \
      -d "${MSG}" "https://ntfy.sh/${TOPIC}" >/dev/null 2>&1 || true
  fi
fi
