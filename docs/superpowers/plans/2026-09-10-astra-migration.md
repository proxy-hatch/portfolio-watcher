# Astra Migration Implementation Plan

**Goal:** Replace the scheduled and mobile agent with Codex while preserving execution rails.
**Architecture:** Python process adapter, deterministic pipeline controller and provider-aware
followup dispatcher behind existing shell entrypoints. Review/report artifacts are distinct.
**Tech stack:** Python stdlib, existing venv for broker scripts, zsh, Codex CLI, tmux/ntfy.
**Spec:** ../specs/2026-09-10-astra-design.md

## Constraints
- ChatGPT sign-in; gpt-6-astra; no automatic API/provider fallback.
- Scheduled verdict has no tools; web-only evidence/report agents; interactive tools only on followup.
- Tests never place orders. Shadow writes only its own metadata/log namespace.
- Legacy history remains readable. No strategy parameter or account-map changes.

## Tasks (inline execution)
- [x] Adapter: tests for strict response parsing, completion/error events, retry policy and process-group timeout cleanup; implement codex_agent.py plus watcher-config.json.
- [x] Snapshot: test save_plan includes exact targets and empty plans; extend v3_execute.py output without changing its calculation or replay behavior.
- [x] Controller: test APPROVE/HALT/failure/shadow/blocked/empty branches; implement watcher.py with serialized run lock, run metadata, evidence, deterministic log and notification.
- [x] Weekly: test report executes only on weekly including failed trading, and separate report outcomes; bounded daily/audit packet, atomic controller publication.
- [x] Mobile: test provider routing, bootstrap vs resume, safe/default separation and ambiguous IDs; implement followup dispatcher and update shell wrappers.
- [x] Verification: run stdlib unit tests, existing tactical functions, zsh syntax, real CLI isolation probes, historical replay, daily/weekly shadow and ntfy transport probe. Review diff for unauthorized execution paths.
- [ ] Deployment: update docs and vault prompts, commit, fast-forward clean main after checking active jobs, push and verify scheduled entrypoints and installed schedule.

## Commands
`python3 -m unittest discover -s tests -v` for regression coverage.
`run.sh daily --shadow` and `run.sh weekly --shadow` for controlled real-data validation.
`watcher.py probe` for authenticated Codex capability/output checks with no broker access.
