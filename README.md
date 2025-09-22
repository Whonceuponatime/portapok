# PN532 Poker PoC

A professional proof-of-concept poker table with PN532 NFC reader and NTAG213 stickers on real cards, driven by a Flask HTTP server on Raspberry Pi.

## Features

- **Professional Web Interface** - Modern, responsive UI with real-time updates
- **Native PN532 Support** - Superior NFC performance with built-in NTAG213 commands
- **Complete NTAG213 Operations** - Native read/write support without complex CRC calculations
- **Real-time card detection** via optimized I2C polling
- **Complete Deck Management** - Visual deck selector with used card tracking
- **REST API** for card mapping and state monitoring
- **Scalable Architecture** - Ready for multiple PN532 readers
- **Future-ready** - Easy expansion to full poker tables with player hands

## Hardware Requirements

- Raspberry Pi (3B+/4/5 recommended)
- 1x PN532 NFC/RFID module (I2C or SPI)
- NTAG213 stickers/cards
- Jumper wires for connections
- Cloth surface for rollable poker table

**Note:** PN532 provides superior NFC performance compared to RC522, with native NTAG213 support and no complex CRC calculations required.

## Wiring

### PN532 I2C Setup (Recommended)

1. **Set PN532 jumpers for I2C mode:**
   - **SET0** = High (H)
   - **SET1** = Low (L)

2. **Enable I2C on Raspberry Pi:**
```bash
sudo raspi-config
# Interface Options → I2C → Enable → Reboot
```

3. **Wire PN532 to Raspberry Pi:**

| PN532 Pin | Pi Pin | GPIO | Description |
|-----------|--------|------|-------------|
| **VDD/5V** | Pin 2 | 5V | Power (can use 3.3V on some boards) |
| **GND** | Pin 6 | GND | Ground |
| **SDA** | Pin 3 | GPIO2 | I2C Data |
| **SCL** | Pin 5 | GPIO3 | I2C Clock |

4. **Verify PN532 detection:**
```bash
sudo apt install -y i2c-tools
sudo i2cdetect -y 1
```
Look for address `24` or `48`. If not found, check jumpers and wiring.

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
python3 pn532_poker_server.py
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

### PN532 NTAG213 Operations
- `GET /ntag/read?page=4` - Read specific page from NTAG213
- `POST /ntag/write` - Write 4-byte hex data to NTAG213 page
- Native PN532 `ntag2xx_read_block()` and `ntag2xx_write_block()` support
- No complex CRC calculations required

### Legacy Endpoints (backward compatibility)
- `GET /state`, `GET /cards`, `POST /map`, `POST /clear`

## PN532 NTAG213 Features ✨

**Native PN532 NTAG213 support!** Superior to RC522 with built-in NFC commands:

### Web Interface Features
- **Real-time page reading** - Read any page (4-39) from NTAG213 tags
- **Native hex writing** - Write 4-byte hex data directly to pages
- **Card label management** - Write/read card labels with automatic encoding
- **Live results** - All operations show detailed results in the web interface
- **Professional PN532 styling** - Dedicated UI for PN532 operations

### Technical Advantages
- **Native NTAG213 commands** - Uses PN532's built-in `ntag2xx_*` functions
- **No CRC calculations** - PN532 handles all low-level protocol details
- **Superior NFC performance** - Better range and reliability than RC522
- **I2C communication** - Simpler wiring, more reliable than SPI
- **Error handling** - Comprehensive error reporting and validation

### Usage Examples
```bash
# Read page 4
curl "http://<pi>:8000/ntag/read?page=4"

# Write hex data to page 4
curl -X POST http://<pi>:8000/ntag/write \
  -H "Content-Type: application/json" \
  -d '{"page":4,"data_hex":"41434521"}'
```

## Multiple PN532 Reader Setup

The current implementation uses a single PN532 reader. To add multiple PN532 readers:

### Option 1: Multiple I2C Addresses
Some PN532 boards support address selection:
- Use PN532 boards with different I2C addresses (0x24, 0x48)
- Connect multiple readers to the same I2C bus
- Update code to poll multiple addresses

### Option 2: I2C Multiplexer
Use an I2C multiplexer (like TCA9548A) for more readers:
- Connect multiplexer to Pi's I2C bus
- Each PN532 on a separate multiplexer channel
- Switch channels to access different readers

### Option 3: Multiple I2C Buses
Use Pi's multiple I2C interfaces:
- I2C0 (GPIO0/1) and I2C1 (GPIO2/3)
- Some Pi models have additional I2C buses
- Each bus can have multiple PN532s with different addresses

### Option 4: Hybrid Setup
Mix PN532 (I2C) with other NFC readers:
- PN532 for primary positions (better performance)
- Additional readers on SPI or UART
- Unified software interface

## Next Steps

- Implement chosen multiple reader approach
- Upgrade to PN532 with external antenna for better range  
- Add game logic and rules engine
- Scale to full poker table with player positions

## Troubleshooting

- **No cards detected:** 
  - Check I2C is enabled: `sudo raspi-config`
  - Verify PN532 detection: `sudo i2cdetect -y 1`
  - Check PN532 jumpers for I2C mode (SET0=H, SET1=L)
  - Verify wiring: VDD, GND, SDA, SCL
- **Import errors:** Install dependencies: `pip3 install -r requirements.txt`
- **PN532 init failed:** 
  - Try different I2C address (change `I2C_ADDR = 0x48` in code)
  - Check power supply (5V recommended)
  - Verify jumper settings
- **NTAG operations fail:** Update library: `pip3 install --upgrade adafruit-circuitpython-pn532`
- **Network issues:** Check Pi's IP address with `hostname -I`
