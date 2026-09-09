"""Generated-seed invariants independent of fixed demonstration recordings."""

from hypothesis import given, settings
from hypothesis import strategies as st
from signal_slate.domain.models import RunConfig, ShotContext
from signal_slate.simulator.engine import SimulatorEngine


@settings(max_examples=40, deadline=None)
@given(
    seed=st.integers(min_value=0, max_value=2**32 - 1),
    family=st.sampled_from(["channel_interference", "antenna_shadow", "audio_clipping", "healthy"]),
)
def test_exact_grid_and_determinism_for_generated_realizations(seed, family):
    engine = SimulatorEngine(ShotContext(), fault_family=family)
    first = engine.run_rehearsal(RunConfig(), seed=seed, start_time_sec=1000)
    second = engine.run_rehearsal(RunConfig(), seed=seed, start_time_sec=1000)
    assert first == second
    samples, metrics, _ = first
    assert {(s.mic_id, s.offset_ms) for s in samples} == {
        (f"mic_{mic}", offset) for mic in range(1, 5) for offset in range(0, 12001, 100)
    }
    assert len(samples) == 484
    assert len(metrics) == 48


@settings(max_examples=30, deadline=None)
@given(
    seed=st.integers(min_value=0, max_value=2**32 - 1),
    family=st.sampled_from(["channel_interference", "antenna_shadow", "audio_clipping"]),
)
def test_backup_routing_never_changes_receiver_physics(seed, family):
    engine = SimulatorEngine(ShotContext(), fault_family=family)
    original = engine.run_rehearsal(RunConfig(), seed=seed)[0]
    backup = engine.run_rehearsal(RunConfig(backup_sources={"mic_1": "mic_4"}), seed=seed)[0]
    fields = [
        "mic_id",
        "offset_ms",
        "quality",
        "link_margin_db",
        "battery_pct",
        "is_dropout",
        "is_clipped",
    ]
    assert [[getattr(s, f) for f in fields] for s in original] == [
        [getattr(s, f) for f in fields] for s in backup
    ]


@settings(max_examples=30, deadline=None)
@given(seed=st.integers(min_value=0, max_value=2**32 - 1), channel=st.sampled_from([11, 12]))
def test_channel_changes_cannot_remove_audio_clipping(seed, channel):
    engine = SimulatorEngine(ShotContext(), fault_family="audio_clipping")
    config = RunConfig()
    config.channel_assignments["mic_1"] = channel
    before = engine.run_rehearsal(RunConfig(), seed=seed)[0]
    after = engine.run_rehearsal(config, seed=seed)[0]
    assert [s.is_clipped for s in before] == [s.is_clipped for s in after]
    assert any(s.is_clipped for s in after)
