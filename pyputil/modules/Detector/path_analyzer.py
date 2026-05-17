#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Path analysis and classification.
"""

import re
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any, Pattern
from dataclasses import dataclass
from fnmatch import fnmatch

from .exceptions import PathResolutionError
from .utils import (
    error_handler,
    safe_path,
    platform_utils,
    file_utils,
    FileUtils,
    PlatformUtils,
    SafePath,
)
from .constants import (
    PackageOrigin,
    PlatformType,
    EDITABLE_INDICATORS,
    DEVELOPMENT_INDICATORS,
    WHEEL_INDICATORS,
    EGG_INDICATORS,
    WINDOWS_SITE_PATHS,
    LINUX_SITE_PATHS,
    MACOS_SITE_PATHS,
)


@dataclass
class PathAnalysis:
    """Result of path analysis."""

    path: str
    """Original path."""

    resolved_path: Path
    """Resolved path (symlinks resolved)."""

    normalized_path: Path
    """Normalized path (case normalized for case-insensitive systems)."""

    is_absolute: bool
    """Whether the path is absolute."""

    exists: bool
    """Whether the path exists."""

    is_file: bool
    """Whether the path is a file."""

    is_dir: bool
    """Whether the path is a directory."""

    is_symlink: bool
    """Whether the path is a symbolic link."""

    parent: Path
    """Parent directory."""

    parts: Tuple[str, ...]
    """Path parts."""

    depth: int
    """Depth of path (number of parent directories)."""

    # Classification
    in_site_packages: bool = False
    """Whether path is in site-packages directory."""

    in_user_site: bool = False
    """Whether path is in user site-packages."""

    in_system_site: bool = False
    """Whether path is in system site-packages."""

    in_venv: bool = False
    """Whether path is in virtual environment."""

    in_conda: bool = False
    """Whether path is in Conda environment."""

    in_docker: bool = False
    """Whether path is in Docker container."""

    in_home_dir: bool = False
    """Whether path is in user's home directory."""

    in_system_dir: bool = False
    """Whether path is in system directory."""

    in_development_dir: bool = False
    """Whether path is in development directory."""

    in_source_dir: bool = False
    """Whether path is in source directory."""

    # Indicators
    has_editable_indicators: bool = False
    """Whether path has editable installation indicators."""

    has_development_indicators: bool = False
    """Whether path has development indicators."""

    has_wheel_indicators: bool = False
    """Whether path has wheel indicators."""

    has_egg_indicators: bool = False
    """Whether path has egg indicators."""

    # Path patterns
    contains_site_packages: bool = False
    """Whether path contains 'site-packages'."""

    contains_dist_packages: bool = False
    """Whether path contains 'dist-packages' (Debian/Ubuntu)."""

    contains_lib: bool = False
    """Whether path contains 'lib'."""

    contains_src: bool = False
    """Whether path contains 'src'."""

    contains_bin: bool = False
    """Whether path contains 'bin'."""

    contains_egg: bool = False
    """Whether path contains '.egg'."""

    contains_whl: bool = False
    """Whether path contains '.whl'."""

    # Confidence factors
    confidence_factors: Dict[str, float] = None
    """Confidence factors for classification."""

    suggested_origin: Optional[PackageOrigin] = None
    """Suggested package origin based on path analysis."""

    confidence_score: float = 0.0
    """Confidence score for suggested origin."""

    def __post_init__(self):
        if self.confidence_factors is None:
            self.confidence_factors = {}


