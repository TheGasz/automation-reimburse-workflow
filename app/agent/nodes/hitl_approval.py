"""Human-in-the-Loop (interrupt/resume), Terminal Decision, and Ledger Notification Nodes."""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from app.db.session import db_manager
from app.services.telemetry import track_node_telemetry


def build_manager_approval_card(state: dict[str, Any]) -> dict[str, Any]:
    """Construct interactive Approval Card payload for Telegram / WhatsApp / Web Finance Manager."""
    claim_id = str(state.get("claim_id", "CLM-UNKNOWN"))
    employee_id = str(state.get("employee_id", "EMP-001"))
    extracted = state.get("extracted_receipt") or {}
    audit = state.get("audit_decision") or {}

    merchant = extracted.get("merchant_name", "Unknown Merchant")
    r_date = extracted.get("receipt_date", "-")
    total_amount = int(extracted.get("total_amount", 0) or 0)
    recommended_amount = int(audit.get("approved_amount", total_amount) or 0)
    summary = audit.get("audit_summary", "Memerlukan otorisasi Manajer Finance.")
    violations = audit.get("violations") or []

    return {
        "event": "HUMAN_APPROVAL_REQUIRED",
        "claim_id": claim_id,
        "employee_id": employee_id,
        "merchant_name": merchant,
        "receipt_date": r_date,
        "total_amount": total_amount,
        "recommended_approved_amount": recommended_amount,
        "audit_summary": summary,
        "violations": violations,
        "inline_keyboard": [
            [
                {
                    "text": f"Setujui Penuh (Rp{total_amount:,})",
                    "callback_data": f"claim:{claim_id}:approve:{total_amount}",
                },
                {
                    "text": f"Setujui Rekomendasi AI (Rp{recommended_amount:,})",
                    "callback_data": f"claim:{claim_id}:approve_partial:{recommended_amount}",
                },
            ],
            [
                {
                    "text": "Tolak Klaim",
                    "callback_data": f"claim:{claim_id}:reject:0",
                }
            ],
        ],
    }


