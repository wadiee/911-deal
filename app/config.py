from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    anthropic_api_key: str
    admin_secret: str = "change_me"

    class Config:
        env_file = ".env"


settings = Settings()
