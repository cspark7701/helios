"""HELIOS Fast Physics Surrogate Model & Pre-Flight Verifier.

Implements high-speed surrogate evaluation for sub-second pre-flight
validation of proposed operational plans and setpoint batches.
"""


from helios.core.schemas import ValidationCheck, ValidationResult
from helios.physics.engine import AnalyticDigitalTwinEngine
from helios.physics.lattice import create_baseline_mebt_lattice


class FastPhysicsSurrogate:
    """Fast surrogate model for instantaneous beam parameter and loss prediction."""

    def __init__(self, max_allowed_loss_pct: float = 1.0, max_rms_envelope_mm: float = 8.0):
        self.max_allowed_loss_pct = max_allowed_loss_pct
        self.max_rms_envelope_mm = max_rms_envelope_mm
        self.digital_twin = AnalyticDigitalTwinEngine(create_baseline_mebt_lattice())

    def predict(self, setpoints: dict[str, float]) -> dict[str, float]:
        """Predict downstream beam metrics given candidate magnet/RF setpoints."""
        traj = self.digital_twin.run_simulation(setpoints=setpoints)
        if not traj:
            return {"loss_pct": 0.0, "max_sig_x_mm": 0.0, "max_sig_y_mm": 0.0}

        max_sig_x = max(p.sigma_x_mm for p in traj)
        max_sig_y = max(p.sigma_y_mm for p in traj)
        loss_pct = traj[-1].loss_fraction * 100.0

        return {
            "loss_pct": loss_pct,
            "max_sig_x_mm": max_sig_x,
            "max_sig_y_mm": max_sig_y,
            "exit_x_mm": traj[-1].x_mm,
            "exit_y_mm": traj[-1].y_mm,
        }

    def validate_plan_setpoints(
        self,
        setpoints: dict[str, float],
        agent_name: str = "HELIOS-Physics",
        required_backend: str | None = None,
    ) -> ValidationResult:
        """Execute pre-flight digital twin verification and generate ValidationResult."""
        pred = self.predict(setpoints)

        checks: list[ValidationCheck] = []
        errors: list[str] = []
        warnings: list[str] = []

        # Check 1: Beam Loss Tolerance
        loss_val = pred["loss_pct"]
        loss_passed = loss_val <= self.max_allowed_loss_pct
        checks.append(ValidationCheck(
            check_name="Projected Beam Loss",
            passed=loss_passed,
            measured_value=loss_val,
            limit_value=self.max_allowed_loss_pct,
            message=f"Projected loss {loss_val:.2f}% vs limit {self.max_allowed_loss_pct:.2f}%",
        ))
        if not loss_passed:
            errors.append(f"Projected beam loss ({loss_val:.2f}%) exceeds safety ceiling ({self.max_allowed_loss_pct}%)")

        # Check 2: Transverse Envelope Stay-Clear (Aperture)
        max_envelope = max(pred["max_sig_x_mm"], pred["max_sig_y_mm"])
        env_passed = max_envelope <= self.max_rms_envelope_mm
        checks.append(ValidationCheck(
            check_name="Transverse Envelope Stay-Clear",
            passed=env_passed,
            measured_value=max_envelope,
            limit_value=self.max_rms_envelope_mm,
            message=f"Peak envelope {max_envelope:.2f} mm vs limit {self.max_rms_envelope_mm:.2f} mm",
        ))
        if not env_passed:
            errors.append(f"Beam envelope ({max_envelope:.2f} mm) violates vacuum chamber aperture stay-clear")

        # Check 3: Backend Fidelity Check (R-06)
        fidelity_passed = True
        if required_backend and required_backend.lower() not in ("analytic", "surrogate"):
            fidelity_passed = False
            checks.append(ValidationCheck(
                check_name="Backend Fidelity Verification",
                passed=False,
                message=f"Required high-fidelity backend '{required_backend}' fell back to analytic model",
            ))
            errors.append(f"High-fidelity simulation verification failed: fell back from {required_backend}")

        is_valid = loss_passed and env_passed and fidelity_passed

        return ValidationResult(
            is_valid=is_valid,
            validator_agent=agent_name,
            checks=checks,
            projected_beam_loss=loss_val,
            provenance="analytic",
            warnings=warnings,
            errors=errors,
        )
