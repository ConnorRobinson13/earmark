from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://budget:budget@postgres:5432/budget"
    ollama_url: str = "http://host.docker.internal:11434"
    # Swapping this needs a matching `constants.EMBEDDING_DIM` and a migration:
    # the vector width is baked into the transactions table.
    embedding_model: str = "mxbai-embed-large"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "sandbox"
    plaid_sync_floor_date: str = "2026-05-14"  # ignore Plaid txns dated before this


settings = Settings()
