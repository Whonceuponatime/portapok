#!/usr/bin/env python3
import binascii, json, threading, time
from pathlib import Path
from flask import Flask, jsonify, request, render_template_string
from datetime import datetime
import struct
import RPi.GPIO as GPIO
from mfrc522 import SimpleMFRC522, MFRC522

# ---------- Config ----------
MAP_FILE = Path("card_map.json")   # UID -> card data
CONFIG_FILE = Path("table_config.json")   # Table configuration
POLL_INTERVAL = 0.1  # seconds

# Default configuration for expandable poker tables
DEFAULT_CONFIG = {
    "table_name": "Poker Table Alpha",
    "max_players": 8,
    "readers": {
        "left":  {"bus": 0, "device": 0, "position": "Community Card 1", "type": "community"},
        "right": {"bus": 0, "device": 1, "position": "Community Card 2", "type": "community"}
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
        return json.loads(MAP_FILE.read_text())
    return {}

def save_map(m): 
    MAP_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2))

def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return DEFAULT_CONFIG.copy()

def save_config(config):
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2))

# NTAG213 Utility Functions
def crc_a(data):
    """Calculate ISO14443A CRC_A for NTAG213 commands"""
    crc = 0x6363
    for byte in data:
        byte ^= crc & 0xFF
        byte ^= (byte << 4) & 0xFF
        crc = ((crc >> 8) ^ (byte << 8) ^ (byte << 3) ^ (byte >> 4)) & 0xFFFF
    return crc & 0xFFFF

def ntag213_read_page(reader_name, page):
    """Read a page (4 bytes) from NTAG213 using raw commands"""
    if reader_name not in raw_readers:
        return None, "Reader not found"
    
    try:
        reader = raw_readers[reader_name]
        
        # NTAG213 READ command: 0x30 + page + CRC_A
        cmd = [0x30, page]
        crc = crc_a(cmd)
        cmd.extend([crc & 0xFF, (crc >> 8) & 0xFF])
        
        # Send command and get response
        (status, back_data) = reader.MFRC522_ToCard(reader.PCD_TRANSCEIVE, cmd)
        
        if status == reader.MI_OK and len(back_data) >= 4:
            # NTAG213 returns 16 bytes (4 pages) but we only need the first 4
            return back_data[:4], None
        else:
            return None, f"Read failed: status={status}, data_len={len(back_data) if back_data else 0}"
            
    except Exception as e:
        return None, f"Exception: {str(e)}"

def ntag213_write_page(reader_name, page, data):
    """Write 4 bytes to a page on NTAG213 using raw commands"""
    if reader_name not in raw_readers:
        return False, "Reader not found"
    
    if len(data) != 4:
        return False, "Data must be exactly 4 bytes"
    
    # Check if page is in writable range (pages 4-39 for NTAG213)
    if page < 4 or page > 39:
        return False, f"Page {page} is not writable (use pages 4-39)"
    
    try:
        reader = raw_readers[reader_name]
        
        # NTAG213 WRITE command: 0xA2 + page + 4 data bytes + CRC_A
        cmd = [0xA2, page] + list(data)
        crc = crc_a(cmd)
        cmd.extend([crc & 0xFF, (crc >> 8) & 0xFF])
        
        # Send command and get response
        (status, back_data) = reader.MFRC522_ToCard(reader.PCD_TRANSCEIVE, cmd)
        
        if status == reader.MI_OK:
            # NTAG213 should respond with ACK (0x0A) for successful write
            if back_data and len(back_data) >= 1 and back_data[0] == 0x0A:
                return True, "Write successful"
            else:
                return False, f"Write failed: unexpected response {back_data}"
        else:
            return False, f"Write failed: status={status}"
            
    except Exception as e:
        return False, f"Exception: {str(e)}"

def format_hex_string(data):
    """Format byte array as hex string"""
    return ''.join(f'{b:02X}' for b in data)

def parse_hex_string(hex_str):
    """Parse hex string to byte array"""
    hex_str = hex_str.replace(' ', '').replace(':', '').upper()
    if len(hex_str) % 2 != 0:
        return None, "Hex string must have even length"
    
    try:
        return bytes.fromhex(hex_str), None
    except ValueError as e:
        return None, f"Invalid hex string: {str(e)}"

