import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import numpy as np

from helios.physics.engine import TrackSimulator
from helios.physics.elements import Steerer
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

# Default hardware power supply conversion calibration for LEBT
DEFAULT_CONVERSION_FACTOR_A_PER_MRAD: float = 0.168
DEFAULT_CURRENT_INCREMENT_A: float = 0.01


def extract_diagnostic_orbit(
    trajectory,
    diagnostics: Dict[str, float] = LEBT_DIAGNOSTICS,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Sample beam centroid offsets (x, y) and RMS beam sizes (sigma_x, sigma_y) at designated diagnostic monitors."""
    x_vals: List[float] = []
    y_vals: List[float] = []
    sx_vals: List[float] = []
    sy_vals: List[float] = []
    for name, z_target in diagnostics.items():
        closest = min(trajectory, key=lambda p: abs(p.s_m - z_target))
        x_vals.append(closest.x_mm)
        y_vals.append(closest.y_mm)
        sx_vals.append(getattr(closest, "sigma_x_mm", 2.5))
        sy_vals.append(getattr(closest, "sigma_y_mm", 2.5))
    return (
        np.array(x_vals, dtype=float),
        np.array(y_vals, dtype=float),
        np.array(sx_vals, dtype=float),
        np.array(sy_vals, dtype=float),
    )


def compute_lebt_response_matrices(
    simulator: TrackSimulator,
    model_dir: Path,
    delta_kick_mrad: float = 1.0,
    conversion_factor_a_per_mrad: float = DEFAULT_CONVERSION_FACTOR_A_PER_MRAD,
    current_increment_a: float = DEFAULT_CURRENT_INCREMENT_A,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Measure empirical Orbit Response Matrix (ORM) using perturbation tracking in TRACK."""
    print(f"\n[1/4] Running unsteered baseline simulation in {model_dir.name}...")
    base_currents = {s: (0.0, 0.0) for s in STEERERS}
    traj_base = simulator.run_from_directory(
        model_dir,
        steerer_currents=base_currents,
        conversion_factor_a_per_mrad=conversion_factor_a_per_mrad,
        current_increment_a=current_increment_a,
    )
    x0, y0, sx0, sy0 = extract_diagnostic_orbit(traj_base)

    m = len(LEBT_DIAGNOSTICS)
    n = len(STEERERS)
    Rx = np.zeros((m, n), dtype=float)
    Ry = np.zeros((m, n), dtype=float)

    print(f"[2/4] Measuring Orbit Response Matrix across {n} steerers (+{delta_kick_mrad:.1f} mrad perturbation)...")
    for j, stm in enumerate(STEERERS):
        # Horizontal response (apply perturbation via steerer current)
        delta_i = Steerer.kick_to_current(delta_kick_mrad, conversion_factor_a_per_mrad, current_increment_a)
        effective_dk = Steerer.current_to_kick(delta_i, conversion_factor_a_per_mrad)

        currents_x = {s: (0.0, 0.0) for s in STEERERS}
        currents_x[stm] = (delta_i, 0.0)
        traj_x = simulator.run_from_directory(
            model_dir,
            steerer_currents=currents_x,
            conversion_factor_a_per_mrad=conversion_factor_a_per_mrad,
            current_increment_a=current_increment_a,
        )
        xk, _, _, _ = extract_diagnostic_orbit(traj_x)
        Rx[:, j] = (xk - x0) / effective_dk

        # Vertical response
        currents_y = {s: (0.0, 0.0) for s in STEERERS}
        currents_y[stm] = (0.0, delta_i)
        traj_y = simulator.run_from_directory(
            model_dir,
            steerer_currents=currents_y,
            conversion_factor_a_per_mrad=conversion_factor_a_per_mrad,
            current_increment_a=current_increment_a,
        )
        _, yk, _, _ = extract_diagnostic_orbit(traj_y)
        Ry[:, j] = (yk - y0) / effective_dk
        print(f"      - {stm}: dX/dI={Rx[-1, j] / conversion_factor_a_per_mrad:+.3f} mm/A ({Rx[-1, j]:+.3f} mm/mrad), dY/dI={Ry[-1, j] / conversion_factor_a_per_mrad:+.3f} mm/A at exit")

    return Rx, Ry, x0, y0, sx0, sy0


def run_tune_orbit_example(
    model_dir: Path = Path("examples/lebt"),
    conversion_factor_a_per_mrad: float = DEFAULT_CONVERSION_FACTOR_A_PER_MRAD,
    current_increment_a: float = DEFAULT_CURRENT_INCREMENT_A,
) -> Dict[str, float]:
    """Execute complete LEBT orbit correction sequence with HELIOS using power supply current actuation."""
    start_time = time.perf_counter()

    print("=" * 78)
    print(" HELIOS HEAVY ION LINAC: LEBT ORBIT TUNING & CURRENT ACTUATION EXAMPLE")
    print("=" * 78)
    print(f"  Steerer Transfer Factor : {conversion_factor_a_per_mrad:.3f} A/mrad")
    print(f"  Power Supply Step Limit : {current_increment_a:.2f} A increment")

    simulator = TrackSimulator(work_dir=Path("/tmp/helios_tune_orbit_lebt"))
    if not simulator.is_available():
        raise RuntimeError(f"TRACK simulator binary or Wine not accessible: {simulator.track_exe}")

    Rx, Ry, x_init, y_init, sx_init, sy_init = compute_lebt_response_matrices(
        simulator,
        model_dir,
        conversion_factor_a_per_mrad=conversion_factor_a_per_mrad,
        current_increment_a=current_increment_a,
    )

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

    print("\n[4/4] Converting Corrector Deflections to Power Supply Currents (A):")
    optimal_currents: Dict[str, Tuple[float, float]] = {}
    optimal_kicks_quantized: Dict[str, Tuple[float, float]] = {}

    for idx, stm in enumerate(STEERERS):
        # Convert continuous mrad kicks to discrete quantized currents
        curr_x = Steerer.kick_to_current(float(kicks_x[idx]), conversion_factor_a_per_mrad, current_increment_a)
        curr_y = Steerer.kick_to_current(float(kicks_y[idx]), conversion_factor_a_per_mrad, current_increment_a)
        optimal_currents[stm] = (curr_x, curr_y)

        eff_kx = Steerer.current_to_kick(curr_x, conversion_factor_a_per_mrad)
        eff_ky = Steerer.current_to_kick(curr_y, conversion_factor_a_per_mrad)
        optimal_kicks_quantized[stm] = (eff_kx, eff_ky)

        print(
            f"      - {stm:6s}: I_x = {curr_x:+6.2f} A (kick {eff_kx:+7.4f} mrad) | "
            f"I_y = {curr_y:+6.2f} A (kick {eff_ky:+7.4f} mrad)"
        )

    # Closed-loop verification with TRACK using quantized power supply currents
    traj_corrected = simulator.run_from_directory(
        model_dir,
        steerer_currents=optimal_currents,
        conversion_factor_a_per_mrad=conversion_factor_a_per_mrad,
        current_increment_a=current_increment_a,
    )
    x_corr, y_corr, sx_corr, sy_corr = extract_diagnostic_orbit(traj_corrected)

    rms_x_corr = float(np.sqrt(np.mean(x_corr**2)))
    rms_y_corr = float(np.sqrt(np.mean(y_corr**2)))
    improvement_x_pct = ((rms_x_init - rms_x_corr) / max(1e-6, rms_x_init)) * 100.0
    improvement_y_pct = ((rms_y_init - rms_y_corr) / max(1e-6, rms_y_init)) * 100.0

    elapsed_time_s = time.perf_counter() - start_time

    print("\n" + "=" * 78)
    print(" VERIFICATION & AUDIT RESULTS")
    print("=" * 78)
    print(f"  Horizontal Orbit RMS : {rms_x_init:.4f} mm  -->  {rms_x_corr:.4f} mm  ({improvement_x_pct:+.1f}%)")
    print(f"  Vertical Orbit RMS   : {rms_y_init:.4f} mm  -->  {rms_y_corr:.4f} mm  ({improvement_y_pct:+.1f}%)")
    print(f"  Orbit Correction Time: {elapsed_time_s:.2f} seconds")
    print("  Diagnostic Station Summary:")
    print("  {:<12} {:>10} {:>10} {:>12} {:>10} {:>12} {:>10} {:>10}".format(
        "Monitor", "z (m)", "X_init(mm)", "X_corr(mm)", "Y_init(mm)", "Y_corr(mm)", "SigX(mm)", "SigY(mm)"
    ))
    print("  " + "-" * 88)
    for i, (name, z_pos) in enumerate(LEBT_DIAGNOSTICS.items()):
        print(f"  {name:<12} {z_pos:>10.4f} {x_init[i]:>10.4f} {x_corr[i]:>12.4f} {y_init[i]:>10.4f} {y_corr[i]:>12.4f} {sx_corr[i]:>10.4f} {sy_corr[i]:>10.4f}")
    print("=" * 78 + "\n")

    return {
        "initial_rms_x_mm": rms_x_init,
        "corrected_rms_x_mm": rms_x_corr,
        "initial_rms_y_mm": rms_y_init,
        "corrected_rms_y_mm": rms_y_corr,
        "improvement_pct": improvement_x_pct,
        "improvement_x_pct": improvement_x_pct,
        "improvement_y_pct": improvement_y_pct,
        "elapsed_time_s": elapsed_time_s,
        "steerers": [
            {
                "name": stm,
                "kick_x_mrad": round(optimal_kicks_quantized[stm][0], 4),
                "current_x_a": round(optimal_currents[stm][0], 4),
                "kick_y_mrad": round(optimal_kicks_quantized[stm][1], 4),
                "current_y_a": round(optimal_currents[stm][1], 4),
            }
            for stm in STEERERS
        ],
        "monitors": [
            {
                "name": name,
                "type": "Wire Scanner" if "WS" in name else ("Slit Collector" if "Allison" in name else "BPM"),
                "z_m": round(z_pos, 4),
                "x_init_mm": round(float(x_init[i]), 4),
                "x_corr_mm": round(float(x_corr[i]), 4),
                "y_init_mm": round(float(y_init[i]), 4),
                "y_corr_mm": round(float(y_corr[i]), 4),
                "sigma_x_mm": round(float(sx_corr[i]), 4),
                "sigma_y_mm": round(float(sy_corr[i]), 4),
            }
            for i, (name, z_pos) in enumerate(LEBT_DIAGNOSTICS.items())
        ],
    }


if __name__ == "__main__":
    run_tune_orbit_example()

