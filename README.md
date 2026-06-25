# Portfolio Watcher — Local Scheduler

Runs the daily/weekly Portfolio Watcher **unattended on this Mac** via `launchd` +
headless `claude -p`, then lets you **resume the same session interactively** to place
any orders it recommends.

Why local (not co-work / not cloud): the watcher needs `127.0.0.1:4001` (IB Gateway)
and the local venv (`ib_async`). Co-work computer-use can't type into a terminal
("click" tier); cloud routines can't reach localhost. A local launchd job can do both.

```
launchd  ──►  run.sh <daily|weekly>  ──►  claude -p (headless, recommend-only)
   │                                          • ibkr-cli reads + metrics.py
   │                                          • writes run log to the vault
   │                                          • saves session id for resume
   └─ schedule:                          ──►  notify.sh  → macOS banner + ntfy push
        daily  Tue–Sat 09:00 (+0800)   # Sat reviews Fri's close
        weekly Sat     09:30 (+0800)   # after the Sat daily

You, later:   watcher-followup <daily|weekly>  ──►  claude -r <saved session>
              (full context loaded; you're present → it CAN place orders)
```

The unattended run is **recommend-only by prompt instruction** — it never places,
modifies, or cancels orders. All order placement happens in the interactive
`watcher-followup` session.

> **First-time install (fresh machine):** see **[SETUP.md](SETUP.md)** — IB Gateway via
> Docker, ibkr-cli, `uv sync`, Claude CLI, ntfy, and installing the launchd jobs.
>
> **Chat with a session from your phone (AFK):** see **[MOBILE.md](MOBILE.md)** — Tailscale
> (handles dynamic IP) + Blink/mosh + two Home-Screen icons for daily/weekly.

---

## Layout

| Path | What |
|---|---|
| `run.sh <daily\|weekly>` | launchd entry point (the scheduled job) — Sonnet 4.6 |
| `followup.sh` → `~/.local/bin/watcher-followup` | resume the last run interactively — Opus 4.8 |
| `wf.sh` → `~/.local/bin/wf <daily\|weekly>` | reattachable (tmux) followup for phone access — see MOBILE.md |
| `sessions.sh` → `~/.local/bin/wf-sessions` | list past runs' sessions / reconnect to one days later |
| `metrics.py` | read-only indicators (SMA/ATR/ADX/vol/beta/…); used by the prompts |
| `catalysts.py` | upcoming earnings (yfinance) + macro calendar (FOMC/CPI/NFP); gap-risk/execution context for §1.10 (daily) / §2.6 (weekly) — no IB connection, degrades gracefully |
| `data/econ_calendar.json` | curated US macro calendar (FOMC/CPI/NFP). **Refresh annually** — `catalysts.py` flags `calendar_stale` once `verified_through` passes |
| `notify.sh` | macOS banner + ntfy.sh phone push |
| `watcher-settings.json` | permission allow/deny for the headless run |
| `pyproject.toml` / `uv.lock` / `.python-version` | uv-managed deps (`ib_async`, `pandas`, `numpy`, `yfinance`) |
| `docker-compose.ib-gateway.yml` / `.env.ib-gateway.example` | IB Gateway container + env template |
| `launchd/*.plist` | source copies of the launchd jobs |
| `secrets/ntfy-topic` | the ntfy topic (gitignored) |
| `state/last-<kind>-session` / `state/sessions.tsv` | latest session id + full run→session history (resume / `wf-sessions`) |
| `logs/` | per-run JSON output, stderr, and `<kind>.log` timestamps |
| `~/Library/LaunchAgents/com.shawn.portfolio-watcher-{daily,weekly}.plist` | the installed schedules |

**The prompts themselves live in the vault and are read live every run** (edit = deploy):
- `~/vaults/trading-kb/03-strategies/trend-following/Portfolio Watcher Daily Close Prompt.md`
- `~/vaults/trading-kb/03-strategies/trend-following/Portfolio Watcher Weekly Review Prompt.md`

Run logs are written to `~/vaults/trading-kb/05-trades/portfolio-watcher-runs/YYYY-MM-DD.md`.

---

## Common tasks

`UID` is `501` (from `id -u`). All `launchctl` commands use `gui/501`.

### Follow up on a run / place orders
```zsh
watcher-followup daily      # resume the most recent daily run, interactively
watcher-followup weekly
```
Then just talk to it, e.g. `place the MSFT sell — 62 sh, TFSA, SMART route`.
It has the full run context (positions, triggers, recommendations) already loaded.

**By default the followup session skips permission prompts** (passes
`--dangerously-skip-permissions` to claude): it auto-approves every action, including
ib_async order placement, so you can act without tap-approving each step — the point of
resuming, often AFK from the phone. Pass `--safe` (or `-s`) to restore normal interactive
prompts: `watcher-followup daily --safe`, or `wf daily --safe`. (Any other args after the
kind pass straight through to claude.)

