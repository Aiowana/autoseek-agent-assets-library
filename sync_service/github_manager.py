"""
GitHub API wrapper for asset repository operations.

Handles fetching manifest files, parsing YAML, and writing back to GitHub.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from github import Github, GithubException, Repository
from github.ContentFile import ContentFile

from sync_service.config import GitHubConfig
from sync_service.models import Asset, ManifestData
from sync_service.schema import ManifestValidator

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class GitHubFile:
    """Represents a file fetched from GitHub."""

    path: str
    content: str
    sha: str
    download_url: str


@dataclass
class ParsedAsset:
    """Result of parsing a manifest file."""

    manifest: ManifestData
    github_path: str
    github_sha: str
    github_url: Optional[str]


# ============================================================================
# GitHub Manager
# ============================================================================

class GitHubManager:
    """
    Manager for GitHub repository operations related to assets.

    Handles:
    - Scanning repository for manifest.yaml files
    - Fetching and parsing manifest content
    - Writing new/updated assets back to GitHub
    """

    def __init__(self, config: GitHubConfig, validator: Optional[ManifestValidator] = None):
        """
        Initialize GitHub manager.

        Args:
            config: GitHub configuration
            validator: Optional manifest validator. Creates default if None.
        """
        self.config = config
        self.validator = validator or ManifestValidator()

        # Initialize GitHub client
        self._client: Optional[Github] = None
        self._repo: Optional[Repository] = None

    @property
    def client(self) -> Github:
        """Lazy initialization of GitHub client."""
        if self._client is None:
            self._client = Github(self.config.token)
            # Test connection
            self._client.get_user().login
            logger.info(f"Connected to GitHub as user")
        return self._client

    @property
    def repo(self) -> Repository:
        """Lazy initialization of repository."""
        if self._repo is None:
            self._repo = self.client.get_repo(self.config.repo)
            logger.info(f"Accessed repository: {self.config.repo}")
        return self._repo

    # ========================================================================
    # Repository Scanning
    # ========================================================================

    def scan_manifests(self, base_path: Optional[str] = None) -> List[GitHubFile]:
        """
        Recursively scan repository for manifest.yaml files.

        Args:
            base_path: Base path to scan from. Uses config.base_path if None.

        Returns:
            List of GitHubFile objects containing manifest data
        """
        base_path = base_path or self.config.base_path
        manifests = []

        logger.info(f"Scanning repository for manifest files in: {base_path or 'root'}")

        try:
            # Get all files with tree traversal
            contents = self.repo.get_contents(base_path) if base_path else self.repo.get_contents("")

            while contents:
                file_content = contents.pop(0)

                if file_content.type == "dir":
                    # Recursively scan directory
                    contents.extend(self.repo.get_contents(file_content.path))

                elif self._is_manifest_file(file_content.name):
                    # Fetch and parse manifest file
                    try:
                        manifest_file = self._fetch_file(file_content)
                        manifests.append(manifest_file)
                        logger.debug(f"Found manifest: {manifest_file.path}")
                    except Exception as e:
                        logger.warning(f"Failed to fetch manifest {file_content.path}: {e}")

        except GithubException as e:
            logger.error(f"GitHub API error while scanning: {e}")
            raise

        logger.info(f"Found {len(manifests)} manifest files")
        return manifests

    def _is_manifest_file(self, filename: str) -> bool:
        """Check if a file is a manifest file."""
        manifest_names = {"manifest.yaml", "manifest.yml"}
        return filename.lower() in manifest_names

    def _fetch_file(self, content_file: ContentFile) -> GitHubFile:
        """Fetch file content from GitHub."""
        decoded_content = content_file.decoded_content.decode("utf-8")

        return GitHubFile(
            path=content_file.path,
            content=decoded_content,
            sha=content_file.sha,
            download_url=content_file.download_url,
        )

    # ========================================================================
    # Manifest Parsing
    # ========================================================================

    def parse_manifest(self, github_file: GitHubFile) -> Optional[ParsedAsset]:
        """
        Parse manifest file content.

        Args:
            github_file: GitHubFile containing manifest data

        Returns:
            ParsedAsset if successful, None if validation fails
        """
        try:
            # Parse YAML
            data = yaml.safe_load(github_file.content)
            if not isinstance(data, dict):
                logger.error(f"Manifest {github_file.path} is not a valid YAML object")
                return None

            # Validate against schema
            manifest = self.validator.validate_and_parse(data)

            return ParsedAsset(
                manifest=manifest,
                github_path=github_file.path,
                github_sha=github_file.sha,
                github_url=github_file.download_url,
            )

        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error for {github_file.path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Validation error for {github_file.path}: {e}")
            return None

    def fetch_and_parse_all(self) -> List[Asset]:
        """
        Fetch and parse all manifests from the repository.

        Returns:
            List of Asset objects
        """
        assets = []

        for github_file in self.scan_manifests():
            parsed = self.parse_manifest(github_file)
            if parsed:
                assets.append(
                    Asset(
                        manifest=parsed.manifest,
                        github_path=parsed.github_path,
                        github_sha=parsed.github_sha,
                        github_url=parsed.github_url,
                    )
                )

        logger.info(f"Successfully parsed {len(assets)} assets")
        return assets

    # ========================================================================
    # GitHub Write Operations
    # ========================================================================

    def save_to_github(
        self,
        asset_id: str,
        manifest_data: Dict[str, Any],
        commit_message: str,
        target_path: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Save or update a manifest file in GitHub.

        Args:
            asset_id: Asset identifier (used to determine path if target_path is None)
            manifest_data: Manifest data to write (will be serialized as YAML)
            commit_message: Git commit message
            target_path: Target path in repository. If None, uses default pattern.

        Returns:
            Tuple of (success, url_or_error_message)
        """
        try:
            # Determine target path
            if target_path is None:
                category = manifest_data.get("category", "tool")
                target_path = f"{category}s/{asset_id}/manifest.yaml"

            # Serialize to YAML
            yaml_content = yaml.dump(
                manifest_data,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
            )

            # Check if file exists
            try:
                existing_file = self.repo.get_contents(target_path, ref=self.config.branch)

                # Update existing file
                self.repo.update_file(
                    path=target_path,
                    message=commit_message,
                    content=yaml_content,
                    sha=existing_file.sha,
                    branch=self.config.branch,
                )
                logger.info(f"Updated manifest in GitHub: {target_path}")

            except GithubException as e:
                if e.status == 404:
                    # Create new file
                    self.repo.create_file(
                        path=target_path,
                        message=commit_message,
                        content=yaml_content,
                        branch=self.config.branch,
                    )
                    logger.info(f"Created manifest in GitHub: {target_path}")
                else:
                    raise

            url = f"https://github.com/{self.config.repo}/blob/{self.config.branch}/{target_path}"
            return True, url

        except GithubException as e:
            error_msg = f"GitHub API error: {e}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            logger.error(error_msg)
            return False, error_msg

    def delete_from_github(
        self,
        asset_id: str,
        file_path: str,
        commit_message: str,
    ) -> Tuple[bool, str]:
        """
        Delete a manifest file from GitHub.

        Args:
            asset_id: Asset identifier
            file_path: Path to the file to delete
            commit_message: Git commit message

        Returns:
            Tuple of (success, error_message if failed)
        """
        try:
            # Get file to obtain SHA
            file_content = self.repo.get_contents(file_path, ref=self.config.branch)

            # Delete file
            self.repo.delete_file(
                path=file_path,
                message=commit_message,
                sha=file_content.sha,
                branch=self.config.branch,
            )

            logger.info(f"Deleted manifest from GitHub: {file_path}")
            return True, ""

        except GithubException as e:
            error_msg = f"GitHub API error: {e}"
            logger.error(error_msg)
            return False, error_msg

    # ========================================================================
    # Repository Metadata
    # ========================================================================

    def get_latest_commit_sha(self) -> Optional[str]:
        """
        Get the SHA of the latest commit on the configured branch.

        Returns:
            Commit SHA or None if failed
        """
        try:
            branch = self.repo.get_branch(self.config.branch)
            return branch.commit.sha
        except GithubException as e:
            logger.error(f"Failed to get latest commit SHA: {e}")
            return None

    def get_commits_since(self, since_timestamp: int) -> List[Any]:
        """
        Get commits since a given timestamp.

        Args:
            since_timestamp: Unix timestamp

        Returns:
            List of commit objects
        """
        try:
            from datetime import datetime

            since_date = datetime.fromtimestamp(since_timestamp)
            commits = self.repo.get_commits(since=since_date)
            return list(commits)
        except GithubException as e:
            logger.error(f"Failed to get commits since {since_timestamp}: {e}")
            return []

    # ========================================================================
    # Asset Operations (Higher-level)
    # ========================================================================

    def get_asset_by_id(self, asset_id: str) -> Optional[Asset]:
        """
        Find and parse an asset by its ID.

        Args:
            asset_id: Asset identifier to search for

        Returns:
            Asset if found, None otherwise
        """
        # Scan all manifests and find matching ID
        for github_file in self.scan_manifests():
            parsed = self.parse_manifest(github_file)
            if parsed and parsed.manifest.id == asset_id:
                return Asset(
                    manifest=parsed.manifest,
                    github_path=parsed.github_path,
                    github_sha=parsed.github_sha,
                    github_url=parsed.github_url,
                )
        return None

    def asset_exists_in_github(self, asset_id: str) -> bool:
        """
        Check if an asset exists in the repository.

        Args:
            asset_id: Asset identifier

        Returns:
            True if asset exists
        """
        return self.get_asset_by_id(asset_id) is not None
