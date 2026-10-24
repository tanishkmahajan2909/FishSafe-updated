/*
 * ============================================================
 * FishSafe ESP32 Firmware
 * fishsafe_esp32.ino
 * ============================================================
 *
 * Hardware:  ESP32 DevKit V1 (ESP32-WROOM-32)
 *            TCS34725 RGB Colour Sensor (I2C: SDA=GPIO21, SCL=GPIO22)
 *            White LEDs    → GPIO 26 (controlled illumination)
 *            Green LED     → GPIO 27 (result: Not Flagged)
 *            Red LED       → GPIO 25 (result: Flagged)
 *            Buzzer        → GPIO 32
 *            Push button   → GPIO 33 (trigger reading; INPUT_PULLUP)
 *
 * Required Libraries (install via Arduino Library Manager):
 *   1. Adafruit TCS34725          — by Adafruit
 *   2. Adafruit BusIO             — by Adafruit (dependency)
 *   3. ArduinoJson                — by Benoit Blanchon (v6.x)
 *   4. HTTPClient                 — built-in ESP32 core
 *   5. WiFi                       — built-in ESP32 core
 *
 * SETUP BEFORE UPLOADING:
 *   1. Set your Wi-Fi SSID and password below.
 *   2. Find your laptop's local IPv4 address:
 *         Open Command Prompt → type: ipconfig
 *         Look for "IPv4 Address" under your Wi-Fi adapter (e.g. 192.168.1.5)
 *   3. Set SERVER_URL to:   http://<your-laptop-ip>:5000/api/sensor-reading
 *   4. Set SAMPLE_ID to the sample ID you registered on the Flask dashboard.
 *   5. Upload using Arduino IDE (select Board: ESP32 Dev Module, Port: your COM port).
 *
 * WIRING TABLE
 * ─────────────────────────────────────────────────────────────────
 * TCS34725 Pin  │ ESP32 Pin  │ Notes
 * ─────────────────────────────────────────────────────────────────
 * VIN / VCC     │ 3V3        │ 3.3 V supply
 * GND           │ GND        │ Common ground
 * SDA           │ GPIO 21    │ I2C data
 * SCL           │ GPIO 22    │ I2C clock
 * LED (INT)     │ NC         │ Not used in this firmware
 * ─────────────────────────────────────────────────────────────────
 * Component     │ ESP32 Pin  │ Notes
 * ─────────────────────────────────────────────────────────────────
 * White LEDs    │ GPIO 26    │ Via NPN transistor or LED driver
 * Green LED     │ GPIO 27    │ 330 Ω series resistor to GND
 * Red LED       │ GPIO 25    │ 330 Ω series resistor to GND
 * Buzzer (–)    │ GPIO 32    │ Active buzzer; (+) to 3V3
 * Push Button   │ GPIO 33    │ Other terminal to GND; uses INPUT_PULLUP
 * ─────────────────────────────────────────────────────────────────
 *
 * ============================================================
 */

#include <Wire.h>
#include <Adafruit_TCS34725.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ------------------------------------------------------------------
// ★ USER CONFIGURATION — Edit these before uploading ★
// ------------------------------------------------------------------

const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// Flask server URL — replace with your laptop's local IPv4 address
// Find it by running  ipconfig  in Command Prompt (Windows)
const char* SERVER_URL    = "http://192.168.1.100:5000/api/sensor-reading";

// Device identifier (shown in the Flask dashboard)
const char* DEVICE_ID     = "ESP32-FishSafe-01";

// Sample ID — must match a registered sample in the Flask dashboard
// Change this to the sample ID you create before each test.
String SAMPLE_ID          = "FS-20251013-DEMO";

// ------------------------------------------------------------------
// Pin definitions
// ------------------------------------------------------------------
#define PIN_GREEN_LED   27
#define PIN_RED_LED     25
#define PIN_BUZZER      32
#define PIN_BUTTON      33

// ------------------------------------------------------------------
// TCS34725 sensor
// TCS34725_INTEGRATIONTIME_50MS and TCS34725_GAIN_4X are reasonable
// starting values. Adjust if your readings are saturated or too dim.
// ------------------------------------------------------------------
Adafruit_TCS34725 tcs = Adafruit_TCS34725(
  TCS34725_INTEGRATIONTIME_50MS,
  TCS34725_GAIN_4X
);

Adafruit_SSD1306 oled(128, 64, &Wire, -1);
bool oledReady = false;