### Reconnect to an earlier day's session
```zsh
wf-sessions             # list every recorded run (newest first) with its session id + live status
wf-sessions daily       # filter to daily (or weekly)
wf-sessions resume 3    # reconnect to row #3  (or: wf-sessions resume <sid-prefix>)
```
Every scheduled run is recorded to `state/sessions.tsv`, and claude keeps each session on
disk — so you can resume a run from days ago (same Opus followup; reattaches its tmux if
still live). Plain `wf daily` always targets the **latest** run; `wf-sessions` is how you
reach older ones.

### Run a watcher manually right now (ad-hoc, off-schedule)
```zsh
~/workspace/portfolio-watcher/run.sh daily
```
Behaves exactly like the scheduled run (writes the log, fires alerts, saves the session
so you can `watcher-followup daily` afterward).

### Force the *scheduled* job to fire now (test the launchd wiring)
```zsh
launchctl kickstart -k gui/501/com.shawn.portfolio-watcher-daily
```

### Stop / disable
```zsh
# Temporary (until next login/reboot or until you bootstrap again):
launchctl bootout gui/501 ~/Library/LaunchAgents/com.shawn.portfolio-watcher-daily.plist

# Persistent (survives reboot — won't run until re-enabled):
launchctl disable gui/501/com.shawn.portfolio-watcher-daily
```
Repeat with `…-weekly` for the weekly job.

### Restart / re-enable
```zsh
launchctl enable    gui/501/com.shawn.portfolio-watcher-daily            # if you disabled it
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.shawn.portfolio-watcher-daily.plist
```
After editing a `.plist`, always `bootout` then `bootstrap` to reload it.

### Check status / next run / recent activity
```zsh
launchctl list | grep portfolio-watcher                       # loaded? last exit code?
launchctl print gui/501/com.shawn.portfolio-watcher-daily     # full state, next firing
tail -f ~/workspace/portfolio-watcher/logs/daily.log  # run start/end timestamps
ls -t  ~/workspace/portfolio-watcher/logs/daily-*.json | head   # per-run output
```

### Change the schedule or which days
Edit `StartCalendarInterval` in the `.plist` (Weekday: Sun=0/7 … Sat=6; Hour/Minute are
Mac-local = +0800), then `bootout` + `bootstrap`.

### Edit what the watcher checks
Edit the prompt `.md` files in the vault (paths above). No redeploy — the next run reads
the new version. `metrics.py` is the deterministic-math helper the prompts call; extend it
if you need a new indicator.

---

## Alerts & human intervention

- **macOS banner** fires every run (✓ clean / action window / 🚨 URGENT / FAILED).
- **Phone push (ntfy)** fires on 🚨 URGENT, an open action window, or a failed run.
  Subscribe in the ntfy app to the topic in `secrets/ntfy-topic`.
- **When you get a 🚨:** open a terminal → `watcher-followup daily` → tell it what to do.
  The recommended action is also in that day's run log under "Recommended Manual Actions".
- **Change push channel:** `notify.sh` uses ntfy by default. Swap the `curl` block for
  Pushover/email, or rotate the topic by editing `secrets/ntfy-topic`.

---

## Gateway / auth notes

- IB Gateway (`algo-trader-ib-gateway-1`, port 4001) **auto-restarts 23:59 Asia/Taipei**;
  the API handshake fails for ~1–2 min during re-auth. The schedules (09:00 / 09:30 +0800) avoid
  that window. `run.sh` does a TCP probe and logs a WARN (non-fatal) if 4001 is unreachable.
- Confirm gateway readiness: `docker logs algo-trader-ib-gateway-1 | grep "Login has completed"`.
- If a run **FAILED** (you'll get a push + `rc≠0` in `logs/daily.log`), check
  `logs/daily-<timestamp>.err`. Common causes: gateway in its re-auth window, or `claude`
  needing re-auth (run `claude` once interactively to refresh).

---

## Models

| | Model | Thinking | Why |
|---|---|---|---|
| **Watcher run** (`run.sh`) | `claude-sonnet-4-6` | medium (`MAX_THINKING_TOKENS=10000`) | mechanical — metrics.py does the math; the model interprets vs thresholds. Cheap, ~5 min. |
| **Followup** (`followup.sh`) | `claude-opus-4-8` | high (`MAX_THINKING_TOKENS=32000`) | order decisions deserve maximal reasoning; interactive, so latency is fine. |

Both call the **real binary** `/opt/homebrew/bin/claude` with explicit `--model`, NOT the
`~/.local/bin/claude` wrapper (which force-sets `MAX_THINKING_TOKENS=63999` / effort=max /
adaptive-off on every turn — fine interactively, but it made the headless multi-step run
take 30–60+ min). `followup.sh` still appends the `thinking-nudge.txt` step-by-step prompt.

## Design notes / gotchas (why run.sh looks the way it does)

- **Lean directive is prepended to the prompt text**, not passed via `--append-system-prompt`
  (that flag can't combine with the wrapper's `--append-system-prompt-file`).
- **Skill / Task / ToolSearch are `--disallowed-tools`** so the headless run doesn't spin up
  the interactive superpowers machinery (it once ballooned to 55 turns writing scratch
  scripts).
- **15-minute watchdog** in run.sh kills a run if an API turn stalls, so the job can't hang.
- **Session sharing:** run.sh and followup.sh both `cd` to the vault so the headless session
  and the interactive resume share a project root (Claude stores sessions per-project).
