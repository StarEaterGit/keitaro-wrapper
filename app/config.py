from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    keitaro_base_url: str = 'https://tlgk.host'
    keitaro_api_key: str = ''
    # Optional emergency read-only switch. Normal setup allows strictly owner-checked writes.
    keitaro_write_enabled: bool = True
    campaign_prefix: str = 'test_yoursurname_'
    database_url: str = 'sqlite:///./wrapper.db'
    # Optional, explicitly configured target objects. Never guessed from the API's first item.
    campaign_domain_id: int | None = Field(default=None, gt=0)
    campaign_group_id: int | None = Field(default=None, gt=0)
    campaign_traffic_source_id: int | None = Field(default=None, gt=0)

    @field_validator('keitaro_base_url')
    @classmethod
    def valid_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path.strip('/'):
            raise ValueError('KEITARO_BASE_URL must be an HTTPS origin without /admin or a path')
        return value.rstrip('/')

    @field_validator('campaign_prefix')
    @classmethod
    def valid_prefix(cls, value: str) -> str:
        import re
        if not re.fullmatch(r'test_[A-Za-z][A-Za-z0-9]{1,29}_', value):
            raise ValueError('CAMPAIGN_PREFIX must look like test_ivanov_ or test_yakimenkoVS_')
        return value


@lru_cache

def get_settings() -> Settings:
    return Settings()
