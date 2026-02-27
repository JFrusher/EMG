# MyoWare EMG Signal Processing System - Complete Setup Guide

## Project Overview
This project implements a complete EMG signal acquisition, processing, and visualization pipeline for prosthetic control applications using:
- **MyoWare 2.0 Muscle Sensor** for EMG acquisition
- **ESP32** for real-time data collection and streaming
- **Python** for signal processing and visualization
- **Digital twin gripper** for prosthetic control simulation

---

## Part 1: Hardware Wiring and Setup

### 1.1 MyoWare Sensor Pinout
The MyoWare 2.0 outputs a single analog signal through its snap connectors:
- **VCC**: Power supply (3.3V or 5V - ESP32 supports 3.3V)
- **GND**: Ground
- **SIG**: Analog output signal (raw EMG amplified ~1000x)

### 1.2 ESP32 to MyoWare Wiring
```
MyoWare Sensor          ESP32 DevKit
─────────────          ─────────────
VCC (Red)       →      3.3V
GND (Black)     →      GND
SIG (White)     →      GPIO 34 (ADC1_CH6) or any ADC pin
```

**Note**: ESP32-DEVKIT-C has several ADC pins:
- ADC1: GPIO 32-39 (recommended: GPIO 34, 35, 36)
- ADC2: GPIO 0, 2, 4, 12-15, 25-27 (avoid if using WiFi)

### 1.3 Physical Setup Checklist
- [ ] Clean skin thoroughly with alcohol wipes
- [ ] Place reference (REF) electrode on bony area away from muscle
- [ ] Place middle (MID) electrode at muscle center
- [ ] Place end (END) electrode along muscle fiber direction
- [ ] Ensure electrode-skin contact is firm
- [ ] Minimize cable movement to reduce motion artifacts

---

## Part 2: ESP32 Firmware

### 2.1 Arduino IDE Setup
1. Install **Arduino IDE 2.0+** or **PlatformIO** in VS Code
2. Add ESP32 board support in Arduino IDE Preferences
3. Select Board: **ESP32 Dev Module**
4. Install required libraries: None needed for basic operation (built-in)

### 2.2 ESP32 Data Acquisition Specifications
- **Sampling Rate**: 1000 Hz (1 sample every 1ms)
- **ADC Resolution**: 12-bit (0-4095 raw values)
- **Input Range**: 0-3.3V
- **Buffer Size**: 5000 samples per transmission (~5 seconds)
- **Serial Baud Rate**: 921600 (high-speed for data streaming)

### 2.3 Data Format
Raw data transmitted as CSV to serial port:
```
timestamp_ms,adc_raw_value
0,2048
1,2050
2,2052
...
```

**Voltage Conversion**: `V = (ADC_value / 4095) * 3.3`

---

## Part 3: Python Signal Processing Pipeline

### 3.1 Required Python Libraries
```bash
pip install numpy scipy matplotlib pandas pyserial
```

### 3.2 Processing Pipeline Architecture

```
Raw EMG Data (1000 Hz)
         ↓
[Step 1] Read from serial OR load saved data
         ↓
[Step 2] Notch filter (remove 50/60 Hz powerline)
         ↓
[Step 3] Bandpass filter (20-500 Hz - EMG content)
         ↓
[Step 4] Full-wave rectification
         ↓
[Step 5] Butterworth low-pass (150 Hz)
         ↓
[Step 6] Envelope extraction (moving average)
         ↓
[Step 7] Peak detection & control input
         ↓
[Step 8] Digital twin gripper control
         ↓
[Output] Multi-level visualization
```

### 3.3 Signal Processing Parameters

| Step | Parameter | Value | Rationale |
|------|-----------|-------|-----------|
| Notch | Frequency | 50 Hz (UK) or 60 Hz (US) | Powerline interference |
| Notch | Q-factor | 30 | Sharp rejection, narrow bandwidth |
| Bandpass | Low cutoff | 20 Hz | Remove DC, baseline wander |
| Bandpass | High cutoff | 500 Hz | Include EMG content, reduce noise |
| Bandpass | Order | 4 | Balance filtering and phase lag |
| Butterworth | Cutoff | 150 Hz | Smooth envelope extraction |
| Butterworth | Order | 2-4 | Minimal phase lag |
| Envelope | Window | 100 ms | Smooth muscular contractions |
| Thresholding | Activation | 20% of max | Discriminate noise from signal |

### 3.4 SNR Calculation
```
SNR_dB = 10 * log10(Signal_Power / Noise_Power)

Where:
- Signal_Power = RMS of rectified, filtered signal
- Noise_Power = RMS of baseline (no muscle activity)
```

### 3.5 Feature Extraction for Control
```
RMS = sqrt(mean(signal^2))  // Root Mean Square
MAV = mean(abs(signal))      // Mean Absolute Value
Peak = max(signal)           // Peak amplitude
```

---

## Part 4: Testing and Validation

### 4.1 Testing Without Physical Pads

