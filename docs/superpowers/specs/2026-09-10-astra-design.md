# Astra watcher migration — approved design

Approved by Shawn on 2026-09-10. Use Codex ChatGPT sign-in and exact gpt-6-astra.
Keep launchd daily Tue–Sat 09:00 / weekly Sat 09:30 Taipei, local IBKR execution,
structural rails, ntfy/macOS notifications, Blink/mosh/tmux, and historical Claude resume.

A frozen plan must carry its own engine snapshot. Scheduled review receives a complete
packet, cannot call tools, and returns a strict verdict/reason/plan_sha256 object.
Only a completed validated APPROVE can reach replay. Five-minute attempt timeout;
one retry only for transient transport/timeout. No API fallback or retry of HALT.
Collect catalysts plus sourced corporate-action/halt evidence before review. Unknown
material risk must fail closed. CLI configuration must exclude inherited integrations.

The controller writes actual outcomes to metadata and the vault. Full weekly analysis
runs once per weekly invocation, independently of the trading outcome; daily runs never
trigger it. A reporting failure does not overwrite trading status. Analysis can use web
search but cannot access brokerage or mutate files; the controller publishes its text.

Stable watcher IDs map to Codex review/report/followup IDs. Followup starts separately,
receives actual execution evidence, then resumes reliably. Preserve default unrestricted
interactive tools and --safe mode, with distinct tmux sessions. Legacy Claude uses its
original provider. Historical artifacts remain untouched.

Test with fake process boundaries and shadow runs (no live execution), then activate only
after tests, tool-isolation probes, auth checks, replay and mobile command checks pass.
