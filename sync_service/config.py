"""
Configuration management for the sync service.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@dataclass
class RedisConfig:
    """Redis connection configuration."""

    host: str = "localhost"
    port: int = 6379
    password: Optional[str] = None
    db: int = 0
    decode_responses: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "RedisConfig":
        return cls(
            host=data.get("host", os.getenv("REDIS_HOST", "localhost")),
            port=int(data.get("port", os.getenv("REDIS_PORT", 6379))),
            password=data.get("password", os.getenv("REDIS_PASSWORD")),
            db=int(data.get("db", os.getenv("REDIS_DB", 0))),
            decode_responses=data.get("decode_responses", True),
        )


@dataclass
class GitHubConfig:
    """GitHub API configuration."""

    token: str
    repo: str  # Format: "owner/repo"
    branch: str = "main"
    base_path: str = ""  # Empty for root, or subdirectory path

    @classmethod
    def from_dict(cls, data: dict) -> "GitHubConfig":
        token = data.get("token", os.getenv("GITHUB_TOKEN", ""))
        if not token:
            raise ValueError("GitHub token is required. Set GITHUB_TOKEN environment variable or in config.")

        repo = data.get("repo", os.getenv("GITHUB_REPO", ""))
        if not repo:
            raise ValueError("GitHub repo is required. Set GITHUB_REPO environment variable or in config.")

        if "/" not in repo:
            raise ValueError(f"Invalid repo format: {repo}. Expected 'owner/repo'")

        return cls(
            token=token,
            repo=repo,
            branch=data.get("branch", os.getenv("GITHUB_BRANCH", "main")),
            base_path=data.get("base_path", ""),
        )

    @property
    def owner(self) -> str:
        """Extract repository owner from repo string."""
        return self.repo.split("/")[0]

    @property
    def repo_name(self) -> str:
        """Extract repository name from repo string."""
        return self.repo.split("/")[1]


@dataclass
class SyncConfig:
    """Synchronization behavior configuration."""

    interval_seconds: int = 300  # 5 minutes
    batch_size: int = 100
    enable_incremental: bool = True
    max_retries: int = 3
    retry_delay: int = 5  # seconds

    @classmethod
    def from_dict(cls, data: dict) -> "SyncConfig":
        return cls(
            interval_seconds=int(data.get("interval_seconds", os.getenv("SYNC_INTERVAL", 300))),
            batch_size=int(data.get("batch_size", os.getenv("SYNC_BATCH_SIZE", 100))),
            enable_incremental=bool(data.get("enable_incremental", True)),
            max_retries=int(data.get("max_retries", 3)),
            retry_delay=int(data.get("retry_delay", 5)),
        )


@dataclass
class LoggingConfig:
    """Logging configuration."""

    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    @classmethod
    def from_dict(cls, data: dict) -> "LoggingConfig":
        return cls(
            level=data.get("level", os.getenv("LOG_LEVEL", "INFO")),
            format=data.get(
                "format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            ),
        )


@dataclass
class Config:
    """Main configuration container."""

    redis: RedisConfig
    github: GitHubConfig
    sync: SyncConfig = field(default_factory=SyncConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        """Load configuration from YAML file."""
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls(
            redis=RedisConfig.from_dict(data.get("redis", {})),
            github=GitHubConfig.from_dict(data.get("github", {})),
            sync=SyncConfig.from_dict(data.get("sync", {})),
            logging=LoggingConfig.from_dict(data.get("logging", {})),
        )

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables only."""
        return cls(
            redis=RedisConfig.from_dict({}),
            github=GitHubConfig.from_dict({}),
            sync=SyncConfig.from_dict({}),
            logging=LoggingConfig.from_dict({}),
        )

    def setup_logging(self) -> None:
        """Configure logging based on settings."""
        import logging

        level = getattr(logging, self.logging.level.upper(), logging.INFO)
        logging.basicConfig(
            level=level,
            format=self.logging.format,
        )