**Option 1: Synthetic Data Generation**
- Generate artificial EMG using sine waves (100-300 Hz) + Gaussian noise
- Modulate amplitude with burst patterns
- Apply muscle activation patterns

**Option 2: Pre-recorded Data Playback**
- Acquire data from another user
- Save to CSV file
- Load and process offline

**Option 3: Function Generator**
- Use audio output or signal generator
- Input 5V sine wave + noise
- Validate filter frequency response

### 4.2 Validation Metrics
1. **Frequency Response**: Plot magnitude vs. frequency
2. **Phase Response**: Verify minimal phase distortion
3. **SNR Before/After**: Compare at each filter stage
4. **Envelope Smoothness**: Check for artifacts
5. **Control Response**: Test gripper motion accuracy

### 4.3 Known Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| Baseline drift | Electrode movement | Apply high-pass filter, use adhesive pads |
| 50/60 Hz noise | Powerline interference | Notch filter, ensure ground connection |
| Motion artifacts | Muscle/sensor movement | Use reference cable, minimize cable sway |
| ADC quantization | Low resolution | Increase ADC resolution, apply dithering |
| Latency | Buffer accumulation | Reduce buffer size (trade-off: SNR) |

---

## Part 5: File Structure

```
emg_project/
├── esp32_firmware/
│   └── myoware_acquisition.ino
├── python_processing/
│   ├── emg_data_recorder.py
│   ├── emg_signal_processor.py
│   ├── emg_visualizer.py
│   ├── digital_twin_gripper.py
│   └── main_pipeline.py
├── sample_data/
│   ├── raw_emg_data.csv
│   └── reference_signals.npy
├── test_data/
│   ├── synthetic_emg.csv
│   └── function_generator_test.csv
└── README.md
```

---

## Part 6: Deployment for Public Engagement

### 6.1 Dry EMG Demo Setup
- Pre-record high-quality EMG data from multiple subjects
- Store as numpy binary files (small file size)
- Load during presentation
- Minimal dependencies (numpy + matplotlib)
- Real-time playback and filtering

### 6.2 Display Requirements
- 1920×1080 or higher resolution screen
- 6 subplots showing filtering progression
- Live gripper animation
- Feature information (RMS, frequency, control commands)

### 6.3 Demo Configuration
- Playback speed: adjustable (0.5x to 2x normal)
- Loop continuously or single play
- Allow pause/resume
- Show/hide different filter stages
- Export visualization as high-res images

---

## Part 7: Troubleshooting Checklist

### Hardware Issues
- [ ] Verify ESP32 USB connection (serial port appears in device list)
- [ ] Check MyoWare sensor LED (should blink when powered)
- [ ] Confirm voltage at sensor (use multimeter)
- [ ] Test ADC with known voltage (e.g., voltage divider)

### Firmware Issues
- [ ] Verify baud rate matches (921600)
- [ ] Check ADC pin is correct (avoid ADC2 if WiFi used)
- [ ] Monitor serial output for garbage data
- [ ] Restart ESP32 and check startup messages

### Software Issues
- [ ] Verify Python version (3.7+)
- [ ] Check library versions: `pip list`
- [ ] Test data file format (CSV structure)
- [ ] Validate filter coefficient stability
- [ ] Check matplotlib backend for visualization

### Signal Quality Issues
- [ ] Increase sampling duration (longer baseline statistics)
- [ ] Check electrode impedance (clean skin surface)
- [ ] Verify muscle activation is visible in raw data
- [ ] Test with different muscle groups
- [ ] Compare SNR across filter stages

---

## Part 8: Future Enhancements

1. **Wireless Communication**: Implement WiFi streaming instead of serial
2. **Real-time ML**: Add classification for different gestures
3. **Haptic Feedback**: Integrate vibration motor for proprioceptive feedback
4. **Multi-channel**: Stack multiple MyoWare sensors for pattern recognition
5. **Cloud Logging**: Send data to server for analysis
6. **Mobile App**: Display and control on smartphone
7. **Gesture Database**: Build library of EMG signatures for multiple movements

---

## Part 9: Safety Considerations

⚠️ **Important Notes**:
1. Do NOT apply electrodes to electrodes or damaged skin
2. Do NOT use electrode pads if allergic to adhesive
3. Maximum recommended session: 8 hours continuous wear
4. Clean skin thoroughly before sensor application
5. Keep water away from sensor during operation
6. EMG signals measure 0-5V, safe voltage for humans

---

## Quick Start Checklist

- [ ] Part 1: Wiring verified
- [ ] Part 2: ESP32 firmware uploaded
- [ ] Part 3: Python environment set up
- [ ] Part 4: Test with synthetic data
- [ ] Part 5: Validate signal processing
- [ ] Apply electrode pads to skin
- [ ] Record real EMG data
- [ ] Adjust filter parameters for your muscle
- [ ] Train gesture recognition (optional)
- [ ] Deploy for public engagement

---

## References

- SparkFun MyoWare 2.0 Documentation
- ESP32 ADC Documentation
- Butterworth Filter Design (Scipy)
- EMG Signal Processing Standards (ISEK)
- Prosthetic Control Literature

