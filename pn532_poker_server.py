#!/usr/bin/env python3
"""
PN532 Poker Full-Stack Application

- Multi-page Flask application with professional UI
- Automatic UID capture from card reads
- Comprehensive card library management
- Virtual poker table layout with reader positioning
- Real-time card detection and management
"""

import time, json, threading
from pathlib import Path
from flask import Flask, jsonify, request, render_template
from datetime import datetime

# Adafruit PN532 imports
try:
    import board, busio
    from adafruit_pn532.i2c import PN532_I2C
    PN532_AVAILABLE = True
except ImportError as e:
    print(f"PN532 libraries not available: {e}")
    print("Install with: pip install adafruit-circuitpython-pn532 adafruit-blinka")
    PN532_AVAILABLE = False

# ---------- Config ----------
MAP_FILE = Path("card_map.json")
CONFIG_FILE = Path("table_config.json")
POLL_INTERVAL = 0.12  # seconds

# Default configuration for expandable poker tables
DEFAULT_CONFIG = {
    "table_name": "PN532 Poker Table Alpha",
    "max_players": 8,
    "readers": {
        "main": {"type": "pn532", "position": "Community Cards", "i2c_addr": 36}
    }
}

# Card suits and values for easy mapping
SUITS = ["♠", "♥", "♦", "♣"]
VALUES = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
FULL_DECK = [f"{val}{suit}" for suit in SUITS for val in VALUES]
# ----------------------------

# Load/save functions
def load_map():
    if MAP_FILE.exists():
        try:
            return json.loads(MAP_FILE.read_text())
        except Exception:
            return {}
    return {}

def save_map(m):
    MAP_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2))

def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return DEFAULT_CONFIG.copy()

def save_config(config):
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2))

# Initialize data
UID_TO_LABEL = load_map()
TABLE_CONFIG = load_config()
READERS = TABLE_CONFIG["readers"]
STATE = {name: {
    "uid": None, 
    "label": None, 
    "last_seen": None, 
    "position": cfg.get("position", name),
    "type": cfg.get("type", "pn532")
} for name, cfg in READERS.items()}

# Global variable to store last detected UID for auto-capture
LAST_DETECTED_UID = None

# Initialize PN532 (I2C) - using same settings as working test program
pn532 = None
if PN532_AVAILABLE:
    try:
        # Use explicit I2C settings that match your working test program
        i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        pn532 = PN532_I2C(i2c, debug=False)  # Remove addr parameter - let it auto-detect
        ic, ver, rev, support = pn532.firmware_version
        print(f"Found PN532 with firmware version {ver}.{rev}")
        pn532.SAM_configuration()
        print("PN532 initialized successfully!")
    except Exception as e:
        print(f"PN532 init failed: {e}")
        print("Check I2C wiring and run 'sudo i2cdetect -y 1' to verify address")
        pn532 = None
else:
    print("PN532 libraries not installed - running in demo mode")

# Enhanced poll loop with auto-capture
stop_flag = False
def poll_loop():
    global LAST_DETECTED_UID
    last_uid = None
    reader_name = list(READERS.keys())[0]  # Use first configured reader
    
    while not stop_flag:
        if pn532 is None:
            STATE[reader_name].update({"uid": None, "label": None, "last_seen": None})
            time.sleep(POLL_INTERVAL)
            continue
            
        try:
            uid = pn532.read_passive_target(timeout=0.5)  # returns bytes or None
        except Exception as e:
            # transient comms error
            uid = None
            
        if uid is not None:
            # uid is bytes -> format as uppercase HEX (no 0x, contiguous)
            uhex = "".join(f"{b:02X}" for b in uid)
        else:
            uhex = None
            
        if uhex != last_uid:
            last_uid = uhex
            label = UID_TO_LABEL.get(uhex)
            STATE[reader_name].update({
                "uid": uhex, 
                "label": label, 
                "last_seen": time.time() if uhex else None
            })
            
            # Update global variable for auto-capture
            LAST_DETECTED_UID = uhex
            
            print(f"[{reader_name}] {uhex or '(no card)'} {('=> '+label) if label else ''}")
            
        time.sleep(POLL_INTERVAL)

# Start background polling thread
t = threading.Thread(target=poll_loop, daemon=True)
t.start()

app = Flask(__name__)

# Routes
@app.route("/")
def table_view():
    return render_template("table.html", 
                         table_name=TABLE_CONFIG["table_name"],
                         readers=READERS,
                         page="table")

@app.route("/config")
def config_view():
    return render_template("config.html", 
                         table_name=TABLE_CONFIG["table_name"],
                         readers=READERS,
                         page="config")

@app.route("/cards")
def cards_view():
    return render_template("cards.html", 
                         table_name=TABLE_CONFIG["table_name"],
                         page="cards")

# API Endpoints
@app.get("/api/state")
def get_state():
    return jsonify(STATE)

@app.get("/api/cards")
def get_cards():
    return jsonify(UID_TO_LABEL)

@app.get("/api/config")
def get_config():
    return jsonify(TABLE_CONFIG)

@app.get("/api/last_uid")
def get_last_uid():
    """Get the last detected UID for auto-capture"""
    return jsonify({"uid": LAST_DETECTED_UID})

