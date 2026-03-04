# EMG Processing System - Complete Testing & Validation Guide

## Quick Start Checklist

### Hardware Setup (Day 1)
- [ ] Obtain MyoWare 2.0 sensor, electrodes, and ESP32 DevKit
- [ ] Wire MyoWare to ESP32 (VCC→3.3V, GND→GND, SIG→GPIO34)
- [ ] Verify wiring with multimeter
- [ ] Install Arduino IDE + ESP32 board support
- [ ] Upload `firmware/esp32/myoware_serial_acquisition/myoware_serial_acquisition.ino` to ESP32
- [ ] Verify serial output in Arduino IDE Serial Monitor at 921600 baud

### Software Setup (Day 2)
```bash
# Install Python 3.8+
python --version

# Create project directory
mkdir emg_project
cd emg_project

# Install dependencies
pip install numpy scipy matplotlib pandas pyserial

# Place all Python files in this directory
# - emg_signal_processor.py
# - digital_twin_gripper.py
# - main_pipeline.py
```

### First Test (Day 2)
```bash
# Run synthetic data test (no hardware needed)
python main_pipeline.py --mode synthetic

# You should see:
# - Console output showing filter stages, SNR, features, peaks
# - 6 subplot visualization of processing pipeline
# - Gripper control panel
# - Filter frequency response plots
```

---

## Testing Protocol: Test Before Using Hardware

### Test 1: Synthetic Data Pipeline ✓ START HERE

**Purpose**: Validate complete software pipeline without hardware
**Time**: 5 minutes
**Hardware**: None needed

```bash
python main_pipeline.py --mode synthetic
```

**Expected Output**:
- Console prints each filter stage
- SNR should improve at each stage (raw → notch → bandpass → butterworth)
- Envelope should show smooth peaks, no noise spikes
- Gripper visualization shows smooth grip transitions

**Success Criteria**:
- ✓ No Python errors
- ✓ SNR improves: raw (-5 dB) → notch (5 dB) → bandpass (8 dB) → envelope (15 dB)
- ✓ Visualizations appear without distortion
- ✓ Peak detection finds 2-4 activation bursts

**Troubleshooting**:
```
ERROR: ModuleNotFoundError: No module named 'numpy'
→ Run: pip install numpy scipy matplotlib pandas

ERROR: No module named 'emg_signal_processor'
→ Verify all .py files in same directory

ERROR: matplotlib error
→ Run: pip install --upgrade matplotlib
```

---

### Test 2: Filter Stability Analysis ✓ VALIDATE MATH

**Purpose**: Verify filter coefficients won't cause oscillations
**Time**: 3 minutes
**Hardware**: None needed

```bash
python main_pipeline.py --test stability
```

**Expected Output**:
```
Notch filter pole radius: 0.9950
Bandpass filter pole radius: 0.9920
Butterworth filter pole radius: 0.9870
✓ Notch filter: STABLE
✓ Bandpass filter: STABLE
✓ Butterworth filter: STABLE
```

**Success Criteria**:
- ✓ All pole radii < 1.0 (indicates stability)
- ✓ All filters marked STABLE
- ✓ No oscillations in frequency response

**Theory**:
- Pole radius > 1.0 = unstable (exponential growth)
- Pole radius < 1.0 = stable (exponential decay)
- For digital filters, all poles must be inside unit circle

---

### Test 3: ESP32 Serial Communication ✓ CHECK HARDWARE

**Purpose**: Verify ESP32 is transmitting data correctly
**Time**: 5 minutes
**Hardware**: ESP32 + USB cable

**Prerequisites**:
- Arduino IDE installed with ESP32 board support
- `firmware/esp32/myoware_serial_acquisition/myoware_serial_acquisition.ino` uploaded to ESP32
- USB cable connected to computer

```bash
python main_pipeline.py --test serial
```

