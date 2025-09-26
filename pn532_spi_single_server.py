#!/usr/bin/env python3
"""
PN532 Poker Single Reader SPI Server

- Single PN532 reader using SPI communication
- Matches user's hardware setup with NSS, MO, MI, SCK pins
- Professional web interface with real-time card detection
- NTAG213 read/write support
"""

import time, json, threading
from pathlib import Path
from flask import Flask, jsonify, request, render_template
from datetime import datetime

# Adafruit PN532 imports
try:
    import board, busio, digitalio
    from adafruit_pn532.spi import PN532_SPI
    PN532_AVAILABLE = True
except ImportError as e:
    print(f"PN532 libraries not available: {e}")
    print("Install with: pip install adafruit-circuitpython-pn532 adafruit-blinka")
    PN532_AVAILABLE = False

# ---------- Config ----------
MAP_FILE = Path("card_map.json")
CONFIG_FILE = Path("table_config.json")
POLL_INTERVAL = 0.12  # seconds

# Default configuration for single reader
DEFAULT_CONFIG = {
    "table_name": "PN532 Poker Table - Single Reader",
    "max_players": 2,
    "readers": {
        "main": {
            "type": "pn532", 
            "position": "Main Player Hand", 
            "spi_cs": 8  # GPIO8 (Pin 24) - NSS/Chip Select
        }
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
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG

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

# Global variables for dual-card overlay detection
LAST_DETECTED_UID = None
CARD_DETECTION_HISTORY = []  # History of recent card detections
CURRENT_HAND = {"cards": [], "last_stable": None, "fold_start": None}

# Configuration for card stability and delays
CARD_STABILITY_TIME = 3.0    # Seconds cards must be stable before showing
FOLD_DELAY_TIME = 5.0        # Seconds cards must be gone before considering folded
MAX_HISTORY_SIZE = 50        # Maximum detection history to keep

# Initialize PN532 (SPI) - Single reader setup
pn532 = None
if PN532_AVAILABLE:
    try:
        # Create SPI bus
        spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
        
        # Get CS pin from config (default GPIO8 for main reader)
        cs_pin = READERS["main"].get("spi_cs", 8)
        if cs_pin == 8:  # CE0
            cs_io = board.CE0
        elif cs_pin == 7:  # CE1
            cs_io = board.CE1
        else:
            cs_io = digitalio.DigitalInOut(getattr(board, f"D{cs_pin}"))
        
        # Initialize PN532 with SPI
        pn532 = PN532_SPI(spi, cs_io, debug=False)
        ic, ver, rev, support = pn532.firmware_version
        print(f"Found PN532 with firmware version {ver}.{rev}")
        pn532.SAM_configuration()
        print(f"PN532 initialized successfully on SPI with CS={cs_pin}!")
        
    except Exception as e:
        print(f"PN532 SPI init failed: {e}")
        print("Check SPI wiring and CS pin configuration")
        pn532 = None
else:
    print("PN532 libraries not installed - running in demo mode")

# Enhanced poll loop with dual-card detection and stability delays
stop_flag = False
def poll_loop():
    global LAST_DETECTED_UID, CARD_DETECTION_HISTORY, CURRENT_HAND
    
    while not stop_flag:
        if pn532:
            try:
                # Try to read a card
                uid = pn532.read_passive_target(timeout=0.1)
                
                if uid:
                    uid_hex_str = "".join(f"{b:02X}" for b in uid)
                    label = UID_TO_LABEL.get(uid_hex_str)
                    
                    # Update state
                    STATE["main"].update({
                        "uid": uid_hex_str,
                        "label": label,
                        "last_seen": time.time()
                    })
                    
                    # Update global last detected UID for auto-capture
                    LAST_DETECTED_UID = uid_hex_str
                    
                    # Add to detection history
                    detection = {
                        "uid": uid_hex_str,
                        "label": label,
                        "timestamp": time.time()
                    }
                    CARD_DETECTION_HISTORY.append(detection)
                    
                    # Keep history size manageable
                    if len(CARD_DETECTION_HISTORY) > MAX_HISTORY_SIZE:
                        CARD_DETECTION_HISTORY = CARD_DETECTION_HISTORY[-MAX_HISTORY_SIZE:]
                    
                    # Dual-card detection logic
                    current_time = time.time()
                    
                    # Check if this is a new card or same card
                    if not CURRENT_HAND["cards"] or uid_hex_str not in [c["uid"] for c in CURRENT_HAND["cards"]]:
                        # New card detected
                        card_info = {"uid": uid_hex_str, "label": label, "first_seen": current_time}
                        CURRENT_HAND["cards"].append(card_info)
                        CURRENT_HAND["last_stable"] = current_time
                        CURRENT_HAND["fold_start"] = None
                        
                        print(f"[main] New card: {uid_hex_str} => {label or 'unmapped'}")
                    else:
                        # Same card, update stability
                        CURRENT_HAND["last_stable"] = current_time
                        CURRENT_HAND["fold_start"] = None
                        
                else:
                    # No card detected
                    if CURRENT_HAND["cards"]:
                        # Cards were present, check if they're gone long enough to fold
                        if CURRENT_HAND["fold_start"] is None:
                            CURRENT_HAND["fold_start"] = time.time()
                        
                        # Check if cards have been gone long enough to consider folded
                        if time.time() - CURRENT_HAND["fold_start"] > FOLD_DELAY_TIME:
                            print(f"[main] Cards folded: {[c['label'] for c in CURRENT_HAND['cards']]}")
                            CURRENT_HAND["cards"] = []
                            CURRENT_HAND["fold_start"] = None
                    
                    # Update state to show no card
                    STATE["main"].update({
                        "uid": None,
                        "label": None,
                        "last_seen": time.time()
                    })
                    LAST_DETECTED_UID = None
                    
            except Exception as e:
                print(f"Card read error: {e}")
                time.sleep(0.1)
        else:
            # Demo mode - simulate card detection
            time.sleep(1.0)
        
        time.sleep(POLL_INTERVAL)

# Start background polling thread
poll_thread = threading.Thread(target=poll_loop, daemon=True)
poll_thread.start()

# Flask app
app = Flask(__name__)

# Routes
@app.route("/")
def index():
    return render_template("table.html", 
                         table_config=TABLE_CONFIG,
                         readers=READERS,
                         state=STATE)

@app.route("/cards")
def cards():
    return render_template("cards.html", 
                         cards=UID_TO_LABEL,
                         full_deck=FULL_DECK)

@app.route("/config")
def config():
    return render_template("config.html", 
                         cards=UID_TO_LABEL,
                         full_deck=FULL_DECK,
                         state=STATE)

@app.route("/heads-up")
def heads_up():
    return render_template("heads_up_table.html", 
                         table_config=TABLE_CONFIG,
                         readers=READERS,
                         state=STATE)

# API Routes
@app.route("/api/state")
def api_state():
    return jsonify(STATE)

@app.route("/api/cards")
def api_cards():
    return jsonify(UID_TO_LABEL)

@app.route("/api/last_uid")
def api_last_uid():
    return jsonify({"uid": LAST_DETECTED_UID})

@app.route("/api/current_hand")
def api_current_hand():
    return jsonify(CURRENT_HAND)

@app.route("/api/detection_history")
def api_detection_history():
    return jsonify(CARD_DETECTION_HISTORY[-20:])  # Last 20 detections

@app.route("/api/current_card_data")
def api_current_card_data():
    """Get detailed data from the currently detected card"""
    if not pn532 or not LAST_DETECTED_UID:
        return jsonify({"error": "No card detected"})
    
    try:
        # Read the card data
        uid = pn532.read_passive_target(timeout=0.1)
        if not uid:
            return jsonify({"error": "Card not detected"})
        
        uid_hex_str = "".join(f"{b:02X}" for b in uid)
        
        # Read NTAG213 data
        card_data = {}
        try:
            # Read pages 4-15 (user memory area)
            for page in range(4, 16):
                try:
                    data = pn532.ntag2xx_read_block(page)
                    if data:
                        card_data[f"page_{page}"] = {
                            "hex": " ".join(f"{b:02X}" for b in data),
                            "ascii": "".join(chr(b) if 32 <= b <= 126 else "." for b in data)
                        }
                except:
                    card_data[f"page_{page}"] = {"hex": "read error", "ascii": "read error"}
        except Exception as e:
            card_data["error"] = str(e)
        
        return jsonify({
            "uid": uid_hex_str,
            "mapped_label": UID_TO_LABEL.get(uid_hex_str),
            "card_data": card_data
        })
        
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/map", methods=["POST"])
def api_map():
    data = request.get_json()
    uid = data.get("uid", "").upper()
    label = data.get("label", "")
    
    if not uid or not label:
        return jsonify({"error": "UID and label required"}), 400
    
    UID_TO_LABEL[uid] = label
    save_map(UID_TO_LABEL)
    
    # Update current state if this UID is currently detected
    for name, state in STATE.items():
        if state["uid"] == uid:
            state["label"] = label
    
    return jsonify({"success": True, "mapped": {uid: label}})

@app.route("/api/clear", methods=["POST"])
def api_clear():
    data = request.get_json()
    uid = data.get("uid", "").upper()
    
    if not uid:
        return jsonify({"error": "UID required"}), 400
    
    if uid in UID_TO_LABEL:
        del UID_TO_LABEL[uid]
        save_map(UID_TO_LABEL)
        
        # Update current state if this UID is currently detected
        for name, state in STATE.items():
            if state["uid"] == uid:
                state["label"] = None
        
        return jsonify({"success": True, "cleared": uid})
    else:
        return jsonify({"success": True, "note": "UID not in map"})

@app.route("/api/write", methods=["POST"])
def api_write():
    """Write data to NTAG213 card"""
    if not pn532:
        return jsonify({"error": "PN532 not available"}), 500
    
    data = request.get_json()
    page = data.get("page", 4)
    data_hex = data.get("data", "")
    
    if not data_hex:
        return jsonify({"error": "Data required"}), 400
    
    try:
        # Convert hex string to bytes
        data_bytes = bytes.fromhex(data_hex.replace(" ", ""))
        
        # Ensure we have 4 bytes
        if len(data_bytes) != 4:
            return jsonify({"error": "Data must be exactly 4 bytes (8 hex chars)"}), 400
        
        # Write to card
        pn532.ntag2xx_write_block(page, data_bytes)
        
        return jsonify({"success": True, "page": page, "data": data_hex})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/read", methods=["GET"])
def api_read():
    """Read data from NTAG213 card"""
    if not pn532:
        return jsonify({"error": "PN532 not available"}), 500
    
    page = request.args.get("page", 4, type=int)
    
    try:
        data = pn532.ntag2xx_read_block(page)
        if data:
            return jsonify({
                "success": True,
                "page": page,
                "data": " ".join(f"{b:02X}" for b in data),
                "ascii": "".join(chr(b) if 32 <= b <= 126 else "." for b in data)
            })
        else:
            return jsonify({"error": "No data read"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("Starting PN532 Poker Server (SPI Single Reader)")
    print(f"Table: {TABLE_CONFIG['table_name']}")
    print(f"Readers: {list(READERS.keys())}")
    print("Web interface: http://0.0.0.0:8000")
    
    try:
        app.run(host="0.0.0.0", port=8000, debug=False)
    except KeyboardInterrupt:
        print("\nShutting down...")
        stop_flag = True
