"""
EMG Frequency Analysis Tool
============================

Analyzes CSV files to show frequency content (FFT) so you can see:
- Where the actual EMG signal is (peaks in spectrum)
- Where the noise is
- How to adjust filter parameters

Usage:
    python frequency_analyzer.py --file data.csv
    python frequency_analyzer.py --folder ./data

Output:
    - Power Spectral Density plot (shows energy at each frequency)
    - Peak frequencies identified
    - Recommendations for filter parameters
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import signal
from pathlib import Path
import argparse


class FrequencyAnalyzer:
    """Analyze EMG frequency content from CSV files."""
    
    def __init__(self, sampling_rate: int = 1000):
        """Initialize analyzer with sampling rate."""
        self.sampling_rate = sampling_rate
        self.data = None
        self.frequencies = None
        self.psd = None
    
    def load_csv(self, filepath: str) -> np.ndarray:
        """
        Load EMG data from CSV file.
        
        Expected format:
            timestamp_ms,adc_raw_value
            0,2048
            1,2050
            ...
        
        Args:
            filepath: Path to CSV file
        
        Returns:
            Voltage array
        """
        print(f"Loading {filepath}...")
        
        # Try different column names
        df = pd.read_csv(filepath)

        # DROP likely index/time columns (common names or sequential integer index)
        drop_cols = []
        for c in df.columns:
            cl = c.lower()
            if cl.startswith('unnamed') or 'timestamp' in cl or cl == 'time' or cl == 'index':
                drop_cols.append(c)

        # If first column is a perfect sequence 0..N-1 treat it as index
        first_col = df.columns[0]
        if first_col not in drop_cols and np.issubdtype(df[first_col].dtype, np.number):
            vals = df[first_col].values
            if np.array_equal(vals, np.arange(len(df))):
                drop_cols.append(first_col)

        if drop_cols:
            df = df.drop(columns=drop_cols)

        # Prefer explicit ADC/voltage columns, otherwise choose the numeric column with highest variance
        numeric_cols = [c for c in df.columns if np.issubdtype(df[c].dtype, np.number)]

        if 'adc_raw_value' in df.columns:
            adc_values = df['adc_raw_value'].values
            # Convert ADC to voltage (12-bit, 3.3V reference)
            self.data = (adc_values / 4095.0) * 3.3
            selected = 'adc_raw_value'

        elif 'voltage' in df.columns:
            self.data = df['voltage'].values.astype(float)
            selected = 'voltage'

        elif len(numeric_cols) == 1:
            selected = numeric_cols[0]
            self.data = df[selected].values.astype(float)

        elif len(numeric_cols) > 1:
            # Choose column with largest variance (most signal-like)
            variances = [np.var(df[c].values.astype(float)) for c in numeric_cols]
            idx = int(np.argmax(variances))
            selected = numeric_cols[idx]
            self.data = df[selected].values.astype(float)
            print(f"Multiple numeric columns found: {numeric_cols}. Selected '{selected}' by max variance.")

        else:
            raise ValueError("No numeric data columns found in CSV to analyze")

        print(f"Loaded {len(self.data)} samples ({len(self.data)/self.sampling_rate:.2f}s) using column: {selected}")
        print(f"Voltage range: {np.min(self.data):.3f}V to {np.max(self.data):.3f}V")

        return self.data
    
    def compute_fft(self):
        """
        Compute Power Spectral Density using FFT.
        
        Shows energy at each frequency.
        """
        if self.data is None:
            raise ValueError("Load data first.")
        
        print("\nComputing FFT...")
        
        # Compute FFT
        fft = np.fft.fft(self.data)
        
        # Power spectral density (magnitude squared)
        psd = np.abs(fft) ** 2
        
        # Frequency axis
        self.frequencies = np.fft.fftfreq(len(self.data), 1/self.sampling_rate)
        
        # Keep only positive frequencies
        positive_idx = self.frequencies >= 0
        self.frequencies = self.frequencies[positive_idx]
        self.psd = psd[positive_idx]
        
        # Smooth PSD with moving average for cleaner display
        window_size = 20
        self.psd_smoothed = np.convolve(self.psd, np.ones(window_size)/window_size, mode='same')
        
        print(f"Frequency range: 0 to {np.max(self.frequencies):.0f} Hz")
    
    def find_peaks(self, threshold_percentile: float = 90.0):
        """
        Find significant frequency peaks (signal content).
        
        Args:
            threshold_percentile: Only show peaks above this percentile
        
        Returns:
            Array of peak frequencies
        """
        if self.psd is None:
            raise ValueError("Compute FFT first.")
        
        # Find peaks
        threshold = np.percentile(self.psd_smoothed, threshold_percentile)
        peaks, properties = signal.find_peaks(self.psd_smoothed, height=threshold, distance=10)
        
        # Sort by power (height)
        sorted_idx = np.argsort(properties['peak_heights'])[::-1]
        peaks = peaks[sorted_idx]
        
        peak_freqs = self.frequencies[peaks]
        peak_powers = self.psd_smoothed[peaks]
        
        return peak_freqs, peak_powers
    
    def plot_frequency_response(self, save_path: str = None, title: str = None, annotation: str = None, pad: float = 0.04):
        """
        Create comprehensive frequency analysis plot.

        Shows:
        1. Full frequency spectrum (0-500 Hz)
        2. Zoomed EMG band (0-200 Hz)
        3. Detected peaks
        4. Recommended filter zones

        Args:
            save_path: Optional path to save figure
            title: Optional title to place on the figure (defaults to standard title)
            annotation: Optional text to annotate on the figure (e.g., filter summary)
            pad: Fractional padding to add around plotted lines (default 0.04 = 4%%).
                 This insets plotted curves from the axis boundaries so features
                 near the edge are easier to inspect.
        """
        if self.psd is None:
            raise ValueError("Compute FFT first.")

        fig, axes = plt.subplots(2, 1, figsize=(14, 10))
        fig.suptitle(title if title else 'EMG Frequency Content Analysis', fontsize=16, fontweight='bold')

        # Plot 1: Full spectrum (0-500 Hz)
        ax = axes[0]
        ax.semilogy(self.frequencies, self.psd_smoothed, color='#1f77b4', linewidth=1.5, label='PSD (smoothed)')
        ax.set_ylabel('Power (dB)', fontweight='bold', fontsize=11)
        ax.set_title('Full Frequency Spectrum (0-500 Hz)', fontweight='bold')
        ax.grid(True, alpha=0.3, which='both')
        ax.set_xlim(0, 500)
        # Add small margins so the plotted PSD has breathing room inside the axes
        ax.margins(x=0.01, y=pad)
        ax.legend()

        # Mark frequency zones
        ax.axvspan(0, 20, alpha=0.1, color='red', label='Baseline/DC (remove)')
        ax.axvspan(20, 400, alpha=0.1, color='green', label='EMG content (keep)')
        ax.axvspan(400, 500, alpha=0.1, color='orange', label='High noise (remove)')
        ax.axvline(50, color='purple', linestyle='--', linewidth=2, alpha=0.7, label='50 Hz powerline')
        ax.legend(loc='upper right', fontsize=9)

        # Plot 2: Zoomed to EMG band (0-200 Hz)
        ax = axes[1]
        ax.plot(self.frequencies, self.psd_smoothed, color='#1f77b4', linewidth=1.5, label='PSD')
        ax.set_xlabel('Frequency (Hz)', fontweight='bold', fontsize=11)
        ax.set_ylabel('Power', fontweight='bold', fontsize=11)
        ax.set_title('EMG Band Detail (0-200 Hz)', fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.set_xlim(0, 200)
        ax.set_yscale('log')
        # Add small margins to inset plotted PSD from the axes edges
        ax.margins(x=0.01, y=pad)

        # Find and mark peaks
        peak_freqs, peak_powers = self.find_peaks(threshold_percentile=85)
        peak_freqs_zoom = peak_freqs[peak_freqs <= 200]
        peak_powers_zoom = peak_powers[:len(peak_freqs_zoom)]

        ax.scatter(peak_freqs_zoom, peak_powers_zoom, color='red', s=100, marker='^', 
                  label='Signal peaks', zorder=5)

        # Annotate peaks
        for freq, power in zip(peak_freqs_zoom[:5], peak_powers_zoom[:5]):  # Top 5 peaks
            ax.annotate(f'{freq:.0f}Hz', xy=(freq, power), xytext=(5, 5), 
                       textcoords='offset points', fontsize=9, fontweight='bold')

        # Mark recommended filter bands
        ax.axvspan(20, 400, alpha=0.1, color='green', label='Recommended bandpass')
        ax.axvline(50, color='purple', linestyle='--', linewidth=2, alpha=0.7, label='50 Hz to remove')
        ax.legend(loc='upper right', fontsize=9)

        # If an annotation is provided, display it on the figure
        if annotation:
            fig.text(0.02, 0.98, annotation, ha='left', va='top', fontsize=9, bbox=dict(facecolor='white', alpha=0.8, edgecolor='none'))

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            print(f"Figure saved to {save_path}")

        plt.show()

        return fig
    
    def print_analysis(self):
        """Print detailed frequency analysis and recommendations."""
        if self.psd is None:
            raise ValueError("Compute FFT first.")
        
        print("\n" + "="*70)
        print("FREQUENCY ANALYSIS REPORT")
        print("="*70)
        
        # Find peaks
        peak_freqs, peak_powers = self.find_peaks(threshold_percentile=80)
        
        print("\nDetected Signal Peaks (top 10):")
        print("-" * 70)
        for i, (freq, power) in enumerate(zip(peak_freqs[:10], peak_powers[:10]), 1):
            percent = (power / np.max(peak_powers)) * 100
            print(f"  {i:2d}. {freq:7.1f} Hz - Power: {power:10.2e} ({percent:5.1f}%)")
        
        # Frequency band analysis
        print("\nFrequency Band Analysis:")
        print("-" * 70)
        
        bands = [
            ("DC/Baseline (0-20 Hz)", 0, 20, "Remove - baseline wander"),
            ("Low EMG (20-50 Hz)", 20, 50, "Keep - EMG content"),
            ("Mid EMG (50-150 Hz)", 50, 150, "Keep - Primary EMG"),
            ("High EMG (150-400 Hz)", 150, 400, "Keep - Secondary EMG"),
            ("Noise (400-500 Hz)", 400, 500, "Remove - high frequency noise"),
        ]
        
        for band_name, freq_low, freq_high, action in bands:
            mask = (self.frequencies >= freq_low) & (self.frequencies < freq_high)
            band_power = np.sum(self.psd[mask])
            percent = (band_power / np.sum(self.psd)) * 100
            print(f"  {band_name:25s}: {percent:6.2f}% power - {action}")
        
        # Recommendations
        print("\nFilter Parameter Recommendations:")
        print("-" * 70)
        
        # Find where 90% of energy is
        sorted_indices = np.argsort(self.psd)[::-1]
        cumsum = np.cumsum(self.psd[sorted_indices])
        cumsum_norm = cumsum / cumsum[-1]
        idx_90 = sorted_indices[np.where(cumsum_norm >= 0.9)[0][-1]]
        freq_90 = self.frequencies[idx_90]
        
        print(f"\n1. BANDPASS FILTER:")
        print(f"   - Low cutoff: 20 Hz (remove DC)")
        print(f"   - High cutoff: {int(freq_90 + 50)} Hz (contains 90% of signal)")
        print(f"   - Recommended: bandpass(20-{int(freq_90 + 50)}, order=2)")
        
        print(f"\n2. NOTCH FILTER:")
        if peak_freqs[0] > 48 and peak_freqs[0] < 52:
            print(f"   - Strong 50 Hz peak detected: YES")
            print(f"   - Recommended: notch(50, Q=30)")
        else:
            print(f"   - 50 Hz peak detected: NO")
            print(f"   - Notch filter: Optional")
        
        print(f"\n3. MOVING AVERAGE WINDOW:")
        print(f"   - Based on muscle activation rate: 100-300 ms")
        print(f"   - Recommended: 200 ms window (0.2 seconds)")
        
        print("\n" + "="*70)


def main():
    parser = argparse.ArgumentParser(
        description='Analyze frequency content of EMG CSV files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python frequency_analyzer.py --file data.csv
  python frequency_analyzer.py --folder ./data
  python frequency_analyzer.py --file emg_data.csv --save freq_analysis.png
        '''
    )
    
    parser.add_argument('--file', default=None,
                       help='Path to single CSV file')
    parser.add_argument('--folder', default='.',
                       help='Folder containing CSV files (default: current folder)')
    parser.add_argument('--save', default=None,
                       help='Save plot to file')
    
    args = parser.parse_args()
    
    # Find CSV files
    if args.file:
        csv_files = [args.file]
    else:
        folder = Path(args.folder)
        csv_files = list(folder.glob('*.csv'))
        if not csv_files:
            print(f"No CSV files found in {folder}")
            return
    
    # Process each file
    for csv_file in csv_files:
        print("\n" + "="*70)
        print(f"Processing: {csv_file}")
        print("="*70)
        
        analyzer = FrequencyAnalyzer(sampling_rate=1000)
        analyzer.load_csv(str(csv_file))
        analyzer.compute_fft()
        analyzer.print_analysis()
        
        # Generate plot
        save_path = args.save if args.save else str(csv_file).replace('.csv', '_frequency_analysis.png')
        analyzer.plot_frequency_response(save_path=save_path)


if __name__ == "__main__":
    main()
