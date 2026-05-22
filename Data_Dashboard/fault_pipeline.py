"""
Complete Fault Detection Pipeline
Phase 1: Introcept Residual Monitor      (Fault Detection)
Phase 2: LOO Activity Model Consensus    (Fault Isolation / Blame)
Phase 3: Fusion – High-Confidence Suspicion
Phase 4: Active Confirmation Test        (z-test)
Phase 6: Final Activity Prediction Output

Key design points
─────────────────
• Phase-1 models (ml_FeatureAQI_*.pkl) receive a single-row feature vector
  whose columns differ per sensor — see _build_introcept_features().

• Phase-2 models (ml_activity_ex_*.pkl) were trained on 3-minute rolling
  window statistics.  LOOBlame keeps a deque of the last WINDOW_SECS seconds
  of raw frames and computes the 13-column stat vector on every call.
  Each LOO model receives that vector *minus* the two columns (mean + std)
  that belong to the excluded sensor.

  Full 13-column order (index → name):
      0  day
      1  data_temperature_mean
      2  data_temperature_std
      3  data_humidity_mean
      4  data_humidity_std
      5  data_pressure_mean
      6  data_pressure_max
      7  data_pm2_5_mean
      8  data_pm2_5_std
      9  data_voc_mean
      10 data_voc_std
      11 data_co2_mean
      12 data_co2_std

  Excluded columns per model:
      ml_activity_ex_pm2_5  → drop indices 7, 8   (pm2_5_mean, pm2_5_std)
      ml_activity_ex_voc    → drop indices 9, 10  (voc_mean,   voc_std)
      ml_activity_ex_co2    → drop indices 11, 12 (co2_mean,   co2_std)
"""

import os
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import numpy as np
from collections import deque, Counter
from datetime import datetime
import logging
import joblib
import keras
keras.utils.disable_interactive_logging()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FaultPipeline")


# ============================================================
# AQI CLASS CONVERSION FUNCTIONS
# ============================================================

def pm10_to_aqi_class(pm10):
    if pm10 <= 50:    return 1
    elif pm10 <= 100: return 2
    elif pm10 <= 250: return 3
    elif pm10 <= 350: return 4
    elif pm10 <= 430: return 5
    else:             return 6


def pm25_to_aqi_class(pm25):
    if pm25 <= 30:    return 1
    elif pm25 <= 60:  return 2
    elif pm25 <= 90:  return 3
    elif pm25 <= 120: return 4
    elif pm25 <= 250: return 5
    else:             return 6


def co_to_aqi_class(co):
    if co <= 1.0:    return 1
    elif co <= 2.0:  return 2
    elif co <= 10.0: return 3
    elif co <= 17.0: return 4
    elif co <= 34.0: return 5
    else:            return 6


def voc_to_aqi_class(voc):
    if voc <= 0.22:  return 1
    elif voc <= 0.66: return 2
    elif voc <= 1.43: return 3
    elif voc <= 2.2:  return 4
    elif voc <= 3.3:  return 5
    else:             return 6


def co2_to_aqi_class(co2):
    if co2 <= 400:   return 1
    elif co2 <= 1000: return 2
    elif co2 <= 1500: return 3
    elif co2 <= 2000: return 4
    elif co2 <= 5000: return 5
    else:             return 6


def pollutant_to_aqi_class(sensor: str, value: float) -> int:
    s = sensor.upper()
    if s == "PM10":  return pm10_to_aqi_class(value)
    if s == "PM2.5": return pm25_to_aqi_class(value)
    if s == "CO":    return co_to_aqi_class(value)
    if s == "VOC":   return voc_to_aqi_class(value)
    if s == "CO2":   return co2_to_aqi_class(value)
    raise ValueError(f"Unsupported sensor: {sensor}")


# ============================================================
# TIME / SEASON HELPERS  (Phase 1 feature engineering)
# ============================================================

def _season(month: int) -> int:
    """1=Winter 2=Spring 3=Summer 4=Autumn — adjust to match your training."""
    if month in (12, 1, 2): return 1
    if month in (3, 4, 5):  return 2
    if month in (6, 7, 8):  return 3
    return 4


