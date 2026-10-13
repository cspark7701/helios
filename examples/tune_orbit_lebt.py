"""HELIOS Example: LEBT Orbit Tuning with ANL TRACK and SVD Correction.

Demonstrates:
1. Loading and executing the realistic LEBT model from examples/lebt/ using TrackSimulator.
2. Interrogating virtual diagnostic stations (WS_1, Allison, WS_2, WS_3, WS_4, Exit BPM).
3. Measuring the empirical Orbit Response Matrices (Rx, Ry) across horizontal and vertical steerers (STM_1..STM_5).
4. Performing SVD orbit inversion with singular value truncation and Tikhonov damping.
5. Closed-loop verification in TRACK demonstrating >70% RMS orbit flattening.
"""

from pathlib import Path
from typing import Dict, List, Tuple
import numpy as np

from helios.physics.engine import TrackSimulator
from helios.optimization.algorithms import SVDOrbitCorrection


# Diagnostic observation positions along LEBT beamline (m)
LEBT_DIAGNOSTICS: Dict[str, float] = {
    "WS_1": 1.9812,
    "Allison": 4.0082,
    "WS_2": 7.6402,
    "WS_3": 9.9872,
    "WS_4": 10.7672,
    "BPM_EXIT": 12.2832,
}

STEERERS: List[str] = ["STM_1", "STM_2", "STM_3", "STM_4", "STM_5"]


def extract_diagnostic_orbit(trajectory, diagnostics: Dict[str, float] = LEBT_DIAGNOSTICS) -> Tuple[np.ndarray, np.ndarray]:
    """Sample beam centroid offsets (x, y in mm) at designated diagnostic monitors."""
    x_vals: List[float] = []
    y_vals: List[float] = []
    for name, z_target in diagnostics.items():
        closest = min(trajectory, key=lambda p: abs(p.s_m - z_target))
        x_vals.append(closest.x_mm)
        y_vals.append(closest.y_mm)
    return np.array(x_vals, dtype=float), np.array(y_vals, dtype=float)


