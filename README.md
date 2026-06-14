# Serial Number Reader

Reads a serial number from a camera, showing the live feed on screen and running OCR
only inside a defined box. Two variants:

- **`serial_reader.py`** — **Android** phone as the camera via the *IP Webcam* app
  (network stream). Cross-platform, OCR with EasyOCR.
- **`serial_reader_apple.py`** — **all-Apple** solution: iPhone as *Continuity Camera*
  + OCR with the macOS **Vision** framework. Faster and more accurate, no app and no
  network stream. See [§ Apple version](#apple-version-iphone--vision-ocr).

## 1. Environment setup (Mac)

```bash
cd serial_number_reader
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Android phone as the camera

1. Install the **IP Webcam** app from the Play Store.
2. Open the app → at the bottom, "Start server".
3. At the top you see a URL like `http://192.168.1.50:8080`.
4. The video stream is that URL **+ `/video`** → `http://192.168.1.50:8080/video`.

> The Mac and the phone must be on the same WiFi network.

## 3. Run

```bash
python serial_reader.py --source http://192.168.1.50:8080/video
```

- `q` to quit.
- Frame the serial inside the green box; the recognized text is printed to the console.

## Useful options

| Flag | What it does | Default |
|------|--------------|---------|
| `--roi W,H` | box size (fraction of the frame) | `0.5,0.18` |
| `--every N` | run OCR every N frames (higher = less CPU) | `12` |
| `--min-conf` | minimum confidence (0-1) | `0.95` |
| `--upscale` | ROI upscaling before OCR | `2.0` |
| `--pattern` | regex: print only matches (e.g. `'[A-Z0-9]{6,}'`) | — |
| `--allowlist` | allowed characters (e.g. uppercase + digits only) | — |
| `--mode` | video source: `auto` / `live` / `mjpeg` / `shot` (see below) | `auto` |

Available modes:

| `--mode` | What it does | When |
|----------|--------------|------|
| `auto` | tries the chain `live → mjpeg → shot` with automatic fallback | default, let it decide |
| `live` | only video via OpenCV/FFMPEG (the "first version") | USB webcam or Windows, where OpenCV opens the stream |
| `mjpeg` | only the internal semi-live MJPEG parser (~50-60 fps) | IP Webcam on macOS, smooth streaming |
| `shot` | only `/shot.jpg` snapshot polling (~5-6 fps) | maximum stability if the stream is flaky |

```bash
# semi-live MJPEG, no initial OpenCV attempt
python serial_reader.py --source http://192.168.1.160:8080/video --mode mjpeg

# straight to snapshot
python serial_reader.py --source http://192.168.1.160:8080/video --mode shot
```

> On macOS `live` usually does **not** open the IP Webcam MJPEG stream (OpenCV
> limitation): use `mjpeg` or `auto`. `live` is meant for USB webcams or Windows.

Example with serial-number rules:

```bash
python serial_reader.py --source http://192.168.1.50:8080/video \
  --pattern '[A-Z0-9]{6,}' \
  --allowlist 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
```

## Notes

- **Streaming on macOS:** OpenCV/FFMPEG does not open the IP Webcam multipart MJPEG
  (`/video`). The script then reads it with an internal MJPEG parser
  (`Stream non apribile con OpenCV, uso il lettore MJPEG diretto...`), getting full
  streaming (~50-60 fps) and automatic reconnection when the phone goes idle. If even
  that yields no frames, it falls back to `/shot.jpg` snapshot polling (~5-6 fps). Keep
  the phone screen on / disable power saving to prevent the stream from stalling.
- **Long text not recognized:** EasyOCR returns a single confidence for the whole
  string, so long serials easily drop below `--min-conf 0.95`. Lower the threshold
  (`--min-conf 0.8`) and/or widen the box (`--roi 0.85,0.18`) so the text fits entirely
  inside it.
- Small/tilted text on an eyeglass temple: increase `--upscale` (3.0) and move the
  camera closer so the serial fills the box.
- If EasyOCR isn't enough, the upgrade is **PaddleOCR** (better on small text, has the
  angle classifier) — or use the [Apple version](#apple-version-iphone--vision-ocr),
  generally more accurate on printed text.

## Apple version (iPhone + Vision OCR)

`serial_reader_apple.py` uses the iPhone as a **Continuity Camera** (the Mac's native
webcam) and runs OCR with the macOS **Vision** framework. No network, no app, no EasyOCR.

**Why it's better:** the camera is native (`--source 0/1`, low latency, autofocus, and
**macro** on iPhone Pro for tiny serials); Vision runs on the Neural Engine and is faster
and more accurate than EasyOCR on printed text, without downloading models.

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip            # an old pip won't build the pyobjc wheels
pip install -r requirements-apple.txt
```

### Connecting the iPhone (Continuity Camera)

1. iPhone (iOS 16+) and Mac (macOS Ventura+) on the **same Apple ID**, Wi-Fi + Bluetooth ON.
2. Place the iPhone still, **rear camera** facing the serial (the screen can stay locked).
   It shows up automatically as a camera on the Mac.
3. On first run macOS asks for camera permission for the terminal/Python: grant it.

### Run

```bash
python serial_reader_apple.py --list           # list camera indices
python serial_reader_apple.py --source 1        # the iPhone is usually 0 or 1
python serial_reader_apple.py --source 1 --pattern '[A-Z0-9]{6,}'
```

Same flags as the Android version (`--roi`, `--every`, `--min-conf`, `--upscale`,
`--pattern`), except `--allowlist`/`--mode` which aren't needed here. `--every` can stay
low (default 6) because Vision is fast.
