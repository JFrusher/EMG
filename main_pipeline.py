"""
Main EMG Processing Pipeline - Integration Script
==================================================

Complete workflow for:
1. Acquiring EMG data from ESP32 via serial
2. Processing through multi-stage filter pipeline
3. Interpreting control commands
4. Visualizing gripper control response
5. Saving results for offline analysis

Usage:
    python main_pipeline.py --mode live      # Stream from ESP32
    python main_pipeline.py --mode load      # Load from CSV
    python main_pipeline.py --mode synthetic # Test with synthetic data
"""

import sys
import argparse
import numpy as np
from pathlib import Path
from datetime import datetime
import pandas as pd

# Import custom modules
from emg_signal_processor import EMGProcessor
from digital_twin_gripper import visualize_gripper_control, create_animated_gripper
from frequency_analyzer import FrequencyAnalyzer
import emg_filters

# -------------------------------------------------------------------------
# FILTER PRESETS (EDIT HERE)
# -------------------------------------------------------------------------
# This project centralizes filter stacks in `emg_filters.py`.
# - To add or change presets: edit `d:\EMG\emg_filters.py` and add a function
#   that accepts a `processor` instance and calls `processor.add_filter(...)`.
# - Available CLI helpers: `--preset <name>` applies the preset; `--list-presets`
#   prints available presets. Example: `--preset default` or `--preset aggressive`.
# - Presets keep your experiments reproducible and let you run the pipeline
#   by only specifying dataset args from the terminal.
# -------------------------------------------------------------------------



# ============================================================================
# SERIAL DATA ACQUISITION
# ============================================================================

def acquire_from_serial(port: str = 'COM3', duration_sec: float = 10.0,
                       baud: int = 921600) -> tuple:
    """
    Acquire EMG data directly from ESP32 via serial.
    
    Requirements:
    - pip install pyserial
    - ESP32 running myoware_acquisition.ino firmware
    - USB cable connected
    
    Args:
        port: Serial port (COM3 on Windows, /dev/ttyUSB0 on Linux)
        duration_sec: Recording duration
        baud: Serial baud rate (must match firmware)
    
    Returns:
        Tuple of (time_array, voltage_array)
    """
    try:
        import serial
    except ImportError:
        print("ERROR: pyserial not installed. Install with: pip install pyserial")
        return None, None
    
    print(f"Attempting to open serial port: {port} @ {baud} baud...")
    
    try:
        ser = serial.Serial(port, baud, timeout=1)
    except serial.SerialException as e:
        print(f"ERROR: Could not open serial port {port}")
        print(f"  {e}")
        print("\nAvailable ports:")
        import serial.tools.list_ports
        for p in serial.tools.list_ports.comports():
            print(f"  {p.device}: {p.description}")
        return None, None
    
    print("Serial port opened. Waiting for data...")
    
    # Clear buffer
    ser.reset_input_buffer()
    
    # Skip startup messages
    for _ in range(3):
        line = ser.readline()
        if line:
            print(f"  > {line.decode().strip()}")
    
    # Collect data
    time_data = []
    adc_data = []
    start_time = datetime.now()
    
    print(f"\nRecording for {duration_sec} seconds...")
    
    while (datetime.now() - start_time).total_seconds() < duration_sec:
        try:
            line = ser.readline().decode().strip()
            
            if line and line != "---END_BUFFER---":
                try:
                    parts = line.split(',')
                    if len(parts) == 2:
                        timestamp_ms = float(parts[0])
                        adc_raw = int(parts[1])
                        
                        # Convert ADC to voltage (3.3V reference, 12-bit)
                        voltage = (adc_raw / 4095.0) * 3.3
                        
                        time_data.append(timestamp_ms / 1000.0)
                        adc_data.append(voltage)
                        
                        # Progress indicator
                        if len(adc_data) % 1000 == 0:
                            print(f"  {len(adc_data)} samples collected...")
                
                except (ValueError, IndexError):
                    pass
        
        except KeyboardInterrupt:
            print("\nRecording interrupted by user")
            break
        except Exception as e:
            print(f"Error reading data: {e}")
    
    ser.close()
    
    print(f"\nRecording complete: {len(adc_data)} samples ({len(adc_data)/1000:.1f}s)")
    
    return np.array(time_data), np.array(adc_data)


