#!/usr/bin/env python3
"""
PN532 12-Reader Poker Server
- Supports 12 PN532 readers via SPI
- 10 player positions + community cards + dealer position
- Dual-card overlay detection for each reader
- Real-time card display and management
"""

import time, json, threading, collections
from pathlib import Path
from flask import Flask, jsonify, request, render_template

# Try to import PN532 libraries
try:
    import board, busio, digitalio
    from adafruit_pn532.spi import PN532_SPI
    PN532_AVAILABLE = True
except ImportError:
    print("PN532 libraries not available - running in demo mode")
    PN532_AVAILABLE = False

# Configuration
MAP_FILE = Path("card_map.json")
CONFIG_FILE = Path("table_config.json")
POLL_INTERVAL = 0.12  # seconds
CARD_STABILITY_TIME = 3.0  # seconds cards must be stable
FOLD_DELAY_TIME = 5.0  # seconds cards must be gone before fold
MAX_HISTORY_SIZE = 50

# Load configuration
def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {"readers": {}}

def load_map():
    if MAP_FILE.exists():
        try:
            return json.loads(MAP_FILE.read_text())
        except Exception:
            return {}
    return {}

def save_map(m):
    MAP_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2))

config = load_config()
UID_TO_LABEL = load_map()
READERS = config.get("readers", {})

# Global state
STATE = {}
CARD_DETECTION_HISTORY = {}
CURRENT_HANDS = {}
LAST_DETECTED_UID = None

# Initialize state for each reader
for name in READERS.keys():
    STATE[name] = {
        "uid": None,
        "label": None,
        "last_seen": None,
        "hand_size": 0,
        "hand_cards": []
    }
    CARD_DETECTION_HISTORY[name] = []
    CURRENT_HANDS[name] = {"cards": [], "last_stable": None, "fold_start": None}

# Initialize PN532 readers
readers = {}
if PN532_AVAILABLE:
    try:
        # Create SPI bus
        spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
        
        # Initialize each reader with its CS pin
        for name, cfg in READERS.items():
            cs_pin = cfg.get("spi_cs")
            if cs_pin:
                if cs_pin in [8, 7]:  # CE0, CE1
                    cs_io = getattr(board, f"CE{cs_pin-8}")
                else:
                    cs_io = digitalio.DigitalInOut(getattr(board, f"D{cs_pin}"))
                
                reader = PN532_SPI(spi, cs_io, debug=False)
                ic, ver, rev, support = reader.firmware_version
                reader.SAM_configuration()
                readers[name] = reader
                print(f"Initialized {name} reader (CS={cs_pin}) - PN532 v{ver}.{rev}")
        
        print(f"Successfully initialized {len(readers)} PN532 readers")
        
    except Exception as e:
        print(f"Failed to initialize PN532 readers: {e}")
        readers = {}
else:
    print("Running in demo mode - no PN532 readers")

# Card detection functions
def uid_hex(uid_bytes):
    if uid_bytes is None:
        return None
    return "".join(f"{b:02X}" for b in uid_bytes)

def up_to_two_cards(pn532, window_ms=450, dwell_ms=40):
    """Detect up to 2 overlapping cards"""
    card_counts = collections.Counter()
    t_end = time.monotonic() + window_ms / 1000
    
    while time.monotonic() < t_end:
        try:
            uid = pn532.read_passive_target(timeout=dwell_ms / 1000)
            if uid:
                card_counts[uid_hex(uid)] += 1
        except Exception:
            pass
    
    return [uid for uid, count in card_counts.most_common(2)]

