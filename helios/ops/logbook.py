"""HELIOS Phase 54: Automated Shift Handover & Digital Linac Logbook Forensics.

Synthesizes electronic linac shift handover reports (e-Log) capturing integrated beam statistics,
uptime, active golden lattice baselines, and executes 50 ms pre-trip circular buffer forensics
to automatically isolate root-cause trip initiators across BPM, BLM, and RF subsystems.
"""

from typing import Dict, List, Any, Optional
import time
from enum import Enum
from pydantic import BaseModel, Field


class ShiftHandoverReport(BaseModel):
    """Structured operational shift handover logbook summary."""
    shift_id: str
    shift_duration_hours: float
    timestamp: float = Field(default_factory=time.time)
    beam_species: str
    target_energy_MeV_u: float
    integrated_charge_uA_hr: float
    beam_uptime_percent: float
    total_trips_count: int
    mean_time_between_failures_min: float
    active_golden_certificate_id: str
    rpo_clearance_active: bool
    handover_notes: str


class TripRootCause(str, Enum):
    SRF_CAVITY_QUENCH_ARC = "SRF_CAVITY_QUENCH_ARC"
    FAST_BEAM_LOSS_PUNCHTHROUGH = "FAST_BEAM_LOSS_PUNCHTHROUGH"
    VACUUM_SPIKE_RUNAWAY = "VACUUM_SPIKE_RUNAWAY"
    MAGNET_POWER_SUPPLY_TRIP = "MAGNET_POWER_SUPPLY_TRIP"
    OPERATOR_MANUAL_ABORT = "OPERATOR_MANUAL_ABORT"


class CircularBufferSample(BaseModel):
    """High-speed 1 kHz multi-channel diagnostic telemetry sample."""
    time_offset_ms: float  # -50.0 ms to 0.0 ms (0.0 = trip trigger)
    bpm_rms_error_mm: float
    blm_total_dose_rate_Gy_s: float
    rf_reflected_power_kW: float
    piezo_voltage_V: float
    vacuum_pressure_mbar: float


class TripForensicsReport(BaseModel):
    """Automated root-cause diagnostic forensics from post-trip circular buffer."""
    trip_id: str
    trigger_timestamp_ms: float
    root_cause: TripRootCause
    primary_initiator_subsystem: str
    primary_event_offset_ms: float
    sequence_of_events: List[str]
    max_bpm_excursion_mm: float
    peak_blm_radiation_Gy_s: float
    peak_rf_reflection_kW: float
    recommended_corrective_action: str


