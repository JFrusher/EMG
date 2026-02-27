/*
 * MyoWare EMG Signal Acquisition Firmware for ESP32
 * ===================================================
 * 
 * Purpose: Acquire EMG data from MyoWare sensor at 1000 Hz and stream to computer
 * 
 * Hardware:
 * - ESP32 DevKit (ADC1: GPIO 32-39)
 * - MyoWare 2.0 Muscle Sensor
 * 
 * Connections:
 * - MyoWare VCC  → ESP32 3.3V
 * - MyoWare GND  → ESP32 GND
 * - MyoWare SIG  → ESP32 GPIO 34 (ADC1_CH6)
 * 
 * Output Format: CSV via Serial at 921600 baud
 *   timestamp_ms,adc_value
 *   0,2048
 *   1,2050
 *   ...
 * 
 * Sampling: 1000 Hz (1 sample every 1 ms)
 * Buffer: 5000 samples (~5 seconds) before transmission
 */

// ============================================================================
// CONFIGURATION PARAMETERS
// ============================================================================
* TODO add the other input pins
const int ADC_PIN = 34;                    // GPIO34 = ADC1_CH6 (recommended)
const int SAMPLING_RATE_HZ = 1000;         // 1000 samples per second
const int SAMPLING_PERIOD_MS = 1;          // 1 millisecond between samples
const int BUFFER_SIZE = 5000;              // 5000 samples = 5 seconds of data
const long SERIAL_BAUD = 921600;           // High-speed serial communication

// ADC settings (ESP32 has 12-bit ADC by default)
const int ADC_RESOLUTION_BITS = 12;        // 12-bit = 0-4095 range
const int ADC_MAX_VALUE = 4095;            // Maximum ADC reading

// ============================================================================
// GLOBAL VARIABLES
// ============================================================================

// Data storage buffers
uint16_t adc_buffer[BUFFER_SIZE];          // Store ADC readings (0-4095)
uint32_t timestamp_buffer[BUFFER_SIZE];    // Store millisecond timestamps
volatile int buffer_index = 0;             // Current write position in buffer
volatile bool buffer_ready = false;        // Flag when buffer is full and ready to transmit

// Sampling control
unsigned long last_sample_time = 0;        // Timestamp of last ADC read
unsigned long startup_time = 0;            // System start time

// ============================================================================
// SETUP: Initialize serial, ADC, and timing
// ============================================================================

void setup() {
  // Initialize serial communication at high baud rate
  Serial.begin(SERIAL_BAUD);
  delay(1000);  // Wait for serial to stabilize
  
  // Print startup message for verification
  Serial.println("=== MyoWare EMG Data Acquisition System ===");
  Serial.print("Sampling Rate: ");
  Serial.print(SAMPLING_RATE_HZ);
  Serial.println(" Hz");
  Serial.print("ADC Resolution: ");
  Serial.print(ADC_RESOLUTION_BITS);
  Serial.println(" bits");
  Serial.print("Buffer Size: ");
  Serial.print(BUFFER_SIZE);
  Serial.println(" samples");
  Serial.println("timestamp_ms,adc_raw_value");
  
  // Configure ADC (ESP32-specific)
  analogReadResolution(ADC_RESOLUTION_BITS);  // Set to 12-bit (0-4095)
  
  // Read ADC pin to initialize it
  analogRead(ADC_PIN);
  
  // Record start time for timestamp calculation
  startup_time = millis();
  last_sample_time = startup_time;
  
  Serial.println("Acquisition started. Waiting for muscle activity...");
}

// ============================================================================
// MAIN LOOP: Acquire samples at fixed 1 kHz rate
// ============================================================================

