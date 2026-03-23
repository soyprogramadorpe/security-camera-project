"""
=============================================================
  CÁMARA DE SEGURIDAD CON DETECCIÓN DE MOVIMIENTO
  + RECONOCIMIENTO FACIAL + ALERTAS POR TELEGRAM
=============================================================

Requisitos de instalación:
    pip install opencv-python face_recognition python-telegram-bot numpy Pillow

Hardware soportado:
    - Raspberry Pi 4 con módulo de cámara o webcam USB
    - PC/Laptop con webcam
    - ESP32-CAM (requiere stream MJPEG - ver configuración)

Uso:
    1. Configurar TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID abajo
    2. (Opcional) Agregar fotos de caras conocidas en la carpeta "rostros_conocidos/"
    3. Ejecutar: python security_camera.py
"""

import cv2
import numpy as np
import os
import time
import datetime
import threading
import logging
import sys
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

try:
    import google.generativeai as genai
except ImportError:  # Se maneja cuando Gemini no está instalado
    genai = None

try:
    from dotenv import load_dotenv
    # Load .env file from the current directory
    load_dotenv()
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("python-dotenv no está instalado. Las variables de entorno en el archivo .env podrían no cargarse.")

# ============================================================
# CONFIGURACIÓN - EDITAR ESTOS VALORES
# ============================================================

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "TU_TOKEN_AQUI")  # Obtener de @BotFather en Telegram
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "TU_CHAT_ID_AQUI")  # Obtener de @userinfobot

# --- Gemini (Análisis de video) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_PROMPT = (
    "Eres un asistente de seguridad. Describe en español, de forma breve (1-2 frases), "
    "lo que se ve en la imagen, incluyendo cuántas personas, su posición general y acciones. "
    "No inventes detalles que no estén claros."
)

# --- Cámara ---
# Intenta obtener de variable de entorno y convertir a entero si es posible, sino usa cadena ("rtsp://...")
_camera_source_env = os.getenv("CAMERA_SOURCE", "0")
try:
    CAMERA_SOURCE = int(_camera_source_env)
except ValueError:
    CAMERA_SOURCE = _camera_source_env

# Para ESP32-CAM usar: CAMERA_SOURCE = "http://192.168.1.100:81/stream"
# Para cámara IP RTSP: CAMERA_SOURCE = "rtsp://usuario:clave@192.168.1.100:554/stream"

CAMERA_RESOLUTION = (640, 480)  # Ancho x Alto
CAMERA_FPS = 15

# --- Detección de movimiento ---
MOTION_THRESHOLD = 5000       # Área mínima de cambio para considerar movimiento (pixeles)
MOTION_BLUR_SIZE = 21         # Tamaño del blur gaussiano (debe ser impar)
MOTION_DILATE_ITERATIONS = 2  # Iteraciones de dilatación para unir áreas cercanas
COOLDOWN_SECONDS = 30         # Segundos entre alertas (evitar spam)

# --- Reconocimiento facial ---
ENABLE_FACE_RECOGNITION = True
KNOWN_FACES_DIR = "rostros_conocidos"  # Carpeta con fotos de personas conocidas
# Nombrar archivos como: juan.jpg, maria.png, etc.
FACE_RECOGNITION_TOLERANCE = 0.6  # Menor = más estricto (0.4-0.6 recomendado)
FACE_CHECK_INTERVAL = 5  # Analizar caras cada N frames (ahorra CPU)

# --- Grabación ---
RECORDINGS_DIR = "grabaciones"
RECORD_SECONDS_BEFORE = 3    # Segundos de "pre-grabación" en buffer circular
RECORD_SECONDS_AFTER = 10    # Segundos a grabar después del último movimiento
VIDEO_CODEC = "mp4v"         # Codec de video (mp4v para .mp4)

