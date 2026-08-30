#!/bin/zsh
# run.sh <daily|weekly>
#
# v3 AUTONOMOUS pipeline. No human step in the recurring loop.
#
#   1. v3_engine.py   — deterministic targets (indicators, leverage, drift)
#   2. v3_execute.py  — DRY RUN: deterministic order plan, rails applied
#   3. claude -p      — reviews the plan against the playbook; emits APPROVE or HALT.
#                       The model is a CIRCUIT BREAKER, not a trader: it cannot change
#                       a quantity, price or symbol — only allow or stop the run.
#   4. v3_execute.py --live  (only if the model APPROVED and the plan is non-empty)
#   5. notify         — reports what happened. Notification, not a request for approval.
#
# Safety lives in v3_execute.py's rails (whitelist, account map, notional clamps,
# idempotency, kill switch). A hallucinated APPROVE still cannot exceed them.
emulate -L zsh
set -u

KIND=${1:-daily}
DIR=${0:A:h}
VAULT=/Users/shawn/vaults/trading-kb
PROMPTS="$VAULT/03-strategies/trend-following"
CLAUDE=/opt/homebrew/bin/claude
PY="$DIR/.venv/bin/python"
export HOME=/Users/shawn
export PATH=/Users/shawn/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin

case "$KIND" in
  # Opus 5 at MEDIUM thinking for both. Verified available 2026-08-26 (fable-5 was NOT —
  # it 401'd then 429'd every Saturday from Jul 24, which is why the weekly never ran).
  # Weekly keeps the longer watchdog because it reads a full week of logs.
  daily)  PROMPT="$PROMPTS/Portfolio Watcher Daily Close Prompt.md"
          CLAUDE_MODEL=claude-opus-5; THINK=10000; CLAUDE_TIMEOUT=1500 ;;
  weekly) PROMPT="$PROMPTS/Portfolio Watcher Weekly Review Prompt.md"
          CLAUDE_MODEL=claude-opus-5; THINK=10000; CLAUDE_TIMEOUT=1800 ;;
  *) echo "usage: run.sh <daily|weekly>" >&2; exit 64 ;;
esac
export MAX_THINKING_TOKENS="$THINK"


TS="$(date +%Y%m%d-%H%M%S)"
LOGDIR="$DIR/logs"; mkdir -p "$LOGDIR" "$DIR/state"
OUT="$LOGDIR/$KIND-$TS.json"; ERR="$LOGDIR/$KIND-$TS.err"
TARGETS="$LOGDIR/$KIND-$TS.targets.json"; PLAN="$LOGDIR/$KIND-$TS.plan.txt"
PLANJSON="$LOGDIR/$KIND-$TS.plan.json"

SID="$(/usr/bin/uuidgen)"
# Human-readable label so a session is findable in history months later.
# Format: <kind>-<run date>-<HHMM>  e.g. daily-2026-08-26-0900
LABEL="$KIND-$(date +%Y-%m-%d-%H%M)"
echo "$SID" > "$DIR/state/last-$KIND-session"
printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%Y-%m-%d %H:%M:%S %z')" "$KIND" "$SID" "$LABEL" "RUNNING" \
  >> "$DIR/state/sessions.tsv"
echo "[$(date)] $KIND run start — $LABEL — session $SID" >> "$LOGDIR/$KIND.log"

# stamp the final outcome onto this run's row (called at every exit path)
stamp() { /usr/bin/python3 "$DIR/stamp_session.py" "$DIR/state/sessions.tsv" "$SID" "$1" 2>/dev/null || true; }

# say(): progress to the TERMINAL as well as the log. Without this a `wf run` pane sits
# blank for the whole ~20-min job and looks hung.
say() { print -r -- "$(date '+%H:%M:%S')  $*"; echo "[$(date)] $*" >> "$LOGDIR/$KIND.log"; }
say "=== $LABEL  ($KIND run, session ${SID[1,8]}) ==="

