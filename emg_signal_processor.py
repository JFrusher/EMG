"""
EMG Signal Processing Module
=============================

Comprehensive EMG signal filtering, analysis, and control interpretation
for prosthetic applications.

Author: Biomedical Signal Processing System
Modules:
  - Signal loading and preprocessing
  - Multi-stage filtering (Notch, Bandpass, Butterworth)
  - Envelope extraction
  - SNR calculation
  - Feature extraction
  - Peak detection and control interpretation
  - Data visualization

Usage:
  from emg_signal_processor import EMGProcessor
  processor = EMGProcessor(sampling_rate=1000)
  processor.load_data('emg_data.csv')
  results = processor.process_complete_pipeline()
  processor.calculate_snr()
  processor.visualize_all()
"""

import numpy as np
from scipy import signal
from scipy.signal import butter, iirnotch, filtfilt, find_peaks
import matplotlib.pyplot as plt
import pandas as pd
import os
import glob
from typing import Tuple, Dict, List
import argparse
import warnings

warnings.filterwarnings('ignore')

# ============================================================================
# EMG PROCESSOR CLASS
# ============================================================================

class EMGProcessor:
    """
    Complete EMG signal processing pipeline with filtering, feature extraction,
    and control signal interpretation.
    
    Attributes:
        sampling_rate (int): Samples per second (typically 1000 Hz)
        raw_data (np.ndarray): Original EMG signal
        time (np.ndarray): Time vector in seconds
        filtered_stages (dict): Intermediate filtering results
        envelope (np.ndarray): Final envelope signal
    """
    
    def __init__(self, sampling_rate: int = 1000):
        """
        Initialize EMG processor with sampling rate.
        
        Args:
            sampling_rate: ADC sampling frequency in Hz (default 1000)
        """
        self.sampling_rate = sampling_rate
        self.raw_data = None
        self.time = None
        self.filtered_stages = {}
        self.envelope = None
        self.peaks = None
        self.control_commands = None
        
    # ========================================================================
    # DATA INPUT FUNCTIONS
    # ========================================================================
    
    def load_from_csv(self, filename: str, voltage_range: float = 3.3):
        """
        Load EMG data from CSV file acquired by ESP32.
        
        CSV Format:
            timestamp_ms,adc_raw_value
            0,2048
            1,2050
            ...
        
        Args:
            filename: Path to CSV file
            voltage_range: ADC reference voltage (3.3V for ESP32)
        """
        print(f"Loading data from {filename}...")
        
        # Read CSV file
        df = pd.read_csv(filename)
        
        # Extract ADC values and convert to voltage
        adc_values = df['adc_raw_value'].values
        self.raw_data = (adc_values / 4095.0) * voltage_range  # 12-bit ADC
        
        # Create time vector
        num_samples = len(self.raw_data)
        self.time = np.arange(num_samples) / self.sampling_rate
        
        print(f"Loaded {num_samples} samples ({self.time[-1]:.2f} seconds)")
        print(f"Signal range: {self.raw_data.min():.3f}V to {self.raw_data.max():.3f}V")
        
    def load_from_numpy(self, data: np.ndarray):
        """
        Load EMG data from numpy array.
        
        Args:
            data: 1D numpy array of EMG samples
        """
        self.raw_data = np.asarray(data, dtype=np.float32)
        num_samples = len(self.raw_data)
        self.time = np.arange(num_samples) / self.sampling_rate
        print(f"Loaded {num_samples} samples from numpy array")
        
    def generate_synthetic_data(self, duration_sec: float = 5.0, 
                           snr_db: float = 10.0):
        """
        Generate realistic synthetic EMG signal for testing.
        
        FIXED: Generate EMG in the actual 50-200 Hz range (more realistic)
        """
        num_samples = int(duration_sec * self.sampling_rate)
        self.time = np.arange(num_samples) / self.sampling_rate
        
        # Generate realistic EMG (50-200 Hz content, actual muscle frequency)
        emg = np.zeros(num_samples)
        
        # Add multiple EMG frequency components (50-150 Hz typical)
        for freq in [50, 75, 100, 125, 150]:
            amplitude = 0.3 / 5  # Divide equally among frequencies
            emg += amplitude * np.sin(2 * np.pi * freq * self.time)
        
        # Add muscle activation bursts (2-3 Hz bursts)
        activation = np.zeros(num_samples)
        burst_starts = [0.5, 1.5, 2.5, 3.5, 4.5]  # Times when muscle activates
        for start_time in burst_starts:
            start_idx = int(start_time * self.sampling_rate)
            duration_idx = int(0.6 * self.sampling_rate)  # 600ms bursts
            activation[start_idx:start_idx + duration_idx] = 1.0
        
        # Smooth activation envelope
        activation_smooth = np.convolve(activation, np.ones(100)/100, mode='same')
        
        # Modulate EMG by activation
        emg_modulated = emg * activation_smooth
        
        # Add Gaussian noise
        signal_power = np.mean(emg_modulated ** 2)
        snr_linear = 10 ** (snr_db / 10)
        noise_power = signal_power / snr_linear
        noise = np.random.normal(0, np.sqrt(noise_power), num_samples)
        
        # Add 50 Hz powerline (to test notch filter)
        powerline = 0.1 * np.sin(2 * np.pi * 50 * self.time)
        
        # Combine
        self.raw_data = emg_modulated + noise + powerline
        
        # Normalize to 0-3.3V range (mimic ADC output)
        self.raw_data = (self.raw_data / np.max(np.abs(self.raw_data))) * 1.5 + 1.65
        
        print(f"Generated synthetic EMG: {duration_sec}s, SNR={snr_db}dB")
        print(f"  - EMG frequencies: 50-150 Hz")
        print(f"  - Signal power: {signal_power:.4f}")
        print(f"  - Noise power: {noise_power:.4f}")
        
    def load_from_dataset(self, dataset_dir: str = None, source: str = 'raw',
                          volunteer_id: int = None, filename: str = None,
                          channel = None, voltage_range: float = 3.3):
        """
        Load EMG data from local dataset CSV files.

        Args:
            dataset_dir: Base dataset directory. If None, defaults to the project's
                         `EMGdataset/dataset` folder next to this module.
            source:     One of 'raw', 'filtered', or 'synthetic'. If 'synthetic', this
                        will call `generate_synthetic_data()` and return.
            volunteer_id: If provided, selects a file matching the volunteer id
                          (e.g. volunteer_1.csv or volunteer_filtered_1.csv).
            filename:   Exact CSV filename to load (overrides volunteer_id)
            channel:    Column name (str) or index (int) to select a single channel.
                        If None and multiple numeric columns exist, columns are
                        concatenated end-to-end and `self.channel_order`
                        / `self.channel_segments` are populated to describe
                        which sample ranges correspond to which channel.
            voltage_range: ADC reference voltage used to convert raw ADC values
                           (used when CSV contains 'adc_raw_value')
        """
        """
        Load EMG data from local dataset CSV files.

        Args:
            dataset_dir: Base dataset directory. If None, defaults to the project's
                         `EMGdataset/dataset` folder next to this module.
            source:     One of 'raw', 'filtered', or 'synthetic'. If 'synthetic', this
                        will call `generate_synthetic_data()` and return.
            volunteer_id: If provided, selects a file matching the volunteer id
                          (e.g. volunteer_1.csv or volunteer_filtered_1.csv).
            filename:   Exact CSV filename to load (overrides volunteer_id)
            voltage_range: ADC reference voltage used to convert raw ADC values
                           (used when CSV contains 'adc_raw_value')
        """
        # Allow quick synthetic shortcut
        if source == 'synthetic':
            print("Loading synthetic data via load_from_dataset(source='synthetic')")
            self.generate_synthetic_data()
            return

        # Resolve base dataset directory
        if dataset_dir is None:
            base_dir = os.path.join(os.path.dirname(__file__), 'EMGdataset', 'dataset')
        else:
            base_dir = dataset_dir

        subdir = 'raw_signals' if source == 'raw' else 'filtered_signals'
        folder = os.path.join(base_dir, subdir)

        if not os.path.isdir(folder):
            raise FileNotFoundError(f"Dataset folder not found: {folder}")

        # Find candidate CSV files
        candidates = sorted(glob.glob(os.path.join(folder, '*.csv')))

        # Choose target file based on filename, volunteer_id, or first candidate
        if filename:
            target = os.path.join(folder, filename)
            if not os.path.isfile(target):
                raise FileNotFoundError(f"File not found: {target}")
        elif volunteer_id is not None:
            pattern = f"*{volunteer_id}*.csv"
            matches = sorted(glob.glob(os.path.join(folder, pattern)))
            if not matches:
                raise FileNotFoundError(f"No files matching volunteer id {volunteer_id} in {folder}")
            target = matches[0]
        else:
            if not candidates:
                raise FileNotFoundError(f"No CSV files found in {folder}")
            target = candidates[0]

        print(f"Loading dataset file: {target}")
        df = pd.read_csv(target)

        # Drop likely index/time columns before selecting channels
        drop_cols = []
        for c in df.columns:
            lc = c.lower()
            if lc.startswith('unnamed') or 'timestamp' in lc or lc == 'time' or lc == 'index':
                drop_cols.append(c)

        # If first column is a perfect sequence 0..N-1 treat it as index/time and drop it
        first_col = df.columns[0]
        if first_col not in drop_cols and np.issubdtype(df[first_col].dtype, np.number):
            vals = df[first_col].values
            if np.array_equal(vals, np.arange(len(df))):
                drop_cols.append(first_col)

        if drop_cols:
            print(f"  - Dropping likely index/time columns: {drop_cols}")
            df = df.drop(columns=drop_cols)

        # If columns present like 'adc_raw_value' or 'voltage', prefer those
        numeric_cols = [c for c in df.columns if np.issubdtype(df[c].dtype, np.number)]

        # Handle ESP32-style single-column CSVs
        if 'adc_raw_value' in df.columns:
            adc_values = df['adc_raw_value'].values
            self.raw_data = (adc_values / 4095.0) * voltage_range
            self.channel_order = ['adc_raw_value']
            self.channel_segments = [( 'adc_raw_value', 0, len(self.raw_data) )]

        elif 'voltage' in df.columns and (channel is None or channel == 'voltage'):
            self.raw_data = df['voltage'].values.astype(float)
            self.channel_order = ['voltage']
            self.channel_segments = [( 'voltage', 0, len(self.raw_data) )]

        # If CSV has a single numeric column, use it
        elif len(numeric_cols) == 1:
            col = numeric_cols[0]
            self.raw_data = df[col].values.astype(float)
            self.channel_order = [col]
            self.channel_segments = [(col, 0, len(self.raw_data))]

        else:
            # Multiple numeric columns
            if channel is not None:
                # Channel may be index or name
                if isinstance(channel, int) or (isinstance(channel, str) and channel.isdigit()):
                    idx = int(channel)
                    if idx < 0 or idx >= len(numeric_cols):
                        raise IndexError(f"Channel index {idx} out of range (0..{len(numeric_cols)-1})")
                    col = numeric_cols[idx]
                else:
                    col = channel
                    if col not in numeric_cols:
                        raise ValueError(f"Requested channel '{col}' not found in numeric columns: {numeric_cols}")

                self.raw_data = df[col].values.astype(float)
                self.channel_order = [col]
                self.channel_segments = [(col, 0, len(self.raw_data))]

            else:
                # Concatenate all numeric columns end-to-end and record segments
                parts = []
                segments = []
                cursor = 0
                for col in numeric_cols:
                    series = df[col].values.astype(float)
                    parts.append(series)
                    start = cursor
                    end = cursor + len(series)
                    segments.append((col, start, end))
                    cursor = end

                if parts:
                    self.raw_data = np.concatenate(parts)
                    self.channel_order = numeric_cols
                    self.channel_segments = segments
                else:
                    raise ValueError("No numeric columns found in dataset CSV")

        # Create time vector
        self.time = np.arange(len(self.raw_data)) / self.sampling_rate
        print(f"Loaded {len(self.raw_data)} samples from {os.path.basename(target)}")

        # If we concatenated channels, print a summary of order and ranges
        if hasattr(self, 'channel_order') and len(self.channel_order) > 1:
            print("  - Channels concatenated in order:")
            for name, start, end in self.channel_segments:
                print(f"    * {name}: samples [{start}:{end}] -> time {start/self.sampling_rate:.2f}s to {end/self.sampling_rate:.2f}s")

    # ========================================================================
    # FILTERING FUNCTIONS
    # ========================================================================
    
    # ---------------------------
    # Filter chain / factories
    # ---------------------------
    def make_notch(self, freq: float = 50, q: float = 30) -> dict:
        """Factory for a notch filter spec."""
        return {'type': 'notch', 'freq': float(freq), 'q': float(q)}

    def make_butter_bandpass(self, lowcut: float = 20, highcut: float = 400, order: int = 2) -> dict:
        """Factory for Butterworth bandpass filter spec."""
        return {'type': 'butter_bandpass', 'lowcut': float(lowcut), 'highcut': float(highcut), 'order': int(order)}

    def make_butter_lowpass(self, cutoff: float = 150, order: int = 3) -> dict:
        """Factory for Butterworth low-pass filter spec."""
        return {'type': 'butter_lowpass', 'cutoff': float(cutoff), 'order': int(order)}

    def make_butter_highpass(self, cutoff: float = 20, order: int = 3) -> dict:
        """Factory for Butterworth high-pass filter spec."""
        return {'type': 'butter_highpass', 'cutoff': float(cutoff), 'order': int(order)}

    def make_moving_average(self, window_ms: float = 200) -> dict:
        """Factory for moving average smoothing spec."""
        return {'type': 'moving_average', 'window_ms': float(window_ms)}

    def add_filter(self, filter_spec: dict):
        """Append a filter spec to the internal filter chain."""
        if not hasattr(self, 'filter_chain') or self.filter_chain is None:
            self.filter_chain = []
        self.filter_chain.append(filter_spec)
        print(f"Added filter to chain: {filter_spec}")

    def clear_filters(self):
        """Clear the filter chain."""
        self.filter_chain = []
        print("Cleared filter chain")

    def get_filter_summary(self) -> List[str]:
        """Return a human-readable summary of the configured filter chain."""
        if not hasattr(self, 'filter_chain') or not self.filter_chain:
            return []
        out = []
        for f in self.filter_chain:
            t = f.get('type')
            if t == 'notch':
                out.append(f"Notch {f['freq']}Hz Q={f['q']}")
            elif t == 'butter_bandpass':
                out.append(f"Bandpass {f['lowcut']}-{f['highcut']} Hz, order={f['order']}")
            elif t == 'butter_lowpass':
                out.append(f"Low-pass {f['cutoff']} Hz, order={f['order']}")
            elif t == 'butter_highpass':
                out.append(f"High-pass {f['cutoff']} Hz, order={f['order']}")
            elif t == 'moving_average':
                out.append(f"MovingAvg {f['window_ms']} ms")
            else:
                out.append(str(f))
        return out

    def last_filtered_signal(self):
        """Return the most recently added filtered signal or raw data if none."""
        if self.filtered_stages:
            # take last inserted key
            last_key = list(self.filtered_stages.keys())[-1]
            return self.filtered_stages[last_key]
        else:
            return self.raw_data

    def apply_filter_chain(self):
        """Apply the configured filter chain in order and store intermediate results.

        If no chain is configured, a sensible default (notch 50 Hz then bandpass 20-400 Hz)
        will be applied.
        """
        if not hasattr(self, 'filter_chain') or not self.filter_chain:
            # sensible defaults
            self.filter_chain = [
                self.make_notch(50, 30),
                self.make_butter_bandpass(20, 400, order=2)
            ]
            print("Using default filter chain: Notch 50Hz + Bandpass 20-400Hz")

        current = self.raw_data
        # Clear any previous filter stages
        self.filtered_stages = {}

        for idx, f in enumerate(self.filter_chain):
            t = f.get('type')
            if t == 'notch':
                b, a = iirnotch(f['freq'], f['q'], self.sampling_rate)
                filtered = filtfilt(b, a, current)
                name = f"notch_{int(f['freq'])}Hz_Q{int(f['q'])}"

            elif t == 'butter_bandpass':
                b, a = butter(int(f['order']), [f['lowcut'], f['highcut']], btype='band', fs=self.sampling_rate)
                filtered = filtfilt(b, a, current)
                name = f"bandpass_{int(f['lowcut'])}-{int(f['highcut'])}_o{int(f['order'])}"

            elif t == 'butter_lowpass':
                b, a = butter(int(f['order']), f['cutoff'], btype='low', fs=self.sampling_rate)
                filtered = filtfilt(b, a, current)
                name = f"lowpass_{int(f['cutoff'])}_o{int(f['order'])}"

            elif t == 'butter_highpass':
                b, a = butter(int(f['order']), f['cutoff'], btype='high', fs=self.sampling_rate)
                filtered = filtfilt(b, a, current)
                name = f"highpass_{int(f['cutoff'])}_o{int(f['order'])}"

            elif t == 'moving_average':
                window_samples = int(f['window_ms'] * self.sampling_rate / 1000)
                kernel = np.ones(window_samples) / window_samples
                filtered = np.convolve(current, kernel, mode='same')
                name = f"movavg_{int(f['window_ms'])}ms"

            else:
                raise ValueError(f"Unknown filter type: {t}")

            self.filtered_stages[name] = filtered
            current = filtered
            print(f"Applied filter: {name}")

        return current

    # ------------------------------------------------------------------------
    # Backwards compatible single-filter helpers
    # ------------------------------------------------------------------------
    def apply_notch_filter(self, freq: float = 50, quality_factor: float = 30):
        """
        Apply notch (band-stop) filter to remove powerline interference.
        
        Removes specific frequency (50 Hz in UK, 60 Hz in US) with high Q-factor
        for sharp rejection. Minimal effect on surrounding frequencies.
        
        Args:
            freq: Frequency to remove (50 or 60 Hz)
            quality_factor: Q factor (higher = sharper rejection)
        
        Returns:
            Filtered signal
        """
        if self.raw_data is None:
            raise ValueError("No data loaded. Call load_from_csv() first.")
        
        # Design notch filter
        b, a = iirnotch(freq, quality_factor, self.sampling_rate)
        
        # Apply forward-backward filtering (zero-phase)
        filtered = filtfilt(b, a, self.raw_data)
        
        self.filtered_stages['notch'] = filtered
        print(f"Applied notch filter: {freq} Hz ± {freq/quality_factor:.1f} Hz")
        return filtered
    
    def apply_bandpass_filter(self, lowcut: float = 20, highcut: float = 490, 
                             order: int = 4):
        """
        Apply bandpass filter to isolate EMG frequency content (20-500 Hz).
        
        Removes DC component and baseline wander (< 20 Hz) and attenuates
        noise above 500 Hz.
        
        Args:
            lowcut: Low cutoff frequency (Hz)
            highcut: High cutoff frequency (Hz)
            order: Filter order (higher = steeper slope)
        
        Returns:
            Filtered signal
        """
        if 'notch' in self.filtered_stages:
            input_signal = self.filtered_stages['notch']
        elif self.raw_data is not None:
            input_signal = self.raw_data
        else:
            raise ValueError("No data loaded.")
        
        # Design Butterworth bandpass filter
        b, a = butter(order, [lowcut, highcut], btype='band', fs=self.sampling_rate)

        
        # Apply forward-backward filtering
        filtered = filtfilt(b, a, input_signal)
        
        self.filtered_stages['bandpass'] = filtered
        print(f"Applied bandpass filter: {lowcut}-{highcut} Hz, order {order}")
        return filtered
    
    def apply_butterworth_lowpass(self, cutoff: float = 150, order: int = 3):
        """
        Apply Butterworth low-pass filter for envelope extraction.
        
        Smooths the rectified signal to create an envelope that represents
        overall muscle activation level.
        
        Args:
            cutoff: Cutoff frequency (Hz)
            order: Filter order
        
        Returns:
            Filtered signal
        """
        input_signal = self.last_filtered_signal()
        # Design Butterworth low-pass filter
        b, a = butter(order, cutoff, btype='low', fs=self.sampling_rate)
        
        # Apply forward-backward filtering
        filtered = filtfilt(b, a, input_signal)
        
        self.filtered_stages[f'butterworth_{int(cutoff)}Hz_o{int(order)}'] = filtered
        return filtered

    def apply_rectification(self):
        """
        Apply full-wave rectification to remove negative component.

        Takes absolute value of signal, essential for envelope detection.
        Rectification precedes Butterworth filter in pipeline.

        Returns:
            Rectified signal
        """
        input_signal = self.last_filtered_signal()
        if input_signal is None:
            raise ValueError("No filtered signal available. Run filters first or load data.")
        rectified = np.abs(input_signal)
        self.filtered_stages['rectified'] = rectified
        print("Applied full-wave rectification")
        return rectified

    def apply_moving_average_envelope(self, window_ms: float = 200):
        """
        Apply moving average for final envelope smoothing.
        
        Creates smooth envelope representing muscle activation.
        
        Args:
            window_ms: Window size in milliseconds
        
        Returns:
            Envelope signal
        """
        window_samples = int(window_ms * self.sampling_rate / 1000)
        
        # Try to use any 'butterworth' stage if available, otherwise use 'rectified'
        butter_key = next((k for k in reversed(self.filtered_stages.keys()) if 'butterworth' in k), None)
        if butter_key is not None:
            input_signal = self.filtered_stages[butter_key]
        elif 'rectified' in self.filtered_stages:
            input_signal = self.filtered_stages['rectified']
        else:
            raise ValueError("Apply rectification first.")
        
        # Moving average using convolve
        kernel = np.ones(window_samples) / window_samples
        envelope = np.convolve(input_signal, kernel, mode='same')
        
        # CRITICAL: Store in self.envelope so extract_features() can find it
        self.envelope = envelope
        
        print(f"Applied moving average envelope: {window_ms}ms window")
        return envelope

    # ------------------------------------------------------------------------
    # EXPORT / ANALYSIS HELPERS
    # ------------------------------------------------------------------------
    def get_pre_envelope(self) -> np.ndarray:
        """
        Return the signal used immediately before the envelope (pre-envelope).
        Prefers any filter stage whose name includes 'butterworth' if present,
        otherwise returns 'rectified'.
        Raises:
            ValueError if no suitable stage is available (run processing first).
        """
        # Prefer any stage with 'butterworth' in its key name (choose most recent)
        for k in reversed(list(self.filtered_stages.keys())):
            if 'butterworth' in k:
                return np.copy(self.filtered_stages[k])

        if 'rectified' in self.filtered_stages:
            return np.copy(self.filtered_stages['rectified'])
        else:
            raise ValueError("No pre-envelope signal available. Run processing pipeline first.")

    def export_pre_envelope(self, filepath: str, include_time: bool = True) -> str:
        """
        Export the pre-envelope signal to a CSV file so it can be analyzed separately
        (for example by `frequency_analyzer.py`).

        Args:
            filepath: Path to output CSV file
            include_time: If True and a time vector exists, include `time_sec` column

        Returns:
            The path to the written file
        """
        sig = self.get_pre_envelope()
        # Ensure parent folder exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        if include_time and self.time is not None and len(self.time) >= len(sig):
            df = pd.DataFrame({'time_sec': self.time[:len(sig)], 'pre_envelope': sig})
        else:
            df = pd.DataFrame({'pre_envelope': sig})

        df.to_csv(filepath, index=False)
        print(f"Exported pre-envelope signal to {filepath}")
        return filepath

    def analyze_pre_envelope(self, save_path: str = None, show_plot: bool = True):
        """
        Run frequency analysis on the pre-envelope signal using the project's
        `FrequencyAnalyzer` and optionally save the resulting plot.

        Args:
            save_path: Optional path to save the frequency analysis plot
            show_plot: If True, will display the plot as well as optionally save it

        Returns:
            An instance of `FrequencyAnalyzer` with results populated
        """
        pre = self.get_pre_envelope()
        # local import to avoid unnecessary top-level imports
        from frequency_analyzer import FrequencyAnalyzer

        analyzer = FrequencyAnalyzer(sampling_rate=self.sampling_rate)
        analyzer.data = pre
        analyzer.compute_fft()
        analyzer.print_analysis()
        if show_plot:
            analyzer.plot_frequency_response(save_path=save_path)
        return analyzer

    # ========================================================================
    # PROCESSING PIPELINE
    # ========================================================================
    
    def process_complete_pipeline(self, run_freq_analysis: bool = False, freq_save_path: str = None) -> Dict:
        """
        Execute complete EMG processing pipeline in correct order:
        
        1. Notch filter (50/60 Hz removal)
        2. Bandpass filter (20-500 Hz EMG content)
        3. Full-wave rectification
        4. Butterworth low-pass filter (150 Hz)
        5. Moving average envelope
        
        Optional:
            - run_freq_analysis: if True, runs frequency analysis on the pre-envelope
                                 signal and (optionally) saves the plot to `freq_save_path`.

        Returns:
            Dictionary containing all processed signals
        """
        if self.raw_data is None:
            raise ValueError("No data loaded.")
        
        print("\n" + "="*60)
        print("EMG PROCESSING PIPELINE")
        print("="*60)
        
        # Step 1-2: Apply configured filter chain (defaults: Notch 50Hz + Bandpass 20-400Hz)
        self.apply_filter_chain()
        
        # Step 3: Rectify signal
        self.apply_rectification()
        
        # Step 4: Smooth with low-pass filter
        #self.apply_butterworth_lowpass(cutoff=150, order=3)
        
        # Step 5: Extract envelope
        self.apply_moving_average_envelope(window_ms=200)

        # Optionally run frequency analysis on the pre-envelope signal
        if run_freq_analysis:
            try:
                print("\nRunning frequency analysis on pre-envelope signal...")
                self.analyze_pre_envelope(save_path=freq_save_path, show_plot=True)
            except Exception as e:
                print(f"Frequency analysis failed: {e}")
        
        print("="*60)
        print("Pipeline complete.\n")
        
        return self.filtered_stages
    
    # ========================================================================
    # SIGNAL ANALYSIS
    # ========================================================================
    
    def calculate_snr(self) -> Dict[str, float]:
        """
        Calculate Signal-to-Noise Ratio at each filtering stage.
        
        FIXED: Use entire signal's noise floor, not just baseline
        """
        snr_results = {}
        
        # For synthetic data with mixed signal+noise, estimate noise from quietest regions
        # Use minimum RMS in sliding windows as noise estimate
        window_size = 500  # 500ms windows
        noise_estimates = []
        
        for i in range(0, len(self.raw_data) - window_size, window_size):
            window_rms = np.sqrt(np.mean(self.raw_data[i:i+window_size] ** 2))
            noise_estimates.append(window_rms)
        
        # Use the 10th percentile as noise floor
        noise_floor = np.percentile(noise_estimates, 10)
        noise_power = noise_floor ** 2
        
        if noise_power == 0:
            noise_power = 1e-10  # Avoid division by zero
        
        # Raw signal
        raw_power = np.mean(self.raw_data ** 2)
        snr_raw = 10 * np.log10(raw_power / noise_power)
        snr_results['raw'] = snr_raw
        
        # After each filter stage
        for stage_name, stage_signal in self.filtered_stages.items():
            signal_power = np.mean(stage_signal ** 2)
            snr = 10 * np.log10(signal_power / noise_power)
            snr_results[stage_name] = snr
        
        # Envelope
        if self.envelope is not None:
            envelope_power = np.mean(self.envelope ** 2)
            snr_env = 10 * np.log10(envelope_power / noise_power)
            snr_results['envelope'] = snr_env
        
        # Print results
        print("\nSignal-to-Noise Ratio Analysis:")
        print("-" * 40)
        for stage, snr_db in snr_results.items():
            print(f"{stage:15s}: {snr_db:6.2f} dB")
        
        return snr_results

    
    def extract_features(self) -> Dict[str, float]:
        """
        Extract EMG features from envelope signal.
        
        Features:
        - RMS: Root Mean Square (energy indicator)
        - MAV: Mean Absolute Value (amplitude)
        - Peak: Maximum amplitude
        - ZC: Zero crossings (frequency content)
        - MNF: Median Frequency
        
        Returns:
            Dictionary of feature values
        """
        if self.envelope is None:
            raise ValueError("Process complete pipeline first.")
        
        features = {}
        
        # Root Mean Square
        features['RMS'] = np.sqrt(np.mean(self.envelope ** 2))
        
        # Mean Absolute Value
        features['MAV'] = np.mean(np.abs(self.envelope))
        
        # Peak amplitude
        features['Peak'] = np.max(self.envelope)
        
        # Zero crossings
        zero_crossings = np.sum(np.abs(np.diff(np.sign(self.envelope - np.mean(self.envelope)))) / 2)
        features['ZC'] = zero_crossings
        
        # Waveform length
        features['WL'] = np.sum(np.abs(np.diff(self.envelope)))
        
        # Mean power frequency (approximation)
        fft = np.fft.fft(self.envelope)
        freqs = np.fft.fftfreq(len(self.envelope), 1/self.sampling_rate)
        pxx = np.abs(fft) ** 2
        # Only positive frequencies
        positive_idx = freqs > 0
        features['MNF'] = np.average(freqs[positive_idx], weights=pxx[positive_idx])
        
        print("\nFeature Extraction:")
        print("-" * 40)
        for feat_name, feat_value in features.items():
            if isinstance(feat_value, float):
                print(f"{feat_name:10s}: {feat_value:10.4f}")
            else:
                print(f"{feat_name:10s}: {feat_value}")
        
        return features
    
    def detect_peaks_and_control(self, threshold_percent: float = 50.0,
                            min_distance_ms: float = 100.0) -> Dict:
        """
        Detect muscle activation bursts (threshold crossings) and interpret as control commands.
        
        Instead of finding isolated peaks, this detects when the envelope CROSSES the threshold,
        which better represents intentional muscle contractions.
        
        Args:
            threshold_percent: Activation threshold as % of max
            min_distance_ms: Minimum time between activations (prevent bounce)
        
        Returns:
            Dictionary with activation events and control interpretation
        """
        if self.envelope is None:
            raise ValueError("Process complete pipeline first.")
        
        # Calculate threshold
        max_amplitude = np.max(self.envelope)
        threshold = (threshold_percent / 100.0) * max_amplitude
        
        # Detect threshold crossings (rising edges)
        above_threshold = self.envelope > threshold
        crossings = np.diff(above_threshold.astype(int))
        rising_edges = np.where(crossings == 1)[0]  # Rising edge (0→1)
        
        # Filter by minimum distance
        min_distance = int(min_distance_ms * self.sampling_rate / 1000)
        filtered_peaks = []
        last_peak = -min_distance
        
        for peak in rising_edges:
            if peak - last_peak >= min_distance:
                filtered_peaks.append(peak)
                last_peak = peak
        
        # Ensure peaks are stored as integer indices (empty -> int array)
        self.peaks = np.array(filtered_peaks, dtype=int)
        
        # Create control commands at each activation
        control_commands = []
        for peak in self.peaks:
            # Find peak amplitude during this activation burst
            # Look forward until signal drops below threshold
            activation_end = np.where(self.envelope[peak:] < threshold)[0]
            if len(activation_end) > 0:
                burst_end = peak + activation_end[0]
            else:
                burst_end = len(self.envelope)

            # Get max amplitude in this burst (with safety check for empty slices)
            burst_slice = self.envelope[peak:burst_end]
            if len(burst_slice) > 0:
                burst_amplitude = np.max(burst_slice)
            else:
                burst_amplitude = self.envelope[peak]  # Fallback to peak value itself

            confidence = burst_amplitude / max_amplitude
            
            # Determine grip type
            if burst_amplitude > max_amplitude * 0.5:
                command = 'GRIP'
            else:
                command = 'LIGHT_GRIP'
            
            control_commands.append({
                'time_sec': self.time[peak],
                'amplitude': burst_amplitude,
                'command': command,
                'confidence': confidence
            })
        
        self.control_commands = control_commands
        
        print(f"\nThreshold Crossing Detection (threshold: {threshold_percent}% of max):")
        print("-" * 40)
        print(f"Detected {len(self.peaks)} muscle activation events")
        for i, cmd in enumerate(control_commands):
            print(f"  Event {i+1}: {cmd['time_sec']:.2f}s, "
                f"Amplitude: {cmd['amplitude']:.3f}V, "
                f"Command: {cmd['command']}, "
                f"Confidence: {cmd['confidence']:.2%}")
        
        return {
            'peaks': self.peaks,
            'control_commands': control_commands,
            'threshold': threshold
        }

    
    # ========================================================================
    # VISUALIZATION
    # ========================================================================
    
    def visualize_all(self, save_path: str = None):
        """
        Dynamic visualization of processing pipeline.
        Plots will adapt to the set of filter stages in `self.filtered_stages` and
        will include a small text box summarizing the active filter chain.
        """
        if self.raw_data is None:
            raise ValueError("No data loaded.")

        # Build stage list: raw, then all filtered stages (in insertion order), rectified/envelope if present
        stages = [('Raw', self.raw_data)]
        for name, sig in self.filtered_stages.items():
            stages.append((name, sig))

        if 'rectified' in self.filtered_stages and ('rectified', self.filtered_stages['rectified']) not in stages:
            stages.append(('rectified', self.filtered_stages['rectified']))

        if self.envelope is not None:
            stages.append(('Envelope', self.envelope))

        # Always include a final envelope+peaks view if envelope present
        include_peak_view = self.envelope is not None

        nrows = len(stages) + (1 if include_peak_view else 0)
        fig, axes = plt.subplots(nrows, 1, figsize=(14, 3 * max(3, nrows)))
        if nrows == 1:
            axes = [axes]

        fig.suptitle('EMG Signal Processing Pipeline', fontsize=16, fontweight='bold')

        # Plot each stage
        for ax, (title, sig) in zip(axes, stages):
            ax.plot(self.time[:len(sig)], sig, color='#1f77b4', linewidth=0.8)
            ax.set_xlim(0, self.time[-1])
            ax.set_ylabel('Voltage (V)', fontweight='bold')
            ax.set_title(title, fontweight='bold')
            ax.grid(True, alpha=0.3)

            # Annotate if this stage corresponds to a configured filter
            if title in self.get_filter_summary() or any(title.startswith(k) for k in self.filtered_stages.keys()):
                # Put small label of params
                ax.text(0.99, 0.95, title, transform=ax.transAxes, ha='right', va='top', fontsize=9,
                        bbox=dict(facecolor='white', alpha=0.6, edgecolor='none'))

        # If concatenated channel segments exist, annotate them on the raw-stage plot
        if hasattr(self, 'channel_segments') and len(self.channel_segments) > 1:
            # find the axis for Raw stage
            raw_idx = next((i for i, (t, _) in enumerate(stages) if t == 'Raw'), None)
            if raw_idx is not None and raw_idx < len(axes):
                ax_raw = axes[raw_idx]
                y_max = np.max(self.raw_data)
                y_min = np.min(self.raw_data)
                y_span = y_max - y_min if y_max != y_min else 1.0
                for name, start, end in self.channel_segments:
                    t_start = start / self.sampling_rate
                    t_end = end / self.sampling_rate
                    ax_raw.axvline(x=t_start, color='grey', linestyle='--', alpha=0.6)
                    mid = (t_start + t_end) / 2.0
                    ax_raw.text(mid, y_max + 0.05 * y_span, name, ha='center', va='bottom', fontsize=9, color='black', bbox=dict(facecolor='white', alpha=0.6, edgecolor='none'))

        # Final envelope + peaks view
        if include_peak_view:
            ax = axes[-1]
            ax.plot(self.time, self.envelope, color='#1f77b4', linewidth=1.2, label='Envelope')

            if self.peaks is not None and len(self.peaks) > 0:
                idx = np.asarray(self.peaks, dtype=int)
                valid_idx = idx[(idx >= 0) & (idx < len(self.envelope))]
                if len(valid_idx) > 0:
                    ax.scatter(self.time[valid_idx], self.envelope[valid_idx], color='red', s=80, marker='^', label='Detected Peaks', zorder=5)

            # Threshold line if control commands present
            if self.control_commands:
                max_amp = np.max(self.envelope)
                threshold = max_amp * 0.2
                ax.axhline(y=threshold, color='red', linestyle='--', alpha=0.6, label='Threshold')

            ax.set_ylabel('Envelope (V)', fontweight='bold')
            ax.set_xlabel('Time (s)', fontweight='bold')
            ax.set_title('Final Envelope + Peaks', fontweight='bold')
            ax.grid(True, alpha=0.3)
            ax.legend(loc='upper right')

        # Show filter chain summary as an anchored textbox on the figure
        filter_summary = self.get_filter_summary()
        if filter_summary:
            txt = 'Filters:\n' + '\n'.join([f"- {s}" for s in filter_summary])
            # place text on top-left of figure
            fig.text(0.02, 0.98, txt, ha='left', va='top', fontsize=9, bbox=dict(facecolor='white', alpha=0.8, edgecolor='none'))

        plt.tight_layout(rect=[0, 0, 1, 0.96])

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            print(f"Figure saved to {save_path}")

        plt.show()
    
    def plot_frequency_response(self, save_path: str = None, pad: float = 0.04):
        """
        Plot frequency response of configured filter chain and the combined response.

        This function inspects `self.filter_chain` (or uses sensible defaults if
        none are set) and computes the frequency response for each stage. It
        plots both magnitude (dB) and phase (degrees) on two stacked subplots,
        overlays each individual filter and a bold combined response, and
        annotates the figure with the filter summary.

        Args:
            save_path: Optional path to save the figure (PNG). If None, the plot
                       is shown inline (or to the active Matplotlib backend).
            pad: Fractional padding to add around plotted lines (default 0.04 = 4%%).
                 This insets the plotted curves from the axis boundaries so
                 features near the edge are easier to inspect.
        """
        # Determine the active filter chain (use defaults if none present)
        if not hasattr(self, 'filter_chain') or not self.filter_chain:
            chain = [self.make_notch(50, 30), self.make_butter_bandpass(20, 400, order=2)]
            print("No filter chain configured — using default chain for plotting: Notch 50Hz + Bandpass 20-400Hz")
        else:
            chain = self.filter_chain

        # Frequency axis (0 .. Nyquist)
        nyq = self.sampling_rate / 2.0
        freqs = np.linspace(0, nyq, 2048)

        # Store responses for multiplication
        H_list = []
        labels = []
        skipped_filters = []

        for f in chain:
            t = f.get('type')
            try:
                if t == 'notch':
                    b, a = iirnotch(f['freq'], f['q'], self.sampling_rate)
                    w, h = signal.freqz(b, a, fs=self.sampling_rate, worN=freqs)
                    label = f"Notch {f['freq']}Hz Q={f['q']}"

                elif t == 'butter_bandpass':
                    b, a = butter(int(f['order']), [f['lowcut'], f['highcut']], btype='band', fs=self.sampling_rate)
                    w, h = signal.freqz(b, a, fs=self.sampling_rate, worN=freqs)
                    label = f"Bandpass {f['lowcut']}-{f['highcut']}Hz o{int(f['order'])}"

                elif t == 'butter_lowpass':
                    b, a = butter(int(f['order']), f['cutoff'], btype='low', fs=self.sampling_rate)
                    w, h = signal.freqz(b, a, fs=self.sampling_rate, worN=freqs)
                    label = f"Low-pass {f['cutoff']}Hz o{int(f['order'])}"

                elif t == 'butter_highpass':
                    b, a = butter(int(f['order']), f['cutoff'], btype='high', fs=self.sampling_rate)
                    w, h = signal.freqz(b, a, fs=self.sampling_rate, worN=freqs)
                    label = f"High-pass {f['cutoff']}Hz o{int(f['order'])}"

                elif t == 'moving_average':
                    # Moving-average is a time-domain smoothing (FIR) and not
                    # considered a frequency-domain filter for this plot. Skip it
                    # to avoid misleading frequency plots.
                    skipped_filters.append(f"MovAvg {int(f.get('window_ms', 0))} ms")
                    print("Skipping moving-average (time-domain smoothing) in frequency response plot")
                    continue

                else:
                    print(f"Warning: Unknown filter type '{t}' - skipping in frequency plot")
                    continue

            except Exception as e:
                print(f"Error designing filter {f}: {e}")
                continue

            H_list.append(h)
            labels.append(label)

        if not H_list:
            if skipped_filters:
                # No frequency-domain filters present, but some filters were skipped
                print("No frequency-domain filters to plot (only time-domain smoothing was configured).")
                print(f"Skipped filters: {skipped_filters}")
                return
            else:
                print("No valid filters to plot.")
                return

        # Compute combined response
        H_combined = np.ones_like(H_list[0])
        for h in H_list:
            H_combined = H_combined * h

        # If any filters were skipped (e.g., moving-average), annotate that on the figure
        skipped_text = None
        if skipped_filters:
            skipped_text = 'Skipped (time-domain): ' + ', '.join(skipped_filters)
        # Prepare figure: magnitude and phase
        fig, (ax_mag, ax_phase) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
        fig.suptitle('Filter Frequency Responses (Individual & Combined)', fontsize=14, fontweight='bold')

        # Plot each filter magnitude and phase
        colors = plt.cm.tab10.colors
        for i, (h, lbl) in enumerate(zip(H_list, labels)):
            mag_db = 20 * np.log10(np.maximum(np.abs(h), 1e-12))
            phase_deg = np.unwrap(np.angle(h)) * 180.0 / np.pi
            ax_mag.plot(w, mag_db, color=colors[i % len(colors)], alpha=0.8, label=lbl)
            ax_phase.plot(w, phase_deg, color=colors[i % len(colors)], alpha=0.8, label=lbl)

        # Plot combined response prominently
        mag_db_comb = 20 * np.log10(np.maximum(np.abs(H_combined), 1e-12))
        phase_deg_comb = np.unwrap(np.angle(H_combined)) * 180.0 / np.pi
        ax_mag.plot(w, mag_db_comb, color='k', linewidth=2.2, label='Combined', zorder=10)
        ax_phase.plot(w, phase_deg_comb, color='k', linewidth=2.2, label='Combined', zorder=10)

        ax_mag.set_ylabel('Magnitude (dB)', fontweight='bold')
        ax_mag.grid(True, alpha=0.3)

        # Apply padding so plotted lines have breathing room inside the axes
        # Start from the previous magnitude heuristics, then expand by `pad`
        curr_lower = np.max(mag_db_comb) - 120
        curr_upper = np.max(mag_db_comb) + 6
        delta = curr_upper - curr_lower
        ax_mag.set_ylim(curr_lower - pad * delta, curr_upper + pad * delta)
        ax_mag.set_xlim(0, nyq)
        ax_mag.margins(x=0.01)

        ax_phase.set_ylabel('Phase (deg)', fontweight='bold')
        ax_phase.set_xlabel('Frequency (Hz)', fontweight='bold')
        ax_phase.grid(True, alpha=0.3)

        # For phase, compute sensible bounds and add padding so edges aren't clipped
        phase_min = np.min(phase_deg_comb)
        phase_max = np.max(phase_deg_comb)
        pdelta = (phase_max - phase_min) if (phase_max != phase_min) else 1.0
        ax_phase.set_ylim(phase_min - pad * pdelta, phase_max + pad * pdelta)
        ax_phase.margins(x=0.01)

        # Legend and filter summary text
        ax_mag.legend(loc='upper right')
        filter_summary = self.get_filter_summary()
        if filter_summary:
            txt = 'Filters:\n' + '\n'.join([f"- {s}" for s in filter_summary])
            fig.text(0.02, 0.98, txt, ha='left', va='top', fontsize=9, bbox=dict(facecolor='white', alpha=0.8, edgecolor='none'))

        # If we skipped any filters from the frequency plot, add a short note
        if skipped_filters:
            note = 'Note: moving-average/time-domain smoothing filters omitted from frequency plot.'
            fig.text(0.02, 0.02, note, ha='left', va='bottom', fontsize=9, color='gray')

        # Increase spacing on all sides for better readability and save margin space
        plt.subplots_adjust(left=0.07, right=0.97, top=0.92, bottom=0.08, hspace=0.28)

        if save_path:
            # Use a larger pad to ensure whitespace is preserved in saved image
            fig.savefig(save_path, dpi=150, bbox_inches='tight', pad_inches=0.4)
            print(f"Frequency response saved to {save_path}")

        plt.show()