@app.post("/api/map")
def map_uid():
    body = request.get_json(force=True)
    uid = (body.get("uid") or "").upper()
    label = body.get("label")
    if not uid or not label:
        return jsonify({"error":"uid and label required"}), 400
    
    # Check if card is already mapped to prevent duplicates
    if label in UID_TO_LABEL.values():
        return jsonify({"error": f"Card {label} is already mapped to another UID"}), 400
    
    UID_TO_LABEL[uid] = label
    save_map(UID_TO_LABEL)
    
    # backfill label if currently seen
    for rn, s in STATE.items():
        if s["uid"] and s["uid"].upper() == uid:
            s["label"] = label
    
    return jsonify({"ok": True, "mapped": {uid: label}})

@app.post("/api/clear")
def clear_uid():
    body = request.get_json(force=True)
    uid = (body.get("uid") or "").upper()
    if not uid:
        return jsonify({"error":"uid required"}), 400
    
    removed_label = UID_TO_LABEL.pop(uid, None)
    save_map(UID_TO_LABEL)
    
    # Update current state
    for rn, s in STATE.items():
        if s["uid"] and s["uid"].upper() == uid:
            s["label"] = None
    
    return jsonify({"ok": True, "removed": removed_label})

@app.post("/api/config")
def update_config():
    body = request.get_json(force=True)
    global TABLE_CONFIG
    
    # Update table configuration
    if "table_name" in body:
        TABLE_CONFIG["table_name"] = body["table_name"]
    if "max_players" in body:
        TABLE_CONFIG["max_players"] = body["max_players"]
    
    save_config(TABLE_CONFIG)
    return jsonify({"ok": True, "config": TABLE_CONFIG})

# Legacy endpoints for backward compatibility
@app.get("/state")
def legacy_get_state():
    return get_state()

@app.get("/cards_api")
def legacy_get_cards():
    return get_cards()

@app.post("/map")
def legacy_map_uid():
    return map_uid()

@app.post("/clear")
def legacy_clear_uid():
    return clear_uid()

# --- NTAG read/write endpoints (uses PN532 ntag2xx helpers) ---
def ensure_pn532():
    if pn532 is None:
        return False, jsonify({"error":"PN532 not initialized"}), 503
    return True, None, None

@app.get("/ntag/read")
def ntag_read():
    ok, resp, code = ensure_pn532()
    if not ok: return resp, code
    
    page = int(request.args.get("page", 4))
    if page < 4 or page > 39:
        return jsonify({"error":"page must be between 4 and 39 for NTAG213"}), 400
    
    try:
        # adafruit_pn532 provides ntag2xx_read_block(block)
        data = pn532.ntag2xx_read_block(page)
        # data is bytes-like (4 bytes)
        return jsonify({
            "ok": True,
            "page": page, 
            "data_hex": "".join(f"{b:02X}" for b in data),
            "ascii": ''.join(chr(b) if 32 <= b <= 126 else '.' for b in data)
        })
    except AttributeError:
        return jsonify({"error":"ntag read not supported by this PN532 driver version"}), 501
    except Exception as e:
        return jsonify({"error":"ntag read failed", "detail": str(e)}), 500

@app.post("/ntag/write")
def ntag_write():
    ok, resp, code = ensure_pn532()
    if not ok: return resp, code
    
    body = request.get_json(force=True)
    page = body.get("page")
    data_hex = body.get("data_hex")
    
    if page is None or data_hex is None:
        return jsonify({"error":"page and data_hex required"}), 400
    
    page = int(page)
    if page < 4 or page > 39:
        return jsonify({"error":"page must be between 4 and 39 for NTAG213"}), 400
    
    # data_hex must represent exactly 4 bytes (8 hex chars)
    try:
        data = bytes.fromhex(data_hex)
    except Exception:
        return jsonify({"error":"data_hex must be valid hex"}), 400
    
    if len(data) != 4:
        return jsonify({"error":"data_hex must be exactly 4 bytes (8 hex digits)"}), 400
    
    try:
        pn532.ntag2xx_write_block(page, data)
        return jsonify({
            "ok": True, 
            "page": page, 
            "written_hex": data_hex.upper(),
            "message": "Write successful"
        })
    except AttributeError:
        return jsonify({"error":"ntag write not supported by this PN532 driver version"}), 501
    except Exception as e:
        return jsonify({"error":"ntag write failed", "detail": str(e)}), 500

# Graceful cleanup
@app.route("/shutdown", methods=["POST"])
def shutdown():
    global stop_flag
    stop_flag = True
    time.sleep(POLL_INTERVAL * 2)
    func = request.environ.get("werkzeug.server.shutdown")
    if func:
        func()
    return jsonify({"ok": True})

if __name__ == "__main__":
    try:
        print(f"Starting PN532 Poker Full-Stack Server on http://0.0.0.0:8000/")
        print(f"PN532 Status: {'✓ Connected' if pn532 else '✗ Not available'}")
        print(f"Pages: Table (/) | Config (/config) | Cards (/cards)")
        app.run(host="0.0.0.0", port=8000, debug=False)
    finally:
        stop_flag = True
        time.sleep(POLL_INTERVAL * 2)
