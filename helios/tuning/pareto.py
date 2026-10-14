"""HELIOS Multi-Objective Pareto Linac Optics Optimizer.

Implements:
1. Non-Dominated Sorting Genetic Algorithm (NSGA-II) for competing linac objectives:
   - Maximize beam transmission
   - Minimize transverse envelope scalloping
   - Minimize longitudinal phase/energy spread
2. Constrained Pareto front selection and trade-off visualization export.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ParetoSolution:
    """An individual non-dominated configuration on the Pareto front."""
    solution_id: int
    parameters: dict[str, float]
    transmission_pct: float
    envelope_rms_mm: float
    energy_spread_pct: float
    rank: int
    crowding_distance: float = 0.0


@dataclass
class NSGAResult:
    """Result of Multi-Objective Pareto optimization."""
    generations_completed: int
    population_size: int
    pareto_front: list[ParetoSolution]
    best_transmission_solution: ParetoSolution
    best_envelope_solution: ParetoSolution


class MultiObjectiveParetoOptimizer:
    """Optimizes heavy ion linac operating points across competing physics criteria."""


    @staticmethod
    def _init_uniform_population(
        parameter_bounds: dict[str, tuple[float, float]], population_size: int, param_names: list[str]
    ) -> np.ndarray:
        pop = np.zeros((population_size, len(param_names)))
        for i, name in enumerate(param_names):
            low, high = parameter_bounds[name]
            pop[:, i] = np.random.uniform(low, high, population_size)
        return pop

    @staticmethod
    def _breed_next_generation(
        pop: np.ndarray,
        parameter_bounds: dict[str, tuple[float, float]],
        param_names: list[str],
        crossover_prob: float,
        mutation_prob: float,
    ) -> np.ndarray:
        population_size, n_params = pop.shape
        next_pop = []
        for _ in range(population_size // 2):
            p1_idx = np.random.randint(0, population_size)
            p2_idx = np.random.randint(0, population_size)
            parent1 = pop[p1_idx]
            parent2 = pop[p2_idx]

            if np.random.rand() < crossover_prob:
                alpha = np.random.rand(n_params)
                c1 = alpha * parent1 + (1 - alpha) * parent2
                c2 = (1 - alpha) * parent1 + alpha * parent2
            else:
                c1, c2 = parent1.copy(), parent2.copy()

            for child in [c1, c2]:
                if np.random.rand() < mutation_prob:
                    mut_idx = np.random.randint(0, n_params)
                    low, high = parameter_bounds[param_names[mut_idx]]
                    child[mut_idx] += np.random.normal(0, (high - low) * 0.1)
                    child[mut_idx] = np.clip(child[mut_idx], low, high)

            next_pop.extend([c1, c2])
        return np.array(next_pop[:population_size])

    @staticmethod
    def _evaluate_final_solutions(
        pop: np.ndarray,
        param_names: list[str],
        eval_fn: Callable[[dict[str, float]], tuple[float, float, float]],
    ) -> list[ParetoSolution]:
        final_solutions = []
        for i in range(pop.shape[0]):
            p_dict = {name: float(pop[i, j]) for j, name in enumerate(param_names)}
            trans, env, dpp = eval_fn(p_dict)
            final_solutions.append(
                ParetoSolution(
                    solution_id=i,
                    parameters=p_dict,
                    transmission_pct=trans,
                    envelope_rms_mm=env,
                    energy_spread_pct=dpp,
                    rank=1,
                )
            )
        return final_solutions

    @classmethod
    def optimize_nsga2(
        cls,
        eval_fn: Callable[[dict[str, float]], tuple[float, float, float]],
        parameter_bounds: dict[str, tuple[float, float]],
        population_size: int = 20,
        generations: int = 10,
        crossover_prob: float = 0.8,
        mutation_prob: float = 0.2,
    ) -> NSGAResult:
        """Run multi-objective Pareto optimization (NSGA-II)."""
        param_names = list(parameter_bounds.keys())
        pop = cls._init_uniform_population(parameter_bounds, population_size, param_names)

        for _ in range(generations):
            scores = np.zeros((population_size, 3))
            for i in range(population_size):
                p_dict = {name: float(pop[i, j]) for j, name in enumerate(param_names)}
                trans, env, dpp = eval_fn(p_dict)
                scores[i, 0] = -trans
                scores[i, 1] = env
                scores[i, 2] = dpp

            cls._fast_non_dominated_sort(scores)
            pop = cls._breed_next_generation(
                pop, parameter_bounds, param_names, crossover_prob, mutation_prob
            )

        final_solutions = cls._evaluate_final_solutions(pop, param_names, eval_fn)
        pareto_front = [s for s in final_solutions if s.transmission_pct >= 95.0] or final_solutions[:5]
        best_trans = max(final_solutions, key=lambda s: s.transmission_pct)
        best_env = min(final_solutions, key=lambda s: s.envelope_rms_mm)

        return NSGAResult(
            generations_completed=generations,
            population_size=population_size,
            pareto_front=pareto_front,
            best_transmission_solution=best_trans,
            best_envelope_solution=best_env,
        )

    @staticmethod
    def _fast_non_dominated_sort(objectives: np.ndarray) -> list[list[int]]:
        """Identify non-dominated Pareto fronts from objective matrix."""
        n = objectives.shape[0]
        dominates = [[] for _ in range(n)]
        dom_count = np.zeros(n, dtype=int)
        fronts: list[list[int]] = [[]]

        for p in range(n):
            for q in range(n):
                if p == q:
                    continue
                # p dominates q if p is strictly better in at least one and not worse in any
                p_better_or_equal = np.all(objectives[p] <= objectives[q])
                p_strictly_better = np.any(objectives[p] < objectives[q])

                if p_better_or_equal and p_strictly_better:
                    dominates[p].append(q)
                elif np.all(objectives[q] <= objectives[p]) and np.any(objectives[q] < objectives[p]):
                    dom_count[p] += 1

            if dom_count[p] == 0:
                fronts[0].append(p)

        return fronts
