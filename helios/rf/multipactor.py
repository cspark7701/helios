"""HELIOS Phase 46: RF Multipactoring Resonant Barriers & Field Emission Dark Current.

Models Secondary Electron Yield (SEY) resonant multipactoring breakdown bands in
SRF coaxial power couplers / cavities (QWR/HWR) and calculates Fowler-Nordheim
electron field emission dark currents and bremsstrahlung radiation dose rates.
"""

import math
from enum import Enum

from pydantic import BaseModel


class SurfaceMaterial(str, Enum):
    NIOBIUM = "niobium"
    COPPER = "copper"
    TITANIUM_NITRIDE_COATED = "tin_coated_copper"


class MultipactorBarriersResult(BaseModel):
    """Calculated multipactoring voltage bands and SEY multiplication factors."""
    material: SurfaceMaterial
    frequency_MHz: float
    gap_distance_mm: float
    dangerous_sey_energy_range_eV: tuple[float, float]
    resonant_order_1_voltage_kV: float
    resonant_order_2_voltage_kV: float
    barrier_voltage_bands_kV: list[tuple[float, float]]
    active_in_barrier: bool
    secondary_emission_yield: float
    risk_level: str  # SAFE, MULTIPACTORING_ALERT, SEVERE_DISCHARGE


class FieldEmissionResult(BaseModel):
    """Fowler-Nordheim dark current and bremsstrahlung radiation metrics."""
    peak_electric_field_MV_m: float
    field_enhancement_beta: float
    dark_current_density_A_per_m2: float
    total_dark_current_uA: float
    radiation_dose_rate_mGy_per_hr: float
    sensor_radiation_status: str  # NOMINAL, ELEVATED, CRITICAL_QUENCH_RISK


