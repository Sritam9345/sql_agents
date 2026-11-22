from typing import Any, Dict

from state.main import AnalyticsState
from prompts.sql_agent_prompt import get_sql_agent_prompt
from llm.main import call_llm


def sql_agent(state: AnalyticsState) -> Dict[str, Any]:

    execution_plan = state.get("execution_plan", [])
    sql_queries = dict(state.get("sql_queries") or {})

    # Use the current task assigned by the planning agent.
    current_task = state.get("current_task")

    # If no current task is assigned, pick the next pending plan step.
    if not current_task:
        current_task = next(
            (task for task in execution_plan if task not in sql_queries),
            None
        )

    if not current_task:
        return {
            "error_message_sql": "No pending task found in execution_plan."
        }

    # Pass the selected task along with the complete planning context.
    prompt_state = {
        **state,
        "current_task": current_task
    }

    prompt = get_sql_agent_prompt(prompt_state)

    # call_llm directly returns the generated response string.
    sql_query = call_llm(prompt).strip()
    print(sql_query)

    # Remove Markdown fences if the LLM adds them.
    lines = sql_query.splitlines()

    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]

    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]

    sql_query = "\n".join(lines).strip()

    if not sql_query:
        return {
            "error_message_sql": "SQL agent generated an empty query."
        }

    # Store the generated SQL against its corresponding plan step.
    sql_queries[current_task] = sql_query

    return {
        "sql_queries": sql_queries,
        "current_task": current_task,
        "error_message_sql": None,
    }