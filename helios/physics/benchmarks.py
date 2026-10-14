"""HELIOS Automated Cross-Code Physics Benchmark Suite.

Runs comparative physics benchmarks evaluating beam trajectory, envelope bounds,
and numerical consistency between ANL TRACK, LBNL IMPACT-Z, and the Analytic Digital Twin.
"""

import logging
import time
from dataclasses import dataclass

from helios.physics.engine import (
    AnalyticDigitalTwinEngine,
    BeamDynamicsEngine,
    ImpactZSimulator,
    TrackSimulator,
)
from helios.physics.lattice import Lattice, create_baseline_mebt_lattice

logger = logging.getLogger(__name__)


@dataclass
class CodeBenchmarkResult:
    """Benchmark outcome for a specific simulation solver."""
    code_name: str
    execution_time_ms: float
    total_length_m: float
    final_sigma_x_mm: float
    final_sigma_y_mm: float
    max_sigma_x_mm: float
    max_sigma_y_mm: float
    points_count: int


@dataclass
class CrossCodeBenchmarkReport:
    """Comprehensive cross-code consistency report."""
    lattice_name: str
    benchmarks: dict[str, CodeBenchmarkResult]
    envelope_discrepancy_pct: float
    fastest_code: str
    consistency_passed: bool


class CrossCodeBenchmarkRunner:
    """Executes identical lattice models across simulation solvers and benchmarks consistency."""

    def __init__(self):
        self.analytic = AnalyticDigitalTwinEngine()
        self.track = TrackSimulator()
        self.impact = ImpactZSimulator()

    def run_benchmark(self, lattice: Lattice | None = None) -> CrossCodeBenchmarkReport:
        """Run full cross-code benchmark suite."""
        lat = lattice or create_baseline_mebt_lattice()
        results: dict[str, CodeBenchmarkResult] = {}

        codes: list[tuple[str, BeamDynamicsEngine]] = [
            ("AnalyticDigitalTwin", self.analytic),
            ("ANL_TRACK", self.track),
            ("LBNL_IMPACT_Z", self.impact),
        ]

        for name, engine in codes:
            t0 = time.perf_counter()
            traj = engine.run_simulation(lat)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            sig_x = [pt.sigma_x_mm for pt in traj]
            sig_y = [pt.sigma_y_mm for pt in traj]

            results[name] = CodeBenchmarkResult(
                code_name=name,
                execution_time_ms=elapsed_ms,
                total_length_m=traj[-1].s_m if traj else 0.0,
                final_sigma_x_mm=sig_x[-1] if sig_x else 0.0,
                final_sigma_y_mm=sig_y[-1] if sig_y else 0.0,
                max_sigma_x_mm=max(sig_x) if sig_x else 0.0,
                max_sigma_y_mm=max(sig_y) if sig_y else 0.0,
                points_count=len(traj),
            )

        # Cross-code envelope discrepancy
        ref_sig_x = results["AnalyticDigitalTwin"].final_sigma_x_mm
        sig_x_vals = [res.final_sigma_x_mm for res in results.values()]
        max_dev = max(abs(v - ref_sig_x) for v in sig_x_vals)
        discrepancy_pct = (max_dev / max(1e-4, ref_sig_x)) * 100.0

        fastest = min(results.items(), key=lambda item: item[1].execution_time_ms)[0]

        return CrossCodeBenchmarkReport(
            lattice_name=lat.name,
            benchmarks=results,
            envelope_discrepancy_pct=float(discrepancy_pct),
            fastest_code=fastest,
            consistency_passed=discrepancy_pct <= 25.0,
        )
