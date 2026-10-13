"""Tests for Multi-Provider LLM layer and NaturalLanguagePlanner."""

import pytest

from helios.agents.planner import NaturalLanguagePlanner
from helios.core.llm import (
    LLMMessage,
    MockLLMClient,
    ToolCall,
    create_llm_client,
)
from helios.core.schemas import AutonomyLevel, PlanState


def test_mock_llm_orbit_intent():
    """Verify MockLLMClient identifies orbit intent and returns structured tool call."""
    client = create_llm_client(provider="mock")
    messages = [
        LLMMessage(role="user", content="Flatten beam orbit in MEBT to reduce trajectory distortion")
    ]
    resp = client.generate(messages)

    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "formulate_orbit_plan"
    assert resp.tool_calls[0].arguments["section"] == "MEBT"
    assert "orbit" in resp.content.lower()


def test_mock_llm_rf_intent():
    """Verify MockLLMClient identifies RF phase scan intent."""
    client = create_llm_client(provider="mock")
    messages = [
        LLMMessage(role="user", content="Scan buncher cavity phase to calibrate RF synchronous angle")
    ]
    resp = client.generate(messages)

    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "formulate_rf_scan_plan"
    assert resp.tool_calls[0].arguments["cavity_name"] == "MEBT_CAV01"


def test_natural_language_planner_orbit_plan():
    """Verify NaturalLanguagePlanner synthesizes an ExecutionPlan from a prompt."""
    planner = NaturalLanguagePlanner()

    prompt = "Please correct horizontal and vertical trajectory in MEBT"
    plan, explanation = planner.formulate_plan_from_prompt(
        user_prompt=prompt,
        plan_id="00060",
        autonomy_level=AutonomyLevel.SUPERVISED,
    )

    assert plan.plan_id == "00060"
    assert "Orbit" in plan.title
    assert len(plan.steps) >= 1
    assert plan.steps[0].target_agent == "HELIOS-Control"
    assert plan.autonomy_level == AutonomyLevel.SUPERVISED
    assert "MEBT" in explanation


def test_natural_language_planner_rf_plan():
    """Verify NaturalLanguagePlanner synthesizes an RF phase scan plan."""
    planner = NaturalLanguagePlanner()

    prompt = "Run RF cavity phase scan"
    plan, explanation = planner.formulate_plan_from_prompt(
        user_prompt=prompt,
        plan_id="00061",
    )

    assert plan.plan_id == "00061"
    assert "Phase Calibration" in plan.title
    assert len(plan.steps) == 5
    assert all("Phase" in s.name for s in plan.steps)