def _timecluster(hour: int) -> int:
    """0=Night 1=Morning 2=Afternoon 3=Evening — adjust to match your training."""
    if hour < 6:   return 0
    if hour < 12:  return 1
    if hour < 18:  return 2
    return 3


def _build_introcept_features(sensor: str, T: float, H: float, P: float,
                               dt: datetime) -> np.ndarray:
    """
    Return a (1, n_features) array for the Phase-1 AQI-class model.

    PM2.5 model  →  8 features:
        ['AT (°C)', 'RH (%)', 'BP (mmHg)', 'month', 'weekday',
         'hour', 'season', 'timecluster']

    VOC / CO2 / CO / PM10  →  7 features:
        ['timestamp', 'data_temperature', 'data_humidity',
         'data_pressure', 'year', 'month', 'hour']
        where 'timestamp' = seconds since midnight

    NOTE: 'date' (YYYYMMDD integer) was present in the raw training CSV
    but was dropped before fitting — the model input layer expects 7 cols.
    If you see "expected 7, got 8" this function is correct; if you see
    "expected 8, got 7" add date_int back as the first element.
    """
    if sensor == "PM2.5":
        return np.array([[
            T,
            H,
            P,
            dt.month,
            dt.weekday(),       # Monday=0 … Sunday=6
            dt.hour,
            _season(dt.month),
            _timecluster(dt.hour),
        ]])

    # VOC, CO2, CO, PM10  — 7 features (no 'date' column)
    ts_sec = dt.hour * 3600 + dt.minute * 60 + dt.second
    return np.array([[
        ts_sec,
        T,
        H,
        P,
        dt.year,
        dt.month,
        dt.hour,
    ]])


# ============================================================
# SENSOR PARAMETERS  (edit after calibration)
# ============================================================

SENSOR_PARAMS = {
    "PM2.5": {
        # ── Phase 1 ──
        # Fault score update:
        #   anomaly  → F = F + d          (additive; d = class residual)
        #   healthy  → F = beta * F       (exponential decay, beta < 1)
        # beta=0.8 means ~half-life of 3 samples; theta_faulty=10 reached
        # after ~10 consecutive single-class anomalies.
        "tau":              2,
         "alpha":1,# min residual (AQI classes) to trigger
        "beta":             0.8,    # decay factor when healthy  (must be <1)
        "theta_faulty":     10,     # F >= this → FAULTY
        "theta_suspicious": 3,      # F >= this → SUSPICIOUS
        "T_I":              3,      # persistence length (seconds)
        # ── Phase 2 ──
        "W_L":              30,     # blame sliding-window length (samples)
        "theta_conf":       0.6,    # min confidence to cast a vote
        "theta_self":       0.6,    # min confidence for self-blame
        "rho":              0.5,    # blame-density threshold → L_s = 1
        # ── Phase 3 ──
        "T_fuse":           5,      # fusion persistence (seconds)
        # ── Phase 4 ──
        "z_thresh":         1.96,   # two-tailed 95 % z-threshold
    },
    "CO2": {
        "tau": 2, "alpha":1, "beta": 0.8,
        "theta_faulty": 10, "theta_suspicious": 3, "T_I": 5,
        "W_L": 30, "theta_conf": 0.6, "theta_self": 0.6, "rho": 0.5,
        "T_fuse": 5, "z_thresh": 1.96,
    },
    "VOC": {
        "tau": 2, "alpha":1, "beta": 0.5,
        "theta_faulty": 10, "theta_suspicious": 3, "T_I": 5,
        "W_L": 30, "theta_conf": 0.6, "theta_self": 0.6, "rho": 0.5,
        "T_fuse": 5, "z_thresh": 1.96,
    },

}


# ============================================================
# PHASE 1 – INTROCEPT MONITOR
# ============================================================

