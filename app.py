from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import PyPDF2
from gtts import gTTS
import os
import uuid
from datetime import datetime
import threading
import time
import concurrent.futures
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)

# Configurar la aplicación para servir archivos estáticos
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)  # Permitir peticiones desde cualquier origen

# Configuración
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
# Límite de tamaño de subida (10 MB)
MAX_UPLOAD_SIZE = 10 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Limpiar archivos antiguos cada hora
def cleanup_old_files():
    while True:
        time.sleep(3600)  # Cada hora
        try:
            now = time.time()
            # Limpiar archivos más antiguos de 1 hora
            for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER]:
                for filename in os.listdir(folder):
                    filepath = os.path.join(folder, filename)
                    if os.path.isfile(filepath):
                        if now - os.path.getmtime(filepath) > 3600:
                            os.remove(filepath)
        except Exception as e:
            print(f"Error en limpieza: {e}")

# Iniciar hilo de limpieza
cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()

# Ruta para servir el frontend
@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

# Ruta para verificar el estado de la API
@app.route('/api/status')
def api_status():
    return jsonify({
        "message": "PDF a Voz API - Servidor funcionando",
        "version": "1.0",
        "endpoints": {
            "/api/convert": "POST - Convertir PDF a MP3",
            "/api/download/<filename>": "GET - Descargar archivo MP3"
        }
    })

@app.route('/api/ping')
def api_ping():
    """Simple endpoint para comprobar conectividad (útil si el navegador bloquea /api/status)."""
    return jsonify({"pong": True, "timestamp": datetime.now().isoformat()})

# Log de peticiones entrantes y tamaño
@app.before_request
def log_request_info():
    if request.path.startswith('/api'):
        content_length = request.headers.get('Content-Length')
        logger.info("Incoming request: %s %s Content-Length=%s", request.method, request.path, content_length)

# --- Asynchronous conversion (returns job id) ---
# Job management
jobs = {}
jobs_lock = threading.Lock()
JOB_TIMEOUT = 300  # seconds

@app.route('/api/convert', methods=['POST'])
def convert_pdf_to_speech():
    # Validar que se envió un archivo
    if 'pdf' not in request.files:
        return jsonify({"error": "No se envió ningún archivo PDF"}), 400

    pdf_file = request.files['pdf']

    if pdf_file.filename == '':
        return jsonify({"error": "Nombre de archivo vacío"}), 400

    if not pdf_file.filename.endswith('.pdf'):
        return jsonify({"error": "El archivo debe ser PDF"}), 400

    # Obtener parámetros
    voice = request.form.get('voice', 'es-ES')
    speed = request.form.get('speed', 'normal')

    # Mapeo de voces
    voice_mapping = {
        'es-ES': ('es', 'es'),
        'es-MX': ('es', 'com.mx'),
        'es-AR': ('es', 'com.ar'),
        'en-US': ('en', 'us')
    }

    lang, tld = voice_mapping.get(voice, ('es', 'es'))
    slow = (speed == 'lento')

    # Generar nombres únicos
    job_id = str(uuid.uuid4())
    pdf_filename = f"{job_id}.pdf"
    mp3_filename = f"{job_id}.mp3"

    pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
    mp3_path = os.path.join(OUTPUT_FOLDER, mp3_filename)

    # Comprobar tamaño del upload antes de guardar
    if request.content_length and request.content_length > MAX_UPLOAD_SIZE:
        return jsonify({"error": "Archivo demasiado grande (máx 10 MB)"}), 413

    # Guardar el PDF y encolar el trabajo
    pdf_file.save(pdf_path)
    with jobs_lock:
        jobs[job_id] = {
            'status': 'pending',
            'created': datetime.now().isoformat(),
            'progress': 0,
            'message': 'Queued',
            'filename': mp3_filename,
            'download_url': None,
            'error': None
        }

    # Lanzar thread en background
    thread = threading.Thread(target=lambda: do_conversion(job_id, pdf_path, mp3_path, voice, speed), daemon=True)
    thread.start()

    logger.info("Job %s queued (input=%s)", job_id, pdf_file.filename)
    return jsonify({'job_id': job_id, 'status_url': f'/api/jobs/{job_id}'}), 202


