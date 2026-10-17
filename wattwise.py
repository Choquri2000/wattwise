"""WattWise engine: parse household electricity usage and compute plain-English insights.

Everything runs in memory. Savings figures are estimates, not guarantees.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DAYS_PER_MONTH = 30.44
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_TIME_HINTS = ("start", "timestamp", "datetime", "date/time", "time", "date", "period")
_VALUE_HINTS = ("kwh", "wh", "kw", "usage", "consumption", "energy", "value", "import")


class UsageError(ValueError):
    """Raised with a user-friendly message when a file cannot be understood."""


@dataclass
class Usage:
    df: pd.DataFrame  # columns: ts (naive local clock), kwh
    interval_min: float
    notes: list = field(default_factory=list)
    hourly: bool = True  # False when data is daily (no hour-of-day analysis)


# ---------------------------------------------------------------- parsing
def _read_table(source) -> pd.DataFrame:
    if isinstance(source, pd.DataFrame):
        return source.copy()
    if hasattr(source, "read"):
        raw = source.read()
    else:
        with open(source, "rb") as f:
            raw = f.read()
    text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw
    lines = text.splitlines()
    start = 0
    for i, ln in enumerate(lines[:60]):  # skip Green Button style preambles
        low = ln.lower()
        if (ln.count(",") + ln.count(";") + ln.count("\t") >= 1
                and any(h in low for h in _TIME_HINTS) and any(h in low for h in _VALUE_HINTS)):
            start = i
            break
    body = "\n".join(lines[start:])
    try:
        return pd.read_csv(io.StringIO(body), sep=None, engine="python")
    except Exception as e:  # noqa: BLE001
        raise UsageError(f"Could not read the file as a CSV table ({e}).") from e


_TZ_RE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2}|\s?UTC|\s?GMT)\s*$", re.I)


def _parse_local(series: pd.Series) -> pd.Series:
    """Parse timestamps keeping the local clock time (offsets are dropped, not converted)."""
    if pd.api.types.is_numeric_dtype(series):
        s = series.astype("float64")
        unit = "ms" if s.median() > 1e11 else "s"
        return pd.to_datetime(s, unit=unit, errors="coerce")
    s = series.astype(str).str.strip().str.replace(_TZ_RE, "", regex=True)
    out = pd.to_datetime(s, errors="coerce", format="mixed")
    if out.notna().mean() < 0.8:
        alt = pd.to_datetime(s, errors="coerce", dayfirst=True, format="mixed")
        if alt.notna().sum() > out.notna().sum():
            out = alt
    return out


def _find_time_col(df):
    cols = list(df.columns)
    for hint in ("start", "timestamp", "datetime", "date/time", "time", "date"):
        for c in cols:
            l = str(c).lower()
            if hint in l and "end" not in l:
                return c
    return cols[0]


def detect_columns(df: pd.DataFrame):
    """Return (time_col, value_col, factor_to_kwh, is_power)."""
    cols = list(df.columns)
    low = {c: str(c).lower() for c in cols}
    time_col = _find_time_col(df)
    cand = [c for c in cols if c != time_col and pd.api.types.is_numeric_dtype(df[c])]
    if not cand:  # numbers stored as text (e.g. "1,234")
        for c in cols:
            if c != time_col:
                conv = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
                if conv.notna().mean() > 0.8:
                    cand.append(c)
    if not cand:
        raise UsageError("No numeric usage column found. Expected a column such as 'kWh' or 'Usage'.")
    value_col = None
    for hint in ("kwh", "wh", "usage", "consumption", "energy", "import", "value", "kw"):
        for c in cand:
            if hint in low[c]:
                value_col = c
                break
        if value_col:
            break
    value_col = value_col or cand[0]
    name = low[value_col]
    factor, power = 1.0, False
    if "kwh" in name:
        factor = 1.0
    elif re.search(r"wh\b", name):
        factor = 0.001
    elif re.search(r"\bkw\b|\(kw\)", name):
        power = True
    elif re.search(r"\bw\b|\(w\)|watt", name):
        power, factor = True, 0.001
    return time_col, value_col, factor, power


def load_usage(source) -> Usage:
    df = _read_table(source)
    if df.empty:
        raise UsageError("The file has no rows.")
    df.columns = [str(c).strip() for c in df.columns]
    notes = []
    lowmap = {c.lower(): c for c in df.columns}
    dcol = next((lowmap[k] for k in lowmap if k in ("date", "start date")), None)
    tcol = next((lowmap[k] for k in lowmap if k in ("start time", "time", "from")), None)
    if dcol and tcol and dcol != tcol:  # Green Button variant: separate DATE and START TIME
        rest = df.drop(columns=[tcol])
        _, value_col, factor, power = detect_columns(rest)
        ts = _parse_local(df[dcol].astype(str) + " " + df[tcol].astype(str))
        time_label = f"{dcol} + {tcol}"
    else:
        time_col, value_col, factor, power = detect_columns(df)
        ts = _parse_local(df[time_col])
        time_label = time_col
    val = df[value_col]
    if not pd.api.types.is_numeric_dtype(val):
        val = pd.to_numeric(val.astype(str).str.replace(",", ""), errors="coerce")
    out = pd.DataFrame({"ts": ts, "kwh": val}).dropna()
    dropped = len(df) - len(out)
    if len(out) < 7:
        raise UsageError("Too few valid rows (need at least a week of data).")
    out = out.groupby("ts", as_index=False)["kwh"].sum().sort_values("ts").reset_index(drop=True)
    diffs = out["ts"].diff().dropna().dt.total_seconds() / 60
    interval = float(diffs.median()) if len(diffs) else 60.0
    if power:
        out["kwh"] = out["kwh"] * factor * (interval / 60)
        notes.append(f"Column '{value_col}' looked like power; converted to energy using the {interval:g}-min interval.")
    else:
        out["kwh"] = out["kwh"] * factor
        if factor != 1.0:
            notes.append(f"Column '{value_col}' looked like Wh; converted to kWh.")
    if (out["kwh"] < 0).any():
        out["kwh"] = out["kwh"].clip(lower=0)
        notes.append("Negative readings (e.g. solar export) were treated as 0.")
    if dropped:
        notes.append(f"{dropped} rows with missing/invalid values were ignored.")
    notes.append(f"Time column '{time_label}', usage column '{value_col}', interval ≈ {interval:g} min. "
                 "Timezone offsets are ignored (local clock time kept).")
    hourly = interval <= 90
    if hourly and interval < 59:
        out = out.set_index("ts")["kwh"].resample("1h").sum().reset_index()
        interval = 60.0
        notes.append("Sub-hourly data was summed into hourly totals.")
    if not hourly:
        notes.append("Data is coarser than hourly, so hour-of-day insights (standby, peak hours) are unavailable.")
    if (out["ts"].max() - out["ts"].min()).days < 6:
        raise UsageError("Need at least 7 days of data for meaningful patterns.")
    return Usage(out, interval, notes, hourly)


# ---------------------------------------------------------------- demo data
def generate_demo(days: int = 120, seed: int = 7, start: str = "2025-01-01") -> pd.DataFrame:
    """Hourly household with a planted ~0.35 kW standby load and an evening peak (17-21h)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=days * 24, freq="h")
    hour, dow = idx.hour.values, idx.dayofweek.values
    base = 0.35  # planted standby (kW)
    prof = np.zeros(len(idx))
    prof += np.where((hour >= 6) & (hour <= 8), 0.45, 0)
    prof += np.where((hour >= 9) & (hour <= 16), 0.18, 0)
    prof += np.where((hour >= 17) & (hour <= 21), 1.45, 0)
    prof += np.where(hour == 22, 0.5, 0)
    prof += np.where((dow >= 5) & (hour >= 10) & (hour <= 16), 0.5, 0)
    season = 1 + 0.25 * np.cos((idx.dayofyear.values - 15) / 365 * 2 * np.pi)
    kwh = (base + prof * season) * (1 + rng.normal(0, 0.06, len(idx)))
    kwh += rng.normal(0, 0.02, len(idx))
    spikes = rng.choice(len(idx), size=6, replace=False)
    kwh[spikes] += rng.uniform(2.5, 4.0, 6)  # e.g. oven / dryer / heater left on
    kwh = np.clip(kwh, 0.05, None)
    return pd.DataFrame({"Start Time": idx.strftime("%Y-%m-%dT%H:%M:%S+04:00"), "Usage (kWh)": kwh.round(3)})


