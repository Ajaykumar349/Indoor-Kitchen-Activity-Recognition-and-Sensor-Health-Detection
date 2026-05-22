"""
Enhanced Flask Backend — Sensor data server with ESP32 WebSocket relay
Features:
  - WebSocket endpoint for ESP32 data ingestion (with case-insensitive auto-mapping)
  - REST API for Streamlit dashboard
  - In-memory data history buffer
  - Connection status tracking
"""

from flask import Flask, jsonify
from flask_sock import Sock
import json
import logging
from datetime import datetime
from collections import deque
import threading

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("FlaskBackend")

# ─────────────────────────────────────────────
# FLASK APP SETUP
# ─────────────────────────────────────────────
app = Flask(__name__)
sock = Sock(app)

# ─────────────────────────────────────────────
# DATA STORAGE
# ─────────────────────────────────────────────
latest_data = {}
data_history = deque(maxlen=1000)  # Keep last 1000 samples
connected_esp32 = False
connection_lock = threading.Lock()

# Default sensor values
DEFAULT_FRAME = {
    'timestamp': datetime.now().isoformat(),
    'T': 20.0,
    'H': 50.0,
    'P': 1013.25,
    'VOC': 100.0,
    'CO2': 400.0,
    'PM2.5': 25.0,
    'source': 'default'
}

latest_data = DEFAULT_FRAME.copy()

# ─────────────────────────────────────────────
# WEBSOCKET ENDPOINT - ESP32 DATA INGESTION
# ─────────────────────────────────────────────
@sock.route('/ws')
def websocket_esp32(ws):
    """
    WebSocket endpoint for ESP32 sensor data
    Maps incoming variable fields cleanly to uppercase pipeline parameters.
    """
    global latest_data, connected_esp32
    
    with connection_lock:
        connected_esp32 = True
    
    logger.info("ESP32 connected via WebSocket")
    
    try:
        while True:
            # Receive data from ESP32
            raw_data = ws.receive()
            
            if raw_data:
                try:
                    raw_payload = json.loads(raw_data)
                    
                    # Intercept and dynamically auto-map firmware key naming variants
                    data = {
                        'T':     float(raw_payload.get('temp', raw_payload.get('T', 25.0))),
                        'H':     float(raw_payload.get('hum',  raw_payload.get('H', 55.0))),
                        'P':     float(raw_payload.get('P',    1013.25)), # Default standard fallback
                        'VOC':   float(raw_payload.get('voc',  raw_payload.get('VOC', 0.0))),
                        'CO2':   float(raw_payload.get('co2',  raw_payload.get('CO2', 400.0))),
                        'PM2.5': float(raw_payload.get('pm25', raw_payload.get('PM2.5', 0.0)))
                    }
                    
                    # Retain timestamp metadata tracking
                    if 'timestamp' not in raw_payload:
                        data['timestamp'] = datetime.now().isoformat()
                    else:
                        data['timestamp'] = raw_payload['timestamp']
                    
                    data['source'] = 'esp32'
                    
                    # Save cleanly structures map down to stack memory space
                    with connection_lock:
                        latest_data = data.copy()
                        data_history.append(data.copy())
                    
                    logger.info(f"RX Cleaned: T={data['T']:.1f}°C | H={data['H']:.1f}% | VOC={data['VOC']:.1f} ppm | CO2={data['CO2']:.0f} ppm")
                    
                    # Send acknowledgment to clear transaction block
                    ws.send(json.dumps({"status": "OK", "timestamp": datetime.now().isoformat()}))
                
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON received: {raw_data}")
                    ws.send(json.dumps({"status": "ERROR", "message": "Invalid JSON"}))
                except Exception as e:
                    logger.error(f"Data processing error: {e}")
                    ws.send(json.dumps({"status": "ERROR", "message": str(e)}))
    
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    
    finally:
        with connection_lock:
            connected_esp32 = False
        logger.info("ESP32 disconnected")


# ─────────────────────────────────────────────
# REST API ENDPOINTS
# ─────────────────────────────────────────────

@app.route('/api/latest', methods=['GET'])
def get_latest():
    with connection_lock:
        return jsonify(latest_data)


@app.route('/api/history', methods=['GET'])
def get_history():
    from flask import request
    limit = int(request.args.get('limit', 100))
    
    with connection_lock:
        history = list(data_history)[-limit:]
    
    return jsonify(history)


@app.route('/api/status', methods=['GET'])
def get_status():
    with connection_lock:
        return jsonify({
            "status": "ready",
            "esp32_connected": connected_esp32,
            "data_points": len(data_history),
            "last_update": latest_data.get('timestamp'),
            "server_time": datetime.now().isoformat()
        })


@app.route('/api/stats', methods=['GET'])
def get_stats():
    import statistics
    
    with connection_lock:
        history = list(data_history)
    
    if not history:
        return jsonify({"error": "No data available"}), 400
    
    sensors = ['T', 'H', 'P', 'VOC', 'CO2', 'PM2.5']
    stats = {}
    
    for sensor in sensors:
        values = [d.get(sensor, 0) for d in history if sensor in d]
        if values:
            stats[sensor] = {
                'min': min(values),
                'max': max(values),
                'mean': statistics.mean(values),
                'stdev': statistics.stdev(values) if len(values) > 1 else 0,
                'count': len(values)
            }
    
    return jsonify(stats)


@app.route('/api/clear_history', methods=['POST'])
def clear_history():
    with connection_lock:
        data_history.clear()
    return jsonify({"message": "History cleared", "timestamp": datetime.now().isoformat()})


@app.route('/api/test_data', methods=['POST'])
def post_test_data():
    from flask import request
    try:
        raw_payload = request.get_json()
        
        # Mirror case mapping logic for direct HTTP simulation routes
        data = {
            'T':     float(raw_payload.get('temp', raw_payload.get('T', 25.0))),
            'H':     float(raw_payload.get('hum',  raw_payload.get('H', 55.0))),
            'P':     float(raw_payload.get('P',    1013.25)),
            'VOC':   float(raw_payload.get('voc',  raw_payload.get('VOC', 0.0))),
            'CO2':   float(raw_payload.get('co2',  raw_payload.get('CO2', 400.0))),
            'PM2.5': float(raw_payload.get('pm25', raw_payload.get('PM2.5', 0.0)))
        }
        data['timestamp'] = datetime.now().isoformat()
        data['source'] = 'test'
        
        with connection_lock:
            global latest_data
            latest_data = data.copy()
            data_history.append(data.copy())
        
        return jsonify({"status": "OK", "data": data}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }), 200

# ─────────────────────────────────────────────
# ERROR HANDLERS
# ─────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal server error: {e}")
    return jsonify({"error": "Internal server error"}), 500

# ─────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting Flask Backend for Sensor Fault Detection Pipeline")
    logger.info("WebSocket: ws://0.0.0.0:5000/ws")
    logger.info("REST API: http://0.0.0.0:5000/api/*")
    
    try:
        from gevent import pywsgi
        from geventwebsocket.handler import WebSocketHandler
        
        logger.info("Using gevent WSGI server for WebSocket support")
        server = pywsgi.WSGIServer(
            ('0.0.0.0', 5000),
            app,
            handler_class=WebSocketHandler
        )
        server.serve_forever()
    except ImportError:
        logger.warning("gevent not available, using Flask development server")
        app.run(host="0.0.0.0", port=5000, debug=True)