class CavityMultipactorEngine:
    """Evaluates multipactor resonance levels and Fowler-Nordheim dark currents."""

    SEY_PARAMETERS = {
        SurfaceMaterial.NIOBIUM: {
            "E1_eV": 60.0,
            "E2_eV": 1300.0,
            "E_max_eV": 300.0,
            "delta_max": 1.45,
            "work_function_eV": 4.3,
        },
        SurfaceMaterial.COPPER: {
            "E1_eV": 45.0,
            "E2_eV": 1500.0,
            "E_max_eV": 250.0,
            "delta_max": 1.85,
            "work_function_eV": 4.65,
        },
        SurfaceMaterial.TITANIUM_NITRIDE_COATED: {
            "E1_eV": 90.0,
            "E2_eV": 650.0,
            "E_max_eV": 280.0,
            "delta_max": 0.98,  # SEY < 1 suppresses multipactoring!
            "work_function_eV": 4.1,
        },
    }

    def evaluate_multipactoring(
        self,
        material: SurfaceMaterial,
        frequency_MHz: float,
        gap_distance_mm: float,
        operating_voltage_kV: float
    ) -> MultipactorBarriersResult:
        """Calculate two-point and one-point multipactoring resonant barriers."""
        props = self.SEY_PARAMETERS[material]
        f_Hz = frequency_MHz * 1e6
        d_m = gap_distance_mm * 1e-3

        # Fundamental resonant electron transit time condition:
        # t_transit = (2n - 1) / (2 * f)
        # v_res ~ d / t_transit = 2 * f * d / (2n - 1)
        # Kinetic energy: E_kin = 1/2 * m_e * v_res^2
        m_e = 9.10938356e-31
        e_ch = 1.602176634e-19

        # Order 1 (n=1: half RF period): v1 = 2 * f * d
        v1 = 2.0 * f_Hz * d_m
        E_kin1_eV = (0.5 * m_e * (v1 ** 2)) / e_ch
        # Voltage across gap producing this impact energy: V ~ pi/2 * E_kin1
        v_order1_kV = (E_kin1_eV * 1.5708) * 1e-3

        # Order 2 (n=2: 3 half RF periods): v2 = 2 * f * d / 3
        v2 = 2.0 * f_Hz * d_m / 3.0
        E_kin2_eV = (0.5 * m_e * (v2 ** 2)) / e_ch
        v_order2_kV = (E_kin2_eV * 1.5708) * 1e-3

        # Resonant voltage bands (+/- 25% bandwidth around resonance)
        bands = [
            (round(v_order2_kV * 0.75, 2), round(v_order2_kV * 1.25, 2)),
            (round(v_order1_kV * 0.75, 2), round(v_order1_kV * 1.25, 2)),
        ]

        # Check if operating voltage falls inside any band
        in_barrier = any(b_low <= operating_voltage_kV <= b_high for b_low, b_high in bands)

        # Estimate SEY at operating point: Vaughan empirical SEY formula
        e_impact = (operating_voltage_kV * 1e3) / 1.5708
        e_ratio = e_impact / props["E_max_eV"]

        if e_ratio < 1.0:
            k = 0.56
        else:
            k = 0.25

        sey = props["delta_max"] * math.pow(e_ratio * math.exp(1.0 - e_ratio), k) if e_ratio > 0 else 0.0

        if in_barrier and sey > 1.0:
            if operating_voltage_kV > 5.0:
                risk = "SEVERE_DISCHARGE"
            else:
                risk = "MULTIPACTORING_ALERT"
        else:
            risk = "SAFE"

        return MultipactorBarriersResult(
            material=material,
            frequency_MHz=frequency_MHz,
            gap_distance_mm=gap_distance_mm,
            dangerous_sey_energy_range_eV=(props["E1_eV"], props["E2_eV"]),
            resonant_order_1_voltage_kV=round(v_order1_kV, 3),
            resonant_order_2_voltage_kV=round(v_order2_kV, 3),
            barrier_voltage_bands_kV=bands,
            active_in_barrier=in_barrier,
            secondary_emission_yield=round(float(sey), 3),
            risk_level=risk
        )

    def evaluate_field_emission(
        self,
        peak_E_MV_m: float,
        field_enhancement_beta: float = 65.0,
        defect_area_m2: float = 1e-10,
        work_function_eV: float = 4.3
    ) -> FieldEmissionResult:
        """Calculate Fowler-Nordheim dark current and bremsstrahlung dose."""
        # Fowler-Nordheim formula: J_FN = A1 * (beta*E)^2 / phi * exp(-B1 * phi^1.5 / (beta*E))
        A1 = 1.54e-6
        B1 = 6.83e9  # V / (m * eV^1.5)

        E_local_V_m = (peak_E_MV_m * 1e6) * field_enhancement_beta
        phi = work_function_eV

        if E_local_V_m > 1e7:
            exponent = -(B1 * math.pow(phi, 1.5)) / E_local_V_m
            # Prevent underflow
            if exponent > -120.0:
                j_fn = (A1 * (E_local_V_m ** 2) / phi) * math.exp(exponent)
            else:
                j_fn = 0.0
        else:
            j_fn = 0.0

        i_dark_uA = (j_fn * defect_area_m2) * 1e6

        # Bremsstrahlung radiation dose rate (mGy/hr) scaling ~ I_dark * E^2.5
        dose_rate = 0.45 * i_dark_uA * math.pow(peak_E_MV_m / 10.0, 2.5)

        if dose_rate > 50.0:
            status = "CRITICAL_QUENCH_RISK"
        elif dose_rate > 2.0:
            status = "ELEVATED"
        else:
            status = "NOMINAL"

        return FieldEmissionResult(
            peak_electric_field_MV_m=round(peak_E_MV_m, 2),
            field_enhancement_beta=round(field_enhancement_beta, 1),
            dark_current_density_A_per_m2=round(float(j_fn), 4),
            total_dark_current_uA=round(float(i_dark_uA), 4),
            radiation_dose_rate_mGy_per_hr=round(float(dose_rate), 3),
            sensor_radiation_status=status
        )
