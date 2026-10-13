"""Tests for HELIOS Phases 35-39: Differentiable Physics, ECR Source, Halo, Mesh & Multi-Modal UI."""

import time
import numpy as np
import torch
import pytest

from helios.physics.differentiable import (
    DifferentiableDrift,
    DifferentiableQuadrupole,
    DifferentiableRFCavity,
    DifferentiableLattice,
    InverseLatticeSolver,
)
from helios.tuning.ionsource import (
    ECRSourceParameters,
    ECRSourceOptimizer,
    MultiSpeciesFastSwitcher,
)
from helios.physics.halo import (
    BeamHaloAnalyzer,
    DynamicCollimatorOptimizer,
)
from helios.safety.predictive import (
    QuenchRiskLevel,
    CryomoduleTelemetry,
    PredictiveQuenchInterlock,
)
from helios.core.mesh import (
    MeshNodeType,
    NodeStatus,
    AgentMeshNode,
    AgentMeshMessage,
    DistributedAgentMesh,
)
from helios.ui.voice import OperatorIntentParser
from helios.ui.visualizer import PhaseSpaceVisualizer


def test_differentiable_physics_and_inverse_solver():
    """Verify PyTorch autodiff through lattice and inverse parameter recovery."""
    torch.manual_seed(42)
    # Create simple FODO-like section
    drift1 = DifferentiableDrift("drift1", length=0.3)
    quad1 = DifferentiableQuadrupole("quad1", length=0.2, k1=4.5)
    drift2 = DifferentiableDrift("drift2", length=0.3)
    cav1 = DifferentiableRFCavity("cav1", length=0.1, voltage_MV=1.2, phase_rad=0.1)

    lattice = DifferentiableLattice([drift1, quad1, drift2, cav1])

    # Initial particle bunch: 100 particles in 6D
    init_bunch = torch.randn(100, 6, dtype=torch.float64) * 0.002

    # Forward tracking
    out_bunch = lattice.track(init_bunch)
    assert out_bunch.shape == (100, 6)

    # Generate target measurements with ground truth quad1.k1 = 5.2
    target_lattice = DifferentiableLattice([
        DifferentiableDrift("drift1", length=0.3),
        DifferentiableQuadrupole("quad1", length=0.2, k1=5.2),
        DifferentiableDrift("drift2", length=0.3),
        DifferentiableRFCavity("cav1", length=0.1, voltage_MV=1.2, phase_rad=0.1)
    ])
    target_bunch = target_lattice.track(init_bunch).detach()

    # Solve inverse problem starting from k1 = 4.5
    solver = InverseLatticeSolver(lattice, lr=0.1, max_iter=60)
    result = solver.solve(
        initial_bunch=init_bunch,
        target_bunch=target_bunch,
        ground_truth={"quad1.k1": 5.2},
        loss_tolerance=1e-5
    )

    assert result.converged or result.final_loss < 1e-4
    recovered_k1 = result.recovered_parameters["quad1.k1"]
    assert abs(recovered_k1 - 5.2) < 0.15


def test_ecr_source_tuning_and_species_switching():
    """Verify ECR charge state distribution optimization and multi-species switching."""
    ecr = ECRSourceOptimizer(species="U238", mass_amu=238.0)
    nominal_params = ECRSourceParameters(
        microwave_power_kW=2.5,
        frequency_GHz=28.0,
        gas_mixing_ratio_percent=25.0
    )
    csd = ecr.simulate_csd(nominal_params, target_q=33)

    assert csd.total_extracted_current_uA > 50.0
    assert 20 <= csd.peak_charge_state <= 40
    assert csd.target_state_current_uA > 0.0

    # Test optimization
    best_params = ecr.optimize_for_charge_state(target_q=33, max_power_kW=4.0)
    assert best_params.microwave_power_kW >= 1.5

    # Test fast species switching Ar40 -> U238
    switcher = MultiSpeciesFastSwitcher()
    plan = switcher.plan_species_switch(source_species="Ar40", target_species="U238", target_q=33)

    assert plan.source_species == "Ar40"
    assert plan.target_species == "U238"
    assert plan.rigidity_ratio > 1.0  # U33+ has higher B*rho than Ar9+ at same keV/u
    assert plan.lebt_solenoid_current_factor == plan.rigidity_ratio
    assert plan.ramp_duration_seconds > 0.0


