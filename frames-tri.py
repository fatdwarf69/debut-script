
import os
import sys
import shutil
import subprocess
import re
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

TESSERACT_EXE = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
TESSDATA_DIR = Path(r"C:\Program Files\Tesseract-OCR\tessdata")

SAMPLE_FPS = 1
OCR_WORKERS = 4

SHOP_KEYWORDS = [
    "buy time remaining",
    "equipment",
    "pistols",
    "mid tier",
    "rifles",
    "grenades",
]

DEATH_KEYWORDS = [
    "killed you with",
    "you were killed",
    "killed by",
]


# ==================================================================
# SETUP
# ==================================================================

pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_EXE)
os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)


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
        raise ValueError(f"Format vidéo non supporté : {video.suffix}")

    return video


# ==================================================================
# FRAME EXTRACTION
# ==================================================================

def extract_frames(video, frames_dir):

    frames_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nExtraction à {SAMPLE_FPS} FPS...")

    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-i", str(video),
            "-vf", f"fps={SAMPLE_FPS}",
            "-q:v", "3",
            str(frames_dir / "f_%06d.jpg")
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE
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
# DEATH OCR DETECTION
# ==================================================================

def is_death(text):

    return any(
        keyword in text
        for keyword in DEATH_KEYWORDS
    )


# ==================================================================
# DEATH DETECTION WITH OPENCV / HSV
# ==================================================================

def is_red_death(img):

    if img is None:
        return False, 0.0, 0.0

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # Rouge : deux plages HSV
    lower_red_1 = np.array([0, 100, 70])
    upper_red_1 = np.array([10, 255, 255])

    lower_red_2 = np.array([170, 100, 70])
    upper_red_2 = np.array([180, 255, 255])

    mask1 = cv2.inRange(hsv, lower_red_1, upper_red_1)
    mask2 = cv2.inRange(hsv, lower_red_2, upper_red_2)

    red_mask = cv2.bitwise_or(mask1, mask2)

    # Pourcentage de rouge sur toute l'image
    red_pixels = cv2.countNonZero(red_mask)
    total_pixels = red_mask.shape[0] * red_mask.shape[1]

    red_ratio = red_pixels / total_pixels

    # Analyse également les bords de l'écran
    height, width = red_mask.shape

    border_mask = np.zeros_like(red_mask)

    border_size_y = int(height * 0.20)
    border_size_x = int(width * 0.20)

    border_mask[:border_size_y, :] = 255
    border_mask[-border_size_y:, :] = 255
    border_mask[:, :border_size_x] = 255
    border_mask[:, -border_size_x:] = 255

    border_pixels = cv2.countNonZero(
        cv2.bitwise_and(red_mask, border_mask)
    )

    border_total = cv2.countNonZero(border_mask)

    border_ratio = border_pixels / max(border_total, 1)

    # Détection d'un écran rouge
    detected = (
        red_ratio >= 0.10
        or border_ratio >= 0.22
    )

    return detected, red_ratio, border_ratio


# ==================================================================
# FRAME ANALYSIS
# ==================================================================

def analyze_frame(frame_path):

    img = cv2.imread(str(frame_path))

    if img is None:
        return "", False, 0.0, 0.0

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    text = pytesseract.image_to_string(
        gray,
        config="--oem 3 --psm 6"
    ).lower()

    red_detected, red_ratio, border_ratio = is_red_death(img)

    return text, red_detected, red_ratio, border_ratio


# ==================================================================
# SHOP -> DEATH DETECTION
# ==================================================================

