#!/bin/zsh
# deadman.sh — run the silence check and escalate it across every channel we have.
#
# Driven by its OWN launchd agent (com.shawn.portfolio-watcher-deadman), several times a
# day, every day — including Sun/Mon when no run is scheduled, because "the laptop never
# came back" is exactly the thing that must not wait for Tuesday.
#
# WHY THE CHANNELS ARE LAYERED
#   On 2026-09-27..30 the watcher failed four days running. Every failure fired an ntfy
#   push into an app iOS had offloaded, so every one vanished. A single push channel
#   cannot tell you that the push channel is broken. So an alert here fans out to:
#
#     1. state/deadman-status.txt   PULL. No delivery involved — `wf-sessions` prints it,
#                                   so simply looking at the session list reveals the truth.
#                                   This is the layer that would have caught the outage.
#     2. macOS banner               local, works with no network at all
#     3. ntfy push                  the normal phone path
#     4. ntfy -> email  (critical only, and only if secrets/ntfy-email exists)
#                                   PULL-durable: an unread email survives an offloaded
#                                   app, a reinstalled phone, and ntfy's ~12h free-tier
#                                   cache expiry. Deliberately NOT wired into notify.sh:
#                                   routine run alerts would burn the free-tier quota and
#                                   train the eye to ignore it. Email means "gone dark".
#
# Nothing here touches the trading path. It only reads state/sessions.tsv.
emulate -L zsh
set -u
export PATH=/Users/shawn/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
export HOME=/Users/shawn

DIR=${0:A:h}
# SYSTEM python, never "$DIR/.venv/bin/python". The venv is one of the things that can be
# broken (and was, in past incidents); the alarm must not share a dependency with the
# subject it is watching.
PY=/usr/bin/python3
LOG="$DIR/logs/deadman.log"
mkdir -p "$DIR/logs" "$DIR/state"

usage() {
  cat >&2 <<'USAGE'
deadman.sh — Portfolio Watcher dead-man's switch (silence detector)

  deadman.sh                 run the check and escalate if unhealthy (what launchd calls)
  deadman.sh --now 'Y-m-d H:M'   evaluate against a pretend clock (reproduce any branch)
  deadman.sh --dry-run       check and print, but send nothing
  deadman.sh --status        print the last recorded verdict and exit
  deadman.sh --test          fire a full-escalation test alert, to prove the channels work
  deadman.sh -h | --help     this

Health is judged from state/sessions.tsv. See deadman.py for what "unhealthy" means.
USAGE
}

DRY=0
typeset -a PYARGS=()
for a in "$@"; do
  case "$a" in
    -h|--help|help) usage; exit 0 ;;
    --status) [[ -r "$DIR/state/deadman-status.txt" ]] \
                && cat "$DIR/state/deadman-status.txt" \
                || echo "No check has run yet." >&2
              exit 0 ;;
    --dry-run) DRY=1; PYARGS+=(--force --no-save) ;;   # never consume the dedup slot
    --test)
      # Prove the whole escalation path end to end, including the email leg. The only way
      # to trust an alarm is to have heard it fire on purpose.
      TITLE="🔔 Watcher dead-man's switch — TEST"
      BODY="If you are reading this, the escalation path works: banner, ntfy push, and (for critical alerts) email. Sent $(date '+%Y-%m-%d %H:%M %Z'). No action needed."
      SEV=critical
      ;;
    *) PYARGS+=("$a") ;;
  esac
done

if [[ -z "${TITLE:-}" ]]; then
  OUT="$("$PY" "$DIR/deadman.py" "${PYARGS[@]}" 2>>"$DIR/logs/deadman.err")"; RC=$?
  # Leave a heartbeat either way, so the switch itself is auditable: if THIS log goes
  # quiet, the watcher of the watcher has stopped.
  if (( RC == 0 )); then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ok" >> "$LOG"
    exit 0
  fi
  if (( RC == 9 )); then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] STILL UNHEALTHY (already alerted; re-nag in <${RENAG:-12}h)" >> "$LOG"
    exit 0
  fi
  if (( RC != 10 && RC != 11 )); then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] deadman.py itself failed rc=$RC" >> "$LOG"
    /usr/bin/osascript -e 'display notification "deadman.py failed — the silence detector is down" with title "🚨 Watcher dead-man'"'"'s switch"' 2>/dev/null || true
    exit $RC
  fi
  SEV="${${OUT%%$'\n'*}%%$'\t'*}"          # line 1, field 1
  TITLE="${${OUT%%$'\n'*}#*$'\t'}"         # line 1, field 2
  BODY="${OUT#*$'\n'}"                     # everything after line 1
