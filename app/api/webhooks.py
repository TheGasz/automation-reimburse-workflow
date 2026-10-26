"""Telegram Bot API & WhatsApp Gateway Webhook Handlers (Receipt Scan & Callback Button Resume)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from app.agent.graph import reimbursement_graph, resume_reimbursement_claim
from app.agent.state import ReimbursementAgentState
from app.db.session import db_manager
from app.services.queue_worker import notifier, queue_manager

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])


@router.post("/telegram")
async def telegram_webhook_handler(update: dict[str, Any]) -> dict[str, Any]:
    """Handle Telegram Update payloads: incoming receipt photos and Finance Manager Inline Keyboard callbacks."""
    # 1. Handle Inline Keyboard button press (callback_query) from Finance Manager
    if "callback_query" in update and update["callback_query"]:
        cb = update["callback_query"]
        data = str(cb.get("data", ""))
        from_user = cb.get("from") or {}
        approver_id = f"TG-{from_user.get('username') or from_user.get('id', 'MGR')}"

        if not data.startswith("claim:"):
            raise HTTPException(
                status_code=400, detail=f"Format callback_data tidak dikenali: {data}"
            )

        parts = data.split(":")
        if len(parts) < 4:
            raise HTTPException(
                status_code=400, detail=f"Format callback_data tidak lengkap: {data}"
            )

        _, claim_id, action, amount_str = parts[:4]
        approved_amount = int(amount_str) if amount_str.isdigit() else 0

        existing = await db_manager.get_claim(claim_id)
        if existing is None:
            raise HTTPException(
                status_code=404, detail=f"Claim '{claim_id}' tidak ditemukan."
            )

        resumed = await resume_reimbursement_claim(
            claim_id=claim_id,
            decision_payload={
                "approver_id": approver_id,
                "action": action,
                "approved_amount": approved_amount,
                "note": "Diputuskan langsung via tombol Inline Keyboard Telegram.",
            },
            graph=reimbursement_graph,
        )

        await notifier.send_employee_notification(
            channel=str(resumed.get("channel", "telegram")),
            chat_id=str(resumed.get("chat_id", existing.get("chat_id", ""))),
            claim_id=claim_id,
            final_status=str(resumed.get("final_status", "APPROVED")),
            message=str(resumed.get("final_message", "")),
        )
        return {
            "event_type": "callback_query_resumed",
            "claim_id": claim_id,
            "final_status": resumed.get("final_status"),
            "approved_amount": (resumed.get("audit_decision") or {}).get(
                "approved_amount", 0
            ),
            "final_message": resumed.get("final_message"),
        }

    # 2. Handle new receipt photo / message from Employee
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    from_user = message.get("from") or {}

    chat_id = str(chat.get("id", "111222"))
    employee_id = str(message.get("employee_id") or f"EMP-TG-{from_user.get('id', '001')}")
    if employee_id.startswith("EMP-TG-") and employee_id not in (
        "EMP-001",
        "EMP-002",
        "EMP-003",
    ):
        employee_id = "EMP-001"

    caption = str(message.get("caption") or message.get("text") or "")
    photos = message.get("photo") or []
    preset_key = message.get("preset_key")
    raw_ocr_text = message.get("raw_ocr_text")

    if preset_key:
        image_ref = f"preset://{preset_key}"
    elif photos:
        file_id = str(photos[-1].get("file_id", "indomaret_snack_rapat"))
        image_ref = (
            f"preset://{file_id}"
            if file_id
            in (
                "indomaret_snack_rapat",
                "restoran_klien_high_value",
                "minimarket_rokok_alkohol_reject",
                "struk_gabungan_atk_dan_rokok",
                "etoll_dan_bbm_dinas",
                "nota_expired_lewat_14_hari",
            )
            else "preset://indomaret_snack_rapat"
        )
    else:
        image_ref = "preset://indomaret_snack_rapat"

    claim_id = str(message.get("claim_id") or f"CLM-TG-{uuid.uuid4().hex[:6].upper()}")
    initial_state: ReimbursementAgentState = {
        "claim_id": claim_id,
        "employee_id": employee_id,
        "channel": "telegram",
        "chat_id": chat_id,
        "image_url_or_path": image_ref,
        "user_caption": caption,
        "raw_ocr_text": raw_ocr_text,
    }

    result = await queue_manager.enqueue_or_run(initial_state, wait_for_result=True)
    return {
        "event_type": "message_claim_processed",
        "claim_id": claim_id,
        "final_status": result.get("final_status"),
        "approved_amount": (result.get("audit_decision") or {}).get(
            "approved_amount", 0
        ),
        "final_message": result.get("final_message"),
        "approval_card": result.get("approval_card"),
    }


@router.post("/whatsapp")
async def whatsapp_webhook_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle WhatsApp Gateway (Baileys) incoming receipt scans."""
    sender = str(payload.get("sender") or payload.get("chat_id") or "628123456789")
    employee_id = str(payload.get("employee_id") or "EMP-001")
    caption = str(payload.get("caption") or payload.get("message") or "")
    preset_key = str(payload.get("preset_key") or "indomaret_snack_rapat")
    raw_ocr_text = payload.get("raw_ocr_text")
    claim_id = str(payload.get("claim_id") or f"CLM-WA-{uuid.uuid4().hex[:6].upper()}")

    initial_state: ReimbursementAgentState = {
        "claim_id": claim_id,
        "employee_id": employee_id,
        "channel": "whatsapp",
        "chat_id": sender,
        "image_url_or_path": f"preset://{preset_key}",
        "user_caption": caption,
        "raw_ocr_text": raw_ocr_text,
    }
    result = await queue_manager.enqueue_or_run(initial_state, wait_for_result=True)
    return {
        "event_type": "whatsapp_claim_processed",
        "claim_id": claim_id,
        "final_status": result.get("final_status"),
        "final_message": result.get("final_message"),
    }