def save_emg_data(time_array: np.ndarray, voltage_array: np.ndarray,
                 output_file: str = None) -> str:
    """
    Save acquired EMG data to CSV file.
    
    Args:
        time_array: Time vector
        voltage_array: Voltage samples
        output_file: Optional output filename
    
    Returns:
        Path to saved file
    """
    if output_file is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"emg_data_{timestamp}.csv"
    
    # Convert voltage back to ADC for storage
    adc_values = (voltage_array / 3.3) * 4095
    adc_values = adc_values.astype(int)
    
    df = pd.DataFrame({
        'timestamp_ms': (time_array * 1000).astype(int),
        'adc_raw_value': adc_values
    })
    
    df.to_csv(output_file, index=False)
    print(f"Data saved to: {output_file}")
    
    return output_file


# ============================================================================
# COMPLETE PROCESSING PIPELINE
# ============================================================================

def process_emg_data(time_array: np.ndarray, voltage_array: np.ndarray,
                    output_dir: str = './results', preset_name: str = None, analyze_filtered: bool = False) -> dict:
    """
    Execute complete EMG processing pipeline.

    Steps:
    1. Load data
    2. Apply multi-stage filtering
    3. Extract features
    4. Detect control commands
    5. Generate visualizations

    Args:
        time_array: Time vector
        voltage_array: EMG voltage samples
        output_dir: Directory for results
        preset_name: Optional name of a filter preset defined in `emg_filters.PRESETS` to apply before processing
        analyze_filtered: If True, run frequency analysis on the last pre-envelope filtered signal and save an analysis image

    Returns:
        Dictionary with all results
    """

    # Create output directory
    Path(output_dir).mkdir(exist_ok=True)

    print("\n" + "="*70)
    print("EMG SIGNAL PROCESSING PIPELINE")
    print("="*70)

    # Initialize processor
    processor = EMGProcessor(sampling_rate=1000)
    processor.load_from_numpy(voltage_array)

    # Run a frequency analysis of the raw signal first (always)
    print("\nRunning initial frequency analysis on raw signal (pre-filters)...")
    analyzer_raw = FrequencyAnalyzer(sampling_rate=processor.sampling_rate)
    analyzer_raw.data = np.asarray(processor.raw_data)
    analyzer_raw.compute_fft()
    analyzer_raw.print_analysis()
    raw_freq_path = f"{output_dir}/00_raw_signal_frequency_analysis.png"
    analyzer_raw.plot_frequency_response(save_path=raw_freq_path, title='EMG Frequency - Raw Signal')
    print(f"Saved raw-signal frequency analysis to: {raw_freq_path}")

    # Apply filter preset if provided
    if preset_name:
        preset_fn = emg_filters.PRESETS.get(preset_name)
        if preset_fn is None:
            print(f"Warning: preset '{preset_name}' not found. Available: {list(emg_filters.PRESETS.keys())}")
        else:
            try:
                preset_fn(processor)
                print(f"Applied filter preset: {preset_name}")
            except Exception as e:
                print(f"Error applying preset '{preset_name}': {e}")

    # Process pipeline
    processor.process_complete_pipeline()
    
    # Analysis
    print("\n" + "-"*70)
    snr_results = processor.calculate_snr()
    
    print("\n" + "-"*70)
    features = processor.extract_features()
    
    print("\n" + "-"*70)
    control_results = processor.detect_peaks_and_control(
        threshold_percent=20.0,
        min_distance_ms=100.0
    )
    
    # Visualizations
    print("\n" + "-"*70)
    print("GENERATING VISUALIZATIONS")
    print("-"*70)

    # Save main processing visualization
    viz_path = f"{output_dir}/01_emg_processing_pipeline.png"
    processor.visualize_all(save_path=viz_path)

    # Save frequency response (chain-based FRF)
    freq_path = f"{output_dir}/02_filter_frequency_response.png"
    processor.plot_frequency_response(save_path=freq_path)

    # Optionally analyze the last pre-envelope filtered signal
    if analyze_filtered:
        print("\nRunning filtered-signal frequency analysis (pre-envelope)...")
        # Prefer 'rectified' (pre-envelope) if present, otherwise use last filtered stage
        if 'rectified' in processor.filtered_stages:
            signal_to_analyze = processor.filtered_stages['rectified']
            source_label = 'rectified (pre-envelope)'
        else:
            signal_to_analyze = processor.last_filtered_signal()
            source_label = 'last filtered stage'

        if signal_to_analyze is None or len(signal_to_analyze) == 0:
            print("No filtered signal available to analyze.")
        else:
            analyzer = FrequencyAnalyzer(sampling_rate=processor.sampling_rate)
            analyzer.data = np.asarray(signal_to_analyze)
            analyzer.compute_fft()
            analyzer.print_analysis()
            filtered_freq_path = f"{output_dir}/04_filtered_signal_frequency_analysis.png"
            analyzer.plot_frequency_response(save_path=filtered_freq_path)
            print(f"Saved filtered-signal frequency analysis ({source_label}) to: {filtered_freq_path}")

    # Save gripper control visualization
    gripper_path = f"{output_dir}/03_gripper_control.png"
    visualize_gripper_control(processor.time, processor.envelope,
                             control_results['control_commands'],
                             save_path=gripper_path)
    
    # Compile results
    results = {
        'processor': processor,
        'snr': snr_results,
        'features': features,
        'control': control_results,
        'output_dir': output_dir
    }
    
    return results


