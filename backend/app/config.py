from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_host: str = '127.0.0.1'
    app_port: int = 8001
    api_key: str = 'local-dev-key'
    allowed_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    data_dir: Path = Path('./data')
    moss_model_id: str = 'OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5'
    moss_device: str = 'auto'
    moss_max_new_tokens: int = 4096
    max_upload_mb: int = 30
    sglang_base_url: str = ''
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


settings = Settings()