def test_beam_halo_and_dynamic_collimation():
    """Verify non-Gaussian halo metrics (kurtosis, H-parameter) and jaw optimization."""
    np.random.seed(42)
    # Generate distribution with core (Gaussian) + halo (heavy Laplace tails)
    n_core = 9000
    n_halo = 1000
    x_core = np.random.normal(0, 0.001, n_core)
    x_halo = np.random.laplace(0, 0.005, n_halo)
    x_total = np.concatenate([x_core, x_halo])
    y_total = np.concatenate([np.random.normal(0, 0.001, n_core), np.random.laplace(0, 0.005, n_halo)])

    analyzer = BeamHaloAnalyzer()
    metrics_x = analyzer.compute_plane_halo(x_total, "x")

    assert metrics_x.kurtosis > 0.5  # Positive excess kurtosis indicating halo
    assert metrics_x.h_parameter > 0.0
    assert metrics_x.halo_fraction > 0.0

    # Optimize dynamic collimator jaws
    optimizer = DynamicCollimatorOptimizer(target_core_transmission=0.995)
    jaws = optimizer.optimize_jaws("COLLIM_MEBT_01", x_total, y_total, core_sigma_multiplier=3.2)

    assert jaws.estimated_core_transmission >= 0.95
    assert jaws.estimated_halo_reduction_fraction > 0.40
    assert jaws.jaw_right_mm > 0.0
    assert jaws.jaw_left_mm < 0.0


def test_predictive_quench_interlock():
    """Verify predictive detection of impending SRF cavity quenches."""
    interlock = PredictiveQuenchInterlock(
        nominal_temp_K=2.05,
        max_allowed_temp_K=2.20,
        temp_rate_threshold_K_per_s=0.15,
        refl_power_ratio_threshold=0.35
    )

    # Nominal telemetry
    nominal_window = [
        CryomoduleTelemetry(
            timestamp_ms=float(i * 10),
            cavity_id="CAV_SCL1_01",
            helium_bath_temp_K=2.05 + 0.001 * (i % 2),
            helium_pressure_mbar=31.0,
            forward_power_kW=4.0,
            reflected_power_kW=0.08
        )
        for i in range(10)
    ]
    res_nom = interlock.evaluate_telemetry_window(nominal_window)
    assert res_nom.risk_level == QuenchRiskLevel.NOMINAL
    assert res_nom.quench_probability < 0.25

    # Impending quench scenario: fast temperature rise + RF reflection surge
    quench_window = [
        CryomoduleTelemetry(
            timestamp_ms=float(i * 10),
            cavity_id="CAV_SCL1_01",
            helium_bath_temp_K=2.05 + 0.015 * i,  # 0.15 K rise over 90 ms -> ~1.6 K/s!
            helium_pressure_mbar=31.0 + 0.5 * i,
            forward_power_kW=4.0,
            reflected_power_kW=0.2 + 0.25 * i  # rapid rise in reflected power
        )
        for i in range(10)
    ]
    res_quench = interlock.evaluate_telemetry_window(quench_window)
    assert res_quench.risk_level == QuenchRiskLevel.CRITICAL_IMPENDING_QUENCH
    assert res_quench.quench_probability > 0.70
    assert "BEAM_CUT" in res_quench.recommended_action


