#!/bin/zsh
# Local autonomous watcher; --shadow exercises data/model without live execution.
emulate -L zsh
set -u
export HOME=/Users/shawn
export PATH=/Users/shawn/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
DIR=${0:A:h}
exec "${WATCHER_PYTHON:-$DIR/.venv/bin/python}" "$DIR/watcher.py" "$@"
