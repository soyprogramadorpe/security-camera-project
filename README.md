# 🔒 Cámara de Seguridad Inteligente

Sistema de vigilancia doméstica local con detección de movimiento, reconocimiento facial, alertas instantáneas por Telegram e integración avanzada con IA para análisis de video.

> **Solo graba cuando pasa algo.** No más revisar horas de video vacío — recibes alertas con foto directo en tu celular apenas inicia el movimiento, y un sumario inteligente cuando finaliza.

## ✨ Características

- **Detección de Movimiento** — Compara frames en tiempo real ignorando cambios menores de luz.
- **Reconocimiento Facial** — Identifica personas conocidas vs. visitantes desconocidos.
- **Alertas por Telegram** — Foto + información al instante en tu celular durante una intrusión.
- **Análisis de Video IA** — Sin interrumpir la vigilancia, analiza el video de forma asíncrona guardado localmente y te envía un resumen inteligente por Telegram.
- **Grabación Limpia** — Guarda videos quemados con su respectiva estampa de tiempo junto con transcripciones detalladas de todos los incidentes en carpetas aisladas por fecha y hora.
- **Resumen Diario** — Recibe un informe estadístico de todos los eventos del día a la hora que programes.

## 📁 Estructura del Proyecto

```
security-camera-project/
├── security_camera.py            # Sistema principal (ejecutar este archivo)
├── requirements.txt              # Dependencias de Python
├── .env.example                  # Molde de variables de entorno
├── .env                          # Archivo de configuración privada (Tus Tokens)
├── .gitignore                    # Reglas de exclusión de git
├── rostros_conocidos/            # Carpeta para colocar fotos de personas conocidas
├── grabaciones/                  # Videos, análisis de texto .txt y fotos
└── README.md                     # Este archivo documental
```

## 🚀 Instalación Rápida

### 0. (Opcional) Dlib para Windows
- Si deseas usar la funcionalidad avanzada de reconocer rostros, requieres CMake y compiladores de C++ instalados en tu sistema para construir el motor.
- Si solo quieres detección de movimiento y grabación inteligente, omite esto y simplemente cambia `ENABLE_FACE_RECOGNITION = False` dentro de la configuración del código.

### 1. Descarga el repositorio
```bash
git clone https://github.com/soyprogramadorpe/security-camera-project.git
cd security-camera-project
```

### 2. Instalar las dependencias
```bash
pip install -r requirements.txt
```

### 3. Configuración del proyecto
Copia el archivo `.env.example` dejándolo como `.env` puro y pega adentro tus datos:
```env
TELEGRAM_BOT_TOKEN="TU_TOKEN_DE_TELEGRAM"
TELEGRAM_CHAT_ID="TU_CHAT_ID"
GEMINI_API_KEY="TU_API_KEY_AQUI"
CAMERA_SOURCE="0"
```
1. **Telegram:** Consigue un Bot Token desde `@BotFather` y tu Chat ID personal desde `@userinfobot`. 
2. **Gemini:** La API Key la obtienes de Google AI Studio, es requerida para el análisis final de video con Gemini 2.5 Flash.

### 4. (Opcional) Entrenar rostros
Coloca fotos individuales en formato `.jpg` en la carpeta `rostros_conocidos/`. El nombre del archivo se detectará como el nombre de la persona (ej. `sergio.jpg`). 

### 5. Encender las cámaras
```bash
python security_camera.py
```

## ⌨️ Controles
Manteniendo activa la ventana de visualización:
| Tecla | Acción |
|-------|--------|
| `Q` | Apaga el sistema de seguridad terminando los procesos en limpio |
| `S` | Genera un reporte manual de estado y fotografía |

## ⚙️ Arquitectura de Almacenamiento
El programa se comunica directamente con la API local de tu red o USB. En el instante que detecta cambios:
1. Toma una **fotografía de emergencia inmediata** y la expide por Telegram reportando el suceso.
2. Inicializa un archivo local MP4 en sincronismo con tus fotogramas detectando y dibujando cuadros de intrusos y marca horaria.
3. El archivo corta y se blinda segundos después de ver que la habitación se pacifica.
4. Un proceso secundario en background **lee el video y redacta una cronología súper detallada** de la intrusión que guarda localmente en el sub-directorio de grabaciones `(ej: motion_YYYYMM...txt)`.
5. Extrae únicamente un **resumen conciso** y te lo chatea a Telegram indicando la ruta local para no agotar tu ancho de banda en la calle.

## 📜 Licencia

MIT License — Implementa como necesites.
