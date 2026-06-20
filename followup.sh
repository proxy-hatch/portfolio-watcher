#!/bin/zsh
# followup.sh [daily|weekly] [extra claude args...]
# Resume the most recent scheduled watcher run INTERACTIVELY — full context loaded
# (positions, computed triggers, alerts). This is where you place orders: you are
# present, so normal interactive permissions apply and ib_async is available.
#
# By DEFAULT this passes --dangerously-skip-permissions to claude, so the resumed session
# auto-approves every tool call with no prompt — including ib_async ORDER PLACEMENT. That's
# the intended ergonomics: you resume to act (often AFK from the phone) and don't want to
# tap-approve each step. Pass --safe (or -s) to restore normal interactive permission
# prompts. Any other args after the kind are forwarded verbatim to claude.
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

# Skip-permissions is the DEFAULT; --safe/-s opts back into normal prompts. --yolo/-y is
# accepted as an explicit (now redundant) opt-in so older shortcuts don't break. Everything
# else is forwarded verbatim to claude.
typeset -a CLAUDE_ARGS=()
skip=1
for a in "$@"; do
  case "$a" in
    --safe|-s) skip=0 ;;
    --yolo|-y) skip=1 ;;
    *)         CLAUDE_ARGS+=("$a") ;;
  esac
done
(( skip )) && CLAUDE_ARGS=(--dangerously-skip-permissions "${CLAUDE_ARGS[@]}")

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
