#!/usr/bin/env python3
"""
DetectorIntrusos — Bot de Telegram con detección de movimiento ligera.
Optimizado para Raspberry Pi Zero W.
"""

import os
import time
import asyncio
import logging
import subprocess
import shutil
import numpy as np
from pathlib import Path
from PIL import Image
from dotenv import load_dotenv
import telegram

# ── Configuración ─────────────────────────────────────────────────────────────

load_dotenv('/home/pi/.env')

TOKEN      = os.getenv("TELEGRAM_TOKEN2")
CHAT_ID    = int(os.getenv("TELEGRAM_CHAT_ID"))
DEVICE     = os.getenv("CAMERA_DEVICE", "/dev/video0")
RESOLUTION = os.getenv("CAPTURE_RESOLUTION", "320x240")
THRESHOLD  = int(os.getenv("MOTION_THRESHOLD", "25"))
MIN_PIXELS = int(os.getenv("MOTION_MIN_PIXELS", "500"))
INTERVAL   = int(os.getenv("CHECK_INTERVAL", "2"))

SNAP_PATH  = Path("/tmp/intrusos_snap.jpg")
ALERT_PATH = Path("/tmp/intrusos_alert.jpg")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Funciones ─────────────────────────────────────────────────────────────────

def capture(path: Path) -> bool:
    """Captura un frame con fswebcam. Devuelve True si tiene éxito."""
    result = subprocess.run(
        [
            "fswebcam",
            "--device", DEVICE,
            "--resolution", RESOLUTION,
            "--no-banner",
            "--skip", "1",
            "--quiet",
            str(path),
        ],
        capture_output=True,
        timeout=15,
    )
    return result.returncode == 0 and path.exists()


def frame_to_array(path: Path) -> np.ndarray:
    """Convierte imagen a array numpy en escala de grises."""
    with Image.open(path) as img:
        return np.array(img.convert("L"), dtype=np.int16)


def detect_motion(prev: np.ndarray, curr: np.ndarray) -> bool:
    """
    Compara dos frames. Devuelve True si hay suficientes píxeles
    con diferencia de brillo superior al umbral.
    """
    diff = np.abs(curr - prev)
    changed_pixels = int(np.sum(diff > THRESHOLD))
    log.debug("Píxeles cambiados: %d (mínimo: %d)", changed_pixels, MIN_PIXELS)
    return changed_pixels >= MIN_PIXELS


async def send_alert(bot: telegram.Bot, image_path: Path) -> None:
    """Envía la imagen de alerta por Telegram."""
    try:
        with open(image_path, "rb") as f:
            await bot.send_photo(
                chat_id=CHAT_ID,
                photo=f,
                caption="🚨 Movimiento detectado",
            )
        log.info("Alerta enviada por Telegram.")
    except telegram.error.TelegramError as e:
        log.error("Error enviando alerta: %s", e)


# ── Bucle principal ────────────────────────────────────────────────────────────

async def main() -> None:
    log.info("Iniciando DetectorIntrusos...")
    bot = telegram.Bot(token=TOKEN)

    async with bot:
        try:
            me = await bot.get_me()
            log.info("Bot conectado: @%s", me.username)
            await bot.send_message(chat_id=CHAT_ID, text="✅ DetectorIntrusos activo y vigilando.")
        except telegram.error.TelegramError as e:
            log.error("No se pudo conectar con Telegram: %s", e)
            raise SystemExit(1)

        prev_frame = None
        cooldown   = 0
        COOLDOWN_S = 30

        while True:
            try:
                if not capture(SNAP_PATH):
                    log.warning("Fallo al capturar frame, reintentando...")
                    await asyncio.sleep(INTERVAL)
                    continue

                curr_frame = frame_to_array(SNAP_PATH)

                if prev_frame is not None:
                    if cooldown <= 0 and detect_motion(prev_frame, curr_frame):
                        log.info("¡Movimiento detectado!")
                        shutil.copy(SNAP_PATH, ALERT_PATH)
                        await send_alert(bot, ALERT_PATH)
                        cooldown = COOLDOWN_S
                    elif cooldown > 0:
                        cooldown -= INTERVAL

                prev_frame = curr_frame

            except KeyboardInterrupt:
                log.info("Detenido por el usuario.")
                break
            except Exception as e:
                log.error("Error inesperado: %s", e)
                await asyncio.sleep(5)

            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())