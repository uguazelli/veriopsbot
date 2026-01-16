from pydantic import computed_field
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    postgres_user: str = "veridata_user"
    postgres_password: str = "veridata_pass"
    postgres_host: str = "veridata.postgres"
    postgres_port: int = 5432
    postgres_db: str = "veridata_bot"
    app_port: int = 4019
    admin_user: str = "vd"
    admin_password: str = "vd"
    rag_service_url: str = "http://veridata.rag:8000"
    rag_api_key: str = ""
    google_api_key: str = ""
    openai_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @computed_field
    def database_url(self) -> str:
        return str(
            MultiHostUrl.build(
                scheme="postgresql+asyncpg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )


settings = Settings()
