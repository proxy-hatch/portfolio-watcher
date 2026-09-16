# Local portfolio watcher with Codex and mobile followup

A local autonomous trading pipeline on macOS: deterministic strategy calculations and
execution rails, a bounded GPT-6 Astra circuit breaker, ntfy phone notifications, and
interactive followups through Blink/mosh/tmux. It uses **Codex ChatGPT sign-in**, not
separately billed API access. Review and weekly task prompts plus the playbook are read
live from the vault. Strategy calculations and brokerage execution remain local.

## Pipeline and cadence

```
launchd → run.sh → watcher.py
  v3_execute.py dry-run → frozen plan + its exact engine snapshot
  catalysts + fetched current halt feed + web-only evidence collection → tool-free Astra verdict
  valid APPROVE + unchanged plan → existing replay checks → execution
  controller records actual outcome → macOS banner + ntfy

Saturday weekly invocation → separate full weekly analysis → report notification
wf daily|weekly → Astra interactive followup with the actual outcome
```

Daily runs Tue–Sat **09:00 Taipei**, covering the prior US close. Weekly runs Saturday
**09:30 Taipei**. Only a weekly invocation creates the full report; daily outcomes do
not trigger it. The report runs after the trading outcome is recorded, including when
trading failed. Its failure cannot change that outcome or gate execution.

The model cannot change quantities, symbols, prices or strategy parameters. The controller
requires completed structured output (`verdict`, `reason`, `plan_sha256`) and matching
artifact bytes. Missing/invalid output, material uncertainty, timeout, auth or quota
failure means no execution. The executor rechecks its existing freshness, positions,
resting orders and price-drift guards before replay.

## Models and configuration

`watcher-config.json` pins `gpt-6-astra` and the absolute Codex executable path.

| Step | Reasoning | Deadline | Tools |
|---|---|---|---|
| Risk evidence | medium | 180 seconds | web search only |
| Trading verdict | medium | 300 seconds | none |
| Full weekly report | high | 600 seconds | web search only |
| Interactive followup | high | interactive | normal Codex tools |

Evidence/review get at most one retry for timeout or transient transport errors. Auth,
quota, invalid output and HALT are never retried to seek approval. Reporting has its own
single attempt. Process groups are terminated on timeout/interruption/completion, so
background descendants cannot keep a completed scheduled review alive.

The scheduled adapter ignores personal config, project instructions, plugins and hooks.
It preserves the vendor model instructions but derives a restricted runtime tool catalog:
no shell, file editing, Code Mode, agents, apps or skill discovery. The reviewer has no
tools; evidence/reporting explicitly enable web search. Unexpected tool events invalidate
the result. Evidence gaps are preserved as unknown for the final reviewer to assess; an
identified active halt always blocks execution. Codex login is explicitly restricted to
ChatGPT; API environment variables are not inherited. No automatic provider or API-billing
fallback exists.

Verified executable: `/Applications/Codex.app/Contents/Resources/codex` (0.154.0-alpha.6.2).
The Homebrew binary failed its version probe on this machine; do not silently fall back.
Revalidate capabilities after upgrading Codex. [CLI documentation](https://learn.chatgpt.com/docs/non-interactive-mode).

## Commands

| Command | Behavior |
|---|---|
| `wf daily` / `wf weekly` | Open or reattach to the latest run's interactive followup |
| `wf daily --safe` | Separate followup with Codex permission prompts |
| `wf run daily` / `wf run weekly` | Run the autonomous pipeline inside tmux |
| `wf run daily --shadow` | Real-data/model test with no live execution or normal push |
| `run.sh daily --shadow` | Same test directly |
| `wf-sessions` | List all legacy and new runs with trading outcomes |
| `wf-sessions resume <#\|id-prefix> [--safe]` | Reconnect to a particular run |
| `wf-sessions clear` | Close watcher tmux sessions; saved conversations remain |

Default interactive followup bypasses permission prompts, as before. This controls tool
permissions; opening a historical run is not new authorization to place orders. `--safe`
uses workspace-write and on-request approvals. New followups use Astra; old recorded
Claude IDs still resume through `/opt/homebrew/bin/claude` with `claude-opus-5`.

Keep the existing symlinks in `~/.local/bin`: `wf` → `wf.sh`, `watcher-followup` →
`followup.sh`, `wf-sessions` → `sessions.sh`. No phone shortcut or Tailscale change is needed.
Use `mosh1 macbook -- /Users/shawn/.local/bin/wf daily` in Blink URL actions. See [MOBILE.md](MOBILE.md).

## Run records and notifications

- `state/sessions.tsv`: five-column historical index; the ID is a watcher run ID for new runs.
- `state/runs/<id>.json`: provider, timestamps, actual trading outcome, model/session IDs,
  separate report status, and interactive session IDs (separate safe/default conversations).
- `logs/<kind>-<timestamp>-<id8>.*`: frozen plan, targets, evidence, execution output and factual log.
- `logs/*-<stage>-attemptN.{jsonl,err,output.json,prompt.txt,catalog.json}`: auditable model calls.
- Vault daily paths remain `05-trades/portfolio-watcher-runs/YYYY-MM-DD.md`; each new run is
  additionally preserved under `runs/<id>.md`. Weekly reports remain `weekly/YYYY-Www.md`.

`notify.sh` sends actual outcomes through the existing macOS/ntfy path. Weekly report
completion/failure is a separate notification. `APPROVE` is a review decision; `PLACED`
means submitted, not proof of a fill. Duplicate-only replay is `CLEAN`; rejection or
partial execution failure is `FAILED-exec` with broker output retained. Consult
`state/orders-audit.jsonl` and current broker state before acting on an uncertain execution.

## Testing and operations

```sh
python3 -m unittest discover -s tests -v
./run.sh daily --shadow
./run.sh weekly --shadow
```

Shadow uses private state/logs/latest pointers, no canonical vault writes or notifications,
and separate reader client IDs (151/182). It cannot pass `--live`. Live writer clientId
remains **1**, SMART routing. Shadow does not hold the live trading lock. `WATCHER_PYTHON`
can select an existing venv for isolated-worktree tests.

Kill switch: `state/AUTOEXEC_OFF`. Set it to stop execution; remove only after reviewing
why it was set. IB Gateway is `127.0.0.1:4001`; its daily ~23:59 restart can briefly keep
the TCP port open while API handshakes fail. See [SETUP.md](SETUP.md).

On auth failure, run the configured Codex executable's `login` command, then retry with
`wf run <kind>`. On quota failure, wait for the reset. Inspect metadata and stage stderr
for other failures. A report failure does not imply trading failed.

The pre-migration Claude runner (including September 10's background-task recovery fix)
is retained as `run.sh.claude-backup`; it is not scheduled. `run.sh.v2-backup` is older,
recommend-only history. Do not run either alongside the active pipeline. For rollback,
restore the prior Git revision after checking no job is active; do not rewrite session
history. Source code belongs in this standalone repo, not in the knowledge vault.