class LinacLogbookForensicsEngine:
    """Manages shift logs and performs multi-subsystem post-trip timeline analysis."""

    @staticmethod
    def generate_shift_handover(
        shift_id: str,
        beam_species: str,
        target_energy_MeV_u: float,
        shift_hours: float,
        operating_hours: float,
        trips_count: int,
        beam_current_uA: float,
        golden_cert_id: str,
        rpo_cleared: bool = True
    ) -> ShiftHandoverReport:
        """Compile automated end-of-shift handover metrics."""
        uptime_pct = (operating_hours / max(1e-4, shift_hours)) * 100.0
        charge_uA_hr = operating_hours * beam_current_uA

        if trips_count > 0:
            mtbf_min = (operating_hours * 60.0) / trips_count
        else:
            mtbf_min = operating_hours * 60.0

        notes = (
            f"Shift {shift_id} delivered {charge_uA_hr:.1f} uA*hr of {beam_species} "
            f"at {target_energy_MeV_u:.2f} MeV/u with {uptime_pct:.1f}% uptime and {trips_count} trips."
        )

        return ShiftHandoverReport(
            shift_id=shift_id,
            shift_duration_hours=round(shift_hours, 2),
            beam_species=beam_species,
            target_energy_MeV_u=round(target_energy_MeV_u, 3),
            integrated_charge_uA_hr=round(charge_uA_hr, 2),
            beam_uptime_percent=round(uptime_pct, 2),
            total_trips_count=trips_count,
            mean_time_between_failures_min=round(mtbf_min, 1),
            active_golden_certificate_id=golden_cert_id,
            rpo_clearance_active=rpo_cleared,
            handover_notes=notes
        )

    def analyze_trip_circular_buffer(
        self,
        trip_id: str,
        buffer_samples: List[CircularBufferSample]
    ) -> TripForensicsReport:
        """Parse pre-trip timeline (-50 ms to 0 ms) and isolate initial failure source."""
        if not buffer_samples:
            raise ValueError("Buffer samples cannot be empty")

        max_bpm = max(s.bpm_rms_error_mm for s in buffer_samples)
        max_blm = max(s.blm_total_dose_rate_Gy_s for s in buffer_samples)
        max_rf_refl = max(s.rf_reflected_power_kW for s in buffer_samples)
        max_vac = max(s.vacuum_pressure_mbar for s in buffer_samples)

        # Find earliest anomaly threshold crossing
        rf_anom_time = None
        bpm_anom_time = None
        blm_anom_time = None
        vac_anom_time = None

        events = []

        for s in buffer_samples:
            if s.rf_reflected_power_kW > 1.5 and rf_anom_time is None:
                rf_anom_time = s.time_offset_ms
                events.append(f"T={s.time_offset_ms:.1f}ms: SRF cavity reflected power surge ({s.rf_reflected_power_kW:.2f} kW)")
            if s.bpm_rms_error_mm > 1.2 and bpm_anom_time is None:
                bpm_anom_time = s.time_offset_ms
                events.append(f"T={s.time_offset_ms:.1f}ms: BPM beam trajectory excursion ({s.bpm_rms_error_mm:.2f} mm)")
            if s.blm_total_dose_rate_Gy_s > 0.05 and blm_anom_time is None:
                blm_anom_time = s.time_offset_ms
                events.append(f"T={s.time_offset_ms:.1f}ms: BLM radiation loss detector spike ({s.blm_total_dose_rate_Gy_s:.3f} Gy/s)")
            if s.vacuum_pressure_mbar > 1.0e-6 and vac_anom_time is None:
                vac_anom_time = s.time_offset_ms
                events.append(f"T={s.time_offset_ms:.1f}ms: UHV chamber vacuum pressure surge ({s.vacuum_pressure_mbar:.2e} mbar)")

        # Determine earliest timestamp to identify primary initiator
        candidates = [
            ("RF", rf_anom_time, TripRootCause.SRF_CAVITY_QUENCH_ARC, "Inspect RF cavity piezo tuner and coupler conditioning."),
            ("VACUUM", vac_anom_time, TripRootCause.VACUUM_SPIKE_RUNAWAY, "Inspect beam pipe ion pump and gate valve seals."),
            ("BEAM_LOSS", blm_anom_time, TripRootCause.FAST_BEAM_LOSS_PUNCHTHROUGH, "Check steerer magnet supply and LEBT chopper stability."),
        ]
        valid_candidates = [c for c in candidates if c[1] is not None]

        if valid_candidates:
            # Sort by earliest time_offset_ms (most negative first)
            valid_candidates.sort(key=lambda x: x[1])
            subsys, t_event, root_cause, action = valid_candidates[0]
        else:
            subsys = "OPERATOR"
            t_event = 0.0
            root_cause = TripRootCause.OPERATOR_MANUAL_ABORT
            action = "Verify operator console action log."

        return TripForensicsReport(
            trip_id=trip_id,
            trigger_timestamp_ms=time.time() * 1000.0,
            root_cause=root_cause,
            primary_initiator_subsystem=subsys,
            primary_event_offset_ms=round(t_event, 2),
            sequence_of_events=events,
            max_bpm_excursion_mm=round(max_bpm, 3),
            peak_blm_radiation_Gy_s=round(max_blm, 4),
            peak_rf_reflection_kW=round(max_rf_refl, 3),
            recommended_corrective_action=action
        )