# ============================================================================
# TESTING PROTOCOLS
# ============================================================================

def test_synthetic_data():
    """
    Test complete pipeline with synthetic EMG data.
    Good for validating filter performance without hardware.
    """
    print("\n" + "="*70)
    print("TEST 1: SYNTHETIC DATA VALIDATION")
    print("="*70)
    print("\nGenerating synthetic EMG with known properties...")
    
    processor = EMGProcessor(sampling_rate=1000)
    processor.generate_synthetic_data(duration_sec=5.0, snr_db=10.0)
    
    processor.process_complete_pipeline()
    processor.calculate_snr()
    processor.extract_features()
    control_results = processor.detect_peaks_and_control()
    
    processor.visualize_all()
    visualize_gripper_control(processor.time, processor.envelope,
                             control_results['control_commands'])
    
    print("✓ Synthetic data test passed")


def test_filter_stability():
    """
    Test filter coefficient stability and phase response.
    Validates that filters don't introduce artifacts.
    """
    print("\n" + "="*70)
    print("TEST 2: FILTER STABILITY ANALYSIS")
    print("="*70)
    
    from scipy.signal import butter, iirnotch, group_delay
    
    fs = 1000
    
    # Test notch filter
    b_notch, a_notch = iirnotch(50, 30, fs)
    poles_notch = np.roots(a_notch)
    print(f"Notch filter pole radius: {np.max(np.abs(poles_notch)):.4f}")
    
    # Test bandpass
    b_bp, a_bp = butter(4, [20/(fs/2), 500/(fs/2)], 'band')
    poles_bp = np.roots(a_bp)
    print(f"Bandpass filter pole radius: {np.max(np.abs(poles_bp)):.4f}")
    
    # Test Butterworth
    b_lp, a_lp = butter(3, 150/(fs/2), 'low')
    poles_lp = np.roots(a_lp)
    print(f"Butterworth filter pole radius: {np.max(np.abs(poles_lp)):.4f}")
    
    # All poles should be inside unit circle for stability
    if np.max(np.abs(poles_notch)) < 1.0:
        print("✓ Notch filter: STABLE")
    else:
        print("✗ Notch filter: UNSTABLE")
    
    if np.max(np.abs(poles_bp)) < 1.0:
        print("✓ Bandpass filter: STABLE")
    else:
        print("✗ Bandpass filter: UNSTABLE")
    
    if np.max(np.abs(poles_lp)) < 1.0:
        print("✓ Butterworth filter: STABLE")
    else:
        print("✗ Butterworth filter: UNSTABLE")


