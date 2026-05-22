"""
Model Loader & Configuration Manager
Loads pre-trained activity classifiers and manages baseline stats.
"""

import pickle
import json
import logging
from pathlib import Path

logger = logging.getLogger("ModelLoader")


class ModelLoader:
    """Load LOO activity models from disk."""

    def __init__(self, model_dir="./models"):
        self.model_dir = Path(model_dir)
        self._activity_models = {}

    def load_activity_models(self) -> dict:
        """
        Expected files (scikit-learn estimators with predict_proba):
            ml_activity_ex_voc.pkl   — trained WITHOUT VOC features
            ml_activity_ex_co2.pkl   — trained WITHOUT CO2 features
            ml_activity_ex_pm2_5.pkl — trained WITHOUT PM2.5 features
        Returns {sensor: model} mapping used by LOOBlame when real models exist.
        """
        mapping = {
            "VOC":   "ml_activity_ex_voc.pkl",
            "CO2":   "ml_activity_ex_co2.pkl",
            "PM2.5": "ml_activity_ex_pm2_5.pkl",
        }
        for sensor, fname in mapping.items():
            path = self.model_dir / fname
            if not path.exists():
                logger.warning(f"Model not found: {path}  (built-in heuristic will be used)")
                continue
            try:
                with open(path, "rb") as f:
                    self._activity_models[sensor] = pickle.load(f)
                logger.info(f"Loaded activity model for {sensor}")
            except Exception as e:
                logger.error(f"Error loading {fname}: {e}")

        return self._activity_models

    def get_activity_models(self) -> dict:
        return self._activity_models


class BaselineStatsManager:
    """
    Manage μ* and σ* for each sensor's best activity A_s*.
    Computed from healthy training data (Section 0.4 of spec).
    Replace the placeholder values below with real computed ones.
    """

    @staticmethod
    def get_default() -> dict:
        """
        Format:
        {
            sensor: {
                activity_name: {"mu": float, "sigma": float},
                ...
            }
        }
        The activity with the smallest sigma is A_s* (best activity).
        """
        return {
            "VOC": {
                "boil":   {"mu": 250.0, "sigma": 20.0},
                "fry":    {"mu": 300.0, "sigma": 25.0},
                "reheat": {"mu": 200.0, "sigma": 15.0},  # ← smallest σ → A*
                "toast":  {"mu": 180.0, "sigma": 12.0},
                "other":  {"mu": 150.0, "sigma": 30.0},
            },
            "CO2": {
                "boil":   {"mu": 500.0, "sigma": 40.0},
                "fry":    {"mu": 600.0, "sigma": 50.0},
                "reheat": {"mu": 450.0, "sigma": 35.0},
                "toast":  {"mu": 420.0, "sigma": 30.0},
                "other":  {"mu": 400.0, "sigma": 30.0},  # ← smallest σ → A*
            },
            "PM2.5": {
                "boil":   {"mu": 25.0, "sigma": 5.0},
                "fry":    {"mu": 40.0, "sigma": 8.0},
                "reheat": {"mu": 15.0, "sigma": 3.0},    # ← smallest σ → A*
                "toast":  {"mu": 30.0, "sigma": 6.0},
                "other":  {"mu": 10.0, "sigma": 5.0},
            },
        }

    @staticmethod
    def best_activity(stats: dict, sensor: str) -> tuple:
        """Return (activity_name, mu, sigma) with the smallest sigma."""
        sensor_stats = stats.get(sensor, {})
        best = min(sensor_stats.items(), key=lambda kv: kv[1]["sigma"])
        return best[0], best[1]["mu"], best[1]["sigma"]

    @staticmethod
    def load_from_file(path: str) -> dict:
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading baseline stats: {e}")
            return BaselineStatsManager.get_default()

    @staticmethod
    def save_to_file(stats: dict, path: str):
        try:
            with open(path, "w") as f:
                json.dump(stats, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving baseline stats: {e}")

    @staticmethod
    def compute_from_data(data: dict) -> dict:
        """
        Compute stats from raw collected data.
        data = { sensor: { activity: [values...] } }
        """
        import numpy as np
        result = {}
        for sensor, acts in data.items():
            result[sensor] = {}
            for act, vals in acts.items():
                if vals:
                    result[sensor][act] = {
                        "mu":    float(np.mean(vals)),
                        "sigma": float(np.std(vals)),
                    }
        return result