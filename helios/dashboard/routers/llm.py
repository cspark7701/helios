"""LLM prompt processing and model catalog routes for HELIOS dashboard."""

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from helios.core.llm import create_llm_client
from helios.core.plan_engine import PlanStore
from helios.dashboard.deps import get_plan_store

logger = logging.getLogger(__name__)
router = APIRouter(tags=["AI Planner"])


@router.get("/api/llm/models")
async def get_llm_models_endpoint() -> list[dict[str, Any]]:
    """List selectable LLM models and local/cloud providers."""
    return [
        {
            "id": "mock-helios-planner",
            "name": "Offline Deterministic (mock-helios-planner)",
            "provider": "mock",
            "type": "Offline / Air-Gapped",
            "description": "Deterministic rule-based physics planner for air-gapped linac control.",
        },
        {
            "id": "llama3",
            "name": "Ollama: Llama 3",
            "provider": "ollama",
            "base_url": "http://localhost:11434/v1",
            "type": "Local GPU (Private)",
            "description": "On-premise LLM served via Ollama.",
        },
        {
            "id": "mistral",
            "name": "Ollama: Mistral",
            "provider": "ollama",
            "base_url": "http://localhost:11434/v1",
            "type": "Local GPU (Private)",
            "description": "Fast lightweight local model via Ollama.",
        },
        {
            "id": "deepseek-r1",
            "name": "Ollama: DeepSeek-R1",
            "provider": "ollama",
            "base_url": "http://localhost:11434/v1",
            "type": "Local GPU (Private)",
            "description": "Reasoning model running locally via Ollama.",
        },
        {
            "id": "gpt-4o-mini",
            "name": "OpenAI: GPT-4o Mini",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "type": "Cloud API",
            "description": "Fast cloud LLM with structured tool calling.",
        },
        {
            "id": "gpt-4o",
            "name": "OpenAI: GPT-4o",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "type": "Cloud API",
            "description": "Advanced reasoning cloud LLM.",
        },
    ]


@router.post("/api/prompt")
async def process_prompt_endpoint(
    payload: dict[str, Any],
    plan_store: PlanStore = Depends(get_plan_store),
) -> dict[str, Any]:
    """Process conversational directive with user-selected Language Model."""
    prompt = payload.get("prompt", "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    provider = str(payload.get("provider", "mock")).lower()
    model_name = str(payload.get("model", "mock-helios-planner"))
    base_url = payload.get("base_url")

    llm_kwargs: dict[str, Any] = {}
    if model_name:
        llm_kwargs["model"] = model_name
    if base_url:
        llm_kwargs["base_url"] = base_url
    elif provider == "ollama":
        llm_kwargs["base_url"] = "http://localhost:11434/v1"

    # Resolve API keys strictly from server environment, never trust or log client-supplied keys
    server_key = (
        os.environ.get("HELIOS_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
    )
    if server_key:
        llm_kwargs["api_key"] = server_key

    try:
        llm_client = create_llm_client(provider=provider, **llm_kwargs)
        from helios.agents.planner import NaturalLanguagePlanner
        planner = NaturalLanguagePlanner(llm_client=llm_client)
        plan, explanation = planner.formulate_plan_from_prompt(prompt)
    except Exception as e:
        logger.error(f"Error querying model {model_name} via {provider}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Error querying model '{model_name}' via provider '{provider}': {str(e)}",
        )

    plan_store.register_plan(plan)

    return {
        "explanation": explanation,
        "model": model_name,
        "provider": provider,
        "plan": {
            "plan_id": plan.plan_id,
            "title": plan.title,
            "steps": [
                {
                    "step_id": s.step_id,
                    "name": s.name,
                    "agent": s.target_agent,
                    "action": s.action,
                    "parameters": s.parameters,
                }
                for s in plan.steps
            ],
        },
        "success": True,
    }
