/*
  
  Timbangan + Ultrasonik + Servo gerbang -> MQTT (WebSocket Secure, port 443)

  Library yang harus diinstal (Library Manager):
    1. WebSockets        (Markus Sattler)
    2. MQTTPubSubClient  (hideakitai)
    3. ESP32Servo
    4. HX711             (Bogdan Necula)

  Topik (unik pakai NIM):
    publish   : <NIM>/data       -> JSON {"berat":..,"jarak":..,"servo":..,"gerbang":".."}
    subscribe : <NIM>/perintah   -> "buka" | "tare" | "servo90" | "servo0"
*/

#include <Arduino.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <MQTTPubSubClient.h>
#include <ESP32Servo.h>
#include "HX711.h"

// ================= KONFIGURASI (EDIT BAGIAN INI) =================
const char* WIFI_SSID = "11S";
const char* WIFI_PASS = "info12345";

const char*    MQTT_HOST = "mqtt.walker880.my.id";
const uint16_t MQTT_PORT = 443;
const char*    MQTT_PATH = "/mqtt";
const char*    MQTT_USER = "";          // isi kalau broker butuh username
const char*    MQTT_PASS = "";          // isi kalau broker butuh password

const String NIM = "E41240977";          // GANTI dengan NIM kamu, dipakai di nama topik

const float         AMBANG_KENDARAAN_CM = 16;     // jarak di bawah ini = ada kendaraan
const unsigned long KONFIRMASI_MS       = 300;    // kendaraan harus terdeteksi stabil selama ini
const unsigned long TUNDA_TUTUP_MS      = 1500;   // setelah kendaraan lewat, 1,5 detik lalu servo menutup
const unsigned long TUNGGU_MAKS_MS      = 5000;   // tidak ada kendaraan sama sekali -> tutup sendiri
const unsigned long KENDARAAN_MAKS_MS   = 15000;  // "kendaraan" terdeteksi terus selama ini -> tutup paksa
// =================================================================

// ---------- Pin ----------
const int LOADCELL_DOUT_PIN = 16;
const int LOADCELL_SCK_PIN  = 4;
const int SERVO_PIN         = 18;
const int TRIG_PIN          = 23;
const int ECHO_PIN          = 22;  // lewat pembagi tegangan

// ---------- Kalibrasi ----------
const float CALIBRATION_FACTOR = 1026.33179;

// ---------- Objek ----------
HX711 scale;
Servo myServo;
WebSocketsClient ws;
MQTTPubSubClient mqtt;

// ---------- MQTT ----------
String TOPIC_DATA;
String TOPIC_PERINTAH;
String CLIENT_ID;
String perintahMasuk = "";           // diisi callback, diproses di loop
unsigned long lastMqttTry = 0;
const unsigned long MQTT_RETRY_MS = 5000;

// ---------- Servo ----------
bool servoDi90 = false;

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
const float JARAK_KOSONG = 400.0;
float bufJarak[N_JARAK] = {400, 400, 400, 400, 400};
int idxJarak = 0;
float jarakCm = -1;
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

// ---------- MQTT ----------
void setupMQTT() {
  TOPIC_DATA     = NIM + "/data";
  TOPIC_PERINTAH = NIM + "/perintah";
  CLIENT_ID      = "esp32-" + NIM;

  //WebSocket Secure ke wss://MQTT_HOST:443/mqtt dengan subprotocol "mqtt"
  ws.beginSSL(MQTT_HOST, MQTT_PORT, MQTT_PATH, "", "mqtt");
  ws.setReconnectInterval(3000);
  mqtt.begin(ws);

  Serial.println("Topik data     : " + TOPIC_DATA);
  Serial.println("Topik perintah : " + TOPIC_PERINTAH);
}

void hubungkanMQTT() {
  if (mqtt.isConnected()) return;
  if (WiFi.status() != WL_CONNECTED) return;
  if (!ws.isConnected()) return;                       // tunggu WebSocket siap dulu
  if (millis() - lastMqttTry < MQTT_RETRY_MS) return;
  lastMqttTry = millis();

  Serial.println("Menghubungkan MQTT...");
  bool ok;
  if (strlen(MQTT_USER) > 0) ok = mqtt.connect(CLIENT_ID, MQTT_USER, MQTT_PASS);
  else                       ok = mqtt.connect(CLIENT_ID);

  if (ok) {
    Serial.println("MQTT terhubung.");
    mqtt.subscribe(TOPIC_PERINTAH, [](const String& payload, const size_t size) {
      perintahMasuk = payload;
    });
  } else {
    Serial.println("MQTT gagal, dicoba lagi nanti.");
  }
}

// ---------- Setup ----------
void setup() {
  Serial.begin(115200);
  setCpuFrequencyMhz(160);

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
  setupMQTT();

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
        gerbang = G_KENDARAAN;
        waktuKendaraan = millis();
      } else if (millis() - waktuBersih >= TUNDA_TUTUP_MS) {
        tutupGerbang("kendaraan sudah lewat");
      }
      break;

    default:
      break;
  }
}

// ---------- Perintah dari web (lewat MQTT) ----------
void prosesPerintah() {
  if (perintahMasuk.length() == 0) return;
  String perintah = perintahMasuk;
  perintahMasuk = "";
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
  } else {
    Serial.println("Perintah tidak dikenal: " +perintah);
  }
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

  long durasi = pulseIn(ECHO_PIN, HIGH, 25000);
  float cm = (durasi == 0) ? JARAK_KOSONG : durasi * 0.0343 / 2.0;
  if (cm < 2.0 || cm > JARAK_KOSONG) cm = JARAK_KOSONG;

  bufJarak[idxJarak] = cm;
  idxJarak = (idxJarak + 1) % N_JARAK;

  float med = medianJarak();
  jarakCm = (med >= JARAK_KOSONG) ? -1 : med;
}

// ---------- Kirim data lewat MQTT ----------
void kirimData() {
  if (!mqtt.isConnected()) return;

  const char* namaGerbang[] = {"tutup", "menunggu", "kendaraan", "bersih"};
  String body = "{\"berat\":" + String(beratTerakhir, 1) +
                ",\"jarak\":" + String(jarakCm, 1) +
                ",\"servo\":" + (servoDi90 ? "90" : "0") +
                ",\"gerbang\":\"" + namaGerbang[gerbang] + "\"}";
  mqtt.publish(TOPIC_DATA, body);
}

// ---------- Jaga WiFi tetap tersambung ----------
void jagaWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - lastReconnect < RECONNECT_INTERVAL_MS) return;
  lastReconnect = millis();
  Serial.println("WiFi putus, mencoba konek ulang...");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
}

// ---------- Loop ----------
void loop() {
  ws.loop();
  mqtt.update();
  jagaWiFi();
  hubungkanMQTT();
  prosesPerintah();

  bacaTimbangan();
  bacaJarak();
  cekGerbang();

  if (millis() - lastPrint >= PRINT_INTERVAL_MS) {
    lastPrint = millis();
    Serial.printf("Berat: %.1f g | Jarak: %.1f cm | Gerbang: %d | MQTT: %s\n",
                  beratTerakhir, jarakCm, (int)gerbang, mqtt.isConnected() ? "ok" : "putus");
  }

  if (millis() - lastSend >= SEND_INTERVAL_MS) {
    lastSend = millis();
    kirimData();
  }
}