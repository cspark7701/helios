"""Pre-flight simulation verification and aperture safety guards powered by FacilityTwin."""

from collections.abc import Mapping
from datetime import datetime, timezone

import numpy as np

from helios.core.schemas import ValidationCheck, ValidationResult
from helios.physics.twin.protocol import FacilityTwin


class TwinPreFlightVerifier:
    """Evaluates proposed setpoint batches against digital twin physics & OOD limits."""

    def __init__(
        self,
        twin: FacilityTwin,
        max_centroid_orbit_mm: float = 1.0,
        aperture_limit_mm: float = 15.0,
    ):
        self.twin = twin
        self.max_centroid_orbit_mm = max_centroid_orbit_mm
        self.aperture_limit_mm = aperture_limit_mm

    def validate_plan_setpoints(self, setpoints: Mapping[str, float]) -> ValidationResult:
        """Execute sub-2ms pre-flight simulation verification."""
        checks: list[ValidationCheck] = []
        errors: list[str] = []
        warnings: list[str] = []

        # 1. Out-of-Domain (OOD) training envelope check
        ood_violations = self.twin.domain.out_of_domain(setpoints)
        if ood_violations:
            msg = f"Candidate setpoints outside twin verified domain: {', '.join(ood_violations)}"
            errors.append(msg)
            checks.append(ValidationCheck(check_name="Twin Domain Envelope", passed=False, message=msg))
        else:
            checks.append(ValidationCheck(
                check_name="Twin Domain Envelope",
                passed=True,
                message=f"All {len(setpoints)} setpoints lie inside twin verified bounds",
            ))

        # 2. Fast forward surrogate prediction
        prediction = self.twin.predict(setpoints)

        # 3. Evaluate predicted centroid orbit
        orbit_vals = [abs(v) for k, v in prediction.items() if "mm" in k or "x" in k.lower() or "y" in k.lower()]
        max_orbit = max(orbit_vals) if orbit_vals else 0.0

        orbit_passed = max_orbit <= self.max_centroid_orbit_mm
        checks.append(ValidationCheck(
            check_name="Centroid Stay-Clear",
            passed=orbit_passed,
            measured_value=round(max_orbit, 4),
            limit_value=self.max_centroid_orbit_mm,
            message=f"Max predicted centroid offset {max_orbit:.3f} mm (limit: {self.max_centroid_orbit_mm} mm)",
        ))
        if not orbit_passed:
            errors.append(f"Predicted centroid orbit {max_orbit:.3f} mm exceeds tolerance {self.max_centroid_orbit_mm} mm")

        # 4. Projected loss estimation
        projected_loss = 0.0
        if max_orbit > self.aperture_limit_mm * 0.8:
            projected_loss = float(np.clip((max_orbit - self.aperture_limit_mm * 0.8) * 10.0, 0.0, 100.0))
            warnings.append(f"Beam envelope approaches vacuum chamber aperture ({max_orbit:.2f} mm)")

        is_valid = len(errors) == 0

        return ValidationResult(
            is_valid=is_valid,
            validator_agent="HELIOS-TwinVerifier",
            timestamp=datetime.now(timezone.utc),
            checks=checks,
            projected_beam_loss=round(projected_loss, 3),
            provenance="twin",
            warnings=warnings,
            errors=errors,
        )