**Expected Output**:
```
Available serial ports:
  [0] COM3: USB-SERIAL CH340 (CH340G)

Testing connection on COM3...
✓ Successfully opened COM3
Reading startup messages:
  === MyoWare EMG Data Acquisition System ===
  Sampling Rate: 1000 Hz
  ADC Resolution: 12 bits
  Buffer Size: 5000 samples
  timestamp_ms,adc_raw_value
  Acquisition started. Waiting for muscle activity...
✓ Connection test passed
```

**Success Criteria**:
- ✓ Serial port appears in list
- ✓ No "Connection failed" error
- ✓ Startup messages visible

**Troubleshooting**:
```
No serial ports found!
→ Check USB cable connection
→ Install CH340 drivers (if using clone board): 
   https://www.wch.cn/download/ch341ser_exe.zip

ERROR: Could not open serial port COM3
→ Port in use by another application
→ Close Arduino IDE Serial Monitor
→ Try different COM port

Garbage characters in output
→ Wrong baud rate (check firmware = 921600)
→ Try: python -m serial.tools.list_ports (for alternative tools)
```

**Verify Firmware**:
```cpp
// In firmware/esp32/myoware_serial_acquisition/myoware_serial_acquisition.ino, verify this line:
const long SERIAL_BAUD = 921600;

// And this line in setup():
Serial.begin(SERIAL_BAUD);
```

---

### Test 4: 10-Second Live Recording ✓ FIRST REAL DATA

**Purpose**: Record actual EMG from ESP32, no muscle activity
**Time**: 15 minutes
**Hardware**: ESP32 + MyoWare + electrodes (NO activation)

