from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    database_url: str = "postgresql://app_admin:lockstep@localhost:5433/tsdb"
    eval_admin_url: str = "postgresql://eval_admin:lockstep@localhost:5433/tsdb"
    golden_service_id: str = ""
    fork_backend: str = "template"
    llm_mode: str = "replay"
    gemini_api_key: str = ""
    gemini_fast_model: str = "gemini-flash-latest"
    gemini_strong_model: str = "gemini-pro-latest"
    gemini_embed_model: str = "gemini-embedding-2"
    embed_dim: int = 768
    seed: int = 42
    sim_start_day: int = 60
    llm_query_drafts: bool = True   # LLM_QUERY_DRAFTS=0 skips Gemini query drafting (e.g. to record only term decisions)


@lru_cache
def get_settings() -> Settings:
    return Settings()
