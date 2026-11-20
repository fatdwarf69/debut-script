import os

# À définir avant les imports OpenCV / Tesseract.
# Chaque worker OCR lance déjà sa propre instance de Tesseract.
os.environ["OMP_THREAD_LIMIT"] = "1"

import sys
import subprocess
import re
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import pytesseract


# ==================================================================
# CONFIGURATION
# ==================================================================

OUTPUT_DIR = Path(r"E:\videos\cut")
FFMPEG = Path(r"E:\videos\ffmpeg\bin\ffmpeg.exe")

TESSERACT_EXE = Path(
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
TESSDATA_DIR = Path(
    r"C:\Program Files\Tesseract-OCR\tessdata"
)

SAMPLE_FPS = 1

# Commencer avec 4 workers maximum pour éviter de saturer le CPU.
OCR_WORKERS = min(4, max(1, (os.cpu_count() or 2) // 2))

# Augmenter à 1600 si les petits textes du shop sont mal reconnus.
FRAME_MAX_WIDTH = 1280

SHOP_KEYWORDS = [
    "buy time remaining",
    "equipment",
    "pistols",
    "mid tier",
    "rifles",
    "grenades",
]

# Seuils stricts de la première version pour limiter les faux positifs.
DEATH_PIXEL_RATIO = 1.8
DEATH_MIN_RED_RATIO = 0.60
DEATH_MIN_BORDER = 0.55
DEATH_MIN_CENTER = 0.55
DEATH_MEAN_DOMINANCE = 1.8
DEATH_MAX_BRIGHTNESS = 130


# ==================================================================
# SETUP
# ==================================================================

pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_EXE)
os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)

# Le parallélisme est assuré par ThreadPoolExecutor.
cv2.setNumThreads(1)


def validate_config():
    if SAMPLE_FPS <= 0:
        raise ValueError("SAMPLE_FPS doit être supérieur à zéro.")

    if FRAME_MAX_WIDTH < 2:
        raise ValueError("FRAME_MAX_WIDTH doit être au moins égal à 2.")

    if OCR_WORKERS < 1:
        raise ValueError("OCR_WORKERS doit être au moins égal à 1.")

    for executable in (FFMPEG, TESSERACT_EXE):
        if not executable.is_file():
            raise FileNotFoundError(
                f"Exécutable introuvable : {executable}"
            )

    english_data = TESSDATA_DIR / "eng.traineddata"

    if not english_data.is_file():
        raise FileNotFoundError(
            f"Données OCR anglaises introuvables : {english_data}"
        )


# ==================================================================
# VIDEO INPUT
# ==================================================================

def pick_video():
    if len(sys.argv) < 2:
        raise ValueError("Aucun chemin vidéo reçu depuis le BAT.")

    video = Path(sys.argv[1]).resolve()

    if not video.is_file():
        raise FileNotFoundError(f"Vidéo introuvable : {video}")

    if video.suffix.lower() not in (
        ".mp4", ".mkv", ".mov", ".avi", ".webm"
    ):
        raise ValueError(
            f"Format vidéo non supporté : {video.suffix}"
        )

    return video


# ==================================================================
# FRAME EXTRACTION
# ==================================================================

def extract_frames(video, frames_dir):
    frames_dir.mkdir(parents=True, exist_ok=True)

    # Nettoyer uniquement les anciennes frames générées.
    # Les autres fichiers du dossier sont conservés.
    for frame_path in frames_dir.glob("f_*.jpg"):
        if (
            frame_path.is_file()
            and re.fullmatch(r"f_\d+\.jpg", frame_path.name)
        ):
            frame_path.unlink()

    print(
        f"\nExtraction à {SAMPLE_FPS} FPS, "
        f"largeur maximale {FRAME_MAX_WIDTH}px..."
    )

    # FPS avant scale : seules les frames retenues sont redimensionnées.
    filters = (
        f"fps={SAMPLE_FPS},"
        f"scale=w='min({FRAME_MAX_WIDTH},iw)':h=-2"
    )

    result = subprocess.run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
            "-y",
            "-i", str(video),
            "-map", "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-vf", filters,
            "-q:v", "3",
            str(frames_dir / "f_%06d.jpg"),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )

    if result.returncode:
        raise RuntimeError(
            f"Échec FFmpeg :\n{result.stderr.strip()}"
        )


