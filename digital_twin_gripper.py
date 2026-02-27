"""
Digital Twin Gripper Control System
====================================

Visualizes a simulated prosthetic gripper responding to EMG control signals.
Shows grip force, finger position, and real-time muscle activation feedback.

Features:
- Real-time gripper animation
- Finger position tracking
- Force feedback visualization
- EMG envelope overlay
- Control command interpretation
- Multi-panel status display
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Slider
import matplotlib.patheffects as path_effects
from typing import Dict, List, Tuple

# ============================================================================
# DIGITAL TWIN GRIPPER CLASS
# ============================================================================

class DigitalGripper:
    """
    Simulates a prosthetic hand gripper with EMG control.
    
    Features:
    - 5 fingers with position tracking
    - Force control and feedback
    - Stiffness simulation
    - Grip type detection (precision vs. power grip)
    """
    
    def __init__(self):
        """Initialize gripper parameters."""
        # Finger state (0 = open, 1 = closed)
        self.finger_positions = [0.0] * 5  # [Thumb, Index, Middle, Ring, Pinky]
        self.grip_force = 0.0  # 0-100 (normalized)
        self.target_force = 0.0
        
        # Physical parameters
        self.max_force = 100  # Maximum grip force (N)
        self.response_time = 0.05  # Seconds for finger response
        self.current_grip_type = 'OPEN'  # OPEN, LIGHT_GRIP, POWER_GRIP
         
    def update(self, control_signal: float, dt: float = 0.01):
        """
        Update gripper state based on EMG control signal.
        
        Args:
            control_signal: 0-1 normalized EMG envelope value
            dt: Time step (seconds)
        """
        # Low-pass filter for smooth control
        self.target_force = control_signal * self.max_force
        self.grip_force += (self.target_force - self.grip_force) * 0.1
        
        # Determine grip type
        if self.grip_force < 10:
            self.current_grip_type = 'OPEN'
        elif self.grip_force < 40:
            self.current_grip_type = 'LIGHT_GRIP'
        else:
            self.current_grip_type = 'POWER_GRIP'
        
        # Update finger positions (simplified model)
        # Different fingers have different response profiles
        finger_ratios = [0.7, 1.0, 1.0, 0.9, 0.8]  # Thumb slightly slower
        
        for i, ratio in enumerate(finger_ratios):
            target_pos = (self.grip_force / self.max_force) * ratio
            self.finger_positions[i] += (target_pos - self.finger_positions[i]) * 0.15
            self.finger_positions[i] = np.clip(self.finger_positions[i], 0, 1)
    
    def get_state(self) -> Dict:
        """
        Get current gripper state.
        
        Returns:
            Dictionary with all gripper parameters
        """
        return {
            'finger_positions': self.finger_positions,
            'grip_force': self.grip_force,
            'grip_type': self.current_grip_type,
            'is_gripping': self.grip_force > 10
        }


# ============================================================================
# GRIPPER VISUALIZATION
# ============================================================================

class GripperVisualizer:
    """
    Renders 2D visualization of prosthetic gripper.
    """
    
    def __init__(self, ax):
        """
        Initialize visualizer with matplotlib axes.
        
        Args:
            ax: matplotlib Axes object
        """
        self.ax = ax
        self.finger_patches = []
        self.setup_visualization()
        
    def setup_visualization(self):
        """Configure initial visualization elements."""
        self.ax.set_xlim(-2, 6)
        self.ax.set_ylim(-1, 5)
        self.ax.set_aspect('equal')
        self.ax.axis('off')
        
        # Title with bold styling
        title = self.ax.text(2, 4.8, 'Prosthetic Gripper Control', 
                            ha='center', fontsize=14, fontweight='bold')
        title.set_path_effects([path_effects.Stroke(linewidth=2, 
                                                      foreground='white'),
                               path_effects.Normal()])
        
        # Draw palm (base of gripper)
        palm = patches.Rectangle((0.5, 0.5), 3, 2, 
                                 linewidth=2, edgecolor='black', 
                                 facecolor='#cccccc')
        self.ax.add_patch(palm)
        self.ax.text(2, 1.5, 'PALM', ha='center', va='center', 
                    fontweight='bold', fontsize=10)
        
        # Initialize finger rectangles
        finger_names = ['THUMB', 'INDEX', 'MIDDLE', 'RING', 'PINKY']
        positions_x = [0.2, 1.2, 2.2, 3.2, 4.2]
        
        for i, (name, x) in enumerate(zip(finger_names, positions_x)):
            # Finger rectangle (will be updated)
            finger_rect = patches.Rectangle((x, 0), 0.7, 0.5,
                                           linewidth=2, edgecolor='#333333',
                                           facecolor='#ff9999')
            self.ax.add_patch(finger_rect)
            self.finger_patches.append({
                'rect': finger_rect,
                'name': name,
                'x_base': x
            })
            
            # Finger label
            self.ax.text(x + 0.35, -0.4, name, ha='center', fontsize=8)
    
    def update(self, gripper_state: Dict):
        """
        Update gripper visualization based on state.
        
        Args:
            gripper_state: Dictionary from DigitalGripper.get_state()
        """
        positions = gripper_state['finger_positions']
        
        # Update each finger
        for i, finger_data in enumerate(self.finger_patches):
            # Closed position reaches toward palm
            y_pos = positions[i] * 2.5  # Fingers move toward base
            height = 0.5 - positions[i] * 0.2  # Slightly compress when closed
            
            finger_data['rect'].set_y(y_pos)
            finger_data['rect'].set_height(height)
            
            # Color based on flexion
            color_intensity = positions[i]
            color = (1.0, 1.0 - color_intensity * 0.5, 1.0 - color_intensity * 0.5)
            finger_data['rect'].set_facecolor(color)


# ============================================================================
# COMPLETE VISUALIZATION DASHBOARD
# ============================================================================

def visualize_gripper_control(time: np.ndarray, 
                              envelope: np.ndarray,
                              control_commands: List[Dict] = None,
                              save_path: str = None):
    """
    Create comprehensive visualization combining EMG and gripper control.
    
    Creates figure with:
    - EMG envelope with peaks
    - Gripper position animation
    - Control command text
    - Force feedback
    
    Args:
        time: Time vector (seconds)
        envelope: EMG envelope signal
        control_commands: List of detected control commands
        save_path: Optional path to save static image
    """
    
    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(3, 2, hspace=0.35, wspace=0.3)
    
    # Create axes
    ax_emg = fig.add_subplot(gs[0, :])
    ax_gripper = fig.add_subplot(gs[1:, 0])
    ax_info = fig.add_subplot(gs[1:, 1])
    
    # ======== EMG Signal Plot ========
    ax_emg.plot(time, envelope, color='#1f77b4', linewidth=1.5, label='EMG Envelope')
    
    # Mark detected peaks
    if control_commands:
        peak_times = [cmd['time_sec'] for cmd in control_commands]
        peak_amps = [cmd['amplitude'] for cmd in control_commands]
        ax_emg.scatter(peak_times, peak_amps, color='red', s=100, 
                      marker='^', label='Detected Peaks', zorder=5)
    
    # Threshold line
    threshold = np.max(envelope) * 0.2
    ax_emg.axhline(y=threshold, color='red', linestyle='--', 
                   alpha=0.3, label='Activation Threshold')
    
    ax_emg.set_ylabel('Muscle Activation (V)', fontweight='bold', fontsize=11)
    ax_emg.set_title('Real-time EMG Envelope & Control Interpretation', 
                    fontweight='bold', fontsize=12)
    ax_emg.grid(True, alpha=0.3)
    ax_emg.legend(loc='upper right')
    ax_emg.set_xlim(0, time[-1])
    
    # ======== Gripper Visualization ========
    gripper_viz = GripperVisualizer(ax_gripper)
    gripper = DigitalGripper()
    
    # Update gripper to final state
    final_control = envelope[-1] / np.max(envelope)
    gripper.update(final_control)
    gripper_viz.update(gripper.get_state())
    
    # ======== Information Panel ========
    ax_info.axis('off')
    
    # Title
    title_text = ax_info.text(0.5, 0.95, 'Control Status', 
                             ha='center', fontsize=13, fontweight='bold',
                             transform=ax_info.transAxes)
    title_text.set_path_effects([path_effects.Stroke(linewidth=2, 
                                                       foreground='white'),
                                path_effects.Normal()])
    
    # Gripper state
    y_pos = 0.85
    gripper_state = gripper.get_state()
    
    ax_info.text(0.05, y_pos, 'Grip Type:', fontsize=11, fontweight='bold',
                transform=ax_info.transAxes)
    ax_info.text(0.5, y_pos, gripper_state['grip_type'], fontsize=11,
                color='red' if gripper_state['grip_type'] == 'POWER_GRIP' else 'green',
                fontweight='bold', transform=ax_info.transAxes)
    
    # Grip force
    y_pos -= 0.15
    ax_info.text(0.05, y_pos, 'Grip Force:', fontsize=11, fontweight='bold',
                transform=ax_info.transAxes)
    force_pct = (gripper_state['grip_force'] / 100) * 100
    ax_info.text(0.5, y_pos, f'{force_pct:.1f}%', fontsize=11,
                fontweight='bold', transform=ax_info.transAxes)
    
    # Force bar
    force_bar = patches.Rectangle((0.05, y_pos - 0.08), 0.9 * force_pct/100, 0.05,
                                 facecolor='#ff6b6b', edgecolor='black',
                                 transform=ax_info.transAxes)
    ax_info.add_patch(force_bar)
    
    # Finger flexion
    y_pos -= 0.2
    ax_info.text(0.05, y_pos, 'Finger Positions:', fontsize=11, fontweight='bold',
                transform=ax_info.transAxes)
    
    finger_names_short = ['T', 'I', 'M', 'R', 'P']
    for j, (name, pos) in enumerate(zip(finger_names_short, gripper_state['finger_positions'])):
        y_sub = y_pos - 0.12 - j * 0.08
        ax_info.text(0.08, y_sub, f'{name}:', fontsize=10, 
                    transform=ax_info.transAxes, fontweight='bold')
        
        # Position bar
        bar = patches.Rectangle((0.2, y_sub - 0.02), 0.6 * pos, 0.05,
                               facecolor='#4ecdc4', edgecolor='black',
                               transform=ax_info.transAxes)
        ax_info.add_patch(bar)
        
        ax_info.text(0.85, y_sub, f'{pos:.0%}', fontsize=9,
                    transform=ax_info.transAxes)
    
    # Statistics
    y_pos = 0.15
    ax_info.text(0.05, y_pos, 'Statistics:', fontsize=11, fontweight='bold',
                transform=ax_info.transAxes)
    
    ax_info.text(0.08, y_pos - 0.08, f'Max Envelope: {np.max(envelope):.3f} V',
                fontsize=9, transform=ax_info.transAxes, family='monospace')
    ax_info.text(0.08, y_pos - 0.14, f'Mean RMS: {np.sqrt(np.mean(envelope**2)):.3f} V',
                fontsize=9, transform=ax_info.transAxes, family='monospace')
    
    if control_commands:
        ax_info.text(0.08, y_pos - 0.20, f'Control Commands: {len(control_commands)}',
                    fontsize=9, transform=ax_info.transAxes, family='monospace')
    
    plt.suptitle('EMG-Driven Prosthetic Gripper Control Demonstration', 
                fontsize=14, fontweight='bold', y=0.98)
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Gripper visualization saved to {save_path}")
    
    plt.show()


def create_animated_gripper(time: np.ndarray, 
                           envelope: np.ndarray,
                           output_video: str = None):
    """
    Create animated gripper control showing real-time response to EMG.
    
    Args:
        time: Time vector (seconds)
        envelope: EMG envelope signal
        output_video: Optional path to save as video file
    """
    
    fig = plt.figure(figsize=(12, 8))
    gs = fig.add_gridspec(2, 1, height_ratios=[1, 2], hspace=0.3)
    
    ax_emg = fig.add_subplot(gs[0])
    ax_gripper = fig.add_subplot(gs[1])
    
    # Setup EMG plot
    ax_emg.plot(time, envelope, color='#1f77b4', linewidth=1, alpha=0.5, label='Full EMG')
    ax_emg.set_ylabel('Activation (V)', fontweight='bold')
    ax_emg.set_title('Real-time EMG Envelope Processing', fontweight='bold')
    ax_emg.grid(True, alpha=0.2)
    ax_emg.set_xlim(0, time[-1])
    
    # Current signal line
    current_line, = ax_emg.plot([], [], 'r-', linewidth=2, label='Current')
    ax_emg.legend()
    
    # Setup gripper visualization
    gripper_viz = GripperVisualizer(ax_gripper)
    gripper = DigitalGripper()
    
    # Animation update function
    def update_frame(frame_idx):
        # Update EMG line
        if frame_idx > 0:
            current_line.set_data(time[:frame_idx], envelope[:frame_idx])
        
        # Update gripper state
        control_signal = envelope[frame_idx] / np.max(envelope)
        gripper.update(control_signal)
        gripper_viz.update(gripper.get_state())
        
        # Update title with time
        ax_gripper.set_title(f'Gripper State @ t={time[frame_idx]:.2f}s | '
                            f'Grip: {gripper.get_state()["grip_type"]}',
                            fontweight='bold')
        
        return current_line,
    
    # Create animation (sample every 10th frame to make it playable)
    anim = FuncAnimation(fig, update_frame, frames=range(0, len(envelope), 10),
                        blit=False, interval=50, repeat=True)
    
    if output_video:
        try:
            anim.save(output_video, writer='ffmpeg', fps=20)
            print(f"Animation saved to {output_video}")
        except Exception as e:
            print(f"Could not save video: {e}")
            print("Install ffmpeg to save animations")
    
    plt.show()


if __name__ == "__main__":
    # Example usage
    print("Digital Twin Gripper Visualization Module")
    print("This module provides real-time gripper visualization for EMG control")
    
    # Generate example data
    duration = 5
    fs = 1000
    t = np.linspace(0, duration, duration * fs)
    
    # Synthetic EMG envelope
    envelope = 0.5 * (1 + np.sin(2*np.pi*0.5*t)) * (1 + 0.3*np.sin(2*np.pi*2*t))
    envelope = envelope / np.max(envelope) * 1.0
    
    # Example control commands
    control_commands = [
        {'time_sec': 1.0, 'amplitude': 0.8, 'command': 'POWER_GRIP', 'confidence': 0.9},
        {'time_sec': 2.5, 'amplitude': 0.6, 'command': 'LIGHT_GRIP', 'confidence': 0.7},
    ]
    
    # Create visualizations
    visualize_gripper_control(t, envelope, control_commands)
    # create_animated_gripper(t, envelope)  # Uncomment to generate animation