void loop() {
  // Calculate time since last sample
  unsigned long current_time = millis();
  unsigned long elapsed = current_time - last_sample_time;
  
  // Check if it's time for next sample (every 1 ms at 1000 Hz)
  if (elapsed >= SAMPLING_PERIOD_MS) {
    
    // Read ADC value from MyoWare sensor
    uint16_t adc_value = analogRead(ADC_PIN);
    
    // Store in buffers
    adc_buffer[buffer_index] = adc_value;
    timestamp_buffer[buffer_index] = current_time - startup_time;
    
    // Advance buffer position
    buffer_index++;
    
    // Update sampling time for next iteration
    last_sample_time = current_time;
    
    // Check if buffer is full
    if (buffer_index >= BUFFER_SIZE) {
      buffer_ready = true;
    }
  }
  
  // Transmit data when buffer is full
  if (buffer_ready) {
    transmit_buffer();
    buffer_ready = false;
  }
}

// ============================================================================
// TRANSMISSION: Send buffered data to computer via Serial
// ============================================================================

void transmit_buffer() {
  /*
   * Sends all collected samples in CSV format:
   * timestamp_ms,adc_raw_value
   * 
   * Time format: milliseconds since acquisition start
   * ADC format: 0-4095 (12-bit raw value)
   * Voltage conversion on computer: V = (adc_value / 4095) * 3.3V
   */
  
  for (int i = 0; i < BUFFER_SIZE; i++) {
    // Format: timestamp,adc_value
    Serial.print(timestamp_buffer[i]);
    Serial.print(",");
    Serial.println(adc_buffer[i]);
  }
  
  // Print separator for clarity in terminal (optional)
  Serial.println("---END_BUFFER---");
  
  // Reset buffer index for next acquisition
  buffer_index = 0;
}

// ============================================================================
// NOTES ON PERFORMANCE AND OPTIMIZATION
// ============================================================================

/*
 * TIMING ACCURACY:
 * - millis() has ~1ms resolution on ESP32
 * - For precise 1kHz sampling, consider using hardware timers
 * - Current approach is sufficient for EMG (signal bandwidth 20-500 Hz)
 * 
 * ADC PERFORMANCE:
 * - ESP32 ADC is 12-bit, reading takes ~100 microseconds
 * - At 1 kHz, each sample takes ~1 ms, so ADC is fast enough
 * - Multiple analogRead() calls can introduce noise; we read once per sample
 * 
 * BUFFER STRATEGY:
 * - 5000 samples @ 1 kHz = 5 seconds of data
 * - USB serial at 921600 baud can transmit ~5 seconds in ~0.5 seconds
 * - Buffer size trades off between memory and transmission frequency
 * 
 * FUTURE IMPROVEMENTS:
 * - Use hardware timer (esp_timer) for more precise sampling
 * - Implement circular buffer for continuous streaming
 * - Add WiFi streaming for wireless operation
 * - Include timestamp synchronization with computer clock
 * - Add on-board filtering to reduce transmission bandwidth
 */

// ============================================================================
// ALTERNATIVE: Higher Precision Sampling with Hardware Timer
// ============================================================================

/*
 * If you need more precise 1 kHz sampling, use hardware timer:
 * 
 * #include <driver/timer.h>
 * 
 * void IRAM_ATTR onTimer() {
 *   if (buffer_index < BUFFER_SIZE) {
 *     adc_buffer[buffer_index] = analogRead(ADC_PIN);
 *     timestamp_buffer[buffer_index] = millis() - startup_time;
 *     buffer_index++;
 *     
 *     if (buffer_index >= BUFFER_SIZE) {
 *       buffer_ready = true;
 *     }
 *   }
 * }
 * 
 * Call this in setup():
 *   timer_t config = TIMER_BASE_CLK / 1000;  // 1 MHz clock for 1 kHz timer
 *   esp_timer_create_args_t args = {
 *     .callback = &onTimer,
 *     .name = "EMG_Timer"
 *   };
 *   esp_timer_handle_t timer;
 *   esp_timer_create(&args, &timer);
 *   esp_timer_start_periodic(timer, 1000);  // 1000 microseconds = 1 kHz
 */
