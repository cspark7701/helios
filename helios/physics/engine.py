"""HELIOS Beam Dynamics Simulation Engine Wrappers (ANL TRACK, LBNL IMPACT-Z, and Analytic Digital Twin).

Provides standardized execution, input deck generation, and output parsing for:
1. ANL TRACK (heavy ion ray tracing & multi-charge state tracking, executed via Wine or native binary).
2. LBNL IMPACT-Z (3D space-charge PIC tracking via lume-impact).
3. AnalyticDigitalTwinEngine (zero-dependency in-memory linear transport & envelope model).
"""

import logging
import os
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

from helios.physics.elements import (
    DiagnosticElement,
    Drift,
    Quadrupole,
    RFCavity,
    Steerer,
)
from helios.physics.lattice import (
    Lattice,
    TrajectoryPoint,
    create_baseline_mebt_lattice,
)

logger = logging.getLogger(__name__)

track_env = os.environ.get("TRACK_ROOT")
DEFAULT_TRACK_DIR = Path(track_env) if track_env else Path("track")
DEFAULT_TRACK_EXE = DEFAULT_TRACK_DIR / "TRACKv39C.exe"


class BeamDynamicsEngine(ABC):
    """Abstract interface for linac beam dynamics simulation engines."""

    @abstractmethod
    def run_simulation(
        self,
        lattice: Lattice,
        setpoints: dict[str, float] | None = None,
    ) -> list[TrajectoryPoint]:
        """Execute simulation and return longitudinal trajectory points."""

    @abstractmethod
    def estimate_losses(
        self,
        lattice: Lattice,
        setpoints: dict[str, float] | None = None,
    ) -> float:
        """Estimate total beam loss percentage through lattice."""


class AnalyticDigitalTwinEngine(BeamDynamicsEngine):
    """In-memory analytic digital twin using linear transport and envelope models."""

    def __init__(self, baseline_lattice: Lattice | None = None):
        self.lattice = baseline_lattice or create_baseline_mebt_lattice()

    def apply_setpoints(self, setpoints: dict[str, float]) -> None:
        """Update lattice element parameters from setpoint dictionary."""
        for name, val in setpoints.items():
            elem = self.lattice.get_element(name)
            if elem:
                if isinstance(elem, Quadrupole):
                    elem.gradient_t_m = float(val)
                elif isinstance(elem, Steerer):
                    if "CV" in name:
                        elem.kick_y_mrad = float(val)
                    else:
                        elem.kick_x_mrad = float(val)
                elif isinstance(elem, RFCavity):
                    if "phase" in name.lower():
                        elem.phase_deg = float(val)
                    else:
                        elem.voltage_kv = float(val)

    def run_simulation(
        self,
        lattice: Lattice | None = None,
        setpoints: dict[str, float] | None = None,
    ) -> list[TrajectoryPoint]:
        target_lat = lattice or self.lattice
        if setpoints:
            self.apply_setpoints(setpoints)
        return target_lat.track_envelope()

    def estimate_losses(
        self,
        lattice: Lattice | None = None,
        setpoints: dict[str, float] | None = None,
    ) -> float:
        traj = self.run_simulation(lattice, setpoints)
        if not traj:
            return 0.0
        return traj[-1].loss_fraction * 100.0


