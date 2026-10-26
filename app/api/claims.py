"""REST API Endpoints for Submitting, Resuming (HITL), and Inspecting Reimbursement Claims."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.agent.graph import reimbursement_graph, resume_reimbursement_claim
from app.agent.nodes.vision_ocr import GOLDEN_RECEIPTS_PATH
from app.agent.state import ReimbursementAgentState
from app.db.session import db_manager
from app.services.queue_worker import notifier, queue_manager

router = APIRouter(prefix="/api/v1/claims", tags=["Claims"])

UPLOADS_DIR = Path(__file__).resolve().parents[2] / "uploads"


class ManagerDecisionRequest(BaseModel):
    """Payload for POST /api/v1/claims/{claim_id}/decision."""

    approver_id: str = Field(
        default="FIN-MGR-01", description="ID Manajer Finance yang memberikan keputusan"
    )
    action: Literal["approve", "approve_partial", "reject"] = Field(
        description="Keputusan persetujuan klaim"
    )
    approved_amount: int | None = Field(
        default=None, ge=0, description="Nominal yang disetujui dalam Rupiah"
    )
    note: str = Field(
        default="Telah diverifikasi oleh Manajer Finance.",
        description="Catatan audit dari Manajer Finance",
    )


@router.get("/presets/list")
async def list_golden_receipt_presets() -> dict[str, Any]:
    """Return golden receipt presets for 1-click scan testing."""
    if not GOLDEN_RECEIPTS_PATH.is_file():
        return {"presets": []}
    presets = json.loads(GOLDEN_RECEIPTS_PATH.read_text(encoding="utf-8"))
    return {"presets": presets}


@router.get("")
async def list_recent_claims() -> dict[str, Any]:
    """List recent claims and employee quota balances for dashboard & scanner portal."""
    claims = await db_manager.list_claims(limit=50)
    quotas = {}
    for emp_id in ("EMP-001", "EMP-002", "EMP-003", "EMP-ZERO"):
        quotas[emp_id] = {
            "meals": await db_manager.get_employee_remaining_quota(emp_id, "meals"),
            "transport": await db_manager.get_employee_remaining_quota(
                emp_id, "transport"
            ),
            "office_supplies": await db_manager.get_employee_remaining_quota(
                emp_id, "office_supplies"
            ),
            "accommodation": await db_manager.get_employee_remaining_quota(
                emp_id, "accommodation"
            ),
            "medical": await db_manager.get_employee_remaining_quota(emp_id, "medical"),
        }
    return {"claims": claims, "employee_quotas": quotas}


@router.post("/submit")
async def submit_claim(
    employee_id: str = Form(default="EMP-001"),
    caption: str = Form(default=""),
    channel: Literal["telegram", "whatsapp"] = Form(default="telegram"),
    chat_id: str = Form(default="web-scanner-user"),
    preset_key: str | None = Form(default=None),
    raw_ocr_text: str | None = Form(default=None),
    image_file: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    """Submit a new reimbursement claim via receipt scan upload or preset selection."""
    claim_id = f"CLM-{uuid.uuid4().hex[:8].upper()}"
    image_ref = f"preset://{preset_key}" if preset_key else "preset://indomaret_snack_rapat"

    if image_file is not None and image_file.filename:
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = f"{claim_id}_{Path(image_file.filename).name}"
        dest_path = UPLOADS_DIR / safe_name
        content_bytes = await image_file.read()
        dest_path.write_bytes(content_bytes)
        image_ref = str(dest_path)

        # If uploaded file is a text/json receipt or user didn't pass raw_ocr_text, check preset match
        if not raw_ocr_text and preset_key:
            image_ref = f"preset://{preset_key}"

    initial_state: ReimbursementAgentState = {
        "claim_id": claim_id,
        "employee_id": employee_id,
        "channel": channel,
        "chat_id": chat_id,
        "image_url_or_path": image_ref,
        "user_caption": caption,
        "raw_ocr_text": raw_ocr_text if raw_ocr_text and raw_ocr_text.strip() else None,
    }

    result = await queue_manager.enqueue_or_run(initial_state, wait_for_result=True)
    return result


@router.post("/{claim_id}/decision")
async def submit_manager_decision(
    claim_id: str,
    decision: ManagerDecisionRequest,
) -> dict[str, Any]:
    """Resume an interrupted (ESCALATED) LangGraph claim with Finance Manager approval/rejection."""
    existing = await db_manager.get_claim(claim_id)
    if existing is None:
        raise HTTPException(
            status_code=404, detail=f"Claim '{claim_id}' tidak ditemukan."
        )

    resumed = await resume_reimbursement_claim(
        claim_id=claim_id,
        decision_payload=decision.model_dump(),
        graph=reimbursement_graph,
    )

    await notifier.send_employee_notification(
        channel=str(resumed.get("channel", existing.get("channel", "telegram"))),
        chat_id=str(resumed.get("chat_id", existing.get("chat_id", ""))),
        claim_id=claim_id,
        final_status=str(resumed.get("final_status", "APPROVED")),
        message=str(resumed.get("final_message", "")),
    )
    return resumed


@router.get("/{claim_id}")
async def get_claim_detail(claim_id: str) -> dict[str, Any]:
    """Retrieve full claim detail, extracted receipt, SOP citations, and LangGraph checkpoint history."""
    record = await db_manager.get_claim(claim_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"Claim '{claim_id}' tidak ditemukan."
        )

    config = {"configurable": {"thread_id": claim_id}}
    checkpoint_history: list[dict[str, Any]] = []
    try:
        async for state_snap in reimbursement_graph.aget_state_history(config):
            checkpoint_history.append(
                {
                    "checkpoint_id": state_snap.config.get("configurable", {}).get(
                        "checkpoint_id"
                    ),
                    "next_nodes": list(state_snap.next),
                    "final_status": state_snap.values.get("final_status", "IN_PROGRESS"),
                    "created_at": state_snap.created_at,
                }
            )
    except Exception:
        pass

    response = dict(record)
    response["checkpoint_history"] = checkpoint_history
    return response
