#!/usr/bin/env python3
"""
PN532 Poker MVP - Professional Flask server with web interface

- Uses PN532 (I2C by default) to read NTAG213 UIDs
- Keeps server-side UID->label mapping in card_map.json
- Professional web interface with real-time updates
- Full NTAG213 read/write support with native PN532 commands
- Scalable architecture for multiple readers
"""

import time, json, threading
from pathlib import Path
from flask import Flask, jsonify, request, render_template_string
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
I2C_ADDR = 0x24       # try 0x24 (common) — change to 0x48 if needed

# Default configuration for expandable poker tables
DEFAULT_CONFIG = {
    "table_name": "PN532 Poker Table Alpha",
    "max_players": 8,
    "readers": {
        "main": {"type": "pn532", "position": "Community Cards", "i2c_addr": 0x24}
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

# Initialize PN532 (I2C)
pn532 = None
if PN532_AVAILABLE:
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        pn532 = PN532_I2C(i2c, addr=I2C_ADDR, debug=False)
        ic, ver, rev, support = pn532.firmware_version
        print(f"Found PN532 firmware {ver}.{rev} (IC {ic})")
        pn532.SAM_configuration()
    except Exception as e:
        print(f"PN532 init failed: {e}")
        print("Check I2C wiring and run 'sudo i2cdetect -y 1' to verify address")
        pn532 = None
else:
    print("PN532 libraries not installed - running in demo mode")

# Poll loop
stop_flag = False
def poll_loop():
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
            print(f"[{reader_name}] {uhex or '(no card)'} {('=> '+label) if label else ''}")
            
        time.sleep(POLL_INTERVAL)

# Start background polling thread
t = threading.Thread(target=poll_loop, daemon=True)
t.start()

app = Flask(__name__)

# Professional Web UI Template
WEB_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ table_name }} - PN532 RFID Poker Management</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #fff;
            min-height: 100vh;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header { text-align: center; margin-bottom: 30px; }
        .header h1 { font-size: 2.5em; margin-bottom: 10px; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }
        .pn532-badge { 
            display: inline-block; 
            background: rgba(76, 175, 80, 0.8); 
            padding: 5px 15px; 
            border-radius: 20px; 
            font-size: 0.8em; 
            margin-top: 10px;
        }
        .status-bar { background: rgba(255,255,255,0.1); padding: 15px; border-radius: 10px; margin-bottom: 30px; }
        .card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .card { 
            background: rgba(255,255,255,0.15); 
            border-radius: 15px; 
            padding: 20px; 
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.2);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        .card:hover { transform: translateY(-5px); box-shadow: 0 10px 30px rgba(0,0,0,0.3); }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .card-title { font-size: 1.2em; font-weight: bold; }
        .card-status { padding: 5px 10px; border-radius: 20px; font-size: 0.8em; }
        .status-active { background: #4CAF50; }
        .status-empty { background: #757575; }
        .card-content { font-size: 1.1em; }
        .card-display { 
            font-size: 2em; 
            font-weight: bold; 
            text-align: center; 
            margin: 10px 0;
            min-height: 60px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(0,0,0,0.2);
            border-radius: 10px;
        }
        .controls { 
            background: rgba(255,255,255,0.1); 
            padding: 25px; 
            border-radius: 15px; 
            margin-bottom: 30px;
        }
        .controls h3 { margin-bottom: 20px; font-size: 1.5em; }
        .form-group { margin-bottom: 15px; }
        .form-row { display: flex; gap: 15px; align-items: end; }
        label { display: block; margin-bottom: 5px; font-weight: 500; }
        input, select, button { 
            padding: 10px 15px; 
            border: none; 
            border-radius: 8px; 
            font-size: 1em;
        }
        input, select { 
            background: rgba(255,255,255,0.9); 
            color: #333;
            flex: 1;
        }
        button { 
            background: #4CAF50; 
            color: white; 
            cursor: pointer; 
            transition: background 0.3s ease;
            min-width: 120px;
        }
        button:hover { background: #45a049; }
        .btn-danger { background: #f44336; }
        .btn-danger:hover { background: #da190b; }
        .btn-pn532 { background: #9C27B0; }
        .btn-pn532:hover { background: #7B1FA2; }
        .deck-selector { 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(60px, 1fr)); 
            gap: 8px; 
            max-height: 200px; 
            overflow-y: auto; 
            padding: 15px;
            background: rgba(0,0,0,0.2);
            border-radius: 8px;
            margin-top: 10px;
        }
        .deck-card { 
            padding: 8px; 
            background: rgba(255,255,255,0.8); 
            color: #333;
            text-align: center; 
            border-radius: 5px; 
            cursor: pointer; 
            transition: all 0.2s ease;
            font-weight: bold;
        }
        .deck-card:hover { background: #4CAF50; color: white; transform: scale(1.05); }
        .deck-card.used { background: #f44336; color: white; cursor: not-allowed; }
        .stats { display: flex; justify-content: space-around; text-align: center; }
        .stat { flex: 1; }
        .stat-number { font-size: 2em; font-weight: bold; }
        .stat-label { font-size: 0.9em; opacity: 0.8; }
        .footer { text-align: center; margin-top: 50px; opacity: 0.7; }
        .results { 
            background: rgba(0,0,0,0.3); 
            padding: 15px; 
            border-radius: 8px; 
            margin-top: 15px; 
            font-family: monospace; 
            font-size: 0.9em; 
            max-height: 300px; 
            overflow-y: auto; 
            display: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎰 {{ table_name }}</h1>
            <p>Professional PN532 RFID Poker Card Management System</p>
            <div class="pn532-badge">🔧 PN532 NFC Module • Native NTAG213 Support</div>
        </div>

        <div class="status-bar">
            <div class="stats">
                <div class="stat">
                    <div class="stat-number" id="activeCards">0</div>
                    <div class="stat-label">Active Cards</div>
                </div>
                <div class="stat">
                    <div class="stat-number" id="totalMapped">0</div>
                    <div class="stat-label">Cards Mapped</div>
                </div>
                <div class="stat">
                    <div class="stat-number" id="totalReaders">{{ readers|length }}</div>
                    <div class="stat-label">PN532 Readers</div>
                </div>
                <div class="stat">
                    <div class="stat-number" id="uptime">00:00:00</div>
                    <div class="stat-label">Uptime</div>
                </div>
            </div>
        </div>

        <div class="card-grid" id="readerGrid">
            <!-- Dynamic reader cards will be inserted here -->
        </div>

        <div class="controls">
            <h3>🃏 Card Management</h3>
            
            <div class="form-group">
                <div class="form-row">
                    <div style="flex: 1;">
                        <label for="mapUid">Card UID:</label>
                        <input type="text" id="mapUid" placeholder="e.g., 04A1B2C3D4" style="text-transform: uppercase;">
                    </div>
                    <div style="flex: 1;">
                        <label for="mapLabel">Card Label:</label>
                        <input type="text" id="mapLabel" placeholder="e.g., A♠ or custom">
                    </div>
                    <div>
                        <button onclick="mapCard()">Map Card</button>
                    </div>
                </div>
            </div>

            <div class="form-group">
                <label>Quick Select from Deck:</label>
                <div class="deck-selector" id="deckSelector">
                    <!-- Deck cards will be populated here -->
                </div>
            </div>

            <div class="form-group">
                <div class="form-row">
                    <div style="flex: 1;">
                        <label for="clearUid">Clear Card UID:</label>
                        <input type="text" id="clearUid" placeholder="UID to remove" style="text-transform: uppercase;">
                    </div>
                    <div>
                        <button class="btn-danger" onclick="clearCard()">Clear Mapping</button>
                    </div>
                </div>
            </div>
        </div>

        <div class="controls">
            <h3>🏷️ PN532 NTAG213 Operations</h3>
            
            <div class="form-group">
                <div class="form-row">
                    <div style="flex: 1;">
                        <label for="ntagPage">Page (4-39):</label>
                        <input type="number" id="ntagPage" min="4" max="39" value="4" placeholder="4">
                    </div>
                    <div>
                        <button class="btn-pn532" onclick="readNtagPage()">Read Page</button>
                    </div>
                </div>
            </div>

            <div class="form-group">
                <div class="form-row">
                    <div style="flex: 2;">
                        <label for="ntagData">Data (8 hex chars = 4 bytes):</label>
                        <input type="text" id="ntagData" placeholder="41434521" maxlength="8" style="text-transform: uppercase;">
                    </div>
                    <div>
                        <button class="btn-pn532" onclick="writeNtagPage()">Write Page</button>
                    </div>
                </div>
            </div>

            <div class="form-group">
                <div class="form-row">
                    <div style="flex: 2;">
                        <label for="cardLabelWrite">Write Card Label to NTAG:</label>
                        <input type="text" id="cardLabelWrite" placeholder="A♠" maxlength="4">
                    </div>
                    <div>
                        <button onclick="writeCardLabel()" style="background: #FF9800;">Write Label</button>
                    </div>
                    <div>
                        <button onclick="readCardLabel()" style="background: #2196F3;">Read Label</button>
                    </div>
                </div>
            </div>

            <div id="ntagResults" class="results">
                <!-- NTAG operation results will appear here -->
            </div>
        </div>

        <div class="footer">
            <p>🎲 Professional PN532 Poker RFID System | Last Updated: <span id="lastUpdate">Never</span></p>
        </div>
    </div>

    <script>
        let startTime = Date.now();
        let usedCards = new Set();

        // Update uptime counter
        function updateUptime() {
            const elapsed = Date.now() - startTime;
            const hours = Math.floor(elapsed / 3600000);
            const minutes = Math.floor((elapsed % 3600000) / 60000);
            const seconds = Math.floor((elapsed % 60000) / 1000);
            document.getElementById('uptime').textContent = 
                `${hours.toString().padStart(2,'0')}:${minutes.toString().padStart(2,'0')}:${seconds.toString().padStart(2,'0')}`;
        }
        setInterval(updateUptime, 1000);

        // Create deck selector
        function createDeckSelector() {
            const deckSelector = document.getElementById('deckSelector');
            const suits = ['♠', '♥', '♦', '♣'];
            const values = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'];
            
            suits.forEach(suit => {
                values.forEach(value => {
                    const card = document.createElement('div');
                    card.className = 'deck-card';
                    card.textContent = value + suit;
                    card.onclick = () => selectDeckCard(value + suit);
                    deckSelector.appendChild(card);
                });
            });
        }

        function selectDeckCard(cardLabel) {
            document.getElementById('mapLabel').value = cardLabel;
        }

        // Update reader display
        function updateReaderDisplay(data) {
            const grid = document.getElementById('readerGrid');
            grid.innerHTML = '';
            
            let activeCount = 0;
            
            Object.entries(data).forEach(([name, info]) => {
                const card = document.createElement('div');
                card.className = 'card';
                
                const isActive = info.uid && info.label;
                if (isActive) activeCount++;
                
                card.innerHTML = `
                    <div class="card-header">
                        <div class="card-title">${info.position || name}</div>
                        <div class="card-status ${isActive ? 'status-active' : 'status-empty'}">
                            ${isActive ? 'ACTIVE' : 'EMPTY'}
                        </div>
                    </div>
                    <div class="card-display">
                        ${info.label || '[ Empty Slot ]'}
                    </div>
                    <div class="card-content">
                        <strong>UID:</strong> ${info.uid || 'None'}<br>
                        <strong>Type:</strong> ${info.type || 'Unknown'}<br>
                        <strong>Last Seen:</strong> ${info.last_seen ? new Date(info.last_seen * 1000).toLocaleTimeString() : 'Never'}
                    </div>
                `;
                
                grid.appendChild(card);
            });
            
            document.getElementById('activeCards').textContent = activeCount;
        }

        // Fetch and update state
        async function updateState() {
            try {
                const [stateRes, cardsRes] = await Promise.all([
                    fetch('/api/state'),
                    fetch('/api/cards')
                ]);
                
                const state = await stateRes.json();
                const cards = await cardsRes.json();
                
                updateReaderDisplay(state);
                document.getElementById('totalMapped').textContent = Object.keys(cards).length;
                document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString();
                
                // Update used cards for deck selector
                usedCards = new Set(Object.values(cards));
                updateDeckSelector();
                
            } catch (error) {
                console.error('Failed to update state:', error);
            }
        }

        function updateDeckSelector() {
            document.querySelectorAll('.deck-card').forEach(card => {
                if (usedCards.has(card.textContent)) {
                    card.classList.add('used');
                } else {
                    card.classList.remove('used');
                }
            });
        }

        // Map card function
        async function mapCard() {
            const uid = document.getElementById('mapUid').value.trim().toUpperCase();
            const label = document.getElementById('mapLabel').value.trim();
            
            if (!uid || !label) {
                alert('Please enter both UID and label');
                return;
            }
            
            try {
                const response = await fetch('/api/map', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ uid, label })
                });
                
                if (response.ok) {
                    document.getElementById('mapUid').value = '';
                    document.getElementById('mapLabel').value = '';
                    updateState();
                } else {
                    const error = await response.json();
                    alert(`Error: ${error.error}`);
                }
            } catch (error) {
                alert(`Network error: ${error.message}`);
            }
        }

        // Clear card function
        async function clearCard() {
            const uid = document.getElementById('clearUid').value.trim().toUpperCase();
            
            if (!uid) {
                alert('Please enter UID to clear');
                return;
            }
            
            try {
                const response = await fetch('/api/clear', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ uid })
                });
                
                if (response.ok) {
                    document.getElementById('clearUid').value = '';
                    updateState();
                } else {
                    const error = await response.json();
                    alert(`Error: ${error.error}`);
                }
            } catch (error) {
                alert(`Network error: ${error.message}`);
            }
        }

        // NTAG213 Functions
        function showNtagResults(title, data) {
            const results = document.getElementById('ntagResults');
            results.innerHTML = `<h4>${title}</h4><pre>${JSON.stringify(data, null, 2)}</pre>`;
            results.style.display = 'block';
        }

        async function readNtagPage() {
            const page = document.getElementById('ntagPage').value;
            
            if (!page) {
                alert('Please enter page number');
                return;
            }
            
            try {
                const response = await fetch(`/ntag/read?page=${page}`);
                const data = await response.json();
                
                if (response.ok) {
                    showNtagResults(`Read Page ${page}`, data);
                } else {
                    alert(`Error: ${data.error}`);
                }
            } catch (error) {
                alert(`Network error: ${error.message}`);
            }
        }

        async function writeNtagPage() {
            const page = parseInt(document.getElementById('ntagPage').value);
            const data = document.getElementById('ntagData').value.trim().toUpperCase();
            
            if (!page || !data) {
                alert('Please fill page and data fields');
                return;
            }
            
            if (data.length !== 8) {
                alert('Data must be exactly 8 hex characters (4 bytes)');
                return;
            }
            
            try {
                const response = await fetch('/ntag/write', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ page: page, data_hex: data })
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    showNtagResults(`Write Page ${page}`, result);
                    document.getElementById('ntagData').value = '';
                } else {
                    alert(`Error: ${result.error}`);
                }
            } catch (error) {
                alert(`Network error: ${error.message}`);
            }
        }

        async function writeCardLabel() {
            const cardLabel = document.getElementById('cardLabelWrite').value.trim();
            
            if (!cardLabel) {
                alert('Please enter card label');
                return;
            }
            
            // Convert to hex (pad to 4 bytes)
            const labelBytes = new TextEncoder().encode(cardLabel);
            const paddedBytes = new Uint8Array(4);
            paddedBytes.set(labelBytes.slice(0, 4));
            const hexData = Array.from(paddedBytes).map(b => b.toString(16).padStart(2, '0')).join('').toUpperCase();
            
            try {
                const response = await fetch('/ntag/write', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ page: 4, data_hex: hexData })
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    showNtagResults(`Write Card Label "${cardLabel}"`, result);
                    document.getElementById('cardLabelWrite').value = '';
                } else {
                    alert(`Error: ${result.error}`);
                }
            } catch (error) {
                alert(`Network error: ${error.message}`);
            }
        }

        async function readCardLabel() {
            try {
                const response = await fetch('/ntag/read?page=4');
                const result = await response.json();
                
                if (response.ok) {
                    // Convert hex back to string
                    const hexData = result.data_hex;
                    const bytes = [];
                    for (let i = 0; i < hexData.length; i += 2) {
                        bytes.push(parseInt(hexData.substr(i, 2), 16));
                    }
                    const label = new TextDecoder().decode(new Uint8Array(bytes)).replace(/\0/g, '');
                    
                    showNtagResults(`Read Card Label: "${label}"`, result);
                    if (label) {
                        document.getElementById('cardLabelWrite').value = label;
                    }
                } else {
                    alert(`Error: ${result.error}`);
                }
            } catch (error) {
                alert(`Network error: ${error.message}`);
            }
        }

        // Initialize
        createDeckSelector();
        updateState();
        setInterval(updateState, 2000); // Update every 2 seconds
    </script>
</body>
</html>
'''

@app.get("/")
def index():
    return render_template_string(WEB_TEMPLATE, 
                                table_name=TABLE_CONFIG["table_name"],
                                readers=READERS)

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

# Legacy endpoints for backward compatibility
@app.get("/state")
def legacy_get_state():
    return get_state()

@app.get("/cards")
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
        print(f"Starting PN532 Poker Server on http://0.0.0.0:8000/")
        print(f"PN532 Status: {'✓ Connected' if pn532 else '✗ Not available'}")
        app.run(host="0.0.0.0", port=8000, debug=False)
    finally:
        stop_flag = True
        time.sleep(POLL_INTERVAL * 2)
