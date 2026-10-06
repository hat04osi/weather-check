"""
Weather Check Tool - Cloud Coverage & Visibility
Runs in browser on phone/desktop via Streamlit
Data source: Open-Meteo (free, no API key)
"""
import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import pydeck as pdk
import json
import os

# ==================== CUSTOM LOCATIONS PERSISTENCE ====================
CUSTOM_LOC_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_locations.json")

def load_custom_locations():
    """Load permanently saved custom locations from JSON file"""
    if not os.path.exists(CUSTOM_LOC_FILE):
        return []
    try:
        with open(CUSTOM_LOC_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [(item["name"], float(item["lat"]), float(item["lon"])) for item in data]
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return []

def save_custom_locations(locations):
    """Save custom locations to JSON file. Fails silently on read-only filesystems
    (e.g. Streamlit Community Cloud, where the filesystem is ephemeral)."""
    data = [{"name": name, "lat": lat, "lon": lon} for name, lat, lon in locations]
    try:
        with open(CUSTOM_LOC_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        # Cloud deployments have a read-only/ephemeral FS - persistence unavailable
        pass

# ==================== DEFAULT LOCATIONS ====================
DEFAULT_LOCATIONS = [
    ("Eilat, Israel", 29.613139, 34.948072),
    ("Hevel Eilot, Israel", 29.727525, 34.996231),
    ("Aqaba, Jordan", 29.604708, 35.014061),
    ("Hevel Eilot (N), Israel", 29.916469, 34.940711),
    ("Ramat Negev, Israel", 30.756061, 34.635633),
    ("Rafah, Gaza Strip", 31.304864, 34.277483),
    ("Cairo, Egypt", 30.095581, 31.349867),
    ("Western Desert (N), Egypt", 31.486722, 25.034164),
    ("Western Desert (S), Egypt", 29.687439, 25.029608),
    ("Siwa Oasis, Egypt", 29.144522, 25.540614),
    ("Southern Desert, Egypt", 22.350019, 25.764486),
    ("Red Sea Coast (N), Egypt", 22.247253, 33.900164),
    ("Red Sea Coast (S), Egypt", 22.278050, 35.624375),
    ("Red Sea Central, Egypt", 23.148731, 34.562156),
]

# ==================== GEOCODING ====================
@st.cache_data(ttl=86400)
def geocode_location(query):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "json", "limit": 5, "addressdetails": 1}
    headers = {"User-Agent": "WeatherCheckTool/1.0"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        results = resp.json()
        formatted = []
        for r in results:
            lat = float(r["lat"])
            lon = float(r["lon"])
            addr = r.get("address", {})
            city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet") or addr.get("county") or ""
            country = addr.get("country", "")
            name = f"{city}, {country}".strip(", ")
            if not name:
                name = r.get("display_name", "").split(",")[0]
            formatted.append({"name": name, "lat": lat, "lon": lon, "display": r.get("display_name", "")})
        return formatted
    except Exception as e:
        st.error(f"Geocoding error: {e}")
        return []

# ==================== FETCH FUNCTION ====================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_weather(lat, lon, days=5):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "cloudcover,visibility",
        "timezone": "auto", "forecast_days": days,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if "hourly" not in data:
            return {"error": f"API returned no hourly data: {data}"}
        return data
    except Exception as e:
        return {"error": str(e)}

def process_data(raw_data, location_name):
    if not raw_data or "hourly" not in raw_data or "error" in raw_data:
        return pd.DataFrame()
    
    hourly = raw_data["hourly"]
    times = hourly["time"]
    cloudcover = hourly["cloudcover"]
    visibility = hourly["visibility"]
    
    rows = []
    for t, cc, vis in zip(times, cloudcover, visibility):
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
        if 7 <= dt.hour <= 19:
            rows.append({
                "Location": location_name,
                "Date": dt.strftime("%Y-%m-%d"),
                "Time": dt.strftime("%H:%M"),
                "Hour": dt.hour,
                "Cloud Cover (%)": cc,
                "Visibility (km)": round(vis / 1000, 1),
                "Condition": cloud_condition(cc),
            })
    return pd.DataFrame(rows)

def cloud_condition(pct):
    if pct <= 10: return "☀️ Clear"
    elif pct <= 30: return "🌤️ Mostly Clear"
    elif pct <= 60: return "⛅ Partly Cloudy"
    elif pct <= 80: return "☁️ Mostly Cloudy"
    else: return "☁️ Overcast"

def visibility_condition(vis_km):
    if vis_km >= 20: return "🔭 Excellent"
    elif vis_km >= 10: return "👁️ Very Good"
    elif vis_km >= 5: return "👓 Good"
    elif vis_km >= 2: return "🌫️ Moderate"
    else: return "🌫️ Poor"

# ==================== BEST DAYS ====================
def compute_best_days(df):
    if df.empty: return {}
    daily = df.groupby(["Location", "Date"]).agg(
        avg_cloud=("Cloud Cover (%)", "mean"),
        min_vis=("Visibility (km)", "min"),
        avg_vis=("Visibility (km)", "mean"),
    ).reset_index()
    daily["clear_score"] = 100 - daily["avg_cloud"]
    best = {}
    for loc in df["Location"].unique():
        loc_daily = daily[daily["Location"] == loc]
        if len(loc_daily) == 0: continue
        best_clear = loc_daily.loc[loc_daily["clear_score"].idxmax()]
        best_vis = loc_daily.loc[loc_daily["avg_vis"].idxmax()]
        best[loc] = {
            "best_clear_date": best_clear["Date"],
            "best_clear_cloud": round(best_clear["avg_cloud"], 1),
            "best_clear_vis": round(best_clear["min_vis"], 1),
            "best_vis_date": best_vis["Date"],
            "best_vis_avg": round(best_vis["avg_vis"], 1),
            "best_vis_cloud": round(best_vis["avg_cloud"], 1),
        }
    return best

def get_overall_recommendations(combined_df):
    if combined_df.empty: return None, None
    daily = combined_df.groupby(["Location", "Date"]).agg(
        avg_cloud=("Cloud Cover (%)", "mean"),
        min_vis=("Visibility (km)", "min"),
        avg_vis=("Visibility (km)", "mean"),
    ).reset_index()
    daily["clear_score"] = 100 - daily["avg_cloud"]
    best_clear = daily.loc[daily["clear_score"].idxmax()]
    best_vis = daily.loc[daily["avg_vis"].idxmax()]
    per_loc_clear = daily.loc[daily.groupby("Location")["clear_score"].idxmax()]
    per_loc_vis = daily.loc[daily.groupby("Location")["avg_vis"].idxmax()]
    return {
        "overall_clear": best_clear, "overall_vis": best_vis,
        "per_loc_clear": per_loc_clear, "per_loc_vis": per_loc_vis,
    }, daily

def get_clear_sky_rankings(combined_df):
    """Rank every forecast day per location by clear-sky quality, best to worst"""
    if combined_df.empty:
        return pd.DataFrame()
    daily = combined_df.groupby(["Location", "Date"]).agg(
        avg_cloud=("Cloud Cover (%)", "mean"),
        max_cloud=("Cloud Cover (%)", "max"),
        min_vis=("Visibility (km)", "min"),
        avg_vis=("Visibility (km)", "mean"),
    ).reset_index()
    # clear score: higher = clearer
    daily["clear_score"] = 100 - daily["avg_cloud"]
    # Rank within each location: 1 = best
    daily["Rank"] = (
        daily.groupby("Location")["clear_score"]
        .rank(ascending=False, method="min")
        .astype(int)
    )
    return daily.sort_values(["Location", "Rank"])

# ==================== MAP LAYER ====================
def create_map_layer(locations, selected_names, hover_data, best_days, center_on=None):
    data = []
    for name, lat, lon in locations:
        is_selected = name in selected_names
        is_hover = center_on and name == center_on
        base_radius = 20000 if is_hover else (15000 if is_selected else 8000)
        
        hover_html = f"<b>{name}</b><br/>{lat:.4f}°N, {lon:.4f}°E"
        
        if name in hover_data and not hover_data[name].empty:
            hd = hover_data[name]
            today = datetime.now().strftime("%Y-%m-%d")
            day_data = hd[hd["Date"] == today]
            if len(day_data) > 0:
                avg_c = day_data["Cloud Cover (%)"].mean()
                min_v = day_data["Visibility (km)"].min()
                hover_html += f"<br/>📅 Today: ☁️ {avg_c:.0f}% cloud | 👁️ {min_v:.1f} km min vis"
        
        if name in best_days:
            bd = best_days[name]
            hover_html += f"<br/><br/><b>🏆 Best Days:</b>"
            hover_html += f"<br/>☀️ Clearest: {bd['best_clear_date']} ({bd['best_clear_cloud']}% cloud, {bd['best_clear_vis']} km vis)"
            hover_html += f"<br/>🔭 Best Vis: {bd['best_vis_date']} ({bd['best_vis_avg']} km avg, {bd['best_vis_cloud']}% cloud)"
        
        data.append({
            "name": name, "lat": lat, "lon": lon,
            "selected": is_selected, "hover": is_hover,
            "base_radius": base_radius,
            "color": [255, 50, 50, 220] if is_hover else ([255, 150, 50, 200] if is_selected else [50, 150, 255, 180]),
            "hover_html": hover_html,
        })
    
    layer = pdk.Layer(
        "ScatterplotLayer", data=data,
        get_position="[lon, lat]", get_radius="base_radius",
        get_fill_color="color", pickable=True, auto_highlight=True,
        radius_min_pixels=4, radius_max_pixels=40,
    )
    
    if center_on:
        center_lat, center_lon = next((lat, lon) for n, lat, lon in locations if n == center_on)
        zoom = 8
    elif selected_names:
        sel_coords = [(lat, lon) for n, lat, lon in locations if n in selected_names]
        center_lat = sum(c[0] for c in sel_coords) / len(sel_coords)
        center_lon = sum(c[1] for c in sel_coords) / len(sel_coords)
        zoom = 5
    else:
        center_lat = sum(lat for _, lat, _ in locations) / len(locations)
        center_lon = sum(lon for _, _, lon in locations) / len(locations)
        zoom = 4
    
    view_state = pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=0)
    tooltip = {"html": "{hover_html}", "style": {"color": "white", "fontSize": "12px", "fontFamily": "monospace"}}
    return pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip=tooltip, map_style="road")

