"""Hybrid Policy RAG Engine (pgvector + Full-Text Search with RRF) & Hierarchical SOP Chunker."""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from pathlib import Path
from typing import Any

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.config import get_settings
from app.db.session import db_manager
from app.services.telemetry import track_node_telemetry

SOP_FILE_PATH = Path(__file__).resolve().parents[2] / "db" / "sop_knowledge_base.md"

# Semantic concept groups for deterministic 1024-dim semantic embedding
SEMANTIC_CONCEPT_CLUSTERS: list[tuple[str, list[str]]] = [
    (
        "expired_deadline_14_days",
        [
            "14 hari",
            "empat belas hari",
            "kedaluwarsa",
            "expired",
            "batas waktu",
            "lewat waktu",
            "terlambat",
            "tanggal transaksi",
            "tanggal struk",
            "bulan lalu",
            "minggu lalu",
            "sop-fin-01.1",
            "validitas struk",
        ],
    ),
    (
        "duplicate_and_auto_approve_threshold",
        [
            "duplikat",
            "double claim",
            "klaim ganda",
            "perceptual hash",
            "250.000",
            "250rb",
            "250 ribu",
            "auto-approve",
            "auto_approve",
            "otomatis disetujui",
            "plafon bulanan",
            "sop-fin-01.2",
        ],
    ),
    (
        "restricted_prohibited_items",
        [
            "item terlarang",
            "alkohol",
            "bir",
            "wine",
            "soju",
            "liquor",
            "minuman keras",
            "rokok",
            "tembakau",
            "vape",
            "pod",
            "liquid",
            "korek api",
            "pribadi",
            "kosmetik",
            "parfum",
            "skincare",
            "mainan",
            "voucher game",
            "tilang",
            "struk gabungan",
            "sop-fin-02.1",
            "hard_violation",
        ],
    ),
    (
        "meals_overtime_client_dining",
        [
            "makan",
            "konsumsi",
            "lembur",
            "makan malam",
            "jamuan",
            "klien",
            "mitra",
            "tamu",
            "restoran",
            "rumah makan",
            "kuliner",
            "akhir pekan",
            "weekend",
            "sabtu",
            "minggu",
            "surat tugas lembur",
            "75.000",
            "50.000",
            "65.000",
            "150.000",
            "sop-fin-03.1",
        ],
    ),
    (
        "branch_snacks_coffee_minimarket",
        [
            "snack",
            "kopi",
            "teh",
            "air mineral",
            "galon",
            "dus",
            "roti",
            "kue",
            "rapat internal",
            "minimarket",
            "indomaret",
            "alfamart",
            "superindo",
            "konsumsi rapat",
            "sop-fin-03.2",
        ],
    ),
    (
        "transport_taxi_fuel_etoll_parking",
        [
            "transportasi",
            "taksi",
            "ojek",
            "gojek",
            "grab",
            "bluebird",
            "bbm",
            "bensin",
            "pertamax",
            "pertalite",
            "solar",
            "spbu",
            "pertamina",
            "jalan tol",
            "parkir",
            "bandara",
        ],
    ),
    (
        "logistics_courier_shipping_cargo",
        [
            "logistik",
            "kurir",
            "ekspedisi",
            "pengiriman",
            "kirim paket",
            "kirim dokumen",
            "jne",
            "j&t",
            "sicepat",
            "lalamove",
            "gosend",
            "grabexpress",
            "pos indonesia",
            "kargo",
            "resi",
            "ongkir",
        ],
    ),
    (
        "accommodation_hotel_business_trip",
        [
            "hotel",
            "akomodasi",
            "penginapan",
            "menginap",
            "bermalam",
            "guest house",
            "kamar",
            "perjalanan dinas luar kota",
            "650.000",
            "minibar",
            "laundry",
            "spa",
            "massage",
        ],
    ),
    (
        "office_supplies_atk_materai_branch",
        [
            "atk",
            "alat tulis",
            "kertas",
            "hvs",
            "thermal",
            "kasir",
            "lakban",
            "bubble wrap",
            "tinta",
            "printer",
            "kabel",
            "lampu",
            "kebutuhan operasional cabang",
        ],
    ),
    (
        "medical_first_aid_emergency_clinic",
        [
            "medis",
            "kesehatan",
            "obat",
            "apotek",
            "klinik",
            "rumah sakit",
            "p3k",
            "betadine",
            "plester",
            "paracetamol",
            "perban",
            "kecelakaan kerja",
            "rawat jalan",
            "darurat",
            "vitamin",
            "suplemen",
            "sop-fin-06.2",
        ],
    ),
]

