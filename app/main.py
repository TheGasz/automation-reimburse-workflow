"""FastAPI Application Entrypoint with Lifespan Checkpointer & Interactive Receipt Scanner Portal."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.agent.nodes.policy_rag import policy_rag_engine
from app.api.claims import router as claims_router
from app.api.metrics import router as metrics_router
from app.api.webhooks import router as webhooks_router
from app.config import get_settings
from app.db.session import db_manager
from app.services.queue_worker import queue_manager


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize database pool, seed SOP pgvector chunks, and connect Redis queue."""
    await db_manager.connect()
    await policy_rag_engine.seed_postgres_if_available()
    await queue_manager.connect()
    yield
    await queue_manager.disconnect()
    await db_manager.disconnect()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Smart Omnichannel Reimbursement & Audit Agent powered by LangGraph, "
        "Hybrid RAG (pgvector + RRF), and DeepSeek."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhooks_router)
app.include_router(claims_router)
app.include_router(metrics_router)


@app.get("/health", tags=["System"])
async def health_check() -> dict[str, Any]:
    """Check connectivity status of PostgreSQL (pgvector), Redis queue, and DeepSeek LLM."""
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": "1.0.0",
        "components": {
            "postgres_pgvector": (
                "in_memory_fallback" if db_manager.is_in_memory else "connected"
            ),
            "redis_queue": (
                "local_async_fallback"
                if queue_manager.is_local_fallback
                else "connected"
            ),
            "deepseek_llm": (
                "deterministic_guardrail_fallback"
                if settings.llm_mock_fallback
                else "live_api"
            ),
            "sop_policy_chunks_loaded": len(policy_rag_engine.chunks),
        },
    }


