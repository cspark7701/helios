"""Tests for Dynamic Capability Classification (Osprey pattern)."""

import pytest

from helios.core.capabilities import (
    Capability,
    CapabilityDomain,
    CapabilityRegistry,
    RiskLevel,
    get_default_registry,
)


def test_registry_registration_and_filtering():
    """Test registering capabilities and filtering by agent or domain."""
    registry = get_default_registry()

    all_caps = registry.list_all()
    assert len(all_caps) >= 8

    diag_caps = registry.filter_by_domain(CapabilityDomain.DIAGNOSTICS)
    assert any(c.name == "read_bpm_orbit" for c in diag_caps)
    assert all(c.domain == CapabilityDomain.DIAGNOSTICS for c in diag_caps)

    tuner_caps = registry.filter_by_agent("HELIOS-Tuner")
    assert any(c.name == "calculate_orbit_correction" for c in tuner_caps)
    assert any(c.name == "rf_phase_amplitude_scan" for c in tuner_caps)


def test_dynamic_capability_classification_orbit():
    """Test intent classification for an orbit correction directive."""
    registry = get_default_registry()

    prompt = "Flatten the beam orbit in the MEBT section using steerers"
    selected = registry.classify_intent(prompt, max_tools=5)
    selected_names = [c.name for c in selected]

    # Must prioritize orbit correction and BPM readings
    assert "calculate_orbit_correction" in selected_names
    assert "read_bpm_orbit" in selected_names
    # Safety checks should always be included
    assert any(c.domain == CapabilityDomain.SAFETY for c in selected)


def test_dynamic_capability_classification_rf():
    """Test intent classification for an RF cavity scan directive."""
    registry = get_default_registry()

    prompt = "Scan buncher cavity phase and amplitude to verify time of flight"
    selected = registry.classify_intent(prompt, max_tools=4)
    selected_names = [c.name for c in selected]

    assert "rf_phase_amplitude_scan" in selected_names


def test_dynamic_capability_classification_simulation():
    """Test intent classification for digital twin simulation."""
    registry = get_default_registry()

    prompt = "Run TRACK ray tracing simulation to check heavy ion beam envelope losses"
    selected = registry.classify_intent(prompt, max_tools=4)
    selected_names = [c.name for c in selected]

    assert "run_track_simulation" in selected_names

    prompt_impact = "Run IMPACT-Z 3D space charge simulation"
    selected_impact = registry.classify_intent(prompt_impact, max_tools=4)
    selected_impact_names = [c.name for c in selected_impact]
    assert "run_impactz_simulation" in selected_impact_names
