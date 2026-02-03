"""
JSON Schema validation for manifest.yaml files.

Defines the JSON Schema for validating manifest.yaml files
and provides validation functionality.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from jsonschema import validate, ValidationError, Draft7Validator

from sync_service.models import ManifestData

logger = logging.getLogger(__name__)


# ============================================================================
# JSON Schema Definition
# ============================================================================

MANIFEST_JSON_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Agent Asset Manifest",
    "type": "object",
    "required": ["id", "version", "category", "name", "description"],
    "properties": {
        "id": {
            "type": "string",
            "pattern": "^[a-zA-Z0-9_-]+$",
            "description": "Unique identifier for the asset",
        },
        "version": {
            "type": "string",
            "pattern": r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$",
            "description": "Semantic version (e.g., 1.0.0)",
        },
        "category": {
            "type": "string",
            "enum": ["tool", "prompt", "skill"],
            "description": "Asset category",
        },
        "name": {
            "type": "string",
            "minLength": 1,
            "description": "Display name for the asset",
        },
        "description": {
            "type": "string",
            "minLength": 1,
            "description": "Brief description of the asset",
        },
        "author": {
            "type": "string",
            "description": "Author or organization name",
        },
        "config_schema": {
            "type": "array",
            "description": "Configuration form schema for UI",
            "items": {
                "type": "object",
                "required": ["name", "label", "type"],
                "properties": {
                    "name": {
                        "type": "string",
                        "pattern": "^[a-zA-Z_][a-zA-Z0-9_]*$",
                        "description": "Variable name for the config",
                    },
                    "label": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Display label in UI",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["string", "number", "select", "secret", "boolean"],
                        "description": "Input field type",
                    },
                    "required": {
                        "type": "boolean",
                        "description": "Whether this field is required",
                    },
                    "default": {
                        "description": "Default value",
                    },
                    "placeholder": {
                        "type": "string",
                        "description": "Placeholder text for input",
                    },
                    "options": {
                        "type": "array",
                        "description": "Options for select type",
                        "items": {
                            "type": "object",
                            "required": ["label", "value"],
                            "properties": {
                                "label": {"type": "string"},
                                "value": {},
                            },
                        },
                    },
                },
                "if": {"properties": {"type": {"const": "select"}}},
                "then": {
                    "required": ["options"],
                    "properties": {
                        "options": {"type": "array", "minItems": 1},
                    },
                },
            },
        },
        "agent_specs": {
            "type": "object",
            "description": "LLM function calling specification",
            "required": ["function_name", "description", "parameters"],
            "properties": {
                "function_name": {
                    "type": "string",
                    "pattern": "^[a-zA-Z_][a-zA-Z0-9_]*$",
                    "description": "Function name for LLM to call",
                },
                "description": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Description for LLM on when to use this tool",
                },
                "parameters": {
                    "type": "object",
                    "description": "Parameters schema following JSON Schema",
                    "required": ["type"],
                    "properties": {
                        "type": {"const": "object"},
                        "properties": {"type": "object"},
                        "required": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
        "runtime": {
            "type": "object",
            "description": "Runtime configuration for dynamic loading",
            "required": ["language", "entry", "handler"],
            "properties": {
                "language": {
                    "type": "string",
                    "enum": ["python"],
                    "description": "Programming language",
                },
                "entry": {
                    "type": "string",
                    "description": "Entry file path relative to asset root",
                },
                "handler": {
                    "type": "string",
                    "description": "Function or class name to call",
                },
                "dependencies": {
                    "type": "array",
                    "description": "List of pip dependencies",
                    "items": {"type": "string"},
                },
            },
        },
        "permissions": {
            "type": "object",
            "description": "Sandbox permissions",
            "properties": {
                "network_access": {"type": "boolean"},
                "filesystem_read": {"type": "boolean"},
            },
        },
    },
}


# ============================================================================
# Validator Class
# ============================================================================

class ManifestValidator:
    """
    Validates manifest.yaml files against the defined schema.
    """

    def __init__(self, schema: Optional[Dict[str, Any]] = None):
        """
        Initialize the validator with a schema.

        Args:
            schema: JSON Schema to use. If None, uses the default MANIFEST_JSON_SCHEMA.
        """
        self.schema = schema or MANIFEST_JSON_SCHEMA
        self.validator = Draft7Validator(self.schema)

    def validate(self, data: Dict[str, Any]) -> List[str]:
        """
        Validate manifest data against the schema.

        Args:
            data: Parsed YAML/JSON data from manifest file

        Returns:
            List of error messages. Empty if validation passes.

        """
        errors = []
        for error in self.validator.iter_errors(data):
            path = ".".join(str(p) for p in error.path) if error.path else "root"
            errors.append(f"[{path}] {error.message}")

        return errors

    def validate_and_parse(self, data: Dict[str, Any]) -> ManifestData:
        """
        Validate and parse manifest data into a ManifestData model.

        Args:
            data: Parsed YAML/JSON data from manifest file

        Returns:
            ManifestData object

        Raises:
            ValidationError: If validation fails
        """
        errors = self.validate(data)
        if errors:
            raise ValidationError(
                f"Manifest validation failed:\n" + "\n".join(errors)
            )

        return ManifestData(**data)

    def is_valid(self, data: Dict[str, Any]) -> bool:
        """
        Quick check if data is valid without raising exceptions.

        Args:
            data: Parsed YAML/JSON data from manifest file

        Returns:
            True if valid, False otherwise
        """
        errors = self.validate(data)
        return len(errors) == 0


# ============================================================================
# Utility Functions
# ============================================================================

def validate_manifest_yaml(content: str) -> tuple[bool, List[str]]:
    """
    Validate a YAML string containing manifest data.

    Args:
        content: YAML string content

    Returns:
        Tuple of (is_valid, error_messages)
    """
    import yaml

    try:
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            return False, ["YAML content must be a dictionary/object"]
    except yaml.YAMLError as e:
        return False, [f"YAML parsing error: {e}"]

    validator = ManifestValidator()
    errors = validator.validate(data)

    return len(errors) == 0, errors


def validate_manifest_file(path: str) -> tuple[bool, List[str]]:
    """
    Validate a manifest YAML file.

    Args:
        path: Path to the manifest.yaml file

    Returns:
        Tuple of (is_valid, error_messages)
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return validate_manifest_yaml(content)
    except FileNotFoundError:
        return False, [f"File not found: {path}"]
    except IOError as e:
        return False, [f"Failed to read file: {e}"]
