#!/bin/zsh
# followup.sh [daily|weekly]
# Resume the most recent scheduled watcher run INTERACTIVELY — full context loaded
# (positions, computed triggers, alerts). This is where you place orders: you are
# present, so normal interactive permissions apply and ib_async is available.
#
# MODEL: Opus 4.8, HIGH thinking — order decisions deserve maximal reasoning. Calls the
# real binary directly with explicit model + thinking + the step-by-step nudge (rather
# than the ~/.local/bin/claude wrapper, so the config is explicit and controlled).
emulate -L zsh
set -u

KIND=${1:-daily}
DIR=${0:A:h}
SFILE="$DIR/state/last-$KIND-session"
NUDGE=/Users/shawn/.claude/thinking-nudge.txt

if [[ ! -f "$SFILE" ]]; then
  echo "No saved $KIND session yet (expected $SFILE). Has the scheduled run fired?" >&2
  exit 1
fi
SID="$(< "$SFILE")"
echo "Resuming $KIND watcher session $SID (Opus 4.8, high thinking) ..." >&2
export MAX_THINKING_TOKENS=32000   # high
cd /Users/shawn/vaults/trading-kb
if [[ -f "$NUDGE" ]]; then
  exec /opt/homebrew/bin/claude -r "$SID" --model claude-opus-4-8 --append-system-prompt-file "$NUDGE"
else
  exec /opt/homebrew/bin/claude -r "$SID" --model claude-opus-4-8
fi
