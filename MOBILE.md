# Mobile access — chat with a followup session from your iPhone (AFK)

Goal: from your iPhone 15 Pro Max, anywhere, open `watcher-followup daily|weekly` and
chat with the session (including placing orders) — despite the home network's **dynamic
public IP**.

## How it solves the dynamic-IP problem

**Tailscale** puts the Mac and the phone on a private encrypted mesh (WireGuard). They
reach each other by stable tailnet name (`shawns-macbook-pro`), brokered through
Tailscale regardless of the home IP / NAT — **no port-forwarding, no DDNS, nothing
exposed to the public internet**. Then **mosh** (over Tailscale) gives a session that
survives cellular↔wifi switches and lock; **tmux** (via the `wf` wrapper) makes it
reattachable if the link fully drops. The Mac stays invisible to the internet; only your
own logged-in devices can reach it.

```
iPhone: Tailscale + Blink(mosh) ──encrypted──► Mac: sshd + mosh + tmux
  Home-Screen icon → blinkshell:// → mosh mac -- wf daily → claude -r (Opus 4.8)
```

---

## Part A — Mac (one-time; needs YOUR admin password)

Already done for you: `mosh` + `tmux` installed, `~/.ssh/authorized_keys` prepared, and
the `wf` wrapper (`~/.local/bin/wf <daily|weekly>` → reattachable tmux + watcher-followup).

You run these three (they need sudo / a GUI login):

1. **Install Tailscale & sign in**
   ```zsh
   brew install --cask tailscale     # enter your password; or install from the App Store
   open -a Tailscale                  # sign in (same account you'll use on the phone)
   ```
2. **Enable Remote Login (sshd)** — mosh bootstraps through it:
   System Settings → General → Sharing → **Remote Login = On** (limit to your user), or:
   ```zsh
   sudo systemsetup -setremotelogin on
   ```
3. **Keep the Mac reachable AFK** (don't sleep on power):
   ```zsh
   sudo pmset -c sleep 0
   ```

(Optional, avoids SSH keys entirely: `tailscale up --ssh` enables Tailscale SSH — then the
phone can `ssh`/`mosh` with no key setup, authorized by your tailnet identity. The key
method below is the most universally compatible, so it's the default here.)

---

## Part B — iPhone (one-time)

1. **Tailscale app** → sign in (same account). Confirm `shawns-macbook-pro` shows up.
2. **Blink Shell** (App Store) → install.
3. **Make an SSH key in Blink:** Settings → Keys → **+** → generate (ed25519), name it
   `iphone`. Tap it → **Copy Public Key**.
4. **Add that key to the Mac.** Easiest: in any session on the Mac run
   ```zsh
   echo 'PASTE_THE_PUBLIC_KEY_HERE' >> ~/.ssh/authorized_keys
   ```
5. **Add a Host in Blink:** Settings → Hosts → **+**
   - Alias: `mac`
   - HostName: `shawns-macbook-pro`  (the Tailscale MagicDNS name; or its `100.x.y.z` IP)
   - User: `shawn`
   - Key: `iphone`
   - Enable **mosh** (Blink's "Prefer Mosh" / mosh server `mosh-server`).
6. **Test:** in Blink type `mosh mac` → you should land on the Mac. Then `wf daily`
   drops you into the daily watcher session. `Ctrl-b d` detaches tmux; closing Blink is
   fine — `wf daily` reattaches the same conversation next time.

---

## Part C — Two Home-Screen icons (daily / weekly)

Uses Blink's URL scheme from the Shortcuts app, then "Add to Home Screen".

1. In **Blink**: Settings → enable the URL scheme / "URL Actions" and note/create the
   **action key** (Blink requires a key so other apps can't run arbitrary commands).
   Call it `home`.
2. In **Shortcuts** app → **+** → add action **Open URLs** (or "Open X-Callback URL") with:
   ```
   blinkshell://run?key=home&cmd=mosh%20mac%20--%20%2FUsers%2Fshawn%2F.local%2Fbin%2Fwf%20daily
   ```
   That `cmd` is URL-encoded `mosh mac -- /Users/shawn/.local/bin/wf daily`.
   Name the Shortcut **Watcher Daily**.
3. Shortcut → Share → **Add to Home Screen** → pick a name + icon (e.g. 📈 "Watcher Daily").
4. **Duplicate** the Shortcut, change `wf%20daily` → `wf%20weekly`, name it **Watcher
   Weekly**, add to Home Screen with a different icon (e.g. 🗓️).

Now tapping **Watcher Daily** / **Watcher Weekly** opens Blink and lands you straight in
that session over mosh — reattaching the live tmux if it's already running.

> If Blink's URL-scheme key/params differ in your version, the fallback is a Shortcut with
> Blink's own **Shortcuts action** ("Run command in Blink"), command =
> `mosh mac -- /Users/shawn/.local/bin/wf daily`, then Add to Home Screen.

---

## Security notes

- The Mac is reachable **only** from devices logged into your Tailscale account — it is not
  on the public internet. Order placement from the phone = the whole point, so guard the
  phone: Face ID lock + a Blink passcode (Blink Settings → Security).
- Lost phone? Remove it from your tailnet (Tailscale admin console → Machines → remove) to
  instantly cut its access.
- Do NOT enable Tailscale **Funnel** for this host (that would expose it publicly).
