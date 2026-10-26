# KlaimKilat AI — Smart Omnichannel Reimbursement & Audit Agent

**KlaimKilat AI** adalah sistem otomasi *reimbursement* dan audit klaim operasional karyawan berbasis **LangGraph**, **Hybrid RAG (`pgvector` + Full-Text Search dengan Reciprocal Rank Fusion)**, **DeepSeek API**, **FastAPI**, dan **Redis**. Pekerja cukup memindai (*scan*) atau mengirim foto struk melalui **Portal Web Scanner**, **Telegram Bot**, atau **WhatsApp**, dan agen secara otomatis mengekstrak item struk, mencocokkan pasal SOP Keuangan, memeriksa kuota bulanan karyawan via *Tool Calling*, serta memutuskan:
- **Auto-Approve (`APPROVED`):** Klaim `<= Rp250.000` yang 100% patuh SOP dan kuota mencukupi.
- **Auto-Reject (`REJECTED`):** Klaim duplikat (*double claim*), struk kedaluwarsa (`> 14 hari`), kuota habis (`Rp0`), atau seluruh item terlarang (rokok/alkohol/pribadi).
- **Stateful Human-in-the-Loop (`ESCALATED` -> `interrupt()` / `Command(resume=...)`):** Klaim `> Rp250.000`, struk gabungan (item sah + item pribadi dipotong otomatis), atau peringatan lunak (*soft warning*), lengkap dengan kartu persetujuan interaktif untuk Manajer Finance.

---

## 1. Arsitektur StateGraph LangGraph

```
[Karyawan (Web Scanner / Telegram / WhatsApp)]
       │ (1. Scan / Upload Foto Struk + Caption)
       ▼
[FastAPI Endpoint / Webhook] ──► [Redis Queue / Async Worker]
                                            │
                                            ▼
                            ┌───────────────────────────────┐
                            │   LangGraph Orchestrator      │
                            │   (Stateful Checkpointer)     │
                            └───────────────┬───────────────┘
                                            │
       ┌────────────────────────────────────┼────────────────────────────────────┐
       ▼                                    ▼                                    ▼
[1. ingest_and_dedup_node]         [2. vision_extraction_node]          [3. hybrid_policy_rag_node]
(Perceptual + Content Hash)        (Structured ExtractedReceipt)        (pgvector + FTS RRF k=60)
       │                                    │                                    │
       │ (Duplicate -> Auto-Reject)         │ (Confidence < 0.65 -> Reupload)    ▼
       │                                    │                           [4. quota_and_audit_node]
       │                                    │                           (DeepSeek + SQL Tool Calling)
       │                                    │                                    │
       │                                    │                           (Conditional Edge Router)
       │                                    │                                    │
       │                                    │          ┌─────────────────────────┼─────────────────────────┐
       │                                    │          ▼                         ▼                         ▼
       │                                    │   [auto_approve_node]     [human_approval_node]     [finalize_reject_node]
       │                                    │   (<= 250rb & Patuh)      (interrupt() -> Manajer)  (Langgar SOP / Duplikat)
       └────────────────────────────────────┴──────────┴─────────────────────────┼─────────────────────────┘
                                                                                 ▼
                                                                      [ledger_and_notify_node]
                                                                      (Potong Kuota, Simpan DB, Notif)
```

---

## 2. Fitur Utama

1. **Zero-Friction Receipt Scanning ("Pekerja Tinggal Scan"):**
   Portal Web interaktif di `GET /` (mendukung kamera ponsel `capture="environment"`, unggah file struk, serta 6 preset skenario Golden Receipts) dan integrasi webhook Telegram/WhatsApp.
2. **Hierarchical Markdown + Table-Aware SOP Chunking & Hybrid Search (`pgvector` + RRF):**
   Memotong dokumen SOP Keuangan (`app/db/sop_knowledge_base.md`) dengan *breadcrumb* `[Dokumen: SOP Keuangan 2026 | Bab X | Pasal Y]` dan menggabungkan *Dense Vector Search* (1024-dim) + *Full-Text Search* (`tsvector`) menggunakan **Reciprocal Rank Fusion (RRF, $k=60$)**.
3. **Deterministic + Agentic Audit Engine (`deepseek-chat` + LangChain `@tool`):**
   Dilengkapi `@tool` `get_employee_monthly_balance` dan `check_ReceiptDate_validity` serta *guardrail* anti-*Prompt Injection* yang menjamin **False Auto-Approve Rate = 0%**.
