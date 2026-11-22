import json
from typing import Any, Dict

from state.main import AnalyticsState
from prompts.planning_agent_prompt import get_planning_agent_prompt
from llm.main import call_llm


def planning_agent(state: AnalyticsState) -> Dict[str, Any]:
    prompt = get_planning_agent_prompt(state)

    response = call_llm(prompt)

    # Support LLM wrappers that return an AIMessage
    if hasattr(response, "content"):
        response = response.content

    # Support wrappers that already return a dictionary
    if isinstance(response, dict):
        result = response
    else:
        response = str(response).strip()

        # Remove Markdown code fences if the LLM adds them
        if response.startswith("```"):
            response = response.removeprefix("```json")
            response = response.removeprefix("```")
            response = response.removesuffix("```")
            response = response.strip()

        try:
            result = json.loads(response)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Planning agent returned invalid JSON: {response}"
            ) from exc

    execution_plan = result.get("execution_plan", [])

    if not isinstance(execution_plan, list):
        raise ValueError(
            "Planning agent output 'execution_plan' must be a list."
        )

    # Keep only valid, non-empty task strings
    execution_plan = [
        task.strip()
        for task in execution_plan
        if isinstance(task, str) and task.strip()
    ]

    current_task = result.get("current_task")

    # Ensure current_task is synchronized with the generated plan
    if execution_plan:
        if current_task not in execution_plan:
            current_task = execution_plan[0]
    else:
        current_task = None

    # In LangGraph, returning only changed fields is preferable
    return {
        "execution_plan": execution_plan,
        "current_task": current_task,
    }