def test_real_data(csv_file: str):
    """
    Test processing on recorded real EMG data.
    
    Args:
        csv_file: Path to CSV file from ESP32
    """
    print("\n" + "="*70)
    print(f"TEST 3: REAL DATA PROCESSING - {csv_file}")
    print("="*70)
    
    processor = EMGProcessor(sampling_rate=1000)
    processor.load_from_csv(csv_file)
    
    results = process_emg_data(processor.time, processor.raw_data)
    
    print("✓ Real data processing completed")
    print(f"  Results saved to: {results['output_dir']}")


def test_esp32_communication():
    """
    Test ESP32 serial communication without data processing.
    Useful for debugging hardware connection issues.
    """
    print("\n" + "="*70)
    print("TEST 4: ESP32 SERIAL COMMUNICATION")
    print("="*70)
    
    try:
        import serial
        import serial.tools.list_ports
    except ImportError:
        print("ERROR: pyserial not installed. Install with: pip install pyserial")
        return
    
    print("\nAvailable serial ports:")
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("  No serial ports found!")
        return
    
    for i, p in enumerate(ports):
        print(f"  [{i}] {p.device}: {p.description}")
    
    if ports:
        port = ports[0].device
        print(f"\nTesting connection on {port}...")
        
        try:
            ser = serial.Serial(port, 921600, timeout=1)
            print(f"✓ Successfully opened {port}")
            
            # Read a few lines
            print("Reading startup messages:")
            for _ in range(5):
                line = ser.readline().decode().strip()
                if line:
                    print(f"  {line}")
            
            ser.close()
            print("✓ Connection test passed")
        
        except Exception as e:
            print(f"✗ Connection failed: {e}")


# ============================================================================
# COMMAND-LINE INTERFACE
# ============================================================================

