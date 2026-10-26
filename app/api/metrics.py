"""Observability & Production Metrics Summary Endpoint (GET /api/v1/metrics/summary)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.db.session import db_manager
from app.services.telemetry import compute_percentile

router = APIRouter(prefix="/api/v1/metrics", tags=["Observability & Metrics"])


@router.get("/summary")
async def get_metrics_summary(
    start_date: str | None = Query(
        default=None, description="Filter start date (YYYY-MM-DD)"
    ),
    end_date: str | None = Query(
        default=None, description="Filter end date (YYYY-MM-DD)"
    ),
) -> dict[str, Any]:
    """Compute production observability metrics: p50/p95 latency, error rate, token cost IDR, and decision ratios."""
    entries = db_manager.get_telemetry_entries()
    if start_date:
        entries = [
            e for e in entries if str(e.get("created_at", ""))[:10] >= start_date
        ]
    if end_date:
        entries = [e for e in entries if str(e.get("created_at", ""))[:10] <= end_date]

    claims = await db_manager.list_claims(limit=500)
    if start_date:
        claims = [c for c in claims if str(c.get("created_at", ""))[:10] >= start_date]
    if end_date:
        claims = [c for c in claims if str(c.get("created_at", ""))[:10] <= end_date]

    # Per-claim end-to-end latency aggregation
    claim_latencies: dict[str, float] = {}
    node_latencies: dict[str, list[float]] = {}
    error_count = 0
    total_tokens = 0
    total_cost_idr = 0.0

    for entry in entries:
        cid = str(entry.get("claim_id", "UNKNOWN"))
        node = str(entry.get("node_name", "unknown"))
        lat = float(entry.get("latency_ms", 0.0))
        claim_latencies[cid] = claim_latencies.get(cid, 0.0) + lat
        node_latencies.setdefault(node, []).append(lat)
        total_tokens += int(entry.get("total_tokens", 0))
        total_cost_idr += float(entry.get("cost_idr", 0.0))
        if entry.get("status") != "SUCCESS":
            error_count += 1

    e2e_latencies = [round(v, 2) for v in claim_latencies.values()]
    p50_ms = compute_percentile(e2e_latencies, 50.0)
    p95_ms = compute_percentile(e2e_latencies, 95.0)

    total_events = len(entries)
    error_rate_pct = (
        round((error_count / total_events) * 100.0, 2) if total_events > 0 else 0.0
    )

    total_claims = len(claims)
    auto_approve_count = 0
    human_review_count = 0
    auto_reject_count = 0

    for claim in claims:
        rec = (claim.get("audit_decision") or {}).get("recommended_action")
        if rec == "auto_approve":
            auto_approve_count += 1
        elif rec == "needs_human_review" or claim.get("final_status") in (
            "ESCALATED",
            "PARTIALLY_APPROVED",
        ):
            human_review_count += 1
        elif rec == "auto_reject" or claim.get("final_status") == "REJECTED":
            auto_reject_count += 1

    per_node_summary = {
        node: {
            "count": len(vals),
            "p50_latency_ms": compute_percentile(vals, 50.0),
            "p95_latency_ms": compute_percentile(vals, 95.0),
        }
        for node, vals in node_latencies.items()
    }

    num_tracked_claims = max(1, len(claim_latencies)) if entries else 0
    avg_cost_per_claim_idr = (
        round(total_cost_idr / num_tracked_claims, 4) if num_tracked_claims > 0 else 0.0
    )

    return {
        "total_claims": total_claims,
        "total_node_executions": total_events,
        "latency": {
            "e2e_p50_ms": p50_ms,
            "e2e_p95_ms": p95_ms,
            "target_p95_ms": 6500.0,
            "meets_sla": p95_ms <= 6500.0,
            "per_node": per_node_summary,
        },
        "tokens_and_cost": {
            "total_tokens": total_tokens,
            "total_cost_idr": round(total_cost_idr, 4),
            "avg_cost_per_claim_idr": avg_cost_per_claim_idr,
            "target_cost_per_claim_idr": 45.0,
            "meets_cost_target": avg_cost_per_claim_idr <= 45.0,
        },
        "reliability": {
            "error_count": error_count,
            "error_rate_pct": error_rate_pct,
            "target_error_rate_pct": 1.5,
        },
        "decision_distribution": {
            "auto_approve_count": auto_approve_count,
            "human_review_count": human_review_count,
            "auto_reject_count": auto_reject_count,
            "auto_approve_ratio": (
                round(auto_approve_count / total_claims, 4) if total_claims > 0 else 0.0
            ),
            "human_review_ratio": (
                round(human_review_count / total_claims, 4) if total_claims > 0 else 0.0
            ),
            "auto_reject_ratio": (
                round(auto_reject_count / total_claims, 4) if total_claims > 0 else 0.0
            ),
        },
    }
