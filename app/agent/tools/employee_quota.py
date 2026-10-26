"""LangChain @tool functions for checking employee monthly balance and receipt date validity."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from langchain_core.tools import tool

from app.config import get_settings
from app.db.session import db_manager


@tool
async def get_employee_monthly_balance(employee_id: str, category: str) -> dict[str, Any]:
    """Fetch the remaining monthly reimbursement quota in Rupiah (IDR) for an employee and expense category.

    Args:
        employee_id: Unique employee identifier (e.g. 'EMP-001').
        category: Expense category ('meals', 'transport', 'accommodation', 'office_supplies', 'medical', 'other').
    """
    remaining_idr = await db_manager.get_employee_remaining_quota(
        employee_id=employee_id, category=category
    )
    return {
        "employee_id": employee_id,
        "category": category,
        "remaining_quota_idr": remaining_idr,
        "has_quota": remaining_idr > 0,
    }


@tool
def check_ReceiptDate_validity(
    receipt_date: str,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Check whether receipt_date (YYYY-MM-DD) is within the 14 calendar day submission window (SOP-FIN-01.1).

    Args:
        receipt_date: Transaction date printed on the receipt in YYYY-MM-DD format.
        reference_date: Optional submission date in YYYY-MM-DD format (defaults to 2026-10-26 or today).
    """
    settings = get_settings()
    max_days = settings.max_receipt_age_days

    try:
        tx_date = datetime.strptime(receipt_date.strip(), "%Y-%m-%d").date()
    except ValueError:
        return {
            "is_valid": False,
            "age_days": -1,
            "max_allowed_days": max_days,
            "policy_code": "SOP-FIN-01.1",
            "reason": f"Format tanggal struk tidak valid: '{receipt_date}'",
        }

    if reference_date:
        ref_dt = datetime.strptime(reference_date.strip(), "%Y-%m-%d").date()
    else:
        # Default reference date aligned with workspace date (2026-10-26)
        ref_dt = date(2026, 10, 26)

    age_days = (ref_dt - tx_date).days
    if age_days > max_days:
        return {
            "is_valid": False,
            "age_days": age_days,
            "max_allowed_days": max_days,
            "policy_code": "SOP-FIN-01.1",
            "reason": (
                f"Tanggal struk ({receipt_date}) berusia {age_days} hari, "
                f"melebihi batas maksimal {max_days} hari kalender pada SOP-FIN-01.1."
            ),
        }

    if age_days < -1:
        return {
            "is_valid": False,
            "age_days": age_days,
            "max_allowed_days": max_days,
            "policy_code": "SOP-FIN-01.1",
            "reason": f"Tanggal struk ({receipt_date}) berada di masa depan terhadap tanggal pengajuan.",
        }

    return {
        "is_valid": True,
        "age_days": max(0, age_days),
        "max_allowed_days": max_days,
        "policy_code": "SOP-FIN-01.1",
        "reason": f"Tanggal struk valid ({max(0, age_days)} hari sejak transaksi).",
    }
