"""Unit tests for Automated Fault Recovery and Self-Healing Linac (Phase 16)."""

import numpy as np
import pytest

from helios.recovery.loss_mitigation import BeamLossMitigator
from helios.recovery.magnet_recovery import MagnetPowerSupplyRecoverer
from helios.recovery.rf_rematch import RFCavityRematcher


def test_rf_cavity_failure_rematching():
    """Verify autonomous local rematching of downstream cavities after an RF trip."""
    rematcher = RFCavityRematcher(max_voltage_boost_factor=1.35)

    tripped = "SCL:CAV:01"
    downstream = ["SCL:CAV:02", "SCL:CAV:03", "SCL:CAV:04"]
    v_active = {"SCL:CAV:02": 1200.0, "SCL:CAV:03": 1200.0, "SCL:CAV:04": 1200.0}
    phi_active = {"SCL:CAV:02": -20.0, "SCL:CAV:03": -20.0, "SCL:CAV:04": -20.0}

    result = rematcher.rematch_downstream_cavities(
        tripped_cavity_id=tripped,
        downstream_cavities=downstream,
        active_voltages_kv=v_active,
        active_phases_deg=phi_active,
        nominal_voltage_tripped_kv=1200.0,
        nominal_phase_tripped_deg=-25.0,
        charge_q=33.0,
    )

    assert result.success
    assert result.energy_recovery_pct >= 90.0
    assert result.residual_energy_error_mev < 0.05
    assert len(result.new_setpoints) == 6  # 3 voltages + 3 phases
    # Check that voltages were boosted to compensate
    assert result.new_setpoints["SCL:CAV:02:VOLT_SET"] > 1200.0


def test_magnet_power_supply_trip_recovery():
    """Verify isolation of tripped magnet and SVD orbit re-steering with remaining steerers."""
    recoverer = MagnetPowerSupplyRecoverer()

    all_steerers = ["MEBT:DCH:01", "MEBT:DCH:02", "MEBT:DCH:03"]
    tripped = "MEBT:DCH:02"

    bpm_readings = {
        "MEBT:BPM:01": 0.35,
        "MEBT:BPM:02": -0.40,
        "MEBT:BPM:03": 0.28,
    }

    res = recoverer.recover_tripped_steerer(
        tripped_pv=tripped,
        all_steerers=all_steerers,
        bpm_readings_mm=bpm_readings,
    )

    assert res.tripped_pv == tripped
    assert tripped not in res.active_compensators
    assert res.corrective_setpoints[tripped] == 0.0
    assert len(res.active_compensators) == 2
    assert res.predicted_residual_rms_mm < 0.5


def test_beam_loss_hotspot_mitigation():
    """Verify BLM radiation spike localization and upstream corrective steering."""
    mitigator = BeamLossMitigator(loss_trip_threshold_w=1.0)

    blms = {
        "MEBT:BLM:01": {"s_m": 1.0, "loss_w": 0.05},
        "MEBT:BLM:02": {"s_m": 2.2, "loss_w": 0.85},  # Hotspot
        "MEBT:BLM:03": {"s_m": 3.5, "loss_w": 0.02},
    }

    steerers = {
        "MEBT:DCH:01": 0.5,
        "MEBT:DCV:01": 0.6,
        "MEBT:DCH:02": 1.8,
        "MEBT:DCV:02": 1.9,
        "MEBT:DCH:03": 3.0,
    }

    active_currents = {
        "MEBT:DCH:01": 0.1,
        "MEBT:DCV:01": -0.2,
        "MEBT:DCH:02": 0.4,
        "MEBT:DCV:02": 0.3,
        "MEBT:DCH:03": 0.0,
    }

    res = mitigator.mitigate_loss_hotspot(
        blm_readings=blms,
        steerer_positions=steerers,
        active_steerer_currents=active_currents,
    )

    assert res.success is True
    assert res.hotspot_blm == "MEBT:BLM:02"
    assert res.hotspot_location_m == 2.2
    assert res.measured_loss_w == 0.85
    # Should select upstream steerers closest to 2.2 m (i.e. DCH:02, DCV:02)
    assert "MEBT:DCH:02" in res.upstream_steerers or "MEBT:DCV:02" in res.upstream_steerers
    assert len(res.applied_correction_a) > 0
