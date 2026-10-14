"""HELIOS Phase 43: Quantum-Inspired Combinatorial Optimization for Linac Subsystems.

Implements Simulated Quantum Annealing (SQA) based on Path-Integral Monte Carlo (PIMC)
and transverse-field Ising formulations to solve hard combinatorial linac tuning problems
(discrete steerer polarities, integer collimator staging) without classical local-trap freezing.
"""

import math

import numpy as np
from pydantic import BaseModel, Field


class QuantumAnnealingConfig(BaseModel):
    """Configuration for Trotter-Suzuki Simulated Quantum Annealing."""
    num_spins: int = Field(..., ge=2, description="Number of discrete binary/spin variables")
    trotter_replicas: int = Field(default=8, ge=2, description="Number of quantum Trotter slices (P)")
    initial_temperature: float = Field(default=2.5, description="Initial thermal temperature")
    final_temperature: float = Field(default=0.05, description="Target low temperature")
    initial_gamma: float = Field(default=3.0, description="Initial transverse quantum tunneling field")
    final_gamma: float = Field(default=0.01, description="Final transverse field (ramped down)")
    sweeps: int = Field(default=200, ge=10, description="Number of Monte Carlo annealing sweeps")


class QuantumAnnealingResult(BaseModel):
    """Optimization outcome from simulated quantum annealing."""
    best_spin_configuration: list[int]
    best_energy: float
    total_sweeps: int
    trotter_slices: int
    tunneling_transitions: int
    convergence_speed_factor: float


class SimulatedQuantumAnnealer:
    """Trotter-Suzuki quantum path-integral Monte Carlo optimizer."""

    def __init__(self, config: QuantumAnnealingConfig):
        self.config = config

    def solve_ising(
        self,
        h_local_fields: np.ndarray,
        J_couplings: np.ndarray
    ) -> QuantumAnnealingResult:
        """Minimize Ising Hamiltonian H = sum(h_i * s_i) + sum(J_ij * s_i * s_j) where s_i in {-1, +1}."""
        N = self.config.num_spins
        P = self.config.trotter_replicas

        np.random.seed(42)
        # Initialize P replicas with random spins (+1, -1)
        # Shape: (P, N)
        spins = np.random.choice([-1, 1], size=(P, N))

        def compute_classical_energy(s_vector: np.ndarray) -> float:
            return float(np.sum(h_local_fields * s_vector) + 0.5 * (s_vector @ J_couplings @ s_vector))

        best_spins = spins[0].copy()
        best_energy = compute_classical_energy(best_spins)
        tunneling_count = 0

        for sweep in range(self.config.sweeps):
            # Linear annealing schedule for T and Gamma
            frac = sweep / max(1, self.config.sweeps - 1)
            T = self.config.initial_temperature * (1.0 - frac) + self.config.final_temperature * frac
            gamma = self.config.initial_gamma * (1.0 - frac) + self.config.final_gamma * frac

            # Coupling between neighboring Trotter replicas: J_perp = -1/2 * T * ln(tanh(gamma / (P*T)))
            arg = max(1e-6, min(1.0 - 1e-6, gamma / (P * max(1e-4, T))))
            j_perp = -0.5 * T * math.log(max(1e-8, math.tanh(arg)))

            # Metropolis sweep across all replicas and spins
            for p in range(P):
                p_next = (p + 1) % P
                p_prev = (p - 1) % P

                for i in range(N):
                    curr_s = spins[p, i]
                    # Local field from classical couplings
                    field_classical = h_local_fields[i] + np.sum(J_couplings[i, :] * spins[p, :]) - J_couplings[i, i] * curr_s
                    # Field from quantum neighbors
                    field_quantum = j_perp * (spins[p_next, i] + spins[p_prev, i])

                    # Energy delta if we flip s_i -> -s_i
                    dE_p = -2.0 * curr_s * (field_classical / P + field_quantum)

                    if dE_p < 0 or np.random.rand() < math.exp(-dE_p / max(1e-4, T)):
                        spins[p, i] = -curr_s
                        tunneling_count += 1

                # Check replica energy
                e_replica = compute_classical_energy(spins[p])
                if e_replica < best_energy:
                    best_energy = e_replica
                    best_spins = spins[p].copy()

        return QuantumAnnealingResult(
            best_spin_configuration=[int(x) for x in best_spins],
            best_energy=round(float(best_energy), 5),
            total_sweeps=self.config.sweeps,
            trotter_slices=P,
            tunneling_transitions=tunneling_count,
            convergence_speed_factor=round(float(tunneling_count / (self.config.sweeps * N * P)), 4)
        )