class IntroceptMonitor:

    def __init__(self, sensors: list, sampling_rate: float = 1.0):
        self.sensors = sensors
        self.fs      = sampling_rate

        self.F   = {s: 0.0 for s in sensors}
        self.C_I = {s: 0   for s in sensors}
        self.I_s = {s: 0   for s in sensors}

        self.models = {
            "PM2.5": joblib.load("ml_FeatureAQI_PM2_5.pkl"),
            "CO2":   joblib.load("ml_FeatureAQI_CO2.pkl"),
            "VOC":   joblib.load("ml_FeatureAQI_VOC.pkl"),
 
        }

    def _predict_aqi_class(self, sensor: str, T: float, H: float, P: float,
                            dt: datetime) -> int:
        X   = _build_introcept_features(sensor, T, H, P, dt)
        out = self.models[sensor].predict(X)
        # out shape (1,)   → direct class label  (sklearn-style wrapper)
        # out shape (1, n) → softmax probability vector (Keras dense output)
        out = np.squeeze(out)   # → scalar  or  1-D array of length n
        if out.ndim == 0:
            # scalar: already a class index
            return int(out)
        # probability vector: argmax gives 0-based index → AQI classes are
        # 1-indexed (1-6), so we add 1
        return int(np.argmax(out)) + 1

    def step(self, sensor: str, x_meas: float, T: float, H: float, P: float,
             dt: datetime) -> dict:
        s = sensor.upper()
        p = SENSOR_PARAMS[s]

        measured_class  = pollutant_to_aqi_class(s, x_meas)
        predicted_class = self._predict_aqi_class(s, T, H, P, dt)

        d  = abs(measured_class - predicted_class)

        # Fault-score update
        # On anomaly: additive increment by residual magnitude (bounded growth)
        # On healthy: exponential decay toward 0 (beta < 1)
        # Hard cap at theta_faulty * 2 so a pre-existing explosion resets fast.
        if d >=p["tau"]:
            self.F[s] = (self.F[s]* p["alpha"])+1
        else:
            self.F[s] = p["beta"] * self.F[s]
        # self.F[s] = min(self.F[s], p["theta_faulty"] * 2)   # hard cap

        fs = self.F[s]

        if fs >= p["theta_faulty"]:
            status = "FAULTY"
        elif fs >= p["theta_suspicious"]:
            status = "SUSPICIOUS"
        else:
            status = "NON-FAULTY"

        # Persistence counter
        if status != "NON-FAULTY":
            self.C_I[s] += 1
        else:
            self.C_I[s] = 0

        threshold    = int(p["T_I"] * self.fs)
        self.I_s[s]  = 1 if self.C_I[s] >= threshold else 0

        return {
            "sensor":              s,
            "measured_value":      x_meas,
            "measured_aqi_class":  measured_class,
            "predicted_aqi_class": predicted_class,
            "residual":            d,
            "fault_score":         fs,
            "status":              status,
            "C_I":                 self.C_I[s],
            "I_s":                 self.I_s[s],
        }


# ============================================================
# PHASE 2 – LOO ACTIVITY CONSENSUS & BLAME
# ============================================================

# Column names per model — must match feature_names_in_ exactly (22 cols each)
# Each model has the same 14 env columns + 8 cols for the two NON-excluded sensors.
# "Unnamed: 0" is the original CSV row index; at inference time we pass 0.
_LOO_COLUMNS = {
    "PM2.5": [                      # trained WITHOUT pm2_5
        "Unnamed: 0", "day",
        "data_temperature_mean", "data_temperature_std",
        "data_temperature_min",  "data_temperature_max",
        "data_humidity_mean",    "data_humidity_std",
        "data_humidity_min",     "data_humidity_max",
        "data_pressure_mean",    "data_pressure_std",
        "data_pressure_min",     "data_pressure_max",
        "data_voc_mean",   "data_voc_std",   "data_voc_min",   "data_voc_max",
        "data_co2_mean",   "data_co2_std",   "data_co2_min",   "data_co2_max",
    ],
    "VOC": [                        # trained WITHOUT voc
        "Unnamed: 0", "day",
        "data_temperature_mean", "data_temperature_std",
        "data_temperature_min",  "data_temperature_max",
        "data_humidity_mean",    "data_humidity_std",
        "data_humidity_min",     "data_humidity_max",
        "data_pressure_mean",    "data_pressure_std",
        "data_pressure_min",     "data_pressure_max",
        "data_pm2_5_mean", "data_pm2_5_std", "data_pm2_5_min", "data_pm2_5_max",
        "data_co2_mean",   "data_co2_std",   "data_co2_min",   "data_co2_max",
    ],
    "CO2": [                        # trained WITHOUT co2
        "Unnamed: 0", "day",
        "data_temperature_mean", "data_temperature_std",
        "data_temperature_min",  "data_temperature_max",
        "data_humidity_mean",    "data_humidity_std",
        "data_humidity_min",     "data_humidity_max",
        "data_pressure_mean",    "data_pressure_std",
        "data_pressure_min",     "data_pressure_max",
        "data_pm2_5_mean", "data_pm2_5_std", "data_pm2_5_min", "data_pm2_5_max",
        "data_voc_mean",   "data_voc_std",   "data_voc_min",   "data_voc_max",
    ],
}

