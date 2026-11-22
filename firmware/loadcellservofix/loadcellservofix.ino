#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ESP32Servo.h>
#include "HX711.h"

// ================= KONFIGURASI (EDIT BAGIAN INI) =================
const char* WIFI_SSID  = "Zafar_MDR";
const char* WIFI_PASS  = "vavifar123";
const char* SERVER_URL = "192.168.1.12:5000/api/berat";  // IP laptop yang menjalankan Flask

const float         AMBANG_KENDARAAN_CM = 16;     // jarak di bawah ini = ada kendaraan
const unsigned long KONFIRMASI_MS       = 300;    // kendaraan harus terdeteksi stabil selama ini
const unsigned long TUNDA_TUTUP_MS      = 1000;   // setelah kendaraan lewat, 3 detik lalu servo menutup
const unsigned long TUNGGU_MAKS_MS      = 5000;   // tidak ada kendaraan sama sekali -> tutup sendiri setelah 5 detik
const unsigned long KENDARAAN_MAKS_MS   = 15000;  // "kendaraan" terdeteksi terus selama ini -> tutup paksa
// =================================================================

// ---------- Pin ----------
const int LOADCELL_DOUT_PIN = 16;
const int LOADCELL_SCK_PIN  = 4;
const int SERVO_PIN         = 18;
const int BUTTON_PIN        = 19;  // tombol antara GPIO19 dan GND
const int TRIG_PIN          = 23;
const int ECHO_PIN          = 22;  // lewat pembagi tegangan (1k atas + 2k bawah)

// ---------- Kalibrasi ----------
const float CALIBRATION_FACTOR = 1026.33179;

// ---------- Objek ----------
HX711 scale;
Servo myServo;

// ---------- Servo & tombol ----------
bool servoDi90 = false;
bool lastButtonState = HIGH;
unsigned long lastButtonTime = 0;
const unsigned long DEBOUNCE_MS = 50;

// ---------- Status gerbang ----------
enum Gerbang { G_TUTUP, G_MENUNGGU, G_KENDARAAN, G_BERSIH };
Gerbang gerbang = G_TUTUP;
unsigned long waktuBuka = 0;
unsigned long waktuMulaiAda = 0;
unsigned long waktuBersih = 0;
unsigned long waktuKendaraan = 0;

// ---------- Timbangan ----------
const int N_SAMPLE = 5;
float samples[N_SAMPLE] = {0};
int sampleIdx = 0;
int sampleCount = 0;
float beratTerakhir = 0.0;

// ---------- Ultrasonic (median 5 bacaan) ----------
const int N_JARAK = 5;
const float JARAK_KOSONG = 400.0;   // nilai untuk "tidak ada pantulan"
float bufJarak[N_JARAK] = {400, 400, 400, 400, 400};
int idxJarak = 0;
float jarakCm = -1;                 // hasil median; -1 = kosong/tidak ada pantulan
unsigned long lastJarak = 0;
const unsigned long JARAK_INTERVAL_MS = 60;

// ---------- Waktu tampil & kirim ----------
unsigned long lastPrint = 0;
const unsigned long PRINT_INTERVAL_MS = 500;
unsigned long lastSend = 0;
const unsigned long SEND_INTERVAL_MS = 500;
unsigned long lastReconnect = 0;
const unsigned long RECONNECT_INTERVAL_MS = 10000;

// ---------- WiFi ----------
void setupWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true);
  delay(100);

  Serial.println("Scan WiFi...");
  int n = WiFi.scanNetworks();
  bool ketemu = false;
  for (int i = 0; i < n; i++) {
    Serial.printf("  %s (sinyal %d dBm)\n", WiFi.SSID(i).c_str(), WiFi.RSSI(i));
    if (WiFi.SSID(i) == WIFI_SSID) ketemu = true;
  }
  if (!ketemu) Serial.println(">> SSID TIDAK TERLIHAT. Kemungkinan 5GHz / nama salah / terlalu jauh.");

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
    Serial.printf("\nWiFi GAGAL, status kode: %d\n", WiFi.status());
  }
}

// ---------- Setup ----------
void setup() {
  Serial.begin(115200);
  setCpuFrequencyMhz(160);

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);

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

// ---------- Servo / gerbang ----------
void bukaGerbang() {
  servoDi90 = true;
  myServo.write(90);
  gerbang = G_MENUNGGU;
  waktuBuka = millis();
  waktuMulaiAda = 0;
  Serial.println("Gerbang BUKA, menunggu kendaraan lewat...");
}

void tutupGerbang(const char* alasan) {
  servoDi90 = false;
  myServo.write(0);
  gerbang = G_TUTUP;
  waktuMulaiAda = 0;
  Serial.printf("Gerbang TUTUP (%s)\n", alasan);
}

