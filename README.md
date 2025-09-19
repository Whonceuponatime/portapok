# RC522 Poker PoC

A semi-rollable proof-of-concept poker table with two RC522 RFID readers and NTAG213 stickers on real cards, driven by a Flask HTTP server on Raspberry Pi.

## Features

- **Professional Web Interface** - Modern, responsive UI with real-time updates
- **Scalable Architecture** - Configurable for multiple readers and poker table layouts
- **Two RC522 readers** on shared SPI bus with unique chip selects (expandable)
- **NTAG213 UID reading** with server-side card mapping
- **Real-time card detection** via background polling threads
- **Complete Deck Management** - Visual deck selector with used card tracking
- **REST API** for card mapping and state monitoring
- **Rollable design** - cloth can fold between reader spots
- **Future-ready** - Easy expansion to full poker tables with player hands

## Hardware Requirements

- Raspberry Pi (3B+/4/5 recommended)
- 2x RC522 RFID reader modules
- NTAG213 stickers/cards
- Jumper wires for connections
- Cloth surface for rollable poker table

## Wiring

Enable SPI first:
```bash
sudo raspi-config
# Interface Options → SPI → Enable → reboot
```

### Shared connections to BOTH readers:
- **3V3** → 3.3V (pin 1)
- **GND** → GND (pin 6)  
- **SCK** → GPIO11/SCLK (pin 23)
- **MOSI** → GPIO10/MOSI (pin 19)
- **MISO** → GPIO9/MISO (pin 21)

### Unique per reader:
- **Reader A (left):**
  - SDA/SS → CE0 (GPIO8, pin 24)
  - RST → GPIO25 (pin 22)
- **Reader B (right):**
  - SDA/SS → CE1 (GPIO7, pin 26)
  - RST → GPIO24 (pin 18)

## Installation

1. Update system and install dependencies:
```bash
sudo apt update
sudo apt install -y python3-pip
```

2. Install Python packages:
```bash
pip3 install -r requirements.txt
```

## Usage

1. **Start the server:**
```bash
python3 poker_mvp_rc522.py
```

2. **Access the Professional Web Interface:**
   - Open browser to `http://<raspberrypi-ip>:8000/`
   - Real-time card monitoring with professional dashboard
   - Interactive deck selector for easy card mapping
   - Live statistics and uptime monitoring

3. **Map cards to labels:**
```bash
# Map first card
curl -X POST http://<pi>:8000/map \
  -H "Content-Type: application/json" \
  -d '{"uid":"04A1B2C3D4","label":"A♠"}'

# Map second card  
curl -X POST http://<pi>:8000/map \
  -H "Content-Type: application/json" \
  -d '{"uid":"0455EE2299FF","label":"K♥"}'
```

4. **Check status:**
```bash
curl http://<pi>:8000/state
curl http://<pi>:8000/cards
```

## API Endpoints

### Card Management
- `GET /` - Professional web interface
- `GET /api/state` - Current UIDs and labels per reader spot
- `GET /api/cards` - Server-side UID to card label mapping
- `POST /api/map` - Map a UID to a card label
- `POST /api/clear` - Remove a UID from the mapping
- `GET /api/config` - Get table configuration
- `POST /api/config` - Update table configuration

### NTAG213 Read/Write Operations
- `GET /api/ntag/read?reader=left&page=4` - Read specific page from NTAG213
- `POST /api/ntag/write` - Write data to NTAG213 page (hex or ASCII)
- `GET /api/ntag/dump?reader=left` - Dump all readable pages
- `POST /api/ntag/write_card` - Write card label to page 4
- `GET /api/ntag/read_card?reader=left` - Read card label from page 4

### Legacy Endpoints (backward compatibility)
- `GET /state`, `GET /cards`, `POST /map`, `POST /clear`

## NTAG213 Read/Write Features ✨

**Full NTAG213 support is now implemented!** This system provides both UID reading and complete on-tag read/write capabilities:

### Web Interface Features
- **Real-time page reading** - Read any page (4-39) from NTAG213 tags
- **Flexible writing** - Write data in hex format or ASCII text
- **Card label management** - Write/read card labels directly to/from tags
- **Memory dumping** - Complete NTAG213 memory dump with formatted display
- **Live results** - All operations show detailed results in the web interface

### Technical Implementation
- **Raw ISO14443A Type-2 commands** - Direct NTAG213 communication
- **CRC_A calculation** - Proper error checking for all operations
- **Page validation** - Safe writing only to user memory (pages 4-39)
- **Dual reader support** - Independent operations on both readers
- **Error handling** - Comprehensive error reporting and validation

### Usage Examples
```bash
# Read page 4 from left reader
curl "http://<pi>:8000/api/ntag/read?reader=left&page=4"

# Write "ACE!" to page 4 on right reader
curl -X POST http://<pi>:8000/api/ntag/write \
  -H "Content-Type: application/json" \
  -d '{"reader":"right","page":4,"data_ascii":"ACE!"}'

# Dump all readable pages
curl "http://<pi>:8000/api/ntag/dump?reader=left"
```

## Next Steps

- Add more readers (one per card spot) with unique CS pins
- Upgrade to PN532 with external antenna for better range
- Add web UI for card management
- Implement game logic and rules engine

## Troubleshooting

- **No cards detected:** Check SPI is enabled and wiring is correct
- **Import errors:** Ensure all dependencies installed with `pip3 install -r requirements.txt`
- **Permission errors:** May need to run with `sudo` for GPIO access
- **Network issues:** Check Pi's IP address with `hostname -I`