def process_card_stability(reader_name, current_time):
    """Process card detection history for stability"""
    history = CARD_DETECTION_HISTORY[reader_name]
    current_hand = CURRENT_HANDS[reader_name]
    
    # Get recent detections (last 10 seconds)
    recent_detections = [
        d for d in history 
        if current_time - d["timestamp"] <= 10.0
    ]
    
    if not recent_detections:
        # No recent detections - check for fold
        if current_hand["cards"] and current_hand["fold_start"] is None:
            current_hand["fold_start"] = current_time
        elif current_hand["fold_start"] and (current_time - current_hand["fold_start"]) >= FOLD_DELAY_TIME:
            if current_hand["cards"]:
                print(f"[{reader_name}] FOLD: {[card['label'] for card in current_hand['cards']]}")
                current_hand["cards"] = []
                current_hand["last_stable"] = None
                current_hand["fold_start"] = None
        return
    
    # Reset fold timer
    current_hand["fold_start"] = None
    
    # Find unique cards
    unique_cards = {}
    for detection in recent_detections:
        uid = detection["uid"]
        if uid not in unique_cards:
            unique_cards[uid] = {
                "uid": uid,
                "label": detection["label"],
                "first_seen": detection["timestamp"],
                "last_seen": detection["timestamp"]
            }
        else:
            unique_cards[uid]["last_seen"] = detection["timestamp"]
    
    # Check for stable cards
    stable_cards = []
    for card in unique_cards.values():
        if (current_time - card["first_seen"]) >= CARD_STABILITY_TIME:
            stable_cards.append(card)
    
    stable_cards.sort(key=lambda x: x["uid"])
    
    # Update hand if changed
    current_uids = [card["uid"] for card in current_hand["cards"]]
    stable_uids = [card["uid"] for card in stable_cards]
    
    if stable_uids != current_uids:
        current_hand["cards"] = stable_cards
        current_hand["last_stable"] = current_time
        
        if stable_cards:
            labels = [card["label"] or "unmapped" for card in stable_cards]
            print(f"[{reader_name}] STABLE: {len(stable_cards)} cards: {labels}")
        else:
            print(f"[{reader_name}] CLEARED")
    
    # Update state
    if stable_cards:
        primary_card = stable_cards[0]
        STATE[reader_name].update({
            "uid": primary_card["uid"],
            "label": primary_card["label"],
            "last_seen": current_time,
            "hand_size": len(stable_cards),
            "hand_cards": stable_cards
        })
    else:
        STATE[reader_name].update({
            "uid": None,
            "label": None,
            "last_seen": None,
            "hand_size": 0,
            "hand_cards": []
        })

# Polling loop
stop_flag = False

def poll_loop():
    global LAST_DETECTED_UID
    
    while not stop_flag:
        current_time = time.time()
        
        for reader_name, reader in readers.items():
            try:
                # Detect up to 2 cards
                detected_uids = up_to_two_cards(reader)
                
                # Add to detection history
                for uid in detected_uids:
                    CARD_DETECTION_HISTORY[reader_name].append({
                        "uid": uid,
                        "label": UID_TO_LABEL.get(uid),
                        "timestamp": current_time
                    })
                    
                    # Update last detected UID for auto-capture
                    LAST_DETECTED_UID = uid
                
                # Keep history manageable
                if len(CARD_DETECTION_HISTORY[reader_name]) > MAX_HISTORY_SIZE:
                    CARD_DETECTION_HISTORY[reader_name] = CARD_DETECTION_HISTORY[reader_name][-MAX_HISTORY_SIZE:]
                
                # Process stability
                process_card_stability(reader_name, current_time)
                
            except Exception as e:
                print(f"Error polling {reader_name}: {e}")
        
        time.sleep(POLL_INTERVAL)

# Start polling thread
if readers:
    t = threading.Thread(target=poll_loop, daemon=True)
    t.start()

# Flask app
app = Flask(__name__)

@app.route("/")
def index():
    return render_template("table.html", 
                         table_name=config.get("table_name", "PN532 Poker Table"),
                         readers=READERS)

@app.route("/config")
def config_page():
    return render_template("config.html", 
                         table_name=config.get("table_name", "PN532 Poker Table"),
                         readers=READERS)

@app.route("/cards")
def cards_page():
    return render_template("cards.html", 
                         table_name=config.get("table_name", "PN532 Poker Table"),
                         readers=READERS)

@app.route("/calibration")
def calibration_page():
    return render_template("calibration.html", 
                         table_name=config.get("table_name", "PN532 Poker Table"),
                         readers=READERS)

@app.route("/heads-up")
def heads_up_page():
    return render_template("heads_up_table.html", 
                         table_name=config.get("table_name", "PN532 Poker Table"),
                         readers=READERS)

# API endpoints
@app.get("/api/state")
def get_state():
    return jsonify(STATE)

@app.get("/api/cards")
def get_cards():
    return jsonify(UID_TO_LABEL)

@app.post("/api/map")
def map_uid():
    body = request.get_json(force=True)
    uid = (body.get("uid") or "").upper()
    label = body.get("label")
    
    if not uid or not label:
        return jsonify({"error": "uid and label required"}), 400
    
    UID_TO_LABEL[uid] = label
    save_map(UID_TO_LABEL)
    
    # Update current state
    for reader_state in STATE.values():
        if reader_state["uid"] and reader_state["uid"].upper() == uid:
            reader_state["label"] = label
    
    return jsonify({"ok": True, "mapped": {uid: label}})

