import os
from urllib.parse import quote_plus

from dotenv import load_dotenv


def load_environment() -> None:
    load_dotenv()


def eodhd_api_key_from_env() -> str:
    load_environment()
    api_key = os.getenv("EODHD_API_KEY")
    if not api_key:
        raise ValueError("EODHD_API_KEY is required")
    return api_key


def database_url_from_env() -> str:
    load_environment()
    explicit_url = os.getenv("FDP_DATABASE_URL")
    if explicit_url:
        return explicit_url

    driver = os.getenv("FDP_DB_DRIVER", "mysql+pymysql")
    host = _required_env("FDP_DB_HOST")
    port = os.getenv("FDP_DB_PORT", "3306")
    user = quote_plus(_required_env("FDP_DB_USER"))
    password = quote_plus(_required_env("FDP_DB_PASSWORD"))
    database = _required_env("FDP_DB_NAME")
    return f"{driver}://{user}:{password}@{host}:{port}/{database}"


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} is required")
    return value
