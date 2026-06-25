#!/bin/zsh
# wf-sessions [daily|weekly]        — list recorded watcher sessions (newest first)
# wf-sessions resume <#|sid>        — reconnect to a past session (resumable days later)
#
# run.sh appends every scheduled run to state/sessions.tsv (started_at<TAB>kind<TAB>sid).
# Claude persists each session on disk, so an old run stays resumable long after — this
# surfaces the ids and reattaches/resumes one in the same `-L watcher` tmux setup as `wf`
# (so phone reconnect-resilience and the Opus/skip-perms followup config all apply).
emulate -L zsh
set -u
export PATH=/Users/shawn/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
export HOME=/Users/shawn
DIR=${0:A:h}                       # repo dir (resolves the ~/.local/bin/wf-sessions symlink)
TSV="$DIR/state/sessions.tsv"
TMUX_BIN=/opt/homebrew/bin/tmux
FOLLOWUP=/Users/shawn/.local/bin/watcher-followup

[[ -r "$TSV" ]] || { echo "No session history yet ($TSV) — it records from the next scheduled run." >&2; exit 1; }

# Load history in file order (oldest first); display/index is newest-first.
typeset -a AT_A KIND_A SID_A
while IFS=$'\t' read -r a k s; do
  [[ -n "$s" ]] || continue
  AT_A+=("$a"); KIND_A+=("$k"); SID_A+=("$s")
done < "$TSV"
n=${#SID_A}
(( n )) || { echo "No sessions recorded yet." >&2; exit 0; }

# Currently-live tmux session names on the watcher server.
typeset -A LIVE
for s in ${(f)"$(${TMUX_BIN} -L watcher ls -F '#{session_name}' 2>/dev/null)"}; do LIVE[$s]=1; done

# ---- resume <#|sid> -----------------------------------------------------------------------
if [[ "${1:-}" == resume || "${1:-}" == reconnect ]]; then
  sel="${2:-}"
  [[ -n "$sel" ]] || { echo "usage: wf-sessions resume <#|sid>" >&2; exit 64 ;}
  pos=0
  if [[ "$sel" == <-> ]]; then                   # a number is an INDEX only (1 = newest),
    (( sel >= 1 && sel <= n )) && pos=$(( n - sel + 1 ))   # never a sid prefix
  else
    for ((i=1; i<=n; i++)); do                   # else match the sid (full or prefix, ci)
      [[ "${SID_A[i]:l}" == "${sel:l}"* ]] && pos=$i
    done
  fi
  (( pos )) || { echo "No session matches '$sel'. Run 'wf-sessions' to list." >&2; exit 1 ;}
  k=${KIND_A[pos]}; sid=${SID_A[pos]}
  echo "Reconnecting to $k session from ${AT_A[pos]} ($sid) ..." >&2
  exec ${TMUX_BIN} -L watcher -f "$DIR/tmux.conf" \
    new-session -A -s "wf-$k-${sid[1,8]}" "$FOLLOWUP $k --sid $sid"
fi

# ---- list [daily|weekly] ------------------------------------------------------------------
filter=""
case "${1:-}" in
  daily|weekly) filter="$1" ;;
  ""|list|ls)   ;;
  *) echo "usage: wf-sessions [daily|weekly] | resume <#|sid>" >&2; exit 64 ;;
esac

printf '  %-3s  %-25s  %-7s  %-9s  %s\n' '#' 'started' 'kind' 'sid' 'status'
printf '  %-3s  %-25s  %-7s  %-9s  %s\n' '---' '-------------------------' '-------' '--------' '------'
for ((i=1; i<=n; i++)); do
  pos=$(( n - i + 1 ))                            # newest first; # is global (ignores filter)
  k=${KIND_A[pos]}; sid=${SID_A[pos]}; at=${AT_A[pos]}; s8=${sid[1,8]}
  [[ -n "$filter" && "$k" != "$filter" ]] && continue
  st=""
  [[ -n "${LIVE[wf-$k-$s8]:-}" || -n "${LIVE[wf-$k-safe-$s8]:-}" ]] && st="● live in tmux"
  printf '  %-3s  %-25s  %-7s  %-9s  %s\n' "$i" "$at" "$k" "$s8" "$st"
done
echo
echo "reconnect:  wf-sessions resume <#|sid>     (resumes via the Opus followup, skip-perms default)"