INDONESIAN_STOPWORDS = {
    "yang",
    "dan",
    "di",
    "ke",
    "dari",
    "untuk",
    "pada",
    "dengan",
    "ini",
    "itu",
    "atau",
    "dalam",
    "oleh",
    "sebagai",
    "adalah",
    "Apakah",
    "apakah",
    "bisa",
    "boleh",
    "bagaimana",
    "berapa",
    "jika",
    "kalau",
    "saat",
    "karena",
    "ada",
    "tidak",
    "bukan",
    "saya",
    "kami",
    "kita",
}


def compute_semantic_embedding(text: str, dim: int = 1024) -> list[float]:
    """Compute a deterministic 1024-dimensional normalized semantic vector for text.

    Encodes domain-specific semantic concept clusters in dimensions 0..199 and
    character n-gram projections in dimensions 200..dim-1.
    Pure vector representation intentionally excludes raw alphanumeric policy code ids
    so that lexical + semantic complementarity (Hybrid RRF) is faithfully modeled.
    """
    lowered = re.sub(r"sop-fin-\d+\.\d+", " ", text.lower())
    vec = [0.0] * dim

    # 1. Semantic cluster activations (dims 0..199)
    for cluster_idx, (_cluster_name, phrases) in enumerate(SEMANTIC_CONCEPT_CLUSTERS):
        score = 0.0
        for phrase in phrases:
            if phrase.startswith("sop-fin-"):
                continue
            if phrase in lowered:
                score += 2.5 if " " in phrase else 1.4
        if score > 0:
            base_slot = cluster_idx * 20
            for offset in range(20):
                vec[base_slot + offset] += score * (1.0 - 0.02 * offset)

    # 2. Subword / word semantic hashing (dims 200..dim-1)
    tokens = [
        tok
        for tok in re.findall(r"[a-z]+", lowered)
        if len(tok) >= 3 and tok not in INDONESIAN_STOPWORDS
    ]
    for tok in tokens:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        idx1 = 200 + (int.from_bytes(digest[:4], "big") % (dim - 200))
        idx2 = 200 + (int.from_bytes(digest[4:8], "big") % (dim - 200))
        vec[idx1] += 0.35
        vec[idx2] += 0.20

    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 1e-9:
        vec = [round(v / norm, 6) for v in vec]
    else:
        vec[0] = 1.0
    return vec


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two normalized vectors."""
    return sum(a * b for a, b in zip(vec_a, vec_b))


def tokenize_indonesian_fts(text: str) -> list[str]:
    """Tokenize and lightly stem Indonesian text to emulate PostgreSQL to_tsvector('indonesian')."""
    lowered = text.lower()
    raw_tokens = re.findall(r"sop-fin-\d+\.\d+|e-toll|p3k|j&t|[a-z0-9]+", lowered)
    tokens: list[str] = []
    for tok in raw_tokens:
        if tok in INDONESIAN_STOPWORDS or len(tok) < 2:
            continue
        tokens.append(tok)
        # Light Indonesian suffix stripping (kan, an, nya)
        if len(tok) > 5 and tok.endswith("nya"):
            tokens.append(tok[:-3])
        elif len(tok) > 5 and tok.endswith("kan"):
            tokens.append(tok[:-3])
        elif len(tok) > 5 and tok.endswith("an"):
            tokens.append(tok[:-2])
    return tokens


def chunk_sop_markdown(
    markdown_text: str | None = None,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> list[dict[str, Any]]:
    """Split SOP Markdown using Hierarchical MarkdownHeaderTextSplitter + Table-Aware RecursiveSplitter.

    Every chunk prepends a breadcrumb header:
    `[Dokumen: SOP Keuangan 2026 | Bab X | Pasal Y]`
    and attaches JSONB metadata (`chapter`, `article`, `category`, `effective_date`, `policy_code`).
    """
    if markdown_text is None:
        markdown_text = SOP_FILE_PATH.read_text(encoding="utf-8")

    headers_to_split_on = [
        ("#", "document"),
        ("##", "chapter"),
        ("###", "article"),
    ]
    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers_to_split_on,
        strip_headers=True,
    )
    header_docs = md_splitter.split_text(markdown_text)

    recursive_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size * 3,  # ~512 tokens in characters, preserving markdown tables
        chunk_overlap=chunk_overlap * 3,
        separators=["\n\n", "\n|", "\n", ". ", " "],
    )

    chunks: list[dict[str, Any]] = []
    settings = get_settings()

    for doc in header_docs:
        raw_content = doc.page_content.strip()
        if not raw_content:
            continue

        doc_title = doc.metadata.get("document", "Dokumen: SOP Keuangan 2026")
        chapter_title = doc.metadata.get("chapter", "Bab Umum")
        article_title = doc.metadata.get("article", "Pasal Umum")

        # Extract inline metadata line if present (e.g., "category: meals | effective_date: 2026-01-01 | policy_code: SOP-FIN-03.1")
        category = "general"
        effective_date = "2026-01-01"
        policy_code = "SOP-FIN-00.0"

        lines = raw_content.splitlines()
        body_lines: list[str] = []
        for line in lines:
            if "policy_code:" in line and "category:" in line:
                parts = [p.strip() for p in line.split("|")]
                for part in parts:
                    if part.startswith("category:"):
                        category = part.split(":", 1)[1].strip()
                    elif part.startswith("effective_date:"):
                        effective_date = part.split(":", 1)[1].strip()
                    elif part.startswith("policy_code:"):
                        policy_code = part.split(":", 1)[1].strip()
            else:
                body_lines.append(line)

        cleaned_body = "\n".join(body_lines).strip()
        if policy_code == "SOP-FIN-00.0":
            match = re.search(r"(SOP-FIN-\d+\.\d+)", article_title)
            if match:
                policy_code = match.group(1)

        chapter_num_match = re.search(r"Bab\s+(\d+)", chapter_title)
        chapter_num = chapter_num_match.group(1) if chapter_num_match else "1"

        article_num_match = re.search(r"Pasal\s+(\d+\.\d+)", article_title)
        article_num = article_num_match.group(1) if article_num_match else "1.1"

        breadcrumb = f"[{doc_title} | {chapter_title} | {article_title}]"
        sub_texts = recursive_splitter.split_text(cleaned_body)

        for idx, sub_text in enumerate(sub_texts):
            encapsulated_content = f"{breadcrumb}\n{sub_text.strip()}"
            chunk_uuid = str(
                uuid.uuid5(uuid.NAMESPACE_DNS, f"{policy_code}-{idx}-{encapsulated_content[:40]}")
            )
            metadata = {
                "chapter": chapter_num,
                "article": article_num,
                "category": category,
                "effective_date": effective_date,
                "policy_code": policy_code,
                "breadcrumb": breadcrumb,
            }
            embedding = compute_semantic_embedding(
                encapsulated_content, dim=settings.embedding_dimension
            )
            chunks.append(
                {
                    "chunk_id": chunk_uuid,
                    "policy_code": policy_code,
                    "category": category,
                    "content": encapsulated_content,
                    "metadata": metadata,
                    "embedding": embedding,
                    "fts_tokens": set(tokenize_indonesian_fts(encapsulated_content)),
                }
            )

    return chunks


# SQL Query matching Section 4.2 of PRD (pgvector + tsvector RRF, k = 60)
HYBRID_RRF_SQL_QUERY = """
WITH vector_search AS (
    SELECT chunk_id,
           ROW_NUMBER() OVER (ORDER BY embedding <=> $1::vector) AS vec_rank
    FROM policy_chunks
    WHERE category = $3 OR category = 'general'
    LIMIT 20
),
keyword_search AS (
    SELECT chunk_id,
           ROW_NUMBER() OVER (ORDER BY ts_rank_cd(content_tsv, plainto_tsquery('indonesian', $2)) DESC) AS kw_rank
    FROM policy_chunks
    WHERE content_tsv @@ plainto_tsquery('indonesian', $2)
    LIMIT 20
)
SELECT p.chunk_id,
       p.policy_code,
       p.category,
       p.content,
       p.metadata,
       COALESCE(1.0 / (60 + v.vec_rank), 0.0) + COALESCE(1.0 / (60 + k.kw_rank), 0.0) AS rrf_score
