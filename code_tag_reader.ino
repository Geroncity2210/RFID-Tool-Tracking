#include <SPI.h>
#include <MFRC522.h>

#define RST_PIN 22  
#define SS_PIN 5    

MFRC522 mfrc522(SS_PIN, RST_PIN);

void setup() {
  Serial.begin(115200);
  SPI.begin(18, 19, 23, 5); // SCK, MISO, MOSI, SS
  mfrc522.PCD_Init();
  Serial.println("Acerca una tarjeta para leer bloque 1");
}

void loop() {
  // Espera a que haya una nueva tarjeta
  if (!mfrc522.PICC_IsNewCardPresent() || !mfrc522.PICC_ReadCardSerial()) return;

  byte block = 1;               // Bloque que deseas leer
  byte buffer[18];              // El bloque tiene 16 bytes + 2 de CRC
  byte size = sizeof(buffer);   

  // Clave por defecto
  MFRC522::MIFARE_Key key;
  for (byte i = 0; i < 6; i++) key.keyByte[i] = 0xFF;

  // Autenticación
  MFRC522::StatusCode status = mfrc522.PCD_Authenticate(
    MFRC522::PICC_CMD_MF_AUTH_KEY_A, block, &key, &(mfrc522.uid));

  if (status != MFRC522::STATUS_OK) {
    Serial.print("Error de autenticación: ");
    Serial.println(mfrc522.GetStatusCodeName(status));
    return;
  }

  Serial.print("UID de la tarjeta: ");
  for (byte i = 0; i < mfrc522.uid.size; i++) {
    Serial.print(mfrc522.uid.uidByte[i] < 0x10 ? "0" : "");
    Serial.print(mfrc522.uid.uidByte[i], HEX);
    Serial.print(" ");
  }
  Serial.println();

  // Lectura del bloque
  status = mfrc522.MIFARE_Read(block, buffer, &size);
  if (status != MFRC522::STATUS_OK) {
    Serial.print("Error al leer el bloque: ");
    Serial.println(mfrc522.GetStatusCodeName(status));
  } else {
    Serial.print("Contenido del bloque 1: ");
    for (byte i = 0; i < 16; i++) {
      Serial.write(buffer[i]);  // Muestra como texto
    }
    Serial.println();
  }

  mfrc522.PICC_HaltA();
  mfrc522.PCD_StopCrypto1();
  delay(2000);
}