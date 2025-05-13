#include <WiFi.h>
#include <PubSubClient.h>
#include <SPI.h>
#include <MFRC522.h>

// Pines RFID
#define RST_PIN 22  
#define SS_PIN 5    
MFRC522 mfrc522(SS_PIN, RST_PIN);

// Credenciales WiFi
const char* ssid     = "wifi_ssid";
const char* password = "password";

// Broker MQTT
const char* mqtt_server = "IP_BROKER_MQTT";
const int   mqtt_port   = 1883;
const char* mqtt_topic  = "fabrica/herramientas";

// Nombre de la estación
String seccion = "nombre_seccion";

// Objetos WiFi y MQTT
WiFiClient espClient;
PubSubClient client(espClient);

void reconnectMQTT() {
  while (!client.connected()) {
    Serial.print("Intentando conectar MQTT...");
    bool ok = client.connect("ESP32Client");
    if (ok) {
      Serial.println("Conectado.");
    } else {
      Serial.print("Error, rc=");
      Serial.print(client.state());
      Serial.println(" intentando de nuevo en 5s");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  SPI.begin(18, 19, 23, 5);
  mfrc522.PCD_Init();

  // WiFi
  WiFi.begin(ssid, password);
  Serial.print("Conectando a WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi conectada.");

  Serial.println();

  // MQTT
  client.setServer(mqtt_server, mqtt_port);
  Serial.println("Listo para leer bloque 1 de la tarjeta");
}

void loop() {
  if (!client.connected()) reconnectMQTT();
  client.loop();

  if (!mfrc522.PICC_IsNewCardPresent() ||
      !mfrc522.PICC_ReadCardSerial()) {
    return;
  }

  // Autenticación
  byte block = 1, buffer[18], size = sizeof(buffer);
  MFRC522::MIFARE_Key key;
  for (byte i = 0; i < 6; i++) key.keyByte[i] = 0xFF;
  auto status = mfrc522.PCD_Authenticate(
    MFRC522::PICC_CMD_MF_AUTH_KEY_A, block, &key, &mfrc522.uid);
  if (status != MFRC522::STATUS_OK) {
    Serial.println("Auth error");
    mfrc522.PICC_HaltA();
    return;
  }

  // Construir UID
  String uidStr;
  for (byte i = 0; i < mfrc522.uid.size; i++) {
    if (mfrc522.uid.uidByte[i] < 0x10) uidStr += "0";
    uidStr += String(mfrc522.uid.uidByte[i], HEX);
  }
  uidStr.toUpperCase();

  // Leer bloque y recortar espacios
  status = mfrc522.MIFARE_Read(block, buffer, &size);
  String herramienta;
  if (status == MFRC522::STATUS_OK) {
    for (byte i = 0; i < 16; i++) {
      char c = char(buffer[i]);
      herramienta += isPrintable(c) ? c : '.';
    }
    herramienta.trim();
  } else {
    herramienta = "ERROR_READ";
  }

  // Sólo publicamos si la lectura fue exitosa
  if (herramienta != "ERROR_READ") {
    // JSON sin timestamp
    String payload = "{";
    payload += "\"uid\":\""         + uidStr        + "\",";
    payload += "\"herramienta\":\"" + herramienta   + "\",";
    payload += "\"seccion\":\""     + seccion       + "\"";
    payload += "}";

    if (client.publish(mqtt_topic, payload.c_str())) {
      Serial.print("Publicado: ");
      Serial.println(payload);
    } else {
      Serial.println("Error publicando MQTT");
    }
  } else {
    Serial.println("Lectura fallida; no se publica.");
  }

  mfrc522.PICC_HaltA();
  mfrc522.PCD_StopCrypto1();
  delay(2000);
}