# ==================== SESSION STATE ====================
if "map_center" not in st.session_state:
    st.session_state.map_center = None
if "custom_locations" not in st.session_state:
    st.session_state.custom_locations = load_custom_locations()
if "selected_locs" not in st.session_state:
    # Select all default locations plus any permanently saved custom ones
    st.session_state.selected_locs = (
        [name for name, _, _ in DEFAULT_LOCATIONS]
        + [name for name, _, _ in st.session_state.custom_locations]
    )

# ==================== STREAMLIT UI ====================
st.set_page_config(page_title="Weather Check - Cloud & Visibility", layout="wide")
st.title("☁️ Cloud Coverage & Visibility Checker")
st.caption("Data: Open-Meteo | 7 AM – 7 PM local time | 5-day forecast | Click 🎯 to center map | Hover points for best days")

# ==================== SIDEBAR ====================
with st.sidebar:
    st.header("⚙️ Settings")
    days = st.slider("Forecast Days", 1, 7, 5)
    
    # ---- ADD NEW LOCATION ----
    st.divider()
    st.subheader("➕ Add Location")
    
    tab1, tab2 = st.tabs(["🔍 Search by Name", "📍 Manual Coordinates"])
    
    with tab1:
        search_query = st.text_input("City, Country or Place", placeholder="e.g., Dubai, UAE", key="search_input")
        if search_query:
            with st.spinner("Searching..."):
                results = geocode_location(search_query)
            if results:
                st.write("**Results:**")
                for r in results:
                    col1, col2 = st.columns([0.7, 0.3])
                    with col1:
                        st.write(f"**{r['name']}**  \n{r['display'][:80]}...")
                    with col2:
                        if st.button("➕ Add", key=f"add_{r['lat']}_{r['lon']}"):
                            all_locs = DEFAULT_LOCATIONS + st.session_state.custom_locations
                            exists = any(abs(lat - r['lat']) < 0.001 and abs(lon - r['lon']) < 0.001 for _, lat, lon in all_locs)
                            if not exists:
                                st.session_state.custom_locations.append((r['name'], r['lat'], r['lon']))
                                save_custom_locations(st.session_state.custom_locations)
                                if r['name'] not in st.session_state.selected_locs:
                                    st.session_state.selected_locs.append(r['name'])
                                st.success(f"Added {r['name']}! Fetching weather...")
                                st.rerun()
                            else:
                                st.warning("Already exists!")
            else:
                st.info("No results found")
    
    with tab2:
        col1, col2 = st.columns(2)
        with col1:
            manual_lat = st.number_input("Latitude", value=0.0, format="%.6f", key="manual_lat")
        with col2:
            manual_lon = st.number_input("Longitude", value=0.0, format="%.6f", key="manual_lon")
        manual_name = st.text_input("Location Name", placeholder="My Location", key="manual_name")
        if st.button("➕ Add Coordinates"):
            if manual_name and manual_lat != 0 and manual_lon != 0:
                all_locs = DEFAULT_LOCATIONS + st.session_state.custom_locations
                exists = any(abs(lat - manual_lat) < 0.001 and abs(lon - manual_lon) < 0.001 for _, lat, lon in all_locs)
                if not exists:
                    st.session_state.custom_locations.append((manual_name, manual_lat, manual_lon))
                    save_custom_locations(st.session_state.custom_locations)
                    if manual_name not in st.session_state.selected_locs:
                        st.session_state.selected_locs.append(manual_name)
                    st.success(f"Added {manual_name}! Fetching weather...")
                    st.rerun()
                else:
                    st.warning("Already exists!")
    
    # ---- CUSTOM LOCATIONS MANAGEMENT ----
    if st.session_state.custom_locations:
        with st.expander(f"🗑️ Custom Locations ({len(st.session_state.custom_locations)})", expanded=False):
            st.caption("⚠️ Cloud version: saved locations reset when the app restarts.")
            for i, (name, lat, lon) in enumerate(st.session_state.custom_locations):
                col1, col2 = st.columns([0.8, 0.2])
                with col1:
                    st.write(f"**{name}**  \n{lat:.4f}, {lon:.4f}")
                with col2:
                    if st.button("🗑️", key=f"del_{i}"):
                        st.session_state.custom_locations.pop(i)
                        save_custom_locations(st.session_state.custom_locations)
                        if name in st.session_state.selected_locs:
                            st.session_state.selected_locs.remove(name)
                        st.rerun()
    
    # ---- LOCATION LIST ----
    st.divider()
    st.subheader("📍 Locations")
    
    all_locations = DEFAULT_LOCATIONS + st.session_state.custom_locations
    location_options = [name for name, _, _ in all_locations]
    
    for name in location_options:
        col1, col2 = st.columns([0.85, 0.15])
        with col1:
            is_selected = name in st.session_state.selected_locs
            checked = st.checkbox(name, value=is_selected, key=f"loc_{name}")
        with col2:
            if st.button("🎯", key=f"center_{name}", help=f"Center map on {name}"):
                st.session_state.map_center = name
                st.rerun()
        
        if checked and name not in st.session_state.selected_locs:
            st.session_state.selected_locs.append(name)
        elif not checked and name in st.session_state.selected_locs:
            st.session_state.selected_locs.remove(name)
    
    selected_locs = st.session_state.selected_locs

