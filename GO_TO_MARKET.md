# WattWise - go to market

**Live app:** https://wattwise-home-energy.streamlit.app  
**Code:** https://github.com/Choquri2000/wattwise

## Landing copy
**Headline:** See where your electricity actually goes - in 60 seconds, without handing over your data.  
**Sub:** Drop in the usage file from your utility. WattWise shows your always-on standby load, your peak-hour habits, odd spikes, and what shifting some use to cheaper hours might save. Processed in your browser session, never stored, no AI.  
**Bullets:** standby load estimate - peak vs off-peak - weekday/weekend - hour heatmap - monthly trend - spike finder - simple what-if savings.  
**CTA:** Try it with demo data, no sign-up.

## Who it helps
Households with a smart meter who can download interval data (Green Button in the US/Canada, similar exports elsewhere), especially people on time-of-use tariffs, EV owners, remote workers at home all day, and renters curious about a high bill.

## Honest limits
Estimates from your own history only. Night minimum is a proxy for standby (a fridge, router, heat pump defrost, or a night-shift routine will be counted). Savings assume your tariff has the prices you enter and that loads can actually move. Not tested on real smart-meter exports from many utilities yet. Not energy, financial or safety advice. No guarantees.

## Validation plan (cheap, honest)
1. Get 10 real exports from friends/forums (with consent) from different utilities; log parse failures and fix column detection.
2. Ask 10 users: "did it tell you something you did not know?" and "would you check again next month?" Target: 4+ yes to the first.
3. Compare the standby estimate with a plug-in meter reading for a handful of households.
4. Track simple, privacy-friendly signals only (shares, feedback form), not uploads.

## Free monetisation ideas (no promises)
- Optional tip jar / "buy me a coffee" link.
- Affiliate links to plug-in energy monitors or smart plugs, clearly disclosed and only shown when standby is high.
- Free tool as lead-in for a paid CSV-to-report PDF or a utility-bill checker later.
- Open-source the engine; offer sponsored integrations for specific utility export formats.

## Distribution (manual, user-driven)
Posts in energy-saving / smart-home / EV communities where self-promo is allowed; a short write-up "What my smart meter data showed about standby power"; SEO pages per utility export format.
