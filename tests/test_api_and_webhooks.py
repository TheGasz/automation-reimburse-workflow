"""Integration tests for FastAPI REST endpoints, Telegram/WhatsApp webhooks, and Observability metrics."""

from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.db.session import db_manager
from app.main import app


@pytest.fixture(autouse=True)
def reset_db() -> None:
    """Reset in-memory DB state before each API test."""
    db_manager.reset_in_memory_state()


@pytest.mark.asyncio
async def test_health_and_scanner_portal_endpoints() -> None:
    """Verify /health and / interactive scanner portal return 200 OK."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health_res = await client.get("/health")
        assert health_res.status_code == 200
        health_json = health_res.json()
        assert health_json["status"] == "healthy"
        assert health_json["components"]["sop_policy_chunks_loaded"] >= 10

        portal_res = await client.get("/")
        assert portal_res.status_code == 200
        assert "KlaimKilat AI" in portal_res.text

        presets_res = await client.get("/api/v1/claims/presets/list")
        assert presets_res.status_code == 200
        assert len(presets_res.json()["presets"]) == 6


@pytest.mark.asyncio
async def test_rest_submit_image_upload_and_detail_endpoint() -> None:
    """Verify POST /api/v1/claims/submit with multipart image upload and GET /api/v1/claims/{claim_id}."""
    img = Image.new("RGB", (120, 120), color=(240, 240, 240))
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/claims/submit",
            data={
                "employee_id": "EMP-001",
                "caption": "Beli air mineral rapat cabang",
                "preset_key": "indomaret_snack_rapat",
            },
            files={"image_file": ("struk_indomaret.png", buf, "image/png")},
        )
        assert res.status_code == 200
        payload = res.json()
        claim_id = payload["claim_id"]
        assert payload["final_status"] == "APPROVED"
        assert payload["audit_decision"]["approved_amount"] == 98_000

        detail_res = await client.get(f"/api/v1/claims/{claim_id}")
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert detail["claim_id"] == claim_id
        assert detail["merchant_name"] == "Indomaret Cabang Gubeng Surabaya"
        assert isinstance(detail["checkpoint_history"], list)


@pytest.mark.asyncio
async def test_telegram_webhook_photo_and_manager_callback_resume() -> None:
    """Verify end-to-end Telegram Bot photo submission -> ESCALATED -> Inline Button Callback -> APPROVED."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Employee sends high-value client dinner receipt photo on Telegram
        tg_msg_update = {
            "update_id": 10001,
            "message": {
                "message_id": 501,
                "from": {"id": 777001, "username": "budi_dbklik"},
                "chat": {"id": 777001, "type": "private"},
                "employee_id": "EMP-001",
                "caption": "Jamuan makan malam klien PT Maju Jaya proyek laptop (4 orang)",
                "photo": [
                    {
                        "file_id": "restoran_klien_high_value",
                        "width": 800,
                        "height": 1200,
                    }
                ],
            },
        }
        msg_res = await client.post("/api/v1/webhooks/telegram", json=tg_msg_update)
        assert msg_res.status_code == 200
        msg_data = msg_res.json()
        claim_id = msg_data["claim_id"]
        assert msg_data["final_status"] == "ESCALATED"
        assert msg_data["approval_card"]["total_amount"] == 522_500

        # 2. Finance Manager clicks Inline Keyboard button to Approve Full (Rp522.500)
        tg_callback_update = {
            "update_id": 10002,
            "callback_query": {
                "id": "cb_999",
                "from": {"id": 987654321, "username": "manager_finance"},
                "data": f"claim:{claim_id}:approve:522500",
            },
        }
        cb_res = await client.post("/api/v1/webhooks/telegram", json=tg_callback_update)
        assert cb_res.status_code == 200
        cb_data = cb_res.json()
        assert cb_data["event_type"] == "callback_query_resumed"
        assert cb_data["claim_id"] == claim_id
        assert cb_data["final_status"] == "APPROVED"
        assert cb_data["approved_amount"] == 522_500


@pytest.mark.asyncio
async def test_rest_decision_resume_and_metrics_summary() -> None:
    """Verify POST /api/v1/claims/{claim_id}/decision and GET /api/v1/metrics/summary."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Submit mixed receipt (ATK + Rokok) -> ESCALATED
        sub_res = await client.post(
            "/api/v1/claims/submit",
            data={
                "employee_id": "EMP-002",
                "caption": "Beli lakban dan kertas thermal kasir",
                "preset_key": "struk_gabungan_atk_dan_rokok",
            },
        )
        assert sub_res.status_code == 200
        claim_id = sub_res.json()["claim_id"]
        assert sub_res.json()["final_status"] == "ESCALATED"

        # Manager approves partial recommended amount (Rp120.000) via REST endpoint
        dec_res = await client.post(
            f"/api/v1/claims/{claim_id}/decision",
            json={
                "approver_id": "FIN-MGR-01",
                "action": "approve_partial",
                "approved_amount": 120_000,
                "note": "Potong item rokok pribadi Rp35.000.",
            },
        )
        assert dec_res.status_code == 200
        assert dec_res.json()["final_status"] == "PARTIALLY_APPROVED"

        # Check metrics summary endpoint
        metrics_res = await client.get("/api/v1/metrics/summary")
        assert metrics_res.status_code == 200
        metrics = metrics_res.json()
        assert metrics["total_claims"] >= 1
        assert metrics["latency"]["meets_sla"] is True
        assert metrics["tokens_and_cost"]["meets_cost_target"] is True
        assert metrics["reliability"]["error_rate_pct"] == 0.0
