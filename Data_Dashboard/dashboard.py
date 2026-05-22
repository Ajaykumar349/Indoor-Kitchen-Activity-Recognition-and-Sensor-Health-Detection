"""
Streamlit Dashboard — Sensor Fault Detection Pipeline
Data source: Flask REST API / WebSocket In-Memory Relay Backend
Pipeline:    Introcept → LOO Blame → Fusion → Active Confirmation → Output
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from collections import deque
import logging
import requests  # Replaced MongoDB handlers with HTTP requests

from fault_pipeline import CompleteFaultDetectionPipeline, SENSOR_PARAMS, WINDOW_SECS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Dashboard")

# ─────────────────────────────────────────────
# FLASK BACKEND CONFIG
# ─────────────────────────────────────────────
BASE_URL = "http://127.0.0.1:5000"  # Change this to your Flask Server IP if hosted externally
API_LATEST = f"{BASE_URL}/api/latest"
API_HISTORY = f"{BASE_URL}/api/history"
API_STATUS = f"{BASE_URL}/api/status"

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Sensor Fault Detection",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

SENSORS = ["VOC", "CO2", "PM2.5"]

# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────
defaults = {
    "pipeline":      None,
    "initialized":   False,
    "data_buffer":   [],
    "fault_history": deque(maxlen=1000),
    "flask_ok":      False,             # Replaced mongo_ok
    "aqi_history":   {s: {"measured": [], "predicted": []} for s in ["VOC", "CO2", "PM2.5"]},
    "loo_vote_history": [],      # list of per-frame LOO vote dicts
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


def init_pipeline():
    try:
        st.session_state.pipeline    = CompleteFaultDetectionPipeline(sampling_rate=1.0)
        st.session_state.initialized = True
        return True
    except Exception as e:
        st.error(f"Init error: {e}")
        return False

# ─────────────────────────────────────────────
# FLASK API HELPER FUNCTIONS
# ─────────────────────────────────────────────
def test_flask_connection():
    try:
        response = requests.get(API_STATUS, timeout=2)
        return response.status_code == 200
    except requests.RequestException:
        return False

def fetch_latest_from_flask():
    try:
        response = requests.get(API_LATEST, timeout=2)
        if response.status_code == 200:
            return response.json()
    except requests.RequestException as e:
        logger.error(f"Error fetching latest data from Flask: {e}")
    return None

def fetch_history_from_flask(limit=100):
    try:
        response = requests.get(f"{API_HISTORY}?limit={limit}", timeout=2)
        if response.status_code == 200:
            return pd.DataFrame(response.json())
    except requests.RequestException as e:
        logger.error(f"Error fetching historical data from Flask: {e}")
    return pd.DataFrame()

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Pipeline")
    if st.button("Initialize pipeline", key="init_btn"):
        with st.spinner("Initializing…"):
            if init_pipeline():
                st.success("✓ Ready")
            else:
                st.error("✗ Failed")

    st.divider()
    st.markdown("### 🌐 Flask Backend")
    if st.button("Test server connection"):
        st.session_state.flask_ok = test_flask_connection()
    
    if st.session_state.flask_ok:
        st.success("✅ Connected to Flask API")
        try:
            status_res = requests.get(API_STATUS).json()
            st.info(f"ESP32 Connected: **{status_res.get('esp32_connected')}**")
            st.info(f"RAM Data Points: **{status_res.get('data_points')}**")
        except Exception:
            pass
    else:
        st.warning("Server not tested or unreachable")

    # Note: Device selectors removed since Flask in-memory pipeline tracks the active WebSocket client directly
    st.divider()
    auto_refresh = st.checkbox("Auto-refresh (2 s)", value=True)

    st.divider()
    st.markdown("### 🔧 Thresholds (current)")
    for s in SENSORS:
        p = SENSOR_PARAMS[s]
        st.markdown(f"**{s}**")
        st.caption(
            f"β={p['beta']}  τ={p['tau']}  "
            f"θ_susp={p['theta_suspicious']}  θ_faulty={p['theta_faulty']}  "
            f"T_I={p['T_I']}s  ρ={p['rho']}  T_fuse={p['T_fuse']}s  z={p['z_thresh']}"
        )
    st.caption(f"LOO window: {WINDOW_SECS} s")

# ─────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────
st.markdown("# 🔍 Sensor fault detection pipeline")
st.markdown(
    "**Data source**: Flask REST API Server `/api/*` | "
    "**Pipeline**: Phase 1 Introcept → Phase 2 LOO Blame (3-min window) → "
    "Phase 3 Fusion → Phase 4 Active Confirmation → Phase 6 Output"
)

if not st.session_state.initialized:
    st.warning("⚠️ Click **Initialize pipeline** in the sidebar to start.")
    st.stop()

# ─────────────────────────────────────────────
# FETCH LATEST FRAME FROM FLASK
# ─────────────────────────────────────────────
frame = fetch_latest_from_flask()
if not frame or frame.get('source') == 'default':
    st.error("❌ No active data frame returned from Flask Server. Ensure your ESP32 is feeding the live WebSocket stream.")
    st.stop()

st.session_state.data_buffer.append(frame)
if len(st.session_state.data_buffer) > 300:
    st.session_state.data_buffer.pop(0)

# ─────────────────────────────────────────────
# RUN PIPELINE
# ─────────────────────────────────────────────
decision = st.session_state.pipeline.process_frame(frame)
st.session_state.fault_history.append(decision)

# ── Accumulate AQI history for introcept chart ────────────────────
for _s in SENSORS:
    _intr = decision["introcept"][_s]
    _hist = st.session_state.aqi_history[_s]
    _hist["measured"].append(_intr["measured_aqi_class"])
    _hist["predicted"].append(_intr["predicted_aqi_class"])
    if len(_hist["measured"]) > 120:      # keep last 120 frames
        _hist["measured"].pop(0)
        _hist["predicted"].pop(0)

# ── Accumulate LOO vote history ───────────────────────────────────
_loo = decision["loo"]
_vote_row = {"frame": len(st.session_state.loo_vote_history) + 1}
for _s in SENSORS:
    _pred = _loo["predictions"].get(_s, {})
    _vote_row[f"{_s}_activity"] = _pred.get("activity", "—")
    _vote_row[f"{_s}_conf"]     = round(_pred.get("conf", 0.0), 3)
    _vote_row[f"{_s}_blame"]    = _loo["blame_votes"].get(_s, 0)
_vote_row["consensus"]  = _loo.get("cons_activity") or "—"
_vote_row["cfull"]      = _loo.get("cfull_activity", "—")
st.session_state.loo_vote_history.append(_vote_row)
if len(st.session_state.loo_vote_history) > 120:
    st.session_state.loo_vote_history.pop(0)

# ─────────────────────────────────────────────
# SECTION 1 – Live Readings
# ─────────────────────────────────────────────
st.markdown("## 📈 Live readings")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("🌡 Temperature", f"{frame['T']:.2f} °C")
c2.metric("💧 Humidity",    f"{frame['H']:.2f} %")
c3.metric("🌐 Pressure",    f"{frame['P']:.2f} hPa")
c4.metric("🟣 VOC",          f"{frame['VOC']:.2f} ppm")
c5.metric("🟤 CO₂",          f"{frame['CO2']:.1f} ppm")
c6.metric("🟠 PM₂.₅",       f"{frame['PM2.5']:.2f} µg/m³")

# LOO window warm-up indicator
window_size = decision["loo"].get("window_size", 0)
warmup_pct  = min(window_size / WINDOW_SECS, 1.0)
if window_size < WINDOW_SECS:
    st.info(
        f"⏳ LOO 3-min window warming up: {window_size}/{WINDOW_SECS} samples "
        f"({warmup_pct*100:.0f}%) — blame scores inactive until full."
    )
    st.progress(warmup_pct)

st.divider()

# ─────────────────────────────────────────────
# SECTION 2 – Phase 1–3 per-sensor status
# ─────────────────────────────────────────────
st.markdown("## 🚨 Phase 1–3 status per sensor")

col1, col2, col3 = st.columns(3)
for col, s in zip([col1, col2, col3], SENSORS):
    intr   = decision["introcept"][s]
    status = intr["status"]
    susp   = decision["suspects"].get(s, 0)
    conf   = s in decision["confirmed_faulty"]

    if conf or status == "FAULTY":
        icon = "🔴"
    elif status == "SUSPICIOUS":
        icon = "🟡"
    else:
        icon = "🟢"

    with col:
        with st.container(border=True):
            st.markdown(f"### {icon} {s}")

            # ── Phase 1 ──────────────────────────────────────────────
            st.markdown("**Phase 1 – Introcept**")
            st.write(
                f"Measured AQI class: `{intr['measured_aqi_class']}`  |  "
                f"Predicted AQI class: `{intr['predicted_aqi_class']}`"
            )
            st.write(
                f"d_s (residual): `{intr['residual']}`   "
                f"τ = `{SENSOR_PARAMS[s]['tau']}`"
            )
            st.write(f"F_s (fault score): `{intr['fault_score']:.2f}`")
            st.write(f"Status: **{status}**")
            st.write(
                f"C_I counter: `{intr['C_I']}`   "
                f"I_s: `{intr['I_s']}`"
            )
            st.progress(
                min(intr["fault_score"] / SENSOR_PARAMS[s]["theta_faulty"], 1.0)
            )

            # ── Phase 2 ──────────────────────────────────────────────
            st.markdown("**Phase 2 – LOO blame**")
            loo_pred = decision["loo"]["predictions"].get(s, {})
            if loo_pred:
                st.write(
                    f"c_{{-{s}}} activity: `{loo_pred.get('activity', '—')}`  "
                    f"conf: `{loo_pred.get('conf', 0):.2f}`"
                )
            else:
                st.write("*(no LOO model for this sensor)*")
            st.write(
                f"Blame vote V_s: `{decision['loo']['blame_votes'].get(s, 0)}`"
            )
            st.write(
                f"D_s (fraction): `{decision['loo']['D_s'].get(s, 0):.3f}`   "
                f"L_s: `{decision['L_s'].get(s, 0)}`"
            )
            cons = decision["loo"].get("cons_activity") or "—"
            st.write(f"Consensus activity: `{cons}`")

            # ── Phase 3 ──────────────────────────────────────────────
            st.markdown("**Phase 3 – Fusion**")
            st.write(
                f"C_fuse: `{decision['fusion']['C_fuse'].get(s, 0)}`"
            )
            st.write(f"Suspect_s: {'🚩 **YES**' if susp else '✓ No'}")
            if conf:
                st.error("⛔ FAULT CONFIRMED (z-test)")

# ─────────────────────────────────────────────
# SECTION 2b – AQI Class Charts (Introcept)
# ─────────────────────────────────────────────
st.markdown("### 📉 Measured vs Predicted AQI class (Phase 1 – Introcept)")
aqi_colors_meas = {"VOC": "#7b2d8b", "CO2": "#c0392b", "PM2.5": "#e67e22"}
aqi_colors_pred = {"VOC": "#c39bd3", "CO2": "#f1948a", "PM2.5": "#f0b27a"}

aqi_cols = st.columns(3)
for _col, _s in zip(aqi_cols, SENSORS):
    with _col:
        _hist = st.session_state.aqi_history[_s]
        _fig = go.Figure()
        _fig.add_trace(go.Scatter(
            y=_hist["measured"],
            name="Measured",
            mode="lines+markers",
            marker=dict(size=5),
            line=dict(color=aqi_colors_meas[_s], width=2),
        ))
        _fig.add_trace(go.Scatter(
            y=_hist["predicted"],
            name="Predicted",
            mode="lines+markers",
            marker=dict(size=5, symbol="diamond"),
            line=dict(color=aqi_colors_pred[_s], width=2, dash="dash"),
        ))
        _fig.update_layout(
            title=dict(text=f"{_s} AQI class", font=dict(size=13)),
            height=240,
            margin=dict(t=36, b=32, l=32, r=16),
            yaxis=dict(
                tickvals=[1,2,3,4,5,6],
                ticktext=["1-Good","2-Sat","3-Mod","4-Poor","5-VPoor","6-Sev"],
                range=[0.5, 6.5],
                gridcolor="#eeeeee",
            ),
            xaxis_title="Sample #",
            legend=dict(orientation="h", y=-0.25, font=dict(size=10)),
            plot_bgcolor="white",
            paper_bgcolor="white",
        )
        _fig.add_hrect(y0=0.5, y1=2.5, fillcolor="green",  opacity=0.05, line_width=0)
        _fig.add_hrect(y0=2.5, y1=3.5, fillcolor="yellow", opacity=0.07, line_width=0)
        _fig.add_hrect(y0=3.5, y1=4.5, fillcolor="orange", opacity=0.07, line_width=0)
        _fig.add_hrect(y0=4.5, y1=6.5, fillcolor="red",    opacity=0.06, line_width=0)
        st.plotly_chart(_fig, use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SECTION 3 – Phase 4 Active Confirmation
# ─────────────────────────────────────────────
if decision.get("active_test_prompt"):
    prompt = decision["active_test_prompt"]
    st.warning(
        f"🚨 **Phase 4 – Active confirmation test triggered**\n\n"
        f"Sensor: **{prompt['sensor']}** | "
        f"Activity: **{prompt['activity']}** | "
        f"Duration: **{prompt['duration_seconds']} s**\n\n"
        f"{prompt['message']}"
    )

if decision["active_test_phase"] in ("stabilising", "collecting"):
    st.markdown("## 🔬 Phase 4 – Active confirmation in progress")
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Sensor",        decision["active_test_sensor"])
    t2.metric("Phase",         decision["active_test_phase"])
    t3.metric("Elapsed (s)",   f"{decision['active_test_elapsed']:.0f} / 150")
    t4.metric("Samples n",     decision["active_test_n"])
    st.progress(min(decision["active_test_elapsed"] / 150, 1.0))

if decision.get("active_test_result"):
    r = decision["active_test_result"]
    if r["status"] == "CONFIRMED":
        st.error(
            f"❌ **FAULT CONFIRMED** — {decision['active_test_sensor']} | "
            f"z = {r['z_score']:.2f}  x̄ = {r['x_bar']:.2f}  "
            f"μ* = {r['mu']}  σ* = {r['sigma']}  n = {r['n']}"
        )
    elif r["status"] == "CLEARED":
        st.success(
            f"✅ **CLEARED** — {decision['active_test_sensor']} | "
            f"z = {r['z_score']:.2f}  |z| < {r['thresh']} → no fault"
        )

st.divider()

# ─────────────────────────────────────────────
# SECTION 4 – Phase 6 Output
# ─────────────────────────────────────────────
st.markdown("## 🏷️ Phase 6 – Final activity prediction")
out = decision["output"]
oc1, oc2, oc3 = st.columns(3)
oc1.metric("Activity",    out["activity"])
oc2.metric("Confidence",  f"{out['confidence']:.2f}")
oc3.metric("Output mode", out["output_mode"])
if out["low_conf_warn"]:
    st.warning("⚡ Low-confidence warning: sensor suspected but not yet confirmed.")
if decision["confirmed_faulty"]:
    st.info(f"Confirmed faulty sensors: {', '.join(decision['confirmed_faulty'])}")

# ─────────────────────────────────────────────
# SECTION 4b – LOO Voting Table
# ─────────────────────────────────────────────
st.markdown("### 🗳️ LOO Model Voting History (Phase 2 – last 30 frames)")

if st.session_state.loo_vote_history:
    _vote_df = pd.DataFrame(st.session_state.loo_vote_history[-30:])

    _display_cols = {
        "frame":          "Frame",
        "VOC_activity":   "c₋VOC  Activity",
        "VOC_conf":       "c₋VOC  Conf",
        "VOC_blame":      "Blame VOC",
        "CO2_activity":   "c₋CO₂  Activity",
        "CO2_conf":       "c₋CO₂  Conf",
        "CO2_blame":      "Blame CO₂",
        "PM2.5_activity": "c₋PM₂.₅ Activity",
        "PM2.5_conf":     "c₋PM₂.₅ Conf",
        "PM2.5_blame":    "Blame PM₂.₅",
        "consensus":      "LOO Consensus",
        "cfull":          "c_full",
    }
    _vote_df = _vote_df.rename(columns=_display_cols)

    def _colour_blame(val):
        if val == 1:
            return "background-color: #fce4d6; color: #c00000; font-weight: bold"
        return ""

    def _colour_conf(val):
        try:
            v = float(val)
            if v >= 0.8:   return "color: #1e7145; font-weight: bold"
            if v >= 0.6:   return "color: #e67e22"
            return "color: #c00000"
        except Exception:
            return ""

    styled = (
        _vote_df.style
        .map(_colour_blame, subset=["Blame VOC","Blame CO₂","Blame PM₂.₅"])
        .map(_colour_conf,  subset=["c₋VOC  Conf","c₋CO₂  Conf","c₋PM₂.₅ Conf"])
        .set_properties(**{"font-size": "12px"})
    )
    st.dataframe(styled, use_container_width=True, height=320)
    st.caption(
        "🟥 Red blame cell = V_s = 1 (that sensor blamed this frame).  "
        "Conf colour: 🟢 ≥ 0.8  🟠 0.6–0.8  🔴 < 0.6"
    )
else:
    st.info("Voting history will appear after the first frame is processed.")

st.divider()

# ─────────────────────────────────────────────
# SECTION 5 – Real-time charts
# ─────────────────────────────────────────────
st.markdown("## 📊 Real-time charts")
df = pd.DataFrame(st.session_state.data_buffer)

if not df.empty:
    colors = {"VOC": "#7b2d8b", "CO2": "#c0392b", "PM2.5": "#e67e22"}
    ch1, ch2 = st.columns(2)

    with ch1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            y=df["VOC"],   name="VOC (ppm)",
            mode="lines",  line=dict(color=colors["VOC"],   width=2)))
        fig.add_trace(go.Scatter(
            y=df["CO2"],   name="CO₂ (ppm)",
            mode="lines",  line=dict(color=colors["CO2"],   width=2)))
        fig.add_trace(go.Scatter(
            y=df["PM2.5"], name="PM₂.₅ (µg/m³)",
            mode="lines",  line=dict(color=colors["PM2.5"], width=2)))
        fig.update_layout(title="Sensor readings", height=320, xaxis_title="Sample #")
        st.plotly_chart(fig, use_container_width=True)

    with ch2:
        fault_hist = {s: [] for s in SENSORS}
        for fd in list(st.session_state.fault_history)[-120:]:
            for s in SENSORS:
                fault_hist[s].append(fd["introcept"][s]["fault_score"])

        fig2 = go.Figure()
        for s in SENSORS:
            fig2.add_trace(go.Scatter(
                y=fault_hist[s], name=f"F_{s}",
                mode="lines", line=dict(color=colors[s], width=2)))
        fig2.add_hline(y=SENSOR_PARAMS["VOC"]["theta_suspicious"],
                       line_dash="dash", line_color="orange", annotation_text="θ_suspicious")
        fig2.add_hline(y=SENSOR_PARAMS["VOC"]["theta_faulty"],
                       line_dash="dash", line_color="red", annotation_text="θ_faulty")
        fig2.update_layout(title="Fault score F_s evolution", height=320, xaxis_title="Sample #")
        st.plotly_chart(fig2, use_container_width=True)

    ch3, ch4 = st.columns(2)

    with ch3:
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(
            y=df["T"], name="Temp (°C)",
            mode="lines", line=dict(color="#e74c3c")))
        fig3.add_trace(go.Scatter(
            y=df["H"], name="Humidity (%)",
            mode="lines", line=dict(color="#3498db")))
        fig3.update_layout(title="T & H (introcept inputs)", height=280, xaxis_title="Sample #")
        st.plotly_chart(fig3, use_container_width=True)

    with ch4:
        blame_hist = {s: [] for s in SENSORS}
        for fd in list(st.session_state.fault_history)[-120:]:
            for s in SENSORS:
                blame_hist[s].append(fd["loo"]["D_s"].get(s, 0))

        fig4 = go.Figure()
        for s in SENSORS:
            fig4.add_trace(go.Scatter(
                y=blame_hist[s], name=f"D_{s}",
                mode="lines",
                line=dict(color=colors[s], width=2, dash="dot")))
        fig4.add_hline(y=SENSOR_PARAMS["VOC"]["rho"],
                       line_dash="dash", line_color="purple", annotation_text="ρ (L_s threshold)")
        fig4.update_layout(title="Blame fraction D_s", height=280, xaxis_title="Sample #")
        st.plotly_chart(fig4, use_container_width=True)

# ─────────────────────────────────────────────
# SECTION 6 – LOO Window Feature Debug
# ─────────────────────────────────────────────
with st.expander("🔬 LOO window features (last frame — debug)"):
    wf = decision["loo"].get("window_features")
    if wf:
        wf_df = pd.DataFrame({"Feature": list(wf.keys()), "Value": list(wf.values())})
        st.dataframe(wf_df, use_container_width=True)
        st.caption(f"Window contains {window_size}/{WINDOW_SECS} samples.")
    else:
        st.info("Window not yet warmed up — waiting for ≥2 samples.")

# ─────────────────────────────────────────────
# SECTION 7 – Flask In-Memory History Log
# ─────────────────────────────────────────────
with st.expander("🗃️ Raw Flask RAM records (last 100 entries)"):
    hist_df = fetch_history_from_flask(limit=100)
    if not hist_df.empty:
        st.dataframe(hist_df, use_container_width=True)
    else:
        st.info("No logs returned from Flask memory stack.")

# ─────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────
st.markdown("---")
st.caption(
    f"Last update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
    f"Source: Flask Server Endpoint `/api/latest` | "
    f"LOO window: {window_size}/{WINDOW_SECS} samples | "
    f"Confirmed faulty: {decision['confirmed_faulty'] or 'none'}"
)

if auto_refresh:
    import time
    time.sleep(2)
    st.rerun()