if not selected_locs:
    st.warning("Select at least one location")
    st.stop()

# ==================== FETCH DATA ====================
filtered_locations = [(n, lat, lon) for n, lat, lon in all_locations if n in selected_locs]

# Debug info
with st.expander("🔧 Debug Info", expanded=False):
    st.write(f"**Selected:** {len(selected_locs)} locations")
    st.write(f"**Filtered for fetch:** {len(filtered_locations)} locations")
    for n, lat, lon in filtered_locations:
        st.write(f"  • {n}: {lat:.4f}, {lon:.4f}")

all_dfs = {}
fetch_errors = {}
progress = st.progress(0)
for idx, (name, lat, lon) in enumerate(filtered_locations):
    raw = fetch_weather(lat, lon, days)
    if "error" in raw:
        fetch_errors[name] = raw["error"]
        df = pd.DataFrame()
    else:
        df = process_data(raw, name)
    all_dfs[name] = df
    progress.progress((idx + 1) / len(filtered_locations))
progress.empty()

if fetch_errors:
    st.error("⚠️ Some locations failed to fetch:")
    for loc, err in fetch_errors.items():
        st.write(f"  **{loc}**: {err}")

combined = pd.concat(all_dfs.values(), ignore_index=True) if all_dfs else pd.DataFrame()

