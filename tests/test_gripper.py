from emgdemo.config import GripperConfig
from emgdemo.domain.gripper import Gripper


def _drive(gripper, close, open_, steps):
    for _ in range(steps):
        gripper.step(close, open_)
    return gripper.state()


def test_starts_open_with_no_force():
    assert Gripper(GripperConfig()).state().force_n == 0.0
    assert Gripper(GripperConfig()).state().label == "OPEN"


def test_closing_side_builds_grip_force():
    state = _drive(Gripper(GripperConfig()), close=1.0, open_=0.0, steps=200)
    assert state.force_n > 50.0


def test_opening_side_from_rest_cannot_drive_force_negative():
    state = _drive(Gripper(GripperConfig()), close=0.0, open_=1.0, steps=200)
    assert state.force_n == 0.0


def test_opening_side_releases_an_existing_grip():
    gripper = Gripper(GripperConfig())
    _drive(gripper, close=1.0, open_=0.0, steps=200)
    gripped = gripper.state().force_n
    released = _drive(gripper, close=0.0, open_=1.0, steps=200).force_n
    assert released < gripped


def test_equal_sides_hold_position():
    gripper = Gripper(GripperConfig())
    _drive(gripper, close=1.0, open_=0.0, steps=200)
    held = gripper.state().force_n
    after = _drive(gripper, close=0.5, open_=0.5, steps=100).force_n
    assert abs(after - held) < 1.0


def test_label_reports_grip_strength_bands():
    assert _drive(Gripper(GripperConfig()), 0.0, 0.0, 1).label == "OPEN"
    assert _drive(Gripper(GripperConfig()), 1.0, 0.0, 200).label == "POWER"


def test_force_is_clamped_to_its_configured_maximum():
    state = _drive(Gripper(GripperConfig()), close=1.0, open_=0.0, steps=5000)
    assert state.force_n <= GripperConfig().max_force_n


def test_fingers_follow_force_and_stay_in_unit_range():
    gripper = Gripper(GripperConfig())
    open_positions = gripper.state().finger_positions
    closed_positions = _drive(gripper, 1.0, 0.0, 500).finger_positions

    assert len(closed_positions) == 5
    assert all(0.0 <= p <= 1.0 for p in closed_positions)
    assert sum(closed_positions) > sum(open_positions)
