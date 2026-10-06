# ☁️ Weather Check — Cloud Coverage & Visibility

Track cloud cover and visibility for 14 locations across Israel, Jordan, Gaza and Egypt.
Interactive map, per-location clear-sky rankings, and best-day recommendations.

**Data source:** [Open-Meteo](https://open-meteo.com/) — free, no API key required.

## Features

- 🗺️ Interactive map with hover tooltips (today's conditions + best days per location)
- 🏅 Clear-sky ranking per location, best → worst
- 🏆 Overall best clear-sky and best-visibility day across all locations
- 🔍 Add locations by city name or manual coordinates
- 📊 Daily summary, hourly detail (07:00–19:00), trend charts
- 📥 CSV / JSON export

## Deploy

Deployed on **Streamlit Community Cloud**.

To deploy your own copy:

1. Fork or clone this repo to your own GitHub account (must be **public**)
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Sign in with GitHub → **New app**
4. Select this repository and branch
5. Set **Main file path** to `weather_app.py`
6. Click **Deploy**

Dependencies live in `requirements.txt`. No secrets or API keys needed.

## Local development

```bash
pip install -r requirements.txt
streamlit run weather_app.py
```

Open http://localhost:8501

## Notes

- Custom locations added via search are stored in `custom_locations.json` locally.
  On Streamlit Community Cloud the filesystem is ephemeral, so they reset on redeploy.
- Forecast window is 07:00–19:00 local time per location, up to 7 days.