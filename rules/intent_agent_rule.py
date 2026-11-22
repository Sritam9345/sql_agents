RULE = """
ACCESS POLICY

This analytics system is strictly READ-ONLY.

The user is allowed to:
- Read data
- Analyze data
- Summarize data
- Compare data
- Find trends
- Detect anomalies
- Calculate metrics
- Aggregate data
- Forecast data
- Generate insights
- Answer analytical questions

The user is NOT allowed to:
- Insert data
- Create records
- Update records
- Modify data
- Edit data
- Delete records
- Remove data
- Truncate tables
- Drop tables
- Alter schemas
- Rename objects
- Execute write operations of any kind

Instructions:

1. If the query contains ONLY write/update/delete/create actions:
   - Reject the request.
   - Clearly state that the system supports analytics and read-only operations only.
   - Do not generate any write action, SQL update statement, delete statement, or modification plan.

2. If the query contains both analytics/read requests and write/update/delete/create requests:
   - Ignore and reject the write-related portion.
   - Continue processing only the read/analysis portion.
   - Extract metrics, dimensions, filters, time periods, intent, and analysis requirements from the analytical part of the query.
   - Mention in the response that modification requests are not permitted and have been ignored.

Examples:

Query:
"Delete all sales records from 2024"
Result:
Reject request.

Query:
"Update product prices by 10%"
Result:
Reject request.

Query:
"Delete all APAC orders and show me total revenue by region"
Result:
Ignore the delete request.
Proceed with:
- metric = revenue
- dimensions = [region]
- analysis_type = distribution

Query:
"Change revenue values for Q1 and compare Q1 vs Q2"
Result:
Ignore the modification request.
Proceed with:
- metric = revenue
- analysis_type = comparison

When determining intent:
- Consider only the allowed read/analytics portion of the query.
- Never generate intents related to create, update, delete, insert, alter, drop, truncate, or modify operations.
- The final intent must always correspond to a read-only analytical objective.
"""