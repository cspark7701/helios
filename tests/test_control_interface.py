import importlib
from unittest.mock import MagicMock, patch
import pytest

import helios.interfaces.epics as epics_mod
from helios.interfaces.base import (
    ControlInterfaceError,
    ReadbackTimeoutError,
    SlewRateLimiter,
)
from helios.interfaces.epics import (
    EPICSInterface,
    MockControlInterface,
)


def test_slew_rate_limiter_trajectory():
    """Verify intermediate setpoints respect max slew rate."""
    # current=0.0, target=10.0, max_slew_rate=5.0 A/s, dt=0.1s -> max_step=0.5A -> 20 steps
    traj = SlewRateLimiter.calculate_trajectory(
        current_val=0.0,
        target_val=10.0,
        max_slew_rate=5.0,
        step_interval_s=0.1,
    )
    assert len(traj) == 20
    assert traj[-1] == 10.0
    assert traj[0] == 0.5
    # Verify no adjacent step exceeds max step
    for i in range(len(traj) - 1):
        assert abs(traj[i+1] - traj[i]) <= 0.500001


def test_slew_rate_limiter_no_change():
    """Verify trajectory when current == target."""
    traj = SlewRateLimiter.calculate_trajectory(5.0, 5.0, 2.0)
    assert traj == [5.0]


def test_mock_control_interface_basic():
    """Verify MockControlInterface get, put, batch, and auto-readback mapping."""
    ctrl = MockControlInterface(response_lag_s=0.0)

    # Set and get
    ctrl.put("MEBT:PSC:QD01:CurrentSet", 12.5)
    assert ctrl.get("MEBT:PSC:QD01:CurrentSet") == 12.5
    # Automatic readback update
    assert ctrl.get("MEBT:PSC:QD01:CurrentAct") == 12.5

    # Test SP -> RB mapping, response lag, and readback noise
    noisy_ctrl = MockControlInterface(readback_noise_std=0.05, response_lag_s=0.001)
    noisy_ctrl.put("CAV:PHASE:SP", -15.0, wait=True)
    assert abs(noisy_ctrl.get("CAV:PHASE:SP") - (-15.0)) < 1.0
    assert noisy_ctrl.get("CAV:PHASE:RB") is not None
    assert noisy_ctrl.get("NONEXISTENT") is None

    # Batch read / write
    ctrl.put_many({
        "MEBT:PSC:CH01:CurrentSet": 1.2,
        "MEBT:PSC:CV01:CurrentSet": -0.8,
    })
    batch_vals = ctrl.get_many(["MEBT:PSC:CH01:CurrentSet", "MEBT:PSC:CV01:CurrentSet"])
    assert batch_vals["MEBT:PSC:CH01:CurrentSet"] == 1.2
    assert batch_vals["MEBT:PSC:CV01:CurrentSet"] == -0.8


def test_mock_control_subscription():
    """Verify value change notifications to subscribers."""
    ctrl = MockControlInterface(response_lag_s=0.0)
    events = []

    def callback(pv, val):
        events.append((pv, val))

    def failing_callback(pv, val):
        raise RuntimeError("Callback failed")

    ctrl.subscribe("MEBT:DIAG:BPM01:X", callback)
    ctrl.subscribe("MEBT:DIAG:BPM01:X", failing_callback)
    ctrl.put("MEBT:DIAG:BPM01:X", 0.45)
    ctrl.put("MEBT:DIAG:BPM01:X", 0.12)

    assert len(events) == 2
    assert events[0] == ("MEBT:DIAG:BPM01:X", 0.45)
    assert events[1] == ("MEBT:DIAG:BPM01:X", 0.12)

    # Unsubscribe
    ctrl.unsubscribe("MEBT:DIAG:BPM01:X")
    ctrl.unsubscribe("NONEXISTENT_PV")



def test_put_with_readback_success():
    """Verify put_with_readback converges successfully with slew-rate limiting."""
    ctrl = MockControlInterface(response_lag_s=0.0)
    ctrl.set_initial_pv("MEBT:PSC:QD01:CurrentSet", 0.0)
    ctrl.set_initial_pv("MEBT:PSC:QD01:CurrentAct", 0.0)

    success = ctrl.put_with_readback(
        setpoint_pv="MEBT:PSC:QD01:CurrentSet",
        readback_pv="MEBT:PSC:QD01:CurrentAct",
        target_val=8.0,
        tolerance=0.05,
        timeout=2.0,
        max_slew_rate=20.0,
    )
    assert success is True
    assert ctrl.get("MEBT:PSC:QD01:CurrentAct") == 8.0


def test_put_with_readback_timeout():
    """Verify ReadbackTimeoutError raised if readback fails to converge."""
    ctrl = MockControlInterface(response_lag_s=0.0)
    # Put to a custom PV that does not auto-update readback
    ctrl.set_initial_pv("CUSTOM:SET", 0.0)
    ctrl.set_initial_pv("CUSTOM:ACT", 0.0)

    with pytest.raises(ReadbackTimeoutError):
        ctrl.put_with_readback(
            setpoint_pv="CUSTOM:SET",
            readback_pv="CUSTOM:ACT",
            target_val=15.0,
            tolerance=0.01,
            timeout=0.2,
            poll_interval=0.05,
        )


def test_epics_interface_missing_pyepics_handling():
    """Verify EPICSInterface handles environment where pyepics is absent gracefully."""
    with patch.dict("sys.modules", {"epics": None}):
        importlib.reload(epics_mod)
        epics_driver = epics_mod.EPICSInterface()
        assert epics_driver._has_epics is False
        with pytest.raises(ControlInterfaceError):
            epics_driver.get("SOME:PV")
        with pytest.raises(ControlInterfaceError):
            epics_driver.put("SOME:PV", 1.0)
        with pytest.raises(ControlInterfaceError):
            epics_driver.get_many(["SOME:PV"])
        with pytest.raises(ControlInterfaceError):
            epics_driver.subscribe("SOME:PV", lambda pv, val: None)


def test_epics_interface_mocked_live():
    """Verify EPICSInterface with live mocked pyepics."""
    mock_epics = MagicMock()
    mock_epics.caget.return_value = 42.0
    mock_epics.caput.return_value = 1
    mock_epics.caget_many.return_value = [10.0, 20.0]
    mock_pv_instance = MagicMock()
    mock_epics.PV.return_value = mock_pv_instance

    with patch.dict("sys.modules", {"epics": mock_epics}):
        importlib.reload(epics_mod)
        epics_live = epics_mod.EPICSInterface()
        assert epics_live._has_epics is True
        assert epics_live.get("SOME:PV") == 42.0
        assert epics_live.put("SOME:PV", 10.0) is True
        mock_epics.caput.return_value = 0
        assert epics_live.put("SOME:PV", 10.0) is False
        assert epics_live.get_many(["PV1", "PV2"]) == {"PV1": 10.0, "PV2": 20.0}

        cbs = []
        epics_live.subscribe("SOME:PV", lambda pv, val: cbs.append(val))
        handler = mock_epics.PV.call_args[1]["callback"]
        handler(pvname="SOME:PV", value=123)
        assert cbs == [123]

        epics_live.unsubscribe("SOME:PV")
        epics_live.unsubscribe("NONEXISTENT")

    importlib.reload(epics_mod)

