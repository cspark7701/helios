"""HELIOS Natural Language Planner Agent.

Translates high-level natural language control room directives into structured,
pre-validated Plan-First ExecutionPlans using dynamic capability injection.
"""

import logging
import uuid
from typing import Any

from helios.core.capabilities import (
    Capability,
    CapabilityRegistry,
    get_default_registry,
)
from helios.core.llm import BaseLLMClient, LLMMessage, ToolCall, create_llm_client
from helios.core.schemas import (
    AutonomyLevel,
    ExecutionPlan,
    PlanStep,
)
from helios.interfaces.channel_map import (
    ChannelManager,
    create_baseline_mebt_channel_manager,
)
from helios.optimization.workflows import OrbitCorrectionWorkflow, RFPhaseScanWorkflow
from helios.physics.lattice import Lattice, create_baseline_mebt_lattice
from helios.physics.surrogate import FastPhysicsSurrogate
from helios.safety.gatekeeper import SafetyGatekeeper

logger = logging.getLogger(__name__)


class NaturalLanguagePlanner:
    """Plans operational sequences from operator requests using LLM and dynamic tool dispatch."""

    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        registry: CapabilityRegistry | None = None,
        channel_manager: ChannelManager | None = None,
        lattice: Lattice | None = None,
    ):
        self.llm = llm_client or create_llm_client(provider="mock")
        self.registry = registry or get_default_registry()
        self.channels = channel_manager or create_baseline_mebt_channel_manager()
        self.lattice = lattice or create_baseline_mebt_lattice()

        self.physics_surrogate = FastPhysicsSurrogate()
        self.safety_gatekeeper = SafetyGatekeeper(self.channels)
        self.orbit_workflow = OrbitCorrectionWorkflow(self.lattice, self.channels)

    def formulate_plan_from_prompt(
        self,
        user_prompt: str,
        plan_id: str | None = None,
        autonomy_level: AutonomyLevel = AutonomyLevel.SUPERVISED,
    ) -> tuple[ExecutionPlan, str]:
        """Convert natural language directive into a pre-validated ExecutionPlan.

        Returns:
            (plan: ExecutionPlan, explanation: str)
        """
        plan_id = plan_id or str(uuid.uuid4())[:5]

        # 1. Dynamic Capability Classification (Osprey model)
        relevant_caps = self.registry.classify_intent(user_prompt, max_tools=6)
        tool_schemas = self._build_tool_schemas(relevant_caps)

        # 2. Query LLM with conversation history and dynamic tools
        system_prompt = (
            "You are the HELIOS Master Orchestrator planning agent for a Heavy Ion Linear Accelerator. "
            "Your role is to formulate structured, safe, plan-first operational workflows based on physicist directives. "
            "Select the most appropriate tool to generate the execution plan."
        )
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]

        response = self.llm.generate(messages, tools=tool_schemas)

        # 3. Translate tool call or response into structured ExecutionPlan
        if response.tool_calls:
            tc = response.tool_calls[0]
            plan = self._dispatch_plan_tool(tc, plan_id, autonomy_level)
        else:
            # Fallback general observation plan
            plan = ExecutionPlan(
                plan_id=plan_id,
                title="Telemetry Inspection",
                objective=user_prompt,
                autonomy_level=autonomy_level,
                steps=[
                    PlanStep(
                        step_id="step_1",
                        name="Read Diagnostics Telemetry",
                        target_agent="HELIOS-Diagnostics",
                        action="read_bpm_orbit",
                        parameters={"section": "MEBT"},
                    )
                ],
            )

        explanation = response.content or f"Generated execution plan '{plan.title}'."
        return plan, explanation

    def _build_tool_schemas(self, capabilities: list[Capability]) -> list[dict[str, Any]]:
        """Convert Capability objects into OpenAI-compatible tool JSON schemas."""
        tools = []
        for cap in capabilities:
            tools.append({
                "type": "function",
                "function": {
                    "name": cap.name,
                    "description": cap.description,
                    "parameters": cap.parameters_schema or {
                        "type": "object",
                        "properties": {
                            "section": {"type": "string", "default": "MEBT"},
                        },
                    },
                },
            })
        return tools

    def _dispatch_plan_tool(self, tool_call: ToolCall, plan_id: str, autonomy_level: AutonomyLevel) -> ExecutionPlan:
        """Route tool call to appropriate workflow plan builder."""
        args = tool_call.arguments
        name = tool_call.name

        if name in ("formulate_orbit_plan", "calculate_orbit_correction"):
            sec = args.get("section", "MEBT")
            steerers = args.get("steerers", [f"{sec}_CH01"])
            bpms = args.get("bpms", [f"{sec}_BPM01", f"{sec}_BPM02"])

            plan, _ = self.orbit_workflow.build_orbit_correction_plan(
                plan_id=plan_id,
                section=sec,
                steerer_names=steerers,
                bpm_names=bpms,
                measured_bpm_x={f"{sec}_BPM01": 0.5, f"{sec}_BPM02": 0.8},
                measured_bpm_y={f"{sec}_BPM01": -0.2, f"{sec}_BPM02": -0.3},
            )
            plan.autonomy_level = autonomy_level
            return plan

        elif name in ("formulate_rf_scan_plan", "rf_phase_amplitude_scan"):
            cav_name = args.get("cavity_name", "MEBT_CAV01")
            grid = RFPhaseScanWorkflow.generate_phase_grid(-180.0, 180.0, 30.0)
            steps = []
            for idx, phase in enumerate(grid[:5]):  # Initial sample steps
                steps.append(PlanStep(
                    step_id=f"step_rf_{idx+1}",
                    name=f"Set {cav_name} Phase to {phase:.0f} deg",
                    target_agent="HELIOS-Tuner",
                    action="set_rf_phase",
                    parameters={"cavity": cav_name, "phase_deg": phase},
                ))
            return ExecutionPlan(
                plan_id=plan_id,
                title=f"{cav_name} RF Phase Calibration Scan",
                objective="Scan RF phase across grid to determine synchronous phase angle",
                autonomy_level=autonomy_level,
                steps=steps,
            )

        else:
            # Default diagnostic check plan
            return ExecutionPlan(
                plan_id=plan_id,
                title="Diagnostic Health Verification",
                objective=f"Execute {name}",
                autonomy_level=autonomy_level,
                steps=[
                    PlanStep(
                        step_id="step_1",
                        name="Query BPM & BLM Telemetry",
                        target_agent="HELIOS-Diagnostics",
                        action="read_bpm_orbit",
                        parameters=args,
                    )
                ],
            )
