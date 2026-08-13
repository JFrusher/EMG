"""The failover state machine, ported with its silence removed."""

from emgdemo.config import ResilienceConfig
from emgdemo.resilience import Action, SourceSupervisor


def _config(**overrides):
    defaults = dict(stall_timeout_s=2.0, restart_cooldown_s=5.0, max_restarts=3)
    defaults.update(overrides)
    return ResilienceConfig(**defaults)


def test_a_healthy_stream_needs_no_intervention():
    supervisor = SourceSupervisor(_config())
    supervisor.observe(samples_seen=10, now=0.0)
    assert supervisor.observe(samples_seen=10, now=1.0) is Action.NONE


def test_silence_past_the_stall_timeout_asks_for_a_restart():
    supervisor = SourceSupervisor(_config())
    supervisor.observe(samples_seen=10, now=0.0)
    assert supervisor.observe(samples_seen=0, now=3.0) is Action.RESTART


def test_cooldown_prevents_a_restart_storm():
    supervisor = SourceSupervisor(_config())
    supervisor.observe(samples_seen=10, now=0.0)
    assert supervisor.observe(samples_seen=0, now=3.0) is Action.RESTART
    assert supervisor.observe(samples_seen=0, now=4.0) is Action.NONE


def test_samples_arriving_again_clears_the_stall():
    supervisor = SourceSupervisor(_config())
    supervisor.observe(samples_seen=10, now=0.0)
    supervisor.observe(samples_seen=0, now=3.0)
    supervisor.observe(samples_seen=10, now=4.0)
    assert supervisor.observe(samples_seen=10, now=20.0) is Action.NONE


def test_exhausting_the_restart_budget_falls_over_to_synthetic():
    supervisor = SourceSupervisor(_config(max_restarts=2))
    supervisor.observe(samples_seen=10, now=0.0)

    assert supervisor.observe(samples_seen=0, now=10.0) is Action.RESTART
    assert supervisor.observe(samples_seen=0, now=20.0) is Action.RESTART
    assert supervisor.observe(samples_seen=0, now=30.0) is Action.FAILOVER


def test_failover_is_final_and_not_repeated():
    supervisor = SourceSupervisor(_config(max_restarts=1))
    supervisor.observe(samples_seen=10, now=0.0)
    supervisor.observe(samples_seen=0, now=10.0)
    assert supervisor.observe(samples_seen=0, now=20.0) is Action.FAILOVER
    assert supervisor.observe(samples_seen=0, now=30.0) is Action.NONE


def test_every_decision_is_recorded_for_the_operator():
    supervisor = SourceSupervisor(_config(max_restarts=1))
    supervisor.observe(samples_seen=10, now=0.0)
    supervisor.observe(samples_seen=0, now=10.0)
    supervisor.observe(samples_seen=0, now=20.0)

    reasons = [entry.reason for entry in supervisor.history]
    assert any("stall" in reason for reason in reasons)
    assert any("failover" in reason for reason in reasons)
