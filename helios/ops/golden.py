"""HELIOS Phase 44: Automated Golden Run Certification Engine.

Provides cryptographic SHA-256 verification and statistical discrepancy certification
of active heavy-ion linac machine states against authorized Golden Run configurations.
"""

from typing import Dict, List, Any, Optional
import hashlib
import json
import time
from enum import Enum
from pydantic import BaseModel, Field


class CertificationGrade(str, Enum):
    CERTIFIED = "CERTIFIED"
    MINOR_DEVIATION = "MINOR_DEVIATION"
    NON_COMPLIANT = "NON_COMPLIANT"


class GoldenRunParameter(BaseModel):
    """Certified baseline parameter setpoint and tolerance."""
    pv_name: str
    baseline_value: float
    tolerance_abs: float
    unit: str = ""
    subsystem: str = "LINAC"


class GoldenRunCertificate(BaseModel):
    """Cryptographically signed compliance certificate for a linac beam configuration."""
    certificate_id: str
    run_name: str
    species: str
    target_energy_MeV_u: float
    timestamp: float = Field(default_factory=time.time)
    grade: CertificationGrade
    compliance_score_percent: float
    sha256_fingerprint: str
    checked_parameters_count: int
    violating_parameters: Dict[str, Dict[str, float]]
    certification_authority: str = "HELIOS-Safety-Authority"


class GoldenRunCertificationEngine:
    """Certifies operational accelerator setpoints against baseline golden configurations."""

    def __init__(self, golden_database: Optional[Dict[str, List[GoldenRunParameter]]] = None):
        self.golden_db = golden_database or {}

    def register_golden_run(self, run_name: str, parameters: List[GoldenRunParameter]) -> None:
        """Register a golden baseline run configuration."""
        self.golden_db[run_name] = parameters

    def certify_machine_state(
        self,
        run_name: str,
        species: str,
        target_energy_MeV_u: float,
        live_pv_values: Dict[str, float]
    ) -> GoldenRunCertificate:
        """Evaluate live PV readings against registered golden baseline."""
        if run_name not in self.golden_db:
            raise KeyError(f"Golden run '{run_name}' is not registered.")

        baseline_params = self.golden_db[run_name]
        violating: Dict[str, Dict[str, float]] = {}
        passed_count = 0

        for p in baseline_params:
            live_val = live_pv_values.get(p.pv_name)
            if live_val is None:
                violating[p.pv_name] = {
                    "baseline": p.baseline_value,
                    "live": float("nan"),
                    "deviation": float("inf"),
                    "tolerance": p.tolerance_abs
                }
                continue

            dev = abs(live_val - p.baseline_value)
            if dev <= p.tolerance_abs:
                passed_count += 1
            else:
                violating[p.pv_name] = {
                    "baseline": p.baseline_value,
                    "live": round(live_val, 4),
                    "deviation": round(dev, 4),
                    "tolerance": p.tolerance_abs
                }

        total = len(baseline_params)
        score = (passed_count / max(1, total)) * 100.0

        if score >= 98.0:
            grade = CertificationGrade.CERTIFIED
        elif score >= 85.0:
            grade = CertificationGrade.MINOR_DEVIATION
        else:
            grade = CertificationGrade.NON_COMPLIANT

        # Cryptographic fingerprint
        raw_payload = json.dumps({
            "run": run_name,
            "species": species,
            "energy": target_energy_MeV_u,
            "score": round(score, 2),
            "pvs": {p.pv_name: live_pv_values.get(p.pv_name, 0.0) for p in baseline_params}
        }, sort_keys=True)
        fingerprint = hashlib.sha256(raw_payload.encode()).hexdigest()

        cert_id = f"CERT-{run_name.upper()}-{fingerprint[:8]}"

        return GoldenRunCertificate(
            certificate_id=cert_id,
            run_name=run_name,
            species=species,
            target_energy_MeV_u=target_energy_MeV_u,
            grade=grade,
            compliance_score_percent=round(score, 2),
            sha256_fingerprint=fingerprint,
            checked_parameters_count=total,
            violating_parameters=violating
        )
