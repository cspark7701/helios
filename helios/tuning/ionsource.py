"""HELIOS Phase 36: ECR Ion Source Plasma Optimization & Fast Multi-Species Switching.

Automates Electron Cyclotron Resonance (ECR) ion source plasma parameters (RF power,
gas mixing, extraction bias) and orchestrates fast multi-species beam switching across
LEBT magnetic rigidity boundaries.
"""

import math

from pydantic import BaseModel, Field


class ECRSourceParameters(BaseModel):
    """Operational parameters for high-charge-state ECR ion source."""
    microwave_power_kW: float = Field(..., ge=0.1, le=10.0, description="Klystron/Gyrotron forward power in kW")
    frequency_GHz: float = Field(default=28.0, ge=14.0, le=56.0, description="Microwave heating frequency in GHz")
    gas_pressure_mbar: float = Field(default=1.5e-7, description="Main neutral gas feed pressure")
    gas_mixing_ratio_percent: float = Field(default=25.0, ge=0.0, le=100.0, description="Mixing gas (e.g., O2/He) percentage")
    bias_disk_voltage_V: float = Field(default=-250.0, le=0.0, description="Negatively biased disk voltage for plasma electron donor")
    extraction_voltage_kV: float = Field(default=35.0, ge=10.0, le=60.0, description="High-voltage extraction platform voltage")


class ChargeStateDistribution(BaseModel):
    """Charge state distribution (CSD) currents in electrical micro-amperes (e uA)."""
    species: str
    mass_amu: float
    target_charge_state: int
    charge_currents_uA: dict[int, float]
    total_extracted_current_uA: float
    peak_charge_state: int
    target_state_current_uA: float


class SpeciesLatticeScaling(BaseModel):
    """Lattice scaling factors relative to a reference beam."""
    source_species: str
    target_species: str
    source_rigidity_T_m: float
    target_rigidity_T_m: float
    rigidity_ratio: float
    lebt_solenoid_current_factor: float
    lebt_dipole_current_factor: float
    rfq_vane_voltage_factor: float
    ramp_duration_seconds: float


class ECRSourceOptimizer:
    """Simulates and optimizes ECR plasma conditions for heavy-ion linacs."""

    def __init__(self, species: str = "U238", mass_amu: float = 238.0):
        self.species = species
        self.mass_amu = mass_amu

    def simulate_csd(
        self,
        params: ECRSourceParameters,
        target_q: int = 33
    ) -> ChargeStateDistribution:
        """Simulate charge state distribution based on plasma confinement and RF heating."""
        # Semi-empirical Geller / Golovanivsky scaling for average charge state:
        # q_bar ~ C * (P_rf ^ 0.25) * (f ^ 0.35) * (1 + 0.15 * log(1 + mixing_ratio))
        base_factor = 14.5 if self.species == "U238" else 8.5
        rf_boost = math.pow(params.microwave_power_kW, 0.28) * math.pow(params.frequency_GHz / 18.0, 0.35)
        gas_mix_boost = 1.0 + 0.008 * params.gas_mixing_ratio_percent
        bias_boost = 1.0 + min(abs(params.bias_disk_voltage_V) / 1000.0, 0.3)

        q_peak = int(round(base_factor * rf_boost * gas_mix_boost * bias_boost))
        q_peak = max(1, min(int(self.mass_amu * 0.4), q_peak))

        # Build Gaussian-like distribution around q_peak
        width = 3.5
        currents: dict[int, float] = {}
        total_I = 150.0 * (params.microwave_power_kW / 2.0) * (params.extraction_voltage_kV / 30.0)

        for q in range(max(1, q_peak - 12), q_peak + 13):
            prob = math.exp(-0.5 * ((q - q_peak) / width) ** 2)
            currents[q] = round(total_I * prob / (width * math.sqrt(2 * math.pi)), 2)

        total_extracted = sum(currents.values())
        target_I = currents.get(target_q, 0.0)

        return ChargeStateDistribution(
            species=self.species,
            mass_amu=self.mass_amu,
            target_charge_state=target_q,
            charge_currents_uA=currents,
            total_extracted_current_uA=round(total_extracted, 2),
            peak_charge_state=q_peak,
            target_state_current_uA=target_I
        )

    def optimize_for_charge_state(
        self,
        target_q: int,
        max_power_kW: float = 5.0
    ) -> ECRSourceParameters:
        """Find optimal RF power and gas mixing ratio to maximize yield of target_q."""
        best_params = ECRSourceParameters(
            microwave_power_kW=2.0,
            frequency_GHz=28.0,
            gas_mixing_ratio_percent=30.0
        )
        best_yield = 0.0

        for p in [1.5, 2.5, 3.5, 4.5, min(max_power_kW, 5.0)]:
            for mix in [10.0, 25.0, 40.0, 50.0]:
                for bias in [-150.0, -250.0, -350.0]:
                    cand = ECRSourceParameters(
                        microwave_power_kW=p,
                        gas_mixing_ratio_percent=mix,
                        bias_disk_voltage_V=bias
                    )
                    csd = self.simulate_csd(cand, target_q=target_q)
                    if csd.target_state_current_uA > best_yield:
                        best_yield = csd.target_state_current_uA
                        best_params = cand

        return best_params


