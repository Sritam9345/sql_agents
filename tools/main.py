import sqlite3

DB_NAME = "company.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def execute_sql(query: str):
    conn = init_db()

    try:
        cursor = conn.cursor()
        cursor.execute(query)

        # SELECT queries
        if query.strip().lower().startswith("select"):
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        # INSERT / UPDATE / DELETE queries
        conn.commit()
        return {
            "success": True,
            "rows_affected": cursor.rowcount
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

    finally:
        conn.close()