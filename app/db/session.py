"""Async PostgreSQL (asyncpg) connection pool and In-Memory fallback store."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import asyncpg

from app.config import get_settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages asyncpg connection pool with automatic in-memory fallback for local/CI runs."""

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None
        self._using_in_memory: bool = False
        self._claims: dict[str, dict[str, Any]] = {}
        self._receipt_hashes: dict[str, str] = {}  # receipt_hash -> claim_id
        self._telemetry: list[dict[str, Any]] = []
        self._quotas: dict[tuple[str, str], dict[str, Any]] = {}
        self._seed_default_quotas()

    def _seed_default_quotas(self) -> None:
        """Seed realistic employee monthly quotas for DB Klik departments."""
        default_employees = [
            ("EMP-001", "Budi Santoso", "Sales & Cabang Surabaya"),
            ("EMP-002", "Siti Rahma", "Operasional & Logistik"),
            ("EMP-003", "Andi Wijaya", "IT & Infrastructure"),
        ]
        default_limits = {
            "meals": 1_500_000,
            "transport": 2_000_000,
            "accommodation": 3_500_000,
            "office_supplies": 1_000_000,
            "medical": 1_000_000,
            "other": 750_000,
        }
        for emp_id, emp_name, dept in default_employees:
            for category, limit_idr in default_limits.items():
                self._quotas[(emp_id, category)] = {
                    "employee_id": emp_id,
                    "employee_name": emp_name,
                    "department": dept,
                    "category": category,
                    "monthly_limit_idr": limit_idr,
                    "used_amount_idr": 200_000 if category == "meals" else 0,
                    "period_month": "2026-10",
                }

        # Special test employee with exhausted quota (Rp0 remaining)
        for category, limit_idr in default_limits.items():
            self._quotas[("EMP-ZERO", category)] = {
                "employee_id": "EMP-ZERO",
                "employee_name": "Doni Kuota Habis",
                "department": "Marketing",
                "category": category,
                "monthly_limit_idr": limit_idr,
                "used_amount_idr": limit_idr,
                "period_month": "2026-10",
            }

    def reset_in_memory_state(self) -> None:
        """Reset in-memory state for deterministic unit testing."""
        self._claims.clear()
        self._receipt_hashes.clear()
        self._telemetry.clear()
        self._quotas.clear()
        self._seed_default_quotas()

    async def connect(self) -> None:
        """Initialize asyncpg pool or fall back to in-memory store."""
        settings = get_settings()
        if settings.use_in_memory_db_fallback:
            try:
                self._pool = await asyncpg.create_pool(
                    dsn=settings.database_url,
                    min_size=1,
                    max_size=5,
                    timeout=1.5,
                )
                self._using_in_memory = False
                logger.info("Connected to PostgreSQL (pgvector) pool.")
                return
            except Exception as exc:
                self._using_in_memory = True
                logger.info(
                    "PostgreSQL unavailable (%s); running with In-Memory DB store.",
                    exc,
                )
                return

        self._pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=2,
            max_size=10,
        )
        self._using_in_memory = False

    async def disconnect(self) -> None:
        """Close asyncpg connection pool if open."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def is_in_memory(self) -> bool:
        """Return True if using in-memory fallback store."""
        return self._using_in_memory or self._pool is None

    @property
    def pool(self) -> asyncpg.Pool | None:
        """Return active asyncpg pool if connected."""
        return self._pool

    async def is_duplicate_receipt(self, receipt_hash: str, current_claim_id: str) -> bool:
        """Check whether a receipt_hash has already been submitted by another claim."""
        if not receipt_hash:
            return False

        if not self.is_in_memory and self._pool is not None:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT claim_id FROM reimbursement_claims
                    WHERE receipt_hash = $1 AND claim_id != $2
                    LIMIT 1
                    """,
                    receipt_hash,
                    current_claim_id,
                )
                return row is not None

        existing_claim = self._receipt_hashes.get(receipt_hash)
        if existing_claim is not None and existing_claim != current_claim_id:
            return True
        return False

    def register_receipt_hash(self, receipt_hash: str, claim_id: str) -> None:
        """Register receipt hash in memory for deduplication."""
        if receipt_hash and receipt_hash not in self._receipt_hashes:
            self._receipt_hashes[receipt_hash] = claim_id

    async def get_employee_remaining_quota(
        self, employee_id: str, category: str
    ) -> int:
        """Fetch remaining monthly reimbursement quota in IDR for an employee and category."""
        normalized_cat = category.lower().strip()
        if not self.is_in_memory and self._pool is not None:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT (monthly_limit_idr - used_amount_idr) AS remaining
                    FROM employee_quotas
                    WHERE employee_id = $1 AND category = $2
                    ORDER BY period_month DESC
                    LIMIT 1
                    """,
                    employee_id,
                    normalized_cat,
                )
                if row is not None:
                    return max(0, int(row["remaining"]))

        record = self._quotas.get((employee_id, normalized_cat))
        if record is None:
            # Default fallback quota for new employees
            default_limit = 1_500_000
            self._quotas[(employee_id, normalized_cat)] = {
                "employee_id": employee_id,
                "employee_name": f"Karyawan {employee_id}",
                "department": "General Operations",
                "category": normalized_cat,
                "monthly_limit_idr": default_limit,
                "used_amount_idr": 0,
                "period_month": "2026-10",
            }
            return default_limit

        remaining = int(record["monthly_limit_idr"]) - int(record["used_amount_idr"])
        return max(0, remaining)

    async def deduct_employee_quota(
        self, employee_id: str, category: str, approved_amount: int
    ) -> int:
        """Deduct approved amount from employee's monthly quota and return new remaining balance."""
        if approved_amount <= 0:
            return await self.get_employee_remaining_quota(employee_id, category)

        normalized_cat = category.lower().strip()
        if not self.is_in_memory and self._pool is not None:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE employee_quotas
                    SET used_amount_idr = used_amount_idr + $1,
                        updated_at = NOW()
                    WHERE employee_id = $2 AND category = $3
                    """,
                    approved_amount,
                    employee_id,
                    normalized_cat,
                )
            return await self.get_employee_remaining_quota(employee_id, normalized_cat)

        _ = await self.get_employee_remaining_quota(employee_id, normalized_cat)
        record = self._quotas[(employee_id, normalized_cat)]
        record["used_amount_idr"] = int(record["used_amount_idr"]) + approved_amount
        return max(
            0, int(record["monthly_limit_idr"]) - int(record["used_amount_idr"])
        )

    async def save_claim(self, state: dict[str, Any]) -> dict[str, Any]:
        """Upsert claim state into database or in-memory ledger."""
        claim_id = str(state["claim_id"])
        extracted = state.get("extracted_receipt") or {}
        audit = state.get("audit_decision") or {}
        receipt_hash = state.get("receipt_hash")
        if receipt_hash and not state.get("is_duplicate", False):
            self.register_receipt_hash(receipt_hash, claim_id)

        now_iso = datetime.now(UTC).isoformat()
        existing = self._claims.get(claim_id, {})

        record: dict[str, Any] = {
            "claim_id": claim_id,
            "employee_id": state.get("employee_id", "EMP-001"),
            "channel": state.get("channel", "telegram"),
            "chat_id": state.get("chat_id", ""),
            "image_url_or_path": state.get("image_url_or_path", ""),
            "user_caption": state.get("user_caption", ""),
            "receipt_hash": receipt_hash,
            "is_duplicate": bool(state.get("is_duplicate", False)),
            "merchant_name": extracted.get("merchant_name"),
            "receipt_date": extracted.get("receipt_date"),
            "category": extracted.get("category"),
            "total_amount": int(extracted.get("total_amount", 0) or 0),
            "approved_amount": int(audit.get("approved_amount", 0) or 0),
            "extracted_receipt": extracted,
            "retrieved_policies": state.get("retrieved_policies", []),
            "employee_remaining_quota": state.get("employee_remaining_quota"),
            "audit_decision": audit,
            "human_review_decision": state.get("human_review_decision"),
            "final_status": state.get("final_status", "PENDING"),
            "final_message": state.get("final_message", ""),
            "telemetry": state.get("telemetry", {}),
            "created_at": existing.get("created_at", now_iso),
            "updated_at": now_iso,
        }

        if not self.is_in_memory and self._pool is not None:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO reimbursement_claims (
                        claim_id, employee_id, channel, chat_id, image_url_or_path,
                        user_caption, receipt_hash, is_duplicate, merchant_name,
                        receipt_date, category, total_amount, approved_amount,
                        extracted_receipt, retrieved_policies, audit_decision,
                        human_review_decision, final_status, final_message, updated_at
                    ) VALUES (
                        $1, $2, $3, $4, $5,
                        $6, $7, $8, $9,
                        $10, $11, $12, $13,
                        $14::jsonb, $15::jsonb, $16::jsonb,
                        $17::jsonb, $18, $19, NOW()
                    )
                    ON CONFLICT (claim_id) DO UPDATE SET
                        receipt_hash = EXCLUDED.receipt_hash,
                        is_duplicate = EXCLUDED.is_duplicate,
                        merchant_name = EXCLUDED.merchant_name,
                        receipt_date = EXCLUDED.receipt_date,
                        category = EXCLUDED.category,
                        total_amount = EXCLUDED.total_amount,
                        approved_amount = EXCLUDED.approved_amount,
                        extracted_receipt = EXCLUDED.extracted_receipt,
                        retrieved_policies = EXCLUDED.retrieved_policies,
                        audit_decision = EXCLUDED.audit_decision,
                        human_review_decision = EXCLUDED.human_review_decision,
                        final_status = EXCLUDED.final_status,
                        final_message = EXCLUDED.final_message,
                        updated_at = NOW()
                    """,
                    record["claim_id"],
                    record["employee_id"],
                    record["channel"],
                    record["chat_id"],
                    record["image_url_or_path"],
                    record["user_caption"],
                    record["receipt_hash"],
                    record["is_duplicate"],
                    record["merchant_name"],
                    record["receipt_date"],
                    record["category"],
                    record["total_amount"],
                    record["approved_amount"],
                    json.dumps(record["extracted_receipt"]),
                    json.dumps(record["retrieved_policies"]),
                    json.dumps(record["audit_decision"]),
                    json.dumps(record["human_review_decision"]),
                    record["final_status"],
                    record["final_message"],
                )

        self._claims[claim_id] = record
        return record

    async def get_claim(self, claim_id: str) -> dict[str, Any] | None:
        """Retrieve a claim record by claim_id."""
        if claim_id in self._claims:
            return self._claims[claim_id]

        if not self.is_in_memory and self._pool is not None:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM reimbursement_claims WHERE claim_id = $1",
                    claim_id,
                )
                if row is not None:
                    return dict(row)
        return None

    async def list_claims(self, limit: int = 50) -> list[dict[str, Any]]:
        """List recent reimbursement claims ordered by updated_at descending."""
        items = list(self._claims.values())
        items.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)
        return items[:limit]

    async def record_telemetry(
        self,
        claim_id: str,
        node_name: str,
        latency_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_idr: float = 0.0,
        status: str = "SUCCESS",
        error_message: str | None = None,
    ) -> dict[str, Any]:
        """Store node telemetry event in agent_telemetry table and in-memory buffer."""
        total_tokens = prompt_tokens + completion_tokens
        entry = {
            "claim_id": claim_id,
            "node_name": node_name,
            "latency_ms": round(latency_ms, 2),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_idr": round(cost_idr, 4),
            "status": status,
            "error_message": error_message,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self._telemetry.append(entry)

        if not self.is_in_memory and self._pool is not None:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO agent_telemetry (
                        claim_id, node_name, latency_ms, prompt_tokens,
                        completion_tokens, total_tokens, cost_idr, status, error_message
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    claim_id,
                    node_name,
                    entry["latency_ms"],
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    entry["cost_idr"],
                    status,
                    error_message,
                )
        return entry

    def get_telemetry_entries(self) -> list[dict[str, Any]]:
        """Return recorded telemetry events."""
        return list(self._telemetry)


db_manager = DatabaseManager()