# ==================================================================
# SHOP DETECTION
# ==================================================================

def is_shop(text):
    matches = sum(
        keyword in text
        for keyword in SHOP_KEYWORDS
    )

    return (
        "buy time remaining" in text
        or matches >= 2
    )


# ==================================================================
# DEATH DETECTION
# ==================================================================

def is_red_death(img):
    if img is None:
        return False, 0.0, 0.0

    small = cv2.resize(
        img,
        (320, 180),
        interpolation=cv2.INTER_AREA,
    )

    b, g, r = cv2.split(small.astype(np.float32))

    tinted = (
        (r > g * DEATH_PIXEL_RATIO)
        & (r > b * DEATH_PIXEL_RATIO)
        & (r > 25)
    )

    height, width = tinted.shape

    red_ratio = float(tinted.mean())

    by = int(height * 0.20)
    bx = int(width * 0.20)

    border = np.zeros_like(tinted, dtype=bool)
    border[:by, :] = True
    border[-by:, :] = True
    border[:, :bx] = True
    border[:, -bx:] = True

    border_ratio = float(tinted[border].mean())
    center_ratio = float(tinted[by:-by, bx:-bx].mean())

    mean_r = float(r.mean())
    mean_g = float(g.mean())
    mean_b = float(b.mean())

    dominance = mean_r / max(mean_g, mean_b, 1.0)
    brightness = (mean_r + mean_g + mean_b) / 3.0

    detected = (
        red_ratio >= DEATH_MIN_RED_RATIO
        and border_ratio >= DEATH_MIN_BORDER
        and center_ratio >= DEATH_MIN_CENTER
        and dominance >= DEATH_MEAN_DOMINANCE
        and brightness <= DEATH_MAX_BRIGHTNESS
    )

    return detected, red_ratio, border_ratio


# ==================================================================
# ANALYSE D'UNE FRAME
# ==================================================================

def read_frame_ocr(frame_path):
    match = re.fullmatch(r"f_(\d+)\.jpg", frame_path.name)

    if not match:
        return None

    frame_number = int(match.group(1))

    # Une seule lecture disque pour les deux analyses.
    img = cv2.imread(str(frame_path))

    if img is None:
        raise RuntimeError(f"Frame illisible : {frame_path}")

    death_detected, _, _ = is_red_death(img)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    text = pytesseract.image_to_string(
        gray,
        lang="eng",
        config="--oem 3 --psm 6",
    )

    text = " ".join(text.lower().split())

    return frame_number, text, death_detected


# ==================================================================
# SHOP / DEATH DETECTION
# ==================================================================

