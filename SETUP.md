# Setup — from scratch

End-to-end install for a fresh machine. For day-to-day operation (stop/restart/
followup/alerts) see [README.md](README.md).

Prerequisites: macOS, [Docker](https://www.docker.com/) (or OrbStack), [uv](https://docs.astral.sh/uv/),
the [Codex CLI](https://learn.chatgpt.com/docs/non-interactive-mode), and an Interactive
Brokers account with the market-data subscriptions you need.

---

## 1. IB Gateway (Docker)

Uses the [`gnzsnz/ib-gateway`](https://github.com/gnzsnz/ib-gateway-docker) image via
`docker-compose.ib-gateway.yml` (container name `algo-trader-ib-gateway-1`).

```bash
cp .env.ib-gateway.example .env.ib-gateway     # then edit in your IBKR credentials
docker compose -f docker-compose.ib-gateway.yml --env-file .env.ib-gateway up -d
```

Ports (bound to localhost only): `127.0.0.1:4001` → live API, `4002` → paper, `5900` → VNC.
- Set `READ_ONLY_API=no` in `.env.ib-gateway` so the interactive `watcher-followup`
  session and the sanctioned autonomous executor can place orders.
- The gateway auto-restarts daily at `AUTO_RESTART_TIME` (default 11:59 PM Asia/Taipei);
  the API is unavailable for ~1-2 min then — the watcher schedules avoid that window.
- Check it's up: `docker logs algo-trader-ib-gateway-1 | grep "Login has completed"`.
- The settings volume is commented out in the compose; uncomment it to persist
  Gateway/jts.ini config (e.g. a Master Client ID) across container *recreation*.

---

## 2. ibkr-cli (read commands)

`ibkr-cli` ([fatwang2/ibkr-cli](https://github.com/fatwang2/ibkr-cli), MIT — a local-first
IB CLI on `ib_async`/Typer/Rich) is used for all account/market **reads**.

```bash
pipx install ibkr-cli        # recommended (isolated); or: python -m pip install ibkr-cli
ibkr --version
ibkr config path             # shows the config file (auto-created with default profiles)
```

Default profiles are auto-created; the one this project uses is **`gateway-live` →
`127.0.0.1:4001`**. Verify connectivity once the gateway is up:

```bash
ibkr profile list
ibkr doctor        --profile gateway-live
ibkr connect test  --profile gateway-live
ibkr account summary --profile gateway-live --json
```

(Reset profiles to defaults with `ibkr profile init --force`; edit the config file to
change host/port/client_id.)

> Writes (placing/cancelling orders) do NOT go through ibkr-cli — `ibkr-cli buy --submit`
> was observed to cancel marketable orders that didn't fill instantly. Order placement
> uses `ib_async` directly in the autonomous executor and authorized interactive followups.

---

## 3. This repo (uv)

Dependencies (`ib_async`, `pandas`, `numpy`) are managed by uv from `pyproject.toml` /
`uv.lock`:

```bash
uv sync                       # creates ./.venv and installs locked deps
./metrics.py QLD QQQ          # smoke test — prints indicator JSON (read-only, clientId 50)
```

`metrics.py` is shebang'd to `./.venv/bin/python`, so it runs directly once `uv sync` has
created the venv.

---

## 4. Codex CLI and ChatGPT sign-in

Set `codex_bin` in `watcher-config.json` to a working absolute executable path.
This Mac uses `/Applications/Codex.app/Contents/Resources/codex` (verified 0.153.4).

```sh
/Applications/Codex.app/Contents/Resources/codex --version
/Applications/Codex.app/Contents/Resources/codex login
/Applications/Codex.app/Contents/Resources/codex -c 'forced_login_method="chatgpt"' login status
```

Sign in with ChatGPT. The watcher pins `gpt-6-astra` and rejects API-key login mode.
Do not copy auth tokens into the repo. Keep Claude installed only if you want to resume
historical Claude runs. See README for model roles and deadlines.

---

## 5. Phone alerts (ntfy)

```bash
echo "pw-watcher-$(uuidgen | tr 'A-Z' 'a-z' | tr -d '-' | cut -c1-16)" > secrets/ntfy-topic
```
Install the [ntfy](https://ntfy.sh/) app and subscribe to that topic. `notify.sh` pushes
to it after trading outcomes and scheduled weekly report completion/failure. (Swap the `curl` block in `notify.sh` for
Pushover/email if preferred.)

---

## 6. Schedule it (launchd)

Source copies of the launchd jobs live in `launchd/`. Install them:

```bash
cp launchd/com.shawn.portfolio-watcher-*.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.shawn.portfolio-watcher-daily.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.shawn.portfolio-watcher-weekly.plist
```

Daily Tue–Sat 09:00 (Sat reviews Fri's close), Weekly Sat 09:30 (Mac-local +0800). If your paths/username differ,
edit the `.plist` ProgramArguments/StandardOut paths first. Then verify:

```bash
launchctl list | grep portfolio-watcher
~/workspace/portfolio-watcher/run.sh daily --shadow   # test without live execution
```
