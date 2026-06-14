# Serial Number Reader

Legge un seriale dalla fotocamera, mostrando il feed a schermo e facendo OCR solo
dentro un riquadro definito. Due varianti:

- **`serial_reader.py`** — telefono **Android** come telecamera via app *IP Webcam*
  (stream su rete). Multipiattaforma, OCR con EasyOCR.
- **`serial_reader_apple.py`** — soluzione **tutta Apple**: iPhone come *Continuity
  Camera* + OCR con il framework **Vision** di macOS. Più veloce e preciso, nessuna
  app né stream di rete. Vedi [§ Versione Apple](#versione-apple-iphone--vision-ocr).

## 1. Setup ambiente (Mac)

```bash
cd serial_number_reader
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Telefono Android come telecamera

1. Installa l'app **IP Webcam** dal Play Store.
2. Apri l'app → in fondo "Start server".
3. In alto vedi un URL tipo `http://192.168.1.50:8080`.
4. Lo stream video è quell'URL **+ `/video`** → `http://192.168.1.50:8080/video`.

> Mac e telefono devono essere sulla stessa rete WiFi.

## 3. Avvio

```bash
python serial_reader.py --source http://192.168.1.50:8080/video
```

- `q` per uscire.
- Inquadra il seriale dentro il riquadro verde; il testo riconosciuto compare in console.

## Opzioni utili

| Flag | Cosa fa | Default |
|------|---------|---------|
| `--roi L,A` | dimensione riquadro (frazione del frame) | `0.5,0.18` |
| `--every N` | OCR ogni N frame (più alto = meno CPU) | `12` |
| `--min-conf` | confidenza minima (0-1) | `0.95` |
| `--upscale` | ingrandimento ROI prima dell'OCR | `2.0` |
| `--pattern` | regex: stampa solo i match (es. `'[A-Z0-9]{6,}'`) | — |
| `--allowlist` | caratteri ammessi (es. solo maiuscole+cifre) | — |
| `--mode` | sorgente video: `auto` / `live` / `mjpeg` / `shot` (vedi sotto) | `auto` |

Modalità disponibili:

| `--mode` | Cosa fa | Quando |
|----------|---------|--------|
| `auto` | prova in catena `live → mjpeg → shot` con fallback automatico | default, lascia decidere |
| `live` | solo video via OpenCV/FFMPEG (la "prima versione") | webcam USB o Windows, dove OpenCV apre lo stream |
| `mjpeg` | solo parser MJPEG interno semi-live (~50-60 fps) | IP Webcam su macOS, streaming fluido |
| `shot` | solo snapshot `/shot.jpg` in polling (~5-6 fps) | massima stabilità se lo stream è capriccioso |

```bash
# semi-live MJPEG, niente tentativo OpenCV iniziale
python serial_reader.py --source http://192.168.1.160:8080/video --mode mjpeg

# direttamente snapshot
python serial_reader.py --source http://192.168.1.160:8080/video --mode shot
```

> Su macOS `live` di solito **non** apre il MJPEG di IP Webcam (limite di OpenCV): usa
> `mjpeg` o `auto`. `live` è pensata per webcam USB o Windows.

Esempio con regole sul seriale:

```bash
python serial_reader.py --source http://192.168.1.50:8080/video \
  --pattern '[A-Z0-9]{6,}' \
  --allowlist 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
```

## Note

- **Streaming su macOS:** OpenCV/FFMPEG non apre il MJPEG multipart di IP Webcam
  (`/video`). Lo script lo legge allora con un parser MJPEG interno
  (`Stream non apribile con OpenCV, uso il lettore MJPEG diretto...`), ottenendo
  streaming pieno (~50-60 fps) e riconnessione automatica quando il telefono va in
  idle. Se nemmeno questo dà frame, ripiega sullo snapshot `/shot.jpg` in polling
  (~5-6 fps). Tieni lo schermo del telefono acceso / disattiva il risparmio energetico
  per evitare che lo stream si fermi.
- **Testo lungo non riconosciuto:** EasyOCR dà una sola confidenza per l'intera
  stringa, quindi i seriali lunghi scendono facilmente sotto `--min-conf 0.95`.
  Abbassa la soglia (`--min-conf 0.8`) e/o allarga il riquadro (`--roi 0.85,0.18`)
  perché il testo ci stia tutto dentro.
- Testo piccolo/inclinato su asta di occhiale: aumenta `--upscale` (3.0) e avvicina la
  telecamera così che il seriale riempia il riquadro.
- Se EasyOCR non basta, l'upgrade è **PaddleOCR** (migliore su testo piccolo, ha il
  classificatore d'angolo) — oppure usa la [versione Apple](#versione-apple-iphone--vision-ocr),
  in genere più precisa su testo stampato.

## Versione Apple (iPhone + Vision OCR)

`serial_reader_apple.py` usa l'iPhone come **Continuity Camera** (webcam nativa del Mac)
e fa OCR con il framework **Vision** di macOS. Niente rete, niente app, niente EasyOCR.

**Perché è meglio:** la fotocamera è nativa (`--source 0/1`, bassa latenza, autofocus, e
**macro** sugli iPhone Pro per i seriali minuscoli); Vision gira sul Neural Engine ed è
più veloce e accurato di EasyOCR su testo stampato, senza scaricare modelli.

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip            # pip vecchio non compila i wheel di pyobjc
pip install -r requirements-apple.txt
```

### Collegare l'iPhone (Continuity Camera)

1. iPhone (iOS 16+) e Mac (macOS Ventura+) con lo **stesso Apple ID**, Wi-Fi + Bluetooth ON.
2. Posiziona l'iPhone fermo, **fotocamera posteriore** verso il seriale (lo schermo può
   restare bloccato). Compare automaticamente come telecamera sul Mac.
3. Al primo avvio macOS chiede il permesso fotocamera per il terminale/Python: concedilo.

### Avvio

```bash
python serial_reader_apple.py --list           # elenca gli indici camera
python serial_reader_apple.py --source 1        # iPhone di solito è 0 o 1
python serial_reader_apple.py --source 1 --pattern '[A-Z0-9]{6,}'
```

Flag uguali alla versione Android (`--roi`, `--every`, `--min-conf`, `--upscale`,
`--pattern`), tranne `--allowlist`/`--mode` che qui non servono. `--every` può restare
basso (default 6) perché Vision è veloce.
