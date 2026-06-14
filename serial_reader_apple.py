"""Versione "tutta Apple" del lettore di seriali, ottimizzata per Mac.

Sorgente video : iPhone come **Continuity Camera** (webcam nativa) o webcam interna.
OCR            : framework **Vision** di macOS (VNRecognizeTextRequest), accelerato
                 dal Neural Engine. Niente EasyOCR/PyTorch, niente download modelli.

Setup:
    pip install opencv-python numpy pyobjc-framework-Vision pyobjc-framework-Quartz

Uso:
    python serial_reader_apple.py --list           # elenca gli indici camera
    python serial_reader_apple.py --source 0       # avvia (iPhone di solito 0 o 1)
    python serial_reader_apple.py --source 1 --pattern '[A-Z0-9]{6,}'
"""

import argparse
import re
import sys
import time

import cv2
import numpy as np

import Quartz
import Vision
from Foundation import NSData

VISION_LEVEL_ACCURATE = Vision.VNRequestTextRecognitionLevelAccurate


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Serial reader Apple (Continuity Camera + Vision OCR)")
    p.add_argument("--source", default="0", help="Indice della camera (default 0). iPhone spesso 0 o 1.")
    p.add_argument("--list", action="store_true", help="Elenca gli indici camera disponibili ed esci.")
    p.add_argument("--roi", default="0.5,0.18", help="Riquadro come frazione del frame: larghezza,altezza")
    p.add_argument("--every", type=int, default=6, help="Esegui l'OCR ogni N frame (default 6).")
    p.add_argument("--min-conf", type=float, default=0.95, help="Confidenza minima 0-1 (default 0.95).")
    p.add_argument("--upscale", type=float, default=2.0, help="Ingrandimento ROI prima dell'OCR.")
    p.add_argument("--pattern", default=None, help="Regex: stampa solo i match (es. '[A-Z0-9]{6,}').")
    return p.parse_args()


def list_cameras(max_index: int = 6) -> None:
    for i in range(max_index):
        cap = cv2.VideoCapture(i)
        ok = cap.isOpened() and cap.read()[0]
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            print(f"  index {i}: {'OK' if ok else 'aperta ma nessun frame'}  {w}x{h}")
        cap.release()


def open_camera(index: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        sys.exit(f"Impossibile aprire la camera index {index}. Prova --list per gli indici.")
    return cap


def roi_box(frame_w: int, frame_h: int, fw: float, fh: float) -> tuple[int, int, int, int]:
    w, h = int(frame_w * fw), int(frame_h * fh)
    x1, y1 = (frame_w - w) // 2, (frame_h - h) // 2
    return x1, y1, x1 + w, y1 + h


def _cgimage_from_bgr(bgr):
    """Converte un frame BGR di OpenCV in CGImage per Vision."""
    ok, buf = cv2.imencode(".png", bgr)
    if not ok:
        return None
    data = NSData.dataWithBytes_length_(buf.tobytes(), len(buf))
    src = Quartz.CGImageSourceCreateWithData(data, None)
    if src is None:
        return None
    return Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)


def vision_ocr(bgr) -> list[tuple[str, float]]:
    """OCR con il framework Vision. Ritorna [(testo, confidenza 0-1), ...]."""
    cg = _cgimage_from_bgr(bgr)
    if cg is None:
        return []
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(VISION_LEVEL_ACCURATE)
    req.setUsesLanguageCorrection_(False)  # i seriali non sono parole: niente autocorrezione
    ok, _ = handler.performRequests_error_([req], None)
    if not ok:
        return []
    out = []
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)
        if cand:
            out.append((cand[0].string(), float(cand[0].confidence())))
    return out


def main() -> None:
    args = parse_args()
    if args.list:
        print("Camere disponibili:")
        list_cameras()
        return

    fw, fh = (float(x) for x in args.roi.split(","))
    pattern = re.compile(args.pattern) if args.pattern else None

    cap = open_camera(int(args.source))
    win = "serial reader Apple (q=esci)"
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
            crop = frame[y1:y2, x1:x2]
            if args.upscale != 1.0:
                crop = cv2.resize(crop, None, fx=args.upscale, fy=args.upscale,
                                  interpolation=cv2.INTER_CUBIC)
            for text, conf in vision_ocr(crop):
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