say "1/5 checking IB Gateway on 127.0.0.1:4001 ..."
if ! /usr/bin/nc -z -G 5 127.0.0.1 4001 2>/dev/null; then
  echo "[$(date)] gateway TCP 4001 unreachable — aborting before any trading" >> "$ERR"
  stamp "FAILED-gateway"
  "$DIR/notify.sh" "🚨 Watcher $KIND — gateway down" "No IBKR connection; no orders placed." urgent
  exit 69
fi

# ---------- 1. deterministic targets ----------------------------------------
say "2/5 computing targets (v3_engine.py) ..."
if ! "$PY" "$DIR/v3_engine.py" --json > "$TARGETS" 2>>"$ERR"; then
  RC=$?
  echo "[$(date)] v3_engine failed rc=$RC" >> "$ERR"
  stamp "FAILED-engine"
  "$DIR/notify.sh" "🚨 Watcher $KIND — engine failed" "v3_engine rc=$RC (stale data or IBKR). No orders." urgent
  exit $RC
fi

# ---------- 2. dry-run plan --------------------------------------------------
say "3/5 building order plan (dry run) ..."
"$PY" "$DIR/v3_execute.py" --save-plan "$PLANJSON" > "$PLAN" 2>>"$ERR"; PRC=$?
sed 's/^/      /' "$PLAN" 2>/dev/null | head -40
if [[ $PRC -eq 4 ]]; then
  stamp "HALTED-killswitch"
  "$DIR/notify.sh" "Watcher $KIND — auto-exec halted" "Kill switch set. Review then remove state/AUTOEXEC_OFF" high
  exit 4
fi

# The engine's exit code is part of the plan, not a detail. A non-zero code means
# NOTHING is executable, and the reviewer has to be told so explicitly: on
# 2026-08-29 a rc=2 funding refusal still presented three tidy BUY lines, and the
# only markers that anything was wrong (the BLOCKED line, the missing funding leg)
# were on a stream the prompt never pasted.
case $PRC in
  0) PLANSTATUS="OK — this plan is executable." ;;
  2) PLANSTATUS="REFUSED BY A RAIL (exit 2) — no plan artifact was written and NOTHING can execute this run. Read the BLOCKED line(s) above; your job is to log the refusal, not to approve." ;;
  3) PLANSTATUS="MALFUNCTION (exit 3) — the engine or an IBKR read failed. Nothing can execute." ;;
  *) PLANSTATUS="UNEXPECTED EXIT $PRC — treat as unsafe; nothing can execute." ;;
esac
say "    engine exit $PRC — ${PLANSTATUS%%.*}"

HAS_ORDERS=0
if [[ $PRC -eq 0 ]]; then
  grep -qE '^\s+(BUY|SELL)\s' "$PLAN" && HAS_ORDERS=1
fi

# ---------- 3. model as circuit breaker -------------------------------------
LEAN="UNATTENDED SCHEDULED RUN — v3 AUTONOMOUS MODE.

The order plan below was computed deterministically by v3_engine.py and v3_execute.py
from the approved Portfolio Playbook v3. You are a CIRCUIT BREAKER, not a trader.

You MUST NOT invent, resize, reprice or add orders. Your only decision is whether to
let this plan execute. Emit exactly one line, on its own, as the LAST line of your reply:
  VERDICT: APPROVE    — plan is consistent with the playbook and the market state
  VERDICT: HALT <reason>  — something is wrong; nothing will be placed

HALT if any of: the engine's regime gate contradicts the orders; a symbol is not in the
v3 playbook; drift/leverage numbers are internally inconsistent; data looks stale or the
NAV moved implausibly; there is a corporate action, halt, or catalyst that makes trading
unsafe today. When genuinely uncertain, HALT — a missed run costs far less than a wrong one.

Then do the normal task: write the run-log file the prompt specifies.
Do not place, modify or cancel orders yourself — execution is handled by the script.

=== ENGINE TARGETS ===
$(cat "$TARGETS")

=== DRY-RUN ORDER PLAN  (v3_execute.py exit ${PRC}) ===
$PLANSTATUS

$(cat "$PLAN")
"

