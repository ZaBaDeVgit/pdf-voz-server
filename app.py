from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import PyPDF2
from gtts import gTTS
import os
import uuid
from datetime import datetime
import threading
import time

# Configurar la aplicación para servir archivos estáticos
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)  # Permitir peticiones desde cualquier origen

# Configuración
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
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

@app.route('/api/convert', methods=['POST'])
def convert_pdf_to_speech():
    try:
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
        unique_id = str(uuid.uuid4())
        pdf_filename = f"{unique_id}.pdf"
        mp3_filename = f"{unique_id}.mp3"

        pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
        mp3_path = os.path.join(OUTPUT_FOLDER, mp3_filename)

        # Guardar PDF temporalmente
        pdf_file.save(pdf_path)

        # Extraer texto del PDF
        text = extract_text_from_pdf(pdf_path)

        if not text.strip():
            os.remove(pdf_path)
            return jsonify({"error": "No se pudo extraer texto del PDF"}), 400

        # Convertir a voz
        tts = gTTS(
            text=text,
            lang=lang,
            tld=tld,
            slow=slow,
            lang_check=False
        )

        tts.save(mp3_path)

        # Limpiar PDF temporal
        os.remove(pdf_path)

        # Obtener tamaño del archivo
        file_size = os.path.getsize(mp3_path)

        return jsonify({
            "success": True,
            "message": "Conversión completada exitosamente",
            "filename": mp3_filename,
            "download_url": f"/download/{mp3_filename}",
            "file_size": file_size,
            "text_length": len(text),
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({
            "error": f"Error en la conversión: {str(e)}"
        }), 500

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