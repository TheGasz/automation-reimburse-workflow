"""Benchmark evaluation script comparing Pure Vector Search vs Keyword Search vs Hybrid Search (RRF).

Evaluates 40 realistic Indonesian reimbursement claim scenarios against SOP Keuangan 2026
and verifies PRD targets: Recall@4 >= 0.90 and MRR >= 0.82.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.agent.nodes.policy_rag import policy_rag_engine

# 40 Golden Retrieval Benchmark Scenarios covering semantic paraphrases, exact SOP codes, and rare terms
RAG_BENCHMARK_SCENARIOS: list[dict[str, Any]] = [
    # SOP-FIN-01.1: Batas waktu 14 hari & validitas struk
    {"id": "Q01", "query": "Klaim nota makan dari tiga minggu lalu lewat 14 hari kalender", "category": "general", "expected_code": "SOP-FIN-01.1"},
    {"id": "Q02", "query": "Apakah struk transaksi bulan lalu yang sudah expired masih bisa diajukan?", "category": "general", "expected_code": "SOP-FIN-01.1"},
    {"id": "Q03", "query": "Ketentuan pasal SOP-FIN-01.1", "category": "general", "expected_code": "SOP-FIN-01.1"},
    {"id": "Q04", "query": "Nota tidak mencantumkan tanggal transaksi dan rincian item", "category": "general", "expected_code": "SOP-FIN-01.1"},
    # SOP-FIN-01.2: Klaim ganda & ambang batas Auto-Approve Rp250.000
    {"id": "Q05", "query": "Karyawan tidak sengaja kirim foto struk yang sama dua kali double claim", "category": "general", "expected_code": "SOP-FIN-01.2"},
    {"id": "Q06", "query": "Berapa batas maksimal nominal klaim agar otomatis disetujui auto-approve?", "category": "general", "expected_code": "SOP-FIN-01.2"},
    {"id": "Q07", "query": "Deteksi klaim duplikat menggunakan perceptual hash gambar", "category": "general", "expected_code": "SOP-FIN-01.2"},
    {"id": "Q08", "query": "Aturan pasal SOP-FIN-01.2", "category": "general", "expected_code": "SOP-FIN-01.2"},
    # SOP-FIN-02.1: Item terlarang (rokok, alkohol, pribadi, struk gabungan)
    {"id": "Q09", "query": "Struk minimarket ada beli rokok Sampoerna Mild dan korek api", "category": "general", "expected_code": "SOP-FIN-02.1"},
    {"id": "Q10", "query": "Jamuan makan malam tapi ada pesanan bir Bintang dan wine beralkohol", "category": "general", "expected_code": "SOP-FIN-02.1"},
    {"id": "Q11", "query": "Beli liquid vape pod dan parfum kosmetik pribadi di struk gabungan", "category": "general", "expected_code": "SOP-FIN-02.1"},
    {"id": "Q12", "query": "Pelanggaran keras hard_violation pada pasal SOP-FIN-02.1", "category": "general", "expected_code": "SOP-FIN-02.1"},
    # SOP-FIN-03.1: Makan perjalanan dinas, lembur, jamuan klien
    {"id": "Q13", "query": "Plafon makan malam lembur karyawan setelah kerja tambahan 3 jam", "category": "meals", "expected_code": "SOP-FIN-03.1"},
    {"id": "Q14", "query": "Santap malam bersama klien proyek pengadaan laptop di restoran", "category": "meals", "expected_code": "SOP-FIN-03.1"},
    {"id": "Q15", "query": "Konsumsi lembur akhir pekan hari Sabtu tanpa lampiran surat tugas lembur", "category": "meals", "expected_code": "SOP-FIN-03.1"},
    {"id": "Q16", "query": "Jatah uang makan harian saat perjalanan dinas luar kota Rp75.000", "category": "meals", "expected_code": "SOP-FIN-03.1"},
    # SOP-FIN-03.2: Kopi, snack rapat, air mineral cabang
    {"id": "Q17", "query": "Beli air mineral dus Aqua dan kopi untuk rapat internal cabang di Indomaret", "category": "meals", "expected_code": "SOP-FIN-03.2"},
    {"id": "Q18", "query": "Pembelian roti dan snack rapat untuk tamu cabang di Alfamart", "category": "meals", "expected_code": "SOP-FIN-03.2"},
    {"id": "Q19", "query": "Ketentuan SOP-FIN-03.2 konsumsi rapat internal di minimarket", "category": "meals", "expected_code": "SOP-FIN-03.2"},
    {"id": "Q20", "query": "Klaim teh kotak dan kue rapat operasional toko di bawah 250rb", "category": "meals", "expected_code": "SOP-FIN-03.2"},
    # SOP-FIN-04.1: Transportasi online, BBM, e-toll, parkir
    {"id": "Q21", "query": "Struk gardu jalan tol dan pemotongan saldo e-toll Flazz BCA", "category": "transport", "expected_code": "SOP-FIN-04.1"},
    {"id": "Q22", "query": "Isi bensin BBM Pertamax mobil operasional cabang di SPBU Pertamina", "category": "transport", "expected_code": "SOP-FIN-04.1"},
    {"id": "Q23", "query": "Naik taksi Bluebird dan Gojek menuju bandara Juanda", "category": "transport", "expected_code": "SOP-FIN-04.1"},
    {"id": "Q24", "query": "Karcis parkir resmi gedung klien dan kartu e-money Mandiri SOP-FIN-04.1", "category": "transport", "expected_code": "SOP-FIN-04.1"},
    # SOP-FIN-04.2: Logistik kurir & ekspedisi cabang
    {"id": "Q25", "query": "Biaya kirim paket sparepart mendadak ke cabang pakai JNE dan J&T", "category": "transport", "expected_code": "SOP-FIN-04.2"},
    {"id": "Q26", "query": "Ongkir pengiriman dokumen kontrak via kurir instan GoSend Lalamove", "category": "transport", "expected_code": "SOP-FIN-04.2"},
    {"id": "Q27", "query": "Sewa kargo ekspedisi SiCepat di atas Rp250.000 pasal SOP-FIN-04.2", "category": "transport", "expected_code": "SOP-FIN-04.2"},
    {"id": "Q28", "query": "Resi pembayaran pengiriman barang antar-cabang Pos Indonesia", "category": "transport", "expected_code": "SOP-FIN-04.2"},
    # SOP-FIN-05.1: Akomodasi hotel & perjalanan dinas luar kota
    {"id": "Q29", "query": "Biaya menginap hotel bintang 3 saat perjalanan dinas luar kota Rp650.000 per malam", "category": "accommodation", "expected_code": "SOP-FIN-05.1"},
    {"id": "Q30", "query": "Tagihan kamar hotel ada tambahan minuman minibar dan laundry pribadi", "category": "accommodation", "expected_code": "SOP-FIN-05.1"},
    {"id": "Q31", "query": "Aturan plafon penginapan guest house dinas pasal SOP-FIN-05.1", "category": "accommodation", "expected_code": "SOP-FIN-05.1"},
    {"id": "Q32", "query": "Potongan biaya spa massage dari invoice akomodasi perjalanan dinas", "category": "accommodation", "expected_code": "SOP-FIN-05.1"},
    # SOP-FIN-06.1: ATK, materai, kebutuhan operasional cabang
    {"id": "Q33", "query": "Pembelian 10 keping materai tempel Rp10.000 untuk tanda tangan kontrak", "category": "office_supplies", "expected_code": "SOP-FIN-06.1"},
    {"id": "Q34", "query": "Beli kertas HVS, kertas thermal printer kasir, dan lakban packing gudang", "category": "office_supplies", "expected_code": "SOP-FIN-06.1"},
    {"id": "Q35", "query": "Beli bubble wrap, tinta printer, dan kabel LAN toko SOP-FIN-06.1", "category": "office_supplies", "expected_code": "SOP-FIN-06.1"},
    {"id": "Q36", "query": "Penggantian lampu toko dan alat tulis kantor mendadak di cabang", "category": "office_supplies", "expected_code": "SOP-FIN-06.1"},
    # SOP-FIN-06.2: Medis darurat & P3K operasional
    {"id": "Q37", "query": "Beli isi kotak obat P3K cabang berupa betadine, plester, dan paracetamol", "category": "medical", "expected_code": "SOP-FIN-06.2"},
    {"id": "Q38", "query": "Kuitansi klinik rawat jalan darurat karena kecelakaan kerja ringan di gudang", "category": "medical", "expected_code": "SOP-FIN-06.2"},
    {"id": "Q39", "query": "Klaim beli suplemen gym fitness dan vitamin kecantikan di apotek", "category": "medical", "expected_code": "SOP-FIN-06.2"},
    {"id": "Q40", "query": "Ketentuan klaim kesehatan darurat pada pasal SOP-FIN-06.2", "category": "medical", "expected_code": "SOP-FIN-06.2"},
]


def _score_rankings(
    results: list[dict[str, Any]], expected_code: str, k: int = 4
) -> tuple[float, float]:
    """Compute Hit@k (0 or 1) and Reciprocal Rank (1/rank or 0) for a single query."""
    for rank_idx, item in enumerate(results[:k], start=1):
        if item.get("policy_code") == expected_code:
            return 1.0, 1.0 / rank_idx
    return 0.0, 0.0


async def evaluate_retrieval_methods() -> dict[str, Any]:
    """Run all 40 benchmark queries across Vector-Only, Keyword-Only, and Hybrid RRF."""
    total = len(RAG_BENCHMARK_SCENARIOS)
    vec_hits = 0.0
    vec_rr = 0.0
    kw_hits = 0.0
    kw_rr = 0.0
    hyb_hits = 0.0
    hyb_rr = 0.0

    for case in RAG_BENCHMARK_SCENARIOS:
        q = case["query"]
        cat = case["category"]
        expected = case["expected_code"]

        vec_res = policy_rag_engine.vector_only_search(query=q, category=cat, top_k=4)
        kw_res = policy_rag_engine.keyword_only_search(query=q, top_k=4)
        hyb_res = await policy_rag_engine.hybrid_rrf_search(
            query=q, category=cat, top_k=4
        )

        vh, vrr = _score_rankings(vec_res, expected, k=4)
        kh, krr = _score_rankings(kw_res, expected, k=4)
        hh, hrr = _score_rankings(hyb_res, expected, k=4)

        vec_hits += vh
        vec_rr += vrr
        kw_hits += kh
        kw_rr += krr
        hyb_hits += hh
        hyb_rr += hrr

    summary = {
        "num_scenarios": total,
        "vector_only": {
            "recall_at_4": round(vec_hits / total, 4),
            "mrr": round(vec_rr / total, 4),
        },
        "keyword_only": {
            "recall_at_4": round(kw_hits / total, 4),
            "mrr": round(kw_rr / total, 4),
        },
        "hybrid_rrf": {
            "recall_at_4": round(hyb_hits / total, 4),
            "mrr": round(hyb_rr / total, 4),
        },
        "meets_prd_targets": (
            (hyb_hits / total) >= 0.90 and (hyb_rr / total) >= 0.82
        ),
    }
    return summary


def main() -> None:
    """CLI entrypoint for running RAG benchmark evaluation."""
    report = asyncio.run(evaluate_retrieval_methods())
    print("=" * 72)
    print("KlaimKilat AI — Hybrid RAG (pgvector + FTS RRF) Benchmark Evaluation")
    print("=" * 72)
    print(json.dumps(report, indent=2))
    assert report["meets_prd_targets"], "Hybrid RAG did not meet minimum PRD targets!"


if __name__ == "__main__":
    main()