def test_distributed_agent_mesh_and_failover():
    """Verify agent mesh pub/sub, edge offline buffering, and orchestrator failover."""
    mesh = DistributedAgentMesh(heartbeat_timeout_s=0.1)

    node_orch1 = AgentMeshNode(
        node_id="orch_primary",
        node_type=MeshNodeType.ORCHESTRATOR,
        address="tcp://10.0.1.1:5555",
        priority_rank=20
    )
    node_orch2 = AgentMeshNode(
        node_id="orch_backup",
        node_type=MeshNodeType.ORCHESTRATOR,
        address="tcp://10.0.1.2:5555",
        priority_rank=15
    )
    node_edge = AgentMeshNode(
        node_id="ioc_mebt_edge",
        node_type=MeshNodeType.EDGE_IOC,
        address="tcp://10.0.1.10:5555",
        priority_rank=5
    )

    mesh.register_node(node_orch1)
    mesh.register_node(node_orch2)
    mesh.register_node(node_edge)

    assert mesh.active_orchestrator_id == "orch_primary"

    # Test pub/sub
    received_msgs = []
    mesh.subscribe("telemetry.bpm", lambda msg: received_msgs.append(msg))

    msg1 = AgentMeshMessage(
        sender_id="ioc_mebt_edge",
        target_id="*",
        topic="telemetry.bpm",
        payload={"bpm_mebt_01_x_mm": 0.12}
    )
    delivered = mesh.publish(msg1)
    assert delivered == 1
    assert len(received_msgs) == 1

    # Test edge offline buffering & sync
    msg_buffered = AgentMeshMessage(
        sender_id="ioc_mebt_edge",
        target_id="orch_primary",
        topic="telemetry.bpm",
        payload={"bpm_mebt_02_x_mm": -0.05}
    )
    mesh.buffer_edge_offline_action("ioc_mebt_edge", msg_buffered)
    synced = mesh.sync_reconnection("ioc_mebt_edge")
    assert synced == 1
    assert len(received_msgs) == 2

    # Simulate primary orchestrator heartbeat timeout (sleep > 0.1s)
    time.sleep(0.12)
    # Refresh backup and edge only
    mesh.heartbeat("orch_backup")
    mesh.heartbeat("ioc_mebt_edge")

    new_leader = mesh.check_liveness_and_elect_orchestrator()
    assert new_leader == "orch_backup"


def test_voice_intent_and_phase_space_visualizer():
    """Verify natural language control room intent parser and 6D phase space projections."""
    parser = OperatorIntentParser()

    intent1 = parser.parse_command("Please correct orbit in SCL1 and check BPM01")
    assert intent1.action_type == "orbit_correction"
    assert intent1.target_subsystem == "SCL1"
    assert "BPM01" in intent1.target_devices
    assert intent1.confidence > 0.8

    intent2 = parser.parse_command("Switch species to Uranium U238 in LEBT")
    assert intent2.action_type == "species_switch"
    assert intent2.target_subsystem == "LEBT"
    assert intent2.parameters.get("target_species") == "U238"

    # Test Phase Space Visualizer
    np.random.seed(42)
    n_part = 500
    # Create 6D bunch [x, x', y, y', z, delta]
    bunch = np.zeros((n_part, 6))
    bunch[:, 0] = np.random.normal(0, 0.001, n_part)
    bunch[:, 1] = np.random.normal(0, 0.0005, n_part) + 0.2 * bunch[:, 0]
    bunch[:, 2] = np.random.normal(0, 0.0012, n_part)
    bunch[:, 3] = np.random.normal(0, 0.0004, n_part)

    vis = PhaseSpaceVisualizer()
    proj_x = vis.project(bunch, plane="x")

    assert proj_x.plane == "x"
    assert proj_x.num_particles == 500
    assert proj_x.twiss.emittance_rms_mm_mrad > 0.0
    assert proj_x.twiss.beta_m > 0.0

    # ASCII render check
    ascii_plot = vis.render_ascii(bunch, plane="x", width=30, height=8)
    assert "+" in ascii_plot
    assert "*" in ascii_plot

    # Discrepancy metric
    sim_bunch = bunch + np.random.normal(0, 0.0001, bunch.shape)
    discrepancy = vis.calculate_discrepancy(bunch, sim_bunch)
    assert 0.0 < discrepancy < 0.001