@app.post("/api/clear")
def clear_uid():
    body = request.get_json(force=True)
    uid = (body.get("uid") or "").upper()
    
    if not uid:
        return jsonify({"error": "uid required"}), 400
    
    UID_TO_LABEL.pop(uid, None)
    save_map(UID_TO_LABEL)
    
    return jsonify({"ok": True})

@app.get("/api/last_uid")
def get_last_uid():
    return jsonify({"uid": LAST_DETECTED_UID})

@app.get("/api/current_hand")
def get_current_hand():
    # Return main player hand for backward compatibility
    main_hand = CURRENT_HANDS.get("main", {"cards": [], "last_stable": None, "fold_start": None})
    return jsonify({
        "hand_cards": main_hand["cards"],
        "hand_size": len(main_hand["cards"]),
        "last_stable": main_hand["last_stable"],
        "fold_start": main_hand["fold_start"],
        "is_stable": len(main_hand["cards"]) > 0,
        "timestamp": time.time()
    })

@app.get("/api/reader_hands")
def get_reader_hands():
    """Get hands for all readers"""
    hands = {}
    for reader_name, hand in CURRENT_HANDS.items():
        hands[reader_name] = {
            "hand_cards": hand["cards"],
            "hand_size": len(hand["cards"]),
            "last_stable": hand["last_stable"],
            "fold_start": hand["fold_start"],
            "is_stable": len(hand["cards"]) > 0
        }
    return jsonify(hands)

# Calibration API endpoints
@app.get("/api/readers")
def get_readers():
    """Get all reader configurations"""
    return jsonify({
        "readers": READERS,
        "table_name": config.get("table_name", "PN532 Poker Table"),
        "max_players": config.get("max_players", 10)
    })

@app.get("/api/reader/<reader_name>/status")
def get_reader_status(reader_name):
    """Get status of a specific reader"""
    if reader_name not in STATE:
        return jsonify({"error": "Reader not found"}), 404
    
    reader_state = STATE[reader_name]
    return jsonify({
        "reader": reader_name,
        "uid": reader_state.get("uid"),
        "label": reader_state.get("label"),
        "hand_size": reader_state.get("hand_size", 0),
        "hand_cards": reader_state.get("hand_cards", []),
        "last_seen": reader_state.get("last_seen"),
        "is_active": reader_state.get("uid") is not None
    })

@app.get("/api/reader/<reader_name>/test")
def test_reader(reader_name):
    """Test a specific reader for card detection"""
    if reader_name not in pn532_objects:
        return jsonify({"error": "Reader not found"}), 404
    
    try:
        pn532_obj = pn532_objects[reader_name]
        if hasattr(pn532_obj, 'read_passive_target'):
            # Real PN532 reader
            uid = pn532_obj.read_passive_target(timeout=0.5)
            if uid:
                uhex = "".join(f"{x:02X}" for x in uid)
                label = UID_TO_LABEL.get(uhex)
                return jsonify({
                    "success": True,
                    "uid": uhex,
                    "label": label,
                    "message": "Card detected successfully"
                })
            else:
                return jsonify({
                    "success": False,
                    "uid": None,
                    "label": None,
                    "message": "No card detected"
                })
        else:
            # Dummy reader
            return jsonify({
                "success": False,
                "uid": None,
                "label": None,
                "message": "Dummy reader - no hardware connected"
            })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "message": "Reader test failed"
        }), 500

@app.post("/api/calibration/result")
def save_calibration_result():
    """Save calibration result for a reader"""
    data = request.get_json()
    reader_name = data.get("reader")
    result = data.get("result")  # "passed", "failed", "skipped"
    notes = data.get("notes", "")
    
    if not reader_name or not result:
        return jsonify({"error": "Reader name and result required"}), 400
    
    # Store calibration result (you could save this to a file)
    # For now, we'll just return success
    return jsonify({
        "success": True,
        "reader": reader_name,
        "result": result,
        "notes": notes,
        "timestamp": time.time()
    })

if __name__ == "__main__":
    try:
        print(f"Starting PN532 12-Reader Poker Server...")
        print(f"Table: {config.get('table_name', 'Unknown')}")
        print(f"Readers: {len(READERS)} configured")
        print(f"Available: {len(readers)} initialized")
        app.run(host="0.0.0.0", port=8000, debug=False)
    finally:
        stop_flag = True
        time.sleep(POLL_INTERVAL * 2)
