"""Configuration management for KlaimKilat AI using Pydantic BaseSettings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(
        default="KlaimKilat AI — Smart Expense & Reimbursement Agent",
        alias="APP_NAME",
    )
    app_env: str = Field(default="development", alias="APP_ENV")
    debug: bool = Field(default=True, alias="DEBUG")

    # Business Policy Thresholds
    auto_approve_threshold_idr: int = Field(
        default=250_000, alias="AUTO_APPROVE_THRESHOLD_IDR"
    )
    max_receipt_age_days: int = Field(default=14, alias="MAX_RECEIPT_AGE_DAYS")
    ocr_min_confidence: float = Field(default=0.65, alias="OCR_MIN_CONFIDENCE")

    # DeepSeek / LLM Configuration
    deepseek_api_key: str = Field(default="sk-mock-deepseek-key", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com/v1", alias="DEEPSEEK_BASE_URL"
    )
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")
    vision_model: str = Field(default="deepseek-vl2", alias="VISION_MODEL")
    llm_mock_fallback: bool = Field(default=True, alias="LLM_MOCK_FALLBACK")

    # Database & pgvector Configuration
    database_url: str = Field(
        default="postgresql://klaimkilat:klaimkilat_secret@localhost:5432/klaimkilat_db",
        alias="DATABASE_URL",
    )
    use_in_memory_db_fallback: bool = Field(
        default=True, alias="USE_IN_MEMORY_DB_FALLBACK"
    )
    embedding_dimension: int = Field(default=1024, alias="EMBEDDING_DIMENSION")

    # Redis Queue Configuration
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    use_local_queue_fallback: bool = Field(
        default=True, alias="USE_LOCAL_QUEUE_FALLBACK"
    )

    # Omnichannel Bot Credentials
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_finance_manager_chat_id: str = Field(
        default="987654321", alias="TELEGRAM_FINANCE_MANAGER_CHAT_ID"
    )
    whatsapp_gateway_url: str = Field(
        default="http://localhost:3001", alias="WHATSAPP_GATEWAY_URL"
    )
    whatsapp_api_key: str = Field(default="", alias="WHATSAPP_API_KEY")

    # Token Cost Estimation (IDR per 1K tokens for DeepSeek V3)
    cost_per_1k_prompt_tokens_idr: float = Field(
        default=2.2, alias="COST_PER_1K_PROMPT_TOKENS_IDR"
    )
    cost_per_1k_completion_tokens_idr: float = Field(
        default=4.5, alias="COST_PER_1K_COMPLETION_TOKENS_IDR"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton settings instance."""
    return Settings()
