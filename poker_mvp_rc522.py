#!/usr/bin/env python3
import binascii, json, threading, time
from pathlib import Path
from flask import Flask, jsonify, request
import RPi.GPIO as GPIO
from mfrc522 import SimpleMFRC522

# ---------- Config ----------
MAP_FILE = Path("card_map.json")   # UID -> "A♠", "K♥", ...
READERS = {
    "left":  {"bus": 0, "device": 0},  # CE0
    "right": {"bus": 0, "device": 1},  # CE1
}
POLL_INTERVAL = 0.1  # seconds
# ----------------------------

# Load/save mapping
def load_map():
    if MAP_FILE.exists():
        return json.loads(MAP_FILE.read_text())
    return {}
def save_map(m): MAP_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2))

UID_TO_CARD = load_map()
STATE = {name: {"uid": None, "label": None, "last_seen": None} for name in READERS}

# Create one SimpleMFRC522 per reader (bind to SPI bus/device)
readers = {name: SimpleMFRC522(bus=cfg["bus"], device=cfg["device"]) for name, cfg in READERS.items()}

stop_flag = False

def uid_hex(val):
    if val is None: return None
    # SimpleMFRC522 returns integer UID for RC522; convert to hex like 04A1B2C3D4
    # 4-byte or 7-byte UIDs get squashed into int; represent as big-endian hex
    h = f"{val:X}"
    if len(h) % 2: h = "0" + h
    return h.upper()

def poll_loop(name, reader):
    global stop_flag
    last = None
    while not stop_flag:
        try:
            uid, _ = reader.read_no_block()  # returns (uid:int or None, text)
        except Exception:
            uid = None  # ignore transient read errors
        uhex = uid_hex(uid)
        if uhex != last:
            last = uhex
            label = UID_TO_CARD.get(uhex) if uhex else None
            STATE[name].update({"uid": uhex, "label": label, "last_seen": time.time()})
            print(f"[{name}] {uhex or '(no card)'}  {('=> '+label) if label else ''}")
        time.sleep(POLL_INTERVAL)

# Start background polling threads
threads = []
for name, rdr in readers.items():
    t = threading.Thread(target=poll_loop, args=(name, rdr), daemon=True)
    t.start()
    threads.append(t)

app = Flask(__name__)

@app.get("/")
def index():
    return jsonify({
        "message": "RC522 Poker MVP running",
        "readers": list(READERS.keys()),
        "endpoints": {
            "GET /state": "current UIDs per spot",
            "GET /cards": "server-side UID->label map",
            "POST /map": {"uid":"04A1B2C3D4", "label":"A♠"},
            "POST /clear": {"uid":"04A1B2C3D4"},
            # ADVANCED (optional, see code comments):
            "POST /ntag/write": {"reader":"left","page":4,"data_hex":"41434521"},
            "GET /ntag/read": {"reader":"left","page":4}
        }
    })

@app.get("/state")
def get_state():
    out = {}
    for name, s in STATE.items():
        out[name] = {
            "uid": s["uid"],
            "label": s["label"],
            "last_seen": s["last_seen"]
        }
    return jsonify(out)

@app.get("/cards")
def get_cards():
    return jsonify(UID_TO_CARD)

@app.post("/map")
def map_uid():
    body = request.get_json(force=True)
    uid = body.get("uid")
    label = body.get("label")
    if not uid or not label:
        return jsonify({"error":"uid and label required"}), 400
    UID_TO_CARD[uid.upper()] = label
    save_map(UID_TO_CARD)
    # back-fill current state
    for name, s in STATE.items():
        if s["uid"] and s["uid"].upper() == uid.upper():
            s["label"] = label
    return jsonify({"ok": True, "mapped": {uid.upper(): label}})

@app.post("/clear")
def clear_uid():
    body = request.get_json(force=True)
    uid = body.get("uid")
    if not uid: return jsonify({"error":"uid required"}), 400
    if UID_TO_CARD.pop(uid.upper(), None) is None:
        return jsonify({"ok": True, "note":"uid not in map"})
    save_map(UID_TO_CARD)
    return jsonify({"ok": True})

# ----------- OPTIONAL: raw NTAG213 read/write (advanced) -----------
# Many RC522 Python libs are Classic-oriented. If your library exposes
# low-level transceive + CRC_A, you can implement ISO14443A Type 2 ops.
# The endpoints below are stubs that return 501 by default.
# If you switch to a PN532 later, use its library for easy NTAG writes.

@app.get("/ntag/read")
def ntag_read():
    return jsonify({"error":"Not implemented in this MVP. RC522 libraries vary for NTAG. Use UID mapping or switch to PN532 for easy on-tag read/write."}), 501

@app.post("/ntag/write")
def ntag_write():
    return jsonify({"error":"Not implemented in this MVP. RC522 on-tag writes require raw Type-2 0xA2; enable only if your lib supports it."}), 501
# -------------------------------------------------------------------

def cleanup():
    global stop_flag
    stop_flag = True
    time.sleep(POLL_INTERVAL * 2)
    GPIO.cleanup()

if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", port=8000, debug=False)
    finally:
        cleanup()
