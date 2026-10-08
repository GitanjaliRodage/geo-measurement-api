from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Override any value with a GEO_* environment variable."""

    model_config = SettingsConfigDict(env_prefix="GEO_")

    database_url: str = "sqlite:///./geo_api.db"
    max_upload_mb: int = 50
    # Guards against zip bombs: limits on what a .zip may expand to.
    max_zip_uncompressed_mb: int = 500
    max_zip_members: int = 200


settings = Settings()
