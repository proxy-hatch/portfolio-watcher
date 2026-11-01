#!/bin/zsh
# gateway_recover.sh — restart a stuck IB Gateway and wait for it to log back in.
#
# Called by run.sh when a scheduled run cannot reach IBKR. There is deliberately no
# separate health check: a failed daily run IS the detector, and this is the remedy.
#
# Why it exists: on Sun 2026-10-25 the weekly 10:30 cold restart got an "Unrecognized
# Username or Password" dialog back from IBKR (credentials were fine — the same ones
# logged in on 11-01). IBC has no handler for that dialog, so it sat on it for 7 days:
# no retry, no exit, no 2FA push. socat kept 4001 open, so every run failed the API
# handshake. A container restart starts a fresh login, which sends a new 2FA push to
# Shawn's phone. That is the whole fix: turn a silent hang into a prompt he can answer.
#
# Exit: 0 logged in · 1 docker restart failed · 2 no login within the wait
#       3 IBKR rejected the login again (restarting straight away would only trip
#         "Too many failed login attempts", so give up and let the next run retry)
emulate -L zsh
set -u

CONTAINER=${GW_CONTAINER:-algo-trader-ib-gateway-1}
WAIT=${GW_WAIT:-900}          # 15 min: IBC re-sends the 2FA push every ~3 min until answered
POLL=${GW_POLL:-10}
SETTLE=${GW_SETTLE:-20}       # API port needs a moment after "Login has completed"
DOCKER=${DOCKER:-/usr/local/bin/docker}

log() { print -r -- "[$(date)] gateway_recover: $*"; }

START=$(date +%s)
log "restarting $CONTAINER"
if ! "$DOCKER" restart "$CONTAINER" >/dev/null 2>&1; then
  log "docker restart failed (is OrbStack running?)"
  exit 1
fi

while (( $(date +%s) - START < WAIT )); do
  sleep "$POLL"
  GWLOG=$("$DOCKER" logs --since "$START" "$CONTAINER" 2>&1)
  # Anchored: the shutdown banner "Login has completed: exiting via [File, Close]" must not match
  if print -r -- "$GWLOG" | grep -qE "Login has completed\$"; then
    log "login completed after $(( $(date +%s) - START ))s"
    sleep "$SETTLE"
    exit 0
  fi
  if [[ $GWLOG == *"Unrecognized Username or Password"* ]]; then
    log "IBKR rejected the login again — not retrying this run"
    exit 3
  fi
done
log "no login within ${WAIT}s (2FA not approved?)"
exit 2
