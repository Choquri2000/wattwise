import io

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import wattwise as ww


def _hourly_frame(days=21, base=0.3):
    idx = pd.date_range("2025-03-01", periods=days * 24, freq="h")
    kwh = base + np.where((idx.hour >= 18) & (idx.hour < 21), 1.2, 0.1)
    return idx, kwh


def test_demo_planted_baseload_and_peak():
    u = ww.load_usage(ww.generate_demo())
    r = ww.analyze(u, ww.Settings(use_tou=True))
    assert 0.25 <= r["baseload_kw"] <= 0.42
    assert r["peak_share"] > 0.3
    assert r["n_spikes"] >= 3
    assert r["shift_saving"] > 0
    assert r["heatmap"].shape == (7, 24)


def test_summary_has_three_takeaways():
    u = ww.load_usage(ww.generate_demo())
    for tou in (False, True):
        s = ww.Settings(use_tou=tou)
        out = ww.summarize(ww.analyze(u, s), s)
        assert len(out["takeaways"]) == 3
        assert "estimate" in " ".join(out["takeaways"]).lower()


def test_wh_units_converted():
    idx, kwh = _hourly_frame()
    df = pd.DataFrame({"Timestamp": idx.strftime("%Y-%m-%d %H:%M"), "Energy (Wh)": kwh * 1000})
    u = ww.load_usage(df)
    assert u.df["kwh"].sum() == pytest.approx(kwh.sum(), rel=1e-6)


def test_15min_summed_to_hourly():
    idx = pd.date_range("2025-03-01", periods=14 * 96, freq="15min")
    df = pd.DataFrame({"start": idx, "kWh": 0.1})
    u = ww.load_usage(df)
    assert u.hourly and u.interval_min == 60
    assert u.df["kwh"].iloc[0] == pytest.approx(0.4)


def test_daily_data_limited_insights():
    idx = pd.date_range("2025-01-01", periods=60, freq="D")
    df = pd.DataFrame({"Date": idx.strftime("%m/%d/%Y"), "Usage": np.full(60, 12.0)})
    u = ww.load_usage(df)
    assert not u.hourly
    r = ww.analyze(u, ww.Settings())
    assert r["heatmap"] is None and r["monthly_cost"] == pytest.approx(12 * ww.DAYS_PER_MONTH * 0.15)
    assert len(ww.summarize(r, ww.Settings())["takeaways"]) == 3


def test_timezone_offsets_keep_local_clock():
    df = pd.DataFrame({"Start": ["2025-03-01T00:00:00+04:00", "2025-03-01T01:00:00+04:00"] +
                       [f"2025-03-{d:02d}T00:00:00-05:00" for d in range(2, 12)], "kWh": 1.0})
    u = ww.load_usage(df)
    assert u.df["ts"].iloc[0] == pd.Timestamp("2025-03-01 00:00")
    assert u.df["ts"].iloc[1] == pd.Timestamp("2025-03-01 01:00")


def test_green_button_preamble_and_separate_date_time_columns():
    idx = pd.date_range("2025-03-01", periods=10 * 24, freq="h")
    body = "Name,John\nAddress,1 Main St\n\nDATE,START TIME,END TIME,USAGE (kWh),NOTES\n"
    body += "\n".join(f"{t:%Y-%m-%d},{t:%H:%M},{(t + pd.Timedelta(hours=1)):%H:%M},0.5," for t in idx)
    u = ww.load_usage(io.BytesIO(body.encode()))
    assert len(u.df) == len(idx)
    assert u.df["kwh"].sum() == pytest.approx(0.5 * len(idx))


def test_kw_power_column():
    idx = pd.date_range("2025-03-01", periods=10 * 24, freq="h")
    u = ww.load_usage(pd.DataFrame({"time": idx, "Demand (kW)": 2.0}))
    assert u.df["kwh"].iloc[0] == pytest.approx(2.0)


def test_bad_inputs():
    with pytest.raises(ww.UsageError):
        ww.load_usage(pd.DataFrame({"a": ["x", "y"], "b": ["p", "q"]}))
    with pytest.raises(ww.UsageError):
        ww.load_usage(pd.DataFrame({"time": pd.date_range("2025-01-01", periods=10, freq="h"), "kWh": 1.0}))


def test_demo_csv_file_roundtrip():
    u = ww.load_usage("demo_usage.csv")
    assert len(u.df) == 120 * 24


def test_app_end_to_end_demo():
    at = AppTest.from_file("app.py", default_timeout=60).run()
    assert not at.exception
    next(c for c in at.checkbox if c.label == 'Use demo data').check().run()
    assert not at.exception
    txt = " ".join(m.value for m in at.markdown)
    assert "Always-on load" in txt and "Peak hours" in txt
    assert len(at.metric) == 4