class PathAnalyzer:
    """Path analysis and classification engine."""

    def __init__(self):
        self._cache: Dict[str, PathAnalysis] = {}
        self._platform_utils = platform_utils
        self._safe_path = safe_path

        # Platform-specific patterns
        self._platform_patterns = self._init_platform_patterns()

        # Common patterns for detection
        self._patterns = {
            "site_packages": re.compile(
                r"(site-packages|dist-packages)", re.IGNORECASE
            ),
            "wheel": re.compile(r"\.whl$|\.dist-info", re.IGNORECASE),
            "egg": re.compile(r"\.egg($|[-_])|\.egg-info", re.IGNORECASE),
            "venv": re.compile(r"(venv|virtualenv|\.venv|env)", re.IGNORECASE),
            "conda": re.compile(r"conda", re.IGNORECASE),
            "docker": re.compile(r"docker", re.IGNORECASE),
            "development": re.compile(
                r"(src|lib|develop|dev|test|docs)", re.IGNORECASE
            ),
            "system": re.compile(r"^(/usr|/etc|/var|/opt|C:\\|D:\\)", re.IGNORECASE),
            "home": re.compile(r"^(/home|/Users|C:\\Users)", re.IGNORECASE),
        }

    def _init_platform_patterns(self) -> Dict[PlatformType, Dict[str, Pattern]]:
        """Initialize platform-specific patterns."""
        patterns = {}

        # Windows patterns
        windows_patterns = {
            "program_files": re.compile(r"C:\\Program Files", re.IGNORECASE),
            "program_files_x86": re.compile(
                r"C:\\Program Files \(x86\)", re.IGNORECASE
            ),
            "appdata": re.compile(r"AppData", re.IGNORECASE),
            "windows": re.compile(r"Windows", re.IGNORECASE),
            "python_install": re.compile(r"Python[0-9]*", re.IGNORECASE),
        }
        patterns[PlatformType.WINDOWS] = windows_patterns

        # Linux patterns
        linux_patterns = {
            "usr": re.compile(r"/usr/"),
            "etc": re.compile(r"/etc/"),
            "var": re.compile(r"/var/"),
            "opt": re.compile(r"/opt/"),
            "home": re.compile(r"/home/"),
            "local": re.compile(r"/usr/local/"),
            "lib": re.compile(r"/lib/"),
        }
        patterns[PlatformType.LINUX] = linux_patterns
        patterns[PlatformType.WSL] = linux_patterns  # WSL uses Linux patterns

        # macOS patterns
        macos_patterns = {
            "applications": re.compile(r"/Applications", re.IGNORECASE),
            "library": re.compile(r"/Library", re.IGNORECASE),
            "users": re.compile(r"/Users", re.IGNORECASE),
            "system": re.compile(r"/System", re.IGNORECASE),
            "homebrew": re.compile(r"(/usr/local/opt|/opt/homebrew)", re.IGNORECASE),
        }
        patterns[PlatformType.MACOS] = macos_patterns

        return patterns

    def analyze(
        self,
        path: Path,
        resolve_symlinks: bool = True,
        check_parents: bool = True,
        max_parent_depth: int = 5,
    ) -> PathAnalysis:
        """
        Analyze a path to gather comprehensive information.

        Args:
            path: Path to analyze.
            resolve_symlinks: Whether to resolve symbolic links.
            check_parents: Whether to check parent directories.
            max_parent_depth: Maximum depth to check parent directories.

        Returns:
            PathAnalysis object with detailed information.

        Raises:
            PathResolutionError: If path resolution fails.
        """
        cache_key = f"{path}:{resolve_symlinks}:{check_parents}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            # Basic path information
            resolved_path = (
                self._safe_path.resolve(path) if resolve_symlinks else path.absolute()
            )
            normalized_path = self._platform_utils.normalize_path_case(resolved_path)

            # Check if path exists and get stats
            exists = self._safe_path.exists(resolved_path)
            is_file = exists and resolved_path.is_file()
            is_dir = exists and resolved_path.is_dir()
            is_symlink = exists and resolved_path.is_symlink()

            # Path components
            parent = resolved_path.parent
            parts = resolved_path.parts
            depth = len(parts)

            # Create initial analysis
            analysis = PathAnalysis(
                path=str(path),
                resolved_path=resolved_path,
                normalized_path=normalized_path,
                is_absolute=resolved_path.is_absolute(),
                exists=exists,
                is_file=is_file,
                is_dir=is_dir,
                is_symlink=is_symlink,
                parent=parent,
                parts=parts,
                depth=depth,
            )

            # Perform comprehensive analysis
            self._analyze_location(analysis)
            self._analyze_indicators(analysis)
            self._analyze_patterns(analysis)

            if check_parents:
                self._analyze_parents(analysis, max_parent_depth)

            # Calculate confidence and suggest origin
            self._calculate_confidence(analysis)

            # Cache the result
            self._cache[cache_key] = analysis

            return analysis

        except Exception as e:
            raise PathResolutionError(path, e) from e

    def _analyze_location(self, analysis: PathAnalysis) -> None:
        """Analyze path location and context."""
        try:
            path_str = str(analysis.normalized_path)
            platform_type = self._platform_utils.detect_platform()

            # Check for site-packages
            analysis.contains_site_packages = "site-packages" in path_str.lower()
            analysis.contains_dist_packages = "dist-packages" in path_str.lower()
            analysis.in_site_packages = (
                analysis.contains_site_packages or analysis.contains_dist_packages
            )

            # Check for common directories
            analysis.contains_lib = "/lib/" in path_str or "\\lib\\" in path_str
            analysis.contains_src = "/src/" in path_str or "\\src\\" in path_str
            analysis.contains_bin = "/bin/" in path_str or "\\bin\\" in path_str
            analysis.contains_egg = ".egg" in path_str.lower()
            analysis.contains_whl = ".whl" in path_str.lower()

            # Check if in user's home directory
            home_dir = self._platform_utils.get_home_dir()
            analysis.in_home_dir = self._safe_path.is_relative_to(
                analysis.resolved_path, home_dir
            )

            # Check system directories
            if platform_type == PlatformType.WINDOWS:
                analysis.in_system_dir = any(
                    pattern.search(path_str)
                    for pattern in self._platform_patterns[platform_type].values()
                )
            else:
                analysis.in_system_dir = path_str.startswith(
                    ("/usr", "/etc", "/var", "/opt", "/System")
                )

            # Check for virtual environment
            analysis.in_venv = self._check_venv(analysis)

            # Check for Conda environment
            analysis.in_conda = self._check_conda(analysis)

            # Check for Docker (simplified - more detailed in environment detection)
            analysis.in_docker = "docker" in path_str.lower()

            # Determine user vs system site-packages
            if analysis.in_site_packages:
                if analysis.in_home_dir:
                    analysis.in_user_site = True
                else:
                    analysis.in_system_site = True

            # Check for development directory
            analysis.in_development_dir = self._check_development_dir(analysis)

            # Check for source directory
            analysis.in_source_dir = analysis.contains_src or self._check_source_dir(
                analysis
            )

        except Exception as e:
            warnings.warn(f"Failed to analyze location: {e}", RuntimeWarning)

    def _analyze_indicators(self, analysis: PathAnalysis) -> None:
        """Analyze path for various indicators."""
        try:
            path_str = str(analysis.normalized_path)

            # Check for editable indicators
            analysis.has_editable_indicators = any(
                indicator in path_str for indicator in EDITABLE_INDICATORS
            )

            # Check for development indicators
            analysis.has_development_indicators = any(
                indicator in path_str for indicator in DEVELOPMENT_INDICATORS
            )

            # Check for wheel indicators
            analysis.has_wheel_indicators = any(
                indicator in path_str for indicator in WHEEL_INDICATORS
            )

            # Check for egg indicators
            analysis.has_egg_indicators = any(
                indicator in path_str for indicator in EGG_INDICATORS
            )

        except Exception as e:
            warnings.warn(f"Failed to analyze indicators: {e}", RuntimeWarning)

    def _analyze_patterns(self, analysis: PathAnalysis) -> None:
        """Analyze path using regex patterns."""
        try:
            path_str = str(analysis.normalized_path)

            # Apply platform-specific patterns
            platform_type = self._platform_utils.detect_platform()
            if platform_type in self._platform_patterns:
                for pattern_name, pattern in self._platform_patterns[
                    platform_type
                ].items():
                    if pattern.search(path_str):
                        analysis.confidence_factors[
                            f"platform_pattern_{pattern_name}"
                        ] = 0.1

            # Apply general patterns
            for pattern_name, pattern in self._patterns.items():
                if pattern.search(path_str):
                    analysis.confidence_factors[f"pattern_{pattern_name}"] = 0.1

        except Exception as e:
            warnings.warn(f"Failed to analyze patterns: {e}", RuntimeWarning)

    def _analyze_parents(self, analysis: PathAnalysis, max_depth: int) -> None:
        """Analyze parent directories for additional context."""
        try:
            current = analysis.resolved_path.parent
            depth = 0

            while current and depth < max_depth:
                parent_str = str(current)

                # Check for editable files in parent directories
                for indicator in EDITABLE_INDICATORS:
                    indicator_file = current / indicator
                    if indicator_file.exists():
                        analysis.has_editable_indicators = True
                        analysis.confidence_factors[f"parent_editable_{indicator}"] = (
                            0.2
                        )

                # Check for development files
                for indicator in DEVELOPMENT_INDICATORS:
                    indicator_file = current / indicator
                    if indicator_file.exists():
                        analysis.has_development_indicators = True
                        analysis.confidence_factors[
                            f"parent_development_{indicator}"
                        ] = 0.15

                # Check for setup.py or pyproject.toml
                if (current / "setup.py").exists() or (
                    current / "pyproject.toml"
                ).exists():
                    analysis.in_development_dir = True
                    analysis.confidence_factors["parent_has_setup"] = 0.3

                # Check for .git directory
                if (current / ".git").exists():
                    analysis.in_development_dir = True
                    analysis.confidence_factors["parent_has_git"] = 0.4

                # Move up
                if current == current.parent:  # Reached root
                    break

                current = current.parent
                depth += 1

        except Exception as e:
            warnings.warn(f"Failed to analyze parents: {e}", RuntimeWarning)

    def _check_venv(self, analysis: PathAnalysis) -> bool:
        """Check if path is in a virtual environment."""
        try:
            path_str = str(analysis.resolved_path)

            # Check common venv patterns
            venv_patterns = [
                r"venv/",
                r"\.venv/",
                r"virtualenv/",
                r"env/",
                r"VIRTUAL_ENV",
            ]

            for pattern in venv_patterns:
                if re.search(pattern, path_str, re.IGNORECASE):
                    return True

            # Check if in known venv directories
            if "VIRTUAL_ENV" in os.environ:
                venv_path = Path(os.environ["VIRTUAL_ENV"])
                return self._safe_path.is_relative_to(analysis.resolved_path, venv_path)

            return False

        except Exception:
            return False

    def _check_conda(self, analysis: PathAnalysis) -> bool:
        """Check if path is in a Conda environment."""
        try:
            path_str = str(analysis.resolved_path)

            # Check for conda patterns
            conda_patterns = [
                r"conda/",
                r"miniconda/",
                r"anaconda/",
                r"envs/",
            ]

            for pattern in conda_patterns:
                if re.search(pattern, path_str, re.IGNORECASE):
                    return True

            # Check environment variables
            if "CONDA_PREFIX" in os.environ:
                conda_path = Path(os.environ["CONDA_PREFIX"])
                return self._safe_path.is_relative_to(
                    analysis.resolved_path, conda_path
                )

            return False

        except Exception:
            return False

    def _check_development_dir(self, analysis: PathAnalysis) -> bool:
        """Check if path is in a development directory."""
        try:
            # Check for development indicators in path
            dev_keywords = {"src", "lib", "develop", "dev", "test", "docs", "build"}
            path_parts = set(analysis.parts)

            if any(keyword in path_parts for keyword in dev_keywords):
                return True

            # Check for development files in the directory
            if analysis.resolved_path.is_dir():
                dev_files = {
                    ".git",
                    ".hg",
                    ".svn",
                    "setup.py",
                    "pyproject.toml",
                    "requirements.txt",
                }
                for dev_file in dev_files:
                    if (analysis.resolved_path / dev_file).exists():
                        return True

            return False

        except Exception:
            return False

    def _check_source_dir(self, analysis: PathAnalysis) -> bool:
        """Check if path is in a source directory."""
        try:
            # Look for source-like structure
            if analysis.resolved_path.is_dir():
                # Check for Python source files
                py_files = list(analysis.resolved_path.glob("*.py"))
                if len(py_files) > 0:
                    # Check if it's not in site-packages
                    if not analysis.in_site_packages:
                        return True

            return False

        except Exception:
            return False

    def _calculate_confidence(self, analysis: PathAnalysis) -> None:
        """Calculate confidence and suggest package origin."""
        try:
            confidence_factors = analysis.confidence_factors
            path_str = str(analysis.normalized_path)

            # Start with base confidence
            confidence = 0.0

            # Strong indicators
            if analysis.in_site_packages:
                confidence += 0.4
                if analysis.in_user_site:
                    confidence_factors["user_site_packages"] = 0.4
                    analysis.suggested_origin = PackageOrigin.USER_SITE
                else:
                    confidence_factors["system_site_packages"] = 0.4
                    analysis.suggested_origin = PackageOrigin.SITE_PACKAGES

            if analysis.has_wheel_indicators or analysis.contains_whl:
                confidence += 0.5
                confidence_factors["wheel_indicators"] = 0.5
                analysis.suggested_origin = PackageOrigin.WHEEL

            if analysis.has_egg_indicators or analysis.contains_egg:
                confidence += 0.5
                confidence_factors["egg_indicators"] = 0.5
                analysis.suggested_origin = PackageOrigin.EGG

            if analysis.has_editable_indicators:
                confidence += 0.6
                confidence_factors["editable_indicators"] = 0.6
                analysis.suggested_origin = PackageOrigin.EDITABLE

            if analysis.in_development_dir:
                confidence += 0.3
                confidence_factors["development_dir"] = 0.3
                if not analysis.suggested_origin:
                    analysis.suggested_origin = PackageOrigin.EDITABLE

            if analysis.in_source_dir:
                confidence += 0.4
                confidence_factors["source_dir"] = 0.4
                analysis.suggested_origin = PackageOrigin.SOURCE

            # Environment indicators
            if analysis.in_venv:
                confidence += 0.2
                confidence_factors["in_venv"] = 0.2

            if analysis.in_conda:
                confidence += 0.3
                confidence_factors["in_conda"] = 0.3
                if not analysis.suggested_origin:
                    analysis.suggested_origin = PackageOrigin.CONDA

            # Location-based indicators
            if analysis.in_home_dir and not analysis.in_site_packages:
                confidence += 0.2
                confidence_factors["in_home_dir"] = 0.2

            if analysis.in_system_dir:
                confidence += 0.1
                confidence_factors["in_system_dir"] = 0.1
                if not analysis.suggested_origin:
                    analysis.suggested_origin = PackageOrigin.SYSTEM

            # Add pattern-based confidence
            confidence += sum(confidence_factors.values()) * 0.1

            # Cap confidence at 1.0
            confidence = min(confidence, 1.0)

            # If no specific origin suggested, mark as unknown
            if not analysis.suggested_origin:
                analysis.suggested_origin = PackageOrigin.UNKNOWN

            analysis.confidence_score = confidence

        except Exception as e:
            warnings.warn(f"Failed to calculate confidence: {e}", RuntimeWarning)
            analysis.suggested_origin = PackageOrigin.UNKNOWN
            analysis.confidence_score = 0.0

    def get_suggested_origin(
        self, path: Path, min_confidence: float = 0.3
    ) -> Tuple[Optional[PackageOrigin], float]:
        """
        Get suggested package origin from path analysis.

        Args:
            path: Path to analyze.
            min_confidence: Minimum confidence threshold.

        Returns:
            Tuple of (suggested_origin, confidence_score).
        """
        analysis = self.analyze(path)

        if analysis.confidence_score >= min_confidence:
            return analysis.suggested_origin, analysis.confidence_score
        else:
            return PackageOrigin.UNKNOWN, analysis.confidence_score

    def clear_cache(self):
        """Clear the path analysis cache."""
        self._cache.clear()


# Global path analyzer instance
path_analyzer = PathAnalyzer()
