# Scheduled local Claude Code, with mobile followup

A pattern for running a **headless Claude Code job on a schedule on your own machine** —
one that can reach **localhost-only services** and your local files, do real work, alert
you, and that you can then **resume interactively (including from your phone) to act on
what it found**.

Two phases share **one Claude session**:

1. **Unattended run** (scheduled, no human) — a cheap, locked-down `claude -p` executes a
   task prompt, calls local compute helpers, writes its findings, and pings you if anything
   needs attention. It only *recommends* — it never acts.
2. **Interactive followup** (you, minutes or days later) — you resume that exact session
   with `claude -r` on a stronger model, full context already loaded, and take the actions
   it proposed. From your desk, or from your phone over a resilient connection.

> The concrete example wired up in this repo is a **portfolio watcher**: it reviews a
> brokerage account each market day against a strategy checklist and lets you place the
> orders it recommends. That's just the demo, though — **nothing in the architecture is
> trading-specific**. Swap the prompt, the compute helpers, and the local service for your
> own and the same skeleton runs any "watch something locally on a schedule, then let me
> act on it from anywhere" job.

## Architecture

```
  UNATTENDED RUN  (scheduled · no human present)
  ───────────────────────────────────────────────────────────────────────────────
  launchd ──► run.sh <kind> ──► claude -p   (headless · cheap model · locked down)
  (calendar      │                 │
   schedule)     │                 ├─ reads  task prompt   ◄── notes vault (.md, edit = deploy)
                 │                 ├─ calls  compute helpers
                 │                 │          • metrics.py   ──► local service @ 127.0.0.1
                 │                 │          • catalysts.py ──► web API + curated data file
                 │                 ├─ writes run log         ──► notes vault
                 │                 ├─ saves session id       ──► state/  (+ sessions.tsv history)
                 │                 └─ returns result ──┐
                 └─ notify.sh ◄─────────────────────────┘ ──► macOS banner + ntfy push ──► 📱
  ───────────────────────────────────────────────────────────────────────────────

  INTERACTIVE FOLLOWUP  (you · minutes or days later · CAN take actions)
  ───────────────────────────────────────────────────────────────────────────────
  terminal ───────────────────────► watcher-followup <kind>
                                          │  = claude -r <session>   (strong model ·
  iPhone ──► Tailscale ──► mosh ──► tmux ─┘    full context loaded · acts on your behalf)
             (dynamic IP)  (survives  (reattach          via the `wf` wrapper
                            drops)     -able)
       wf-sessions  ──► list past runs / reconnect to an older day's session
  ───────────────────────────────────────────────────────────────────────────────
```

### The pieces

- **Scheduler — `launchd`.** macOS user agents fire `run.sh <kind>` on a calendar schedule
  (here Tue–Sat 09:00 + Sat 09:30, +0800). On Linux this would be cron or a systemd timer.
- **Headless runner — `run.sh`.** Boots `claude -p` with the task prompt and guardrails: a
  cheap model, a "lean" directive, `--disallowed-tools` (so it doesn't spin up heavy
  interactive machinery), `--permission-mode acceptEdits`, and a wall-clock watchdog so it
  can't hang. Mints a session id up front and records it.
- **Task prompt — in a notes vault.** The actual checklist lives as Markdown in an Obsidian
  vault and is **read live every run** — edit the note and the next run uses it, no
  redeploy. Written to be *recommend-only*: the unattended run proposes, it never acts.
- **Compute helpers — `metrics.py`, `catalysts.py`.** Small Python that does the
  deterministic work the model shouldn't eyeball. One reads a **localhost-only service**;
  the other pulls an external API plus a curated local data file. Both degrade gracefully so
  a flaky call can't break the run.
- **The local service — why this runs locally at all.** The run needs something reachable
  only on `127.0.0.1` (here a brokerage gateway) plus a local Python venv. A cloud agent
  can't reach localhost; a GUI-automation agent can't reliably drive a terminal. A local
  scheduled job does both — that constraint is the whole reason for this design.
- **Outputs & state.** Each run writes a dated log to the vault and per-run JSON/stderr to
  `logs/`; the session id goes to `state/last-<kind>-session` and is appended to
  `state/sessions.tsv` (the history `wf-sessions` reads).
- **Alerting — `notify.sh`.** Severity-based: a macOS banner every run, plus an
  [ntfy](https://ntfy.sh) push to your phone on anything actionable or a failure.
- **Interactive followup — `followup.sh` → `watcher-followup`.** Resumes the run's exact
  session with `claude -r` on a stronger model — full context already loaded — so you, being
  present, can take the actions it proposed. Skips permission prompts by default (you resumed
  *to act*); `--safe` restores them.
- **Mobile access — `wf` + Tailscale/mosh/tmux.** Tailscale gives a stable address despite a
  dynamic home IP; mosh survives network drops and sleep; tmux makes the session
  reattachable; `wf` wraps it so a Home-Screen icon drops you straight into the followup. See
  **[MOBILE.md](MOBILE.md)**.
- **Session history — `wf-sessions`.** Lists every recorded run and reconnects to any of them
  days later (Claude persists each session on disk).
- **Models.** Cheap/medium for the mechanical daily run; a stronger model + deeper thinking
  for the analytical weekly run and the interactive followup — see [Models](#models).

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
| `metrics.py` | compute helper #1 — deterministic numbers read from the local service, so the model doesn't eyeball them (example: market indicators from IB Gateway) |
| `catalysts.py` | compute helper #2 — external API + a curated local data file; degrades gracefully, never blocks the run (example: upcoming earnings + a macro-event calendar) |
| `data/econ_calendar.json` | curated local data file the helper reads (example: macro events). **Refresh annually** — `catalysts.py` flags `calendar_stale` once `verified_through` passes |
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
| **Daily run** (`run.sh daily`) | `claude-sonnet-4-6` | medium (`10000`) | mechanical — metrics.py does the math; the model interprets vs thresholds. Cheap, ~5 min. |
| **Weekly run** (`run.sh weekly`) | `claude-fable-5` | high (`32000`) | analytical — reconciliation, thesis review, allocation drift, catalyst outlook. Once/week, so latency is fine (20-min watchdog). |
| **Followup** (`followup.sh`, either kind) | `claude-fable-5` | high (`32000`) | order decisions deserve maximal reasoning; interactive. |

All call the **real binary** `/opt/homebrew/bin/claude` with explicit `--model`, NOT the
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
