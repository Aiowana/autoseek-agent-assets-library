"""
Data models for asset manifests.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field, field_validator


# ============================================================================
# Pydantic Models for Validation
# ============================================================================

class ConfigSchemaItem(BaseModel):
    """Single configuration item in config_schema."""

    name: str
    label: str
    type: Literal["string", "number", "select", "secret", "boolean"]
    required: bool = False
    default: Any = None
    placeholder: Optional[str] = None
    options: Optional[List[Dict[str, Any]]] = None  # For select type

    @field_validator("options")
    @classmethod
    def validate_options(cls, v, info):
        if info.data.get("type") == "select" and not v:
            raise ValueError("options is required when type is 'select'")
        return v


class AgentSpecs(BaseModel):
    """Agent specs for LLM function calling."""

    function_name: str
    description: str
    parameters: Dict[str, Any]


class Runtime(BaseModel):
    """Runtime configuration for dynamic loading."""

    language: Literal["python"]  # Currently only Python
    entry: str  # e.g., "main.py"
    handler: str  # e.g., "main_handler"
    dependencies: List[str] = Field(default_factory=list)


class Permissions(BaseModel):
    """Permissions for sandboxing."""

    network_access: bool = False
    filesystem_read: bool = False


class ManifestData(BaseModel):
    """Complete manifest data model."""

    id: str
    version: str
    category: Literal["tool", "prompt", "skill"]
    name: str
    description: str
    author: Optional[str] = None
    config_schema: List[ConfigSchemaItem] = Field(default_factory=list)
    agent_specs: Optional[AgentSpecs] = None
    runtime: Optional[Runtime] = None
    permissions: Optional[Permissions] = Field(default_factory=Permissions)

    @field_validator("id")
    @classmethod
    def validate_id(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError("id must be a non-empty string")
        # Allow alphanumeric, underscore, hyphen
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError(f"id '{v}' contains invalid characters. Use only alphanumeric, underscore, and hyphen.")
        return v

    @field_validator("version")
    @classmethod
    def validate_version(cls, v):
        # Basic semver validation
        import re
        pattern = r'^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$'
        if not re.match(pattern, v):
            raise ValueError(f"version '{v}' is not valid semver (e.g., '1.0.0')")
        return v


# ============================================================================
# Redis Storage Models
# ============================================================================

@dataclass
class StoredAsset:
    """Asset as stored in Redis Hash."""

    id: str
    version: str
    category: str
    name: str
    description: str
    config_schema: str  # JSON string
    agent_specs: Optional[str]  # JSON string or None
    runtime: Optional[str]  # JSON string or None
    github_path: str
    github_sha: str
    created_at: int  # Unix timestamp
    updated_at: int  # Unix timestamp
    author: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Redis HSET."""
        result = {
            "id": self.id,
            "version": self.version,
            "category": self.category,
            "name": self.name,
            "description": self.description,
            "config_schema": self.config_schema,
            "github_path": self.github_path,
            "github_sha": self.github_sha,
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
        }
        if self.agent_specs:
            result["agent_specs"] = self.agent_specs
        if self.runtime:
            result["runtime"] = self.runtime
        if self.author:
            result["author"] = self.author
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StoredAsset":
        """Create from Redis HGETALL result."""
        return cls(
            id=data["id"],
            version=data["version"],
            category=data["category"],
            name=data["name"],
            description=data["description"],
            config_schema=data["config_schema"],
            agent_specs=data.get("agent_specs"),
            runtime=data.get("runtime"),
            github_path=data["github_path"],
            github_sha=data["github_sha"],
            created_at=int(data["created_at"]),
            updated_at=int(data["updated_at"]),
            author=data.get("author"),
        )


# ============================================================================
# Domain Model
# ============================================================================

@dataclass
class Asset:
    """
    Domain model representing a complete asset with metadata.
    Combines manifest data with GitHub metadata.
    """

    manifest: ManifestData
    github_path: str
    github_sha: str
    github_url: Optional[str] = None

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def category(self) -> str:
        return self.manifest.category

    def to_stored_asset(self) -> StoredAsset:
        """Convert to StoredAsset for Redis storage."""
        import json
        from datetime import datetime

        now = int(datetime.now().timestamp())

        return StoredAsset(
            id=self.manifest.id,
            version=self.manifest.version,
            category=self.manifest.category,
            name=self.manifest.name,
            description=self.manifest.description,
            config_schema=json.dumps([item.model_dump() for item in self.manifest.config_schema]),
            agent_specs=json.dumps(self.manifest.agent_specs.model_dump()) if self.manifest.agent_specs else None,
            runtime=json.dumps(self.manifest.runtime.model_dump()) if self.manifest.runtime else None,
            github_path=self.github_path,
            github_sha=self.github_sha,
            created_at=now,
            updated_at=now,
            author=self.manifest.author,
        )
