#!/usr/bin/env python3

# -*- coding: utf-8 -*-

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CHANGELOG.md generator with semantic versioning support.

This module provides tools for generating and maintaining
CHANGELOG.md files following Keep a Changelog format and semantic versioning
principles. It supports automated version tracking, release management,
and detailed change documentation.

Examples
--------
>>> from pyputil.template import changelog_template
>>> 
>>> # Basic usage
>>> changelog_template(
...     project_name="My Project",
...     repository_url="https://github.com/user/project"
... )
>>> 
>>> # Advanced with releases
>>> changelog_template(
...     project_name="My Project",
...     versions=[
...         {
...             "version": "1.0.0",
...             "date": "2024-01-15",
...             "added": ["Initial release", "Core functionality"],
...             "changed": ["Updated documentation"],
...             "fixed": ["Bug fixes"]
...         }
...     ]
... )
"""

from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple
from enum import Enum
from datetime import datetime
import warnings
import re
from dataclasses import dataclass, field


class ChangeType(str, Enum):
    """
    Types of changes in the changelog.
    
    Attributes
    ----------
    ADDED : str
        New features or functionality added.
    CHANGED : str
        Changes to existing functionality.
    DEPRECATED : str
        Features that will be removed in future.
    REMOVED : str
        Features that were removed.
    FIXED : str
        Bug fixes and corrections.
    SECURITY : str
        Security-related fixes or improvements.
    """
    ADDED = "added"
    CHANGED = "changed"
    DEPRECATED = "deprecated"
    REMOVED = "removed"
    FIXED = "fixed"
    SECURITY = "security"


class VersionStatus(str, Enum):
    """
    Version status indicators.
    
    Attributes
    ----------
    RELEASED : str
        Officially released version.
    UNRELEASED : str
        Changes not yet released.
    YANKED : str
        Version that was yanked from distribution.
    """
    RELEASED = "released"
    UNRELEASED = "unreleased"
    YANKED = "yanked"


@dataclass
class ChangeEntry:
    """
    Individual change entry in the changelog.
    
    Attributes
    ----------
    change_type : ChangeType
        Type of change (added, changed, fixed, etc.).
    description : str
        Description of the change.
    issue_numbers : Optional[List[int]]
        Related issue numbers (e.g., #123).
    pull_request : Optional[int]
        Related pull request number.
    author : Optional[str]
        Author of the change.
    """
    change_type: ChangeType
    description: str
    issue_numbers: Optional[List[int]] = None
    pull_request: Optional[int] = None
    author: Optional[str] = None
    
    def to_markdown(self) -> str:
        """Convert change entry to markdown format."""
        parts = [self.description]
        
        if self.issue_numbers:
            issues = ", ".join(f"#{num}" for num in self.issue_numbers)
            parts.append(f"({issues})")
        
        if self.pull_request:
            parts.append(f"[PR #{self.pull_request}]")
        
        if self.author:
            parts.append(f"(@{self.author})")
        
        return " ".join(parts)


@dataclass
class VersionRelease:
    """
    Version release information.
    
    Attributes
    ----------
    version : str
        Semantic version (e.g., "1.0.0", "2.1.0-beta").
    date : Optional[str]
        Release date in YYYY-MM-DD format.
    status : VersionStatus
        Release status (released, unreleased, yanked).
    added : List[str]
        New features added.
    changed : List[str]
        Changes to existing features.
    deprecated : List[str]
        Deprecated features.
    removed : List[str]
        Removed features.
    fixed : List[str]
        Bug fixes.
    security : List[str]
        Security fixes.
    """
    version: str
    date: Optional[str] = None
    status: VersionStatus = VersionStatus.RELEASED
    added: List[str] = field(default_factory=list)
    changed: List[str] = field(default_factory=list)
    deprecated: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    fixed: List[str] = field(default_factory=list)
    security: List[str] = field(default_factory=list)
    
    def get_entries(self) -> Dict[ChangeType, List[str]]:
        """Get all change entries organized by type."""
        return {
            ChangeType.ADDED: self.added,
            ChangeType.CHANGED: self.changed,
            ChangeType.DEPRECATED: self.deprecated,
            ChangeType.REMOVED: self.removed,
            ChangeType.FIXED: self.fixed,
            ChangeType.SECURITY: self.security,
        }
    
    def has_changes(self) -> bool:
        """Check if version has any changes."""
        return any([
            self.added,
            self.changed,
            self.deprecated,
            self.removed,
            self.fixed,
            self.security,
        ])


@dataclass
class ChangelogStats:
    """
    Statistics about the generated changelog.
    
    Attributes
    ----------
    total_versions : int
        Number of versions in the changelog.
    unreleased_changes : int
        Number of changes in unreleased section.
    released_versions : int
        Number of released versions.
    total_changes : int
        Total number of change entries.
    generated_time : float
        Time taken to generate in seconds.
    """
    total_versions: int = 0
    unreleased_changes: int = 0
    released_versions: int = 0
    total_changes: int = 0
    generated_time: float = 0.0


class ChangelogGenerator:
    """
    Generator for CHANGELOG.md files following Keep a Changelog format.
    
    This class provides comprehensive functionality for generating and managing
    changelog files with semantic versioning, categorized changes, and formatting.
    
    Attributes
    ----------
    project_name : str
        Name of the project.
    repository_url : Optional[str]
        URL to the project repository.
    versions : List[VersionRelease]
        List of version releases.
    stats : ChangelogStats
        Statistics about the changelog.
    
    Examples
    --------
    >>> generator = ChangelogGenerator(
    ...     project_name="My Project",
    ...     repository_url="https://github.com/user/project"
    ... )
    >>> 
    >>> # Add unreleased changes
    >>> generator.add_unreleased_changes(
    ...     added=["New feature X", "Performance improvements"],
    ...     fixed=["Bug in authentication"]
    ... )
    >>> 
    >>> # Release new version
    >>> generator.add_release(
    ...     version="1.0.0",
    ...     date="2024-01-15",
    ...     added=["Initial release"],
    ...     changed=["Updated documentation"]
    ... )
    >>> 
    >>> generator.generate()
    """
    
    def __init__(
        self,
        project_name: str = "My Project",
        repository_url: Optional[str] = None,
        versions: Optional[List[VersionRelease]] = None,
        keep_unreleased: bool = True,
        add_comparison_links: bool = True,
        add_contributors: bool = False,
        date_format: str = "%Y-%m-%d",
        output_dir: Union[str, Path] = ".",
        force_overwrite: bool = False,
        dry_run: bool = False,
        verbose: bool = False,
        show_warnings: bool = True,
        add_timestamp_comment: bool = True,
    ) -> None:
        """
        Initialize the ChangelogGenerator.
        
        Parameters
        ----------
        project_name : str, default="My Project"
            Name of the project. Used in the changelog header.
            
        repository_url : Optional[str], optional
            URL to the project repository. Used to generate comparison
            links and issue/PR references. Example: "https://github.com/user/project"
            
        versions : Optional[List[VersionRelease]], optional
            List of existing version releases. If provided, these will be
            included in the changelog. Useful for loading existing releases.
            
        keep_unreleased : bool, default=True
            Whether to keep an "Unreleased" section for changes that
            haven't been released yet.
            
        add_comparison_links : bool, default=True
            Whether to add links comparing versions (e.g., 
            [1.0.0...1.1.0]). Requires repository_url to be set.
            
        add_contributors : bool, default=False
            Whether to add contributor information to change entries.
            Parses from commit messages or requires manual entry.
            
        date_format : str, default="%Y-%m-%d"
            Format for dates in the changelog. Default is ISO format.
            
        output_dir : Union[str, Path], default="."
            Directory where CHANGELOG.md will be created.
            
        force_overwrite : bool, default=False
            Whether to overwrite existing CHANGELOG.md file.
            
        dry_run : bool, default=False
            Whether to simulate generation without writing.
            
        verbose : bool, default=False
            Whether to print detailed information.
            
        show_warnings : bool, default=True
            Whether to show warning messages.
            
        add_timestamp_comment : bool, default=True
            Whether to add generation timestamp comment.
            
        Raises
        ------
        ValueError
            If configuration parameters are invalid.
        PermissionError
            If the output directory cannot be accessed.
            
        Examples
        --------
        >>> generator = ChangelogGenerator(
        ...     project_name="My Package",
        ...     repository_url="https://github.com/user/mypackage",
        ...     keep_unreleased=True,
        ...     add_comparison_links=True
        ... )
        """
        # Basic configuration
        self.project_name = project_name
        self.repository_url = repository_url.rstrip('/') if repository_url else None
        self.keep_unreleased = keep_unreleased
        self.add_comparison_links = add_comparison_links
        self.add_contributors = add_contributors
        self.date_format = date_format
        self.output_dir = Path(output_dir)
        self.force_overwrite = force_overwrite
        self.dry_run = dry_run
        self.verbose = verbose
        self.show_warnings = show_warnings
        self.add_timestamp_comment = add_timestamp_comment
        
        # Initialize versions
        self.versions: List[VersionRelease] = versions or []
        self._unreleased = VersionRelease(
            version="Unreleased",
            date=None,
            status=VersionStatus.UNRELEASED
        )
        
        # Statistics
        self.stats = ChangelogStats()
        self._warnings_count = 0
        
        # Validate configuration
        self._validate_config()
        
        if self.verbose:
            self._log(f"ChangelogGenerator initialized")
            self._log(f"  Project: {self.project_name}")
            self._log(f"  Repository: {self.repository_url or 'Not set'}")
            self._log(f"  Existing versions: {len(self.versions)}")
    
    def _validate_config(self) -> None:
        """Validate configuration parameters."""
        # Validate output directory
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionError(f"Cannot create output directory {self.output_dir}: {e}")
        
        # Validate versions
        for version in self.versions:
            if not self._is_valid_semver(version.version) and version.status != VersionStatus.UNRELEASED:
                self._warn(f"Version '{version.version}' does not follow semantic versioning")
    
    def _log(self, message: str) -> None:
        """Log verbose messages."""
        if self.verbose:
            print(f"[INFO] {message}")
    
    def _warn(self, message: str) -> None:
        """Issue a warning."""
        self._warnings_count += 1
        if self.show_warnings:
            warnings.warn(message, UserWarning, stacklevel=2)
    
    def _is_valid_semver(self, version: str) -> bool:
        """Check if version follows semantic versioning."""
        pattern = r'^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$'
        return bool(re.match(pattern, version))
    
    def _parse_version_parts(self, version: str) -> Tuple[int, int, int]:
        """Parse version into major, minor, patch components."""
        match = re.match(r'^(\d+)\.(\d+)\.(\d+)', version)
        if match:
            return int(match.group(1)), int(match.group(2)), int(match.group(3))
        return 0, 0, 0
    
    def _get_comparison_link(self, from_version: str, to_version: str) -> str:
        """Generate GitHub comparison link between versions."""
        if not self.repository_url:
            return ""
        
        base_url = f"{self.repository_url}/compare"
        return f"[{from_version}...{to_version}]({base_url}/{from_version}...{to_version})"
    
    def add_unreleased_changes(
        self,
        added: Optional[List[str]] = None,
        changed: Optional[List[str]] = None,
        deprecated: Optional[List[str]] = None,
        removed: Optional[List[str]] = None,
        fixed: Optional[List[str]] = None,
        security: Optional[List[str]] = None,
    ) -> None:
        """
        Add changes to the Unreleased section.
        
        Parameters
        ----------
        added : Optional[List[str]], optional
            New features added.
        changed : Optional[List[str]], optional
            Changes to existing features.
        deprecated : Optional[List[str]], optional
            Deprecated features.
        removed : Optional[List[str]], optional
            Removed features.
        fixed : Optional[List[str]], optional
            Bug fixes.
        security : Optional[List[str]], optional
            Security fixes.
            
        Examples
        --------
        >>> generator.add_unreleased_changes(
        ...     added=["New CLI interface", "Async support"],
        ...     fixed=["Memory leak in cache", "Race condition in threading"]
        ... )
        """
        if added:
            self._unreleased.added.extend(added)
        if changed:
            self._unreleased.changed.extend(changed)
        if deprecated:
            self._unreleased.deprecated.extend(deprecated)
        if removed:
            self._unreleased.removed.extend(removed)
        if fixed:
            self._unreleased.fixed.extend(fixed)
        if security:
            self._unreleased.security.extend(security)
        
        if self.verbose:
            total = len(added or []) + len(changed or []) + len(deprecated or []) + \
                    len(removed or []) + len(fixed or []) + len(security or [])
            self._log(f"Added {total} changes to Unreleased section")
    
    def add_release(
        self,
        version: str,
        date: Optional[str] = None,
        added: Optional[List[str]] = None,
        changed: Optional[List[str]] = None,
        deprecated: Optional[List[str]] = None,
        removed: Optional[List[str]] = None,
        fixed: Optional[List[str]] = None,
        security: Optional[List[str]] = None,
    ) -> None:
        """
        Add a new version release.
        
        Parameters
        ----------
        version : str
            Version number following semantic versioning (e.g., "1.0.0").
        date : Optional[str], optional
            Release date. If not provided, uses current date.
        added : Optional[List[str]], optional
            New features added.
        changed : Optional[List[str]], optional
            Changes to existing features.
        deprecated : Optional[List[str]], optional
            Deprecated features.
        removed : Optional[List[str]], optional
            Removed features.
        fixed : Optional[List[str]], optional
            Bug fixes.
        security : Optional[List[str]], optional
            Security fixes.
            
        Raises
        ------
        ValueError
            If version already exists or is invalid.
            
        Examples
        --------
        >>> generator.add_release(
        ...     version="1.0.0",
        ...     date="2024-01-15",
        ...     added=["Initial release"],
        ...     fixed=["Various bug fixes"]
        ... )
        """
        # Validate version
        if not self._is_valid_semver(version):
            raise ValueError(f"Invalid semantic version: {version}")
        
        # Check for duplicate
        if any(v.version == version for v in self.versions):
            raise ValueError(f"Version {version} already exists")
        
        # Create release
        release = VersionRelease(
            version=version,
            date=date or datetime.now().strftime(self.date_format),
            status=VersionStatus.RELEASED,
            added=added or [],
            changed=changed or [],
            deprecated=deprecated or [],
            removed=removed or [],
            fixed=fixed or [],
            security=security or [],
        )
        
        self.versions.append(release)
        self.versions.sort(key=lambda v: self._parse_version_parts(v.version), reverse=True)
        
        if self.verbose:
            changes = release.get_entries()
            total = sum(len(entries) for entries in changes.values())
            self._log(f"Added release {version} with {total} changes")
    
    def yank_version(self, version: str, reason: Optional[str] = None) -> None:
        """
        Mark a version as yanked (unusable).
        
        Parameters
        ----------
        version : str
            Version to yank.
        reason : Optional[str], optional
            Reason for yanking the version.
            
        Raises
        ------
        ValueError
            If version does not exist.
            
        Examples
        --------
        >>> generator.yank_version("1.0.0", reason="Critical security vulnerability")
        """
        for v in self.versions:
            if v.version == version:
                v.status = VersionStatus.YANKED
                if reason:
                    v.added.append(f"YANKED: {reason}")
                if self.verbose:
                    self._log(f"Yanked version {version}")
                return
        
        raise ValueError(f"Version {version} not found")
    
    def release_unreleased(
        self,
        version: str,
        date: Optional[str] = None,
    ) -> None:
        """
        Move Unreleased changes to a new version release.
        
        Parameters
        ----------
        version : str
            Version number for the new release.
        date : Optional[str], optional
            Release date. If not provided, uses current date.
            
        Examples
        --------
        >>> generator.add_unreleased_changes(added=["New feature"])
        >>> generator.release_unreleased("1.0.0")
        """
        if not self._unreleased.has_changes():
            self._warn("No unreleased changes to release")
            return
        
        self.add_release(
            version=version,
            date=date,
            added=self._unreleased.added,
            changed=self._unreleased.changed,
            deprecated=self._unreleased.deprecated,
            removed=self._unreleased.removed,
            fixed=self._unreleased.fixed,
            security=self._unreleased.security,
        )
        
        # Clear unreleased changes
        self._unreleased = VersionRelease(
            version="Unreleased",
            date=None,
            status=VersionStatus.UNRELEASED
        )
        
        if self.verbose:
            self._log(f"Released version {version} from Unreleased changes")
    
    def _format_version_section(self, release: VersionRelease) -> List[str]:
        """Format a version section as markdown."""
        lines = []
        
        # Version header
        header = f"## [{release.version}]"
        if release.date:
            header += f" - {release.date}"
        if release.status == VersionStatus.YANKED:
            header += " (YANKED)"
        lines.append(header)
        lines.append("")
        
        # Add changes by category
        categories = [
            (ChangeType.ADDED, "### Added"),
            (ChangeType.CHANGED, "### Changed"),
            (ChangeType.DEPRECATED, "### Deprecated"),
            (ChangeType.REMOVED, "### Removed"),
            (ChangeType.FIXED, "### Fixed"),
            (ChangeType.SECURITY, "### Security"),
        ]
        
        has_changes = False
        for change_type, heading in categories:
            entries = release.get_entries()[change_type]
            if entries:
                lines.append(heading)
                for entry in entries:
                    lines.append(f"- {entry}")
                lines.append("")
                has_changes = True
        
        if not has_changes:
            lines.append("No significant changes")
            lines.append("")
        
        return lines
    
    def _build_content(self) -> str:
        """Build the complete changelog content."""
        content_lines = []
        
        # Header
        content_lines.append(f"# Changelog for {self.project_name}")
        content_lines.append("")
        content_lines.append("All notable changes to this project will be documented in this file.")
        content_lines.append("")
        content_lines.append("The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),")
        content_lines.append("and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).")
        content_lines.append("")
        
        # Add Unreleased section
        if self.keep_unreleased and self._unreleased.has_changes():
            unreleased_lines = self._format_version_section(self._unreleased)
            content_lines.extend(unreleased_lines)
            
            # Count changes
            for changes in self._unreleased.get_entries().values():
                self.stats.unreleased_changes += len(changes)
        
        # Add released versions
        for release in self.versions:
            if release.has_changes():
                version_lines = self._format_version_section(release)
                content_lines.extend(version_lines)
                self.stats.released_versions += 1
                
                # Count changes
                for changes in release.get_entries().values():
                    self.stats.total_changes += len(changes)
        
        self.stats.total_versions = len(self.versions)
        
        # Add comparison links section
        if self.add_comparison_links and self.repository_url and len(self.versions) >= 1:
            content_lines.append("## Comparison Links")
            content_lines.append("")
            
            # Sort versions in ascending order for links
            sorted_versions = sorted(self.versions, key=lambda v: self._parse_version_parts(v.version))
            
            for i in range(len(sorted_versions) - 1):
                from_ver = sorted_versions[i].version
                to_ver = sorted_versions[i + 1].version
                link = self._get_comparison_link(from_ver, to_ver)
                if link:
                    content_lines.append(f"- [{from_ver}...{to_ver}]({link})")
            
            content_lines.append("")
        
        # Add footer
        footer = [
            "---",
            "",
            f"*This changelog was automatically generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            f"*Format based on [Keep a Changelog](https://keepachangelog.com/)*",
        ]
        content_lines.extend(footer)
        
        return "\n".join(content_lines)
    
    def generate(self) -> str:
        """
        Generate the CHANGELOG.md file.
        
        Returns
        -------
        str
            Path to the generated CHANGELOG.md file.
            
        Raises
        ------
        FileExistsError
            If CHANGELOG.md already exists and force_overwrite is False.
        IOError
            If the file cannot be written.
            
        Examples
        --------
        >>> generator = ChangelogGenerator(project_name="My Project")
        >>> generator.add_unreleased_changes(added=["New feature"])
        >>> generator.add_release(version="1.0.0", added=["Initial release"])
        >>> path = generator.generate()
        """
        import time
        start_time = time.time()
        
        changelog_path = self.output_dir / "CHANGELOG.md"
        
        # Check if file exists
        if changelog_path.exists() and not self.force_overwrite:
            raise FileExistsError(
                f"{changelog_path} already exists. "
                f"Use force_overwrite=True to overwrite."
            )
        
        # Build content
        content = self._build_content()
        
        # Calculate statistics
        self.stats.generated_time = time.time() - start_time
        
        if self.verbose:
            self._log(f"Generated changelog with:")
            self._log(f"  Total versions: {self.stats.total_versions}")
            self._log(f"  Released versions: {self.stats.released_versions}")
            self._log(f"  Total changes: {self.stats.total_changes}")
            self._log(f"  Unreleased changes: {self.stats.unreleased_changes}")
            self._log(f"  Time: {self.stats.generated_time:.3f}s")
        
        if self._warnings_count > 0:
            self._log(f"Warnings: {self._warnings_count}")
        
        # Dry run
        if self.dry_run:
            self._log(f"DRY RUN: Would generate {changelog_path}")
            self._log(f"Content preview:\n{content[:500]}...")
            return str(changelog_path)
        
        # Write file
        try:
            changelog_path.write_text(content, encoding="utf-8")
            if self.verbose:
                self._log(f"Written to: {changelog_path}")
                self._log(f"File size: {changelog_path.stat().st_size} bytes")
        except (IOError, OSError) as e:
            raise IOError(f"Failed to write {changelog_path}: {e}")
        
        return str(changelog_path)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get generation statistics.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary containing generation statistics.
            
        Examples
        --------
        >>> generator = ChangelogGenerator()
        >>> generator.add_release(version="1.0.0")
        >>> generator.generate()
        >>> stats = generator.get_stats()
        >>> print(f"Generated {stats['total_versions']} versions")
        """
        return {
            "total_versions": self.stats.total_versions,
            "released_versions": self.stats.released_versions,
            "total_changes": self.stats.total_changes,
            "unreleased_changes": self.stats.unreleased_changes,
            "generated_time": self.stats.generated_time,
            "warnings_count": self._warnings_count,
        }


def changelog_template(
    project_name: str = "My Project",
    repository_url: Optional[str] = None,
    versions: Optional[List[Dict[str, Any]]] = None,
    unreleased_changes: Optional[Dict[str, List[str]]] = None,
    keep_unreleased: bool = True,
    add_comparison_links: bool = True,
    add_contributors: bool = False,
    date_format: str = "%Y-%m-%d",
    output_dir: Union[str, Path] = ".",
    force_overwrite: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
    show_warnings: bool = True,
    add_timestamp_comment: bool = True,
) -> str:
    """
    Generate a CHANGELOG.md file following Keep a Changelog format.
    
    This function creates a comprehensive changelog with support for semantic
    versioning, categorized changes, and automatic version management.
    
    Parameters
    ----------
    project_name : str, default="My Project"
        Name of the project. Appears in the changelog header.
        
    repository_url : Optional[str], optional
        URL to the project repository. Used for comparison links and references.
        Example: "https://github.com/user/project"
        
    versions : Optional[List[Dict[str, Any]]], optional
        List of version releases. Each version should be a dictionary with:
        - "version": str - Version number
        - "date": str, optional - Release date (YYYY-MM-DD)
        - "added": List[str], optional - New features
        - "changed": List[str], optional - Changes
        - "deprecated": List[str], optional - Deprecated features
        - "removed": List[str], optional - Removed features
        - "fixed": List[str], optional - Bug fixes
        - "security": List[str], optional - Security fixes
        
    unreleased_changes : Optional[Dict[str, List[str]]], optional
        Changes not yet released. Keys are change types:
        - "added": New features
        - "changed": Changes
        - "deprecated": Deprecated features
        - "removed": Removed features
        - "fixed": Bug fixes
        - "security": Security fixes
        
    keep_unreleased : bool, default=True
        Whether to include an "Unreleased" section in the changelog.
        
    add_comparison_links : bool, default=True
        Whether to add links comparing versions. Requires repository_url.
        
    add_contributors : bool, default=False
        Whether to include contributor information in change entries.
        
    date_format : str, default="%Y-%m-%d"
        Format for dates in the changelog.
        
    output_dir : Union[str, Path], default="."
        Directory where CHANGELOG.md will be created.
        
    force_overwrite : bool, default=False
        Whether to overwrite existing CHANGELOG.md file.
        
    dry_run : bool, default=False
        Whether to simulate generation without writing.
        
    verbose : bool, default=False
        Whether to print detailed information.
        
    show_warnings : bool, default=True
        Whether to show warning messages.
        
    add_timestamp_comment : bool, default=True
        Whether to add generation timestamp comment.
        
    Returns
    -------
    str
        Path to the generated CHANGELOG.md file.
        
    Raises
    ------
    FileExistsError
        If CHANGELOG.md already exists and force_overwrite is False.
    PermissionError
        If the output directory cannot be accessed.
    ValueError
        If configuration parameters are invalid.
        
    Examples
    --------
    Basic usage with versions:
    >>> changelog_template(
    ...     project_name="My Package",
    ...     versions=[
    ...         {
    ...             "version": "1.0.0",
    ...             "date": "2024-01-15",
    ...             "added": ["Initial release", "Core functionality"],
    ...             "fixed": ["Various bug fixes"]
    ...         },
    ...         {
    ...             "version": "0.1.0",
    ...             "date": "2024-01-01",
    ...             "added": ["First beta release"]
    ...         }
    ...     ]
    ... )
    
    With unreleased changes:
    >>> changelog_template(
    ...     project_name="My Package",
    ...     repository_url="https://github.com/user/mypackage",
    ...     unreleased_changes={
    ...         "added": ["Async support", "New CLI commands"],
    ...         "fixed": ["Memory leak in parser"],
    ...         "changed": ["Updated documentation"]
    ...     },
    ...     keep_unreleased=True
    ... )
    
    Complete example with all features:
    >>> changelog_template(
    ...     project_name="My Package",
    ...     repository_url="https://github.com/user/mypackage",
    ...     versions=[
    ...         {
    ...             "version": "1.0.0",
    ...             "date": "2024-01-15",
    ...             "added": ["Initial release"],
    ...             "changed": ["Updated API docs"],
    ...             "fixed": ["Bug fixes"],
    ...             "security": ["Security patches"]
    ...         }
    ...     ],
    ...     unreleased_changes={
    ...         "added": ["New features in development"],
    ...         "changed": ["API improvements"]
    ...     },
    ...     add_comparison_links=True,
    ...     verbose=True
    ... )
    
    Notes
    -----
    - Follows the Keep a Changelog specification
    - Supports semantic versioning (SemVer)
    - Automatically sorts versions in reverse chronological order
    - Generates comparison links between versions (GitHub format)
    - Handles yanked versions with special markers
    - Provides detailed statistics about changelog contents
    """
    # Convert dictionary versions to VersionRelease objects
    version_objects = []
    if versions:
        for v in versions:
            version_objects.append(VersionRelease(
                version=v.get("version", ""),
                date=v.get("date"),
                status=VersionStatus.YANKED if v.get("yanked", False) else VersionStatus.RELEASED,
                added=v.get("added", []),
                changed=v.get("changed", []),
                deprecated=v.get("deprecated", []),
                removed=v.get("removed", []),
                fixed=v.get("fixed", []),
                security=v.get("security", []),
            ))
    
    # Create generator
    generator = ChangelogGenerator(
        project_name=project_name,
        repository_url=repository_url,
        versions=version_objects,
        keep_unreleased=keep_unreleased,
        add_comparison_links=add_comparison_links,
        add_contributors=add_contributors,
        date_format=date_format,
        output_dir=output_dir,
        force_overwrite=force_overwrite,
        dry_run=dry_run,
        verbose=verbose,
        show_warnings=show_warnings,
        add_timestamp_comment=add_timestamp_comment,
    )
    
    # Add unreleased changes
    if unreleased_changes:
        generator.add_unreleased_changes(
            added=unreleased_changes.get("added"),
            changed=unreleased_changes.get("changed"),
            deprecated=unreleased_changes.get("deprecated"),
            removed=unreleased_changes.get("removed"),
            fixed=unreleased_changes.get("fixed"),
            security=unreleased_changes.get("security"),
        )
    
    # Generate and return path
    return generator.generate()


def write_changelog(path: Union[str, Path] = "CHANGELOG.md", **kwargs) -> None:
    """
    Generate CHANGELOG.md and write it directly to disk.
    
    This is a convenience wrapper around changelog_template() that handles
    file writing with proper encoding and error handling.
    
    Parameters
    ----------
    path : str or Path, default="CHANGELOG.md"
        Path where to write the CHANGELOG.md file. If a directory is provided,
        writes to that directory/CHANGELOG.md.
    **kwargs
        Additional arguments passed to changelog_template().
        
    Examples
    --------
    Write to current directory:
    >>> write_changelog("CHANGELOG.md", project_name="My Project")
    
    Write to specific directory:
    >>> write_changelog(
    ...     "./docs/CHANGELOG.md",
    ...     project_name="My Project",
    ...     versions=[{"version": "1.0.0", "added": ["Initial release"]}]
    ... )
    
    Notes
    -----
    - The file is written with UTF-8 encoding
    - Existing files are handled according to force_overwrite parameter
    - The directory is created if it doesn't exist
    """
    path_obj = Path(path)
    
    # If path is a directory, append CHANGELOG.md
    if path_obj.is_dir() or (not path_obj.suffix and path_obj.name != "CHANGELOG.md"):
        path_obj = path_obj / "CHANGELOG.md"
    
    # Extract output_dir from path
    output_dir = kwargs.pop("output_dir", path_obj.parent)
    
    # Generate changelog content
    content = changelog_template(output_dir=output_dir, **kwargs)
    
    # Ensure parent directory exists
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    # Write to file
    path_obj.write_text(content, encoding="utf-8")