if combined.empty:
    st.error("No weather data retrieved for any location")
    st.stop()

# ==================== COMPUTE BEST DAYS ====================
best_days = compute_best_days(combined)
recs, daily_df = get_overall_recommendations(combined)

# ==================== RECOMMENDATIONS ====================
if recs:
    st.subheader("🏆 Recommendations")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### ☀️ Best Clear Sky Day (Overall)")
        oc = recs["overall_clear"]
        st.success(f"""
        **{oc['Date']}** — Best day for clear skies across all locations
        
        **Avg Cloud Cover:** {oc['avg_cloud']:.1f}% ({cloud_condition(oc['avg_cloud'])})
        
        **Min Visibility:** {oc['min_vis']:.1f} km ({visibility_condition(oc['min_vis'])})
        """)
        with st.expander("Per-location best clear days"):
            for _, row in recs["per_loc_clear"].iterrows():
                st.write(f"**{row['Location']}**: {row['Date']} — {row['avg_cloud']:.1f}% cloud ({cloud_condition(row['avg_cloud'])})")
    
    with col2:
        st.markdown("### 🔭 Best Visibility Day (Overall)")
        ov = recs["overall_vis"]
        st.info(f"""
        **{ov['Date']}** — Best day for visibility across all locations
        
        **Avg Visibility:** {ov['avg_vis']:.1f} km ({visibility_condition(ov['avg_vis'])})
        
        **Avg Cloud Cover:** {ov['avg_cloud']:.1f}% ({cloud_condition(ov['avg_cloud'])})
        """)
        with st.expander("Per-location best visibility days"):
            for _, row in recs["per_loc_vis"].iterrows():
                st.write(f"**{row['Location']}**: {row['Date']} — {row['avg_vis']:.1f} km avg ({visibility_condition(row['avg_vis'])})")

