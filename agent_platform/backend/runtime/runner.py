"""run_agent — execute one agent turn on top of litellm.

This is the platform's execution core (replacing the prototype's hardcoded
runner). Given an agent's config and a conversation history, it runs litellm
with the agent's tools, executes any tool calls in a manual loop, and returns
the final assistant text plus the call cost.

It is provider-agnostic: litellm resolves credentials from the model-name
prefix (e.g. ``gemini/...`` -> GEMINI_API_KEY).
"""
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import litellm

from .tools import TOOL_REGISTRY, TOOLS_TO_FUNCTION

logger = logging.getLogger("agent_platform.runner")

# Retry transient rate-limit / overload errors with exponential backoff. Free
# tiers (e.g. Gemini) easily hit 429 RESOURCE_EXHAUSTED when agents run in
# parallel, so we wait a few seconds and try again.
_RETRY_BACKOFF = [4, 8, 16]  # seconds between attempts
_RATE_LIMIT_HINTS = ("rate", "429", "resource_exhausted", "quota", "overloaded", "503")


def _is_rate_limit(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return "ratelimit" in name or any(h in text for h in _RATE_LIMIT_HINTS)


def _completion_with_retry(kwargs: Dict[str, Any]):
    """litellm.completion with backoff on rate-limit/overload errors."""
    for attempt, wait in enumerate([0] + _RETRY_BACKOFF):
        if wait:
            logger.warning("rate-limited; retrying in %ss (attempt %s)", wait, attempt)
            time.sleep(wait)
        try:
            return litellm.completion(**kwargs)
        except Exception as e:  # noqa: BLE001
            if _is_rate_limit(e) and attempt < len(_RETRY_BACKOFF):
                continue
            raise


@dataclass
class AgentRunConfig:
    """The subset of agent fields the runtime needs. Built from an Agent row."""

    name: str
    model: str
    system_prompt: str
    temperature: float = 0.2
    max_output_tokens: int = 8126
    tools: Optional[List[str]] = None

    @classmethod
    def from_row(cls, agent) -> "AgentRunConfig":
        return cls(
            name=agent.name,
            model=agent.model,
            system_prompt=agent.system_prompt,
            temperature=agent.temperature,
            max_output_tokens=agent.max_output_tokens,
            tools=list(agent.tools or []),
        )


@dataclass
class RunResult:
    output: str
    cost: float
    history: List[Dict[str, Any]]  # full message list incl. tool calls/results


def _system_message(prompt: str) -> Dict[str, Any]:
    return {"role": "system", "content": prompt}


def run_agent(
    config: AgentRunConfig,
    user_input: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    max_tool_iterations: int = 5,
) -> RunResult:
    """Run a single agent turn.

    - ``history``: prior messages (OpenAI chat format). A system message is
      prepended if absent.
    - ``user_input``: optional new user message appended before the call.
    Returns the final assistant text, accumulated cost, and the updated history.
    """
    messages: List[Dict[str, Any]] = list(history or [])
    if not messages or messages[0].get("role") != "system":
        messages.insert(0, _system_message(config.system_prompt))
    if user_input is not None:
        messages.append({"role": "user", "content": user_input})

    tool_defs = [TOOL_REGISTRY[t] for t in (config.tools or []) if t in TOOL_REGISTRY]
    total_cost = 0.0

    for _ in range(max_tool_iterations):
        kwargs: Dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "temperature": config.temperature,
            "max_completion_tokens": config.max_output_tokens,
        }
        if tool_defs:
            kwargs["tools"] = tool_defs
            kwargs["tool_choice"] = "auto"

        response = _completion_with_retry(kwargs)
        total_cost += _cost_of(response)
        msg = response.choices[0].message

        if not getattr(msg, "tool_calls", None):
            text = msg.content or ""
            messages.append({"role": "assistant", "content": text})
            return RunResult(output=text, cost=total_cost, history=messages)

        # Record the assistant's tool-call turn, then execute each call.
        messages.append(msg.model_dump())
        for call in msg.tool_calls:
            result = _execute_tool(call)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.function.name,
                    "content": result,
                }
            )

    # Tool budget exhausted without a final answer.
    return RunResult(
        output="[max tool iterations reached without a final answer]",
        cost=total_cost,
        history=messages,
    )


def _execute_tool(call) -> str:
    name = call.function.name
    fn = TOOLS_TO_FUNCTION.get(name)
    if fn is None:
        return f'{{"error": "unknown tool {name}"}}'
    try:
        import json

        args = json.loads(call.function.arguments or "{}")
        return fn(**args)
    except Exception as e:  # never let a tool error crash the loop
        return f'{{"error": "{type(e).__name__}: {e}"}}'


def _cost_of(response) -> float:
    """Best-effort per-call USD cost from litellm token usage."""
    try:
        usage = response.usage
        inp, out = litellm.cost_per_token(
            model=response.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )
        return float(inp + out)
    except Exception:
        return 0.0
