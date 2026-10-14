"""HELIOS Phase 35: Differentiable Beam Dynamics & Gradient-Based Inverse Lattice Solver.

Provides end-to-end PyTorch automatic differentiation through linear and non-linear
accelerator lattice elements, enabling analytical gradient backpropagation for
rapid parameter recovery and physics-informed inverse problem solving.
"""

try:
    import torch
    import torch.nn as nn
except ImportError as e:
    from helios._optional import OptionalDependencyError
    raise OptionalDependencyError("torch", extra="ml", feature="Differentiable beam dynamics") from e

from pydantic import BaseModel


class DifferentiableElement(nn.Module):
    """Base class for differentiable lattice elements."""
    def __init__(self, name: str, length: float):
        super().__init__()
        self.name = name
        self.length = nn.Parameter(torch.tensor(float(length), dtype=torch.float64), requires_grad=False)

    def forward(self, particles: torch.Tensor) -> torch.Tensor:
        """Propagate bunch tensor (N, 6) through element."""
        raise NotImplementedError


class DifferentiableDrift(DifferentiableElement):
    """Differentiable drift space."""
    def forward(self, particles: torch.Tensor) -> torch.Tensor:
        # particles: [x, x', y, y', z, delta]
        L = self.length
        out = particles.clone()
        out[:, 0] = particles[:, 0] + L * particles[:, 1]
        out[:, 2] = particles[:, 2] + L * particles[:, 3]
        return out


class DifferentiableQuadrupole(DifferentiableElement):
    """Differentiable quadrupole with gradient k1 as a learnable parameter."""
    def __init__(self, name: str, length: float, k1: float):
        super().__init__(name, length)
        self.k1 = nn.Parameter(torch.tensor(float(k1), dtype=torch.float64), requires_grad=True)

    def forward(self, particles: torch.Tensor) -> torch.Tensor:
        L = self.length
        k = self.k1
        out = particles.clone()

        # Handle focusing vs defocusing smoothly
        eps = 1e-12
        abs_k = torch.clamp(torch.abs(k), min=eps)
        sqrt_k = torch.sqrt(abs_k)
        phi = sqrt_k * L

        # x-plane focusing condition (k > 0: focus x, defocus y)
        is_focus = k >= 0.0

        if is_focus:
            cx = torch.cos(phi)
            sx = torch.sin(phi) / sqrt_k
            dx = -sqrt_k * torch.sin(phi)
            cy = torch.cosh(phi)
            sy = torch.sinh(phi) / sqrt_k
            dy = sqrt_k * torch.sinh(phi)
        else:
            cx = torch.cosh(phi)
            sx = torch.sinh(phi) / sqrt_k
            dx = sqrt_k * torch.sinh(phi)
            cy = torch.cos(phi)
            sy = torch.sin(phi) / sqrt_k
            dy = -sqrt_k * torch.sin(phi)

        out[:, 0] = cx * particles[:, 0] + sx * particles[:, 1]
        out[:, 1] = dx * particles[:, 0] + cx * particles[:, 1]
        out[:, 2] = cy * particles[:, 2] + sy * particles[:, 3]
        out[:, 3] = dy * particles[:, 2] + cy * particles[:, 3]
        return out


class DifferentiableRFCavity(DifferentiableElement):
    """Differentiable thin RF cavity buncher/accelerator gap."""
    def __init__(self, name: str, length: float, voltage_MV: float, phase_rad: float, frequency_MHz: float = 162.5):
        super().__init__(name, length)
        self.voltage_MV = nn.Parameter(torch.tensor(float(voltage_MV), dtype=torch.float64), requires_grad=True)
        self.phase_rad = nn.Parameter(torch.tensor(float(phase_rad), dtype=torch.float64), requires_grad=True)
        self.omega = 2.0 * 3.141592653589793 * (frequency_MHz * 1e6)

    def forward(self, particles: torch.Tensor) -> torch.Tensor:
        out = particles.clone()
        # Thin cavity longitudinal kick: delta -> delta + (q*V / E0) * sin(phi + k_rf * z)
        # Transverse defocusing kick: x' -> x' - (q*V*omega / (2*c*p*v)) * sin(phi) * x
        scale = self.voltage_MV * 0.01  # normalized coupling factor
        d_phase = self.phase_rad

        out[:, 5] = particles[:, 5] + scale * torch.cos(d_phase)
        out[:, 1] = particles[:, 1] - scale * 0.05 * torch.sin(d_phase) * particles[:, 0]
        out[:, 3] = particles[:, 3] - scale * 0.05 * torch.sin(d_phase) * particles[:, 2]
        return out


class DifferentiableLattice(nn.Module):
    """Complete differentiable beamline lattice."""
    def __init__(self, elements: list[DifferentiableElement]):
        super().__init__()
        self.elements = nn.ModuleList(elements)

    def track(self, particles: torch.Tensor) -> torch.Tensor:
        """Track particle bunch through all elements sequentially."""
        state = particles
        for elem in self.elements:
            state = elem(state)
        return state

    def get_tunable_parameters(self) -> dict[str, torch.Tensor]:
        """Return dict of all learnable parameters with their element names."""
        params = {}
        for elem in self.elements:
            for pname, param in elem.named_parameters():
                if param.requires_grad:
                    params[f"{elem.name}.{pname}"] = param
        return params


class InverseSolverResult(BaseModel):
    """Results from gradient-based inverse lattice optimization."""
    converged: bool
    iterations: int
    final_loss: float
    recovered_parameters: dict[str, float]
    parameter_errors: dict[str, float]


class InverseLatticeSolver:
    """Solves parameter identification / calibration via analytical gradient backprop."""

    def __init__(self, lattice: DifferentiableLattice, lr: float = 0.05, max_iter: int = 100):
        self.lattice = lattice
        self.lr = lr
        self.max_iter = max_iter

    def solve(
        self,
        initial_bunch: torch.Tensor,
        target_bunch: torch.Tensor,
        ground_truth: dict[str, float] | None = None,
        loss_tolerance: float = 1e-6
    ) -> InverseSolverResult:
        """Recover perturbed lattice parameters matching target bunch measurements."""
        optimizer = torch.optim.Adam(
            [p for p in self.lattice.parameters() if p.requires_grad],
            lr=self.lr
        )

        converged = False
        final_loss = float("inf")
        iter_count = 0

        for it in range(self.max_iter):
            iter_count = it + 1
            optimizer.zero_grad()
            pred_bunch = self.lattice.track(initial_bunch)
            
            # Relative mean squared error normalized by target bunch variance
            denom = torch.mean(target_bunch ** 2) + 1e-12
            loss = torch.mean((pred_bunch - target_bunch) ** 2) / denom
            loss.backward()
            optimizer.step()

            final_loss = float(loss.item())
            if final_loss < loss_tolerance:
                converged = True
                break

        recovered = {k: float(v.detach().item()) for k, v in self.lattice.get_tunable_parameters().items()}
        errors = {}
        if ground_truth:
            for k, val in recovered.items():
                if k in ground_truth:
                    errors[k] = abs(val - ground_truth[k])

        return InverseSolverResult(
            converged=converged,
            iterations=iter_count,
            final_loss=final_loss,
            recovered_parameters=recovered,
            parameter_errors=errors
        )
