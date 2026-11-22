from langgraph.graph import START, END, StateGraph

from agents.analysis_agent import analysis_agent
from agents.intent_agent import intent_agent
from agents.planning_agent import planning_agent
from agents.reporting_agent import reporting_agent
from agents.sql_agent import sql_agent
from state.main import AnalyticsState
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.memory import InMemorySaver


# -------------------------
# Routing functions
# -------------------------

def route_after_planning(state: AnalyticsState):
    """
    Expected state["next_agent"] values:
    - "sql_agent"
    - "analysis_agent"
    - "end"
    """
    return "sql_agent"


def route_after_sql(state: AnalyticsState):
    """
    Successful query execution goes to analysis.
    Missing fields, insufficient information, or SQL errors
    return control to planning.
    """
    if state["sql_success"]:
        return "analysis_agent"

    return "planning_agent"


def route_after_analysis(state: AnalyticsState):
    """
    Enough data for the requested analysis goes to reporting.
    Otherwise, return to planning for another SQL/analysis step.
    """
    if state["analysis_complete"]:
        return "reporting_agent"

    return "planning_agent"

def route_after_intent(state: AnalyticsState):
    """
    If user has malicious Intent
    """

    # if state["intent"] == 2:
    #     return "END"
    
    return "planning_agent"

# -------------------------
# Build graph
# -------------------------

builder = StateGraph(AnalyticsState)

builder.add_node("intent_agent", intent_agent)
builder.add_node("planning_agent", planning_agent)
builder.add_node("sql_agent", sql_agent)
builder.add_node("analysis_agent", analysis_agent)
builder.add_node("reporting_agent", reporting_agent)


# Fixed edges
builder.add_edge(START, "intent_agent")
builder.add_edge("reporting_agent", END)


# Dynamic routing from planning_agent
builder.add_conditional_edges(
    "planning_agent",
    route_after_planning,
    {
        "sql_agent": "sql_agent",
        "analysis_agent": "analysis_agent",
        "end": END,
    },
)


# SQL success → analysis
# SQL failure / missing information → planning
builder.add_conditional_edges(
    "sql_agent",
    route_after_sql,
    {
        "analysis_agent": "analysis_agent",
        "planning_agent": "planning_agent",
    },
)


# Analysis complete → reporting
# Insufficient data → planning
builder.add_conditional_edges(
    "analysis_agent",
    route_after_analysis,
    {
        "reporting_agent": "reporting_agent",
        "planning_agent": "planning_agent",
    },
)

builder.add_conditional_edges(
    "intent_agent",
    route_after_intent,
    {
        "planning_agent":"planning_agent",
        "END":END
    }
)


conn = sqlite3.connect('db/graph.db', check_same_thread=False)
checkpointer = SqliteSaver(conn)

graph = builder.compile(checkpointer=checkpointer)




def start_graph(userQuery: str, threadID: str) -> AnalyticsState:
    initial_state: AnalyticsState = {
        "user_query": userQuery
    }

    config = {
        "configurable": {
            "thread_id": threadID
        }
    }

    return graph.invoke(initial_state, config=config)




start_graph(userQuery="Give the company profits from q2 to q3.",threadID="user_123")