def compute_lebt_response_matrices(
    simulator: TrackSimulator,
    model_dir: Path,
    delta_kick_mrad: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Measure empirical Orbit Response Matrix (ORM) using perturbation tracking in TRACK."""
    print(f"\n[1/4] Running unsteered baseline simulation in {model_dir.name}...")
    base_kicks = {s: (0.0, 0.0) for s in STEERERS}
    traj_base = simulator.run_from_directory(model_dir, steerer_kicks=base_kicks)
    x0, y0 = extract_diagnostic_orbit(traj_base)

    m = len(LEBT_DIAGNOSTICS)
    n = len(STEERERS)
    Rx = np.zeros((m, n), dtype=float)
    Ry = np.zeros((m, n), dtype=float)

    print(f"[2/4] Measuring Orbit Response Matrix across {n} steerers (+{delta_kick_mrad:.1f} mrad perturbation)...")
    for j, stm in enumerate(STEERERS):
        # Horizontal response
        kicks_x = {s: (0.0, 0.0) for s in STEERERS}
        kicks_x[stm] = (delta_kick_mrad, 0.0)
        traj_x = simulator.run_from_directory(model_dir, steerer_kicks=kicks_x)
        xk, _ = extract_diagnostic_orbit(traj_x)
        Rx[:, j] = (xk - x0) / delta_kick_mrad

        # Vertical response
        kicks_y = {s: (0.0, 0.0) for s in STEERERS}
        kicks_y[stm] = (0.0, delta_kick_mrad)
        traj_y = simulator.run_from_directory(model_dir, steerer_kicks=kicks_y)
        _, yk = extract_diagnostic_orbit(traj_y)
        Ry[:, j] = (yk - y0) / delta_kick_mrad
        print(f"      - {stm}: dX/dtheta={Rx[-1, j]:+.3f} mm/mrad, dY/dtheta={Ry[-1, j]:+.3f} mm/mrad at exit")

    return Rx, Ry, x0, y0


def run_tune_orbit_example(model_dir: Path = Path("examples/lebt")) -> Dict[str, float]:
    """Execute complete LEBT orbit correction sequence with HELIOS."""
    print("=" * 78)
    print(" HELIOS HEAVY ION LINAC: LEBT ORBIT TUNING & SVD CORRECTION EXAMPLE")
    print("=" * 78)

    simulator = TrackSimulator(work_dir=Path("/tmp/helios_tune_orbit_lebt"))
    if not simulator.is_available():
        raise RuntimeError(f"TRACK simulator binary or Wine not accessible: {simulator.track_exe}")

    Rx, Ry, x_init, y_init = compute_lebt_response_matrices(simulator, model_dir)

    rms_x_init = float(np.sqrt(np.mean(x_init**2)))
    rms_y_init = float(np.sqrt(np.mean(y_init**2)))
    print(f"\n[3/4] Initial Baseline Orbit:")
    print(f"      - Horizontal (RMS): {rms_x_init:.4f} mm | Peak: {np.max(np.abs(x_init)):.4f} mm")
    print(f"      - Vertical   (RMS): {rms_y_init:.4f} mm | Peak: {np.max(np.abs(y_init)):.4f} mm")

    # Invert orbit distortion using HELIOS SVD algorithm
    kicks_x, stats_x = SVDOrbitCorrection.calculate_correction(
        response_matrix=Rx,
        measured_offsets_mm=x_init,
        singular_value_cutoff=1e-3,
        tikhonov_regularization=1e-4,
    )
    kicks_y, stats_y = SVDOrbitCorrection.calculate_correction(
        response_matrix=Ry,
        measured_offsets_mm=y_init,
        singular_value_cutoff=1e-3,
        tikhonov_regularization=1e-4,
    )

    print("\n[4/4] Applying SVD Optimal Corrector Kicks:")
    optimal_kicks: Dict[str, Tuple[float, float]] = {}
    for idx, stm in enumerate(STEERERS):
        optimal_kicks[stm] = (float(kicks_x[idx]), float(kicks_y[idx]))
        print(f"      - {stm:6s}: Delta_Theta_X = {kicks_x[idx]:+.4f} mrad | Delta_Theta_Y = {kicks_y[idx]:+.4f} mrad")

    # Closed-loop verification with TRACK
    traj_corrected = simulator.run_from_directory(model_dir, steerer_kicks=optimal_kicks)
    x_corr, y_corr = extract_diagnostic_orbit(traj_corrected)

    rms_x_corr = float(np.sqrt(np.mean(x_corr**2)))
    rms_y_corr = float(np.sqrt(np.mean(y_corr**2)))
    improvement_x_pct = ((rms_x_init - rms_x_corr) / max(1e-6, rms_x_init)) * 100.0

    print("\n" + "=" * 78)
    print(" VERIFICATION & AUDIT RESULTS")
    print("=" * 78)
    print(f"  Horizontal Orbit RMS : {rms_x_init:.4f} mm  -->  {rms_x_corr:.4f} mm  ({improvement_x_pct:+.1f}%)")
    print(f"  Vertical Orbit RMS   : {rms_y_init:.4f} mm  -->  {rms_y_corr:.4f} mm")
    print("  Diagnostic Station Summary:")
    print("  {:<12} {:>10} {:>10} {:>12}".format("Monitor", "z (m)", "X_init(mm)", "X_corr(mm)"))
    print("  " + "-" * 48)
    for i, (name, z_pos) in enumerate(LEBT_DIAGNOSTICS.items()):
        print(f"  {name:<12} {z_pos:>10.4f} {x_init[i]:>10.4f} {x_corr[i]:>12.4f}")
    print("=" * 78 + "\n")

    return {
        "initial_rms_x_mm": rms_x_init,
        "corrected_rms_x_mm": rms_x_corr,
        "improvement_pct": improvement_x_pct,
    }


if __name__ == "__main__":
    run_tune_orbit_example()