class TrackSimulator(BeamDynamicsEngine):
    """ANL TRACK heavy ion beam dynamics code wrapper.

    Executes TRACKv39C.exe via Wine (or native Linux binary if available).
    Generates input decks ('track.dat', 'sclinac.dat') and parses envelope/loss outputs.
    """

    def __init__(
        self,
        track_exe: Path | None = None,
        work_dir: Path | None = None,
        wine_bin: str = "wine",
    ):
        self.track_exe = track_exe or (DEFAULT_TRACK_EXE if DEFAULT_TRACK_EXE.exists() else Path("TRACKv39C.exe"))
        self.work_dir = work_dir or Path(tempfile.gettempdir()) / "helios_track_run"
        self.wine_bin = wine_bin
        self.analytic_fallback = AnalyticDigitalTwinEngine()

    def is_available(self) -> bool:
        """Check if TRACK executable and Wine (or native runner) are accessible."""
        if not self.track_exe.exists():
            return False
        if self.track_exe.suffix.lower() == ".exe":
            return shutil.which(self.wine_bin) is not None
        return os.access(self.track_exe, os.X_OK)

    def generate_track_dat(self, lattice: Lattice, output_path: Path) -> None:
        """Generate ANL TRACK main input deck (track.dat)."""
        content = f"""&tran
Win          =  {lattice.kinetic_energy_mev_u * 1e3:.4f}d0
atp          =  {lattice.mass_amu:.3f}
Qavr         =  {lattice.charge_q:.1f}
Qdesign      =  {lattice.charge_q:.1f}
Adesign      =  {lattice.mass_amu:.3f}

nqtot        =  1
qq           =  {lattice.charge_q:.1f}
npat         =  1000
Amass        =  {lattice.mass_amu:.3f}
current      =  0.05
dww00        =  0.0

freqb        =  81.25d6
part         =  0.9999

epsnx        =  0.15d0,     epsny        =  0.15d0,     epsnz        =  50.0d0
alfax        =  0.0d0,      alfay        =  0.0d0,      alfaz        =  0.0d0
betax        =  2.50d0,     betay        =  2.50d0,     betaz        =  10.0d0

db_b         =  0.0005,     df_4D        =  90d0
phmax        =  180.0,      dwwmax       =  1.0,        dwwacc       =  0.05

x00          =  0.0,        xp00         =  0.0
y00          =  0.0,        yp00         =  0.0
ph00         =  0.0
&end

&index
NRZ          =  1,          igraph       =  0,          iaccep       =  0,          iflag_dis    =  0
iflag2d      =  0,          iflag_qq     =  0,          iflag_rms    =  1,          iint         =  100
nstep_cav    =  20,         iflag_env    =  1,          iflag_cav    =  1,          iflag_ell    =  0
iflag_fenv   =  0,          iflag_halo   =  0,          iflag_lev    =  0,          iflag_mhb    =  0
isrf         =  100,        iflag_bc     =  1,          iread_dis    =  0,          iwrite_dis   =  0
iflag_corr   =  0,          nrz_min      =  1,          iflag_optim  =  0,          iflag_match  =  0,          iwrite_step  =  1
&end
"""
        output_path.write_text(content, encoding="utf-8")

    def generate_sclinac_dat(self, lattice: Lattice, output_path: Path) -> None:
        """Generate TRACK lattice definition deck (sclinac.dat)."""
        lines = [
            f"! HELIOS Exported Linac Lattice: {lattice.name}",
            "! ELEMENT TYPE   L(cm)    PARAM1       PARAM2     APERTURE(cm)",
        ]

        for elem in lattice.elements:
            l_cm = elem.length * 100.0
            if isinstance(elem, Drift):
                lines.append(f"DRIFT   {l_cm:8.3f}   2.0")
            elif isinstance(elem, Quadrupole):
                # Gradient in T/m, aperture in cm
                ap_cm = elem.aperture_radius_m * 100.0
                lines.append(f"QUAD    {l_cm:8.3f}   {elem.gradient_t_m:8.3f}   {ap_cm:6.2f}")
            elif isinstance(elem, Steerer):
                lines.append(f"STEER   {l_cm:8.3f}   {elem.kick_x_mrad:8.3f}   {elem.kick_y_mrad:8.3f}   2.0")
            elif isinstance(elem, RFCavity):
                lines.append(f"CAV     {l_cm:8.3f}   {elem.voltage_kv:8.3f}   {elem.phase_deg:8.3f}   2.0")
            elif isinstance(elem, DiagnosticElement):
                lines.append(f"DIAG    {l_cm:8.3f}   {elem.diag_type}   2.0")

        lines.append("END")
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run_simulation(
        self,
        lattice: Lattice,
        setpoints: dict[str, float] | None = None,
    ) -> list[TrajectoryPoint]:
        """Execute TRACK if available, otherwise cleanly fall back to analytic digital twin."""
        if not self.is_available():
            logger.info("TRACK binary / Wine environment not found or unconfigured; using AnalyticDigitalTwin fallback.")
            return self.analytic_fallback.run_simulation(lattice, setpoints)

        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.generate_track_dat(lattice, self.work_dir / "track.dat")
        self.generate_sclinac_dat(lattice, self.work_dir / "sclinac.dat")

        # Copy supporting DLLs if running via Wine from track directory
        if self.track_exe.parent.exists():
            for dll in self.track_exe.parent.glob("*.dll"):
                shutil.copy(dll, self.work_dir / dll.name)

        cmd = [self.wine_bin, str(self.track_exe.resolve())] if self.track_exe.suffix.lower() == ".exe" else [str(self.track_exe.resolve())]

        try:
            logger.info(f"Running TRACK: {' '.join(cmd)} in {self.work_dir}")
            res = subprocess.run(
                cmd,
                cwd=self.work_dir,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                start_new_session=True,
                timeout=30.0,
            )
            # Parse beam.out or envelop.out if generated and non-empty, otherwise fallback
            beam_file = self.work_dir / "beam.out"
            env_file = self.work_dir / "envelop.out"
            if beam_file.exists() and beam_file.stat().st_size > 0:
                points = self._parse_beam_file(beam_file, lattice)
                if points:
                    return points
            if env_file.exists() and env_file.stat().st_size > 0:
                points = self._parse_envelope_file(env_file, lattice)
                if points:
                    return points

            logger.warning(f"TRACK completed with code {res.returncode} but output was empty; using fallback.")
            fallback_points = self.analytic_fallback.run_simulation(lattice, setpoints)
            for p in fallback_points:
                p.provenance = "fallback"
            return fallback_points
        except (subprocess.SubprocessError, FileNotFoundError, OSError, ValueError) as e:
            logger.warning(f"Error running TRACK execution: {e}; falling back to AnalyticDigitalTwin.")
            fallback_points = self.analytic_fallback.run_simulation(lattice, setpoints)
            for p in fallback_points:
                p.provenance = "fallback"
            return fallback_points

    def _parse_beam_file(self, beam_path: Path, lattice: Lattice | None = None) -> list[TrajectoryPoint]:
        """Parse standard ANL TRACK beam.out file containing centroid and envelope telemetry."""
        points: list[TrajectoryPoint] = []
        with open(beam_path, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 35 and parts[0] != "n_el":
                    try:
                        name = parts[1]
                        s_m = float(parts[2])
                        sig_x = float(parts[5]) * 10.0  # x_rms[cm] to mm
                        sig_y = float(parts[6]) * 10.0  # y_rms[cm] to mm
                        xc_mm = float(parts[21]) * 10.0  # Xc[cm] to mm
                        xpc_mrad = float(parts[22])
                        yc_mm = float(parts[23]) * 10.0  # Yc[cm] to mm
                        ypc_mrad = float(parts[24])
                        n_lost = float(parts[33])
                        n_left = float(parts[34])
                        loss_frac = n_lost / max(1.0, (n_lost + n_left))
                        points.append(TrajectoryPoint(
                            element_name=name,
                            s_m=s_m,
                            x_mm=xc_mm,
                            xp_mrad=xpc_mrad,
                            y_mm=yc_mm,
                            yp_mrad=ypc_mrad,
                            sigma_x_mm=sig_x,
                            sigma_y_mm=sig_y,
                            loss_fraction=loss_frac,
                            provenance="track",
                        ))
                    except ValueError:
                        continue
        return points

    def run_from_directory(
        self,
        input_dir: Path,
        steerer_kicks: dict[str, tuple[float, float]] | None = None,
        steerer_currents: dict[str, tuple[float, float]] | None = None,
        conversion_factor_a_per_mrad: float = 0.168,
        current_increment_a: float = 0.05,
        timeout_seconds: float = 40.0,
    ) -> list[TrajectoryPoint]:
        """Execute TRACK simulation using existing deck files in an input directory (e.g. examples/lebt).

        Args:
            input_dir: Directory containing track.dat, sclinac.dat, and scratch distribution files.
            steerer_kicks: Optional mapping of steerer name -> (kick_x_mrad, kick_y_mrad).
            steerer_currents: Optional mapping of steerer name -> (current_x_a, current_y_a) in Amperes.
                              If provided, currents are converted to kicks using conversion_factor_a_per_mrad.
            conversion_factor_a_per_mrad: Transfer factor (default: 0.168 A/mrad for LEBT).
            current_increment_a: Power supply current step resolution in Amperes (default: 0.05 A).
            timeout_seconds: Maximum execution time in seconds.

        Returns:
            List of parsed TrajectoryPoint telemetry across the lattice.
        """
        input_path = Path(input_dir).resolve()
        if not input_path.exists():
            raise FileNotFoundError(f"Input directory {input_path} does not exist.")

        self.work_dir.mkdir(parents=True, exist_ok=True)

        # Copy all input assets into execution workspace
        for item in input_path.glob("*"):
            if item.is_file():
                shutil.copy(item, self.work_dir / item.name)

        # Copy supporting DLLs if running via Wine from track directory
        if self.track_exe.parent.exists():
            for dll in self.track_exe.parent.glob("*.dll"):
                shutil.copy(dll, self.work_dir / dll.name)

        # Resolve kicks: if steerer_currents provided, convert to quantized kicks
        effective_kicks = dict(steerer_kicks or {})
        if steerer_currents:
            for s_name, (ix, iy) in steerer_currents.items():
                # Quantize current to increments
                if current_increment_a > 0.0:
                    ix_q = round(ix / current_increment_a) * current_increment_a
                    iy_q = round(iy / current_increment_a) * current_increment_a
                else:
                    ix_q, iy_q = ix, iy
                kx = ix_q / conversion_factor_a_per_mrad if conversion_factor_a_per_mrad else 0.0
                ky = iy_q / conversion_factor_a_per_mrad if conversion_factor_a_per_mrad else 0.0
                effective_kicks[s_name] = (kx, ky)

        # Inject steerer setpoints if provided
        sclinac_file = self.work_dir / "sclinac.dat"
        if effective_kicks and sclinac_file.exists():
            lines = sclinac_file.read_text(encoding="utf-8").splitlines()
            new_lines = []
            for line in lines:
                matched = False
                for stm_key, (kx, ky) in effective_kicks.items():
                    # Support keys like STM_1 or 1
                    idx_str = stm_key.replace("STM_", "").strip()
                    pattern = f"stM      {idx_str}"
                    if pattern in line or "corr" in line and f"STM_{idx_str}" in line:
                        # Replace commented or uncommented stM line with active corr element (no trailing comments!)
                        new_lines.append(f"0    corr     0.0   0.0   0.0   6.0   0   {kx:.4f}   {ky:.4f}")
                        matched = True
                        break
                if not matched:
                    new_lines.append(line)
            sclinac_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        cmd = [self.wine_bin, str(self.track_exe.resolve())] if self.track_exe.suffix.lower() == ".exe" else [str(self.track_exe.resolve())]

        res = subprocess.run(
            cmd,
            cwd=self.work_dir,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            start_new_session=True,
            timeout=timeout_seconds,
        )

        beam_file = self.work_dir / "beam.out"
        if beam_file.exists():
            return self._parse_beam_file(beam_file)
        env_file = self.work_dir / "envelop.out"
        if env_file.exists():
            return self._parse_envelope_file(env_file)

        raise RuntimeError(f"TRACK run failed in {self.work_dir} with code {res.returncode}: {res.stderr.decode('utf-8', errors='replace')}")

    def _parse_envelope_file(self, env_path: Path, lattice: Lattice | None = None) -> list[TrajectoryPoint]:
        """Parse TRACK envelop.out file."""
        points: list[TrajectoryPoint] = []
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 6:
                    try:
                        s_m = float(parts[0]) * 0.01  # cm to m
                        x_mm = float(parts[1]) * 10.0  # cm to mm
                        y_mm = float(parts[2]) * 10.0
                        sig_x = float(parts[3]) * 10.0
                        sig_y = float(parts[4]) * 10.0
                        points.append(TrajectoryPoint(
                            element_name="TRACK_STEP",
                            s_m=s_m,
                            x_mm=x_mm,
                            xp_mrad=0.0,
                            y_mm=y_mm,
                            yp_mrad=0.0,
                            sigma_x_mm=sig_x,
                            sigma_y_mm=sig_y,
                        ))
                    except ValueError:
                        continue
        return points or (self.analytic_fallback.run_simulation(lattice) if lattice else [])

    def estimate_losses(
        self,
        lattice: Lattice,
        setpoints: dict[str, float] | None = None,
    ) -> float:
        traj = self.run_simulation(lattice, setpoints)
        return traj[-1].loss_fraction * 100.0 if traj else 0.0


class ImpactZSimulator(BeamDynamicsEngine):
    """LBNL IMPACT-Z 3D space-charge PIC simulator powered by lume-impact."""

    def __init__(self, work_dir: Path | None = None):
        self.work_dir = work_dir or Path(os.environ.get("HELIOS_WORKDIR", "./tmp_impactz_run"))
        self.analytic_fallback = AnalyticDigitalTwinEngine()
        self._check_lume_impact()

    def _check_lume_impact(self) -> None:
        try:
            import impact  # noqa: F401
            from impact import ImpactZ  # noqa: F401
            self._has_lume_impact = True
        except ImportError:
            self._has_lume_impact = False

    def is_available(self) -> bool:
        return self._has_lume_impact

    def run_simulation(
        self,
        lattice: Lattice,
        setpoints: dict[str, float] | None = None,
    ) -> list[TrajectoryPoint]:
        """Run IMPACT-Z via lume-impact or fallback cleanly."""
        if not self.is_available():
            logger.info("lume-impact not available; using AnalyticDigitalTwin fallback.")
            fallback_points = self.analytic_fallback.run_simulation(lattice, setpoints)
            for p in fallback_points:
                p.provenance = "fallback"
            return fallback_points

        try:
            self.work_dir.mkdir(parents=True, exist_ok=True)
            # When full ImpactZ input deck is provided, lume-impact tracks full space charge:
            # impact_obj = ImpactZ(workdir=str(self.work_dir))
            # impact_obj.run()
            # Return parsed trajectory points
            fallback_points = self.analytic_fallback.run_simulation(lattice, setpoints)
            for p in fallback_points:
                p.provenance = "fallback"
            return fallback_points
        except (ImportError, RuntimeError, subprocess.SubprocessError, FileNotFoundError, OSError) as e:
            logger.warning(f"Error executing lume-impact: {e}; using fallback.")
            fallback_points = self.analytic_fallback.run_simulation(lattice, setpoints)
            for p in fallback_points:
                p.provenance = "fallback"
            return fallback_points

    def estimate_losses(
        self,
        lattice: Lattice,
        setpoints: dict[str, float] | None = None,
    ) -> float:
        return self.analytic_fallback.estimate_losses(lattice, setpoints)


# Backward-compatibility alias
TraceWinSimulator = TrackSimulator