# ==================== CLEAR SKY RANKING PER LOCATION ====================
rankings_df = get_clear_sky_rankings(combined)

if not rankings_df.empty:
    st.subheader("🏅 Clear Sky Ranking by Location (Best → Worst)")
    st.caption("All forecast days ranked per location. Rank 1 = clearest skies.")

    for loc in selected_locs:
        loc_rank = rankings_df[rankings_df["Location"] == loc]
        if loc_rank.empty:
            continue

        best_row = loc_rank.iloc[0]
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(best_row["Rank"], "⭐")
        st.markdown(
            f"#### {medal} {loc} — best: **{best_row['Date']}** "
            f"({best_row['avg_cloud']:.1f}% cloud · {best_row['min_vis']:.1f} km vis)"
        )

        display = loc_rank[["Rank", "Date", "avg_cloud", "max_cloud", "min_vis", "avg_vis", "clear_score"]].copy()
        display.columns = ["Rank", "Date", "Avg Cloud %", "Peak Cloud %", "Min Vis (km)", "Avg Vis (km)", "Clear Score"]
        display["Sky"] = display["Avg Cloud %"].apply(cloud_condition)

        st.dataframe(
            display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn("Rank", format="%d", width="small"),
                "Date": st.column_config.TextColumn("Date", width="small"),
                "Avg Cloud %": st.column_config.NumberColumn("Avg Cloud %", format="%.1f%%"),
                "Peak Cloud %": st.column_config.NumberColumn("Peak Cloud %", format="%.0f%%"),
                "Min Vis (km)": st.column_config.NumberColumn("Min Vis (km)", format="%.1f"),
                "Avg Vis (km)": st.column_config.NumberColumn("Avg Vis (km)", format="%.1f"),
                "Clear Score": st.column_config.ProgressColumn(
                    "Clear Score", min_value=0, max_value=100, format="%.0f"
                ),
                "Sky": st.column_config.TextColumn("Sky"),
            },
        )

    # Combined view: every location's single best day, ranked against each other
    with st.expander("📊 All locations — best day each, ranked side by side"):
        best_per_loc = (
            rankings_df.loc[rankings_df.groupby("Location")["Rank"].idxmin()]
            .sort_values("clear_score", ascending=False)
            .reset_index(drop=True)
        )
        best_per_loc.index = range(1, len(best_per_loc) + 1)
        side = best_per_loc[["Date", "Location", "avg_cloud", "min_vis", "avg_vis", "clear_score"]].copy()
        side.columns = ["Date", "Location", "Avg Cloud %", "Min Vis (km)", "Avg Vis (km)", "Clear Score"]
        side.insert(0, "#", range(1, len(side) + 1))
        st.dataframe(
            side,
            use_container_width=True,
            hide_index=True,
            column_config={
                "#": st.column_config.NumberColumn("#", format="%d", width="small"),
                "Clear Score": st.column_config.ProgressColumn(
                    "Clear Score", min_value=0, max_value=100, format="%.0f"
                ),
            },
        )

