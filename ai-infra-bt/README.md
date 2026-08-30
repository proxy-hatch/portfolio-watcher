# ai-infra-bt — trend-following research harness

Engines behind **[[AI-Infra Tactical Trend (v3 spec) 2026-08-25]]** and
**[[Trend Sleeve v3.1 — Research Findings 2026-08-25]]** (vault:
`03-strategies/trend-following/`). Stdlib Python only, deterministic, no deps.

## THREE benches — pick by the question
| bench | file | answers |
|---|---|---|
| trade-level | `engine.py` | "is this trade rule good?" (R-multiples, stops, exits) |
| portfolio | `bench2.py` | "is this a business?" (equity curve, vol targeting, leverage, correlation, drawdown) |
| cross-sectional | `bench3.py` | "which names, not just when?" (rank top-K, dual momentum) + **adjusted-data loader** |

## DATA RULE (added 2026-08-25, invalidated earlier results)
Always fetch `--what-to-show ADJUSTED_LAST`. Price-only TRADES bars understate
TLT by 2.7%/yr and are disqualifying for any distribution-paying instrument.
`data/` = price-only (legacy), `data_adj/` = total return (**use this**).
IBKR paces historical requests at ~60 per 10 min — `fetch_slow.sh` sleeps 15s.

    python3 run_final.py     # regenerates every number quoted in v3 spec §3
    python3 status.py [NAV]  # live gate screen + risk-budgeted sizing

## Files
| file | step | purpose |
|---|---|---|
| `engine.py`   | — | indicators, strategy state machine, metrics. **The contract.** |
| `universe.py` | — | frozen name lists, periods, and the accidental-v1 benchmark |
| `run_is.py`   | 1a | in-sample ablation, one change at a time |
| `run_is2.py`  | 1b | entry-quality ablation + combinations |
| `run_oos.py`  | 2a | out-of-sample, frozen configs |
| `run_oos2.py` | 2b | adds trend-capture % and the anti-survivorship control |
| `run_sens.py` | 3  | one-at-a-time parameter sensitivity |
| `run_final.py`| 4  | frozen v3-FINAL report |
| `status.py`   | —  | live gate screen, reusable by the daily watcher |

## v3-FINAL parameters
```python
dict(gc=True, hh_tol=0.95, clear=2.0, m1=3.5, m2=5.25, b3="buffer", b3_buf=0.5,
     shock=0.0, reentry="v2", n_cool=5, cost=0.0015)
```

## Rules of the road (see v3 spec Appendix A6)
1. Select parameters on `universe.IS_NAMES` / `IS_PERIOD` **only**.
2. Freeze configs, then run `universe.EVAL` **once**. No refitting afterwards.
3. **Always include the anti-survivorship control set** (`run_oos2.CONTROL`).
   Sets picked because a name went up will flatter any long-only trend system.
4. Report a sensitivity sweep. A knife-edge optimum is an overfit optimum.
5. Refresh data with `fetch.sh`-style calls; re-check the >80% jump screen and
   `engine.VALID_START` whenever a symbol is added (v3 spec Appendix B).

## Data
`data/*.json` — IBKR daily bars, `ibkr bars <SYM> --duration "6 Y" --bar-size "1 day" --json`.
Split-adjusted, **not** dividend-adjusted. 48 symbols cached 2026-08-25.


## Headline results (2026-08-25)
- Single-name trend, anti-survivorship IS: v2 **−0.15 R**, v3 **+0.07 R** — no edge.
- Diversified cross-asset trend standalone 2011-2026: Sharpe **0.36-0.48** vs SPY **1.05**.
- 2007-2010 GFC: Ensemble Donchian L/S **13.5% CAGR, Sharpe 0.90, −14.9% maxDD** — crisis alpha is the product.
- **20% trend overlay + 1.41x leverage on the QLD core: +3.5pp CAGR at identical −20.6% maxDD.**

    python3 run_universe.py run_decisive.py run_stack.py run_blend.py