SCANNER_PORTAL_HTML = """<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>KlaimKilat AI — Smart Receipt Scanner & Finance Audit Portal</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b1120;
      --card: #131c31;
      --border: #233252;
      --text: #f1f5f9;
      --muted: #94a3b8;
      --primary: #38bdf8;
      --success: #22c55e;
      --warning: #f59e0b;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: system-ui, -apple-system, sans-serif; }
    body { background: var(--bg); color: var(--text); padding: 1.5rem; max-width: 1280px; margin: 0 auto; line-height: 1.5; }
    header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; gap: 1rem; }
    h1 { font-size: 1.4rem; color: var(--primary); }
    .badge { background: #1e293b; border: 1px solid var(--border); padding: 0.25rem 0.65rem; border-radius: 999px; font-size: 0.8rem; }
    .grid { display: grid; grid-template-columns: 1fr 1.25fr; gap: 1.5rem; }
    @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 0.75rem; padding: 1.25rem; margin-bottom: 1.25rem; }
    .card h2 { font-size: 1.05rem; margin-bottom: 0.85rem; color: #e2e8f0; }
    label { display: block; font-size: 0.85rem; color: var(--muted); margin-bottom: 0.3rem; margin-top: 0.75rem; }
    select, input, textarea { width: 100%; background: #0f172a; border: 1px solid var(--border); color: var(--text); padding: 0.6rem; border-radius: 0.5rem; font-size: 0.9rem; }
    button { background: var(--primary); color: #020617; font-weight: 600; border: none; padding: 0.65rem 1rem; border-radius: 0.5rem; cursor: pointer; margin-top: 1rem; width: 100%; font-size: 0.92rem; }
    button:hover { opacity: 0.92; }
    .btn-row { display: flex; gap: 0.5rem; margin-top: 0.75rem; }
    .btn-approve { background: var(--success); color: #052e16; }
    .btn-partial { background: var(--warning); color: #451a03; }
    .btn-reject { background: var(--danger); color: #450a0a; }
    pre { background: #090d16; padding: 0.75rem; border-radius: 0.5rem; overflow-x: auto; font-size: 0.8rem; border: 1px solid var(--border); color: #cbd5e1; white-space: pre-wrap; }
    .status-pill { display: inline-block; padding: 0.15rem 0.55rem; border-radius: 0.35rem; font-size: 0.75rem; font-weight: 700; }
    .status-APPROVED { background: rgba(34,197,94,0.2); color: #4ade80; }
    .status-PARTIALLY_APPROVED { background: rgba(245,158,11,0.2); color: #fbbf24; }
    .status-ESCALATED { background: rgba(56,189,248,0.2); color: #38bdf8; }
    .status-REJECTED { background: rgba(239,68,68,0.2); color: #f87171; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>⚡ KlaimKilat AI — Smart Receipt Scanner & Finance Audit</h1>
      <p style="color: var(--muted); font-size: 0.88rem;">Pekerja tinggal scan foto struk • Hybrid RAG (pgvector + RRF) • DeepSeek Audit • Stateful HITL Approval</p>
    </div>
    <div>
      <a href="/docs" style="color: var(--primary); text-decoration: none; font-size: 0.88rem; margin-right: 1rem;">📄 Swagger API Docs</a>
      <span class="badge" id="metrics-badge">Memuat metrik...</span>
    </div>
  </header>

  <div class="grid">
    <div>
      <div class="card">
        <h2>📸 1. Scan / Upload Struk Klaim Baru (Pekerja)</h2>
        <form id="scan-form">
          <label for="employee_id">Pilih Karyawan Pemohon</label>
          <select id="employee_id" name="employee_id">
            <option value="EMP-001">EMP-001 — Budi Santoso (Sales Surabaya)</option>
            <option value="EMP-002">EMP-002 — Siti Rahma (Operasional & Logistik)</option>
            <option value="EMP-003">EMP-003 — Andi Wijaya (IT & Infra)</option>
            <option value="EMP-ZERO">EMP-ZERO — Doni (Simulasi Kuota Habis Rp0)</option>
          </select>

          <label for="preset_key">Pilih Skenario Struk Cepat (Atau Upload File Struk)</label>
          <select id="preset_key" name="preset_key"></select>

          <label for="image_file">Atau Ambil Foto / Upload File Struk (Kamera HP / File)</label>
          <input type="file" id="image_file" name="image_file" accept="image/*" capture="environment" />

          <label for="caption">Catatan Singkat Klaim</label>
          <input type="text" id="caption" name="caption" placeholder="Contoh: Reimburse konsumsi rapat cabang Surabaya" />

          <label for="raw_ocr_text">Pratinjau / Edit Teks OCR Struk</label>
          <textarea id="raw_ocr_text" name="raw_ocr_text" rows="6"></textarea>

          <button type="submit" id="submit-btn">🚀 Scan & Proses Klaim Sekarang</button>
        </form>
      </div>
    </div>

    <div>
      <div class="card">
        <h2>🔍 2. Hasil Ekstraksi Vision, Pasal SOP (RAG), & Keputusan Audit AI</h2>
        <div id="latest-result">
          <p style="color: var(--muted); font-size: 0.9rem;">Pilih skenario struk di sebelah kiri lalu klik <b>Scan & Proses Klaim Sekarang</b>.</p>
        </div>
      </div>

      <div class="card">
        <h2>📋 3. Antrean Persetujuan Manajer Finance (HITL) & Riwayat Klaim</h2>
        <div id="claims-list"></div>
      </div>
    </div>
  </div>

  <script>
    let presetsData = [];

    async function loadPresets() {
      const res = await fetch('/api/v1/claims/presets/list');
      const data = await res.json();
      presetsData = data.presets || [];
      const sel = document.getElementById('preset_key');
      sel.innerHTML = presetsData.map(p => `<option value="${p.preset_key}">${p.sample_id}: ${p.title}</option>`).join('');
      if (presetsData.length > 0) applyPreset(presetsData[0].preset_key);
      sel.addEventListener('change', (e) => applyPreset(e.target.value));
    }

    function applyPreset(key) {
      const found = presetsData.find(p => p.preset_key === key);
      if (!found) return;
      document.getElementById('employee_id').value = found.employee_id;
      document.getElementById('caption').value = found.caption;
      document.getElementById('raw_ocr_text').value = found.raw_ocr_text;
    }

    async function refreshDashboard() {
      const [claimsRes, metricsRes] = await Promise.all([
        fetch('/api/v1/claims'),
        fetch('/api/v1/metrics/summary')
      ]);
      const claimsData = await claimsRes.json();
      const metrics = await metricsRes.json();

      document.getElementById('metrics-badge').textContent =
        `Claims: ${metrics.total_claims} | p95: ${metrics.latency.e2e_p95_ms}ms | Avg Cost: Rp${metrics.tokens_and_cost.avg_cost_per_claim_idr}`;

      const listEl = document.getElementById('claims-list');
      const claims = claimsData.claims || [];
      if (claims.length === 0) {
        listEl.innerHTML = '<p style="color: var(--muted); font-size: 0.88rem;">Belum ada riwayat klaim.</p>';
        return;
      }
      listEl.innerHTML = claims.map(c => {
        const isEscalated = c.final_status === 'ESCALATED';
        const recAmount = (c.audit_decision && c.audit_decision.approved_amount) || 0;
        return `
          <div style="border-bottom: 1px solid var(--border); padding: 0.75rem 0;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <strong>${c.claim_id} — ${c.merchant_name || 'Merchant'} (Rp${Number(c.total_amount || 0).toLocaleString('id-ID')})</strong>
              <span class="status-pill status-${c.final_status}">${c.final_status}</span>
            </div>
            <p style="font-size: 0.83rem; color: var(--muted); margin-top: 0.25rem;">${c.final_message || ''}</p>
            ${isEscalated ? `
              <div class="btn-row">
                <button class="btn-approve" onclick="decideClaim('${c.claim_id}', 'approve', ${c.total_amount})">✅ Setujui Penuh (Rp${Number(c.total_amount).toLocaleString('id-ID')})</button>
                <button class="btn-partial" onclick="decideClaim('${c.claim_id}', 'approve_partial', ${recAmount})">⚖️ Setujui Rekomendasi AI (Rp${Number(recAmount).toLocaleString('id-ID')})</button>
                <button class="btn-reject" onclick="decideClaim('${c.claim_id}', 'reject', 0)">❌ Tolak</button>
              </div>
            ` : ''}
          </div>
        `;
      }).join('');
    }

    async function decideClaim(claimId, action, amount) {
      const res = await fetch(`/api/v1/claims/${claimId}/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          approver_id: 'FIN-MGR-WEB',
          action: action,
          approved_amount: amount,
          note: `Keputusan Manajer Finance via Portal (${action})`
        })
      });
      const out = await res.json();
      renderResult(out);
      await refreshDashboard();
    }

    function renderResult(data) {
      const el = document.getElementById('latest-result');
      const policies = (data.retrieved_policies || []).map(p => p.policy_code).join(', ');
      el.innerHTML = `
        <div style="margin-bottom: 0.6rem;">
          <span class="status-pill status-${data.final_status}">${data.final_status}</span>
          <strong style="margin-left: 0.5rem;">${data.claim_id}</strong>
          <span style="color: var(--muted); font-size: 0.82rem; margin-left: 0.5rem;">Pasal RAG: ${policies || '-'}</span>
        </div>
        <p style="font-size: 0.9rem; margin-bottom: 0.6rem;">${data.final_message || ''}</p>
        <pre>${JSON.stringify({
          extracted_receipt: data.extracted_receipt,
          audit_decision: data.audit_decision,
          employee_remaining_quota: data.employee_remaining_quota,
          telemetry: data.telemetry
        }, null, 2)}</pre>
      `;
    }

    document.getElementById('scan-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('submit-btn');
      btn.textContent = '⏳ Memproses OCR + Hybrid RAG + Audit DeepSeek...';
      btn.disabled = true;
      try {
        const formData = new FormData(e.target);
        const res = await fetch('/api/v1/claims/submit', { method: 'POST', body: formData });
        const out = await res.json();
        renderResult(out);
        await refreshDashboard();
      } finally {
        btn.textContent = '🚀 Scan & Proses Klaim Sekarang';
        btn.disabled = false;
      }
    });

    loadPresets().then(refreshDashboard);
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root_scanner_portal() -> HTMLResponse:
    """Serve the interactive KlaimKilat AI Smart Receipt Scanner & Finance Approval Portal."""
    return HTMLResponse(content=SCANNER_PORTAL_HTML)