# Initialize data
UID_TO_CARD = load_map()
TABLE_CONFIG = load_config()
READERS = TABLE_CONFIG["readers"]
STATE = {name: {
    "uid": None, 
    "label": None, 
    "last_seen": None, 
    "position": cfg.get("position", name),
    "type": cfg.get("type", "unknown")
} for name, cfg in READERS.items()}

# Initialize readers
# Note: Standard mfrc522 library only supports one SPI device at a time
# For multiple readers, you'll need one of these approaches:
# 1. Use a library like 'pi-rc522' that supports multiple SPI devices
# 2. Use GPIO multiplexing to switch between readers
# 3. Use separate Pi GPIO pins for each reader's reset/CS lines
# 4. Use I2C-to-SPI bridges for additional readers
#
# Current implementation: Single reader mapped to all configured positions
# This allows testing the full web interface with one physical reader
readers = {}
raw_readers = {}

print("Initializing RFID readers...")

# For now, initialize only the first reader (left) as the standard library doesn't support multiple SPI devices
# This can be expanded later with a library that supports multiple readers
try:
    # Create SimpleMFRC522 for UID detection (uses default SPI settings)
    simple_reader = SimpleMFRC522()
    
    # Create raw MFRC522 for NTAG213 operations (uses default SPI settings)
    raw_reader = MFRC522()
    
    # Map both configured readers to the same physical reader for now
    # This allows the web interface to work while we use a single reader
    for name in READERS.keys():
        readers[name] = simple_reader
        raw_readers[name] = raw_reader
        print(f"Mapped {name} reader to physical RC522 (SPI default)")
    
    print(f"Successfully initialized RC522 reader(s)")
    
except Exception as e:
    print(f"Failed to initialize RC522 reader: {e}")
    print("Make sure SPI is enabled and RC522 is properly connected")
    # Create dummy readers to prevent crashes
    class DummyReader:
        def read_no_block(self):
            return None, None
        def MFRC522_ToCard(self, command, data):
            return None, None
        @property
        def MI_OK(self):
            return 0
        @property
        def PCD_TRANSCEIVE(self):
            return 0
    
    dummy = DummyReader()
    for name in READERS.keys():
        readers[name] = dummy
        raw_readers[name] = dummy
    print("Using dummy readers - RFID functionality disabled")

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

