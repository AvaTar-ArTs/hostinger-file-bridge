from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HFB_",
        env_file=".env",
        extra="ignore",
    )

    sftp_host: str = "82.29.199.248"
    sftp_port: int = 65002
    sftp_username: str = "u365102102"
    sftp_key_path: Path
    sftp_key_passphrase: str | None = None

    remote_root: str = "/home/u365102102/domains/avatararts.org/public_html/gpt-export-rename"

    public_base_url: str = "http://127.0.0.1:8000"
    upload_signing_secret: str
    upload_ticket_ttl: int = 900
    max_upload_bytes: int = 512 * 1024 * 1024

    http_bearer_token: str | None = None
    known_hosts_path: Path | None = None
    log_level: str = "INFO"