# ---------------------------------------------------------------- analysis
@dataclass
class Settings:
    price: float = 0.15
    peak_start: int = 17
    peak_end: int = 21  # exclusive
    use_tou: bool = False
    peak_price: float = 0.25
    offpeak_price: float = 0.10
    shift_pct: float = 20.0
    standby_cut_pct: float = 30.0


def _in_peak(hours, s: Settings):
    if s.peak_start <= s.peak_end:
        return (hours >= s.peak_start) & (hours < s.peak_end)
    return (hours >= s.peak_start) | (hours < s.peak_end)


def analyze(u: Usage, s: Settings) -> dict:
    d = u.df.copy()
    d["date"] = d["ts"].dt.floor("D")
    d["dow"] = d["ts"].dt.dayofweek
    d["is_weekend"] = d["dow"] >= 5
    n_days = max(d["date"].nunique(), 1)
    total = float(d["kwh"].sum())
    daily = d.groupby("date")["kwh"].sum()
    avg_daily = float(daily.mean())
    monthly_kwh = avg_daily * DAYS_PER_MONTH
    r: dict = {"total_kwh": total, "days": n_days, "avg_daily_kwh": avg_daily, "monthly_kwh": monthly_kwh,
               "start": d["ts"].min(), "end": d["ts"].max(), "hourly": u.hourly}

    m = d.groupby(d["ts"].dt.to_period("M")).agg(kwh=("kwh", "sum"), days=("date", "nunique"))
    m["kwh_per_day"] = m["kwh"] / m["days"]
    m["partial"] = m["days"] < 25
    m.index = m.index.astype(str)
    r["monthly"] = m

    wd = d[~d["is_weekend"]].groupby("date")["kwh"].sum()
    we = d[d["is_weekend"]].groupby("date")["kwh"].sum()
    r["weekday_daily"] = float(wd.mean()) if len(wd) else np.nan
    r["weekend_daily"] = float(we.mean()) if len(we) else np.nan

    if u.hourly:
        d["hour"] = d["ts"].dt.hour
        night = d[d["hour"] <= 5].groupby("date")["kwh"].min()
        base_kw = float(night.median()) * (60 / u.interval_min) if len(night) else np.nan
        r["baseload_kw"] = base_kw
        r["standby_kwh_month"] = base_kw * 24 * DAYS_PER_MONTH
        r["standby_share"] = min(base_kw * 24 / avg_daily, 1.0) if avg_daily else np.nan
        pk = _in_peak(d["hour"], s)
        peak_kwh = float(d.loc[pk, "kwh"].sum())
        r["peak_share"] = peak_kwh / total if total else np.nan
        r["peak_kwh_month"] = peak_kwh / n_days * DAYS_PER_MONTH
        r["offpeak_kwh_month"] = monthly_kwh - r["peak_kwh_month"]
        hm = d.pivot_table(index="dow", columns="hour", values="kwh", aggfunc="mean")
        hm = hm.reindex(index=range(7), columns=range(24))
        hm.index = DOW
        r["heatmap"] = hm
        prof = d.groupby(["is_weekend", "hour"])["kwh"].mean().unstack(0)
        prof.columns = ["Weekday" if not c else "Weekend" for c in prof.columns]
        r["profile"] = prof
        # spikes vs the household's own baseline (same hour-of-day, weekday/weekend)
        g = d.groupby(["is_weekend", "hour"])["kwh"]
        med = g.transform("median")
        mad = (d["kwh"] - med).abs().groupby([d["is_weekend"], d["hour"]]).transform("median") * 1.4826
        thresh = np.maximum(med + 4 * mad, med * 2)
        sp = d[(d["kwh"] > thresh) & (d["kwh"] > med + 0.5)].copy()
        sp["typical_kwh"] = med[sp.index]
        sp["excess_kwh"] = sp["kwh"] - sp["typical_kwh"]
        r["spikes"] = sp.sort_values("excess_kwh", ascending=False)[["ts", "kwh", "typical_kwh", "excess_kwh"]].head(10)
        r["n_spikes"] = len(sp)
        r["spike_excess_kwh"] = float(sp["excess_kwh"].sum())
        if s.use_tou:
            r["monthly_cost"] = r["peak_kwh_month"] * s.peak_price + r["offpeak_kwh_month"] * s.offpeak_price
        else:
            r["monthly_cost"] = monthly_kwh * s.price
        r["shifted_kwh_month"] = r["peak_kwh_month"] * s.shift_pct / 100
        r["shift_saving"] = r["shifted_kwh_month"] * (s.peak_price - s.offpeak_price) if s.use_tou else None
        r["standby_saving"] = r["standby_kwh_month"] * s.standby_cut_pct / 100 * (
            s.offpeak_price if s.use_tou else s.price)
    else:
        r["monthly_cost"] = monthly_kwh * s.price
        r["baseload_kw"] = r["standby_kwh_month"] = r["standby_share"] = r["peak_share"] = np.nan
        r["shift_saving"] = r["standby_saving"] = None
        r["spikes"] = pd.DataFrame(columns=["ts", "kwh", "typical_kwh", "excess_kwh"])
        r["spike_excess_kwh"] = 0.0
        r["heatmap"] = r["profile"] = None
        med = daily.median()
        mad = (daily - med).abs().median() * 1.4826
        r["n_spikes"] = int((daily > med + max(4 * mad, 0.5 * med)).sum())
    return r


