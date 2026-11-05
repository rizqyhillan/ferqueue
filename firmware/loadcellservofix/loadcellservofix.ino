#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ESP32Servo.h>
#include "HX711.h"

// ================= KONFIGURASI (EDIT BAGIAN INI) =================
const char* WIFI_SSID  = "Ael";
const char* WIFI_PASS  = "kocakwoi";
const char* SERVER_URL = "http://10.10.190.45:5000/api/berat";  // IP laptop teman + port Flask

const unsigned long DURASI_BUKA_MS = 5000;  // servo terbuka berapa lama (ms) sebelum menutup otomatis
// =================================================================

// ---------- Pin ----------
const int LOADCELL_DOUT_PIN = 16;
const int LOADCELL_SCK_PIN  = 4;
const int SERVO_PIN         = 18;
const int BUTTON_PIN        = 19;  // tombol antara GPIO19 dan GND

// ---------- Kalibrasi ----------
const float CALIBRATION_FACTOR = 1026.33179;

// ---------- Objek ----------
HX711 scale;
Servo myServo;

// ---------- Status servo & tombol ----------
bool servoDi90 = false;
bool lastButtonState = HIGH;
unsigned long lastButtonTime = 0;
const unsigned long DEBOUNCE_MS = 50;

// ---------- Auto-tutup servo ----------
bool autoTutupAktif = false;
unsigned long waktuBuka = 0;

// ---------- Rata-rata bergerak timbangan ----------
const int N_SAMPLE = 5;
float samples[N_SAMPLE] = {0};
int sampleIdx = 0;
int sampleCount = 0;

// ---------- Waktu tampil & kirim ----------
unsigned long lastPrint = 0;
const unsigned long PRINT_INTERVAL_MS = 500;

unsigned long lastSend = 0;
const unsigned long SEND_INTERVAL_MS = 500;

float beratTerakhir = 0.0;

// ---------- WiFi ----------
void setupWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  Serial.print("Menghubungkan WiFi");
  unsigned long mulai = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - mulai < 20000) {
    delay(500);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("\nWiFi terhubung. IP ESP32: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nWiFi GAGAL terhubung (akan dicoba terus di background).");
  }
}

// ---------- Setup ----------
void setup() {
  Serial.begin(115200);
  setCpuFrequencyMhz(160);

  pinMode(BUTTON_PIN, INPUT_PULLUP);

  myServo.attach(SERVO_PIN);
  myServo.write(0);

  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);
  while (!scale.is_ready()) {
    Serial.println("HX711 tidak ditemukan / wiring terlepas.");
    delay(1000);
  }
  scale.set_scale(CALIBRATION_FACTOR);

  setupWiFi();

  Serial.println("Kosongkan load cell... tare dalam 5 detik.");
  delay(5000);
  scale.tare(20);
  Serial.println("Tare selesai. Siap.");
}

// ---------- Servo helper ----------
void bukaServoOtomatis() {
  servoDi90 = true;
  myServo.write(90);
  autoTutupAktif = true;
  waktuBuka = millis();   // kalau perintah buka datang lagi, timer di-reset
  Serial.println("Servo BUKA (auto-tutup dalam beberapa detik)");
}

void cekAutoTutup() {
  if (autoTutupAktif && millis() - waktuBuka >= DURASI_BUKA_MS) {
    autoTutupAktif = false;
    servoDi90 = false;
    myServo.write(0);
    Serial.println("Servo TUTUP otomatis");
  }
}

// ---------- Tombol fisik ----------
void bacaTombol() {
  bool buttonState = digitalRead(BUTTON_PIN);

  if (lastButtonState == HIGH && buttonState == LOW &&
      millis() - lastButtonTime > DEBOUNCE_MS) {
    lastButtonTime = millis();
    autoTutupAktif = false;   // kontrol manual membatalkan auto-tutup
    servoDi90 = !servoDi90;
    myServo.write(servoDi90 ? 90 : 0);
    Serial.println(servoDi90 ? "Servo ke 90 derajat" : "Servo kembali ke 0 derajat");
  }

  lastButtonState = buttonState;
}

// ---------- Timbangan ----------
void bacaTimbangan() {
  if (!scale.is_ready()) return;

  float berat = scale.get_units(1);

  samples[sampleIdx] = berat;
  sampleIdx = (sampleIdx + 1) % N_SAMPLE;
  if (sampleCount < N_SAMPLE) sampleCount++;

  float total = 0;
  for (int i = 0; i < sampleCount; i++) total += samples[i];
  beratTerakhir = total / sampleCount;

  if (fabs(beratTerakhir) < 0.3) beratTerakhir = 0.0;
}

// ---------- Kirim ke Flask & terima perintah ----------
void kirimKeServer() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi putus, menunggu reconnect...");
    return;
  }

  HTTPClient http;
  http.begin(SERVER_URL);
  http.setTimeout(2000);
  http.addHeader("Content-Type", "application/json");

  String body = "{\"berat\":" + String(beratTerakhir, 1) +
                ",\"servo\":" + (servoDi90 ? "90" : "0") + "}";
  int code = http.POST(body);

  if (code == 200) {
    String perintah = http.getString();
    perintah.trim();

    if (perintah == "buka") {
      Serial.println("Perintah web: BUKA");
      bukaServoOtomatis();
    } else if (perintah == "servo90") {
      autoTutupAktif = false;
      servoDi90 = true;
      myServo.write(90);
      Serial.println("Perintah web: servo 90");
    } else if (perintah == "servo0") {
      autoTutupAktif = false;
      servoDi90 = false;
      myServo.write(0);
      Serial.println("Perintah web: servo 0");
    } else if (perintah == "tare") {
      Serial.println("Perintah web: tare...");
      scale.tare(20);
      sampleCount = 0;
      sampleIdx = 0;
      beratTerakhir = 0.0;
      Serial.println("Tare selesai.");
    }
    // "none" = tidak ada perintah
  } else {
    Serial.printf("Gagal kirim ke server, kode: %d\n", code);
  }

  http.end();
}

// ---------- Loop ----------
void loop() {
  bacaTombol();
  bacaTimbangan();
  cekAutoTutup();

  if (millis() - lastPrint >= PRINT_INTERVAL_MS) {
    lastPrint = millis();
    Serial.print("Berat: ");
    Serial.print(beratTerakhir, 1);
    Serial.println(" g");
  }

  if (millis() - lastSend >= SEND_INTERVAL_MS) {
    lastSend = millis();
    kirimKeServer();
  }
}