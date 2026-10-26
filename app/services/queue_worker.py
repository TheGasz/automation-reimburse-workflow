"""Redis Async Job Queue Worker & Omnichannel Notification Dispatcher (Telegram / WhatsApp)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import redis.asyncio as aioredis

from app.agent.graph import reimbursement_graph, run_reimbursement_claim
from app.agent.state import ReimbursementAgentState
from app.config import get_settings

logger = logging.getLogger(__name__)

QUEUE_KEY = "klaimkilat:claims_queue"


class OmnichannelNotifier:
    """Dispatches messages and interactive Inline Keyboard approval cards to Telegram & WhatsApp."""

    def __init__(self) -> None:
        self.sent_messages: list[dict[str, Any]] = []

    async def send_employee_notification(
        self,
        channel: str,
        chat_id: str,
        claim_id: str,
        final_status: str,
        message: str,
    ) -> dict[str, Any]:
        """Send claim status notification back to the submitting employee."""
        settings = get_settings()
        record = {
            "recipient_role": "employee",
            "channel": channel,
            "chat_id": chat_id,
            "claim_id": claim_id,
            "status": final_status,
            "text": message,
        }
        self.sent_messages.append(record)

        if (
            channel == "telegram"
            and settings.telegram_bot_token
            and not settings.telegram_bot_token.startswith("your-")
        ):
            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(
                        url,
                        json={"chat_id": chat_id, "text": message},
                    )
            except Exception as exc:
                logger.warning("Telegram sendMessage failed: %s", exc)
        return record

    async def send_manager_approval_card(
        self,
        approval_card: dict[str, Any],
    ) -> dict[str, Any]:
        """Send interactive Approval Card with Inline Keyboard buttons to Finance Manager."""
        settings = get_settings()
        manager_chat_id = settings.telegram_finance_manager_chat_id
        text = (
            f"🔔 *[PERLU PERSETUJUAN MANAJER FINANCE]*\n"
            f"• ID Klaim: `{approval_card.get('claim_id')}`\n"
            f"• Karyawan: `{approval_card.get('employee_id')}`\n"
            f"• Merchant: {approval_card.get('merchant_name')}\n"
            f"• Tanggal Struk: {approval_card.get('receipt_date')}\n"
            f"• Total Struk: Rp{int(approval_card.get('total_amount', 0)):,}\n"
            f"• Rekomendasi AI: Rp{int(approval_card.get('recommended_approved_amount', 0)):,}\n"
            f"• Ringkasan Audit: {approval_card.get('audit_summary')}"
        )
        reply_markup = {"inline_keyboard": approval_card.get("inline_keyboard", [])}

        record = {
            "recipient_role": "finance_manager",
            "channel": "telegram",
            "chat_id": manager_chat_id,
            "claim_id": approval_card.get("claim_id"),
            "text": text,
            "reply_markup": reply_markup,
        }
        self.sent_messages.append(record)

        if settings.telegram_bot_token and not settings.telegram_bot_token.startswith(
            "your-"
        ):
            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(
                        url,
                        json={
                            "chat_id": manager_chat_id,
                            "text": text,
                            "parse_mode": "Markdown",
                            "reply_markup": reply_markup,
                        },
                    )
            except Exception as exc:
                logger.warning("Telegram manager card dispatch failed: %s", exc)
        return record


notifier = OmnichannelNotifier()


class ClaimQueueManager:
    """Manages Redis job queue with automatic in-process async execution fallback."""

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._using_local_fallback: bool = True

    async def connect(self) -> None:
        """Connect to Redis or enable local async execution fallback."""
        settings = get_settings()
        try:
            client = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=1.5,
            )
            await client.ping()
            self._redis = client
            self._using_local_fallback = False
            logger.info("Connected to Redis queue at %s", settings.redis_url)
        except Exception as exc:
            self._redis = None
            self._using_local_fallback = True
            logger.info(
                "Redis unavailable (%s); using local async execution fallback.", exc
            )

    async def disconnect(self) -> None:
        """Close Redis connection if open."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    @property
    def is_local_fallback(self) -> bool:
        """Return True if running in local fallback mode without external Redis."""
        return self._using_local_fallback or self._redis is None

    async def enqueue_or_run(
        self,
        initial_state: ReimbursementAgentState,
        wait_for_result: bool = True,
    ) -> dict[str, Any]:
        """Enqueue job into Redis (if worker mode) or execute immediately and dispatch notifications."""
        if not wait_for_result and not self.is_local_fallback and self._redis is not None:
            await self._redis.rpush(QUEUE_KEY, json.dumps(initial_state))
            return {
                "claim_id": initial_state.get("claim_id"),
                "final_status": "QUEUED",
                "final_message": "Klaim masuk antrean pemrosesan Redis.",
            }

        return await process_claim_job(initial_state)


async def process_claim_job(initial_state: ReimbursementAgentState) -> dict[str, Any]:
    """Execute LangGraph reimbursement workflow and send omnichannel notifications."""
    result = await run_reimbursement_claim(initial_state, graph=reimbursement_graph)
    claim_id = str(result.get("claim_id", initial_state.get("claim_id", "")))
    channel = str(result.get("channel", initial_state.get("channel", "telegram")))
    chat_id = str(result.get("chat_id", initial_state.get("chat_id", "")))
    final_status = str(result.get("final_status", "PENDING"))
    final_message = str(result.get("final_message", ""))

    if final_status == "ESCALATED" and "approval_card" in result:
        await notifier.send_manager_approval_card(result["approval_card"])

    if chat_id:
        await notifier.send_employee_notification(
            channel=channel,
            chat_id=chat_id,
            claim_id=claim_id,
            final_status=final_status,
            message=final_message,
        )
    return result


queue_manager = ClaimQueueManager()


async def run_redis_worker_loop() -> None:
    """Continuous Redis BLPOP worker loop for Docker worker service."""
    await queue_manager.connect()
    if queue_manager.is_local_fallback or queue_manager._redis is None:
        logger.warning("Redis is not connected; worker loop exiting.")
        return

    logger.info("KlaimKilat AI Redis Worker listening on %s...", QUEUE_KEY)
    while True:
        item = await queue_manager._redis.blpop(QUEUE_KEY, timeout=5)
        if item is None:
            await asyncio.sleep(0.2)
            continue
        _key, payload_raw = item
        state_payload: ReimbursementAgentState = json.loads(payload_raw)
        await process_claim_job(state_payload)


if __name__ == "__main__":
    asyncio.run(run_redis_worker_loop())
