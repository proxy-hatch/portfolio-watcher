#!/bin/zsh
# run.sh <daily|weekly>
# Headless Portfolio Watcher run, invoked by launchd. Runs claude -p locally with
# Bash access (ibkr-cli reads + metrics.py), persists the session so it can be
# resumed interactively for order placement (see followup.sh), and pushes an alert
# if the run surfaces anything actionable.
emulate -L zsh
set -u

KIND=${1:-daily}
DIR=${0:A:h}
VAULT=/Users/shawn/vaults/trading-kb
PROMPTS="$VAULT/03-strategies/trend-following"
# MODEL: Sonnet 4.6, MEDIUM thinking — the watcher is mechanical (metrics.py does the
# heavy math deterministically; the model just interprets numbers vs thresholds and
# writes the log), so Sonnet is plenty and far cheaper than Opus. The interactive
# followup (order decisions) uses Opus 4.8 high — see followup.sh.
# Call the REAL binary directly, bypassing ~/.local/bin/claude — that wrapper forces
# MAX_THINKING_TOKENS=63999 / effort=max / adaptive-thinking OFF on every turn, which
# would make this multi-step job take 30-60+ min.
CLAUDE=/opt/homebrew/bin/claude
CLAUDE_MODEL=claude-sonnet-4-6
CLAUDE_TIMEOUT=900   # hard wall-clock cap (s) so a stalled API turn can't hang the job
export HOME=/Users/shawn
export PATH=/Users/shawn/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
export MAX_THINKING_TOKENS=10000   # medium; adaptive thinking left ON (do NOT set
                                   # ALWAYS_ENABLE_EFFORT / DISABLE_ADAPTIVE)

case "$KIND" in
  daily)  PROMPT="$PROMPTS/Portfolio Watcher Daily Close Prompt.md" ;;
  weekly) PROMPT="$PROMPTS/Portfolio Watcher Weekly Review Prompt.md" ;;
  *) echo "usage: run.sh <daily|weekly>" >&2; exit 64 ;;
esac

TS="$(date +%Y%m%d-%H%M%S)"
LOGDIR="$DIR/logs"
OUT="$LOGDIR/$KIND-$TS.json"
ERR="$LOGDIR/$KIND-$TS.err"
mkdir -p "$LOGDIR" "$DIR/state"

# --- IB Gateway readiness: TCP probe (daily 16:30 / weekly 09:00 are far from the
#     23:59 Taipei restart, so this should normally pass). Informational only. ---
if ! /usr/bin/nc -z -G 5 127.0.0.1 4001 2>/dev/null; then
  echo "[$(date)] WARN: gateway TCP 127.0.0.1:4001 not accepting — running anyway" >> "$ERR"
fi

# --- Mint a session id up front so we own it regardless of how the run exits ---
SID="$(/usr/bin/uuidgen)"
echo "$SID" > "$DIR/state/last-$KIND-session"
echo "[$(date)] $KIND run start — session $SID" >> "$LOGDIR/$KIND.log"

# --- Keep the scheduled run LEAN: no skills / task-tools / tool-search / scratch
#     scripts; just use metrics.py + ibkr and write the log. ---
LEAN="UNATTENDED SCHEDULED RUN. Execute the task prompt directly and efficiently. \
Do not write scratch scripts to /tmp — use the provided metrics.py and ibkr-cli for \
all data and computation. No preamble or meta-commentary. Under no circumstance do \
you place, modify, or cancel any order. Finish by writing the run-log file the prompt \
specifies."

# --- Headless run, backgrounded under a watchdog. Read-only-by-policy: prompt is
#     recommend-only; venv python IS on the allowlist (user's choice) so the boundary
#     is the prompt instruction, not the permission system. cd into the vault so this
#     session shares a project root with the interactive resume (followup.sh). ---
cd "$VAULT" || { echo "[$(date)] cannot cd $VAULT" >> "$ERR"; exit 70; }

# LEAN is prepended to the prompt text (can't use --append-system-prompt: the global
# config already injects --append-system-prompt-file and the two can't combine).
"$CLAUDE" -p "${LEAN}

---

$(cat "$PROMPT")" \
  --model "$CLAUDE_MODEL" \
  --session-id "$SID" \
  --add-dir "$VAULT" \
  --settings "$DIR/watcher-settings.json" \
  --permission-mode acceptEdits \
  --disallowed-tools Task TaskCreate TaskUpdate TaskOutput TaskList TaskGet TaskStop Skill ToolSearch \
  --output-format json \
  --max-turns 80 \
  > "$OUT" 2>> "$ERR" &
CPID=$!

# watchdog: kill the run if it exceeds the wall-clock cap
( sleep "$CLAUDE_TIMEOUT"
  if kill -0 "$CPID" 2>/dev/null; then
    echo "[$(date)] TIMEOUT after ${CLAUDE_TIMEOUT}s — killing $CPID" >> "$ERR"
    kill "$CPID" 2>/dev/null; sleep 5; kill -9 "$CPID" 2>/dev/null
  fi ) &
WPID=$!

wait "$CPID"; RC=$?
kill "$WPID" 2>/dev/null   # cancel watchdog if the run finished first

RESULT="$(/usr/bin/jq -r '.result // .text // empty' "$OUT" 2>/dev/null)"
echo "[$(date)] $KIND run end rc=$RC" >> "$LOGDIR/$KIND.log"

FOLLOWUP="watcher-followup $KIND"

if [[ $RC -ne 0 || -z "$RESULT" ]]; then
  "$DIR/notify.sh" "Watcher $KIND FAILED" "Run errored (rc=$RC). Check logs/$KIND-$TS.err then: $FOLLOWUP" high
  exit $RC
fi

# --- Alert thresholds: push to phone on URGENT or an open action window;
#     macOS banner always so you know it ran. ---
TODAY_LOG="$VAULT/05-trades/portfolio-watcher-runs/$(date +%Y-%m-%d).md"
SCAN="$RESULT"
[[ -f "$TODAY_LOG" ]] && SCAN="$SCAN
$(cat "$TODAY_LOG")"

if print -r -- "$SCAN" | grep -qiE "🚨|URGENT ALERT"; then
  HEAD="$(print -r -- "$SCAN" | grep -iE "🚨|URGENT" | head -3 | tr '\n' ' ')"
  "$DIR/notify.sh" "🚨 Watcher $KIND URGENT" "${HEAD:0:300} → $FOLLOWUP" urgent
elif print -r -- "$SCAN" | grep -qiE "📈|window open|ACTION REQUIRED"; then
  "$DIR/notify.sh" "Watcher $KIND — action window" "Actionable signal. Resume: $FOLLOWUP" high
else
  "$DIR/notify.sh" "Watcher $KIND ✓" "Ran clean, no actions. Resume anytime: $FOLLOWUP" low
fi

exit 0
