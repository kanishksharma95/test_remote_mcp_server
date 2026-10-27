from datetime import date
from pathlib import Path
import sqlite3
from typing import Any
from fastmcp import FastMCP

mcp = FastMCP(name="MCP-expense-tracker")

# Database stored in the project root directory
DB_PATH = Path(__file__).resolve().parents[2] / "expenses.db"


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL DEFAULT 'General',
                date TEXT NOT NULL,
                description TEXT DEFAULT ''
            )
        """)
        conn.commit()


# Ensure the table is created
init_db()


@mcp.tool
def add_expense(
    title: str,
    amount: float,
    category: str = "General",
    expense_date: str | None = None,
    description: str = "",
) -> dict[str, Any]:
    """Add a new expense.

    Args:
        title: Short title or name of the expense (e.g., 'Groceries', 'Coffee').
        amount: Cost of the expense (must be a positive number).
        category: Category for the expense (e.g., 'Food', 'Travel', 'Utilities', 'Shopping'). Defaults to 'General'.
        expense_date: Date in YYYY-MM-DD format. If omitted, today's date is used.
        description: Additional notes or details about the expense.
    """
    if amount <= 0:
        return {"success": False, "error": "Amount must be greater than 0."}

    date_str = expense_date or date.today().isoformat()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO expenses (title, amount, category, date, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (title.strip(), round(amount, 2), category.strip().title(), date_str, description.strip()),
        )
        conn.commit()
        expense_id = cursor.lastrowid

    return {
        "success": True,
        "message": f"Expense '{title}' added successfully with ID {expense_id}.",
        "expense": {
            "id": expense_id,
            "title": title.strip(),
            "amount": round(amount, 2),
            "category": category.strip().title(),
            "date": date_str,
            "description": description.strip(),
        },
    }


@mcp.tool
def list_expenses(
    category: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List expenses with optional filtering by category, date range, and count limit.

    Args:
        category: Filter by specific category (e.g., 'Food'). Case-insensitive.
        start_date: Filter expenses on or after this date (YYYY-MM-DD).
        end_date: Filter expenses on or before this date (YYYY-MM-DD).
        limit: Maximum number of expenses to return (default: 50).
    """
    query = "SELECT id, title, amount, category, date, description FROM expenses WHERE 1=1"
    params: list[Any] = []

    if category:
        query += " AND LOWER(category) = LOWER(?)"
        params.append(category.strip())
    if start_date:
        query += " AND date >= ?"
        params.append(start_date.strip())
    if end_date:
        query += " AND date <= ?"
        params.append(end_date.strip())

    query += " ORDER BY date DESC, id DESC LIMIT ?"
    params.append(limit)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

    expenses = [dict(row) for row in rows]
    total_amount = sum(item["amount"] for item in expenses)

    return {
        "count": len(expenses),
        "total_amount": round(total_amount, 2),
        "expenses": expenses,
    }


@mcp.tool
def summarize_expenses(
    category: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Summarize expenses with total spending, transaction count, average cost, and category breakdown.

    Args:
        category: Filter summary to a specific category.
        start_date: Filter summary from this start date (YYYY-MM-DD).
        end_date: Filter summary up to this end date (YYYY-MM-DD).
    """
    filters = " WHERE 1=1"
    params: list[Any] = []

    if category:
        filters += " AND LOWER(category) = LOWER(?)"
        params.append(category.strip())
    if start_date:
        filters += " AND date >= ?"
        params.append(start_date.strip())
    if end_date:
        filters += " AND date <= ?"
        params.append(end_date.strip())

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Overall summary
        summary_query = f"""
            SELECT 
                COUNT(*) as count,
                COALESCE(SUM(amount), 0) as total,
                COALESCE(AVG(amount), 0) as average,
                COALESCE(MAX(amount), 0) as highest
            FROM expenses {filters}
        """
        cursor.execute(summary_query, params)
        overall = dict(cursor.fetchone())

        # Category breakdown
        cat_query = f"""
            SELECT category, COUNT(*) as count, SUM(amount) as total
            FROM expenses {filters}
            GROUP BY category
            ORDER BY total DESC
        """
        cursor.execute(cat_query, params)
        cat_rows = cursor.fetchall()

    category_breakdown = [
        {"category": row["category"], "count": row["count"], "total": round(row["total"], 2)}
        for row in cat_rows
    ]

    return {
        "total_spent": round(overall["total"], 2),
        "total_transactions": overall["count"],
        "average_expense": round(overall["average"], 2),
        "highest_expense": round(overall["highest"], 2),
        "category_breakdown": category_breakdown,
    }


@mcp.tool
def edit_expense(
    expense_id: int,
    title: str | None = None,
    amount: float | None = None,
    category: str | None = None,
    expense_date: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Edit an existing expense by its unique ID. Only specified fields will be updated.

    Args:
        expense_id: The ID of the expense to edit.
        title: New title for the expense (optional).
        amount: New amount for the expense (optional).
        category: New category (optional).
        expense_date: New date in YYYY-MM-DD format (optional).
        description: New description or notes (optional).
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,))
        existing = cursor.fetchone()

        if not existing:
            return {"success": False, "error": f"Expense with ID {expense_id} not found."}

        updates: list[str] = []
        params: list[Any] = []

        if title is not None:
            updates.append("title = ?")
            params.append(title.strip())
        if amount is not None:
            if amount <= 0:
                return {"success": False, "error": "Amount must be greater than 0."}
            updates.append("amount = ?")
            params.append(round(amount, 2))
        if category is not None:
            updates.append("category = ?")
            params.append(category.strip().title())
        if expense_date is not None:
            updates.append("date = ?")
            params.append(expense_date.strip())
        if description is not None:
            updates.append("description = ?")
            params.append(description.strip())

        if not updates:
            return {"success": False, "message": "No changes specified."}

        params.append(expense_id)
        cursor.execute(f"UPDATE expenses SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

        cursor.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,))
        updated = dict(cursor.fetchone())

    return {
        "success": True,
        "message": f"Expense ID {expense_id} updated successfully.",
        "expense": updated,
    }


@mcp.tool
def delete_expense(expense_id: int) -> dict[str, Any]:
    """Delete an expense permanently by its unique ID.

    Args:
        expense_id: The unique ID of the expense to delete.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,))
        existing = cursor.fetchone()

        if not existing:
            return {"success": False, "error": f"Expense with ID {expense_id} not found."}

        cursor.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        conn.commit()

    return {
        "success": True,
        "message": f"Expense with ID {expense_id} ('{existing['title']}') was deleted successfully.",
        "deleted_expense": dict(existing),
    }


if __name__ == "__main__":
    mcp.run(transport ="http", host ="localhost", port =9000)
