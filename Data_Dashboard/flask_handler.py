"""
Flask Handler — Fetch sensor data from Flask backend
Replaces mongo_handler for Flask-based data retrieval
"""

import requests
import pandas as pd
from datetime import datetime
import logging

logger = logging.getLogger("FlaskHandler")


def check_flask_connection(flask_url):
    """
    Test connection to Flask backend
    
    Args:
        flask_url (str): Base URL of Flask server (e.g., 'http://localhost:5000')
    
    Returns:
        bool: True if connection successful, False otherwise
    """
    try:
        response = requests.get(f"{flask_url}/api/latest", timeout=5)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Flask connection failed: {e}")
        return False


def get_latest_data(flask_url):
    """
    Fetch the latest sensor data from Flask backend
    
    Args:
        flask_url (str): Base URL of Flask server
    
    Returns:
        dict: Latest sensor data with keys: T, H, P, VOC, CO2, PM2.5, timestamp
              Returns None if fetch fails
    
    Example response:
        {
            'timestamp': '2024-01-15T10:30:45.123Z',
            'T': 22.5,
            'H': 45.2,
            'P': 1013.25,
            'VOC': 125,
            'CO2': 420,
            'PM2.5': 15.3
        }
    """
    try:
        response = requests.get(f"{flask_url}/api/latest", timeout=5)
        if response.status_code == 200:
            data = response.json()
            # Ensure timestamp exists
            if 'timestamp' not in data:
                data['timestamp'] = datetime.now().isoformat()
            return data
        else:
            logger.error(f"Flask returned status {response.status_code}")
            return None
    except requests.exceptions.Timeout:
        logger.error("Flask request timeout")
        return None
    except requests.exceptions.ConnectionError:
        logger.error("Flask connection error")
        return None
    except Exception as e:
        logger.error(f"Error fetching from Flask: {e}")
        return None


def get_data_history(flask_url, limit=100):
    """
    Fetch historical data from Flask backend (if available)
    
    Args:
        flask_url (str): Base URL of Flask server
        limit (int): Maximum number of records to fetch (default: 100)
    
    Returns:
        pd.DataFrame: Historical sensor data, empty DataFrame if not available
    """
    try:
        # Endpoint for history (you may need to add this to Flask backend)
        response = requests.get(f"{flask_url}/api/history?limit={limit}", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame(data)
                return df
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"Could not fetch history: {e}")
        return pd.DataFrame()


def stream_flask_data(flask_url, callback, interval=1):
    """
    Continuously stream data from Flask backend
    Useful for real-time processing
    
    Args:
        flask_url (str): Base URL of Flask server
        callback (callable): Function to call with each data point
        interval (int): Polling interval in seconds (default: 1)
    """
    import time
    last_timestamp = None
    
    while True:
        try:
            data = get_latest_data(flask_url)
            if data:
                # Only process if new data (different timestamp)
                current_ts = data.get('timestamp')
                if current_ts != last_timestamp:
                    callback(data)
                    last_timestamp = current_ts
            time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Stream interrupted by user")
            break
        except Exception as e:
            logger.error(f"Stream error: {e}")
            time.sleep(interval)


def validate_sensor_data(data):
    """
    Validate sensor data from Flask backend
    
    Args:
        data (dict): Raw sensor data
    
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    required_fields = ['T', 'H', 'P', 'VOC', 'CO2', 'PM2.5']
    
    if not isinstance(data, dict):
        return False, "Data is not a dictionary"
    
    missing = [f for f in required_fields if f not in data]
    if missing:
        return False, f"Missing fields: {missing}"
    
    # Check for reasonable ranges (adjust as needed)
    ranges = {
        'T': (-40, 80),      # Temperature: -40 to 80°C
        'H': (0, 100),       # Humidity: 0-100%
        'P': (300, 1100),    # Pressure: 300-1100 hPa
        'VOC': (0, 5000),    # VOC: 0-5000 ppb
        'CO2': (0, 10000),   # CO2: 0-10000 ppm
        'PM2.5': (0, 1000),  # PM2.5: 0-1000 µg/m³
    }
    
    for field, (min_val, max_val) in ranges.items():
        try:
            value = float(data[field])
            if not (min_val <= value <= max_val):
                return False, f"{field} out of range: {value} (expected {min_val}-{max_val})"
        except (ValueError, TypeError):
            return False, f"{field} is not a number: {data[field]}"
    
    return True, None


# ─────────────────────────────────────────────
# Data caching (optional, for performance)
# ─────────────────────────────────────────────

class FlaskDataCache:
    """Simple in-memory cache for Flask data"""
    
    def __init__(self, max_size=500):
        self.cache = []
        self.max_size = max_size
    
    def add(self, data):
        """Add data point to cache"""
        self.cache.append(data)
        if len(self.cache) > self.max_size:
            self.cache.pop(0)
    
    def get_latest(self):
        """Get most recent data point"""
        return self.cache[-1] if self.cache else None
    
    def get_all(self):
        """Get all cached data"""
        return self.cache.copy()
    
    def to_dataframe(self):
        """Convert cache to pandas DataFrame"""
        return pd.DataFrame(self.cache) if self.cache else pd.DataFrame()
    
    def clear(self):
        """Clear cache"""
        self.cache.clear()