void cekGerbang() {
  if (gerbang == G_TUTUP) return;

  bool ada = (jarakCm > 0 && jarakCm < AMBANG_KENDARAAN_CM);

  switch (gerbang) {
    case G_MENUNGGU:
      if (ada) {
        if (waktuMulaiAda == 0) waktuMulaiAda = millis();
        if (millis() - waktuMulaiAda >= KONFIRMASI_MS) {
          gerbang = G_KENDARAAN;
          waktuKendaraan = millis();
          Serial.println("Kendaraan terdeteksi, sedang lewat...");
        }
      } else {
        waktuMulaiAda = 0;
        if (millis() - waktuBuka >= TUNGGU_MAKS_MS) {
          tutupGerbang("tidak ada kendaraan, timeout");
        }
      }
      break;

    case G_KENDARAAN:
      if (!ada) {
        gerbang = G_BERSIH;
        waktuBersih = millis();
        Serial.println("Kendaraan sudah lewat, menunggu sebelum menutup...");
      } else if (millis() - waktuKendaraan >= KENDARAAN_MAKS_MS) {
        tutupGerbang("batas waktu kendaraan");
      }
      break;

    case G_BERSIH:
      if (ada) {
        gerbang = G_KENDARAAN;   // kendaraan muncul lagi, batalkan penutupan
        waktuKendaraan = millis();
      } else if (millis() - waktuBersih >= TUNDA_TUTUP_MS) {
        tutupGerbang("kendaraan sudah lewat");
      }
      break;

    default:
      break;
  }
}

// ---------- Tombol fisik ----------
void bacaTombol() {
  bool buttonState = digitalRead(BUTTON_PIN);

  if (lastButtonState == HIGH && buttonState == LOW &&
      millis() - lastButtonTime > DEBOUNCE_MS) {
    lastButtonTime = millis();
    if (!servoDi90) {
      bukaGerbang();               // buka + masuk mode otomatis
    } else {
      tutupGerbang("manual");      // tekan lagi = tutup paksa
    }
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

// ---------- Ultrasonic ----------
float medianJarak() {
  float tmp[N_JARAK];
  for (int i = 0; i < N_JARAK; i++) tmp[i] = bufJarak[i];
  for (int i = 0; i < N_JARAK - 1; i++)
    for (int j = 0; j < N_JARAK - 1 - i; j++)
      if (tmp[j] > tmp[j + 1]) { float t = tmp[j]; tmp[j] = tmp[j + 1]; tmp[j + 1] = t; }
  return tmp[N_JARAK / 2];
}

void bacaJarak() {
  if (millis() - lastJarak < JARAK_INTERVAL_MS) return;
  lastJarak = millis();

  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long durasi = pulseIn(ECHO_PIN, HIGH, 25000);   // timeout 25 ms (~4 m)
  float cm = (durasi == 0) ? JARAK_KOSONG : durasi * 0.0343 / 2.0;
  if (cm < 2.0 || cm > JARAK_KOSONG) cm = JARAK_KOSONG;   // di luar jangkauan = kosong

  bufJarak[idxJarak] = cm;
  idxJarak = (idxJarak + 1) % N_JARAK;

  float med = medianJarak();
  jarakCm = (med >= JARAK_KOSONG) ? -1 : med;
}

// ---------- Kirim ke Flask & terima perintah ----------
void kirimKeServer() {
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - lastReconnect >= RECONNECT_INTERVAL_MS) {
      lastReconnect = millis();
      Serial.println("WiFi putus, mencoba konek ulang...");
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASS);
    }
    return;
  }

  HTTPClient http;
  http.begin(SERVER_URL);
  http.setTimeout(2000);
  http.addHeader("Content-Type", "application/json");

  const char* namaGerbang[] = {"tutup", "menunggu", "kendaraan", "bersih"};
  String body = "{\"berat\":" + String(beratTerakhir, 1) +
                ",\"jarak\":" + String(jarakCm, 1) +
                ",\"servo\":" + (servoDi90 ? "90" : "0") +
                ",\"gerbang\":\"" + namaGerbang[gerbang] + "\"}";
  int code = http.POST(body);

  if (code == 200) {
    String perintah = http.getString();
    perintah.trim();

    if (perintah == "buka") {
      Serial.println("Perintah web: BUKA");
      bukaGerbang();
    } else if (perintah == "servo90") {
      gerbang = G_TUTUP;
      servoDi90 = true;
      myServo.write(90);
      Serial.println("Perintah web: servo 90 (manual)");
    } else if (perintah == "servo0") {
      gerbang = G_TUTUP;
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
  } else {
    Serial.printf("Gagal kirim ke server, kode: %d\n", code);
  }

  http.end();
}

// ---------- Loop ----------
void loop() {
  bacaTimbangan();
  bacaJarak();
  cekGerbang();

  if (millis() - lastPrint >= PRINT_INTERVAL_MS) {
    lastPrint = millis();
    Serial.printf("Berat: %.1f g | Jarak: %.1f cm | Gerbang: %d\n", beratTerakhir, jarakCm, (int)gerbang);
  }

  if (millis() - lastSend >= SEND_INTERVAL_MS) {
    lastSend = millis();
    kirimKeServer();
  }
}