"""Unit tests for SRF Quench Protection, Persistent Rollback Journal, and MPS Latency (Phase 12)."""

from pathlib import Path
import tempfile
import pytest

from helios.interfaces.epics import MockControlInterface
from helios.safety.mps import LatencyBudget, MPSManager
from helios.safety.rollback import PersistentRollbackJournal, RollbackCheckpoint, RollbackController
from helios.safety.srf_protection import SRFCavityLimits, SRFProtectionMonitor


def test_srf_protection_monitor_checks():
    """Verify SRFProtectionMonitor validates quench, multipacting, cryo temp, and reflected power."""
    monitor = SRFProtectionMonitor()

    # 1. Normal safe operation at 8.0 MV/m, 2.05 K, 95% He, low Pref
    res_ok = monitor.validate_srf_state(
        cavity_id="MEBT:CAV:01",
        gradient_mv_m=8.0,
        cryo_temp_k=2.05,
        helium_level_pct=95.0,
        p_fwd_kw=5.0,
        p_refl_kw=0.1,
    )
    assert res_ok.is_valid is True
    assert len(res_ok.errors) == 0

    # 2. Quench gradient violation (> 12.0 MV/m)
    res_quench = monitor.validate_srf_state(
        cavity_id="MEBT:CAV:01",
        gradient_mv_m=13.5,
    )
    assert res_quench.is_valid is False
    assert any("exceeds quench threshold" in e for e in res_quench.errors)

    # 3. Multipacting zone resonance (1.5 - 2.2 MV/m)
    res_mp = monitor.validate_srf_state(
        cavity_id="MEBT:CAV:01",
        gradient_mv_m=1.8,
    )
    assert res_mp.is_valid is False
    assert any("multipacting zone" in e for e in res_mp.errors)

    # 4. Cryo temperature breach (> 2.1 K)
    res_temp = monitor.validate_srf_state(
        cavity_id="MEBT:CAV:01",
        gradient_mv_m=8.0,
        cryo_temp_k=2.25,
    )
    assert res_temp.is_valid is False
    assert any("superfluid limit" in e for e in res_temp.errors)

    # 5. High reflected power ratio trip (Pref/Pfwd > 0.20)
    res_refl = monitor.validate_srf_state(
        cavity_id="MEBT:CAV:01",
        gradient_mv_m=8.0,
        p_fwd_kw=10.0,
        p_refl_kw=3.5,
    )
    assert res_refl.is_valid is False
    assert any("Reflected power ratio" in e for e in res_refl.errors)


def test_mps_latency_budget_and_fast_interlocks():
    """Verify MPS latency modeling and interlock monitoring."""
    mps = MPSManager()

    # Nominal latency budget: total 15 us <= 25 us limit
    budget = LatencyBudget(detection_time_us=3.0, propagation_time_us=4.0, actuation_time_us=8.0)
    assert budget.is_compliant is True
    assert budget.margin_us == 10.0

    res_ok = mps.verify_mps_readiness(budget)
    assert res_ok.is_valid is True

    # Tripped interlock
    mps.set_interlock_status("MPS:FAST:RF_ARC_DETECT", is_tripped=True)
    res_tripped = mps.verify_mps_readiness(budget)
    assert res_tripped.is_valid is False
    assert any("RF_ARC_DETECT" in e for e in res_tripped.errors)

    # Latency violation budget
    slow_budget = LatencyBudget(detection_time_us=10.0, propagation_time_us=10.0, actuation_time_us=15.0)
    assert slow_budget.is_compliant is False
    res_latency = mps.verify_mps_readiness(slow_budget)
    assert res_latency.is_valid is False
    assert any("latency budget exceeded" in e for e in res_latency.errors)


def test_persistent_rollback_journal_and_panic_shutdown():
    """Verify SQLite persistent rollback journal survives restart and panic zeros setpoints."""
    ctrl = MockControlInterface()
    ctrl.set_initial_pv("MEBT:CAV:01:AMP_SET", 5.0)
    ctrl.set_initial_pv("MEBT:DCH:01:I_SET", 2.2)

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "safety_rollback.sqlite"

        # Session 1: Create checkpoint and save to journal
        rc1 = RollbackController(control_interface=ctrl, journal_path=db_path)
        cp_id = rc1.create_checkpoint("golden_orbit", {"MEBT:CAV:01:AMP_SET": 5.0, "MEBT:DCH:01:I_SET": 2.2})
        assert len(rc1.list_checkpoints()) == 1

        # Modify values
        ctrl.put("MEBT:CAV:01:AMP_SET", 9.0)
        ctrl.put("MEBT:DCH:01:I_SET", 8.0)

        # Session 2: Crash restart - new controller reading the same SQLite db
        rc2 = RollbackController(control_interface=ctrl, journal_path=db_path)
        assert len(rc2.list_checkpoints()) == 1
        assert rc2.list_checkpoints()[0].checkpoint_id == cp_id

        # Trigger rollback from reloaded journal
        ok = rc2.trigger_rollback(cp_id)
        assert ok is True
        assert ctrl.get("MEBT:CAV:01:AMP_SET") == 5.0
        assert ctrl.get("MEBT:DCH:01:I_SET") == 2.2

        # Panic shutdown zeros target PVs
        panic_ok = rc2.panic_shutdown()
        assert panic_ok is True
        assert ctrl.get("MEBT:CAV:01:AMP_SET") == 0.0
        assert ctrl.get("MEBT:DCH:01:I_SET") == 0.0
