"""Unit tests for SOP Hierarchical Chunking and Hybrid Search (pgvector + FTS RRF)."""

import pytest

from app.agent.nodes.policy_rag import (
    chunk_sop_markdown,
    hybrid_policy_rag_node,
    policy_rag_engine,
)
from eval.evaluate_rag import evaluate_retrieval_methods


def test_chunk_sop_markdown_preserves_breadcrumbs_and_metadata() -> None:
    """Verify every SOP chunk includes breadcrumb header and required JSONB metadata."""
    chunks = chunk_sop_markdown()
    assert len(chunks) >= 10

    for chunk in chunks:
        assert chunk["content"].startswith("[Dokumen: SOP Keuangan 2026 |")
        metadata = chunk["metadata"]
        assert "chapter" in metadata
        assert "article" in metadata
        assert "category" in metadata
        assert "effective_date" in metadata
        assert metadata["policy_code"].startswith("SOP-FIN-")
        assert len(chunk["embedding"]) == 1024


@pytest.mark.asyncio
async def test_hybrid_rrf_search_exact_keywords_and_semantic_queries() -> None:
    """Verify Hybrid RRF retrieves exact keyword anchors ('materai', 'e-toll') and semantic paraphrases."""
    # 1. Exact keyword anchor: materai
    materai_res = await policy_rag_engine.hybrid_rrf_search(
        query="pembelian materai tempel 10.000 untuk kontrak cabang",
        category="office_supplies",
        top_k=4,
    )
    assert materai_res[0]["policy_code"] == "SOP-FIN-06.1"

    # 2. Exact keyword anchor: e-toll
    etoll_res = await policy_rag_engine.hybrid_rrf_search(
        query="potongan saldo kartu e-toll flazz gardu tol",
        category="transport",
        top_k=4,
    )
    assert etoll_res[0]["policy_code"] == "SOP-FIN-04.1"

    # 3. Semantic query: jamuan makan malam klien
    meals_res = await policy_rag_engine.hybrid_rrf_search(
        query="santap malam bersama mitra klien proyek di rumah makan",
        category="meals",
        top_k=4,
    )
    assert meals_res[0]["policy_code"] == "SOP-FIN-03.1"


@pytest.mark.asyncio
async def test_hybrid_policy_rag_node_updates_state_and_telemetry() -> None:
    """Verify LangGraph hybrid_policy_rag_node populates retrieved_policies and telemetry."""
    state = {
        "claim_id": "CLM-TEST-RAG-01",
        "user_caption": "Beli lakban dan rokok di Indomaret",
        "extracted_receipt": {
            "merchant_name": "Indomaret",
            "category": "office_supplies",
            "total_amount": 155000,
            "items": [
                {"item_name": "Lakban Packing", "is_restricted": False},
                {"item_name": "Rokok Surya", "is_restricted": True},
            ],
        },
        "telemetry": {},
    }
    output = await hybrid_policy_rag_node(state)
    policies = output["retrieved_policies"]
    assert len(policies) == 4
    codes = {p["policy_code"] for p in policies}
    assert "SOP-FIN-06.1" in codes
    assert "SOP-FIN-02.1" in codes
    assert "hybrid_policy_rag_node" in output["telemetry"]["nodes"]


@pytest.mark.asyncio
async def test_rag_benchmark_exceeds_prd_targets() -> None:
    """Verify 40-scenario RAG evaluation meets Recall@4 >= 0.90 and MRR >= 0.82."""
    report = await evaluate_retrieval_methods()
    assert report["num_scenarios"] == 40
    assert report["hybrid_rrf"]["recall_at_4"] >= 0.90
    assert report["hybrid_rrf"]["mrr"] >= 0.82
    assert (
        report["hybrid_rrf"]["mrr"] >= report["vector_only"]["mrr"]
    ), "Hybrid RRF should match or outperform pure vector search MRR"
    assert (
        report["hybrid_rrf"]["mrr"] >= report["keyword_only"]["mrr"]
    ), "Hybrid RRF should match or outperform pure keyword search MRR"
    assert report["meets_prd_targets"] is True