# ==================== MAP VIEW ====================
st.subheader("🗺️ Interactive Map (hover for best days, 🎯 to center, circles scale with zoom)")
map_deck = create_map_layer(all_locations, selected_locs, all_dfs, best_days, st.session_state.map_center)
st.pydeck_chart(map_deck, use_container_width=True)

if st.session_state.map_center:
    st.session_state.map_center = None

# ==================== DAILY SUMMARY ====================
st.subheader("📅 Daily Summary (7 AM – 7 PM)")
summary_rows = []
for loc in selected_locs:
    loc_df = combined[combined["Location"] == loc]
    for date in sorted(loc_df["Date"].unique()):
        day_df = loc_df[loc_df["Date"] == date]
        avg_cloud = day_df["Cloud Cover (%)"].mean()
        min_vis = day_df["Visibility (km)"].min()
        avg_vis = day_df["Visibility (km)"].mean()
        summary_rows.append({
            "Location": loc, "Date": date,
            "Avg Cloud %": round(avg_cloud, 1),
            "Min Visibility (km)": round(min_vis, 1),
            "Avg Visibility (km)": round(avg_vis, 1),
            "Sky": cloud_condition(avg_cloud),
            "Vis Quality": visibility_condition(avg_vis),
        })
summary_df = pd.DataFrame(summary_rows)
st.dataframe(summary_df, use_container_width=True, hide_index=True, column_config={
    "Location": st.column_config.TextColumn("Location", width="medium"),
    "Date": st.column_config.TextColumn("Date", width="small"),
    "Avg Cloud %": st.column_config.NumberColumn("Avg Cloud %", format="%.1f%%"),
    "Min Visibility (km)": st.column_config.NumberColumn("Min Vis (km)", format="%.1f"),
    "Avg Visibility (km)": st.column_config.NumberColumn("Avg Vis (km)", format="%.1f"),
    "Sky": st.column_config.TextColumn("Sky"),
    "Vis Quality": st.column_config.TextColumn("Vis Quality"),
})

# ==================== DETAILED TABLE ====================
st.subheader("📊 Hourly Details (7 AM – 7 PM)")
for loc in selected_locs:
    loc_df = combined[combined["Location"] == loc].copy()
    if len(loc_df) == 0:
        st.warning(f"No data for {loc}")
        continue
    with st.expander(f"📍 {loc} ({len(loc_df)} hours)"):
        display_df = loc_df[["Date", "Time", "Cloud Cover (%)", "Visibility (km)", "Condition"]]
        st.dataframe(display_df, use_container_width=True, hide_index=True, column_config={
            "Cloud Cover (%)": st.column_config.NumberColumn("Cloud %", format="%d%%"),
            "Visibility (km)": st.column_config.NumberColumn("Vis (km)", format="%.1f"),
        })

# ==================== CHARTS ====================
col1, col2 = st.columns(2)
with col1:
    st.subheader("📈 Cloud Cover Trend")
    chart_df = combined.pivot_table(
        index=["Date", "Time"], columns="Location", values="Cloud Cover (%)", aggfunc="first"
    ).reset_index()
    chart_df["DateTime"] = pd.to_datetime(chart_df["Date"] + " " + chart_df["Time"])
    st.line_chart(chart_df.set_index("DateTime").drop(columns=["Date", "Time"]), height=300)

with col2:
    st.subheader("📈 Visibility Trend")
    vis_chart = combined.pivot_table(
        index=["Date", "Time"], columns="Location", values="Visibility (km)", aggfunc="first"
    ).reset_index()
    vis_chart["DateTime"] = pd.to_datetime(vis_chart["Date"] + " " + vis_chart["Time"])
    st.line_chart(vis_chart.set_index("DateTime").drop(columns=["Date", "Time"]), height=300)

# ==================== EXPORT ====================
with st.expander("📥 Export Data"):
    csv = combined.to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", csv, "weather_data.csv", "text/csv", use_container_width=True)
    st.download_button("Download JSON", combined.to_json(orient="records", indent=2).encode("utf-8"), "weather_data.json", "application/json", use_container_width=True)

st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(selected_locs)} locations × {days} days")