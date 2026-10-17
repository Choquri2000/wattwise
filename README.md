# ⚡ WattWise

Privacy-first household electricity insights. Upload a usage CSV (Green Button style: timestamp + kWh; hourly, 15-minute or daily) and get:

- plain-English summary with 3 takeaways
- standby / always-on load (night minimum), peak-hour share, weekday vs weekend, hour-of-day heatmap, monthly trend
- unusual spikes versus your own baseline
- estimated monthly cost (flat price or simple time-of-use) and "what if I shift X% of peak use" savings

**Privacy:** processed in memory, never stored, no AI/API calls. Savings are estimates, not guarantees.

Column and unit detection: Wh/kWh/kW/W columns, ISO timestamps with offsets (local clock time is kept), separate DATE + START TIME columns, preambles above the header.

## Run
```
pip install -r requirements.txt
streamlit run app.py
pytest
```
`demo_usage.csv` is synthetic (planted ~350 W standby load and an evening peak). Tick **Use demo data** in the app.

See `GO_TO_MARKET.md` for positioning and the validation plan.