# Full-model (c_full) 13-column feature layout — mean+std only, no min/max
# Must match feature_names_in_ of ml_activity_full.pkl exactly.
_CFULL_COLUMNS = [
    "day",
    "data_temperature_mean", "data_temperature_std",
    "data_humidity_mean",    "data_humidity_std",
    "data_pressure_mean",    "data_pressure_max",   # note: max not std
    "data_pm2_5_mean",       "data_pm2_5_std",
    "data_voc_mean",         "data_voc_std",
    "data_co2_mean",         "data_co2_std",
]

# 3-minute window at 1 Hz = 180 samples
WINDOW_SECS = 180


class LOOBlame:
    """
    Leave-One-Out blame using 3-minute rolling window statistics.

    For every incoming frame the raw readings (T, H, P, PM2.5, VOC, CO2) are
    pushed onto a deque.  Once ≥2 samples are available the 13-column stat
    vector is computed; each LOO model then receives that vector with the two
    columns of its excluded sensor removed.
    """

    LOO_SENSORS = ["PM2.5", "VOC", "CO2"]   # sensors with a LOO model

    def __init__(self, sensors: list, sampling_rate: float = 1.0):
        self.sensors = sensors
        self.fs      = sampling_rate

        # Rolling buffer — stores raw scalar readings per frame
        maxlen = max(WINDOW_SECS, 2)
        self.window: deque = deque(maxlen=maxlen)

        # Sliding blame windows (one per pipeline sensor)
        self.blame_windows = {
            s: deque(maxlen=SENSOR_PARAMS[s]["W_L"])
            for s in sensors
        }
        self.D_s = {s: 0.0 for s in sensors}
        self.L_s = {s: 0   for s in sensors}

        # LOO models — filename uses pm2_5 (underscore), not PM2.5 (dot)
        self.models = {
            "PM2.5": joblib.load("ml_activity_ex_pm2_5.pkl"),
            "VOC":   joblib.load("ml_activity_ex_voc.pkl"),
            "CO2":   joblib.load("ml_activity_ex_co2.pkl"),
        }
        # Full model — used for c_full prediction (all sensors healthy or suspect)
        self.model_full = joblib.load("ml_activity_full.pkl")

    # ----------------------------------------------------------------
    # Window statistics → shared stat dict used by _loo_predict
    # ----------------------------------------------------------------
    def _compute_stats(self) -> dict:
        """
        Compute mean/std/min/max over the current rolling window for every
        raw signal.  Returns a plain dict keyed by stat name.
        Std defaults to 0.0 when only one sample is available.
        """
        buf  = list(self.window)

        def arr(key):
            return np.array([f[key] for f in buf], dtype=float)

        def stats(a, name):
            std = float(np.std(a, ddof=1)) if len(a) > 1 else 0.0
            return {
                f"{name}_mean": float(np.mean(a)),
                f"{name}_std":  std,
                f"{name}_min":  float(np.min(a)),
                f"{name}_max":  float(np.max(a)),
            }

        d = {}
        d.update(stats(arr("T"),     "data_temperature"))
        d.update(stats(arr("H"),     "data_humidity"))
        d.update(stats(arr("P"),     "data_pressure"))
        d.update(stats(arr("PM2.5"), "data_pm2_5"))
        d.update(stats(arr("VOC"),   "data_voc"))
        d.update(stats(arr("CO2"),   "data_co2"))
        return d

    # ----------------------------------------------------------------
    # Single LOO prediction
    # ----------------------------------------------------------------
    def _loo_predict(self, exclude_sensor: str,
                     stat_dict: dict, day: int) -> tuple:
        """
        Build a named DataFrame with exactly the 22 columns the model expects,
        then predict.  Returns (activity_label, confidence).
        """
        import pandas as pd

        cols  = _LOO_COLUMNS[exclude_sensor]   # 22 column names for this model
        # Build one-row dict; "Unnamed: 0" is the original CSV row index → 0
        row   = {"Unnamed: 0": 0, "day": day}
        row.update(stat_dict)

        X     = pd.DataFrame([row], columns=cols)
        model = self.models[exclude_sensor]

        pred  = model.predict(X)[0]
        conf  = (float(np.max(model.predict_proba(X)[0]))
                 if hasattr(model, "predict_proba") else 0.5)
        return pred, conf

    # ----------------------------------------------------------------
    # Full-model prediction  (c_full)
    # ----------------------------------------------------------------
    def _predict_cfull(self, stat_dict: dict, day: int) -> tuple:
        """
        Build the 13-column DataFrame for the full activity model and predict.
        Returns (activity_label, confidence).
        """
        import pandas as pd

        row = {
            "day":                   day,
            "data_temperature_mean": stat_dict["data_temperature_mean"],
            "data_temperature_std":  stat_dict["data_temperature_std"],
            "data_humidity_mean":    stat_dict["data_humidity_mean"],
            "data_humidity_std":     stat_dict["data_humidity_std"],
            "data_pressure_mean":    stat_dict["data_pressure_mean"],
            "data_pressure_max":     stat_dict["data_pressure_max"],
            "data_pm2_5_mean":       stat_dict["data_pm2_5_mean"],
            "data_pm2_5_std":        stat_dict["data_pm2_5_std"],
            "data_voc_mean":         stat_dict["data_voc_mean"],
            "data_voc_std":          stat_dict["data_voc_std"],
            "data_co2_mean":         stat_dict["data_co2_mean"],
            "data_co2_std":          stat_dict["data_co2_std"],
        }
        X    = pd.DataFrame([row], columns=_CFULL_COLUMNS)
        pred = self.model_full.predict(X)[0]
        conf = (float(np.max(self.model_full.predict_proba(X)[0]))
                if hasattr(self.model_full, "predict_proba") else 0.5)
        return pred, conf

    # ----------------------------------------------------------------
    # Main step — called once per frame
    # ----------------------------------------------------------------
    def step(self, frame: dict) -> dict:
        """
        frame must contain: T, H, P, VOC, CO2, PM2.5, timestamp (unix float).

        Returns the standard LOO result dict including predictions, consensus,
        blame votes, D_s, and L_s.
        """
        # Push raw reading into rolling buffer
        self.window.append({
            "T":     frame["T"],
            "H":     frame["H"],
            "P":     frame["P"],
            "PM2.5": frame["PM2.5"],
            "VOC":   frame["VOC"],
            "CO2":   frame["CO2"],
        })

        ts = frame.get("timestamp", datetime.now().timestamp())

        try:
            # Numeric Unix timestamp
            dt = datetime.fromtimestamp(float(ts))
        except (ValueError, TypeError):
            # ISO timestamp string
            dt = datetime.fromisoformat(ts)

        # Need ≥2 samples to compute std; return neutral result until warmed up
        if len(self.window) < 2:
            neutral = {s: {"activity": "other", "conf": 0.0}
                       for s in self.LOO_SENSORS}
            for s in self.sensors:
                self.blame_windows[s].append(0)
            return {
                "predictions":    neutral,
                "cfull_activity": "unknown",
                "cfull_conf":     0.0,
                "cons_activity":  None,
                "cons_exists":    False,
                "blame_votes":    {s: 0 for s in self.sensors},
                "D_s":            dict(self.D_s),
                "L_s":            dict(self.L_s),
                "window_size":    len(self.window),
                "window_features": {},
            }

        stat_dict = self._compute_stats()
        day       = dt.weekday()   # 0=Mon … 6=Sun

        # ── Run full model (c_full) ───────────────────────────────────
        cfull_activity, cfull_conf = self._predict_cfull(stat_dict, day)

        # ── Run all LOO models ────────────────────────────────────────
        predictions = {}
        for s in self.LOO_SENSORS:
            act, conf = self._loo_predict(s, stat_dict, day)
            predictions[s] = {"activity": act, "conf": conf}

        # ── Consensus (≥2 high-confidence models agree) ──────────────
        theta_conf = SENSOR_PARAMS[self.sensors[0]]["theta_conf"]
        vote_map   = {}
        for s, pred in predictions.items():
            if pred["conf"] > theta_conf:
                vote_map.setdefault(pred["activity"], []).append(s)

        cons_activity = None
        cons_exists   = False
        for act, voters in vote_map.items():
            if len(voters) >= 2:
                cons_activity = act
                cons_exists   = True
                break

        # ── Blame votes ───────────────────────────────────────────────
        blame_votes = {}
        for s in self.sensors:
            v = 0
            if s in predictions:
                pred       = predictions[s]
                theta_self = SENSOR_PARAMS[s]["theta_self"]
                if (cons_exists
                        and pred["activity"] != cons_activity
                        and pred["conf"]     >  theta_self):
                    v = 1
            blame_votes[s] = v
            self.blame_windows[s].append(v)

        # ── Persistence filter → L_s ──────────────────────────────────
        for s in self.sensors:
            win          = self.blame_windows[s]
            self.D_s[s]  = sum(win) / len(win) if win else 0.0
            self.L_s[s]  = 1 if self.D_s[s] >= SENSOR_PARAMS[s]["rho"] else 0

        return {
            "predictions":     predictions,
            "cfull_activity":  cfull_activity,
            "cfull_conf":      cfull_conf,
            "cons_activity":   cons_activity,
            "cons_exists":     cons_exists,
            "blame_votes":     blame_votes,
            "D_s":             dict(self.D_s),
            "L_s":             dict(self.L_s),
            "window_size":     len(self.window),
            "window_features": stat_dict,
        }


