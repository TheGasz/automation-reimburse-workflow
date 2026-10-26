"""LangGraph StateGraph construction, Conditional Edge Routing, and Interrupt/Resume orchestration."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.agent.nodes.auditor import quota_and_audit_node
from app.agent.nodes.hitl_approval import (
    auto_approve_node,
    build_manager_approval_card,
    finalize_reject_node,
    human_approval_node,
    ledger_and_notify_node,
    request_reupload_node,
)
from app.agent.nodes.policy_rag import hybrid_policy_rag_node
from app.agent.nodes.vision_ocr import ingest_and_dedup_node, vision_extraction_node
from app.agent.state import ReimbursementAgentState
from app.config import get_settings
from app.db.session import db_manager


def route_after_ingest(
    state: ReimbursementAgentState,
) -> Literal["finalize_reject_node", "vision_extraction_node"]:
    """Route duplicate receipts directly to finalize_reject_node."""
    if state.get("is_duplicate"):
        return "finalize_reject_node"
    return "vision_extraction_node"


def route_after_vision_extraction(
    state: ReimbursementAgentState,
) -> Literal["request_reupload_node", "hybrid_policy_rag_node"]:
    """Route low-confidence OCR (< 0.65) or missing total/date to request_reupload_node."""
    settings = get_settings()
    extracted = state.get("extracted_receipt") or {}
    confidence = float(extracted.get("ocr_confidence", 0.0) or 0.0)
    total_amount = int(extracted.get("total_amount", 0) or 0)
    receipt_date = str(extracted.get("receipt_date") or "")

    if (
        confidence < settings.ocr_min_confidence
        or total_amount <= 0
        or not receipt_date
        or receipt_date == "invalid-date"
    ):
        return "request_reupload_node"
    return "hybrid_policy_rag_node"


def route_after_audit(
    state: ReimbursementAgentState,
) -> Literal["auto_approve_node", "human_approval_node", "finalize_reject_node"]:
    """Route based on AuditDecision.recommended_action."""
    audit = state.get("audit_decision") or {}
    action = str(audit.get("recommended_action", "needs_human_review"))
    if action == "auto_approve":
        return "auto_approve_node"
    if action == "auto_reject":
        return "finalize_reject_node"
    return "human_approval_node"


def build_reimbursement_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> Any:
    """Construct and compile the KlaimKilat AI StateGraph with checkpointer support."""
    builder = StateGraph(ReimbursementAgentState)

    # Register nodes
    builder.add_node("ingest_and_dedup_node", ingest_and_dedup_node)
    builder.add_node("vision_extraction_node", vision_extraction_node)
    builder.add_node("request_reupload_node", request_reupload_node)
    builder.add_node("hybrid_policy_rag_node", hybrid_policy_rag_node)
    builder.add_node("quota_and_audit_node", quota_and_audit_node)
    builder.add_node("auto_approve_node", auto_approve_node)
    builder.add_node("human_approval_node", human_approval_node)
    builder.add_node("finalize_reject_node", finalize_reject_node)
    builder.add_node("ledger_and_notify_node", ledger_and_notify_node)

    # Wire edges & conditional routers
    builder.add_edge(START, "ingest_and_dedup_node")
    builder.add_conditional_edges(
        "ingest_and_dedup_node",
        route_after_ingest,
        {
            "finalize_reject_node": "finalize_reject_node",
            "vision_extraction_node": "vision_extraction_node",
        },
    )
    builder.add_conditional_edges(
        "vision_extraction_node",
        route_after_vision_extraction,
        {
            "request_reupload_node": "request_reupload_node",
            "hybrid_policy_rag_node": "hybrid_policy_rag_node",
        },
    )
    builder.add_edge("hybrid_policy_rag_node", "quota_and_audit_node")
    builder.add_conditional_edges(
        "quota_and_audit_node",
        route_after_audit,
        {
            "auto_approve_node": "auto_approve_node",
            "human_approval_node": "human_approval_node",
            "finalize_reject_node": "finalize_reject_node",
        },
    )

    builder.add_edge("auto_approve_node", "ledger_and_notify_node")
    builder.add_edge("human_approval_node", "ledger_and_notify_node")
    builder.add_edge("finalize_reject_node", "ledger_and_notify_node")
    builder.add_edge("request_reupload_node", "ledger_and_notify_node")
    builder.add_edge("ledger_and_notify_node", END)

    active_checkpointer = checkpointer if checkpointer is not None else MemorySaver()
    return builder.compile(checkpointer=active_checkpointer)


# Global singleton checkpointer and compiled graph
default_checkpointer = MemorySaver()
reimbursement_graph = build_reimbursement_graph(checkpointer=default_checkpointer)


async def run_reimbursement_claim(
    initial_state: ReimbursementAgentState,
    graph: Any | None = None,
) -> dict[str, Any]:
    """Execute reimbursement graph for a new claim and persist intermediate ESCALATED state if interrupted."""
    active_graph = graph or reimbursement_graph
    claim_id = str(initial_state["claim_id"])
    config = {"configurable": {"thread_id": claim_id}}

    result_state = await active_graph.ainvoke(initial_state, config=config)
    snapshot = await active_graph.aget_state(config)

    # Check if graph paused at human_approval_node via interrupt()
    if snapshot.next and "human_approval_node" in snapshot.next:
        escalated_state = dict(snapshot.values)
        escalated_state["final_status"] = "ESCALATED"
        audit_summary = (escalated_state.get("audit_decision") or {}).get(
            "audit_summary", "Menunggu persetujuan Manajer Finance."
        )
        escalated_state["final_message"] = (
            f"Klaim {claim_id} DIJEDA (ESCALATED) untuk persetujuan Manajer Finance. {audit_summary}"
        )
        await db_manager.save_claim(escalated_state)
        escalated_state["approval_card"] = build_manager_approval_card(escalated_state)
        return escalated_state

    return dict(result_state)


async def resume_reimbursement_claim(
    claim_id: str,
    decision_payload: dict[str, Any],
    graph: Any | None = None,
) -> dict[str, Any]:
    """Resume an interrupted reimbursement claim using LangGraph Command(resume=...)."""
    active_graph = graph or reimbursement_graph
    config = {"configurable": {"thread_id": claim_id}}
    resumed_state = await active_graph.ainvoke(
        Command(resume=decision_payload),
        config=config,
    )
    return dict(resumed_state)
