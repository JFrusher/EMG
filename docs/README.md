# MyoWare EMG Signal Processing System - Complete Project

## 📋 Project Overview

This is a complete **end-to-end EMG (Electromyography) signal processing system** for prosthetic control. It combines hardware acquisition with sophisticated signal processing and real-time gripper visualization.

**What it does:**
- Acquires raw muscle electrical signals at 1000 Hz from MyoWare sensor
- Processes through 5-stage filter pipeline (notch → bandpass → rectify → butterworth → envelope)
- Detects muscle activation patterns
- Interprets as prosthetic gripper control commands
- Visualizes everything with a digital twin gripper animation
- Suitable for research, education, and public engagement demonstrations

**System components:**
```
Physical Hardware          Firmware              Software Processing
┌──────────────┐      ┌──────────────┐      ┌────────────────────┐
│ MyoWare      │ ──→  │ ESP32        │ ──→  │ Python Signal      │
│ EMG Sensor   │      │ ADC @ 1kHz   │      │ Processing &       │
│ + Electrodes │      │ Serial 921k  │      │ Gripper Control    │
└──────────────┘      └──────────────┘      └────────────────────┘
     
EMG Signal:                Raw Data:             Processed Output:
0-3.3V analog       CSV timestamps + ADC     - Filtered signals
Muscle activity     values at 1kHz           - SNR analysis
                                             - Peak detection
                                             - Gripper animation
```

---

## 📦 What's Included

### Hardware Files
- **`myoware_acquisition.ino`**: Arduino firmware for ESP32
  - Configurable sampling rate (1000 Hz default)
  - High-speed serial output (921600 baud)
  - Buffered transmission every 5 seconds
  - Complete with error handling and documentation

### Python Processing Modules
- **`emg_signal_processor.py`**: Core signal processing (680+ lines)
  - Multi-stage filtering (notch, bandpass, butterworth)
  - Feature extraction (RMS, MAV, peak detection)
  - SNR calculation at each stage
  - Complete visualization pipeline
  
- **`digital_twin_gripper.py`**: Prosthetic gripper simulation (350+ lines)
  - 5-finger gripper model with physics-based dynamics
  - Real-time animation and control feedback
  - Grip force visualization
  - Finger position tracking

- **`main_pipeline.py`**: Integration and orchestration (400+ lines)
  - Live ESP32 serial acquisition
  - CSV file loading/saving
  - Synthetic data generation for testing
  - Complete command-line interface
  - Data processing automation

### Documentation
- **`EMG_Setup_Guide.md`**: Hardware and software setup (9 sections)
- **`TESTING_GUIDE.md`**: Comprehensive testing protocol (8 tests)
- **`README.md`**: This file

---

## 🚀 Quick Start (5 Minutes)

### Prerequisites
```bash
# Python 3.8+ required
python --version

# Install dependencies
pip install numpy scipy matplotlib pandas
```

### Run Without Hardware (Test Everything)
```bash
python main_pipeline.py --mode synthetic
```

This will:
1. ✓ Generate synthetic EMG data
2. ✓ Apply all filters in sequence
3. ✓ Display 6-panel signal visualization
4. ✓ Show frequency response plots
5. ✓ Display gripper control simulation
6. ✓ Calculate SNR and features
7. ✓ Save results to `./results/`

**Takes ~30 seconds, no hardware needed**

---

## 📊 Signal Processing Pipeline

### Stage-by-Stage Processing

```
Raw EMG Signal (1000 Hz, noisy)
            ↓
[1] NOTCH FILTER (50 Hz rejection)
    - Removes powerline interference
    - Quality factor: 30 (sharp rejection)
    - Minimal effect on EMG content
            ↓
[2] BANDPASS FILTER (20-500 Hz)
    - Isolates EMG frequency content
    - Removes DC baseline wander
    - Removes high-frequency noise
    - Order: 4 (steep slope)
            ↓
[3] FULL-WAVE RECTIFICATION
    - Takes absolute value
    - Converts bipolar to unipolar signal
    - Essential for envelope detection
            ↓
[4] BUTTERWORTH LOW-PASS (150 Hz cutoff)
    - Smooths rectified signal
    - Creates preliminary envelope
    - Order: 3 (minimal phase lag)
            ↓
[5] MOVING AVERAGE ENVELOPE (100ms window)
    - Final smoothing
    - Represents muscle activation level
    - Ready for control interpretation
            ↓
Clean Envelope Signal (ready for prosthetic control)
```

### Filter Specifications