**Setup**:
1. Apply electrode pads to your arm (don't activate muscle yet)
2. Keep arm relaxed and still
3. Run:

```bash
python main_pipeline.py --mode live --port COM3 --duration 10
```

**Expected Output**:
```
Mode: LIVE ACQUISITION from COM3
Attempting to open serial port: COM3 @ 921600 baud...
Serial port opened. Waiting for data...
Recording for 10.0 seconds...
  1000 samples collected...
  2000 samples collected...
  ...
  10000 samples collected...

Recording complete: 10000 samples (10.0s)

EMG PROCESSING PIPELINE
...SNR Analysis...
...Features...
✓ Processing complete
Results saved to: ./results/
```

**Expected Characteristics**:
```
Raw signal voltage: 1.5V - 1.8V (should be ~midpoint of 0-3.3V)
Envelope RMS: 0.05 - 0.15V (low baseline with relaxed muscle)
Detected peaks: 0-1 (occasional noise spikes, not true contractions)
```

**Success Criteria**:
- ✓ 10,000 samples collected (1 sample per ms)
- ✓ Voltage between 0.5V - 3.0V (not saturated)
- ✓ SNR improves through processing stages
- ✓ Visualizations show noisy baseline

**Results Directory**:
```
./results/
├── 01_emg_processing_pipeline.png  # 6-panel signal flow
├── 02_filter_frequency_response.png # Filter characteristics
└── 03_gripper_control.png          # Gripper visualization
```

---

### Test 5: Muscle Activation Recording ✓ FULL SYSTEM

**Purpose**: Record EMG while actively contracting muscle
**Time**: 20 minutes
**Hardware**: Complete setup with electrodes applied

**Setup**:
1. Verify electrode placement:
   - Reference (REF): Bony area away from muscle
   - Middle (MID): Center of muscle belly
   - End (END): Aligned with muscle fiber direction
2. Clean electrode sites with alcohol wipe
3. Press pads firmly onto skin

**Activation Pattern**:
```
Time    Action
0-2s    Relax completely (baseline)
2-3s    Light contraction (20% force)
3-4s    Rest
4-5s    Strong contraction (80% force)
5-6s    Rest
6-7s    Medium contraction (50% force)
7-10s   Rest completely
```

**Run Recording**:
```bash
python main_pipeline.py --mode live --port COM3 --duration 10 --output results_muscle_activation
```

**Expected Behavior**:
- Voltage increases when muscle contracts
- Voltage decreases during rest
- Smooth transitions between states

**Expected SNR**:
```
Raw:        -5 dB (lots of noise)
Notch:       5 dB (powerline removed)
Bandpass:    8 dB (EMG isolated)
Butterworth: 15 dB (smoothed)
Envelope:    20 dB (clean)
```

**Success Criteria**:
- ✓ Clear peaks detected during contractions
- ✓ Peaks coincide with your muscle activation timing
- ✓ Rest periods show low envelope
- ✓ Gripper shows grip progression: OPEN → LIGHT_GRIP → POWER_GRIP → OPEN

**Troubleshooting**:
```
No clear peaks detected (all baseline noise)
→ Check electrode contact (clean skin better)
→ Move electrodes to different spot on muscle
→ Increase contraction force (harder squeeze)
→ Try different muscle (biceps, forearm flexor, etc.)

Very noisy signal (looks like random jumps)
→ Cable moving too much (secure with tape)
→ EMG sensor not pressed firmly on skin
→ Skin too dry (add electrode gel)
→ Electromagnetic interference (move away from devices)

Signal too high/low (clipped or invisible)
→ High: Reduce gain (move reference electrode further)
→ Low: Increase gain (better electrode contact)
```

---

### Test 6: Different Muscles ✓ VALIDATE ON NEW MUSCLES

**Purpose**: Test system works on different muscle groups
**Muscles to try**:
1. **Biceps**: Arm flexion (easier to detect)
2. **Forearm**: Wrist flexion (good for prosthetics)
3. **Triceps**: Arm extension (different pattern)
4. **Vastus Lateralis**: Quadriceps (large muscle)

**For each muscle**:
1. Clean skin and apply electrodes
2. Record 10 seconds with activation pattern
3. Compare results

```bash
# Record from biceps
python main_pipeline.py --mode live --port COM3 --duration 10 --output results_biceps

# Record from forearm
python main_pipeline.py --mode live --port COM3 --duration 10 --output results_forearm
```

**Expected Differences**:
- Forearm: Faster activation/deactivation (for prosthetic control)
- Biceps: Slower, larger amplitude
- Triceps: Lower amplitude, requires less force
- Quad: Very large amplitude, strong signal

---

## Advanced Testing

### Test 7: Filter Parameter Optimization

The pipeline uses default parameters. If you want to optimize:

**Edit `emg_signal_processor.py`**:

```python
# DEFAULT - works well for most cases
self.apply_notch_filter(freq=50, quality_factor=30)
self.apply_bandpass_filter(lowcut=20, highcut=500, order=4)
self.apply_butterworth_lowpass(cutoff=150, order=3)

# FOR NOISIER SIGNALS - more aggressive filtering
self.apply_notch_filter(freq=50, quality_factor=40)  # Sharper notch
self.apply_bandpass_filter(lowcut=30, highcut=400, order=5)  # Tighter band
self.apply_butterworth_lowpass(cutoff=100, order=4)  # More smoothing

# FOR FASTER RESPONSE - less filtering
self.apply_bandpass_filter(lowcut=10, highcut=600, order=2)
self.apply_butterworth_lowpass(cutoff=200, order=2)
```

**Validate Changes**:
```bash
# Run synthetic data with new parameters
python main_pipeline.py --mode synthetic

# Check SNR improves as expected
# Verify envelope is smooth, not distorted
# Confirm peaks detected properly
```

### Test 8: Motion Artifact Robustness

**Purpose**: Verify system handles electrode movement

```bash
# Record with normal electrode:
python main_pipeline.py --mode live --port COM3 --duration 5 --output results_static

# During recording, gently move the electrode back and forth
# Re-run and record with movement:
python main_pipeline.py --mode live --port COM3 --duration 5 --output results_movement

# Compare visualizations
# Expected: movement adds noise to raw signal, but envelope should be similar
```

---

## Validation Metrics Checklist

After each test, verify these metrics:

### Electrical Metrics
- [ ] ADC range: 0.5V - 3.0V (not saturated)
- [ ] Sampling rate: exactly 1000 Hz
- [ ] No missed samples (timestamps should increment by 1)

### Signal Quality
- [ ] SNR improves at each filter stage
- [ ] Envelope is smooth (no sharp spikes)
- [ ] Frequency content is 20-500 Hz

### Control Performance
- [ ] Peaks detected match muscle activation timing
- [ ] Confidence score (0-1) reflects contraction strength
- [ ] Gripper responds with appropriate grip type

### Visualization Quality
- [ ] All 6 subplots appear correctly
- [ ] Colors are visible and distinct
- [ ] No distortion or clipping in plots

---

## Deployment for Public Engagement

Once tests pass:

1. **Record reference data** with multiple subjects
2. **Save as numpy files** (smaller than CSV):
   ```python
   np.save('emg_demo_data.npy', voltage_array)
   ```

3. **Create demo script** that loads pre-recorded data:
   ```bash
   python main_pipeline.py --mode load --file emg_demo_data.npy
   ```

4. **Run on projection screen** at event
5. **Pause and discuss** filter stages
6. **Show gripper response** in real-time

---

## Command Reference

### Run Tests
```bash
# Test all components
python main_pipeline.py --test all

# Test specific component
python main_pipeline.py --test synthetic
python main_pipeline.py --test stability
python main_pipeline.py --test serial
```

### Data Acquisition
```bash
# Synthetic data (no hardware)
python main_pipeline.py --mode synthetic

# Live from ESP32
python main_pipeline.py --mode live --port COM3 --duration 10

# Load from file
python main_pipeline.py --mode load --file data.csv

# Specify output directory
python main_pipeline.py --mode live --port COM3 --output ./my_results
```

### Serial Port Help
```bash
# List available ports
python -m serial.tools.list_ports

# Test connection
python main_pipeline.py --test serial
```

---

## Expected File Structure After Testing

```
emg_project/
├── firmware/esp32/myoware_serial_acquisition/myoware_serial_acquisition.ino  # Arduino sketch
├── emg_signal_processor.py          # Main processing module
├── digital_twin_gripper.py          # Gripper visualization
├── main_pipeline.py                 # Integration script
├── results_synthetic/               # From --mode synthetic
│   ├── 01_emg_processing_pipeline.png
│   ├── 02_filter_frequency_response.png
│   └── 03_gripper_control.png
├── results_live_relaxed/            # From first live test
│   └── [same visualization files]
├── results_muscle_activation/       # From activation test
│   └── [same visualization files]
└── emg_demo_data.npy                # For public engagement
```

---

## Success Indicators

You're ready for production when:

- ✓ All 6 tests pass without errors
- ✓ Synthetic data shows clean envelope with detected peaks
- ✓ Live data shows clear activation/deactivation patterns
- ✓ Gripper visualization responds correctly to muscle activation
- ✓ Multiple muscles tested successfully
- ✓ Visualizations are clear and professional

**Congratulations!** You have a fully functional EMG prosthetic control system.

---

## Next Steps

1. **Gesture Training**: Record multiple contractions for each desired grip
2. **Machine Learning**: Add classification to distinguish grip types
3. **Hardware Integration**: Connect to actual prosthetic hand
4. **Wireless**: Replace serial with WiFi for mobility
5. **Haptic Feedback**: Add vibration motor for proprioceptive feedback
6. **Publication**: Document results for academic paper

---

## Contact & References

For issues with:
- **MyoWare sensor**: https://www.advancertechnologies.com
- **ESP32**: https://www.espressif.com/en/products/devkits
- **Signal processing**: ISEK EMG standards or IEEE biomedical signal processing

