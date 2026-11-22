import json
import re
from typing import Any, Dict

from state.main import AnalyticsState
from prompts.intent_agent_prompt import get_intent_agent_prompt
from rules.intent_agent_rule import RULE
from llm.main import call_llm


INTENT_FIELDS = {
    "metric",
    "dimensions",
    "filters",
    "time_period",
    "analysis_type",
}


def _parse_llm_json(response: Any) -> Dict[str, Any]:
    """
    Convert the LLM response into a dictionary.

    Supports:
    - A dictionary response
    - A normal JSON string
    - JSON wrapped inside Markdown code fences
    """

    if isinstance(response, dict):
        return response

    if hasattr(response, "content"):
        response = response.content

    if not isinstance(response, str):
        raise TypeError(
            f"Expected LLM response to be str or dict, got {type(response).__name__}"
        )

    response = response.strip()

    # Remove Markdown fences such as ```json ... ```
    response = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        response,
        flags=re.IGNORECASE,
    ).strip()

    return json.loads(response)


def intent_agent(state: AnalyticsState) -> AnalyticsState:
    """
    Analyze the user's query and populate the intent-related graph state.

    The RULE ensures that:
    - Read and analysis requests are allowed.
    - Write, update, and delete requests are rejected.
    - Mixed requests process only the read/analysis portion.
    """

    prompt = f"""


{get_intent_agent_prompt(state)}
"""

    try:
        llm_response = call_llm(prompt)
        print(llm_response)
        parsed_response = _parse_llm_json(llm_response)
        

        # Update only fields that belong to the intent agent
        intent_output = {
            key: value
            for key, value in parsed_response.items()
            if key in INTENT_FIELDS
        }

        # TypedDict-style AnalyticsState
        if isinstance(state, dict):
            state.update(intent_output)
            return state

        # Pydantic/dataclass-style AnalyticsState
        for key, value in intent_output.items():
            setattr(state, key, value)

        return state

    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Intent agent returned invalid JSON: {llm_response}"
        ) from exc

    except Exception as exc:
        raise RuntimeError(
            f"Intent agent failed while processing the query: {exc}"
        ) from exc