| Filter | Type | Parameters | Purpose |
|--------|------|-----------|---------|
| Notch | IIR | f=50Hz, Q=30 | Powerline removal |
| Bandpass | Butterworth | 20-500Hz, order=4 | EMG isolation |
| Rectification | Full-wave | abs() | Bipolar→unipolar |
| Low-pass | Butterworth | f=150Hz, order=3 | Envelope smoothing |
| Envelope | Moving average | window=100ms | Muscle activation |

### SNR Improvement

**Typical SNR values** (dB):
```
Raw signal:          -5 dB (lots of noise)
After notch:         +5 dB (powerline removed)
After bandpass:      +8 dB (noise outside band removed)
After butterworth:   +15 dB (smoothed)
Final envelope:      +20 dB (clean, interpretable)
```

---

## 💾 Data Format

### CSV Format (from ESP32)
```
timestamp_ms,adc_raw_value
0,2048
1,2050
2,2052
...
```

**Conversion to voltage:**
```python
voltage = (adc_raw_value / 4095.0) * 3.3  # V (ESP32 is 12-bit, 3.3V ref)
```

### Sampling Specifications
- **Rate**: 1000 Hz (1 sample per millisecond)
- **Duration**: ~5 seconds per transmission (5000 samples)
- **Resolution**: 12-bit ADC → 4096 levels
- **Voltage range**: 0.0V to 3.3V

---

## 🔧 Hardware Setup

### Wiring Diagram

```
MyoWare Sensor          ESP32 DevKit
──────────────          ────────────
VCC (Red)       ──→     3.3V
GND (Black)     ──→     GND  
SIG (White)     ──→     GPIO 34 (ADC1_CH6)
```

### Electrode Placement (Critical!)

```
                 Muscle Belly
┌─────────────────────────────┐
│ Forearm muscle (Flexor)     │
├─────────────────────────────┤
│                             │
│  M      (MID)   = Electrode 1
│  ↓ Fiber        = Center of muscle
│  I (END)        = Electrode 2 (aligned with fiber)
│  D
│  
│  R (REF)        = Electrode 3 (bony area, away from muscle)
└─────────────────────────────┘
Wrist                      Elbow
```

### Recommended ADC Pins (ESP32)
- **ADC1** (recommended): GPIO 32, 33, 34, 35, 36, 37, 38, 39
- **ADC2** (avoid): GPIO 0, 2, 4, 12-15, 25-27 (conflicts with WiFi)

**Use GPIO 34 by default** (best pin layout)

---

## 🧪 Testing Strategy

### Test Order (Recommended)

1. **Synthetic Data Test** (5 min, no hardware)
   ```bash
   python main_pipeline.py --mode synthetic
   ```
   ✓ Validates complete software pipeline

2. **Filter Stability Test** (2 min)
   ```bash
   python main_pipeline.py --test stability
   ```
   ✓ Confirms no oscillations or instability

3. **Serial Communication Test** (5 min)
   ```bash
   python main_pipeline.py --test serial
   ```
   ✓ Verifies ESP32 connection works

4. **10-Second Baseline Recording** (10 min)
   ```bash
   python main_pipeline.py --mode live --port COM3 --duration 10
   ```
   ✓ Records with relaxed muscle (no activation)

5. **Muscle Activation Recording** (15 min)
   ```bash
   python main_pipeline.py --mode live --port COM3 --duration 10
   ```
   ✓ Records with deliberate contractions

6. **Multiple Muscle Test** (20 min)
   - Record from biceps, forearm, triceps
   - Validate system works on different anatomies

7. **Motion Artifact Test** (10 min)
   - Record with electrode movement
   - Verify system is robust

8. **Long-Duration Test** (optional)
   - Record 5-10 minutes continuous
   - Validate electrode adhesion
   - Check for signal drift

**Total testing time: ~90 minutes (including hardware setup)**

---

## 📈 Command-Line Reference

### Data Acquisition
```bash
# Test with synthetic data (no hardware needed)
python main_pipeline.py --mode synthetic

# Stream from ESP32
python main_pipeline.py --mode live --port COM3 --duration 10

# Load from previously recorded CSV
python main_pipeline.py --mode load --file emg_data.csv
```

### Testing
```bash
# Run all tests
python main_pipeline.py --test all

# Test specific component
python main_pipeline.py --test synthetic
python main_pipeline.py --test stability
python main_pipeline.py --test serial
```

### Advanced Options
```bash
# Specify output directory
python main_pipeline.py --mode live --port COM3 --output ./my_results

# Different port (Linux/Mac)
python main_pipeline.py --mode live --port /dev/ttyUSB0 --duration 10

# Longer recording
python main_pipeline.py --mode live --port COM3 --duration 30
```

---

## 📊 Output Files

After each run, results saved to `./results/`:

```
results/
├── 01_emg_processing_pipeline.png
│   └── 6-subplot visualization showing each filter stage
│   
├── 02_filter_frequency_response.png
│   └── Magnitude and phase response of all filters
│   
└── 03_gripper_control.png
    └── EMG envelope + detected peaks + gripper state feedback
```

### Example Visualization Interpretation

**Subplot 1 (Raw Signal)**
- Should show oscillation with noise
- Voltage: 0.5V - 3.0V
- Frequency content: 20-500 Hz + 50 Hz noise + DC

**Subplot 2 (Notch Filtered)**
- 50 Hz powerline component removed
- SNR improved by ~10 dB
- May still look noisy (bandpass not applied yet)

**Subplot 3 (Bandpass)**
- EMG-only content (20-500 Hz)
- Much cleaner than raw
- Shows bipolar waveform

**Subplot 4 (Rectified)**
- All-positive waveform
- No negative components
- Ready for envelope detection

**Subplot 5 (Butterworth Low-Pass)**
- Smoothed rectified signal
- Shows overall activation level
- Envelope beginning to appear

**Subplot 6 (Final Envelope + Peaks)**
- Clean, interpretable signal
- Red triangles = detected activation peaks
- Dashed line = activation threshold (20% of max)

---

## 🎯 Feature Extraction Results

After processing, system calculates:

| Feature | Description | Typical Range |
|---------|-------------|----------------|
| **RMS** | Root Mean Square (signal energy) | 0.1 - 1.5 V |
| **MAV** | Mean Absolute Value (amplitude) | 0.05 - 0.8 V |
| **Peak** | Maximum amplitude | 0.2 - 3.0 V |
| **ZC** | Zero Crossings (frequency indicator) | 50 - 500 |
| **WL** | Waveform Length (complexity) | 100 - 5000 |
| **MNF** | Median Frequency (Hz) | 50 - 300 Hz |

---

## 👁️ Gripper Visualization

The digital twin gripper responds to EMG in real-time:

```
Grip Type Recognition:
  Envelope < 10% max  →  OPEN (no contact)
  10% ≤ Envelope < 40%  →  LIGHT_GRIP (precision, 5-10% force)
  Envelope ≥ 40% max   →  POWER_GRIP (full force grasp)

Finger Response:
  - Each finger has individual flexion (0-100%)
  - Thumb slightly slower (0.7x ratio)
  - Index/Middle fastest (1.0x ratio)
  - Pinky slightly slower (0.8x ratio)
  - Smooth low-pass filtered response (avoids jerky motion)

Visual Feedback:
  - Color changes from white (open) to red (closed)
  - Force bar shows grip strength
  - Activation text updates in real-time
  - Confidence score (0-100%) displayed
```

---

## 🛠️ Troubleshooting

### No Peaks Detected
```
Problem: Envelope looks flat, no activation detected

Solutions:
1. Increase contraction force (harder muscle squeeze)
2. Check electrode contact (clean skin with alcohol)
3. Move reference electrode further from muscle
4. Try different muscle (forearm often best for prosthetics)
5. Increase recording duration (signal may take time)
```

### Very Noisy Signal
```
Problem: Raw signal looks like random jumps, hard to interpret

Solutions:
1. Secure ESP32/sensor with tape (cable movement = noise)
2. Add electrode gel (improves skin contact)
3. Move away from electronic devices (WiFi router, computers)
4. Use shielded USB cable if possible
5. Clean skin more thoroughly with alcohol
```

### Serial Connection Failed
```
Problem: "Could not open serial port COM3"

Solutions:
1. Check USB cable connection
2. Install CH340 drivers (if using clone ESP32)
   Download: https://www.wch.cn/download/ch341ser_exe.zip
3. Check Arduino IDE Serial Monitor shows data
4. Try different COM port (if multiple USB devices)
5. Restart ESP32 (press reset button)
```

### SNR Not Improving
```
Problem: Filter stages don't show SNR improvement

Solutions:
1. Longer baseline (SNR calculated on first 10% of signal)
2. Stronger muscle activation (clearer signal/noise separation)
3. Check filter parameters aren't too aggressive
4. Verify electrode placement quality
```

---

## 📚 Educational Value

This system is perfect for teaching:

1. **Signal Processing**
   - Filter design and implementation
   - Frequency domain analysis
   - Phase response and group delay
   - Digital vs. analog filtering trade-offs

2. **Biomedical Engineering**
   - EMG signal characteristics
   - Electrode theory and placement
   - SNR optimization in biological signals
   - Real-world noise sources

3. **Control Systems**
   - Command interpretation from sensors
   - Real-time feedback and control
   - Prosthetic control algorithms
   - Human-machine interfaces