def human_approval_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph Node 5: Pause execution with interrupt() and resume upon Finance Manager decision."""
    approval_card = build_manager_approval_card(state)

    #LangGraph interrupt() freezes graph state in checkpointer and surfaces approval_card to caller
    human_decision: dict[str, Any] = interrupt(approval_card)

    action = str(human_decision.get("action", "approve")).lower().strip()
    approver_id = str(human_decision.get("approver_id", "FIN-MGR-01"))
    note = str(human_decision.get("note") or "Telah ditinjau oleh Manajer Finance.")

    extracted = state.get("extracted_receipt") or {}
    audit = dict(state.get("audit_decision") or {})
    total_amount = int(extracted.get("total_amount", 0) or 0)
    default_rec_amount = int(audit.get("approved_amount", total_amount) or 0)

    if action == "reject":
        approved_amount = 0
        final_status = "REJECTED"
        final_message = (
            f"Klaim {state.get('claim_id')} DITOLAK oleh Manajer Finance ({approver_id}). "
            f"Catatan: {note}"
        )
    else:
        raw_approved = human_decision.get("approved_amount")
        approved_amount = (
            int(raw_approved)
            if raw_approved is not None
            else default_rec_amount
        )
        if 0 < approved_amount < total_amount or action == "approve_partial":
            final_status = "PARTIALLY_APPROVED"
            final_message = (
                f"Klaim {state.get('claim_id')} DISETUJUI SEBAGIAN sebesar Rp{approved_amount:,} "
                f"(dari total Rp{total_amount:,}) oleh Manajer Finance ({approver_id}). Catatan: {note}"
            )
        else:
            final_status = "APPROVED"
            final_message = (
                f"Klaim {state.get('claim_id')} DISETUJUI PENUH sebesar Rp{approved_amount:,} "
                f"oleh Manajer Finance ({approver_id}). Catatan: {note}"
            )

    audit["approved_amount"] = approved_amount
    return {
        "audit_decision": audit,
        "human_review_decision": {
            "approver_id": approver_id,
            "action": action,
            "approved_amount": approved_amount,
            "note": note,
        },
        "final_status": final_status,
        "final_message": final_message,
    }


@track_node_telemetry("auto_approve_node")
async def auto_approve_node(state: dict[str, Any]) -> dict[str, Any]:
    """Finalize Auto-Approved claim (<= Rp250.000 and 100% SOP compliant)."""
    audit = state.get("audit_decision") or {}
    approved_amount = int(audit.get("approved_amount", 0) or 0)
    summary = str(audit.get("audit_summary", "Disetujui otomatis sesuai SOP."))
    return {
        "final_status": "APPROVED",
        "final_message": (
            f"Klaim {state.get('claim_id')} DISETUJUI OTOMATIS (Auto-Approve) sebesar "
            f"Rp{approved_amount:,}. {summary}"
        ),
    }


@track_node_telemetry("finalize_reject_node")
async def finalize_reject_node(state: dict[str, Any]) -> dict[str, Any]:
    """Finalize Auto-Rejected claim (Duplicate receipt or SOP hard violation)."""
    claim_id = str(state.get("claim_id", "CLM-UNKNOWN"))
    if state.get("is_duplicate"):
        dup_decision = {
            "is_compliant": False,
            "recommended_action": "auto_reject",
            "approved_amount": 0,
            "violations": [
                {
                    "policy_code": "SOP-FIN-01.2",
                    "description": (
                        "Struk terdeteksi duplikat (double claim) berdasarkan perceptual/content hash."
                    ),
                    "severity": "hard_violation",
                }
            ],
            "audit_summary": (
                "Klaim ditolak otomatis (SOP-FIN-01.2): Bukti struk ini sudah pernah diajukan sebelumnya."
            ),
        }
        return {
            "audit_decision": dup_decision,
            "final_status": "REJECTED",
            "final_message": (
                f"Klaim {claim_id} DITOLAK OTOMATIS (SOP-FIN-01.2): Struk terdeteksi duplikat (Double Claim)."
            ),
        }

    audit = dict(state.get("audit_decision") or {})
    audit["approved_amount"] = 0
    summary = str(audit.get("audit_summary", "Melanggar ketentuan SOP Keuangan."))
    return {
        "audit_decision": audit,
        "final_status": "REJECTED",
        "final_message": f"Klaim {claim_id} DITOLAK OTOMATIS: {summary}",
    }


@track_node_telemetry("request_reupload_node")
async def request_reupload_node(state: dict[str, Any]) -> dict[str, Any]:
    """Handle unreadable or low-confidence (< 0.65) receipt scans by requesting re-upload."""
    claim_id = str(state.get("claim_id", "CLM-UNKNOWN"))
    extracted = state.get("extracted_receipt") or {}
    conf = float(extracted.get("ocr_confidence", 0.0) or 0.0)
    reupload_decision = {
        "is_compliant": False,
        "recommended_action": "auto_reject",
        "approved_amount": 0,
        "violations": [
            {
                "policy_code": "SOP-FIN-01.1",
                "description": (
                    f"Tingkat keterbacaan OCR ({conf:.2f}) di bawah batas minimum 0.65 "
                    "atau tanggal/nominal struk gagal terbaca."
                ),
                "severity": "hard_violation",
            }
        ],
        "audit_summary": (
            "Foto struk buram atau tidak terbaca. Mohon unggah ulang foto struk yang jelas."
        ),
    }
    return {
        "audit_decision": reupload_decision,
        "final_status": "REJECTED",
        "final_message": (
            f"Klaim {claim_id} belum dapat diproses karena foto struk kurang jelas "
            f"(OCR confidence: {conf:.0%}). Silakan kirim ulang foto struk dengan pencahayaan yang terang."
        ),
    }


@track_node_telemetry("ledger_and_notify_node")
async def ledger_and_notify_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph Node 6: Persist final claim status to ledger, deduct quota if approved, and notify user."""
    final_status = str(state.get("final_status", "PENDING"))
    employee_id = str(state.get("employee_id", "EMP-001"))
    extracted = state.get("extracted_receipt") or {}
    category = str(extracted.get("category") or "meals")
    audit = state.get("audit_decision") or {}
    approved_amount = int(audit.get("approved_amount", 0) or 0)

    new_remaining_quota = state.get("employee_remaining_quota")
    if final_status in ("APPROVED", "PARTIALLY_APPROVED") and approved_amount > 0:
        new_remaining_quota = await db_manager.deduct_employee_quota(
            employee_id=employee_id,
            category=category,
            approved_amount=approved_amount,
        )

    merged_state = dict(state)
    if new_remaining_quota is not None:
        merged_state["employee_remaining_quota"] = new_remaining_quota

    await db_manager.save_claim(merged_state)
    return {
        "employee_remaining_quota": new_remaining_quota,
        "final_status": final_status,
        "final_message": str(state.get("final_message", "")),
    }