fi

case "$SEV" in
  critical) PRIO=urgent ;;
  warn)     PRIO=high ;;
  *)        PRIO=default ;;
esac

if (( DRY )); then
  print -r -- "[dry-run] severity=$SEV priority=$PRIO"
  print -r -- "[dry-run] $TITLE"
  print -r -- "$BODY"
  exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ALERT [$SEV] $TITLE" >> "$LOG"

# --- channels 2 + 3: banner and ntfy push -------------------------------------------------
"$DIR/notify.sh" "$TITLE" "$BODY" "$PRIO"

# --- channel 4: ntfy -> email, critical only ----------------------------------------------
# Opt-in: create secrets/ntfy-email containing one address. Absent, the switch still works,
# it just loses its most durable leg. secrets/ is gitignored.
EMAIL_FILE="$DIR/secrets/ntfy-email"
TOKEN_FILE="$DIR/secrets/ntfy-token"
TOPIC_FILE="$DIR/secrets/ntfy-topic"
if [[ "$SEV" == critical && -s "$EMAIL_FILE" && -s "$TOPIC_FILE" ]]; then
  # secrets/ntfy-email is hand-edited, so treat it as untrusted input: take the FIRST line
  # only, strip surrounding whitespace, and require it to look like an address. A stray
  # newline would otherwise be injected raw into the HTTP header block.
  EMAIL="${$(/usr/bin/head -1 "$EMAIL_FILE")##[[:space:]]##}"
  EMAIL="${EMAIL%%[[:space:]]##}"
  TOPIC="$(< "$TOPIC_FILE")"

  # ntfy.sh refuses anonymous email sending (HTTP 400, code 40053) — the Email header needs
  # a free ntfy.sh account and an access token in secrets/ntfy-token. Without it this leg
  # cannot work, so say so plainly rather than failing vaguely.
  typeset -a AUTH=()
  if [[ -s "$TOKEN_FILE" ]]; then
    AUTH=(-H "Authorization: Bearer ${$(/usr/bin/head -1 "$TOKEN_FILE")//[[:space:]]/}")
  fi

  if [[ ! "$EMAIL" =~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$' ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]   email leg SKIPPED — secrets/ntfy-email is not a valid address" >> "$LOG"
  elif (( ! ${#AUTH} )); then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]   email leg SKIPPED — needs secrets/ntfy-token (ntfy.sh forbids anonymous email)" >> "$LOG"
  else
    BODYF="$(/usr/bin/mktemp -t deadman-ntfy)"
    HTTP="$(/usr/bin/curl -sS -o "$BODYF" -w '%{http_code}' --max-time 20 \
       -H "Title: ${TITLE}" -H "Priority: urgent" -H "Tags: rotating_light" \
       -H "Email: ${EMAIL}" "${AUTH[@]}" \
       -d "${BODY}

-- Portfolio Watcher dead-man's switch. Full status: wf-sessions, or
   cat ~/workspace/portfolio-watcher/state/deadman-status.txt" \
       "https://ntfy.sh/${TOPIC}" 2>/dev/null)"
    if [[ "$HTTP" == 2* ]]; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')]   email leg sent (HTTP $HTTP)" >> "$LOG"
    else
      # Log what ntfy ACTUALLY said. Guessing "network or quota" once sent me chasing the
      # wrong cause; the server states the reason, so record it (address redacted).
      ERR="$(/usr/bin/head -c 300 "$BODYF" | /usr/bin/sed "s|${EMAIL}|<redacted>|g" | /usr/bin/tr -d '\n')"
      echo "[$(date '+%Y-%m-%d %H:%M:%S')]   email leg FAILED (HTTP ${HTTP:-none}) ${ERR}" >> "$LOG"
    fi
    /bin/rm -f "$BODYF"
  fi
elif [[ "$SEV" == critical && ! -s "$EMAIL_FILE" ]]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')]   email leg skipped — no secrets/ntfy-email" >> "$LOG"
fi

print -r -- "$TITLE"
print -r -- "$BODY"
