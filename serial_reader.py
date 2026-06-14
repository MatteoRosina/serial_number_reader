"""Legge un seriale da uno stream video (es. telefono Android via app "IP Webcam").

Mostra il feed con un riquadro (ROI) al centro; fa OCR solo dentro il riquadro
e stampa in console il testo riconosciuto.

Esempi:
    python serial_reader.py --source http://192.168.1.50:8080/video
    python serial_reader.py --source 0            # webcam/Continuity USB
    python serial_reader.py --source ... --pattern "[A-Z0-9]{6,}"
"""

import argparse
import os
import re
import sys
import time
import select
import urllib.parse
import urllib.request

import numpy as np

# Su macOS il Python di python.org non ha i certificati SSL di sistema: senza
# questo, il download dei modelli EasyOCR fallisce con CERTIFICATE_VERIFY_FAILED.
try:
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:
    pass

import cv2
import easyocr


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Serial number reader da stream video")
    p.add_argument(
        "--source",
        required=True,
        help="URL stream (es. http://IP:8080/video) o indice webcam (es. 0)",
    )
    p.add_argument(
        "--roi",
        default="0.5,0.18",
        help="Dimensione riquadro come frazione del frame: larghezza,altezza (default 0.5,0.18)",
    )
    p.add_argument(
        "--every",
        type=int,
        default=12,
        help="Esegui l'OCR ogni N frame (default 12). Più alto = meno CPU.",
    )
    p.add_argument(
        "--min-conf",
        type=float,
        default=0.95,
        help="Confidenza minima per accettare un testo (0-1, default 0.95)",
    )
    p.add_argument(
        "--upscale",
        type=float,
        default=2.0,
        help="Fattore di ingrandimento della ROI prima dell'OCR (aiuta su testo piccolo)",
    )
    p.add_argument(
        "--pattern",
        default=None,
        help="Regex opzionale: stampa solo i testi che combaciano (es. '[A-Z0-9]{6,}')",
    )
    p.add_argument(
        "--allowlist",
        default=None,
        help="Caratteri ammessi per l'OCR (es. 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')",
    )
    p.add_argument(
        "--mode",
        choices=["auto", "live", "mjpeg", "shot"],
        default="auto",
        help="auto: live->mjpeg->shot con fallback; live: solo video OpenCV; "
             "mjpeg: solo parser MJPEG semi-live; shot: solo snapshot /shot.jpg",
    )
    return p.parse_args()