void displayStatus(String line1, String line2 = "") {
  if (!oledReady) return;
  oled.clearDisplay();
  oled.setTextSize(1);
  oled.setTextColor(SSD1306_WHITE);
  oled.setCursor(0, 0);
  oled.println("FishSafe");
  oled.println(line1);
  oled.println(line2);
  oled.display();
}

// ------------------------------------------------------------------
// State
// ------------------------------------------------------------------
bool wifiConnected   = false;
bool sensorReady     = false;
unsigned long lastWifiCheck = 0;

// ------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n\n========================================");
  Serial.println("   FishSafe ESP32 Firmware Starting");
  Serial.println("========================================");

  // Pin modes
  pinMode(PIN_GREEN_LED,  OUTPUT);
  pinMode(PIN_RED_LED,    OUTPUT);
  pinMode(PIN_BUZZER,     OUTPUT);
  pinMode(PIN_BUTTON,     INPUT_PULLUP);

  // All outputs OFF initially
  digitalWrite(PIN_GREEN_LED,  LOW);
  digitalWrite(PIN_RED_LED,    LOW);
  digitalWrite(PIN_BUZZER,     LOW);

  Wire.begin(21, 22);
  oledReady = oled.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  displayStatus("Starting...");

  // Initialise TCS34725
  if (tcs.begin()) {
    Serial.println("[SENSOR] TCS34725 initialised OK.");
    sensorReady = true;
    // Short blink to confirm sensor is alive
    digitalWrite(PIN_RED_LED, LOW);
    digitalWrite(PIN_GREEN_LED, LOW);
  } else {
    Serial.println("[SENSOR] ERROR: TCS34725 not found! Check wiring.");
    Serial.println("         SDA → GPIO 21 | SCL → GPIO 22 | VCC → 3V3");
    digitalWrite(PIN_RED_LED, LOW);
    digitalWrite(PIN_GREEN_LED, LOW);
    // Continue anyway so serial feedback keeps working
  }

  // Connect to Wi-Fi
  connectWifi();

  Serial.println("\nReady. Press the button to capture a reading.\n");
  displayStatus("Ready", "Press button");
}

// ------------------------------------------------------------------
void loop() {
  // Reconnect Wi-Fi if dropped
  if (millis() - lastWifiCheck > 10000) {
    lastWifiCheck = millis();
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("[WiFi] Connection lost. Reconnecting…");
      connectWifi();
    }
  }

  // Wait for button press (active LOW with pull-up)
  if (digitalRead(PIN_BUTTON) == LOW) {
    delay(50); // debounce
    if (digitalRead(PIN_BUTTON) == LOW) {
      Serial.println("\n[BUTTON] Button pressed — capturing reading…");
      captureAndSend();

      // Wait for button release
      while (digitalRead(PIN_BUTTON) == LOW) delay(10);
    }
  }
}