def detect_shop_death(frames_dir):

    frames = sorted(
        frames_dir.glob("f_*.jpg"),
        key=lambda p: int(re.search(r"f_(\d+)", p.stem).group(1))
    )

    if not frames:
        print("Aucune frame trouvée.")
        return []

    print(f"\nAnalyse de {len(frames)} frames...")

    with ThreadPoolExecutor(max_workers=OCR_WORKERS) as executor:
        results = list(executor.map(analyze_frame, frames))

    segments = []

    shop_candidate = None
    shop_hits = 0
    last_shop_hit = None

    shop_start = None

    for frame, result in zip(frames, results):

        text, red_detected, red_ratio, border_ratio = result

        frame_number = int(
            re.search(r"f_(\d+)", frame.stem).group(1)
        )

        # --------------------------------------------------
        # RECHERCHE DU SHOP
        # --------------------------------------------------

        if shop_start is None:

            if is_shop(text):

                if shop_candidate is None:
                    shop_candidate = frame_number
                    shop_hits = 0

                # Deux détections OCR rapprochées.
                # Une interruption de quelques frames est tolérée.
                if last_shop_hit is None or frame_number - last_shop_hit <= 3:
                    shop_hits += 1
                else:
                    shop_candidate = frame_number
                    shop_hits = 1

                last_shop_hit = frame_number

                if shop_hits >= 2:

                    shop_start = shop_candidate

                    print(
                        f"SHOP détecté : f_{shop_start:06d}"
                    )

            elif (
                last_shop_hit is not None
                and frame_number - last_shop_hit > 3
            ):

                shop_candidate = None
                shop_hits = 0
                last_shop_hit = None

        # --------------------------------------------------
        # RECHERCHE DE LA MORT
        # --------------------------------------------------

        else:

            death_ocr = is_death(text)

            if death_ocr or red_detected:

                reason = []

                if death_ocr:
                    reason.append("OCR")

                if red_detected:
                    reason.append("HSV ROUGE")

                print(
                    f"MORT détectée : f_{frame_number:06d} "
                    f"({' + '.join(reason)})"
                )

                if red_detected:
                    print(
                        f"Rouge écran : {red_ratio * 100:.1f}% | "
                        f"Bords : {border_ratio * 100:.1f}%"
                    )

                # Conversion des frames en secondes.
                # FFmpeg commence généralement la numérotation à 1.
                shop_time = (shop_start - 1) / SAMPLE_FPS
                death_time = (frame_number - 1) / SAMPLE_FPS

                # Marges de sécurité
                cut_start = max(0, shop_time - 0.5)
                cut_end = death_time + 0.5

                segments.append({
                    "start_frame": shop_start,
                    "end_frame": frame_number,
                    "cut_start": cut_start,
                    "cut_end": cut_end
                })

                print(
                    f"SEGMENT : {cut_start:.2f}s -> "
                    f"{cut_end:.2f}s"
                )

                # Réinitialisation
                shop_start = None
                shop_candidate = None
                shop_hits = 0
                last_shop_hit = None

    if shop_start is not None:
        print(
            f"SHOP sans mort détectée : f_{shop_start:06d}"
        )

    return segments


# ==================================================================
# LOGS
# ==================================================================

def save_logs(video, segments, logs_dir):

    logs_dir.mkdir(parents=True, exist_ok=True)

    log_file = logs_dir / "shop_death_detection.txt"

    with open(log_file, "w", encoding="utf-8") as log:

        log.write(f"VIDEO: {video.name}\n")
        log.write("=" * 50 + "\n\n")

        for segment in segments:

            start = segment["start_frame"]
            end = segment["end_frame"]

            cut_start = segment["cut_start"]
            cut_end = segment["cut_end"]

            result = (
                f"SHOP: f_{start:06d} "
                f"-> DEATH: f_{end:06d}"
            )

            print(result)
            log.write(result + "\n")

            log.write(
                f"CUT: {cut_start:.3f}s -> {cut_end:.3f}s\n\n"
            )

    print(f"\nLogs sauvegardés : {log_file}")


# ==================================================================
# EXECUTION
# ==================================================================

try:

    video = pick_video()

    print(f"\nVIDEO : {video.name}")

    video_dir = OUTPUT_DIR / video.stem
    frames_dir = video_dir / "frames"
    logs_dir = video_dir / "logs"

    if frames_dir.exists():
        shutil.rmtree(frames_dir)

    frames_dir.mkdir(parents=True, exist_ok=True)

    print(f"FRAMES : {frames_dir}")

    extract_frames(video, frames_dir)

    print("\nExtraction terminée !")

    segments = detect_shop_death(frames_dir)

    save_logs(video, segments, logs_dir)

    print("\nTraitement terminé !")

except Exception as e:

    print(f"\nERREUR : {e}")
    sys.exit(1)