4. **Stateful Human-in-the-Loop (`interrupt` & `Command(resume=...)`):**
   Membekukan *state graph* saat membutuhkan persetujuan Manajer Finance, mengirim *Inline Keyboard* (`Setujui Penuh`, `Setujui Rekomendasi AI`, `Tolak`), dan melanjutkan eksekusi tepat dari titik henti ketika tombol ditekan.
5. **Production Observability & Telemetry:**
   Mencatat `latency_ms` per *node*, `prompt_tokens`, `completion_tokens`, dan estimasi biaya dalam Rupiah (`cost_idr`) ke tabel `agent_telemetry` dan menampilkannya secara *real-time* di `GET /api/v1/metrics/summary`.

---

## 3. Cara Menjalankan Proyek (Quickstart)

### Opsi A: Jalankan Lokal (Tanpa Perlu Daemon Docker — In-Memory / Fallback Aktif Otomatis)

```bash
# 1. Buat virtual environment & install dependensi via uv
uv venv .venv
uv pip install -e ".[dev]"

# 2. Jalankan server FastAPI & Portal Scanner
.venv/Scripts/uvicorn app.main:app --reload --port 8000
```
- **Portal Scanner & Approval Manajer:** Buka `http://localhost:8000/`
- **Swagger UI Dokumentasi API:** Buka `http://localhost:8000/docs`
- **Health Check:** Buka `http://localhost:8000/health`

### Opsi B: Jalankan Full Stack dengan Docker Compose (PostgreSQL `pgvector` + Redis + API + Worker)

```bash
cp .env.example .env
docker compose up --build -d
```

### Opsi C: Deployment di VPS dengan PM2

```bash
pm2 start ecosystem.config.js --env production
```

---

## 4. Verifikasi, Evaluasi Hybrid RAG, & Pengujian Otomatis

```bash
# 1. Jalankan benchmark evaluasi Hybrid Search (40 skenario klaim)
.venv/Scripts/python -m eval.evaluate_rag

# 2. Jalankan seluruh unit & integration test (16 test cases)
.venv/Scripts/pytest -v

# 3. Jalankan Linter (Ruff) & Type Checker (Mypy)
.venv/Scripts/ruff check app tests eval
.venv/Scripts/mypy app tests eval
```

### Hasil Benchmark Hybrid RAG (`eval/evaluate_rag.py` — 40 Skenario)
| Metode Retrieval | Recall@4 (Target >= 0.90) | MRR (Target >= 0.82) |
| :--- | :---: | :---: |
| **Vector Search Only** | `1.0000` | `1.0000` |
| **Keyword Search Only (FTS)** | `1.0000` | `0.9583` |
| **Hybrid Search (RRF, k=60)** | **`1.0000`** | **`1.0000`** |

---

## 5. Kontrak Endpoint FastAPI

| Method | Endpoint | Deskripsi |
| :--- | :--- | :--- |
| `GET` | `/` | Portal Web Interaktif *Smart Receipt Scanner* (Pekerja) & *Approval Console* (Manajer Finance) |
| `POST` | `/api/v1/claims/submit` | Mengajukan klaim baru via unggah foto struk (`Multipart`) atau pilihan skenario |
| `POST` | `/api/v1/claims/{claim_id}/decision` | Melanjutkan *state graph* yang di-`interrupt` berdasarkan keputusan Manajer Finance |
| `GET` | `/api/v1/claims/{claim_id}` | Mengambil detail klaim, ekstraksi struk, pasal SOP RAG, dan riwayat *checkpoint* LangGraph |
| `GET` | `/api/v1/claims` | Menampilkan daftar klaim terbaru beserta sisa kuota bulanan karyawan |
| `POST` | `/api/v1/webhooks/telegram` | Webhook Telegram Bot API untuk foto struk baru & *callback* tombol *Inline Keyboard* |
| `POST` | `/api/v1/webhooks/whatsapp` | Webhook WhatsApp Gateway untuk pengajuan klaim struk |
| `GET` | `/api/v1/metrics/summary` | Ringkasan telemetri produksi (latensi p50/p95, *error rate*, biaya token IDR, rasio keputusan) |
| `GET` | `/health` | Pemeriksaan status konektivitas PostgreSQL (`pgvector`), Redis, dan LLM |