# ============================================================
# PHASE 3 – FUSION LAYER
# ============================================================

class FusionLayer:
    """Suspect_s = 1 when I_s AND L_s both stay 1 for T_fuse seconds."""

    def __init__(self, sensors: list, sampling_rate: float = 1.0):
        self.sensors = sensors
        self.fs      = sampling_rate
        self.C_fuse  = {s: 0 for s in sensors}
        self.Suspect = {s: 0 for s in sensors}

    def step(self, I_s: dict, L_s: dict) -> dict:
        prev = dict(self.Suspect)
        for s in self.sensors:
            if I_s[s] == 1 and L_s[s] == 1:
                self.C_fuse[s] += 1
            else:
                self.C_fuse[s]  = 0
            threshold       = int(SENSOR_PARAMS[s]["T_fuse"] * self.fs)
            self.Suspect[s] = 1 if self.C_fuse[s] >= threshold else 0

        new_suspects = [s for s in self.sensors
                        if self.Suspect[s] == 1 and prev[s] == 0]
        return {
            "C_fuse":       dict(self.C_fuse),
            "Suspect":      dict(self.Suspect),
            "new_suspects": new_suspects,
        }


# ============================================================
# PHASE 4 – ACTIVE CONFIRMATION TEST  (z-test)
# ============================================================