# Professional Web UI Template
WEB_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ table_name }} - RFID Poker Management</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: #fff;
            min-height: 100vh;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header { text-align: center; margin-bottom: 30px; }
        .header h1 { font-size: 2.5em; margin-bottom: 10px; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }
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
        .card-header { display: flex; justify-content: between; align-items: center; margin-bottom: 15px; }
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
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎰 {{ table_name }}</h1>
            <p>Professional RFID Poker Card Management System</p>
            <div style="background: rgba(255,165,0,0.2); padding: 10px; border-radius: 8px; margin-top: 15px; border: 1px solid rgba(255,165,0,0.4);">
                <small>📍 <strong>Single Reader Mode:</strong> All positions currently map to one physical RC522 reader. 
                See documentation for multiple reader setup options.</small>
            </div>
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
                    <div class="stat-label">Card Readers</div>
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
            <h3>🏷️ NTAG213 Read/Write Operations</h3>
            
            <div class="form-group">
                <div class="form-row">
                    <div style="flex: 1;">
                        <label for="ntagReader">Reader:</label>
                        <select id="ntagReader">
                            <option value="">Select Reader</option>
                            <option value="left">Left Reader</option>
                            <option value="right">Right Reader</option>
                        </select>
                    </div>
                    <div style="flex: 1;">
                        <label for="ntagPage">Page (4-39):</label>
                        <input type="number" id="ntagPage" min="4" max="39" value="4" placeholder="4">
                    </div>
                    <div>
                        <button onclick="readNtagPage()">Read Page</button>
                    </div>
                </div>
            </div>

            <div class="form-group">
                <div class="form-row">
                    <div style="flex: 2;">
                        <label for="ntagData">Data (Hex or ASCII):</label>
                        <input type="text" id="ntagData" placeholder="41434521 or ACE!" maxlength="8">
                    </div>
                    <div>
                        <label for="ntagFormat">Format:</label>
                        <select id="ntagFormat">
                            <option value="ascii">ASCII</option>
                            <option value="hex">Hex</option>
                        </select>
                    </div>
                    <div>
                        <button onclick="writeNtagPage()">Write Page</button>
                    </div>
                </div>
            </div>

            <div class="form-group">
                <div class="form-row">
                    <div style="flex: 2;">
                        <label for="cardLabelWrite">Write Card Label to Tag:</label>
                        <input type="text" id="cardLabelWrite" placeholder="A♠" maxlength="4">
                    </div>
                    <div>
                        <button onclick="writeCardLabel()" style="background: #FF9800;">Write to Tag</button>
                    </div>
                    <div>
                        <button onclick="readCardLabel()" style="background: #2196F3;">Read from Tag</button>
                    </div>
                </div>
            </div>

            <div class="form-group">
                <button onclick="dumpNtag()" style="background: #9C27B0; width: 100%;">Dump All Pages</button>
            </div>

            <div id="ntagResults" style="background: rgba(0,0,0,0.3); padding: 15px; border-radius: 8px; margin-top: 15px; font-family: monospace; font-size: 0.9em; max-height: 300px; overflow-y: auto; display: none;">
                <!-- NTAG operation results will appear here -->
            </div>
        </div>

        <div class="footer">
            <p>🎲 Professional Poker RFID System | Last Updated: <span id="lastUpdate">Never</span></p>
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
            const reader = document.getElementById('ntagReader').value;
            const page = document.getElementById('ntagPage').value;
            
            if (!reader || !page) {
                alert('Please select reader and page');
                return;
            }
            
            try {
                const response = await fetch(`/api/ntag/read?reader=${reader}&page=${page}`);
                const data = await response.json();
                
                if (response.ok) {
                    showNtagResults(`Read Page ${page} from ${reader}`, data);
                } else {
                    alert(`Error: ${data.error}`);
                }
            } catch (error) {
                alert(`Network error: ${error.message}`);
            }
        }

        async function writeNtagPage() {
            const reader = document.getElementById('ntagReader').value;
            const page = parseInt(document.getElementById('ntagPage').value);
            const data = document.getElementById('ntagData').value;
            const format = document.getElementById('ntagFormat').value;
            
            if (!reader || !page || !data) {
                alert('Please fill all fields');
                return;
            }
            
            const payload = {
                reader: reader,
                page: page
            };
            
            if (format === 'hex') {
                payload.data_hex = data;
            } else {
                payload.data_ascii = data;
            }
            
            try {
                const response = await fetch('/api/ntag/write', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    showNtagResults(`Write Page ${page} to ${reader}`, result);
                    document.getElementById('ntagData').value = '';
                } else {
                    alert(`Error: ${result.error}`);
                }
            } catch (error) {
                alert(`Network error: ${error.message}`);
            }
        }

        async function writeCardLabel() {
            const reader = document.getElementById('ntagReader').value;
            const cardLabel = document.getElementById('cardLabelWrite').value;
            
            if (!reader || !cardLabel) {
                alert('Please select reader and enter card label');
                return;
            }
            
            try {
                const response = await fetch('/api/ntag/write_card', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reader: reader, card_label: cardLabel })
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    showNtagResults(`Write Card Label "${cardLabel}" to ${reader}`, result);
                    document.getElementById('cardLabelWrite').value = '';
                } else {
                    alert(`Error: ${result.error}`);
                }
            } catch (error) {
                alert(`Network error: ${error.message}`);
            }
        }

        async function readCardLabel() {
            const reader = document.getElementById('ntagReader').value;
            
            if (!reader) {
                alert('Please select reader');
                return;
            }
            
            try {
                const response = await fetch(`/api/ntag/read_card?reader=${reader}`);
                const result = await response.json();
                
                if (response.ok) {
                    showNtagResults(`Read Card Label from ${reader}`, result);
                    if (result.card_label) {
                        document.getElementById('cardLabelWrite').value = result.card_label;
                    }
                } else {
                    alert(`Error: ${result.error}`);
                }
            } catch (error) {
                alert(`Network error: ${error.message}`);
            }
        }

        async function dumpNtag() {
            const reader = document.getElementById('ntagReader').value;
            
            if (!reader) {
                alert('Please select reader');
                return;
            }
            
            try {
                showNtagResults(`Dumping ${reader}...`, { status: 'Reading all pages...' });
                
                const response = await fetch(`/api/ntag/dump?reader=${reader}`);
                const result = await response.json();
                
                if (response.ok) {
                    // Format dump data for better display
                    let formatted = `NTAG213 Memory Dump - ${reader.toUpperCase()}\n`;
                    formatted += `Total Pages: ${result.total_pages}\n\n`;
                    
                    for (let page = 0; page < 40; page++) {
                        if (result.pages[page]) {
                            const pageData = result.pages[page];
                            formatted += `Page ${page.toString().padStart(2, '0')}: ${pageData.hex} | ${pageData.ascii}\n`;
                        } else {
                            formatted += `Page ${page.toString().padStart(2, '0')}: [UNREADABLE]\n`;
                        }
                    }
                    
                    if (result.errors.length > 0) {
                        formatted += `\nErrors:\n${result.errors.join('\n')}`;
                    }
                    
                    showNtagResults(`NTAG213 Dump - ${reader}`, { formatted_dump: formatted, raw_data: result });
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
    out = {}
    for name, s in STATE.items():
        out[name] = {
            "uid": s["uid"],
            "label": s["label"],
            "last_seen": s["last_seen"],
            "position": s["position"],
            "type": s["type"]
        }
    return jsonify(out)

@app.get("/api/cards")
def get_cards():
    return jsonify(UID_TO_CARD)

@app.get("/api/config")
def get_config():
    return jsonify(TABLE_CONFIG)

@app.get("/api/deck")
def get_deck():
    return jsonify({"cards": FULL_DECK, "used": list(UID_TO_CARD.values())})

@app.post("/api/map")
def map_uid():
    body = request.get_json(force=True)
    uid = body.get("uid")
    label = body.get("label")
    if not uid or not label:
        return jsonify({"error":"uid and label required"}), 400
    
    # Check if card is already mapped to prevent duplicates
    if label in UID_TO_CARD.values():
        return jsonify({"error": f"Card {label} is already mapped to another UID"}), 400
    
    UID_TO_CARD[uid.upper()] = label
    save_map(UID_TO_CARD)
    
    # back-fill current state
    for name, s in STATE.items():
        if s["uid"] and s["uid"].upper() == uid.upper():
            s["label"] = label
    
    return jsonify({"ok": True, "mapped": {uid.upper(): label}})

@app.post("/api/clear")
def clear_uid():
    body = request.get_json(force=True)
    uid = body.get("uid")
    if not uid: return jsonify({"error":"uid required"}), 400
    
    removed_label = UID_TO_CARD.pop(uid.upper(), None)
    if removed_label is None:
        return jsonify({"ok": True, "note":"uid not in map"})
    
    save_map(UID_TO_CARD)
    
    # Update current state
    for name, s in STATE.items():
        if s["uid"] and s["uid"].upper() == uid.upper():
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

# Legacy API endpoints for backward compatibility
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

# ----------- NTAG213 Read/Write Operations -----------
@app.get("/api/ntag/read")
def ntag_read():
    """Read data from NTAG213 page"""
    reader_name = request.args.get('reader')
    page = request.args.get('page', type=int)
    
    if not reader_name or page is None:
        return jsonify({"error": "reader and page parameters required"}), 400
    
    if reader_name not in READERS:
        return jsonify({"error": f"Reader '{reader_name}' not found"}), 400
    
    data, error = ntag213_read_page(reader_name, page)
    
    if error:
        return jsonify({"error": error}), 500
    
    return jsonify({
        "ok": True,
        "reader": reader_name,
        "page": page,
        "data": list(data),
        "hex": format_hex_string(data),
        "ascii": ''.join(chr(b) if 32 <= b <= 126 else '.' for b in data)
    })

@app.post("/api/ntag/write")
def ntag_write():
    """Write data to NTAG213 page"""
    body = request.get_json(force=True)
    reader_name = body.get('reader')
    page = body.get('page')
    data_hex = body.get('data_hex')
    data_ascii = body.get('data_ascii')
    
    if not reader_name or page is None:
        return jsonify({"error": "reader and page required"}), 400
    
    if reader_name not in READERS:
        return jsonify({"error": f"Reader '{reader_name}' not found"}), 400
    
    # Parse data from hex or ASCII
    if data_hex:
        data, error = parse_hex_string(data_hex)
        if error:
            return jsonify({"error": error}), 400
    elif data_ascii:
        data = data_ascii.encode('utf-8')
    else:
        return jsonify({"error": "Either data_hex or data_ascii required"}), 400
    
    # Pad or truncate to 4 bytes
    if len(data) < 4:
        data = data + b'\x00' * (4 - len(data))
    elif len(data) > 4:
        data = data[:4]
    
    success, message = ntag213_write_page(reader_name, page, data)
    
    if not success:
        return jsonify({"error": message}), 500
    
    return jsonify({
        "ok": True,
        "reader": reader_name,
        "page": page,
        "data": list(data),
        "hex": format_hex_string(data),
        "message": message
    })

@app.get("/api/ntag/dump")
def ntag_dump():
    """Dump all readable pages from NTAG213"""
    reader_name = request.args.get('reader')
    
    if not reader_name:
        return jsonify({"error": "reader parameter required"}), 400
    
    if reader_name not in READERS:
        return jsonify({"error": f"Reader '{reader_name}' not found"}), 400
    
    dump_data = {}
    errors = []
    
    # Read all pages (0-39 for NTAG213, but some may be protected)
    for page in range(40):
        data, error = ntag213_read_page(reader_name, page)
        if data:
            dump_data[page] = {
                "data": list(data),
                "hex": format_hex_string(data),
                "ascii": ''.join(chr(b) if 32 <= b <= 126 else '.' for b in data)
            }
        else:
            errors.append(f"Page {page}: {error}")
    
    return jsonify({
        "ok": True,
        "reader": reader_name,
        "pages": dump_data,
        "errors": errors,
        "total_pages": len(dump_data)
    })

@app.post("/api/ntag/write_card")
def ntag_write_card():
    """Write card label to NTAG213 user memory (page 4)"""
    body = request.get_json(force=True)
    reader_name = body.get('reader')
    card_label = body.get('card_label', '')
    
    if not reader_name:
        return jsonify({"error": "reader required"}), 400
    
    if reader_name not in READERS:
        return jsonify({"error": f"Reader '{reader_name}' not found"}), 400
    
    # Write card label to page 4 (first user memory page)
    data = card_label.encode('utf-8')
    if len(data) < 4:
        data = data + b'\x00' * (4 - len(data))
    elif len(data) > 4:
        data = data[:4]
    
    success, message = ntag213_write_page(reader_name, 4, data)
    
    if not success:
        return jsonify({"error": message}), 500
    
    return jsonify({
        "ok": True,
        "reader": reader_name,
        "page": 4,
        "card_label": card_label,
        "data": list(data),
        "hex": format_hex_string(data),
        "message": message
    })

@app.get("/api/ntag/read_card")
def ntag_read_card():
    """Read card label from NTAG213 user memory (page 4)"""
    reader_name = request.args.get('reader')
    
    if not reader_name:
        return jsonify({"error": "reader parameter required"}), 400
    
    if reader_name not in READERS:
        return jsonify({"error": f"Reader '{reader_name}' not found"}), 400
    
    data, error = ntag213_read_page(reader_name, 4)
    
    if error:
        return jsonify({"error": error}), 500
    
    # Convert to string, removing null bytes
    card_label = data.rstrip(b'\x00').decode('utf-8', errors='ignore')
    
    return jsonify({
        "ok": True,
        "reader": reader_name,
        "page": 4,
        "card_label": card_label,
        "data": list(data),
        "hex": format_hex_string(data)
    })
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