def do_conversion(job_id, pdf_path, mp3_path, voice, speed):
    """Función que realiza la conversión en background y actualiza el diccionario jobs."""
    try:
        with jobs_lock:
            jobs[job_id]['status'] = 'running'
            jobs[job_id]['progress'] = 5
            jobs[job_id]['message'] = 'Running'

        start_time = time.monotonic()

        # Mapear voz
        voice_mapping = {
            'es-ES': ('es', 'es'),
            'es-MX': ('es', 'com.mx'),
            'es-AR': ('es', 'com.ar'),
            'en-US': ('en', 'us')
        }
        lang, tld = voice_mapping.get(voice, ('es', 'es'))
        slow = (speed == 'lento')

        logger.info("Job %s: starting extraction", job_id)
        with jobs_lock:
            jobs[job_id]['progress'] = 20
            jobs[job_id]['message'] = 'Extracting text'

        # Run extraction with a timeout to avoid blocking the worker indefinitely
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(extract_text_from_pdf, pdf_path)
            try:
                text = future.result(timeout=JOB_TIMEOUT)
            except concurrent.futures.TimeoutError:
                raise Exception('Text extraction timed out')

        if not text.strip():
            raise Exception('No se pudo extraer texto del PDF')

        with jobs_lock:
            jobs[job_id]['progress'] = 50
            jobs[job_id]['message'] = 'Converting to speech'

        # Check timeout before heavy work
        elapsed = time.monotonic() - start_time
        if elapsed > JOB_TIMEOUT:
            raise Exception('Job timed out')

        logger.info("Job %s: initializing TTS", job_id)
        tts = gTTS(text=text, lang=lang, tld=tld, slow=slow, lang_check=False)

        # Save TTS with timeout
        elapsed = time.monotonic() - start_time
        remaining = max(5, JOB_TIMEOUT - elapsed)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(tts.save, mp3_path)
            try:
                future.result(timeout=remaining)
            except concurrent.futures.TimeoutError:
                raise Exception('TTS generation/saving timed out')

        # Limpiar PDF temporal
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        except Exception:
            pass

        # Mark success
        file_size = os.path.getsize(mp3_path)
        with jobs_lock:
            jobs[job_id]['status'] = 'success'
            jobs[job_id]['progress'] = 100
            jobs[job_id]['message'] = 'Completed'
            jobs[job_id]['download_url'] = f"/download/{jobs[job_id]['filename']}"

        elapsed = time.monotonic() - start_time
        logger.info("Job %s completed in %.1fs", job_id, elapsed)

    except Exception as e:
        logger.exception("Job %s failed: %s", job_id, e)
        with jobs_lock:
            jobs[job_id]['status'] = 'error'
            jobs[job_id]['error'] = str(e)
            jobs[job_id]['message'] = 'Failed'
        # Cleanup any files
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        except Exception:
            pass

    finally:
        # Ensure progress and message set
        with jobs_lock:
            if jobs[job_id]['status'] == 'running':
                jobs[job_id]['status'] = 'error'
                jobs[job_id]['message'] = 'Timeout or unknown error'

@app.route('/api/jobs/<job_id>', methods=['GET'])
def get_job_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({'error': 'Job no encontrado'}), 404
        return jsonify(job)

@app.route('/api/download/<filename>', methods=['GET'])
def download_file(filename):
    try:
        # Validar nombre de archivo por seguridad
        if not filename.endswith('.mp3') or '/' in filename or '\\' in filename:
            return jsonify({"error": "Nombre de archivo inválido"}), 400

        file_path = os.path.join(OUTPUT_FOLDER, filename)

        if not os.path.exists(file_path):
            return jsonify({"error": "Archivo no encontrado"}), 404

        return send_file(
            file_path,
            as_attachment=True,
            download_name=f"audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3",
            mimetype='audio/mpeg'
        )

    except Exception as e:
        return jsonify({"error": f"Error al descargar: {str(e)}"}), 500

def extract_text_from_pdf(pdf_path):
    """Extrae texto de un archivo PDF"""
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
        return text
    except Exception as e:
        raise Exception(f"Error al extraer texto: {str(e)}")

@app.route('/api/health', methods=['GET'])
def health_check():
    """Endpoint para verificar que el servidor está funcionando"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "uploads_folder": os.path.exists(UPLOAD_FOLDER),
        "outputs_folder": os.path.exists(OUTPUT_FOLDER)
    })

# --- Manejo global de errores para endpoints de la API (devuelve JSON en errores) ---
@app.errorhandler(404)
def handle_not_found(e):
    if request.path.startswith('/api'):
        return jsonify({'error': 'Endpoint no encontrado'}), 404
    return e

@app.errorhandler(Exception)
def handle_exception(e):
    # Devuelve JSON para errores en rutas /api; en otras rutas deja el comportamiento por defecto
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        code = e.code
        message = e.description
    else:
        code = 500
        message = str(e)
    if request.path.startswith('/api'):
        return jsonify({'error': f'Error interno: {message}'}), code
    # Para rutas no-API, relanzamos para mantener el modo debug o comportamiento por defecto
    raise e

if __name__ == '__main__':
    # Para desarrollo local
    app.run(debug=True, host='0.0.0.0', port=5000)