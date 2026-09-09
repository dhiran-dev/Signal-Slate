"""Unit tests for Signal Slate deterministic simulator engine."""

from signal_slate.domain.models import RunConfig, ShotContext
from signal_slate.simulator.engine import SimulatorEngine


def test_simulator_generates_exact_484_samples_and_48_metrics():
    context = ShotContext()
    engine = SimulatorEngine(context)
    config = RunConfig(channel_assignments={"mic_1": 10, "mic_2": 20, "mic_3": 30, "mic_4": 40})

    samples, metrics, events = engine.run_rehearsal(config, seed=42)

    # 121 offsets x 4 microphones = 484 samples
    assert len(samples) == 484
    # 12 seconds x 4 microphones = 48 per-second metric summaries
    assert len(metrics) == 48
    # Lifecycle events must include completion marker
    assert any(e.get("event") == "run_completed" and e.get("samples_count") == 484 for e in events)

    # Verify per-mic distribution
    for mic_id in context.mic_ids:
        mic_samples = [s for s in samples if s.mic_id == mic_id]
        assert len(mic_samples) == 121
        mic_metrics = [m for m in metrics if m.mic_id == mic_id]
        assert len(mic_metrics) == 12


def test_channel_10_produces_dropouts_during_critical_interval():
    context = ShotContext()
    engine = SimulatorEngine(context)
    config = RunConfig(channel_assignments={"mic_1": 10})

    samples, _, _ = engine.run_rehearsal(config, seed=42)

    # In critical interval (4200ms - 6800ms), mic_1 on channel 10 has dropouts
    crit_samples = [
        s
        for s in samples
        if s.mic_id == "mic_1"
        and context.critical_line_start_ms <= s.offset_ms <= context.critical_line_end_ms
    ]
    dropouts = [s for s in crit_samples if s.is_dropout]
    assert len(dropouts) > 0
    assert any(s.quality < 30.0 for s in crit_samples)


def test_channel_12_cleans_up_mic_1_interference():
    context = ShotContext()
    engine = SimulatorEngine(context)
    config = RunConfig(channel_assignments={"mic_1": 12})

    samples, _, _ = engine.run_rehearsal(config, seed=42)

    mic1_samples = [s for s in samples if s.mic_id == "mic_1"]
    # Zero dropouts across entire 12 seconds on Channel 12
    assert all(not s.is_dropout for s in mic1_samples)
    assert all(s.quality >= 80.0 for s in mic1_samples)


def test_simulator_is_strictly_deterministic():
    engine = SimulatorEngine()
    config = RunConfig()

    s1, m1, e1 = engine.run_rehearsal(config, seed=123)
    s2, m2, e2 = engine.run_rehearsal(config, seed=123)

    assert [s.model_dump() for s in s1] == [s.model_dump() for s in s2]
    assert [m.model_dump() for m in m1] == [m.model_dump() for m in m2]


def test_simulator_supplied_seed_is_used_and_deterministic():
    engine = SimulatorEngine()
    config = RunConfig()

    s_seed42, _, _ = engine.run_rehearsal(config, seed=42)
    s_seed99, _, _ = engine.run_rehearsal(config, seed=99)

    # Different seeds must produce different simulated values
    assert [s.model_dump() for s in s_seed42] != [s.model_dump() for s in s_seed99]

    # Re-running with seed 42 produces identical results
    s_seed42_again, _, _ = engine.run_rehearsal(config, seed=42)
    assert [s.model_dump() for s in s_seed42] == [s.model_dump() for s in s_seed42_again]


def test_unknown_channel_fails_and_produces_dropouts():
    """R10: Unknown channels must fail, not remain magically healthy."""
    context = ShotContext()
    engine = SimulatorEngine(context)

    # Assign invalid/unknown channels not in available_channels (e.g. 99, 999)
    config = RunConfig(channel_assignments={"mic_1": 99, "mic_2": 999})
    samples, _, _ = engine.run_rehearsal(config, seed=42)

    mic1_samples = [s for s in samples if s.mic_id == "mic_1"]
    mic2_samples = [s for s in samples if s.mic_id == "mic_2"]

    # Unknown channels must fail completely with dropouts and 0 quality
    assert all(s.is_dropout for s in mic1_samples)
    assert all(s.quality == 0.0 for s in mic1_samples)
    assert all(s.is_dropout for s in mic2_samples)
    assert all(s.quality == 0.0 for s in mic2_samples)


def test_shot_context_aligned_to_canonical_assets():
    """R10: ShotContext dialogue and timings aligned to committed audio assets."""
    context = ShotContext()
    assert context.critical_line_start_ms == 4900
    assert context.critical_line_end_ms == 6800
    assert "cut the feed" in context.critical_dialogue_text
    assert context.vulnerable_word == "cut"
    assert context.timing_precision == "approximate"
    assert context.synthetic_disclosure != ""
    assert (
        context.source_audio_hash
        == "d7afbe4395aad34313673f18fae92c90be7fd34e33d072fe882cf3ed24c50c03"
    )


def test_cross_process_identity_across_pythonhashseeds():
    """R10: Cross-process determinism regardless of PYTHONHASHSEED."""
    import subprocess
    import sys

    code = """
import json
from signal_slate.domain.models import RunConfig
from signal_slate.simulator.engine import SimulatorEngine

engine = SimulatorEngine()
config = RunConfig(channel_assignments={"mic_1": 10})
samples, metrics, _ = engine.run_rehearsal(config, seed=42)
print(json.dumps([s.model_dump() for s in samples[:10]]))
"""
    cmd = [sys.executable, "-c", code]

    res1 = subprocess.run(
        cmd, capture_output=True, text=True, env={"PYTHONHASHSEED": "0"}, check=True
    )
    res2 = subprocess.run(
        cmd, capture_output=True, text=True, env={"PYTHONHASHSEED": "42"}, check=True
    )
    res3 = subprocess.run(
        cmd, capture_output=True, text=True, env={"PYTHONHASHSEED": "random"}, check=True
    )

    assert res1.stdout.strip() == res2.stdout.strip()
    assert res1.stdout.strip() == res3.stdout.strip()
