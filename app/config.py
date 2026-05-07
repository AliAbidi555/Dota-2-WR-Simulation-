from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    opendota_api_key: str = ""
    default_match_limit: int = 20
    friends_file: Path = ROOT_DIR / "friends.json"

    @property
    def opendota_base_url(self) -> str:
        return "https://api.opendota.com/api"


settings = Settings()
