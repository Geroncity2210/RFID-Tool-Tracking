#include <SPI.h>
#include <MFRC522.h>

#define RST_PIN 22  
#define SS_PIN 5   

MFRC522 mfrc522(SS_PIN, RST_PIN);

void setup() {
  Serial.begin(115200);
  SPI.begin(18, 19, 23, 5); // SCK, MISO, MOSI, SS
  mfrc522.PCD_Init();
  Serial.println("Acercar RFID");
}

void loop() {
  if (!mfrc522.PICC_IsNewCardPresent() || !mfrc522.PICC_ReadCardSerial()) return;

  byte block = 1;
  byte dataBlock[16] = {'U','S','B',' ','H','U','B',' ',' ',' ',' ',' ',' ',' ',' ',' '}; 

  // Preparar clave (por defecto es 0xFF)
  MFRC522::MIFARE_Key key;
  for (byte i = 0; i < 6; i++) key.keyByte[i] = 0xFF;

  // Autenticación con la tarjeta
  MFRC522::StatusCode status = mfrc522.PCD_Authenticate(
    MFRC522::PICC_CMD_MF_AUTH_KEY_A, block, &key, &(mfrc522.uid));

  if (status != MFRC522::STATUS_OK) {
    Serial.print("Error de autenticación: ");
    Serial.println(mfrc522.GetStatusCodeName(status));
    return;
  }

  // Escritura
  status = mfrc522.MIFARE_Write(block, dataBlock, 16);
  if (status == MFRC522::STATUS_OK) {
    Serial.println("Datos escritos correctamente.");
  } else {
    Serial.print("Error al escribir: ");
    Serial.println(mfrc522.GetStatusCodeName(status));
  }

  mfrc522.PICC_HaltA();
  mfrc522.PCD_StopCrypto1();
  delay(2000);
}