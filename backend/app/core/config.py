from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Modern Library Portal"
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./library_portal.db"
    frontend_origin: str = "http://localhost:5173"
    frontend_origins: str = ""
    demo_mode: bool = True
    recommender_backend: str = "auto"  # auto | lightfm | content
    koha_base_url: str = ""
    koha_opac_url: str = "http://localhost:8080"
    koha_api_prefix: str = "/api/v1"
    koha_auth_method: str = "oauth2"
    koha_api_token: str = ""
    koha_client_id: str = ""
    koha_client_secret: str = ""
    koha_basic_username: str = ""
    koha_basic_password: str = ""
    koha_token_path: str = "/oauth/token"
    app_session_secret: str = ""
    session_cookie_secure: bool = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