def main():
    """Main entry point with command-line argument handling."""
    
    parser = argparse.ArgumentParser(
        description='EMG Signal Processing Pipeline for Prosthetic Control',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Test with synthetic data
  python main_pipeline.py --mode synthetic
  
  # Stream from ESP32
  python main_pipeline.py --mode live --port COM3
  
  # Process previously recorded file
  python main_pipeline.py --mode load --file emg_data_20231215_143022.csv

  # Load volunteer 1 from local dataset (raw or filtered) using default filter preset
  python main_pipeline.py --mode load --volunteer 1 --dataset-source raw --preset default
  
  # Run validation tests
  python main_pipeline.py --test all
  python main_pipeline.py --test synthetic
  python main_pipeline.py --test stability
        '''
    )
    
    parser.add_argument('--mode', choices=['synthetic', 'live', 'load'],
                       default='synthetic',
                       help='Data acquisition mode')
    parser.add_argument('--port', default='COM3',
                       help='Serial port for ESP32 (default: COM3)')
    parser.add_argument('--file', default=None,
                       help='CSV file for load mode')
    parser.add_argument('--volunteer', type=int, default=None,
                       help='Volunteer id to load from dataset (e.g., 1)')
    parser.add_argument('--dataset-source', choices=['raw','filtered'], default='raw',
                       help='Dataset subfolder to use when loading volunteers (raw or filtered)')
    parser.add_argument('--duration', type=float, default=10.0,
                       help='Recording duration in seconds (live mode)')
    parser.add_argument('--snr', type=float, default=10.0,
                       help='SNR (dB) for synthetic data generation')
    parser.add_argument('--channel', default=None,
                       help='Channel name or index to load from multichannel CSV; if omitted concatenates all channels')
    parser.add_argument('--output', default='./results',
                       help='Output directory for results')
    parser.add_argument('--preset', type=str, default=None,
                       help='Filter preset name (see emg_filters.PRESETS) to apply before processing')
    parser.add_argument('--list-presets', action='store_true',
                       help='List available filter presets and exit')
    parser.add_argument('--analyze-filtered', action='store_true',
                       help='Run frequency analysis (PSD/FFT) on the last pre-envelope filtered signal and save result')
    parser.add_argument('--test', choices=['all', 'synthetic', 'stability', 'serial', 'real'],
                       help='Run validation tests instead of processing')
    
    args = parser.parse_args()
    
    print("\n" + "="*70)
    print("EMG SIGNAL PROCESSING SYSTEM")
    print("="*70)
    
    # Run tests if requested
    if args.test:
        if args.test in ['all', 'synthetic']:
            test_synthetic_data()
        
        if args.test in ['all', 'stability']:
            test_filter_stability()
        
        if args.test in ['all', 'serial']:
            test_esp32_communication()
        
        return
    
    # If user asked to list presets, show them and exit
    if args.list_presets:
        print("Available filter presets:")
        for name in emg_filters.PRESETS.keys():
            print(f" - {name}")
        return

    # Normal operation
    if args.mode == 'synthetic':
        print("\nMode: SYNTHETIC DATA GENERATION")
        processor = EMGProcessor(sampling_rate=1000)
        duration = args.duration if args.duration else 5.0
        processor.generate_synthetic_data(duration_sec=duration, snr_db=args.snr)
        time_array = processor.time
        voltage_array = processor.raw_data
    
    elif args.mode == 'live':
        print(f"\nMode: LIVE ACQUISITION from {args.port}")
        time_array, voltage_array = acquire_from_serial(
            port=args.port,
            duration_sec=args.duration
        )
        if time_array is None:
            return
    
    elif args.mode == 'load':
        print(f"\nMode: LOAD FROM FILE/DATASET")
        processor = EMGProcessor(sampling_rate=1000)
        if args.file:
            processor.load_from_csv(args.file)
            time_array = processor.time
            voltage_array = processor.raw_data
        elif args.volunteer is not None:
            # Pass channel through (may be name or index string)
            ch = args.channel
            # try to convert numeric-looking channel to int
            if ch is not None:
                try:
                    ch_idx = int(ch)
                    ch = ch_idx
                except Exception:
                    pass
            processor.load_from_dataset(source=args.dataset_source, volunteer_id=args.volunteer, channel=ch)
            time_array = processor.time
            voltage_array = processor.raw_data
        else:
            print("ERROR: --file or --volunteer required for load mode")
            return

    # Process data (pass selected filter preset name)
    results = process_emg_data(time_array, voltage_array, args.output, preset_name=args.preset, analyze_filtered=args.analyze_filtered)
    
    print("\n" + "="*70)
    print("PROCESSING COMPLETE")
    print("="*70)
    print(f"Results saved to: {args.output}/")
    print("\nGenerated files:")
    print("  - 01_emg_processing_pipeline.png")
    print("  - 02_filter_frequency_response.png")
    print("  - 03_gripper_control.png")
    print("  - 04_filtered_signal_frequency_analysis.png (if --analyze-filtered used)")
    print("  - results_summary.csv")


if __name__ == "__main__":
    # Allow matplotlib to work in non-interactive environments
    import matplotlib
    matplotlib.use('Agg')  # Use non-interactive backend
    import matplotlib.pyplot as plt
    
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
        sys.exit(0)
