from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    opendota_api_key: str = ""
    default_match_limit: int = 20
    stratz_api_key: str = ""
    # Stratz RankBracketBasicEnum bracket groups for hero meta queries.
    # Valid values: HERALD_GUARDIAN, CRUSADER_ARCHON, LEGEND_ANCIENT, DIVINE_IMMORTAL, ALL
    # Adjust to match your group's MMR range.
    stratz_brackets: list[str] = ["LEGEND_ANCIENT"]
    friends_file: Path = ROOT_DIR / "friends.json"

    @property
    def opendota_base_url(self) -> str:
        return "https://api.opendota.com/api"


settings = Settings()
