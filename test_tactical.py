import math
import tactical as t

def test_entry_gate():
    assert t.entry_gate(110, 100, 90, True) is True
    assert t.entry_gate(95, 100, 90, True) is False
    assert t.entry_gate(110, 100, 90, False) is False

def test_extension_and_dampening():
    assert abs(t.extension_pct(131, 100) - 0.31) < 1e-9
    assert t.dampened_fraction(0.10) == 1.0
    assert t.dampened_fraction(0.52) == 0.10
    mid = t.dampened_fraction(0.32)
    assert 0.10 < mid < 1.0

def test_risk_budget_shares():
    sh = t.risk_budget_shares(265000, 26.8, 347)
    assert sh == 28
    capped = t.risk_budget_shares(265000, 0.05, 10)
    assert capped * 10 <= 0.06 * 265000 + 10

def test_b1_b2_b3():
    assert abs(t.b1_trail_level(100, 5) - 85.0) < 1e-9
    assert abs(t.b2_catastrophe_level(100, 5) - 77.5) < 1e-9
    assert t.b3_regime_break(99, 100) is True
    assert t.b3_regime_break(101, 100) is False

def test_cooldown():
    assert t.cooldown_ok(120, 110, 1, 100, 99) is True
    assert t.cooldown_ok(105, 110, 2, 100, 99) is False
    assert t.cooldown_ok(105, 110, 5, 100, 99) is True
    assert t.cooldown_ok(105, 110, 6, 100, 101) is False

def test_levels_from_bars():
    closes = [10,11,12,13,12,11]
    highs  = [10,11,12,13,12,11]
    lows   = [10,11,12,13,12,11]
    out = t.levels_from_bars(closes, highs, lows, entry_date_idx=0, atr_mult=3.0)
    assert out["highest_close_since_entry"] == 13
    assert out["b1_trail"] == 13 - 3.0 * out["atr14"]
    assert out["b2_floor"] < out["b1_trail"]
