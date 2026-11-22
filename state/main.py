from typing import TypedDict, List, Dict, Any, Optional


class AnalyticsState(TypedDict):
    # User Request
    user_query: str

    # Intent Agent Output
    metric: str
    dimensions: List[str]
    filters: Dict[str, Any]
    analysis_type: str

    # Planning Agent Output
    execution_plan: List[str]
    current_task: Optional[str]

    # SQL Agent Output
    sql_queries: Dict[str, str]
    query_results: Dict[str, Any]

    retry_count: int
    error_message_sql: Optional[str]

    # Analysis Agent Output
    trends: Dict[str, Any]
    anomalies: List[Dict]
    root_causes: List[str]
    insights: List[str]
    error_message_analysis: Optional[str]

    # Reporting Agent Output
    charts: List[str]
    recommendations: List[str]
    executive_summary: str

    # Final
    final_response: str
    next_agent: str