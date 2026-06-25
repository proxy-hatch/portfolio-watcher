#!/bin/zsh
# wf <daily|weekly> [--safe|extra claude args...] — reattachable remote entry point.
# Runs watcher-followup inside a named tmux session so a dropped phone connection
# (cellular↔wifi, lock, dead zone) doesn't kill the live order-placing session —
# you just reconnect and land back in the same conversation. Pairs with mosh, which
# auto-reconnects the transport. Used by the Blink Shell Home-Screen shortcuts.
#
# By DEFAULT the resumed session skips permission prompts (--dangerously-skip-permissions:
# auto-approves every action, INCLUDING order placement — the point of resuming AFK). Pass
# --safe (or -s) to restore normal prompts. Other args after the kind pass through to claude
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
KIND=${1:-daily}
case "$KIND" in daily|weekly) ;; *) echo "usage: wf <daily|weekly> [--safe|extra claude args]" >&2; exit 64 ;; esac
(( $# )) && shift                  # drop the kind; forward the rest to watcher-followup

# Build the inner command (single string for tmux), quoting each forwarded arg. --safe selects
# a distinct session family so safe/default stay separate (a tmux session's permission mode is
# fixed when it's created; -A would otherwise reattach into the wrong one).
suffix=""
cmd="/Users/shawn/.local/bin/watcher-followup $KIND"
for a in "$@"; do
  case "$a" in
    --safe|-s) suffix="-safe" ;;
  esac
  cmd+=" ${(q)a}"
done

TMUX_BIN=/opt/homebrew/bin/tmux

# Key the tmux session name to the CURRENT saved session id (run.sh writes a fresh uuid to
# state/last-<kind>-session on every scheduled run). Without this, `new-session -A -s wf-daily`
# silently REATTACHES to a still-running followup from a PREVIOUS day — you'd keep landing in
# yesterday's conversation even though today's run minted a new session. Keying the name to the
# SID means a new run → new session name → fresh followup, while same-day reconnects (SID
# unchanged) still reattach to the same conversation (phone resilience preserved).
SFILE="$DIR/state/last-$KIND-session"
SID=""; [[ -r "$SFILE" ]] && SID="$(< "$SFILE")"
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
