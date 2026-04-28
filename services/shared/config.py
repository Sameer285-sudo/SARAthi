from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "PDS360 AI Platform"

    # Default: SQLite so the app runs without Docker/PostgreSQL.
    # Override in env/.env:
    #   Local Postgres: DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pds360
    #   Render:        DATABASE_URL=postgresql://user:pass@host/db   (auto-normalized to psycopg driver)
    database_url: str = f"sqlite:///{_ROOT / 'pds360.db'}"

    smart_allot_artifacts_dir: str = str(_ROOT / "ml" / "smart_allot" / "artifacts")

    # Twilio credentials (optional — IVR works only when set)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # AI credentials (optional — rule-based fallbacks used when absent)
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Public base URL for Twilio webhooks (use ngrok for local dev)
    public_base_url: str = "http://localhost:8005"

    model_config = SettingsConfigDict(
        env_file=str(_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
