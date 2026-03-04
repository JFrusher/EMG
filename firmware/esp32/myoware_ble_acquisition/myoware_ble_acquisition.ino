/*
 * MyoWare BLE Acquisition Firmware (ESP32)
 * ========================================
 *
 * Streams MyoWare analog EMG to a laptop over BLE notifications with
 * robust reconnect behavior for public demos.
 *
 * Payload format (notify): little-endian uint16 ADC samples, packed.
 * - One notification contains SAMPLE_BATCH samples.
 * - Laptop converts raw 0..4095 to 0..3.3V.
 */

#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// -----------------------------------------------------------------------------
// Hardware + sampling config
// -----------------------------------------------------------------------------
static const int EMG_PIN = 34;                 // ADC1 pin (safe with BLE)
static const int ADC_BITS = 12;                // 0..4095
static const int SAMPLE_RATE_HZ = 1000;        // 1 kHz
static const uint32_t SAMPLE_PERIOD_US = 1000000UL / SAMPLE_RATE_HZ;
static const int SAMPLE_BATCH = 20;            // 20 ms packets at 1 kHz
static const uint8_t LED_PIN = 2;              // status LED (built-in on many boards)

// -----------------------------------------------------------------------------
// BLE IDs (match Python auto-discovery candidates)
// -----------------------------------------------------------------------------
static const char* DEVICE_NAME = "MYOWARE_EMG";
static const char* SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b";
static const char* CHAR_UUID    = "beb5483e-36e1-4688-b7f5-ea07361b26a8";

// -----------------------------------------------------------------------------
// Runtime state
// -----------------------------------------------------------------------------
BLEServer* bleServer = nullptr;
BLECharacteristic* emgCharacteristic = nullptr;
volatile bool bleClientConnected = false;

uint16_t sampleBuffer[SAMPLE_BATCH];
volatile int sampleIndex = 0;
uint32_t lastSampleUs = 0;
uint32_t lastLedToggleMs = 0;

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) override {
    bleClientConnected = true;
  }

  void onDisconnect(BLEServer* pServer) override {
    bleClientConnected = false;
    delay(80);
    BLEDevice::startAdvertising();
  }
};

void setup_ble() {
  BLEDevice::init(DEVICE_NAME);
  bleServer = BLEDevice::createServer();
  bleServer->setCallbacks(new ServerCallbacks());

  BLEService* service = bleServer->createService(SERVICE_UUID);
  emgCharacteristic = service->createCharacteristic(
    CHAR_UUID,
    BLECharacteristic::PROPERTY_NOTIFY
  );
  emgCharacteristic->addDescriptor(new BLE2902());
  service->start();

  BLEAdvertising* advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->setScanResponse(true);
  advertising->setMinPreferred(0x06);
  advertising->setMinPreferred(0x12);
  BLEDevice::startAdvertising();
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  analogReadResolution(ADC_BITS);
  analogRead(EMG_PIN);

  Serial.begin(115200);
  delay(300);
  Serial.println("BLE MyoWare acquisition starting...");
  Serial.printf("Device: %s\n", DEVICE_NAME);
  Serial.printf("Service UUID: %s\n", SERVICE_UUID);
  Serial.printf("Char UUID: %s\n", CHAR_UUID);

  setup_ble();
  lastSampleUs = micros();
}

void publish_batch_if_ready() {
  if (!bleClientConnected) {
    sampleIndex = 0;
    return;
  }

  if (sampleIndex < SAMPLE_BATCH) {
    return;
  }

  const uint8_t* payload = reinterpret_cast<const uint8_t*>(sampleBuffer);
  const size_t payloadLen = SAMPLE_BATCH * sizeof(uint16_t);
  emgCharacteristic->setValue(payload, payloadLen);
  emgCharacteristic->notify();
  sampleIndex = 0;
}

void update_status_led() {
  uint32_t nowMs = millis();
  uint32_t interval = bleClientConnected ? 120 : 600;
  if (nowMs - lastLedToggleMs >= interval) {
    lastLedToggleMs = nowMs;
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
  }
}

void loop() {
  uint32_t nowUs = micros();

  while ((uint32_t)(nowUs - lastSampleUs) >= SAMPLE_PERIOD_US) {
    lastSampleUs += SAMPLE_PERIOD_US;

    uint16_t raw = (uint16_t)analogRead(EMG_PIN);
    if (sampleIndex < SAMPLE_BATCH) {
      sampleBuffer[sampleIndex++] = raw;
    }
  }

  publish_batch_if_ready();
  update_status_led();

  if (!bleClientConnected) {
    delay(3);
  }
}
