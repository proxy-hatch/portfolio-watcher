#!/bin/zsh
# followup.sh [daily|weekly] [extra claude args...]
# Resume the most recent scheduled watcher run INTERACTIVELY — full context loaded
# (positions, computed triggers, alerts). This is where you place orders: you are
# present, so normal interactive permissions apply and ib_async is available.
#
# Any args after the kind are forwarded verbatim to `claude`, with one convenience alias:
#   --yolo | -y  →  --dangerously-skip-permissions
# That makes the session auto-approve EVERY tool call with no prompt — including ib_async
# ORDER PLACEMENT. Handy AFK from the phone, but it removes the per-action confirmation, so
# only use it when you intend to let the session act unattended. (e.g. `watcher-followup
# daily --yolo`, or via `wf daily --yolo`.)
#
# MODEL: Opus 4.8, HIGH thinking — order decisions deserve maximal reasoning. Calls the
# real binary directly with explicit model + thinking + the step-by-step nudge (rather
# than the ~/.local/bin/claude wrapper, so the config is explicit and controlled).
emulate -L zsh
set -u

KIND=${1:-daily}
(( $# )) && shift                  # drop the kind; the rest pass through to claude
DIR=${0:A:h}
SFILE="$DIR/state/last-$KIND-session"
NUDGE=/Users/shawn/.claude/thinking-nudge.txt

# Forward extra args to claude, translating the --yolo/-y convenience alias.
typeset -a CLAUDE_ARGS=()
for a in "$@"; do
  case "$a" in
    --yolo|-y) CLAUDE_ARGS+=(--dangerously-skip-permissions) ;;
    *)         CLAUDE_ARGS+=("$a") ;;
  esac
done

if [[ ! -f "$SFILE" ]]; then
  echo "No saved $KIND session yet (expected $SFILE). Has the scheduled run fired?" >&2
  exit 1
fi
SID="$(< "$SFILE")"
echo "Resuming $KIND watcher session $SID (Opus 4.8, high thinking) ..." >&2
export MAX_THINKING_TOKENS=32000   # high
cd /Users/shawn/vaults/trading-kb
if [[ -f "$NUDGE" ]]; then
  exec /opt/homebrew/bin/claude -r "$SID" --model claude-opus-4-8 --append-system-prompt-file "$NUDGE" "${CLAUDE_ARGS[@]}"
else
  exec /opt/homebrew/bin/claude -r "$SID" --model claude-opus-4-8 "${CLAUDE_ARGS[@]}"
fi