# Replace mu / sigma with values from your healthy calibration data.
BASELINE_STATS = {
    "VOC":   {"best_activity": "reheat", "mu": 200.0, "sigma": 15.0},
    "CO2":   {"best_activity": "other",  "mu": 400.0, "sigma": 30.0},
    "PM2.5": {"best_activity": "reheat", "mu":  15.0, "sigma":  3.0},
}


class ActiveConfirmationTest:
    """
    1. Prompt user to perform A_s* for 2 minutes.
    2. After 30 s stabilisation, collect n raw samples.
    3. z_s = (x̄ − μ*) / (σ* / √n)
    4. |z_s| ≥ z_thresh → CONFIRMED   else CLEARED
    """

    STABILISE_SECS = 30
    TOTAL_SECS     = 150   # 30 stabilise + 120 collect

    def __init__(self):
        self.test_sensor  = None
        self.start_time   = None
        self.phase        = "idle"   # idle | stabilising | collecting | done
        self.samples: list = []
        self.last_result  = None

    @property
    def active(self) -> bool:
        return self.phase in ("stabilising", "collecting")

    def start(self, sensor: str) -> dict:
        self.test_sensor  = sensor
        self.start_time   = datetime.now()
        self.phase        = "stabilising"
        self.samples      = []
        self.last_result  = None
        bs = BASELINE_STATS[sensor]
        logger.info(
            f"[ActiveTest] START {sensor} — perform '{bs['best_activity']}' "
            f"for 2 minutes (μ*={bs['mu']}, σ*={bs['sigma']})"
        )
        return {
            "sensor":           sensor,
            "activity":         bs["best_activity"],
            "duration_seconds": 120,
            "message": (
                f"Please perform '{bs['best_activity']}' for 2 minutes "
                f"to verify the {sensor} sensor."
            ),
        }

    def add_sample(self, value: float):
        if not self.active or self.test_sensor is None:
            return
        elapsed = (datetime.now() - self.start_time).total_seconds()
        if elapsed >= self.STABILISE_SECS:
            self.phase = "collecting"
            self.samples.append(value)
        if elapsed >= self.TOTAL_SECS:
            self._run_z_test()

    def _run_z_test(self):
        s  = self.test_sensor
        bs = BASELINE_STATS[s]
        n  = len(self.samples)
        if n < 10:
            self.last_result = {"status": "INCOMPLETE", "n": n}
            self.phase       = "done"
            return

        x_bar  = float(np.mean(self.samples))
        mu, sigma = bs["mu"], bs["sigma"]
        z      = (x_bar - mu) / (sigma / np.sqrt(n)) if sigma > 0 else 0.0
        thresh = SENSOR_PARAMS[s]["z_thresh"]
        status = "CONFIRMED" if abs(z) >= thresh else "CLEARED"

        self.last_result = {
            "status": status, "z_score": z,
            "x_bar": x_bar, "mu": mu, "sigma": sigma,
            "n": n, "thresh": thresh,
        }
        self.phase = "done"
        logger.info(f"[ActiveTest] z-test {s}: z={z:.2f} → {status}")

    def reset(self):
        self.test_sensor = None
        self.start_time  = None
        self.phase       = "idle"
        self.samples     = []

    def elapsed(self) -> float:
        return (0.0 if self.start_time is None
                else (datetime.now() - self.start_time).total_seconds())