# ============================================================================
# STANDALONE TESTING FUNCTIONS
# ============================================================================

def test_synthetic_pipeline():
    """
    Test complete pipeline with synthetic EMG data.
    """
    print("\n" + "="*60)
    print("TESTING WITH SYNTHETIC DATA")
    print("="*60 + "\n")
    
    # Create processor
    processor = EMGProcessor(sampling_rate=1000)
    
    # Generate synthetic data
    processor.generate_synthetic_data(duration_sec=5.0, snr_db=20)
    
    # Process
    processor.process_complete_pipeline()
    
    # Analyze
    processor.calculate_snr()
    processor.extract_features()
    processor.detect_peaks_and_control()
    
    # Visualize
    processor.visualize_all()
    processor.plot_frequency_response()

    # --- Demonstrate export & frequency analysis of the pre-envelope signal ---
    os.makedirs('results', exist_ok=True)
    csv_path = os.path.join('results', 'pre_envelope.csv')
    png_path = os.path.join('results', 'pre_envelope_freq.png')
    processor.export_pre_envelope(csv_path)
    try:
        processor.analyze_pre_envelope(save_path=png_path, show_plot=False)
        print(f"Saved pre-envelope frequency analysis to: {png_path}")
    except Exception as e:
        print(f"Pre-envelope frequency analysis failed: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='Run EMGProcessor pipeline and helpers from CLI'
    )
    parser.add_argument('--mode', choices=['synthetic', 'dataset', 'file', 'test'], default='synthetic',
                        help='Mode to run (synthetic: generate test data, dataset: load from dataset, file: load single CSV, test: run built-in tests)')
    parser.add_argument('--file', default=None, help='Path to CSV file (used with --mode=file or to specify exact dataset filename)')
    parser.add_argument('--dataset-dir', default=None, help='Base dataset directory (when --mode=dataset)')
    parser.add_argument('--source', choices=['raw', 'filtered', 'synthetic'], default='synthetic', help='Dataset source when using --mode=dataset')
    parser.add_argument('--volunteer-id', type=int, default=None, help='Volunteer id to pick dataset file (when --mode=dataset)')
    parser.add_argument('--sampling-rate', type=int, default=1000, help='Sampling rate in Hz')

    # Frequency analysis / export flags
    parser.add_argument('--run-freq-analysis', action='store_true', help='Run frequency analysis on pre-envelope after processing')
    parser.add_argument('--fa-save', default=None, help='Path to save frequency analysis plot (optional)')
    parser.add_argument('--export-pre', default=None, help='Path to export pre-envelope CSV (optional)')
    parser.add_argument('--no-fa-plot', action='store_true', help='Do not display the frequency analysis plot (useful in headless environments)')

    args = parser.parse_args()

    # Create processor
    processor = EMGProcessor(sampling_rate=args.sampling_rate)

    # Load or generate data
    if args.mode == 'synthetic':
        processor.generate_synthetic_data()
    elif args.mode == 'file':
        if not args.file:
            parser.error("--file is required when --mode=file")
        processor.load_from_csv(args.file)
    elif args.mode == 'dataset':
        if args.source == 'synthetic':
            processor.generate_synthetic_data()
        else:
            processor.load_from_dataset(dataset_dir=args.dataset_dir, source=args.source, volunteer_id=args.volunteer_id, filename=args.file)
    elif args.mode == 'test':
        test_synthetic_pipeline()
        return

    # Run processing pipeline
    processor.process_complete_pipeline()

    # Optional: export pre-envelop CSV
    if args.export_pre:
        os.makedirs(os.path.dirname(args.export_pre), exist_ok=True)
        processor.export_pre_envelope(args.export_pre)

    # Optional: run frequency analysis on pre-envelope
    if args.run_freq_analysis:
        show_plot = not args.no_fa_plot
        try:
            processor.analyze_pre_envelope(save_path=args.fa_save, show_plot=show_plot)
            if args.fa_save:
                print(f"Saved frequency analysis to: {args.fa_save}")
        except Exception as e:
            print(f"Frequency analysis failed: {e}")


if __name__ == "__main__":
    main()
