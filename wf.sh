#!/bin/zsh
# wf <daily|weekly> — reattachable remote entry point for phone access.
# Runs watcher-followup inside a named tmux session so a dropped phone connection
# (cellular↔wifi, lock, dead zone) doesn't kill the live order-placing session —
# you just reconnect and land back in the same conversation. Pairs with mosh, which
# auto-reconnects the transport. Used by the Blink Shell Home-Screen shortcuts.
emulate -L zsh
set -u
# Self-contained PATH so this works when launched WITHOUT a login shell — e.g.
# `mosh host -- wf daily` (command mode) or a Blink URL action, where ~/.local/bin and
# /opt/homebrew/bin would otherwise be missing and the inner command would die instantly.
export PATH=/Users/shawn/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
export HOME=/Users/shawn
DIR=${0:A:h}                       # repo dir (resolves the ~/.local/bin/wf symlink)
KIND=${1:-daily}
case "$KIND" in daily|weekly) ;; *) echo "usage: wf <daily|weekly>" >&2; exit 64 ;; esac
# Dedicated tmux server (-L watcher) so our -f config reliably loads — a `-f` config is
# ignored if it joins an already-running default server. Isolated from any other tmux.
# Absolute inner path (watcher-followup) for the same no-login-shell robustness.
exec /opt/homebrew/bin/tmux -L watcher -f "$DIR/tmux.conf" \
  new-session -A -s "wf-$KIND" "/Users/shawn/.local/bin/watcher-followup $KIND"