# ============================================================
# PHASE 6 – FINAL ACTIVITY PREDICTION OUTPUT
# ============================================================

def phase6_output(loo_result: dict,
                  confirmed_faulty: set,
                  suspect_flags: dict) -> dict:
    """
    Implements equation (1) exactly:

        ŷ(t) = c_full(t)        if ALL sensors HEALTHY
        ŷ(t) = c_{-s}(t)        if sensor s is CONFIRMED FAULTY
        ŷ(t) = c_full(t) [LOW]  if any sensor is SUSPECT (unconfirmed)

    c_full  → ml_activity_full.pkl   (all 3 sensors in feature vector)
    c_{-s}  → ml_activity_ex_*.pkl   (LOO model that never saw sensor s)

    Multiple confirmed faulty: majority vote among the relevant LOO models.
    Switch to LOO is instantaneous once fault is confirmed.
    """
    predictions    = loo_result["predictions"]
    cfull_activity = loo_result.get("cfull_activity") #,"unknown"
    cfull_conf     = loo_result.get("cfull_conf",     0.0)
    faulty_list    = list(confirmed_faulty)

    # Any sensor suspected but not yet confirmed?
    any_suspect = any(
        v == 1 for s, v in suspect_flags.items()
        if s not in confirmed_faulty
    )

    if not faulty_list:
        # ── All healthy  OR  suspect-but-unconfirmed → use c_full ─────
        activity = cfull_activity
        conf     = cfull_conf
        mode     = "c_full"
        warn     = any_suspect          # LOW CONF flag when suspect present

    elif len(faulty_list) == 1:
        # ── Exactly one sensor CONFIRMED FAULTY → switch to c_{-s} ───
        excl     = faulty_list[0]
        activity = predictions[excl]["activity"] if excl in predictions else "unknown"
        conf     = predictions[excl]["conf"]     if excl in predictions else 0.0
        mode     = f"c_minus_{excl}"
        warn     = False

    else:
        # ── Multiple CONFIRMED FAULTY → majority vote of LOO models ───
        valid    = [s for s in predictions if s in faulty_list]
        votes    = Counter(predictions[s]["activity"] for s in valid)
        activity = votes.most_common(1)[0][0] if votes else "unknown"
        conf     = max((predictions[s]["conf"] for s in valid), default=0.0)
        mode     = "majority_loo_vote"
        warn     = False

    return {
        "activity":      activity,
        "confidence":    conf,
        "output_mode":   mode,
        "low_conf_warn": warn,
    }


