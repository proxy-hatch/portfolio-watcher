#!/bin/zsh
# wf <daily|weekly> — reattachable remote entry point for phone access.
# Runs watcher-followup inside a named tmux session so a dropped phone connection
# (cellular↔wifi, lock, dead zone) doesn't kill the live order-placing session —
# you just reconnect and land back in the same conversation. Pairs with mosh, which
# auto-reconnects the transport. Used by the Blink Shell Home-Screen shortcuts.
emulate -L zsh
set -u
DIR=${0:A:h}                       # repo dir (resolves the ~/.local/bin/wf symlink)
KIND=${1:-daily}
case "$KIND" in daily|weekly) ;; *) echo "usage: wf <daily|weekly>" >&2; exit 64 ;; esac
exec /opt/homebrew/bin/tmux -f "$DIR/tmux.conf" new-session -A -s "wf-$KIND" "watcher-followup $KIND"