say "4/5 review by $CLAUDE_MODEL (circuit breaker) — up to ${CLAUDE_TIMEOUT}s, no output until done ..."
TIMEOUT_FLAG="$LOGDIR/$KIND-$TS.timedout"
MSTART=$SECONDS
cd "$VAULT" || { echo "[$(date)] cannot cd $VAULT" >> "$ERR"; exit 70; }
"$CLAUDE" -p "${LEAN}

---

$(cat "$PROMPT")" \
  --model "$CLAUDE_MODEL" --session-id "$SID" --add-dir "$VAULT" \
  --settings "$DIR/watcher-settings.json" --permission-mode acceptEdits \
  --disallowed-tools Task TaskCreate TaskUpdate TaskOutput TaskList TaskGet TaskStop Skill ToolSearch \
  --output-format json --max-turns 80 > "$OUT" 2>> "$ERR" &
CPID=$!
# The watchdog leaves a marker. Without it a watchdog kill is indistinguishable
# from an auth failure: both produce rc!=0 and an empty result, and both used to be
# stamped FAILED-model. That mislabelling is why re-authenticating on 2026-08-29 did
# not help — that day's two failures were 20- and 30-minute hangs, not tokens.
( sleep "$CLAUDE_TIMEOUT"
  if kill -0 "$CPID" 2>/dev/null; then
    echo "[$(date)] TIMEOUT ${CLAUDE_TIMEOUT}s — killing model review (pid $CPID)" >> "$ERR"
    : > "$TIMEOUT_FLAG"
    kill "$CPID" 2>/dev/null; sleep 5; kill -9 "$CPID" 2>/dev/null
  fi ) &
WPID=$!
wait "$CPID"; RC=$?; kill "$WPID" 2>/dev/null
ELAPSED=$(( SECONDS - MSTART ))

RESULT="$(/usr/bin/jq -r '.result // .text // empty' "$OUT" 2>/dev/null)"
APIERR="$(/usr/bin/jq -r '.api_error_status // empty' "$OUT" 2>/dev/null)"
ISERR="$(/usr/bin/jq -r '.is_error // false' "$OUT" 2>/dev/null)"

# Distinguish "the model is UNREACHABLE" from "the model ran and withheld approval".
#   unreachable  -> infrastructure. The plan already passed every deterministic rail,
#                   so trade it, but at a TIGHTER cap and shout about it.
#   ran, no verdict -> the model was working and did not approve. Fail closed.
# Rationale: 4 model-layer failures in 5 weeks (401 x2, 429 credits, 429 session limit)
# vs 0 engine/rail failures. A circuit breaker that cannot change a number must not be
# a single point of failure for a system whose trading logic does not need it.
# A model outage is an OPERATOR problem, not a trading decision. If the model cannot be
# reached we place NOTHING and say so loudly — there is no unreviewed trading path.
# Classify precisely. The keyword scan runs ONLY when the CLI actually reported an
# error — otherwise a review that merely *discusses* a past rate limit would classify
# itself as an outage. Structured fields first, prose last.
FAILKIND=""; FAILFIX=""
if [[ -f "$TIMEOUT_FLAG" ]]; then
  FAILKIND="timeout"
  FAILFIX="review exceeded ${CLAUDE_TIMEOUT}s (killed by our own watchdog, not IBKR). See logs/$KIND-$TS.err; retry: wf run $KIND"
elif [[ "$APIERR" == 401* ]]; then
  FAILKIND="auth";  FAILFIX="token revoked/expired. Fix: claude /login, then: wf run $KIND"
elif [[ "$APIERR" == 429* ]]; then
  FAILKIND="quota"; FAILFIX="rate/session/credit limit. Retry after reset: wf run $KIND"
elif [[ -n "$APIERR" ]]; then
  FAILKIND="api";   FAILFIX="API error $APIERR. Retry: wf run $KIND"
elif [[ "$ISERR" == "true" ]] && print -r -- "$RESULT" | grep -qiE 'OAuth|revoked|authenticate'; then
  FAILKIND="auth";  FAILFIX="Fix: claude /login, then: wf run $KIND"
