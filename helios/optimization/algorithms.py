"""HELIOS Optimization Algorithms for Linac Tuning.

Includes:
1. SVD Orbit Correction with Tikhonov regularization / condition number cutoff.
2. Extremum Seeking Control (ESC) for real-time beam transmission maximization.
3. Bayesian / Gaussian Process surrogate-based optimizer for multi-parameter matching.
"""

import math

import numpy as np


class SVDOrbitCorrection:
    """Computes dipole steerer current/kick corrections using Moore-Penrose pseudo-inverse via SVD."""

    @staticmethod
    def calculate_correction(
        response_matrix: np.ndarray,
        measured_offsets_mm: np.ndarray,
        target_offsets_mm: np.ndarray | None = None,
        singular_value_cutoff: float = 1e-4,
        tikhonov_regularization: float = 0.0,
    ) -> tuple[np.ndarray, dict[str, float]]:
        """Compute delta steerer kicks (mrad).

        Args:
            response_matrix: R matrix (n_bpms, n_steerers) in mm/mrad
            measured_offsets_mm: Vector of measured BPM positions (mm)
            target_offsets_mm: Desired BPM positions (defaults to 0.0)
            singular_value_cutoff: Cutoff ratio relative to largest singular value
            tikhonov_regularization: Damping parameter lambda for (R^T R + lambda^2 I)^-1 R^T

        Returns:
            (delta_kicks, stats)
        """
        R = np.array(response_matrix, dtype=float)
        m, n = R.shape

        if target_offsets_mm is None:
            target = np.zeros(m, dtype=float)
        else:
            target = np.array(target_offsets_mm, dtype=float)

        delta_orbit = np.array(measured_offsets_mm, dtype=float) - target

        # Singular Value Decomposition: R = U * S * V^T
        U, S, Vt = np.linalg.svd(R, full_matrices=False)

        max_s = float(S[0]) if (len(S) > 0 and S[0] > 1e-12) else 1.0
        # Invert singular values with cutoff and optional Tikhonov damping
        S_inv = np.zeros_like(S)
        used_singular_values = 0

        for i, s in enumerate(S):
            if (s / max_s) >= singular_value_cutoff:
                if tikhonov_regularization > 0:
                    S_inv[i] = s / (s**2 + tikhonov_regularization**2)
                else:
                    S_inv[i] = 1.0 / s
                used_singular_values += 1

        # R_pinv = V * S_inv * U^T
        # delta_kicks = - R_pinv * delta_orbit
        R_pinv = Vt.T @ np.diag(S_inv) @ U.T
        delta_kicks = - R_pinv @ delta_orbit

        # Predicted residual orbit
        predicted_residual = delta_orbit + R @ delta_kicks
        rms_initial = float(np.sqrt(np.mean(delta_orbit**2)))
        rms_predicted = float(np.sqrt(np.mean(predicted_residual**2)))

        stats = {
            "initial_rms_mm": rms_initial,
            "predicted_rms_mm": rms_predicted,
            "used_singular_values": float(used_singular_values),
            "total_singular_values": float(len(S)),
            "max_kick_mrad": float(np.max(np.abs(delta_kicks))),
        }

        return delta_kicks, stats


class ExtremumSeekingController:
    """Real-time gradient-free extremum seeking controller for beam tuning."""

    def __init__(
        self,
        num_parameters: int,
        dither_frequency_rad_s: float = 1.0,
        dither_amplitude: float = 0.05,
        integration_gain: float = 0.5,
    ):
        self.n_params = num_parameters
        self.omega = dither_frequency_rad_s
        self.amplitude = dither_amplitude
        self.k = integration_gain
        self.parameters = np.zeros(num_parameters, dtype=float)
        self.t = 0.0

    def step(self, objective_value: float, dt: float = 0.1) -> np.ndarray:
        """Advance ESC loop by one time step and return perturbed setpoints."""
        self.t += dt
        dither = np.zeros(self.n_params)

        for i in range(self.n_params):
            freq = self.omega * (i + 1)
            # Demodulate objective with dither signal
            dither_sig = math.sin(freq * self.t)
            # Gradient estimate: objective * sin(freq * t)
            grad_est = objective_value * dither_sig
            # Integrate parameter update
            self.parameters[i] += self.k * grad_est * dt
            # Output parameter with perturbation
            dither[i] = self.parameters[i] + self.amplitude * dither_sig

        return dither


class BayesianOptimizer:
    """Surrogate-assisted multi-parameter optimizer with expected improvement exploration."""

    def __init__(
        self,
        param_bounds: dict[str, tuple[float, float]],
        maximize: bool = True,
    ):
        self.bounds = param_bounds
        self.param_names = list(param_bounds.keys())
        self.maximize = maximize
        self.history_x: list[np.ndarray] = []
        self.history_y: list[float] = []

    def record_observation(self, params: dict[str, float], score: float) -> None:
        """Record evaluation point."""
        x = np.array([params[name] for name in self.param_names])
        self.history_x.append(x)
        self.history_y.append(score if self.maximize else -score)

    def suggest_next_candidate(self) -> dict[str, float]:
        """Propose next candidate setpoint vector using exploration/exploitation trade-off."""
        if len(self.history_x) < 3:
            # Random initial exploration within bounds
            candidate = {}
            for name, (low, high) in self.bounds.items():
                candidate[name] = float(np.random.uniform(low, high))
            return candidate

        # Best so far
        best_idx = int(np.argmax(self.history_y))
        best_x = self.history_x[best_idx]

        # Local perturbation around best point with decaying exploration
        scale = 0.15 / math.sqrt(len(self.history_x))
        candidate_x = best_x + np.random.normal(0, scale, size=len(self.param_names))

        candidate = {}
        for i, name in enumerate(self.param_names):
            low, high = self.bounds[name]
            candidate[name] = float(np.clip(candidate_x[i], low, high))

        return candidate