# --- Resumen diario ---
ENABLE_DAILY_SUMMARY = True
SUMMARY_HOUR = 22  # Hora del resumen (formato 24h)
SUMMARY_MINUTE = 0

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('security_camera.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============================================================
# MÓDULO DE TELEGRAM
# ============================================================

class TelegramNotifier:
    """Envía alertas por Telegram de forma asíncrona."""

    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.enabled = token != "TU_TOKEN_AQUI"

        if not self.enabled:
            logger.warning("⚠️  Telegram NO configurado. Edita TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID")

    def send_message(self, text):
        """Envía un mensaje de texto."""
        if not self.enabled:
            logger.info(f"[Telegram simulado] {text}")
            return

        try:
            import urllib.request
            import urllib.parse
            url = f"{self.base_url}/sendMessage"
            data = urllib.parse.urlencode({
                'chat_id': self.chat_id,
                'text': text,
                'parse_mode': 'HTML'
            }).encode()
            req = urllib.request.Request(url, data=data)
            urllib.request.urlopen(req, timeout=10)
            logger.info(f"📨 Mensaje enviado a Telegram")
        except Exception as e:
            logger.error(f"Error enviando mensaje: {e}")

    def send_photo(self, image_path, caption=""):
        """Envía una foto con descripción."""
        if not self.enabled:
            logger.info(f"[Telegram simulado] Foto: {image_path} - {caption}")
            return

        try:
            import urllib.request
            boundary = "----FormBoundary" + str(int(time.time()))
            body = bytearray()

            # Campo chat_id
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'.encode())
            body.extend(f"{self.chat_id}\r\n".encode())

            # Campo caption
            if caption:
                body.extend(f"--{boundary}\r\n".encode())
                body.extend(f'Content-Disposition: form-data; name="caption"\r\n\r\n'.encode())
                body.extend(f"{caption}\r\n".encode())

            # Campo photo (archivo)
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="photo"; filename="capture.jpg"\r\n'.encode())
            body.extend(f"Content-Type: image/jpeg\r\n\r\n".encode())
            with open(image_path, 'rb') as f:
                body.extend(f.read())
            body.extend(f"\r\n--{boundary}--\r\n".encode())

            url = f"{self.base_url}/sendPhoto"
            req = urllib.request.Request(url, data=bytes(body))
            req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
            urllib.request.urlopen(req, timeout=30)
            logger.info(f"📸 Foto enviada a Telegram")
        except urllib.error.HTTPError as e:
            logger.error(f"Error enviando foto. HTTP {e.code}: {e.read().decode('utf-8')}")
        except Exception as e:
            logger.error(f"Error enviando foto: {e}")

    def send_video(self, video_path, caption=""):
        """Envía un video con descripción."""
        if not self.enabled:
            logger.info(f"[Telegram simulado] Video: {video_path} - {caption}")
            return

        try:
            import urllib.request
            boundary = "----FormBoundary" + str(int(time.time()))
            body = bytearray()

            # Campo chat_id
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'.encode())
            body.extend(f"{self.chat_id}\r\n".encode())

            # Campo caption
            if caption:
                body.extend(f"--{boundary}\r\n".encode())
                body.extend(f'Content-Disposition: form-data; name="caption"\r\n\r\n'.encode())
                body.extend(f"{caption}\r\n".encode())

            # Campo video (archivo)
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="video"; filename="video.mp4"\r\n'.encode())
            body.extend(f"Content-Type: video/mp4\r\n\r\n".encode())
            with open(video_path, 'rb') as f:
                body.extend(f.read())
            body.extend(f"\r\n--{boundary}--\r\n".encode())

            url = f"{self.base_url}/sendVideo"
            req = urllib.request.Request(url, data=bytes(body))
            req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
            urllib.request.urlopen(req, timeout=120) # Timeout mayor porque el video pesa más
            logger.info(f"🎥 Video enviado a Telegram")
        except urllib.error.HTTPError as e:
            logger.error(f"Error enviando video. HTTP {e.code}: {e.read().decode('utf-8')}")
        except Exception as e:
            logger.error(f"Error enviando video: {e}")

    def send_async(self, func, *args):
        """Ejecuta envío en thread separado para no bloquear la cámara."""
        thread = threading.Thread(target=func, args=args, daemon=True)
        thread.start()


# ============================================================
# MÓDULO DE RECONOCIMIENTO FACIAL
# ============================================================

class FaceRecognizer:
    """Reconoce caras conocidas vs desconocidas."""

    def __init__(self, known_faces_dir, tolerance=0.6):
        self.known_encodings = []
        self.known_names = []
        self.tolerance = tolerance
        self.available = False

        try:
            import face_recognition
            self.fr = face_recognition
            self.available = True
            logger.info("✅ face_recognition disponible")
        except ImportError:
            logger.warning("⚠️  face_recognition no instalado. Solo detección de movimiento.")
            logger.warning("   Instalar con: pip install face_recognition")
            return

        self._load_known_faces(known_faces_dir)

    def _load_known_faces(self, directory):
        """Carga fotos de personas conocidas."""
        if not os.path.exists(directory):
            os.makedirs(directory)
            logger.info(f"📁 Carpeta '{directory}' creada. Agrega fotos con formato: nombre.jpg")
            return

        for filename in os.listdir(directory):
            if filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                filepath = os.path.join(directory, filename)
                try:
                    image = self.fr.load_image_file(filepath)
                    encodings = self.fr.face_encodings(image)
                    if encodings:
                        self.known_encodings.append(encodings[0])
                        name = os.path.splitext(filename)[0].replace("_", " ").title()
                        self.known_names.append(name)
                        logger.info(f"👤 Rostro cargado: {name}")
                    else:
                        logger.warning(f"⚠️  No se detectó rostro en: {filename}")
                except Exception as e:
                    logger.error(f"Error cargando {filename}: {e}")

        logger.info(f"📊 {len(self.known_names)} rostros conocidos cargados")

    def identify_faces(self, frame):
        """
        Analiza un frame y retorna lista de caras detectadas.
        Returns: lista de dict con 'name', 'location', 'known'
        """
        if not self.available:
            return []

        # Reducir tamaño para mayor velocidad
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        rgb_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

        face_locations = self.fr.face_locations(rgb_frame)
        face_encodings = self.fr.face_encodings(rgb_frame, face_locations)

        results = []
        for encoding, location in zip(face_encodings, face_locations):
            name = "Desconocido"
            known = False

            if self.known_encodings:
                matches = self.fr.compare_faces(
                    self.known_encodings, encoding, tolerance=self.tolerance
                )
                distances = self.fr.face_distance(self.known_encodings, encoding)

                if True in matches:
                    best_idx = np.argmin(distances)
                    if matches[best_idx]:
                        name = self.known_names[best_idx]
                        known = True

            # Escalar ubicación de vuelta al tamaño original
            top, right, bottom, left = [v * 4 for v in location]
            results.append({
                'name': name,
                'location': (top, right, bottom, left),
                'known': known
            })

        return results


# ============================================================
# DETECTOR DE MOVIMIENTO
# ============================================================

class MotionDetector:
    """Detecta movimiento comparando frames consecutivos."""

    def __init__(self, threshold=5000, blur_size=21, dilate_iterations=2):
        self.threshold = threshold
        self.blur_size = blur_size
        self.dilate_iterations = dilate_iterations
        self.prev_frame = None

    def detect(self, frame):
        """
        Compara frame actual con el anterior.
        Returns: (motion_detected: bool, motion_area: int, contours: list)
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (self.blur_size, self.blur_size), 0)

        if self.prev_frame is None:
            self.prev_frame = gray
            return False, 0, []

        # Diferencia absoluta entre frames
        delta = cv2.absdiff(self.prev_frame, gray)
        self.prev_frame = gray

        # Umbral + dilatación para obtener contornos claros
        thresh = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=self.dilate_iterations)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Calcular área total de movimiento
        total_area = sum(cv2.contourArea(c) for c in contours)

        motion_detected = total_area > self.threshold
        return motion_detected, total_area, contours


# ============================================================
# GRABADOR DE VIDEO
# ============================================================

class VideoRecorder:
    """Graba clips de video cuando hay movimiento."""

    def __init__(self, output_dir, codec="mp4v", fps=15, resolution=(640, 480)):
        self.output_dir = output_dir
        self.codec = codec
        self.fps = fps
        self.resolution = resolution
        self.writer = None
        self.current_file = None
        os.makedirs(output_dir, exist_ok=True)

    def start_recording(self, frame_size=None):
        """Inicia un nuevo clip de video en una carpeta dedicada."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Crear subcarpeta para este evento
        folder_name = f"motion_{timestamp}"
        event_folder = os.path.join(self.output_dir, folder_name)
        os.makedirs(event_folder, exist_ok=True)
        
        # Archivo de video dentro de esa carpeta
        self.current_file = os.path.join(event_folder, f"{folder_name}.mp4")
        
        fourcc = cv2.VideoWriter_fourcc(*self.codec)
        res = frame_size if frame_size else self.resolution
        self.writer = cv2.VideoWriter(self.current_file, fourcc, self.fps, res)
        logger.info(f"🔴 Grabando en: {event_folder}")
        return self.current_file
        res = frame_size if frame_size else self.resolution
        self.writer = cv2.VideoWriter(self.current_file, fourcc, self.fps, res)
        logger.info(f"🔴 Grabando: {self.current_file}")
        return self.current_file

    def write_frame(self, frame):
        """Escribe un frame al video actual."""
        if self.writer and self.writer.isOpened():
            self.writer.write(frame)

    def stop_recording(self):
        """Detiene la grabación actual."""
        filepath = self.current_file
        if self.writer:
            self.writer.release()
            self.writer = None
            self.current_file = None
            logger.info(f"⏹️  Grabación finalizada: {filepath}")
        return filepath

    @property
    def is_recording(self):
        return self.writer is not None and self.writer.isOpened()


# ============================================================
# MÓDULO DE DESCRIPCIÓN CON GEMINI
# ============================================================

class GeminiDescriber:
    """Genera una descripción corta de la escena usando Gemini Vision."""

    def __init__(self, api_key, model, prompt):
        self.enabled = bool(api_key and api_key != "TU_API_KEY_GEMINI" and genai)
        self.model_name = model
        self.prompt = prompt
        self.model = None

        if not self.enabled:
            logger.info("ℹ️  Gemini no configurado o dependencia ausente. Generación de análisis desactivada.")
            return

        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(model)
            logger.info(f"✅ Gemini habilitado con modelo: {model}")
        except Exception as e:
            logger.error(f"Error inicializando Gemini: {e}")
            self.enabled = False

    def describe_image(self, image_path, retries=3):
        if not self.enabled or not self.model:
            return None

        for attempt in range(retries):
            try:
                with open(image_path, "rb") as f:
                    image_bytes = f.read()

                response = self.model.generate_content([
                    {"text": self.prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_bytes
                        }
                    }
                ])

                if response and response.candidates:
                    return response.candidates[0].content.parts[0].text.strip()
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "Quota" in error_msg or "503" in error_msg:
                    if attempt < retries - 1:
                        logger.warning(f"⚠️ Cuota de Gemini excedida en FOTO (intento {attempt+1}/{retries}). Reintentando en 35s...")
                        time.sleep(35)
                        continue
                logger.error(f"Error al describir imagen con Gemini: {e}")
                break

        return None

    def describe_video(self, video_path, retries=3):
        """Sube un video a Gemini, espera a que se procese y lo analiza con reintentos."""
        if not self.enabled or not self.model:
            return None

        try:
            logger.info(f"⏳ Subiendo video a Gemini para análisis detallado: {video_path}")
            video_file = genai.upload_file(path=video_path)
            
            # Esperar a que Gemini procese el video
            while video_file.state.name == 'PROCESSING':
                time.sleep(2)
                video_file = genai.get_file(video_file.name)
                
            if video_file.state.name == 'FAILED':
                logger.error("❌ Fallo al procesar el video continuo.")
                return None
                
            logger.info("✅ Video procesado en la nube. Solicitando análisis...")
            prompt = (
                "Este es un video de la cámara de seguridad local. "
                "Escribe estrictamente en este formato exacto:\n\n"
                "RESUMEN:\n"
                "(Escribe 2 líneas con el resumen de la escena, si interactúan con cosas, agarran dinero etc)\n\n"
                "DETALLE:\n"
                "(Escribe minuciosamente lo que pasó en el video, como a los 0:05 sacó algo, 0:10 etc.)"
            )
            
            for attempt in range(retries):
                try:
                    response = self.model.generate_content([video_file, prompt])
                    break # Salir del bucle si fue exitoso
                except Exception as e:
                    error_msg = str(e)
                    if ("429" in error_msg or "Quota" in error_msg or "503" in error_msg) and attempt < retries - 1:
                        logger.warning(f"⚠️ Cuota de Gemini excedida en VIDEO (intento {attempt+1}/{retries}). Reintentando en 35s...")
                        time.sleep(35)
                        continue
                    logger.error(f"Error al analizar video con Gemini: {e}")
                    raise # Forzar el borrado del archivo en caso de error insalvable
            
            # Borrar archivo de la nube para no consumir almacenamiento de Gemini 
            try:
                genai.delete_file(video_file.name)
            except Exception:
                pass
            
            if response and response.candidates:
                return response.candidates[0].content.parts[0].text.strip()
        except Exception as e:
            # Capturamos cualquier otro error grave no cubierto
            pass

        return None