elif [[ "$ISERR" == "true" ]] && print -r -- "$RESULT" | grep -qiE 'usage credits|session limit|rate limit'; then
  FAILKIND="quota"; FAILFIX="Retry after reset: wf run $KIND"
elif [[ $RC -ne 0 || -z "$RESULT" ]]; then
  FAILKIND="model"; FAILFIX="rc=$RC, empty result after ${ELAPSED}s. Retry: wf run $KIND"
fi

if [[ -n "$FAILKIND" ]]; then
  SHORT="$(print -r -- "$RESULT" | head -c 90 | tr -d '\n')"
  say "!! model step failed [$FAILKIND] after ${ELAPSED}s: ${SHORT:-<no output>}"
  stamp "FAILED-$FAILKIND"
  "$DIR/notify.sh" "🚨 Watcher $KIND — $FAILKIND, NO orders placed" \
    "${SHORT:-no output} (${ELAPSED}s). $FAILFIX" urgent
  say "=== done: FAILED-$FAILKIND (nothing placed) ==="
  exit 75
fi
say "    model review completed in ${ELAPSED}s"

VERDICT="$(print -r -- "$RESULT" | grep -oE 'VERDICT:[[:space:]]*(APPROVE|HALT.*)' | tail -1)"
say "    verdict: ${VERDICT:-<none emitted>}"

# ---------- 4. execute (fail-closed: anything but a clean APPROVE = no trade) ----
EXEC_OUT=""
if [[ $PRC -ne 0 ]]; then
  STATUS="BLOCKED by engine (exit $PRC) — nothing executable"
elif [[ $HAS_ORDERS -eq 0 ]]; then
  STATUS="clean — no orders due"
elif [[ "$VERDICT" == VERDICT:*APPROVE* ]]; then
  say "5/5 EXECUTING (v3_execute.py --live) ..."
  # Replay the EXACT plan that was reviewed. Regenerating here would mean the model
  # approved plan A while plan B got placed — prices, positions and even the code can
  # move between review and execution.
  EXEC_OUT="$("$PY" "$DIR/v3_execute.py" --live --plan "$PLANJSON" 2>&1)"; ERC=$?
  print -r -- "$EXEC_OUT" | sed 's/^/      /' | head -20
  echo "$EXEC_OUT" >> "$LOGDIR/$KIND-$TS.exec.txt"
  if [[ $ERC -eq 0 ]]; then STATUS="EXECUTED: $(print -r -- "$EXEC_OUT" | grep -cE 'PLACED') order(s)"
  else STATUS="EXECUTION FAILED rc=$ERC"; fi
else
  STATUS="HALTED by review — ${VERDICT:-no verdict emitted}"
fi

case "$STATUS" in
  EXECUTED*)  stamp "EXECUTED" ;;
  HALTED*)    stamp "HALTED" ;;
  EXECUTION*) stamp "FAILED-exec" ;;
  BLOCKED*)   stamp "BLOCKED" ;;
  *)          stamp "CLEAN" ;;
esac
say "=== done: $STATUS ==="

# ---------- 5. notify (informational — no action requested) ------------------
case "$STATUS" in
  EXECUTED*) "$DIR/notify.sh" "✅ Watcher $KIND — $STATUS" \
               "$(print -r -- "$EXEC_OUT" | grep -E 'PLACED|SKIPPED' | head -4 | tr '\n' ' ')" high ;;
  HALTED*)   "$DIR/notify.sh" "⛔ Watcher $KIND HALTED" "${VERDICT:0:250}" urgent ;;
  EXECUTION*)"$DIR/notify.sh" "🚨 Watcher $KIND — execution failed" "${EXEC_OUT:0:250}" urgent ;;
  BLOCKED*)  "$DIR/notify.sh" "⛔ Watcher $KIND — engine refused (rail held)" \
               "$(grep -m2 'BLOCKED' "$PLAN" | tr '\n' ' ')" high ;;
  *)         "$DIR/notify.sh" "Watcher $KIND ✓" "Ran clean, nothing due." low ;;
esac
exit 0
