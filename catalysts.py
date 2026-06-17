#!/Users/shawn/workspace/portfolio-watcher/.venv/bin/python
"""Catalyst calendar for the Portfolio Watcher — upcoming earnings + US macro events.

Pre-market PRICE is noise for a close-based trend system, but *scheduled catalysts* are
genuinely telling: a holding that reports earnings tomorrow, or an FOMC/CPI/NFP print in
the next few days, governs overnight GAP risk and whether to rest a limit now or wait. It
never changes a trend SIGNAL (those stay close-based) — only execution timing.

Deliberately SEPARATE from metrics.py (the IB read path): this makes a network call to
Yahoo (yfinance) for earnings and reads the curated macro calendar, and must NEVER be able
to break the core IB metrics. It degrades gracefully — a failed earnings lookup yields
{"date": null, "note": ...}, never an exception that aborts the run; macro still prints if
yfinance is missing entirely.

THIS FILE CONTAINS NO ORDER CODE. Reads only.

Usage:
  catalysts.py SYM [SYM ...] [--days 7]

Output (stdout): one JSON object:
  {"asof": <utc iso>, "today_et": "YYYY-MM-DD", "window_days": 7,
   "earnings": {"MSFT": {"date":"2026-07-22","in_days":5,"when":"amc","in_window":true}|
                        {"date": null, "note": "..."}, ...},
   "macro": [{"date":"2026-06-17","event":"FOMC decision","impact":"high","in_days":1,
              "in_window":true}, ...],
   "calendar_stale": false, "notes": [...]}

`in_days` is counted from the current US/Eastern date — i.e. the next US trading session is
in_days 0 or 1. So "FOMC in_days 1" means it lands on the very next session you're trading.
"""
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo

DIR = Path(__file__).resolve().parent
CAL_PATH = DIR / "data" / "econ_calendar.json"

# ETFs / leveraged funds in the watcher's universe — no earnings; skip the yfinance call.
ETFS = {"QLD", "QQQ", "TQQQ", "SGOV", "AGQ", "SPY", "IWM", "DIA"}


def today_eastern():
    return datetime.now(ZoneInfo("America/New_York")).date()


def load_macro(today, window, notes):
    """Read the curated macro calendar; return forward events within the window."""
    try:
        data = json.loads(CAL_PATH.read_text())
    except Exception as e:  # noqa: BLE001
        notes.append(f"macro calendar unreadable ({CAL_PATH.name}): {e}")
        return [], False
    stale = False
    vt = data.get("verified_through")
    if vt:
        try:
            if today > date.fromisoformat(vt):
                stale = True
                notes.append(
                    f"macro calendar STALE — verified_through {vt} has passed; "
                    "refresh FOMC (federalreserve.gov) + CPI/NFP (bls.gov/schedule)."
                )
        except ValueError:
            pass
    out = []
    for ev in data.get("events", []):
        try:
            d = date.fromisoformat(ev["date"])
        except (KeyError, ValueError):
            continue
        in_days = (d - today).days
        if in_days < 0:
            continue  # past
        out.append({
            "date": ev["date"],
            "event": ev.get("event", "?"),
            "impact": ev.get("impact", "med"),
            "in_days": in_days,
            "in_window": in_days <= window,
        })
    out.sort(key=lambda x: x["date"])
    return out, stale


def next_earnings(sym, today, window):
    """Next future earnings date for a single stock via yfinance. Never raises."""
    if sym.upper() in ETFS:
        return {"date": None, "note": "ETF — no earnings"}
    try:
        import yfinance as yf
    except Exception:  # noqa: BLE001 — ImportError or partial install
        return {"date": None, "note": "yfinance unavailable"}

    best = None  # (date, when)
    # Primary: get_earnings_dates returns a tz-aware DatetimeIndex (US/Eastern),
    # future estimates + past actuals.
    try:
        t = yf.Ticker(sym)
        df = t.get_earnings_dates(limit=16)
        if df is not None and len(df):
            for ts in df.index:
                d = ts.date()
                if d < today:
                    continue
                when = None
                hour = getattr(ts, "hour", None)
                if hour is not None:
                    when = "bmo" if hour < 12 else "amc"
                if best is None or d < best[0]:
                    best = (d, when)
    except Exception:  # noqa: BLE001
        pass

    # Fallback: .calendar dict often carries 'Earnings Date' as a list of date(s).
    if best is None:
        try:
            cal = yf.Ticker(sym).calendar
            ed = None
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
            if ed:
                cands = ed if isinstance(ed, (list, tuple)) else [ed]
                for c in cands:
                    d = c.date() if hasattr(c, "date") else c
                    if isinstance(d, date) and d >= today:
                        if best is None or d < best[0]:
                            best = (d, None)
        except Exception:  # noqa: BLE001
            pass

    if best is None:
        return {"date": None, "note": "no upcoming date found"}
    d, when = best
    in_days = (d - today).days
    res = {"date": d.isoformat(), "in_days": in_days, "in_window": in_days <= window}
    if when:
        res["when"] = when  # bmo = before open, amc = after close
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--days", type=int, default=7, help="look-ahead window (default 7)")
    args = ap.parse_args()

    today = today_eastern()
    window = args.days
    notes = []

    macro, stale = load_macro(today, window, notes)
    earnings = {}
    for sym in dict.fromkeys(s.upper() for s in args.symbols):
        earnings[sym] = next_earnings(sym, today, window)

    out = {
        "asof": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today_et": today.isoformat(),
        "window_days": window,
        "earnings": earnings,
        "macro": macro,
        "calendar_stale": stale,
        "notes": notes,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
