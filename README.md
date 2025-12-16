# PDF a Voz - Servidor de Conversión

Aplicación web que convierte archivos PDF a archivos de audio MP3 utilizando síntesis de voz.

## Características

- Sube archivos PDF y conviértelos a audio MP3
- Soporte para múltiples idiomas
- Interfaz web intuitiva
- API RESTful para integraciones

## Requisitos

- Python 3.8+
- pip

## Instalación

1. Clona el repositorio:
   ```bash
   git clone https://github.com/tu-usuario/pdf-voz-server.git
   cd pdf-voz-server
   ```

2. Crea un entorno virtual (recomendado):
   ```bash
   python -m venv venv
   source venv/bin/activate  # En Windows: .\\venv\\Scripts\\activate
   ```

3. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

## Uso

1. Inicia el servidor:
   ```bash
   python app.py
   ```

2. Abre tu navegador en:
   ```
   http://localhost:5000
   ```

## Despliegue en Producción

Para desplegar en producción, considera usar:

1. **Render.com** (Recomendado para principiantes)
2. **PythonAnywhere** (Gratis para aplicaciones pequeñas)
3. **Heroku** (Requiere tarjeta de crédito para verificación)
4. **VPS** (DigitalOcean, Linode, AWS, etc.)

### Despliegue en Render.com

1. Crea una cuenta en [Render.com](https://render.com/)
2. Haz clic en "New" y selecciona "Web Service"
3. Conecta tu repositorio de GitHub
4. Configura el servicio:
   - Runtime: Python 3
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
5. Haz clic en "Create Web Service"

## API

### Convertir PDF a MP3
```
POST /convert
Content-Type: multipart/form-data

file: [archivo PDF]
lang: [código de idioma, opcional, por defecto 'es']
```

### Descargar archivo MP3
```
GET /download/<nombre_archivo>
```

## Licencia

MIT
