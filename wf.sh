#!/bin/zsh
# wf <daily|weekly> [--safe] — reattachable remote entry point (resume a run to act on it).
# Also: `wf run <daily|weekly>` triggers a fresh run.sh in tmux; `wf --help` for usage.
# Runs the followup (or a run) inside a named tmux session so a dropped phone connection
# (cellular↔wifi, lock, dead zone) doesn't kill the live order-placing session —
# you just reconnect and land back in the same conversation. Pairs with mosh, which
# auto-reconnects the transport. Used by the Blink Shell Home-Screen shortcuts.
#
# By DEFAULT the resumed session skips permission prompts (--dangerously-skip-permissions:
# auto-approves every action, INCLUDING order placement — the point of resuming AFK). Pass
# --safe (or -s) to restore normal prompts. Other args after the kind pass through to the selected provider
# (via watcher-followup). A --safe run gets its OWN tmux session (`wf-<kind>-safe`) so it
# never silently reattaches to — or gets reattached by — the default session of the kind.
emulate -L zsh
set -u
# Self-contained PATH so this works when launched WITHOUT a login shell — e.g.
# `mosh host -- wf daily` (command mode) or a Blink URL action, where ~/.local/bin and
# /opt/homebrew/bin would otherwise be missing and the inner command would die instantly.
export PATH=/Users/shawn/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
export HOME=/Users/shawn
DIR=${0:A:h}                       # repo dir (resolves the ~/.local/bin/wf symlink)
TMUX_BIN=${WATCHER_TMUX_BIN:-/opt/homebrew/bin/tmux}

usage() {
  cat >&2 <<'USAGE'
wf — Portfolio Watcher: trigger a run, or resume one to act on it (reattachable tmux/mosh)

  wf <daily|weekly> [--safe]   resume the latest run's session to act on it — skips
                               permission prompts by default; --safe restores them
  wf run <daily|weekly>        trigger a FRESH run now (run.sh) inside tmux, so it
                               survives a dropped phone connection; follow up with `wf <kind>`
  wf -h | --help               show this help

See also: wf-sessions (list / reconnect older sessions / clear tmux).
USAGE
}

# Intercept sub-verbs before treating $1 as the kind.
case "${1:-}" in
  -h|--help|help) usage; exit 0 ;;
  run|run-now|trigger)
    shift
    KIND=${1:-daily}
    case "$KIND" in daily|weekly) ;; *) echo "usage: wf run <daily|weekly>" >&2; exit 64 ;; esac
    # Run the scheduled-style pass (run.sh) inside tmux so a dropped phone connection can't
    # kill the ~10-min job. new-session -A reattaches to an in-progress run of this kind
    # instead of starting a second concurrent one. run.sh saves the session + fires alerts;
    # afterward `wf <kind>` resumes it to act on the recommendations.
    (( $# )) && shift
    run_suffix=""
    run_cmd="$DIR/run.sh $KIND"
    for a in "$@"; do
      case "$a" in --shadow) run_suffix="-shadow" ;; *) echo "unexpected run argument: $a" >&2; exit 64 ;; esac
      run_cmd+=" ${(q)a}"
    done
    exec ${TMUX_BIN} -L watcher -f "$DIR/tmux.conf" \
      new-session -A -s "wf-run-$KIND$run_suffix" "$run_cmd"
    ;;
esac

KIND=${1:-daily}
case "$KIND" in daily|weekly) ;; *) echo "usage: wf <daily|weekly> [--safe] | wf run <daily|weekly> | wf --help" >&2; exit 64 ;; esac
(( $# )) && shift                  # drop the kind; forward the rest to watcher-followup

# Build the inner command (single string for tmux), quoting each forwarded arg. --safe selects
# a distinct session family so safe/default stay separate (a tmux session's permission mode is
# fixed when it's created; -A would otherwise reattach into the wrong one).
suffix=""
cmd="${(q)DIR}/followup.sh $KIND"
SID_OVERRIDE=""
expect_sid=0
for a in "$@"; do
  if (( expect_sid )); then SID_OVERRIDE="$a"; expect_sid=0; fi
  case "$a" in
    --sid) expect_sid=1 ;;
    --safe|-s) suffix="-safe" ;;
  esac
  cmd+=" ${(q)a}"
done
(( expect_sid )) && { echo "--sid needs a run ID" >&2; exit 64; }

# Key the tmux session name to the CURRENT saved session id (run.sh writes a fresh uuid to
# state/last-<kind>-session on every scheduled run). Without this, `new-session -A -s wf-daily`
# silently REATTACHES to a still-running followup from a PREVIOUS day — you'd keep landing in
# yesterday's conversation even though today's run minted a new session. Keying the name to the
# SID means a new run → new session name → fresh followup, while same-day reconnects (SID
# unchanged) still reattach to the same conversation (phone resilience preserved).
SFILE="$DIR/state/last-$KIND-session"
SID="$SID_OVERRIDE"
if [[ -z "$SID" && -r "$SFILE" ]]; then SID="$(< "$SFILE")"; fi
[[ -n "$SID" ]] || { echo "No saved $KIND run yet." >&2; exit 1; }
# Pin the selected ID, including latest, so a scheduler update cannot change the inner target.
[[ -n "$SID_OVERRIDE" ]] || cmd+=" --sid ${(q)SID}"
tag=""; [[ -n "$SID" ]] && tag="-${SID[1,8]}"
session="wf-$KIND$suffix$tag"

# Reap stale same-family sessions (same kind + mode, but a DIFFERENT SID = prior days) so old
# `claude -r` processes don't accumulate and can't be reattached by mistake. Only DETACHED
# ones — never kill a session that's currently in use (e.g. one you reconnected to via
# `wf-sessions`). Never touches the target session or the other mode's (safe vs default) ones.
if [[ -n "$tag" ]]; then
  while IFS=' ' read -r s att; do
    [[ -n "$s" && "$att" == 0 && "$s" != "$session" ]] || continue
    if [[ -n "$suffix" ]]; then
      [[ "$s" == wf-$KIND-safe* ]] && ${TMUX_BIN} -L watcher kill-session -t "$s" 2>/dev/null
    else
      [[ "$s" == wf-$KIND* && "$s" != wf-$KIND-safe* ]] && ${TMUX_BIN} -L watcher kill-session -t "$s" 2>/dev/null
    fi
  done < <(${TMUX_BIN} -L watcher ls -F '#{session_name} #{session_attached}' 2>/dev/null)
fi

# Dedicated tmux server (-L watcher) so our -f config reliably loads — a `-f` config is
# ignored if it joins an already-running default server. Isolated from any other tmux.
# Absolute inner path (watcher-followup) for the same no-login-shell robustness.
exec ${TMUX_BIN} -L watcher -f "$DIR/tmux.conf" \
  new-session -A -s "$session" "$cmd"