def detect_shop_death(frames_dir):
    frames = sorted(
        (
            path
            for path in frames_dir.glob("f_*.jpg")
            if re.fullmatch(r"f_\d+\.jpg", path.name)
        ),
        key=lambda path: int(path.stem[2:]),
    )

    if not frames:
        raise RuntimeError("Aucune frame trouvée.")

    total = len(frames)

    print(
        f"\nAnalyse de {total} frames "
        f"avec {OCR_WORKERS} workers..."
    )

    segments = []
    events = []

    active_shop = None
    previous_shop = False

    started = time.perf_counter()

    with ThreadPoolExecutor(max_workers=OCR_WORKERS) as executor:
        # map conserve l'ordre des frames malgré le parallélisme.
        results = executor.map(read_frame_ocr, frames)

        for processed, result in enumerate(results, start=1):
            if result is None:
                continue

            frame_number, text, death_detected = result
            shop_detected = is_shop(text)

            # Nouvelle ouverture du shop.
            if shop_detected and not previous_shop:
                if active_shop is not None:
                    events.append({
                        "type": "SHOP",
                        "start_frame": active_shop,
                        "end_frame": frame_number,
                    })

                active_shop = frame_number

            previous_shop = shop_detected

            # Ne retenir une mort qu'après une ouverture du shop.
            if active_shop is not None and death_detected:
                events.append({
                    "type": "DEATH",
                    "start_frame": active_shop,
                    "end_frame": frame_number,
                })

                segments.append({
                    "start_frame": active_shop,
                    "end_frame": frame_number,
                    "cut_start": (active_shop - 1) / SAMPLE_FPS,
                    "cut_end": (frame_number - 1) / SAMPLE_FPS,
                })

                active_shop = None

            if processed % 25 == 0 or processed == total:
                elapsed = time.perf_counter() - started
                speed = processed / max(elapsed, 0.001)

                print(
                    f"\rAnalyse : {processed}/{total} "
                    f"| {speed:.1f} frames/s",
                    end="",
                    flush=True,
                )

    print()

    # Dernier shop sans mort détectée.
    if active_shop is not None:
        events.append({
            "type": "SHOP_OPEN",
            "start_frame": active_shop,
            "end_frame": active_shop,
        })

    return segments, events


# ==================================================================
# LOGS
# ==================================================================

def save_logs(video, segments, events, logs_dir):
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_file = logs_dir / "shop_death_detection.txt"

    segments_by_frames = {
        (segment["start_frame"], segment["end_frame"]): segment
        for segment in segments
    }

    with log_file.open("w", encoding="utf-8") as log:
        log.write(f"VIDEO: {video.name}\n")
        log.write("=" * 50 + "\n\n")

        for event in events:
            start = event["start_frame"]
            end = event["end_frame"]

            if event["type"] == "SHOP":
                result = (
                    f"SHOP: f_{start:06d} "
                    f"-> SHOP: f_{end:06d}"
                )

            elif event["type"] == "DEATH":
                result = (
                    f"SHOP: f_{start:06d} "
                    f"-> DEATH: f_{end:06d}"
                )

            else:
                result = (
                    f"SHOP OUVERT: f_{start:06d} "
                    f"(sans mort)"
                )

            print(result)
            log.write(result + "\n")

            if event["type"] == "DEATH":
                segment = segments_by_frames.get((start, end))

                if segment is not None:
                    log.write(
                        f"CUT: {segment['cut_start']:.3f}s "
                        f"-> {segment['cut_end']:.3f}s\n"
                    )

            log.write("\n")

    print(f"\nLogs sauvegardés : {log_file}")


# ==================================================================
# EXECUTION
# ==================================================================

def main():
    validate_config()
    video = pick_video()

    total_started = time.perf_counter()

    video_dir = OUTPUT_DIR / video.stem
    frames_dir = video_dir / "frames"
    logs_dir = video_dir / "logs"

    print(f"\nVIDEO : {video.name}")
    print(f"FRAMES : {frames_dir}")

    extraction_started = time.perf_counter()

    extract_frames(video, frames_dir)

    extraction_elapsed = time.perf_counter() - extraction_started
    print(f"\nExtraction terminée en {extraction_elapsed:.1f}s.")

    analysis_started = time.perf_counter()

    segments, events = detect_shop_death(frames_dir)

    analysis_elapsed = time.perf_counter() - analysis_started
    print(f"Analyse terminée en {analysis_elapsed:.1f}s.")

    save_logs(video, segments, events, logs_dir)

    total_elapsed = time.perf_counter() - total_started

    print(f"\nSegments détectés : {len(segments)}")
    print(f"Traitement terminé en {total_elapsed:.1f}s.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTraitement interrompu.")
        sys.exit(130)
    except Exception as error:
        print(f"\nERREUR : {error}")
        sys.exit(1)
