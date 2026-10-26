"""State schema and Pydantic v2 validation models for KlaimKilat AI."""

from typing import Literal, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class ReceiptItem(BaseModel):
    """Single line item extracted from a receipt."""

    item_name: str = Field(description="Nama barang atau jasa pada struk")
    quantity: int = Field(default=1, ge=1)
    unit_price: int = Field(description="Harga satuan dalam Rupiah")
    subtotal: int = Field(description="Total harga item dalam Rupiah")
    is_restricted: bool = Field(
        default=False,
        description="True jika termasuk item terlarang di SOP seperti rokok/alkohol/pribadi",
    )


class ExtractedReceipt(BaseModel):
    """Structured receipt extracted by Vision/OCR node."""

    merchant_name: str
    receipt_date: str = Field(description="Format YYYY-MM-DD")
    receipt_number: Optional[str] = None
    category: Literal[
        "meals",
        "transport",
        "accommodation",
        "office_supplies",
        "medical",
        "other",
    ]
    items: list[ReceiptItem]
    tax_and_service: int = Field(default=0)
    total_amount: int = Field(description="Total nominal pembayaran dalam Rupiah")
    ocr_confidence: float = Field(ge=0.0, le=1.0)


class PolicyViolation(BaseModel):
    """Specific SOP violation or soft warning identified during audit."""

    policy_code: str = Field(description="Kode pasal SOP, misal SOP-FIN-04.2")
    description: str = Field(
        description="Penjelasan pelanggaran atau peringatan kebijakan"
    )
    severity: Literal["hard_violation", "soft_warning"]


class AuditDecision(BaseModel):
    """Audit decision produced by DeepSeek reasoning and deterministic guardrails."""

    is_compliant: bool
    recommended_action: Literal[
        "auto_approve", "needs_human_review", "auto_reject"
    ]
    approved_amount: int = Field(
        description="Nominal yang layak diganti setelah dipotong item non-compliant jika ada"
    )
    violations: list[PolicyViolation] = Field(default_factory=list)
    audit_summary: str = Field(
        description="Ringkasan objektif untuk karyawan dan Manajer Finance"
    )


class ReimbursementAgentState(TypedDict, total=False):
    """LangGraph State Schema for Smart Expense & Reimbursement Automation Agent."""

    claim_id: str
    employee_id: str
    channel: Literal["telegram", "whatsapp"]
    chat_id: str
    image_url_or_path: str
    user_caption: str
    raw_ocr_text: Optional[str]
    receipt_hash: Optional[str]
    is_duplicate: bool
    extracted_receipt: Optional[dict]        # Serialized ExtractedReceipt
    retrieved_policies: list[dict]           # Hasil Hybrid Search pgvector
    employee_remaining_quota: Optional[int]  # Hasil Tool Calling database
    audit_decision: Optional[dict]           # Serialized AuditDecision
    human_review_decision: Optional[dict]    # Output dari interrupt() / Command(resume=...)
    final_status: Literal[
        "PENDING",
        "APPROVED",
        "PARTIALLY_APPROVED",
        "REJECTED",
        "ESCALATED",
    ]
    final_message: str
    telemetry: dict                          # Latency per node, token count, cost_idr, errors