# ============================================================
# MASTER PIPELINE
# ============================================================

class CompleteFaultDetectionPipeline:
    """
    Call process_frame(sensor_data) every second.

    sensor_data expected keys:
        T, H, P          – environmental readings
        VOC, CO2, PM2.5  – pollutant sensor readings
        timestamp        – unix float (optional; defaults to now)
    """

    SENSORS = ["VOC", "CO2", "PM2.5"]

    def __init__(self, sampling_rate: float = 1.0):
        self.fs               = sampling_rate
        self.introcept        = IntroceptMonitor(self.SENSORS, sampling_rate)
        self.loo              = LOOBlame(self.SENSORS, sampling_rate)
        self.fusion           = FusionLayer(self.SENSORS, sampling_rate)
        self.active_test      = ActiveConfirmationTest()
        self.confirmed_faulty : set = set()
        self.history          : deque = deque(maxlen=1000)

    def process_frame(self, sensor_data: dict) -> dict:
        T  = sensor_data.get("T",    25.0)
        H  = sensor_data.get("H",    55.0)
        P  = sensor_data.get("P", 1013.25)
        ts = sensor_data.get("timestamp", datetime.now().timestamp())
        try:
            # Unix timestamp
            dt = datetime.fromtimestamp(float(ts))
        except (ValueError, TypeError):
            # ISO datetime string
            dt = datetime.fromisoformat(ts)

        # ── Phase 1: Introcept ────────────────────────────────────────
        introcept_results = {}
        I_s = {}
        for s in self.SENSORS:
            x_meas             = sensor_data.get(s, 0.0)
            r                  = self.introcept.step(s, x_meas, T, H, P, dt)
            introcept_results[s] = r
            I_s[s]             = r["I_s"]

        # ── Phase 2: LOO Blame (3-min window features) ────────────────
        loo_frame = {s: sensor_data.get(s, 0.0) for s in self.SENSORS}
        loo_frame.update({"T": T, "H": H, "P": P, "timestamp": ts})
        loo_result = self.loo.step(loo_frame)
        L_s        = loo_result["L_s"]

        # ── Phase 3: Fusion ───────────────────────────────────────────
        fusion_result = self.fusion.step(I_s, L_s)

        # ── Phase 4: Active Confirmation ──────────────────────────────
        active_test_prompt = None
        for s in fusion_result["new_suspects"]:
            if not self.active_test.active and s not in self.confirmed_faulty:
                active_test_prompt = self.active_test.start(s)

        if self.active_test.active:
            meas = sensor_data.get(self.active_test.test_sensor, 0.0)
            self.active_test.add_sample(meas)

            if self.active_test.phase == "done":
                result = self.active_test.last_result
                if result and result["status"] == "CONFIRMED":
                    self.confirmed_faulty.add(self.active_test.test_sensor)
                self.active_test.reset()

        # ── Phase 6: Output ───────────────────────────────────────────
        output = phase6_output(
            loo_result,
            self.confirmed_faulty,
            fusion_result["Suspect"],
        )

        decision = {
            "timestamp":            ts,
            "introcept":            introcept_results,
            "I_s":                  I_s,
            "loo":                  loo_result,
            "L_s":                  L_s,
            "fusion":               fusion_result,
            "suspects":             fusion_result["Suspect"],
            "confirmed_faulty":     list(self.confirmed_faulty),
            "active_test_prompt":   active_test_prompt,
            "active_test_phase":    self.active_test.phase,
            "active_test_sensor":   self.active_test.test_sensor,
            "active_test_elapsed":  self.active_test.elapsed(),
            "active_test_n":        len(self.active_test.samples),
            "active_test_result":   self.active_test.last_result,
            "output":               output,
        }
        self.history.append(decision)
        return decision