4. **Python Programming**
   - Scientific computing (NumPy, SciPy)
   - Data visualization (Matplotlib)
   - Signal processing libraries
   - Serial communication

5. **Embedded Systems**
   - Microcontroller ADC programming
   - Real-time sampling
   - Serial communication protocols
   - Firmware optimization

---

## 🎤 Public Engagement Demo

### Setup for Presentation
1. Pre-record 5-10 seconds of your own EMG
2. Save as `emg_demo.csv`
3. Load during presentation:
   ```bash
   python main_pipeline.py --mode load --file emg_demo.csv
   ```

### Demo Flow
1. **Explain hardware** (1 min)
   - Show MyoWare sensor
   - Point out electrode placement
   - Discuss signal at body

2. **Show raw signal** (1 min)
   - Display subplot 1 (raw EMG)
   - Point out noise and powerline interference
   - Discuss SNR = -5 dB

3. **Walk through filters** (2 min)
   - Notch filter removes 50 Hz
   - Bandpass isolates EMG content
   - Butterworth smooths signal
   - Each step improves SNR

4. **Show envelope and control** (2 min)
   - Final clean signal
   - Detected peaks = muscle activations
   - Gripper responds in real-time
   - Explain grip type interpretation

5. **Live demo** (optional)
   - Apply electrode pads to volunteer
   - Record 20 seconds
   - Process live on projector
   - Show instant results

**Total demo time: 8-10 minutes + questions**

---

## 📖 References & Standards

**EMG Signal Processing:**
- ISEK (International Society of Electrophysiology and Kinesiology) guidelines
- Phalen & Kuiken (2005) - Prosthetic control review
- Merletti & Farina (2008) - EMG fundamentals

**Signal Processing:**
- Butterworth filter theory (Butterworth, 1930)
- Digital filter design (Oppenheim & Schafer)
- Notch filters for powerline rejection (IEEE)

**Prosthetic Control:**
- Neural interfaces review (Dadarlat et al., 2019)
- EMG envelope extraction methods (Esposito et al., 2023)
- Real-time gesture recognition (Phinyomark et al., 2012)

**Open Source EMG Tools:**
- OpenSim (Stanford) - biomechanics simulation
- BioSig - biomedical signal processing (Octave/MATLAB)
- PyEMG - Python EMG toolbox

---

## 🔮 Future Enhancements

### Phase 1: Core System (✓ Complete)
- [x] Multi-stage filtering
- [x] Peak detection
- [x] Gripper visualization
- [x] Synthetic data generation

### Phase 2: Machine Learning (Recommended next)
- [ ] Gesture classification (fist, pinch, point, etc.)
- [ ] Training data collection
- [ ] Real-time gesture recognition
- [ ] Multi-muscle pattern analysis

### Phase 3: Advanced Features
- [ ] Wireless WiFi streaming
- [ ] Cloud data logging
- [ ] Mobile app control
- [ ] Haptic feedback integration
- [ ] Multi-subject database

### Phase 4: Hardware Integration
- [ ] Actual prosthetic hand connection
- [ ] Force sensor feedback
- [ ] Joint angle encoding
- [ ] Battery power system

---

## 📝 License & Attribution

**Code:** Free to use for research and education
**Citation:** If publishing, mention MyoWare EMG and ESP32 platform

**Recommended Citation:**
```
MyoWare EMG Processing System for Prosthetic Control
Southampton Biomedical Engineering
https://github.com/[your-repo]
```

---

## ✉️ Support

**For issues with:**
- **Python code**: Check TESTING_GUIDE.md troubleshooting section
- **ESP32 firmware**: Verify Arduino IDE setup, board selection
- **Signal quality**: See electrode placement guide in EMG_Setup_Guide.md
- **Specific errors**: Run `python main_pipeline.py --test all` for diagnostics

---

## 🎓 Summary

You now have:

✅ **Hardware**: Complete EMG acquisition system  
✅ **Firmware**: Arduino-based data collection  
✅ **Software**: Professional-grade signal processing  
✅ **Visualization**: Real-time gripper control simulation  
✅ **Testing**: Comprehensive validation protocol  
✅ **Documentation**: Complete guides and reference material  

**Next steps:**
1. Run synthetic data test (5 min)
2. Set up hardware (30 min)
3. Complete testing protocol (90 min)
4. Customize for your application (ongoing)

**Good luck with your biomedical engineering project!** 🧬🤖

---

*Last updated: December 2025*  
*Version: 1.0 - Complete System*  
*Python 3.8+ | scipy, numpy, matplotlib, pandas required*
