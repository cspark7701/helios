"""Unit tests for EPICS pvAccess, Archiver Appliance, and CAS Security (Phase 10)."""

from datetime import datetime, timezone
import numpy as np
import pytest

from helios.interfaces.archiver import ArchiverApplianceClient
from helios.interfaces.pva import PVAccessInterface
from helios.interfaces.security import (
    ControlSecurityManager,
    ControlSecurityPolicy,
    SecurityViolationError,
    UserRole,
)


def test_control_security_roles_and_boundaries():
    """Verify Channel Access Security policy and role permissions."""
    policy = ControlSecurityPolicy()
    mgr = ControlSecurityManager(policy=policy)

    # By default, session is PHYSICIST
    assert mgr.current_role == UserRole.PHYSICIST

    # Physicist can write to Quadrupoles and Steerers
    mgr.check_permission("MEBT:QUAD:01:B_SET")
    mgr.check_permission("MEBT:DCH:01:I_SET")

    # Read-only PVs (interlocks, readbacks) require ADMIN
    with pytest.raises(SecurityViolationError):
        mgr.check_permission("MEBT:MPS:INTERLOCK:STATUS")

    # Demote to OPERATOR
    mgr.set_session_role(UserRole.OPERATOR)
    # Operator can write to steerers
    mgr.check_permission("MEBT:DCH:01:I_SET")
    # Operator cannot write to RF cavity phase/amplitude
    with pytest.raises(SecurityViolationError):
        mgr.check_permission("MEBT:CAV:01:PHASE_SET")

    # Demote to READ_ONLY
    mgr.set_session_role(UserRole.READ_ONLY)
    with pytest.raises(SecurityViolationError):
        mgr.check_permission("MEBT:DCH:01:I_SET")

    # Elevate to ADMIN
    mgr.set_session_role(UserRole.ADMIN)
    mgr.check_permission("MEBT:MPS:INTERLOCK:STATUS")
    mgr.check_permission("MEBT:CAV:01:PHASE_SET")


def test_pvaccess_interface_mock_and_normative_types():
    """Verify PVAccessInterface reads and writes scalars, NTTables, and NTNDArrays."""
    mgr = ControlSecurityManager()
    mgr.set_session_role(UserRole.ADMIN)
    pva = PVAccessInterface(security_manager=mgr, use_mock=True)

    # 1. Scalar put & get
    pva.put("MEBT:DCH:01:I_SET", 2.5)
    assert pva.get("MEBT:DCH:01:I_SET") == 2.5

    # 2. NTTable put & get (multi-BPM orbit table)
    orbit_table = {
        "bpm_id": ["BPM01", "BPM02", "BPM03"],
        "s_pos": [0.5, 1.8, 3.2],
        "x_mm": [0.12, -0.05, 0.22],
        "y_mm": [-0.08, 0.15, -0.02],
    }
    pva.put_nt_table("MEBT:DIAG:ORBIT_TABLE", orbit_table)
    retrieved_table = pva.get_nt_table("MEBT:DIAG:ORBIT_TABLE")
    assert retrieved_table["bpm_id"] == ["BPM01", "BPM02", "BPM03"]
    assert len(retrieved_table["x_mm"]) == 3

    # 3. NTNDArray put & get (camera matrix)
    cam_img = np.ones((64, 64), dtype=np.float32) * 42.0
    pva.put_nt_ndarray("MEBT:CAM:01:IMAGE", cam_img)
    retrieved_img = pva.get_nt_ndarray("MEBT:CAM:01:IMAGE")
    assert retrieved_img.shape == (64, 64)
    assert retrieved_img[0, 0] == 42.0

    # 4. Security violation during PVA put
    mgr.set_session_role(UserRole.READ_ONLY)
    with pytest.raises(SecurityViolationError):
        pva.put("MEBT:DCH:01:I_SET", 5.0)


def test_pvaccess_subscription_monitor():
    """Verify PVAccessInterface monitor subscriptions."""
    pva = PVAccessInterface(use_mock=True)
    events = []

    def on_change(pv: str, val: float):
        events.append((pv, val))

    pva.subscribe("MEBT:BPM:01:X", on_change)
    pva.put("MEBT:BPM:01:X", 0.45)
    pva.put("MEBT:BPM:01:X", 0.60)

    assert len(events) == 2
    assert events[0] == ("MEBT:BPM:01:X", 0.45)
    assert events[1] == ("MEBT:BPM:01:X", 0.60)

    pva.unsubscribe("MEBT:BPM:01:X")
    pva.put("MEBT:BPM:01:X", 0.75)
    assert len(events) == 2


def test_pvaccess_live_failure_raises_and_never_falls_back_to_mock():
    """R-01 regression: Live PVA put/get failure must raise ControlInterfaceError and never write to mock store."""
    from unittest.mock import MagicMock
    from helios.interfaces.base import ControlInterfaceError

    pva = PVAccessInterface(use_mock=True)
    pva.use_mock = False
    mock_ctxt = MagicMock()
    mock_ctxt.put.side_effect = RuntimeError("Channel Access link timeout")
    mock_ctxt.get.side_effect = RuntimeError("Channel Access disconnected")
    pva.pva_ctxt = mock_ctxt

    with pytest.raises(ControlInterfaceError) as exc_put:
        pva.put("MEBT:DCH:01:I_SET", 12.5)
    assert "PVA put failed" in str(exc_put.value)
    # Ensure mock store did NOT get populated
    assert pva._store is not None
    assert pva._store.get("MEBT:DCH:01:I_SET") is None

    with pytest.raises(ControlInterfaceError) as exc_get:
        pva.get("MEBT:DCH:01:I_SET")
    assert "PVA get failed" in str(exc_get.value)


def test_archiver_appliance_client():
    """Verify ArchiverApplianceClient historical queries and baseline calculations."""
    client = ArchiverApplianceClient(mock_mode=True)
    t_ref = datetime(2026, 10, 13, 10, 0, 0, tzinfo=timezone.utc)
    t_start = datetime(2026, 10, 13, 9, 30, 0, tzinfo=timezone.utc)
    t_end = datetime(2026, 10, 13, 10, 30, 0, tzinfo=timezone.utc)

    # 1. Query time series
    data = client.get_data("MEBT:BPM:01:X", t_start, t_end)
    assert len(data) > 0
    assert "val" in data[0]
    assert "secs" in data[0]

    # 2. Golden baseline extraction
    pvs = ["MEBT:BPM:01:X", "MEBT:BPM:02:X", "MEBT:QUAD:01:B_SET"]
    baseline = client.get_golden_baseline(pvs, t_ref)
    assert len(baseline) == 3
    assert all(isinstance(v, float) for v in baseline.values())

    # 3. Compute statistics and drift rate
    stats = client.compute_pv_statistics("MEBT:BPM:01:X", t_start, t_end)
    assert stats["count"] > 0
    assert "mean" in stats
    assert "std" in stats
    assert "drift_per_min" in stats
