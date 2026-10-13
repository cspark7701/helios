# Execution Plan / Change Record: 00015

- **Sub-tasks**: Phase 8 LLM Agent Core & Operator Chat Interface (8.1, 8.2, 8.3)
- **Status**: Completed
- **Date**: 2026-10-13
- **Author**: Chong Shik Park / HELIOS Team
- **Reference**: LBNL Osprey Framework

---

## 1. Objectives

- Implement the multi-provider LLM integration layer with structured tool calling and offline mock support for air-gapped accelerator networks.
- Build the `NaturalLanguagePlanner` agent translating conversational control room prompts into structured, pre-validated `ExecutionPlan` drafts using Osprey dynamic capability injection.
- Provide an interactive terminal chat interface (`helios chat`) with visual plan summary tables, operator approval gates, and live execution progress.

---

## 2. Implementation Summary

1. **Multi-Provider LLM Client (`helios/core/llm.py`)**:
   - `BaseLLMClient`: Abstract interface accepting conversation history (`LLMMessage`) and function schemas (`tools`).
   - `MockLLMClient`: Deterministic offline engine supporting physics-informed rule-based intent parsing (orbit correction, RF phase scans, loss diagnostics) without requiring external network connectivity.
   - `OpenAICompatibleLLMClient`: Compatible with OpenAI, vLLM, LocalAI, and Ollama self-hosted endpoints.
   - `create_llm_client`: Factory instantiation helper.
2. **`NaturalLanguagePlanner` (`helios/agents/planner.py`)**:
   - Ingests free-form physicist directives (e.g., *"Please correct horizontal and vertical trajectory in MEBT"*).
   - Dynamically selects relevant tools via `CapabilityRegistry.classify_intent` (Osprey model).
   - Generates fully populated `ExecutionPlan` instances with target agents, actions, parameters, and rationale.
3. **Interactive Operator Console (`helios/cli/main.py`)**:
   - Added `helios chat` command featuring interactive prompts, formatted plan review tables, human-in-the-loop approval confirmation (`[y/n/d]`), and direct closed-loop execution.
4. **Automated Testing**:
   - Implemented `tests/test_llm.py` testing orbit intent, RF intent, and plan synthesis.
   - Verified that all 48 tests pass cleanly across the test suite in the `helios` conda environment.

---

## 3. Files Modified / Created

- `M  docs/exec-plans/active/00014_next_development_phases_tasklist.md`
- `A  docs/exec-plans/completed/00015_phase8_llm_agent_and_chat_console.md`
- `M  helios/agents/__init__.py`
- `A  helios/agents/planner.py`
- `M  helios/cli/main.py`
- `M  helios/core/__init__.py`
- `A  helios/core/llm.py`
- `A  tests/test_llm.py`