# ============================================================
# SISTEMA PRINCIPAL
# ============================================================

class SecurityCamera:
    """Sistema principal que coordina todos los módulos."""

    def __init__(self):
        self.telegram = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
        self.motion_detector = MotionDetector(
            threshold=MOTION_THRESHOLD,
            blur_size=MOTION_BLUR_SIZE,
            dilate_iterations=MOTION_DILATE_ITERATIONS
        )
        self.face_recognizer = FaceRecognizer(
            KNOWN_FACES_DIR, FACE_RECOGNITION_TOLERANCE
        ) if ENABLE_FACE_RECOGNITION else None
        self.recorder = VideoRecorder(
            RECORDINGS_DIR, VIDEO_CODEC, CAMERA_FPS, CAMERA_RESOLUTION
        )
        self.describer = GeminiDescriber(
            GEMINI_API_KEY, GEMINI_MODEL, GEMINI_PROMPT
        )

        self.last_alert_time = 0
        self.frame_count = 0
        self.events_today = []
        self.running = False

    def _draw_overlays(self, frame, contours, faces=None):
        """Dibuja rectángulos de movimiento y caras en el frame."""
        # Rectángulos de movimiento (verde)
        for contour in contours:
            if cv2.contourArea(contour) > MOTION_THRESHOLD // 4:
                (x, y, w, h) = cv2.boundingRect(contour)
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

        # Rectángulos de caras
        if faces:
            for face in faces:
                top, right, bottom, left = face['location']
                color = (0, 255, 0) if face['known'] else (0, 0, 255)  # Verde=conocido, Rojo=desconocido
                cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                cv2.putText(frame, face['name'], (left, top - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        # Timestamp
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, timestamp, (10, frame.shape[0] - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        return frame

    def _save_snapshot(self, frame):
        """Guarda una captura temporal para enviar por Telegram."""
        path = os.path.join(RECORDINGS_DIR, "snapshot_temp.jpg")
        cv2.imwrite(path, frame)
        return path

    def _handle_motion_event(self, frame, faces):
        """Maneja un evento de movimiento detectado."""
        now = time.time()
        timestamp = datetime.datetime.now()

        # Registrar evento
        event = {
            'time': timestamp.strftime("%H:%M:%S"),
            'faces': [f['name'] for f in faces] if faces else [],
            'unknown_count': len([f for f in faces if not f['known']]) if faces else 0
        }
        self.events_today.append(event)

        # Cooldown para alertas
        if now - self.last_alert_time < COOLDOWN_SECONDS:
            return

        self.last_alert_time = now

        # Preparar alerta
        snapshot_path = self._save_snapshot(frame)

        # Análisis opcional
        ai_description = None
        if self.describer and self.describer.enabled:
            ai_description = self.describer.describe_image(snapshot_path)

        face_info = ""
        if faces:
            known = [f['name'] for f in faces if f['known']]
            unknown_count = len([f for f in faces if not f['known']])
            if known:
                face_info += f"\n👤 Identificados: {', '.join(known)}"
            if unknown_count:
                face_info += f"\n⚠️ Desconocidos: {unknown_count}"

        if ai_description:
            face_info += f"\n🤖 Análisis: {ai_description}"
        
        caption = (
            f"🚨 <b>MOVIMIENTO DETECTADO</b>\n"
            f"📅 {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
            f"{face_info}"
        )

        # Enviar alerta en segundo plano
        self.telegram.send_async(self.telegram.send_photo, snapshot_path, caption)
        logger.info(f"🚨 Movimiento detectado! Caras: {[f['name'] for f in faces] if faces else 'ninguna'}")

    def _process_finished_video(self, filepath):
        """Analiza el video completo y envía un resumen por Telegram."""
        if not filepath or not os.path.exists(filepath):
            return

        ai_description = None
        if self.describer and self.describer.enabled:
            ai_description = self.describer.describe_video(filepath)

        if ai_description:
            # Guardamos la descripción larga en un .txt adjunto al video
            txt_path = filepath.replace(".mp4", ".txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(ai_description)
            logger.info(f"📄 Resumen guardado en: {txt_path}")

            # Extraemos del texto generado solo la parte del RESUMEN
            resumen_corto = ai_description
            if "DETALLE:" in ai_description:
                resumen_corto = ai_description.split("DETALLE:")[0].replace("RESUMEN:", "").strip()

            folder_name = os.path.basename(os.path.dirname(filepath))
            msg = f"📼 <b>GRABACIÓN GUARDADA LOCALMENTE:</b>\n"
            msg += f"📂 {folder_name}\n\n"
            msg += f"🤖 <b>RESUMEN DE LA ACCIÓN:</b>\n{resumen_corto}"
            self.telegram.send_async(self.telegram.send_message, msg)
        else:
            # Si el análisis falla, solo notificamos que se cerró
            msg = f"📼 <b>GRABACIÓN FINALIZADA</b>\n"
            msg += f"📂 Ubicación: {filepath}"
            self.telegram.send_async(self.telegram.send_message, msg)

    def _send_daily_summary(self):
        """Envía resumen del día por Telegram."""
        if not self.events_today:
            summary = "📊 <b>Resumen del día</b>\n\n✅ Sin eventos de movimiento hoy."
        else:
            summary = f"📊 <b>Resumen del día</b>\n\n"
            summary += f"📌 Total de eventos: {len(self.events_today)}\n\n"

            for i, event in enumerate(self.events_today, 1):
                faces_str = ", ".join(event['faces']) if event['faces'] else "Sin rostros"
                summary += f"  {i}. ⏰ {event['time']} - {faces_str}\n"

            # Estadísticas
            total_unknown = sum(e['unknown_count'] for e in self.events_today)
            if total_unknown:
                summary += f"\n⚠️ Visitas de desconocidos: {total_unknown}"

        self.telegram.send_async(self.telegram.send_message, summary)
        self.events_today = []  # Reset para el nuevo día



    def run(self):
        """Bucle principal del sistema."""
        logger.info("=" * 50)
        logger.info("🎥 CÁMARA DE SEGURIDAD INICIADA")
        logger.info("=" * 50)

        # Abrir cámara
        cap = cv2.VideoCapture(CAMERA_SOURCE)
        if not cap.isOpened():
            logger.error("❌ No se pudo abrir la cámara. Verifica CAMERA_SOURCE.")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_RESOLUTION[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_RESOLUTION[1])
        # Intentar obtener FPS real de la cámara, si falla usar el por defecto
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        if actual_fps > 0:
            self.recorder.fps = actual_fps
            
        logger.info(f"📷 Cámara abierta: {CAMERA_RESOLUTION[0]}x{CAMERA_RESOLUTION[1]} @ {self.recorder.fps}fps")

        self.running = True
        recording_end_time = 0
        last_summary_date = None
        last_faces = []

        # Notificar inicio
        self.telegram.send_async(
            self.telegram.send_message,
            "🟢 <b>Sistema de seguridad activado</b>\n"
            f"📷 Resolución: {CAMERA_RESOLUTION[0]}x{CAMERA_RESOLUTION[1]}\n"
            f"🔍 Reconocimiento facial: {'Sí' if ENABLE_FACE_RECOGNITION else 'No'}"
        )

        try:
            while self.running:
                ret, frame = cap.read()
                if not ret:
                    logger.warning("⚠️  Frame perdido, reconectando...")
                    time.sleep(1)
                    cap.release()
                    cap = cv2.VideoCapture(CAMERA_SOURCE)
                    continue

                self.frame_count += 1

                # --- Detección de movimiento ---
                motion, area, contours = self.motion_detector.detect(frame)

                # --- Reconocimiento facial (cada N frames si hay movimiento) ---
                if motion and self.face_recognizer and self.face_recognizer.available:
                    # Chequea caras inmediatamente en el primer frame de movimiento, o cada 5 frames
                    if not last_faces or self.frame_count % FACE_CHECK_INTERVAL == 0:
                        last_faces = self.face_recognizer.identify_faces(frame)
                elif not motion:
                    last_faces = [] # Limpiar caras si no hay movimiento para no arrastrarlas al siguiente evento

                # --- Dibujar overlays ---
                display_frame = self._draw_overlays(frame.copy(), contours, last_faces)

                # --- Manejar eventos ---
                if motion:
                    if not self.recorder.is_recording:
                        h, w = display_frame.shape[:2]
                        self.recorder.start_recording(frame_size=(w, h))
                    recording_end_time = time.time() + RECORD_SECONDS_AFTER

                    self._handle_motion_event(display_frame, last_faces)

                # --- Grabación ---
                if self.recorder.is_recording:
                    self.recorder.write_frame(display_frame) # Guardar display_frame para que incluya la hora y recuadros verdes
                    if not motion and time.time() >= recording_end_time:
                        filepath = self.recorder.stop_recording()
                        if filepath:
                            # Inicia el procesamiento del video en segundo plano al finalizar
                            threading.Thread(target=self._process_finished_video, args=(filepath,), daemon=True).start()

                # --- Resumen diario ---
                if ENABLE_DAILY_SUMMARY:
                    now = datetime.datetime.now()
                    if (now.hour == SUMMARY_HOUR and
                        now.minute == SUMMARY_MINUTE and
                        last_summary_date != now.date()):
                        self._send_daily_summary()
                        last_summary_date = now.date()

                # --- Mostrar ventana (comentar en Raspberry Pi sin monitor) ---
                cv2.imshow("Seguridad", display_frame)
                key = cv2.waitKey(1) & 0xFF

                if key == ord('q'):
                    logger.info("🛑 Salida solicitada por usuario (tecla Q)")
                    break
                elif key == ord('s'):
                    # Captura manual
                    path = self._save_snapshot(display_frame)
                    logger.info(f"📸 Captura manual guardada: {path}")

        except KeyboardInterrupt:
            logger.info("🛑 Interrumpido por usuario (Ctrl+C)")
        finally:
            self.running = False
            if self.recorder.is_recording:
                self.recorder.stop_recording()
            cap.release()
            cv2.destroyAllWindows()

            self.telegram.send_async(
                self.telegram.send_message,
                "🔴 <b>Sistema de seguridad detenido</b>"
            )
            time.sleep(2)  # Esperar a que se envíe el mensaje
            logger.info("Sistema finalizado correctamente.")


# ============================================================
# PUNTO DE ENTRADA
# ============================================================

if __name__ == "__main__":
    print("""
    ==============================================
    |   [!] CAMARA DE SEGURIDAD INTELIGENTE      |
    |                                            |
    |   Controles:                               |
    |   Q = Salir                                |
    |   S = Captura manual                       |
    ==============================================
    """)

    camera = SecurityCamera()
    camera.run()