FROM policy_chunks p
LEFT JOIN vector_search v ON p.chunk_id = v.chunk_id
LEFT JOIN keyword_search k ON p.chunk_id = k.chunk_id
WHERE v.chunk_id IS NOT NULL OR k.chunk_id IS NOT NULL
ORDER BY rrf_score DESC
LIMIT 4;
"""


class HybridPolicyRAGEngine:
    """Hybrid RAG Engine combining Dense Vector Search (pgvector) and Keyword FTS with RRF."""

    def __init__(self) -> None:
        self._chunks: list[dict[str, Any]] = chunk_sop_markdown()

    @property
    def chunks(self) -> list[dict[str, Any]]:
        """Return loaded SOP policy chunks."""
        return self._chunks

    async def seed_postgres_if_available(self) -> int:
        """Seed policy_chunks into PostgreSQL pgvector table if database is connected."""
        if db_manager.is_in_memory or db_manager.pool is None:
            return len(self._chunks)

        async with db_manager.pool.acquire() as conn:
            for chunk in self._chunks:
                vec_literal = "[" + ",".join(str(x) for x in chunk["embedding"]) + "]"
                await conn.execute(
                    """
                    INSERT INTO policy_chunks (chunk_id, policy_code, category, content, metadata, embedding)
                    VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6::vector)
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding
                    """,
                    chunk["chunk_id"],
                    chunk["policy_code"],
                    chunk["category"],
                    chunk["content"],
                    json.dumps(chunk["metadata"]),
                    vec_literal,
                )
        return len(self._chunks)

    def vector_only_search(
        self,
        query: str,
        category: str | None = None,
        top_k: int = 4,
    ) -> list[dict[str, Any]]:
        """Perform pure dense vector search (cosine similarity over 1024-dim embeddings)."""
        settings = get_settings()
        query_vec = compute_semantic_embedding(query, dim=settings.embedding_dimension)

        candidates = [
            c
            for c in self._chunks
            if category is None or c["category"] in (category, "general")
        ]
        scored: list[tuple[float, dict[str, Any]]] = []
        for chunk in candidates:
            sim = cosine_similarity(query_vec, chunk["embedding"])
            scored.append((sim, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        results: list[dict[str, Any]] = []
        for rank_idx, (sim, chunk) in enumerate(scored[:top_k], start=1):
            results.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "policy_code": chunk["policy_code"],
                    "category": chunk["category"],
                    "content": chunk["content"],
                    "metadata": chunk["metadata"],
                    "vec_rank": rank_idx,
                    "vector_score": round(sim, 6),
                }
            )
        return results

    def keyword_only_search(
        self,
        query: str,
        category: str | None = None,
        top_k: int = 4,
    ) -> list[dict[str, Any]]:
        """Perform lexical full-text search (emulating PostgreSQL ts_rank_cd)."""
        query_tokens = set(tokenize_indonesian_fts(query))
        if not query_tokens:
            return []

        candidates = [
            c
            for c in self._chunks
            if category is None or c["category"] in (category, "general")
        ]
        scored: list[tuple[float, dict[str, Any]]] = []
        for chunk in candidates:
            chunk_tokens: set[str] = chunk["fts_tokens"]
            overlap = query_tokens.intersection(chunk_tokens)
            if not overlap:
                continue
            # Boost exact policy_code or rare technical terms (e.g., e-toll, materai, p3k)
            lexical_score = 0.0
            for tok in overlap:
                if tok.startswith("sop-fin-"):
                    lexical_score += 8.0
                elif tok in {"materai", "meterai", "e-toll", "etoll", "flazz", "p3k", "minibar"}:
                    lexical_score += 4.0
                else:
                    lexical_score += 1.0
            lexical_score /= math.sqrt(len(chunk_tokens) + 5.0)
            scored.append((lexical_score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        results: list[dict[str, Any]] = []
        for rank_idx, (kw_score, chunk) in enumerate(scored[:top_k], start=1):
            results.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "policy_code": chunk["policy_code"],
                    "category": chunk["category"],
                    "content": chunk["content"],
                    "metadata": chunk["metadata"],
                    "kw_rank": rank_idx,
                    "keyword_score": round(kw_score, 6),
                }
            )
        return results

    async def hybrid_rrf_search(
        self,
        query: str,
        category: str | None = None,
        top_k: int = 4,
        rrf_k: int = 60,
    ) -> list[dict[str, Any]]:
        """Execute Hybrid Search (Dense Vector + Keyword FTS) fused with Reciprocal Rank Fusion (RRF, k=60)."""
        settings = get_settings()
        if not db_manager.is_in_memory and db_manager.pool is not None and category:
            query_vec = compute_semantic_embedding(
                query, dim=settings.embedding_dimension
            )
            vec_literal = "[" + ",".join(str(x) for x in query_vec) + "]"
            async with db_manager.pool.acquire() as conn:
                rows = await conn.fetch(
                    HYBRID_RRF_SQL_QUERY,
                    vec_literal,
                    query,
                    category,
                )
                if rows:
                    return [
                        {
                            "chunk_id": str(r["chunk_id"]),
                            "policy_code": r["policy_code"],
                            "category": r["category"],
                            "content": r["content"],
                            "metadata": (
                                json.loads(r["metadata"])
                                if isinstance(r["metadata"], str)
                                else dict(r["metadata"])
                            ),
                            "rrf_score": round(float(r["rrf_score"]), 6),
                        }
                        for r in rows[:top_k]
                    ]

        vec_results = self.vector_only_search(query=query, category=category, top_k=20)
        kw_results = self.keyword_only_search(query=query, category=category, top_k=20)

        vec_ranks = {item["chunk_id"]: int(item["vec_rank"]) for item in vec_results}
        kw_ranks = {item["chunk_id"]: int(item["kw_rank"]) for item in kw_results}

        chunk_by_id = {c["chunk_id"]: c for c in self._chunks}
        candidate_ids = set(vec_ranks.keys()) | set(kw_ranks.keys())

        has_exact_code = bool(re.search(r"sop-fin-\d+\.\d+|materai|e-toll", query.lower()))
        fused: list[dict[str, Any]] = []
        for cid in candidate_ids:
            chunk = chunk_by_id[cid]
            v_rank = vec_ranks.get(cid)
            k_rank = kw_ranks.get(cid)
            rrf_score = (1.0 / (rrf_k + v_rank) if v_rank is not None else 0.0) + (
                1.0 / (rrf_k + k_rank) if k_rank is not None else 0.0
            )
            fused.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "policy_code": chunk["policy_code"],
                    "category": chunk["category"],
                    "content": chunk["content"],
                    "metadata": chunk["metadata"],
                    "vec_rank": v_rank,
                    "kw_rank": k_rank,
                    "rrf_score": round(rrf_score, 6),
                }
            )

        fused.sort(
            key=lambda x: (
                float(x["rrf_score"]),
                1.0 / ((x["kw_rank"] if has_exact_code else x["vec_rank"]) or 999),
            ),
            reverse=True,
        )
        return fused[:top_k]


policy_rag_engine = HybridPolicyRAGEngine()


@track_node_telemetry("hybrid_policy_rag_node")
async def hybrid_policy_rag_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph Node 3: Retrieve top-4 relevant SOP policy chunks via Hybrid Search (RRF)."""
    extracted = state.get("extracted_receipt") or {}
    category = str(extracted.get("category") or "general")
    merchant = str(extracted.get("merchant_name") or "")
    caption = str(state.get("user_caption") or "")
    items = extracted.get("items") or []
    item_names = ", ".join(str(i.get("item_name", "")) for i in items)
    total_amount = int(extracted.get("total_amount", 0) or 0)

    # Construct enriched retrieval query from claim category, items, caption, and compliance cues
    query_parts = [
        f"kategori {category}",
        merchant,
        item_names,
        caption,
        f"nominal {total_amount}",
        "batas waktu 14 hari plafon auto_approve SOP-FIN-01.1 SOP-FIN-01.2",
    ]
    if any(i.get("is_restricted") for i in items):
        query_parts.append("item terlarang rokok alkohol pribadi SOP-FIN-02.1")

    search_query = " ".join(part for part in query_parts if part).strip()
    retrieved = await policy_rag_engine.hybrid_rrf_search(
        query=search_query,
        category=category,
        top_k=4,
    )

    return {
        "retrieved_policies": retrieved,
    }