def summarize(r: dict, s: Settings, currency: str = "$") -> dict:
    """Plain-English headline + exactly 3 takeaways (hedged, estimates only)."""
    c = currency
    head = (f"Over {r['days']} days you used about {r['total_kwh']:,.0f} kWh "
            f"(≈ {r['avg_daily_kwh']:.1f} kWh/day, ≈ {r['monthly_kwh']:,.0f} kWh/month), "
            f"which would cost roughly {c}{r['monthly_cost']:,.0f} per month at your entered price(s).")
    tips = []
    if r["hourly"]:
        bk = r["baseload_kw"]
        if np.isfinite(bk):
            unit = s.offpeak_price if s.use_tou else s.price
            tips.append(
                f"**Always-on load:** your overnight minimum is about {bk * 1000:,.0f} W, roughly "
                f"{r['standby_share'] * 100:.0f}% of your usage (≈ {r['standby_kwh_month']:,.0f} kWh/month, ≈ {c}"
                f"{r['standby_kwh_month'] * unit:,.0f}/month). "
                f"Cutting {s.standby_cut_pct:.0f}% of it (old fridge, set-top boxes, chargers, always-on devices) "
                f"could save about {c}{r['standby_saving']:,.1f}/month — an estimate; check what is actually plugged in.")
        hrs = (s.peak_end - s.peak_start) % 24 or 24
        tips.append(
            f"**Peak hours ({s.peak_start:02d}:00–{s.peak_end:02d}:00):** {r['peak_share'] * 100:.0f}% of your electricity falls "
            f"in {hrs} of 24 hours. " +
            (f"Moving {s.shift_pct:.0f}% of it (laundry, dishwasher, EV charging) to off-peak could save about "
             f"{c}{r['shift_saving']:,.1f}/month under your time-of-use prices — an estimate, and only if your tariff really has them."
             if r["shift_saving"] is not None else
             "You are on a flat price, so shifting use would not change your bill; enable time-of-use prices in the "
             "sidebar to test a tariff with cheaper off-peak hours."))
        if r["n_spikes"]:
            tips.append(f"**Unusual spikes:** {r['n_spikes']} hours were far above your own normal for that hour "
                        f"(≈ {r['spike_excess_kwh']:,.0f} kWh extra in total). See the list below and ask whether a "
                        "heater, oven or dryer was left on.")
        else:
            tips.append("**No unusual spikes:** no hour stood out strongly against your own pattern.")
    else:
        tips.append("**Daily data only:** hour-of-day insights need hourly or 15-minute data. Export a finer interval from your utility for standby and peak analysis.")
        tips.append(f"**Spikes:** {r['n_spikes']} days were well above your usual daily level.")
    wd, we = r["weekday_daily"], r["weekend_daily"]
    if np.isfinite(wd) and np.isfinite(we) and wd > 0:
        diff = (we / wd - 1) * 100
        if abs(diff) >= 10:
            tips.append(f"**Weekday vs weekend:** weekends use {abs(diff):.0f}% {'more' if diff > 0 else 'less'} than weekdays "
                        f"({we:.1f} vs {wd:.1f} kWh/day).")
        else:
            tips.append(f"**Steady week:** weekends and weekdays are within {abs(diff):.0f}% of each other ({we:.1f} vs {wd:.1f} kWh/day).")
    while len(tips) < 3:
        tips.append("**More data helps:** upload a few months to see seasonal trends.")
    return {"headline": head, "takeaways": tips[:3]}