class MultiSpeciesFastSwitcher:
    """Orchestrates fast multi-species beam switching across LEBT and RFQ."""

    SPECIES_DB = {
        "O16": {"mass_amu": 16.0, "nominal_q": 6, "energy_per_u_keV": 10.0},
        "Ar40": {"mass_amu": 40.0, "nominal_q": 9, "energy_per_u_keV": 10.0},
        "Xe124": {"mass_amu": 124.0, "nominal_q": 20, "energy_per_u_keV": 10.0},
        "U238": {"mass_amu": 238.0, "nominal_q": 33, "energy_per_u_keV": 10.0},
    }

    @staticmethod
    def calculate_rigidity(mass_amu: float, charge_state: int, energy_per_u_keV: float) -> float:
        """Calculate magnetic rigidity B*rho in Tesla-meters."""
        # p = sqrt(2 * m * E_kin)
        # m = mass_amu * 931.494 MeV / c^2
        # T_kin = mass_amu * energy_per_u_keV * 1e-3 MeV
        _c = 299792458.0
        e_charge = 1.602176634e-19
        amu_kg = 1.66053906660e-27

        m_kg = mass_amu * amu_kg
        E_joules = mass_amu * (energy_per_u_keV * 1e3) * e_charge
        p = math.sqrt(2.0 * m_kg * E_joules)
        q_coulomb = charge_state * e_charge

        B_rho = p / q_coulomb
        return B_rho

    def plan_species_switch(
        self,
        source_species: str,
        target_species: str,
        target_q: int | None = None
    ) -> SpeciesLatticeScaling:
        """Calculate magnet scaling factors and ramp duration for seamless species changeover."""
        src_info = self.SPECIES_DB[source_species]
        tgt_info = self.SPECIES_DB[target_species]

        tgt_q = target_q if target_q is not None else tgt_info["nominal_q"]

        brho_src = self.calculate_rigidity(src_info["mass_amu"], src_info["nominal_q"], src_info["energy_per_u_keV"])
        brho_tgt = self.calculate_rigidity(tgt_info["mass_amu"], tgt_q, tgt_info["energy_per_u_keV"])

        ratio = brho_tgt / brho_src
        
        # Solenoids focus as (B / B*rho)^2, so current scales linearly with B*rho
        sol_factor = ratio
        # Dipole field scales linearly with B*rho
        dip_factor = ratio
        # RFQ vane voltage scales with (A / q) for synchronous acceleration
        vane_factor = (tgt_info["mass_amu"] / tgt_q) / (src_info["mass_amu"] / src_info["nominal_q"])

        # Ramp duration based on rate of current change (e.g. 1 A/s)
        ramp_time = min(120.0, max(15.0, abs(ratio - 1.0) * 60.0))

        return SpeciesLatticeScaling(
            source_species=source_species,
            target_species=target_species,
            source_rigidity_T_m=round(brho_src, 5),
            target_rigidity_T_m=round(brho_tgt, 5),
            rigidity_ratio=round(ratio, 4),
            lebt_solenoid_current_factor=round(sol_factor, 4),
            lebt_dipole_current_factor=round(dip_factor, 4),
            rfq_vane_voltage_factor=round(vane_factor, 4),
            ramp_duration_seconds=round(ramp_time, 1)
        )
