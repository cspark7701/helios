"""Unit tests achieving 100% test coverage for helios/interfaces and helios/diagnostics."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from helios.core.schemas import TelemetrySnapshot
from helios.diagnostics.anomaly import LinacAnomalyDetector
from helios.diagnostics.archiver import TelemetryArchiver
from helios.diagnostics.survey import (
    GirderMoverAdjustment,
    LaserTrackerSurveyAnalyzer,
    MagnetFiducialMeasurement,
)
from helios.diagnostics.telemetry import TelemetryProcessor
from helios.interfaces.archiver import ArchiverApplianceClient
from helios.interfaces.base import (
    ControlInterfaceError,
    InMemoryPVStore,
    MissingReadbackError,
    ReadbackTimeoutError,
    SlewRateLimiter,
)
from helios.interfaces.channel_map import (
    ChannelLimits,
    ChannelManager,
    DeviceType,
    LinacDevice,
    create_baseline_mebt_channel_manager,
)
from helios.interfaces.epics import EPICSInterface, MockControlInterface
from helios.interfaces.pva import PVAccessInterface
from helios.interfaces.security import (
    ControlSecurityManager,
    ControlSecurityPolicy,
    SecurityViolationError,
    UserRole,
)


# ==============================================================================
# 1. Base Interfaces & Slew Rate Limiter Coverage
# ==============================================================================

def test_slew_rate_limiter_and_inmemory_pvstore():
    # SlewRateLimiter branches
    # max_slew_rate <= 0
    assert SlewRateLimiter.calculate_trajectory(10.0, 20.0, max_slew_rate=0.0) == [20.0]
    # delta near zero
    assert SlewRateLimiter.calculate_trajectory(10.0, 10.00000001, max_slew_rate=5.0) == [10.00000001]
    # num_steps <= 1
    assert SlewRateLimiter.calculate_trajectory(10.0, 10.5, max_slew_rate=5.0, step_interval_s=0.2) == [10.5]
    # multi-step ramping positive delta
    traj_pos = SlewRateLimiter.calculate_trajectory(0.0, 10.0, max_slew_rate=2.0, step_interval_s=1.0)
    assert len(traj_pos) > 1
    assert traj_pos[-1] == 10.0
    # multi-step ramping negative delta
    traj_neg = SlewRateLimiter.calculate_trajectory(10.0, 0.0, max_slew_rate=2.0, step_interval_s=1.0)
    assert len(traj_neg) > 1
    assert traj_neg[-1] == 0.0

    # InMemoryPVStore
    store = InMemoryPVStore({"TEST:PV1": 1.0})
    assert store.get("TEST:PV1") == 1.0
    assert store.get("NONEXISTENT") is None

    store.set("TEST:PV2", 2.0)
    assert store.get("TEST:PV2") == 2.0

    # Subscribers and error handling in callback
    received = []
    store.subscribe("TEST:PV1", lambda name, val: received.append((name, val)))

    def failing_cb(name, val):
        raise RuntimeError("Callback explosion")

    store.subscribe("TEST:PV1", failing_cb)
    store.put("TEST:PV1", 5.0)
    assert ("TEST:PV1", 5.0) in received

    # Unsubscribe and clear
    store.unsubscribe("TEST:PV1")
    store.clear()
    assert store.get("TEST:PV2") is None


def test_base_control_interface_methods():
    mock = MockControlInterface()

    # get_many & put_many
    mock.put_many({"PV:A": 1.0, "PV:B": 2.0})
    vals = mock.get_many(["PV:A", "PV:B"])
    assert vals == {"PV:A": 1.0, "PV:B": 2.0}

    # put_with_readback without slew rate
    mock.put("DEV:SET", 0.0)
    mock.put("DEV:ACT", 10.0)
    # Converges immediately since MockControlInterface automatically mirrors Set to Act
    assert mock.put_with_readback("DEV:Set", "DEV:Act", 15.0, tolerance=0.1, timeout=1.0)

    # put_with_readback with max_slew_rate and missing initial setpoint
    with pytest.raises(MissingReadbackError):
        mock.put_with_readback("UNSET:PV:Set", "UNSET:PV:Act", 10.0, max_slew_rate=2.0, poll_interval=0.01)

    # put_with_readback with max_slew_rate success
    mock.put("RAMP:Set", 0.0)
    mock.put("RAMP:Act", 0.0)
    assert mock.put_with_readback("RAMP:Set", "RAMP:Act", 2.0, max_slew_rate=20.0, poll_interval=0.01, timeout=1.0)

    # put_with_readback timeout failure
    mock.put("STUCK:Set", 0.0)
    mock.put("STUCK:READBACK", -999.0)  # readback never updates
    with pytest.raises(ReadbackTimeoutError):
        mock.put_with_readback("STUCK:Set", "STUCK:READBACK", 10.0, tolerance=0.01, timeout=0.05, poll_interval=0.01)


# ==============================================================================
# 2. EPICS Interface Coverage
# ==============================================================================

def test_epics_interface_coverage():
    # MockControlInterface: SP -> RB mirroring
    mock = MockControlInterface()
    mock.put("MAGNET:SP", 42.0)
    assert mock.get("MAGNET:RB") == 42.0

    # MockControlInterface: subscriber callback error branch
    def broken_cb(pv, val):
        raise ValueError("broken")
    mock.subscribe("TRIGGER:Set", broken_cb)
    mock.put("TRIGGER:Set", 1.0)  # catches and logs error

    mock.unsubscribe("TRIGGER:Set")
    mock.unsubscribe("NONEXISTENT_PV")

    # EPICSInterface without pyepics installed
    epics_iface = EPICSInterface()
    epics_iface._has_epics = False

    with pytest.raises(ControlInterfaceError):
        epics_iface.get("SOME:PV")
    with pytest.raises(ControlInterfaceError):
        epics_iface.put("SOME:PV", 10.0)
    with pytest.raises(ControlInterfaceError):
        epics_iface.get_many(["SOME:PV"])
    with pytest.raises(ControlInterfaceError):
        epics_iface.subscribe("SOME:PV", lambda pv, val: None)

    # EPICSInterface with mocked pyepics
    mock_epics = MagicMock()
    mock_epics.caget.return_value = 12.34
    mock_epics.caput.return_value = 1
    mock_epics.caget_many.return_value = [1.0, 2.0]
    mock_pv_instance = MagicMock()
    mock_epics.PV.return_value = mock_pv_instance

    with patch.dict("sys.modules", {"epics": mock_epics}):
        epics_live = EPICSInterface()
        epics_live._has_epics = True

        assert epics_live.get("LIVE:PV") == 12.34
        assert epics_live.put("LIVE:PV", 5.0) is True

        mock_epics.caput.return_value = 0  # failure
        assert epics_live.put("LIVE:PV", 5.0) is False

        assert epics_live.get_many(["P1", "P2"]) == {"P1": 1.0, "P2": 2.0}

        called_vals = []
        epics_live.subscribe("LIVE:PV", lambda pv, val: called_vals.append((pv, val)))
        # Verify handler was registered
        args, kwargs = mock_epics.PV.call_args
        handler = kwargs.get("callback")
        handler(pvname="LIVE:PV", value=99.0)
        assert called_vals == [("LIVE:PV", 99.0)]

        epics_live.unsubscribe("LIVE:PV")
        mock_pv_instance.clear_callbacks.assert_called_once()
        epics_live.unsubscribe("NONEXISTENT")


# ==============================================================================
# 3. PVA Interface Coverage
# ==============================================================================

def test_pva_interface_coverage():
    # 1. Mock store mode
    pva_mock = PVAccessInterface(use_mock=True)
    pva_mock.put("PVA:TEST", 100.0)
    assert pva_mock.get("PVA:TEST") == 100.0

    sub_vals = []
    pva_mock.subscribe("PVA:TEST", lambda pv, val: sub_vals.append(val))
    pva_mock.put("PVA:TEST", 200.0)
    assert 200.0 in sub_vals
    pva_mock.unsubscribe("PVA:TEST")

    # NTTable operations in mock mode
    table_data = {"labels": ["bpm", "x"], "value": [["BPM1", "BPM2"], [0.1, -0.2]]}
    pva_mock.put_nt_table("ORBIT:TABLE", table_data)
    table_res = pva_mock.get_nt_table("ORBIT:TABLE")
    assert table_res["bpm"] == ["BPM1", "BPM2"]
    assert table_res["x"] == [0.1, -0.2]

    # NTTable raw dict without labels
    pva_mock.put("ORBIT:RAW_DICT", {"col1": [1, 2]})
    assert pva_mock.get_nt_table("ORBIT:RAW_DICT") == {"col1": [1, 2]}

    # NTTable empty fallback
    pva_mock.put("ORBIT:INVALID", "not_a_dict")
    assert pva_mock.get_nt_table("ORBIT:INVALID") == {}

    # NTNDArray operations in mock mode
    img = np.ones((4, 4), dtype=np.float32)
    pva_mock.put_nt_ndarray("CAMERA:IMG", img)
    assert np.allclose(pva_mock.get_nt_ndarray("CAMERA:IMG"), img)

    # NTNDArray list fallback
    pva_mock.put("CAMERA:LIST", [[1.0, 2.0], [3.0, 4.0]])
    assert pva_mock.get_nt_ndarray("CAMERA:LIST").shape == (2, 2)

    # NTNDArray empty fallback
    pva_mock.put("CAMERA:NONE", None)
    assert pva_mock.get_nt_ndarray("CAMERA:NONE").shape == (1, 1)

    # Mock store not initialized branches
    pva_mock._store = None
    with pytest.raises(ControlInterfaceError):
        pva_mock.get("PVA:ERR")
    with pytest.raises(ControlInterfaceError):
        pva_mock.put("PVA:ERR", 1.0)
    with pytest.raises(ControlInterfaceError):
        pva_mock.subscribe("PVA:ERR", lambda p, v: None)
    pva_mock.unsubscribe("PVA:ERR")

    # 2. Non-mock mode with missing/failed p4p
    with patch("helios.interfaces.pva.require", side_effect=ImportError("p4p missing")):
        with pytest.raises(ControlInterfaceError):
            PVAccessInterface(use_mock=False)

    # 3. Non-mock mode with mocked p4p context
    mock_pva_ctxt = MagicMock()
    mock_val_with_raw = MagicMock()
    mock_val_with_raw.raw = True
    mock_val_with_raw.value = 88.88
    mock_pva_ctxt.get.side_effect = [mock_val_with_raw, "plain_val", RuntimeError("PVA timeout")]
    mock_pva_ctxt.put.side_effect = [None, RuntimeError("Put timeout")]

    pva_live = object.__new__(PVAccessInterface)
    pva_live.security_manager = ControlSecurityManager()
    pva_live.use_mock = False
    pva_live._store = None
    pva_live.pva_ctxt = mock_pva_ctxt

    # get unwraps raw.value
    assert pva_live.get("CHAN1") == 88.88
    assert pva_live.get("CHAN2") == "plain_val"
    with pytest.raises(ControlInterfaceError):
        pva_live.get("CHAN3")

    # put success and failure
    assert pva_live.put("CHAN1", 10.0) is True
    with pytest.raises(ControlInterfaceError):
        pva_live.put("CHAN1", 10.0)

    # subscribe with monitor
    mon_cbs = []
    pva_live.subscribe("CHAN1", lambda p, v: mon_cbs.append(v))
    handler_fn = mock_pva_ctxt.monitor.call_args[0][1]
    handler_fn(mock_val_with_raw)
    assert mon_cbs == [88.88]

    # Context is None branches
    pva_live.pva_ctxt = None
    with pytest.raises(ControlInterfaceError):
        pva_live.get("CHAN1")
    with pytest.raises(ControlInterfaceError):
        pva_live.put("CHAN1", 1.0)
    with pytest.raises(ControlInterfaceError):
        pva_live.subscribe("CHAN1", lambda p, v: None)


# ==============================================================================
# 4. Security & Access Control Coverage
# ==============================================================================

def test_control_security_coverage():
    policy = ControlSecurityPolicy()

    # is_strictly_readonly
    assert policy.is_strictly_readonly("MEBT:MPS:TRIP_STATUS") is True
    assert policy.is_strictly_readonly("MEBT:PSC:CH01:CurrentSet") is False

    # required_role
    assert policy.required_role("MEBT:INTERLOCK:TRIP") == UserRole.ADMIN
    assert policy.required_role("MEBT:HIGH_VOLTAGE:SET") == UserRole.ADMIN
    assert policy.required_role("MEBT:CAV:01:PHASE_SET") == UserRole.PHYSICIST
    assert policy.required_role("MEBT:PSC:CH01:CurrentSet") == UserRole.OPERATOR

    # authorize_write
    assert policy.authorize_write("ANY:PV", UserRole.READ_ONLY) is False
    assert policy.authorize_write("MEBT:MPS:STATUS", UserRole.PHYSICIST) is False
    assert policy.authorize_write("MEBT:MPS:STATUS", UserRole.ADMIN) is True
    assert policy.authorize_write("MEBT:CAV:01:PHASE_SET", UserRole.OPERATOR) is False
    assert policy.authorize_write("MEBT:CAV:01:PHASE_SET", UserRole.PHYSICIST) is True
    assert policy.authorize_write("MEBT:PSC:CH01:CurrentSet", UserRole.OPERATOR) is True

    # ControlSecurityManager
    mgr = ControlSecurityManager(policy)
    assert mgr.current_role == UserRole.PHYSICIST

    mgr.set_session_role(UserRole.OPERATOR)
    assert mgr.current_role == UserRole.OPERATOR

    # check_permission permits benign write
    mgr.check_permission("MEBT:PSC:CH01:CurrentSet")

    # check_permission denies RF amplitude write to OPERATOR
    with pytest.raises(SecurityViolationError):
        mgr.check_permission("MEBT:CAV:01:AMP_SET")


# ==============================================================================
# 5. Archiver Appliance Client Coverage
# ==============================================================================

def test_archiver_client_coverage():
    t_start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    t_end = datetime(2026, 1, 1, 1, 0, 0, tzinfo=timezone.utc)

    # Mock mode with pre-registered data
    client_mock = ArchiverApplianceClient(mock_mode=True)
    sample_data = [
        {"secs": int(t_start.timestamp()) + 10, "val": 1.25},
        {"secs": int(t_start.timestamp()) + 30, "val": 1.35},
    ]
    client_mock.register_mock_history("MEBT:BPM01:X", sample_data)
    queried = client_mock.get_data("MEBT:BPM01:X", t_start, t_end)
    assert len(queried) == 2
    assert queried[0]["val"] == 1.25

    # Mock mode synthetic generated data
    synth_data = client_mock.get_data("MEBT:BPM02:X", t_start, t_end)
    assert len(synth_data) > 0

    # compute_pv_statistics with valid data
    stats = client_mock.compute_pv_statistics("MEBT:BPM01:X", t_start, t_end)
    assert stats["count"] == 2.0
    assert stats["mean"] == pytest.approx(1.30)
    assert stats["min"] == 1.25
    assert stats["max"] == 1.35

    # compute_pv_statistics with empty data
    # Filter registered data for empty window
    client_mock.register_mock_history("EMPTY:PV", [{"secs": 0, "val": 10.0}])
    stats_empty = client_mock.compute_pv_statistics("EMPTY:PV", t_start, t_end)
    assert stats_empty["count"] == 0.0

    # get_golden_baseline with and without numeric points
    client_mock.register_mock_history("PV:VALID", [{"secs": int(t_start.timestamp()), "val": 42.0}])
    client_mock.register_mock_history("PV:NON_NUMERIC", [{"secs": int(t_start.timestamp()), "val": "invalid"}])
    client_mock.register_mock_history("PV:EMPTY", [{"secs": 0, "val": 1.0}])

    base = client_mock.get_golden_baseline(["PV:VALID", "PV:NON_NUMERIC", "PV:EMPTY"], t_start, window_seconds=100)
    assert base["PV:VALID"] == 42.0
    assert base["PV:NON_NUMERIC"] == 0.0
    assert base["PV:EMPTY"] == 0.0

    # Live requests mode with mock HTTP responses
    client_live = ArchiverApplianceClient(mock_mode=False)

    mock_resp_success = MagicMock()
    mock_resp_success.json.return_value = [{"meta": {}, "data": [{"secs": 100, "val": 3.14}]}]
    mock_resp_success.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp_success):
        data_live = client_live.get_data("LIVE:PV", t_start, t_end)
        assert data_live == [{"secs": 100, "val": 3.14}]

    # Non-list response
    mock_resp_empty = MagicMock()
    mock_resp_empty.json.return_value = {}
    with patch("requests.get", return_value=mock_resp_empty):
        assert client_live.get_data("LIVE:PV", t_start, t_end) == []

    # HTTP exception fallback to mock
    with patch("requests.get", side_effect=RuntimeError("Network unreachable")):
        fb_data = client_live.get_data("MEBT:BPM01:X", t_start, t_end)
        assert len(fb_data) > 0


# ==============================================================================
# 6. Channel Map Coverage
# ==============================================================================

def test_channel_map_coverage(tmp_path):
    mgr = create_baseline_mebt_channel_manager()

    # resolve_pv_from_semantic: ":" match
    assert mgr.resolve_pv_from_semantic("MEBT:QD01", "setpoint") == "MEBT:PSC:QD01:CurrentSet"
    assert mgr.resolve_pv_from_semantic("MEBT:QD01", "readback") == "MEBT:PSC:QD01:CurrentAct"
    assert mgr.resolve_pv_from_semantic("MEBT:QD01", "status") == "MEBT:PSC:QD01:Status"
    assert mgr.resolve_pv_from_semantic("MEBT:QD01", "unknown_type") is None

    # Alias match
    assert mgr.resolve_pv_from_semantic("mebt quad 01") == "MEBT:PSC:QD01:CurrentSet"

    # Fuzzy keyword search
    assert mgr.resolve_pv_from_semantic("Please adjust MEBT QD01 now") == "MEBT:PSC:QD01:CurrentSet"

    # No match
    assert mgr.resolve_pv_from_semantic("Completely unknown query") is None

    # get_device_by_pv
    dev = mgr.get_device_by_pv("MEBT:PSC:QD01:CurrentSet")
    assert dev is not None
    assert dev.name == "QD01"
    assert mgr.get_device_by_pv("NONEXISTENT:PV") is None

    # filter_devices
    mebt_quads = mgr.filter_devices(section="MEBT", device_type=DeviceType.QUADRUPOLE)
    assert len(mebt_quads) == 2
    assert mebt_quads[0].z_position_m < mebt_quads[1].z_position_m

    all_steerers = mgr.filter_devices(device_type=DeviceType.STEERER_H)
    assert len(all_steerers) == 1

    # from_yaml_file
    import yaml
    yaml_file = tmp_path / "channels_test.yaml"
    with open(yaml_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "devices": [
                {
                    "name": "DUMMY_Q1",
                    "device_id": "DUMMY_Q1",
                    "section": "TEST",
                    "device_type": "QUADRUPOLE",
                    "setpoint_pv": "TEST:Q1:Set",
                    "limits": {"min_val": -10.0, "max_val": 10.0},
                }
            ]
        }, f)
    loaded_mgr = ChannelManager.from_yaml_file(yaml_file)
    assert loaded_mgr.get_device("TEST", "DUMMY_Q1") is not None


# ==============================================================================
# 7. Diagnostics (Anomaly, Archiver, Survey, Telemetry) Coverage
# ==============================================================================

def test_diagnostics_coverage(tmp_path):
    # LinacAnomalyDetector
    detector = LinacAnomalyDetector(max_rms_orbit_mm=1.0, min_transmission_pct=90.0, max_blm_dose=10.0)

    # 1. Transmission drop: WARNING (70%) and CRITICAL (30%)
    snap_warn = TelemetrySnapshot(
        section="MEBT",
        bpm_x={"B1": 0.1},
        bpm_y={"B1": 0.1},
        blm_loss={"L1": 1.0},
        transmission_pct=70.0,
        beam_current_ma=5.0,
    )
    rep_warn = detector.inspect_telemetry(snap_warn)
    assert len(rep_warn) == 1
    assert rep_warn[0].severity.value == "WARNING"

    snap_crit = TelemetrySnapshot(
        section="MEBT",
        bpm_x={"B1": 2.5},  # orbit excursion
        bpm_y={"B1": 0.1},
        blm_loss={"L1": 25.0},  # BLM spike
        transmission_pct=30.0,  # critical transmission drop
        beam_current_ma=2.0,
    )
    rep_crit = detector.inspect_telemetry(snap_crit)
    assert len(rep_crit) == 3  # transmission drop, BLM spike, orbit excursion

    # 2. inspect_rf_station
    rep_trip = detector.inspect_rf_station("CAV01", amp_set=100.0, amp_act=0.0, interlock_tripped=True)
    assert rep_trip is not None
    assert rep_trip.anomaly_type == "RF_TRIP"

    rep_collapse = detector.inspect_rf_station("CAV01", amp_set=100.0, amp_act=0.5, interlock_tripped=False)
    assert rep_collapse is not None
    assert rep_collapse.anomaly_type == "RF_AMPLITUDE_COLLAPSE"

    assert detector.inspect_rf_station("CAV01", amp_set=100.0, amp_act=99.8, interlock_tripped=False) is None

    # TelemetryArchiver
    arch = TelemetryArchiver(max_buffer_size=5)
    assert arch.get_latest() is None

    arch.record_snapshot(snap_warn)
    arch.record_snapshot(snap_crit)
    assert arch.get_latest() == snap_crit
    assert len(arch.get_recent(5)) == 2

    stats_x = arch.compute_trend_stats("B1", plane="x")
    assert stats_x["count"] == 2
    assert stats_x["mean"] == pytest.approx((0.1 + 2.5) / 2.0)

    stats_y = arch.compute_trend_stats("B1", plane="y")
    assert stats_y["count"] == 2

    assert arch.compute_trend_stats("UNKNOWN_BPM")["count"] == 0

    json_export = tmp_path / "telemetry_history.json"
    arch.export_json(json_export)
    assert json_export.exists()

    # LaserTrackerSurveyAnalyzer
    m1 = MagnetFiducialMeasurement(
        element_id="Q1",
        girder_id="G1",
        s_longitudinal_m=0.0,
        measured_x_mm=0.2,
        measured_y_mm=-0.1,
        measured_z_mm=0.0,
    )
    m2 = MagnetFiducialMeasurement(
        element_id="Q2",
        girder_id="G1",
        s_longitudinal_m=1.0,
        measured_x_mm=0.4,
        measured_y_mm=-0.2,
        measured_z_mm=0.0,
    )
    misalign = LaserTrackerSurveyAnalyzer.evaluate_misalignments([m1, m2])
    assert misalign["Q1"]["delta_x_mm"] == 0.2
    assert misalign["Q2"]["delta_x_mm"] == 0.4

    survey_analyzer = LaserTrackerSurveyAnalyzer()
    with pytest.raises(ValueError):
        survey_analyzer.optimize_girder_realignment("G1", [])

    adj = survey_analyzer.optimize_girder_realignment("G1", [m1, m2])
    assert isinstance(adj, GirderMoverAdjustment)
    assert adj.girder_id == "G1"
    assert adj.rms_residual_error_mm < 0.3

    # TelemetryProcessor
    assert TelemetryProcessor.compute_rms_orbit({}) == 0.0
    assert TelemetryProcessor.compute_rms_orbit({"B1": 3.0, "B2": 4.0}) == pytest.approx(np.sqrt(12.5))

    assert TelemetryProcessor.compute_transmission(0.0, 5.0) == 0.0
    assert TelemetryProcessor.compute_transmission(10.0, 9.5) == pytest.approx(95.0)

    # calculate_energy_from_tof near-zero phase and normal phase
    energy_near_zero = TelemetryProcessor.calculate_energy_from_tof(0.0, 0.00001, distance_m=0.5)
    assert energy_near_zero > 0.0

    energy_normal = TelemetryProcessor.calculate_energy_from_tof(0.0, 45.0, distance_m=0.5)
    assert energy_normal > 0.0

    # process_snapshot
    proc_snap, metrics = TelemetryProcessor.process_snapshot(
        bpm_x={"B1": 0.5},
        bpm_y={"B1": -0.5},
        blm_losses={"L1": 2.0},
        upstream_current_ma=10.0,
        downstream_current_ma=9.8,
    )
    assert proc_snap.transmission_pct == pytest.approx(98.0)
    assert metrics["total_loss_dose"] == 2.0
