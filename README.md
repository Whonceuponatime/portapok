# RC522 Poker PoC

A semi-rollable proof-of-concept poker table with two RC522 RFID readers and NTAG213 stickers on real cards, driven by a Flask HTTP server on Raspberry Pi.

## Features

- **Two RC522 readers** on shared SPI bus with unique chip selects
- **NTAG213 UID reading** with server-side card mapping
- **Real-time card detection** via background polling threads
- **REST API** for card mapping and state monitoring
- **Rollable design** - cloth can fold between the two reader spots

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

2. **Access the API:**
   - Open browser to `http://<raspberrypi-ip>:8000/`
   - View current state: `GET /state`
   - View card mappings: `GET /cards`

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

- `GET /` - API documentation and available endpoints
- `GET /state` - Current UIDs and labels per reader spot
- `GET /cards` - Server-side UID to card label mapping
- `POST /map` - Map a UID to a card label
- `POST /clear` - Remove a UID from the mapping
- `GET /ntag/read` - (Not implemented) Raw NTAG213 page read
- `POST /ntag/write` - (Not implemented) Raw NTAG213 page write

## Advanced: On-Tag Writing

This MVP focuses on **UID reading + server-side mapping** for maximum reliability. For on-tag writes:

### Option 1: Use your phone
- Install "NFC Tools" app
- Write small strings to NTAG213 page 4 (first user memory)
- RC522 still reads UIDs; server doesn't need on-tag data

### Option 2: Raw RC522 writes (advanced)
- Requires RC522 library with `transceive` + `CRC_A` support
- Implement ISO14443A Type-2 operations:
  - READ: `30 <page> CRC_A`
  - WRITE: `A2 <page> d0 d1 d2 d3 CRC_A`
- Only write pages 4–39 on NTAG213 (user memory)

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
