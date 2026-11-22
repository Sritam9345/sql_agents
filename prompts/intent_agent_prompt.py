from datetime import date
from state.main import AnalyticsState


def get_intent_agent_prompt(state: AnalyticsState) -> str:
    current_date = date.today().isoformat()

    return f"""Extract analytics intent from the user query as valid JSON only.

Current Date: {current_date}
User Query: {state["user_query"]}

Fields to extract (use snake_case, return null or empty []/{{}} if absent):
1. metric: Primary KPI (e.g., revenue, sales, profit, orders, customer_count, conversion_rate, inventory).
2. dimensions: Grouping fields (e.g., region, country, city, product, category, channel, customer_segment, salesperson).
3. filters: Explicit conditions as key-value pairs (e.g., {{"region": "APAC", "category": "Electronics"}}).
4. time_period: Resolve year, quarter, month, relative period, or range into YYYY-MM-DD dates using Current Date ({current_date}) when year/date is relative.
   - Quarter bounds: Q1=01-01..03-31, Q2=04-01..06-30, Q3=07-01..09-30, Q4=10-01..12-31.
   - Format: {{"type": "year|quarter|month|relative|range", "value": "...", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}} (or {{}} if none).
5. analysis_type: One of [aggregate, trend, comparison, ranking, distribution, anomaly, forecast, root_cause].

Rules:
- Do not invent missing values.
- Output ONLY valid JSON matching the schema below. No markdown or explanations.

Schema:
{{
    "metric": null,
    "dimensions": [],
    "filters": {{}},
    "time_period": {{}},
    "analysis_type": ""
}}

Example:
Query: "What were the total sales in Q2 2024?"
Output:
{{"metric": "sales", "dimensions": [], "filters": {{}}, "time_period": {{"type": "quarter", "value": "Q2 2024", "start_date": "2024-04-01", "end_date": "2024-06-30"}}, "analysis_type": "aggregate"}}

Example:
Query: "how profitable was company in Q2 compared to Q1?"
Output:
{{"metric": "sales", "dimensions": [], "filters": {{}}, "time_period": {{"type": "quarter", "value": "Q2 2024", "start_date": "2024-04-01", "end_date": "2024-06-30"}}, "analysis_type": "aggregate"}}


"""