class MjpegStreamCapture:
    """Legge lo stream MJPEG multipart (es. IP Webcam /video) parsando i JPEG a mano.

    OpenCV/FFMPEG su macOS non apre questo stream; qui teniamo una connessione
    persistente e tagliamo i frame sui marker JPEG (FFD8…FFD9). Streaming pieno
    (~50fps). Si riconnette da solo quando il telefono va in idle e lo stream si
    interrompe.
    """

    def __init__(self, url: str, timeout: float = 5.0):
        self.url = url
        self.timeout = timeout
        self.stream = None
        self.buf = b""
        self._connect()

    def _connect(self) -> bool:
        try:
            self.stream = urllib.request.urlopen(self.url, timeout=self.timeout)
            self.buf = b""
            return True
        except Exception:
            self.stream = None
            return False

    def _pop_frame(self):
        """Estrae l'ultimo JPEG completo già nel buffer, scartando i precedenti."""
        latest = None
        while True:
            a = self.buf.find(b"\xff\xd8")
            b = self.buf.find(b"\xff\xd9", a + 2) if a != -1 else -1
            if a == -1 or b == -1:
                break
            latest = self.buf[a:b + 2]
            self.buf = self.buf[b + 2:]
        return latest

    def read(self):
        for _ in range(2):  # un tentativo + una riconnessione
            if self.stream is None and not self._connect():
                time.sleep(0.3)
                continue
            try:
                latest = self._pop_frame()
                # Finché ci sono dati già pronti sul socket, continua a leggere e
                # scarta i frame vecchi: vogliamo solo il più recente (bassa latenza).
                while latest is None or select.select([self.stream], [], [], 0)[0]:
                    chunk = self.stream.read(16384)
                    if not chunk:
                        raise ConnectionError("stream chiuso")
                    self.buf += chunk
                    newer = self._pop_frame()
                    if newer is not None:
                        latest = newer
                img = cv2.imdecode(np.frombuffer(latest, np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    return True, img
            except Exception:
                self.stream = None  # forza riconnessione al prossimo giro
        return False, None

    def release(self):
        if self.stream is not None:
            self.stream.close()


class SnapshotCapture:
    """Legge frame ripetendo GET sull'endpoint snapshot (es. IP Webcam /shot.jpg).

    OpenCV su macOS non apre lo stream MJPEG multipart (/video): qui facciamo
    polling di un singolo JPEG, che è molto più robusto.
    """

    def __init__(self, url: str, timeout: float = 4.0):
        self.url = url
        self.timeout = timeout

    def read(self):
        try:
            data = urllib.request.urlopen(self.url, timeout=self.timeout).read()
        except Exception:
            return False, None
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        return img is not None, img

    def release(self):
        pass


def snapshot_url(source: str) -> str:
    """Deriva l'URL /shot.jpg dalla base dello stream (scheme://host:port)."""
    u = urllib.parse.urlsplit(source)
    return urllib.parse.urlunsplit((u.scheme, u.netloc, "/shot.jpg", "", ""))


def _open_live(source: str):
    """Video live via OpenCV/FFMPEG. None se non si apre o non dà frame."""
    cap = cv2.VideoCapture(source)
    if cap.isOpened() and cap.read()[0]:
        return cap
    cap.release()
    return None


def _open_mjpeg(source: str):
    """Semi-live: parser MJPEG multipart interno. None se non arriva nessun frame."""
    mjpeg = MjpegStreamCapture(source)
    if mjpeg.read()[0]:
        return mjpeg
    mjpeg.release()
    return None


def _open_shot(source: str):
    """Snapshot in polling su /shot.jpg. None se l'endpoint non risponde."""
    probe = SnapshotCapture(snapshot_url(source))
    return probe if probe.read()[0] else None


def open_source(source: str, mode: str = "auto"):
    if source.isdigit():
        cap = cv2.VideoCapture(int(source))
        if not cap.isOpened():
            sys.exit(f"Impossibile aprire la sorgente: {source}")
        return cap

    openers = {"live": _open_live, "mjpeg": _open_mjpeg, "shot": _open_shot}
    if mode in openers:
        print(f"Modalità {mode}...", flush=True)
        cap = openers[mode](source)
        if cap is None:
            sys.exit(f"Impossibile aprire la sorgente in modalità {mode}: {source}")
        return cap

    # auto: video live -> MJPEG semi-live -> snapshot.
    if cap := _open_live(source):
        return cap
    print("OpenCV non apre lo stream, provo il lettore MJPEG diretto...", flush=True)
    if cap := _open_mjpeg(source):
        return cap
    snap = snapshot_url(source)
    print(f"MJPEG non disponibile, uso lo snapshot: {snap}", flush=True)
    if cap := _open_shot(source):
        return cap
    sys.exit(f"Impossibile aprire la sorgente: {source} (né live, né MJPEG, né snapshot)")


def roi_box(frame_w: int, frame_h: int, fw: float, fh: float) -> tuple[int, int, int, int]:
    """Riquadro centrato. Ritorna (x1, y1, x2, y2)."""
    w, h = int(frame_w * fw), int(frame_h * fh)
    x1, y1 = (frame_w - w) // 2, (frame_h - h) // 2
    return x1, y1, x1 + w, y1 + h


def preprocess(crop, upscale: float):
    if upscale != 1.0:
        crop = cv2.resize(crop, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    return cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)


def main() -> None:
    args = parse_args()
    fw, fh = (float(x) for x in args.roi.split(","))
    pattern = re.compile(args.pattern) if args.pattern else None

    print("Carico EasyOCR (la prima volta scarica i modelli)...", flush=True)
    reader = easyocr.Reader(["en"], gpu=False)

    cap = open_source(args.source, args.mode)
    win = "serial reader (q=esci)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    frame_i = 0
    last_text = None
    overlay = ""

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Frame perso, riprovo...", flush=True)
            time.sleep(0.1)
            continue

        h, w = frame.shape[:2]
        x1, y1, x2, y2 = roi_box(w, h, fw, fh)

        if frame_i % args.every == 0:
            crop = preprocess(frame[y1:y2, x1:x2], args.upscale)
            results = reader.readtext(crop, allowlist=args.allowlist)
            for _, text, conf in results:
                text = text.strip()
                if conf < args.min_conf or not text:
                    continue
                if pattern and not pattern.search(text):
                    continue
                overlay = f"{text}  ({conf:.2f})"
                if text != last_text:
                    print(f"[{time.strftime('%H:%M:%S')}] {text}  conf={conf:.2f}", flush=True)
                    last_text = text

        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        if overlay:
            cv2.putText(frame, overlay, (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.imshow(win, frame)

        frame_i += 1
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