// ------------------------------------------------------------------
// Read from TCS34725 and POST to Flask
// ------------------------------------------------------------------
void captureAndSend() {
  digitalWrite(PIN_RED_LED, LOW);
  digitalWrite(PIN_GREEN_LED, LOW);
  if (!sensorReady) {
    Serial.println("[ERROR] Sensor not ready. Check I2C wiring.");
    digitalWrite(PIN_RED_LED, LOW);
    digitalWrite(PIN_GREEN_LED, LOW);
    return;
  }

  // Use consistent ambient illumination; no white LED is fitted.

  // Read raw 16-bit RGBC values
  uint16_t r, g, b, c;
  tcs.getRawData(&r, &g, &b, &c);

  // Turn off illumination LEDs

  // Print to Serial Monitor
  displayStatus("R:" + String(r) + " G:" + String(g), "B:" + String(b) + " C:" + String(c));
  Serial.println("----------------------------------------");
  Serial.println("[SENSOR] Raw RGBC Values:");
  Serial.print("  R = "); Serial.println(r);
  Serial.print("  G = "); Serial.println(g);
  Serial.print("  B = "); Serial.println(b);
  Serial.print("  C = "); Serial.println(c);

  if (c == 0) {
    Serial.println("[WARNING] Clear channel = 0. Check LED and sensor positioning.");
  }

  // Colour temperature and lux (informational only)
  uint16_t colorTemp = tcs.calculateColorTemperature_dn40(r, g, b, c);
  uint16_t lux       = tcs.calculateLux(r, g, b);
  Serial.print("  Colour Temp ≈ "); Serial.print(colorTemp); Serial.println(" K");
  Serial.print("  Lux         ≈ "); Serial.println(lux);
  Serial.println("----------------------------------------");

  // Build JSON
  StaticJsonDocument<256> doc;
  doc["sample_id"] = SAMPLE_ID;
  doc["device_id"] = DEVICE_ID;
  doc["red"]       = r;
  doc["green"]     = g;
  doc["blue"]      = b;
  doc["clear"]     = c;
  doc["is_demo"]   = false;

  String jsonBody;
  serializeJson(doc, jsonBody);

  // POST to Flask
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[ERROR] Wi-Fi not connected. Cannot send reading.");
    digitalWrite(PIN_RED_LED, LOW);
    digitalWrite(PIN_GREEN_LED, LOW);
    return;
  }

  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");
  // If FISHSAFE_DEVICE_KEY is configured on Vercel, set the same key here.
  const char* DEVICE_KEY = "";
  if (strlen(DEVICE_KEY) > 0) http.addHeader("X-Device-Key", DEVICE_KEY);

  Serial.print("[HTTP] POSTing to: ");
  Serial.println(SERVER_URL);

  int httpCode = http.POST(jsonBody);

  if (httpCode > 0) {
    String response = http.getString();
    Serial.print("[HTTP] Response code: ");
    Serial.println(httpCode);
    Serial.print("[HTTP] Response body: ");
    Serial.println(response);

    // Parse response
    StaticJsonDocument<512> resp;
    DeserializationError err = deserializeJson(resp, response);
    if (!err && httpCode == 200) {
      String classification = resp["classification"] | "Inconclusive";
      Serial.print("[RESULT] Classification: ");
      Serial.println(classification);
      displayStatus("Result:", classification);

      // Show result on LEDs and buzzer
      if (classification == "Flagged") {
        showResult(true);
      } else if (classification == "Not Flagged") {
        showResult(false);
      } else {
        // Inconclusive: both indicator LEDs OFF.
        digitalWrite(PIN_RED_LED, LOW);
        digitalWrite(PIN_GREEN_LED, LOW);
      }
    } else {
      Serial.println("[HTTP] Could not parse server response.");
      digitalWrite(PIN_RED_LED, LOW);
    digitalWrite(PIN_GREEN_LED, LOW);
    }
  } else {
    Serial.print("[HTTP] POST failed. Error: ");
    Serial.println(http.errorToString(httpCode));
    Serial.println("       Check SERVER_URL and ensure Flask is running on the laptop.");
    digitalWrite(PIN_RED_LED, LOW);
    digitalWrite(PIN_GREEN_LED, LOW);
  }

  http.end();
}

// ------------------------------------------------------------------
// Connect or reconnect to Wi-Fi
// ------------------------------------------------------------------
void connectWifi() {
  Serial.print("[WiFi] Connecting to: ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    wifiConnected = true;
    Serial.println("\n[WiFi] Connected!");
    Serial.print("[WiFi] IP Address: ");
    Serial.println(WiFi.localIP());
    digitalWrite(PIN_RED_LED, LOW);
    digitalWrite(PIN_GREEN_LED, LOW);
  } else {
    wifiConnected = false;
    Serial.println("\n[WiFi] Connection FAILED.");
    Serial.println("       Check SSID, password, and that the laptop is on the same network.");
    digitalWrite(PIN_RED_LED, LOW);
    digitalWrite(PIN_GREEN_LED, LOW);
  }
}

// ------------------------------------------------------------------
// Show result on LEDs and buzzer
// ------------------------------------------------------------------
void showResult(bool flagged) {
  if (flagged) {
    // Flagged — red LED on, buzzer beep
    digitalWrite(PIN_GREEN_LED, LOW);
    digitalWrite(PIN_RED_LED,   HIGH);
    tone(PIN_BUZZER, 1000, 500);
    delay(600);
    tone(PIN_BUZZER, 1000, 500);
    delay(600);
  } else {
    // Not Flagged — green LED on, short pleasant beep
    digitalWrite(PIN_RED_LED,   LOW);
    digitalWrite(PIN_GREEN_LED, HIGH);
    tone(PIN_BUZZER, 1800, 200);
    delay(200);
  }
}

// ------------------------------------------------------------------
// Helper: blink an LED
// ------------------------------------------------------------------
void blinkLed(int pin, int times, int delayMs) {
  for (int i = 0; i < times; i++) {
    digitalWrite(pin, HIGH);
    delay(delayMs);
    digitalWrite(pin, LOW);
    delay(delayMs);
  }
}

// tone() may not be defined on all ESP32 cores.
// If you get a compile error, install the ESP32 Arduino core v2.x+ or
// replace tone() with a simple digitalWrite + delay approach for the buzzer.
