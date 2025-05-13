import sqlite3
import json
import time
import datetime
import requests
import threading
import paho.mqtt.client as mqtt

# ====== CONFIGURA TU CLAVE DE GEMINI ======
GEMINI_API_KEY = "AIzaSyCsK81-UUvv1rSLoVrLmsjMa8cheG8sLUE"
# Lista modelos disponibles (opcional, para verificar)
MODEL     = "gemini-2.0-flash"
ENDPOINT  = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
# ====== CONFIGURACIï¿½N UBIDOTS ======
UBI_TOKEN         = "BBUS-AEpYg9g22LzKRfemOhMbU0lNFJs3MA"
DEVICE_LABEL      = "rasp_gw"           # etiqueta de tu dispositivo en Ubidots
BUTTON_VAR_LABEL  = "gen_report"      # variable que actua como boton
UBI_MQTT_VAR       = "report" 
UBI_BASE_URL      = "https://industrial.api.ubidots.com/api/v1.6/devices"

# ====== CONFIGURACION MQTT ======
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "fabrica/herramientas"

# ====== CONFIGURACION BASE DE DATOS ======
DB_NAME = "uso_herramientas.db"

def inicializar_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            herramienta TEXT,
            seccion TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)
    ''')
    conn.commit()
    conn.close()

# ====== PROCESAMIENTO DE DATOS ======
def calcular_uso(herramienta):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp FROM registros WHERE herramienta = ? ORDER BY timestamp DESC LIMIT 1", (herramienta,))
    row = cursor.fetchone()
    conn.close()

    if row:
        ultima_fecha = datetime.datetime.fromisoformat(row[0])
        ahora = datetime.datetime.now()
        delta_horas = (ahora - ultima_fecha).total_seconds() / 3600
        return round(delta_horas, 2)
    else:
        return None  # Primer uso
    
def poll_button():
    """
    Hilo que cada segundo comprueba el valor del boton en Ubidots.
    Cuando detecta un '1' tras un '0', dispara generate_report().
    """
    last_state = 0
    url = f"{UBI_BASE_URL}/{DEVICE_LABEL}/{BUTTON_VAR_LABEL}/lv?token={UBI_TOKEN}"
    while True:
        try:
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            data = r.json()
            # Si viene un dict con "value", se usa; si no, es un float directamente
            if isinstance(data, dict):
                state = int(data.get("value", 0))
            else:
                state = int(data)
            print("Estado del boton: ",state)
        except Exception as e:
            print(f"[Ubidots] Error al leer boton: {e}")
            state = 0

        # Si pasa de 0 -> 1, generamos informe
        if state == 1 and last_state == 0:
            print("Boton de informe pulsado. Generando reporte...")
            generate_report()
        last_state = state

        time.sleep(0.5)

def generate_report():
    """
    Extrae de SQLite un resumen por herramienta y lo envia a Gemini.
    """
    # Consultar DB
    conn   = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT herramienta,
               COUNT(*) AS total_usos,
               MAX(timestamp) AS ultima_fecha
        FROM registros
        GROUP BY herramienta
    """)
    filas = cursor.fetchall()
    conn.close()

    # 2) Construir seccion de datos para el prompt
    resumen = ""
    for herramienta, total, ultima in filas:
        # parseo de fecha para calculo de delta
        ultima_dt = datetime.datetime.fromisoformat(ultima)
        horas_desde = round((datetime.datetime.now() - ultima_dt).total_seconds()/3600, 1)
        resumen += f"- {herramienta}: {total} usos, ultima vez hace {horas_desde} h\n"

    # 3) Construir prompt completo
    prompt = (
        "Por favor, genera un informe detallado del uso de herramientas en la planta:\n"
        f"{resumen}\n"
        "Incluye para cada herramienta recomendaciones de mantenimiento preventivo basado en que herramienta es y su naturaleza de uso"
        "Tambien provee un analisis del nivel de uso (bajo, moderado, alto)."
        "regresa el informe en formato json donde se divida en cada herramienta con sus respectivas recomendaciones (\"recomendacion\") y analisis por aparte (\"uso\")"
        "Asegúrate de que el JSON de salida sea válido y no incluyas texto explicativo antes o después del mismo"
        "Finalmente, procura ser lo mas consiso y breve posible, pues este resumen se debe visualizar en un dashboard"
        ""
    )

    informe = enviar_prompt_gemini(prompt)
    print(" Informe generado por IA:\n", informe)
    publish_report_mqtt(informe)
    
def enviar_prompt_gemini(prompt_text: str) -> str:
    """
    Envia cualquier prompt_text ya formateado a Gemini y devuelve la respuesta.
    """
    url = f"{ENDPOINT}?key={GEMINI_API_KEY}"
    payload = {
        "contents": [
            {"parts": [{"text": prompt_text}]}
        ]
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        print("Esperando respuesta de Gemini...")
    except requests.RequestException as e:
        print(f"[Error HTTP] {e}")
        return 0 # en caso de fallo se retorna 0 para controlar errores de mierda

    try:
        data      = resp.json()
        candidate = data["candidates"][0]
        part      = candidate["content"]["parts"][0]
        return part["text"] 
    except Exception as e:
        print(f"[Error de parsing] {e} : Payload: {resp.text}")
        return 0 # lo mismo

def publish_report_mqtt(report_text: str):
    """
    Recibe un string JSON generado por la IA y publica cada entrada en su respectiva variable en Ubidots.
    La variable tendrá el nombre de la herramienta, y en el contexto se enviarán las recomendaciones.
    """
    try:
        data = json.loads(report_text)
    except json.JSONDecodeError as e:
        print(f"[Error] JSON inválido desde la IA: {e}")
        return

    for herramienta, info in data.items():

        usos = info.get("usos_totales", 0)
        horas = info.get("ultima_vez_hace_horas", 0)
        uso_nivel = info.get("nivel_uso", "desconocido")
        recomendaciones = info.get("recomendaciones", [])

        context = {
            "usos": usos,
            "uso_nivel": uso_nivel,
            "ultima_vez_horas": horas,
            "recomendaciones": " | ".join(recomendaciones)
        }

        topic = f"/v1.6/devices/{DEVICE_LABEL}/{herramienta.lower().replace(" ", "_") + '_report'}/lv" # la misma conversion que con la recepción de mensajes, por si las moscas
        payload = json.dumps({
            "value": 1,
            "context": context
        })

        try:
            client.publish(topic, payload)
            print(f"[Ubidots MQTT] Publicado informe de {herramienta} en {topic}")
        except Exception as e:
            print(f"[Error] No se pudo publicar {herramienta}: {e}")

# ====== CALLBACK DE MQTT ======
def on_message(client, userdata, msg):
    """ Este cacho de código (hecho con mis manos, sin chatGPT) recibe y almacena los datos de la herramienta leida por los lectores
    se crea un topic con la herramienta como variable para publicar en ubidots, si esa variable no está creada, la plataforma la crea automáticamente"""
    payload     = json.loads(msg.payload.decode())
    herramienta = payload.get("herramienta", "").strip()
    seccion     = payload.get("seccion", "").strip()
    timestamp   = datetime.datetime.now()
    # Esta vaina es el label que va a aparecer en el ubidots ej: TIJERAS NYLON -> tijeras_nylon 
    tool_var_label = herramienta.lower().replace(" ", "_")
    topic       = f"/v1.6/devices/{DEVICE_LABEL}/{tool_var_label}/lv"

    print(f"Herramienta recibida: {herramienta} | Seccion: {seccion}")

    try:
        # Ubidots espera un JSON {"value": ...}
        # En el contexto le enviamos la herramienta, la sección y la hora para mostrarla en un widget previamente creado y configurado
        payload = json.dumps({"value": 1, "context": {"herramienta": herramienta, "seccion": seccion, "timestamp": timestamp}})
        client.publish(topic, payload)
        print(f"[Ubidots MQTT] Estado de la herramienta {herramienta} publicado en {topic}.")
    except Exception as e:
        print(f"[Ubidots MQTT] Error publicando estado: {e}")
    finally:
        # Finalmente el registro se guarda en la base de datos
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO registros (herramienta, seccion, timestamp) VALUES (?, ?, ?)",
                    (herramienta, seccion, timestamp))
        conn.commit()
        conn.close()



# ====== INICIALIZACION ======
inicializar_db()

client = mqtt.Client()
client.on_message = on_message

# Lanzar el hilo de Ubidots en background
t = threading.Thread(target=poll_button, daemon=True)
t.start()

client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.subscribe(MQTT_TOPIC)
print("Esperando datos desde ESP32...\n")
client.loop_forever()


