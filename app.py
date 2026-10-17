"""WattWise - privacy-first household electricity insights (Streamlit UI)."""
import altair as alt
import streamlit as st

import wattwise as ww

st.set_page_config(page_title="WattWise - understand your electricity use", page_icon="⚡", layout="wide")
st.title("⚡ WattWise")
st.caption("Upload your electricity usage CSV and get plain-English insights. "
           "Your file is processed in memory only — never stored, never sent to any AI or third party.")

with st.sidebar:
    st.header("Your prices")
    currency = st.text_input("Currency symbol", "$", max_chars=4)
    price = st.number_input("Price per kWh", 0.0, 10.0, 0.15, 0.01, help="Your flat price. Check your bill.")
    use_tou = st.checkbox("I have time-of-use prices", help="Different price at peak and off-peak hours")
    ps, pe = st.slider("Peak hours (from – to)", 0, 24, (17, 21))
    peak_price = st.number_input("Peak price per kWh", 0.0, 10.0, 0.25, 0.01, disabled=not use_tou)
    off_price = st.number_input("Off-peak price per kWh", 0.0, 10.0, 0.10, 0.01, disabled=not use_tou)
    st.header("What-if")
    shift = st.slider("Shift X% of peak use to off-peak", 0, 100, 20)
    cut = st.slider("Cut X% of always-on (standby) load", 0, 100, 30)
    st.info("Savings are estimates based on your own history, not guarantees.")

demo = st.checkbox("Use demo data", help="Synthetic household with a planted high standby load and evening peak")
up = None if demo else st.file_uploader(
    "Electricity usage CSV (Green Button style: timestamp + kWh; hourly, 15-min or daily)", type=["csv", "txt"])

usage = None
if demo:
    demo_df = ww.generate_demo()
    usage = ww.load_usage(demo_df)
    st.download_button("Download demo CSV", demo_df.to_csv(index=False), "demo_usage.csv", "text/csv")
elif up is not None:
    try:
        usage = ww.load_usage(up)
    except ww.UsageError as e:
        st.error(str(e))
    except Exception as e:  # noqa: BLE001
        st.error(f"Sorry, could not process this file: {e}")

if usage is None:
    if not demo and up is None:
        st.info("Upload a CSV or tick **Use demo data** to see how it works.")
    st.stop()

s = ww.Settings(price=price, peak_start=ps, peak_end=pe, use_tou=use_tou, peak_price=peak_price,
                offpeak_price=off_price, shift_pct=shift, standby_cut_pct=cut)
r = ww.analyze(usage, s)
summ = ww.summarize(r, s, currency)

st.subheader("Summary")
st.markdown(summ["headline"])
for t in summ["takeaways"]:
    st.markdown(f"- {t}")

c = st.columns(4)
c[0].metric("Est. monthly cost", f"{currency}{r['monthly_cost']:,.0f}")
c[1].metric("Avg per day", f"{r['avg_daily_kwh']:.1f} kWh")
if r["hourly"]:
    c[2].metric("Standby (night min)", f"{r['baseload_kw'] * 1000:,.0f} W")
    c[3].metric("Peak-hour share", f"{r['peak_share'] * 100:.0f}%")

with st.expander("How we read your file"):
    for n in usage.notes:
        st.write("• " + n)

if r["hourly"]:
    st.subheader("When you use electricity (average kWh per hour)")
    hm = r["heatmap"].reset_index(names="Day").melt(id_vars="Day", var_name="Hour", value_name="kWh")
    st.altair_chart(
        alt.Chart(hm).mark_rect().encode(
            x=alt.X("Hour:O", title="Hour of day"),
            y=alt.Y("Day:O", sort=ww.DOW, title=None),
            color=alt.Color("kWh:Q", scale=alt.Scale(scheme="yelloworangered"), title="Avg kWh"),
            tooltip=["Day", "Hour", alt.Tooltip("kWh:Q", format=".2f")]),
        use_container_width=True)
    st.subheader("Weekday vs weekend pattern")
    st.line_chart(r["profile"])

st.subheader("Monthly trend (kWh per day)")
st.bar_chart(r["monthly"]["kwh_per_day"])
if r["monthly"]["partial"].any():
    st.caption("Months with fewer than 25 days of data are partial; kWh/day keeps them comparable.")

st.subheader("Unusual spikes vs your own baseline")
if r["n_spikes"] and r["hourly"]:
    sp = r["spikes"].copy()
    sp.columns = ["Time", "kWh", "Typical kWh for that hour", "Extra kWh"]
    st.dataframe(sp.round({"kWh": 2, "Typical kWh for that hour": 2, "Extra kWh": 2}), hide_index=True, use_container_width=True)
elif r["n_spikes"]:
    st.write(f"{r['n_spikes']} unusually high days found.")
else:
    st.write("None found.")

st.divider()
st.caption("WattWise gives estimates from the data you provide. Not energy, financial or safety advice; "
           "actual bills depend on your tariff, fees and taxes.")
