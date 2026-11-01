# tactical — dip-buy / tactical-overlay research (2026-11-01)

Backs **[[Tactical Opportunity Book — Research & Proposal 2026-11-01]]** (vault
`03-strategies/trend-following/`). Stdlib only, reads `../data_adj`. Run each as
`python3 tactical/pN_*.py tactical` from `ai-infra-bt/`.

| script | question |
|---|---|
| `p1_live_vs_bt.py` | is the live −10% drawdown abnormal for v3? |
| `p2_core_dip.py` | QQQ dip-buy forward returns vs random entry, IS 1999–2012 / OOS 2013–2026 |
| `p3_overlay.py` | tactical QLD overlay at portfolio level, exit variants (time/stop/trail/gate) |
| `p4_gateoff.py` | buying a theme the month its v3 gate turns DEFENSIVE — 22-ETF control set |
| `p5_static.py` | same-exposure static benchmark for p3 |
