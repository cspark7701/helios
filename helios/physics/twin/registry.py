"""Dynamic entry-point registry and fallback mechanisms for FacilityTwin plugins."""

import importlib.metadata
import logging
from collections.abc import Mapping
from typing import Any

import numpy as np

from helios.physics.engine import AnalyticDigitalTwinEngine
from helios.physics.lattice import create_baseline_mebt_lattice
from helios.physics.twin.protocol import FacilityPlugin, FacilityTwin, TwinDomain

logger = logging.getLogger(__name__)


class MockSurrogate:
    """Zero-dependency deterministic mock surrogate for public CI and testing."""

    def __init__(self, control_names: list[str], diagnostic_names: list[str]):
        self.control_names = control_names
        self.diagnostic_names = diagnostic_names
        # Response matrix: diagnostic_dim x control_dim
        n_diag = len(diagnostic_names)
        n_ctrl = len(control_names)
        self.R = np.zeros((n_diag, n_ctrl), dtype=np.float32)
        for i in range(n_diag):
            for j in range(n_ctrl):
                if i >= j:
                    self.R[i, j] = 0.15 * (i - j + 1)

    def predict(self, controls: Mapping[str, float] | np.ndarray) -> dict[str, float]:
        if isinstance(controls, dict):
            u = np.array([float(controls.get(k, 0.0)) for k in self.control_names], dtype=np.float32)
        else:
            u = np.array(controls, dtype=np.float32)

        y = self.R @ u
        return {self.diagnostic_names[i]: float(y[i]) for i in range(len(self.diagnostic_names))}

    def predict_tensor(self, x: Any) -> Any:
        try:
            import torch
            R_tensor = torch.tensor(self.R, dtype=torch.float32, device=x.device)
            return torch.matmul(x, R_tensor.t())
        except ImportError:
            return x


class MockFacilityPlugin:
    """Built-in mock facility plugin enabling full CI without proprietary plugins."""

    def available_sections(self) -> list[str]:
        return ["LEBT", "MEBT"]

    def load_twin(self, section: str) -> FacilityTwin:
        sec = section.upper()
        if sec == "LEBT":
            ctrls = ["STM_1", "STM_2", "STM_3", "STM_4", "STM_5"]
            diags = ["WS_1:x_mm", "WS_2:x_mm", "WS_3:x_mm", "WS_4:x_mm", "BPM_EXIT:x_mm"]
            lower = {c: -10.0 for c in ctrls}
            upper = {c: 10.0 for c in ctrls}
        else:
            ctrls = ["MEBT:DCH:01", "MEBT:DCV:01", "MEBT:DCH:02", "MEBT:DCV:02"]
            diags = ["BPM01:x_mm", "BPM01:y_mm", "BPM02:x_mm", "BPM02:y_mm"]
            lower = {c: -5.0 for c in ctrls}
            upper = {c: 5.0 for c in ctrls}

        surrogate = MockSurrogate(ctrls, diags)
        domain = TwinDomain(names=ctrls, lower=lower, upper=upper)
        return FacilityTwin(
            facility="MOCK",
            section=sec,
            surrogate=surrogate,
            control_names=ctrls,
            control_units={c: "A" for c in ctrls},
            diagnostic_names=diags,
            domain=domain,
            provenance={"type": "mock_synthetic", "version": "1.0.0"},
        )

    def to_actuator_commands(self, section: str, controls: Mapping[str, float]) -> dict[str, Any]:
        return {f"{k}:CurrentSet": v for k, v in controls.items()}

    def make_env(self, section: str, **kwargs: Any) -> Any:
        from helios.physics.twin.env import LinacSurrogateGymEnv
        twin = self.load_twin(section)
        return LinacSurrogateGymEnv(twin=twin, **kwargs)


class AnalyticTwinFallbackPlugin:
    """Wraps AnalyticDigitalTwinEngine as a fallback twin plugin."""

    def __init__(self) -> None:
        self.engine = AnalyticDigitalTwinEngine()
        self.lattice = create_baseline_mebt_lattice()

    def available_sections(self) -> list[str]:
        return ["MEBT"]

    def load_twin(self, section: str) -> FacilityTwin:
        ctrls = ["MEBT:DCH:01", "MEBT:DCV:01", "MEBT:DCH:02", "MEBT:DCV:02"]
        diags = ["BPM01:x_mm", "BPM01:y_mm", "BPM02:x_mm", "BPM02:y_mm"]
        lower = {c: -5.0 for c in ctrls}
        upper = {c: 5.0 for c in ctrls}

        class AnalyticSurrogateWrapper:
            def __init__(self, engine: AnalyticDigitalTwinEngine, lattice: Any):
                self.engine = engine
                self.lattice = lattice

            def predict(self, controls: Mapping[str, float] | np.ndarray) -> dict[str, float]:
                pts = self.engine.run_simulation(self.lattice)
                res: dict[str, float] = {}
                for i, p in enumerate(pts[:4]):
                    res[f"BPM{i+1:02d}:x_mm"] = p.x_mm
                    res[f"BPM{i+1:02d}:y_mm"] = p.y_mm
                return res

            def predict_tensor(self, x: Any) -> Any:
                return x

        surrogate = AnalyticSurrogateWrapper(self.engine, self.lattice)
        domain = TwinDomain(names=ctrls, lower=lower, upper=upper)
        return FacilityTwin(
            facility="ANALYTIC",
            section="MEBT",
            surrogate=surrogate,
            control_names=ctrls,
            control_units={c: "A" for c in ctrls},
            diagnostic_names=diags,
            domain=domain,
            provenance={"type": "analytic_fallback", "version": "1.0.0"},
        )

    def to_actuator_commands(self, section: str, controls: Mapping[str, float]) -> dict[str, Any]:
        return {f"{k}:CurrentSet": v for k, v in controls.items()}

    def make_env(self, section: str, **kwargs: Any) -> Any:
        from helios.physics.twin.env import LinacSurrogateGymEnv
        twin = self.load_twin(section)
        return LinacSurrogateGymEnv(twin=twin, **kwargs)


def discover_facility_plugins() -> dict[str, FacilityPlugin]:
    """Discover registered facility plugins via entry points with safe fallback."""
    plugins: dict[str, FacilityPlugin] = {
        "mock": MockFacilityPlugin(),
        "analytic": AnalyticTwinFallbackPlugin(),
    }

    try:
        eps = importlib.metadata.entry_points(group="helios.facilities")
        for ep in eps:
            try:
                plugin_cls = ep.load()
                plugins[ep.name] = plugin_cls()
                logger.info(f"Loaded facility plugin: '{ep.name}'")
            except Exception as e:
                logger.warning(f"Could not load facility plugin '{ep.name}': {e}")
    except Exception as e:
        logger.debug(f"Entry-point discovery error: {e}")

    return plugins


def get_facility_twin(facility: str = "mock", section: str = "MEBT") -> FacilityTwin:
    """Retrieve a FacilityTwin instance by facility name and section."""
    plugins = discover_facility_plugins()
    target_fac = facility.lower()
    if target_fac in plugins:
        plugin = plugins[target_fac]
        if section.upper() in [s.upper() for s in plugin.available_sections()]:
            return plugin.load_twin(section)

    # Fallback to mock or analytic
    if "mock" in plugins and section.upper() in plugins["mock"].available_sections():
        return plugins["mock"].load_twin(section)
    return plugins["analytic"].load_twin("MEBT")
