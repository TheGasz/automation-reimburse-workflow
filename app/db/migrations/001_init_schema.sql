-- 001_init_schema.sql
-- KlaimKilat AI Database Schema: pgvector Hybrid Search, Claims Ledger, Employee Quotas, & Telemetry

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Policy Chunks Table (pgvector + Full-Text Search)
CREATE TABLE IF NOT EXISTS policy_chunks (
    chunk_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    policy_code VARCHAR(50) NOT NULL,
    category VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(1024),
    content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('indonesian', content)) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_policy_embedding_hnsw
    ON policy_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_policy_tsv_gin
    ON policy_chunks USING gin (content_tsv);

CREATE INDEX IF NOT EXISTS idx_policy_category
    ON policy_chunks (category);

-- 2. Employee Monthly Quotas Table
CREATE TABLE IF NOT EXISTS employee_quotas (
    employee_id VARCHAR(64) NOT NULL,
    employee_name VARCHAR(120) NOT NULL,
    department VARCHAR(80) NOT NULL,
    category VARCHAR(50) NOT NULL,
    monthly_limit_idr BIGINT NOT NULL,
    used_amount_idr BIGINT NOT NULL DEFAULT 0,
    period_month VARCHAR(7) NOT NULL, -- Format YYYY-MM
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (employee_id, category, period_month)
);

-- 3. Reimbursement Claims Ledger Table
CREATE TABLE IF NOT EXISTS reimbursement_claims (
    claim_id VARCHAR(64) PRIMARY KEY,
    employee_id VARCHAR(64) NOT NULL,
    channel VARCHAR(20) NOT NULL,
    chat_id VARCHAR(64) NOT NULL,
    image_url_or_path TEXT NOT NULL,
    user_caption TEXT NOT NULL DEFAULT '',
    receipt_hash VARCHAR(128),
    is_duplicate BOOLEAN NOT NULL DEFAULT FALSE,
    merchant_name VARCHAR(255),
    receipt_date VARCHAR(20),
    category VARCHAR(50),
    total_amount BIGINT DEFAULT 0,
    approved_amount BIGINT DEFAULT 0,
    extracted_receipt JSONB,
    retrieved_policies JSONB DEFAULT '[]'::jsonb,
    audit_decision JSONB,
    human_review_decision JSONB,
    final_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    final_message TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_claims_receipt_hash
    ON reimbursement_claims (receipt_hash);

CREATE INDEX IF NOT EXISTS idx_claims_employee_status
    ON reimbursement_claims (employee_id, final_status);

-- 4. Agent Telemetry Table (Observability: Latency, Token Usage, Cost IDR)
CREATE TABLE IF NOT EXISTS agent_telemetry (
    telemetry_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id VARCHAR(64) NOT NULL,
    node_name VARCHAR(64) NOT NULL,
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    total_tokens INT NOT NULL DEFAULT 0,
    cost_idr DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    status VARCHAR(20) NOT NULL DEFAULT 'SUCCESS',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telemetry_claim_id
    ON agent_telemetry (claim_id);

CREATE INDEX IF NOT EXISTS idx_telemetry_created_at
    ON agent_telemetry (created_at);
