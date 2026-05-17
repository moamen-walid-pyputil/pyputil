#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Package Detector Constants and Definitions.

This module contains all constants, enumerations, and type definitions
used throughout the package detector.
"""

from enum import Enum, auto
from typing import Literal, Dict, Any, Optional, List, Tuple, Set
from dataclasses import dataclass
from pathlib import Path


class PackageOrigin(str, Enum):
    """Enumeration of all possible package origins."""

    BUILTIN = "builtin"
    """Built-in modules compiled into Python interpreter (C extensions)."""

    STDLIB = "stdlib"
    """Python standard library modules."""

    SITE_PACKAGES = "site-packages"
    """System-wide pip installation in site-packages."""

    USER_SITE = "user-site"
    """User-local pip installation in user site-packages."""

    EDITABLE = "editable"
    """Development/editable installation (pip install -e .)."""

    WHEEL = "wheel"
    """Wheel-based installation (.whl file)."""

    EGG = "egg"
    """Legacy egg-based installation."""

    NAMESPACE = "namespace"
    """Namespace package (PEP 420)."""

    FROZEN = "frozen"
    """Frozen/packaged application (PyInstaller, cx_Freeze)."""

    DOCKER = "docker"
    """Running inside Docker container."""

    VENV = "venv"
    """Virtual environment."""

    CONDA = "conda"
    """Conda/Miniconda/Anaconda environment."""

    SYSTEM = "system"
    """System package manager (apt, yum, brew, pacman)."""

    BUNDLED = "bundled"
    """Bundled with application."""

    SOURCE = "source"
    """Direct from source directory."""

    UNKNOWN = "unknown"
    """Cannot determine origin."""

    NOT_FOUND = None
    """Package not found."""


class DetectionConfidence(str, Enum):
    """Confidence levels for detection results."""

    HIGH = "high"  # 90-100% confidence
    MEDIUM = "medium"  # 70-89% confidence
    LOW = "low"  # 50-69% confidence
    WEAK = "weak"  # <50% confidence


class PlatformType(str, Enum):
    """Platform types."""

    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    CYGWIN = "cygwin"
    WSL = "wsl"  # Windows Subsystem for Linux
    UNKNOWN = "unknown"


class EnvironmentType(str, Enum):
    """Environment types."""

    VENV = "venv"
    CONDA = "conda"
    PIPENV = "pipenv"
    POETRY = "poetry"
    VIRTUALENV = "virtualenv"
    DOCKER = "docker"
    SYSTEM = "system"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PackageInfo:
    """Detailed information about a package's origin and installation."""

    name: str
    """Package name."""

    origin: PackageOrigin
    """Detected origin of the package."""

    confidence: DetectionConfidence
    """Confidence level of the detection."""

    confidence_score: float
    """Numerical confidence score (0.0 to 1.0)."""

    path: Optional[Path] = None
    """Path to the package/module."""

    version: Optional[str] = None
    """Package version if available."""

    installer: Optional[str] = None
    """Installer used (pip, conda, system, etc.)."""

    is_editable: bool = False
    """Whether it's an editable installation."""

    is_namespace: bool = False
    """Whether it's a namespace package."""

    is_development: bool = False
    """Whether it's in a development environment."""

    metadata: Optional[Dict[str, Any]] = None
    """Raw package metadata if available."""

    environment_info: Optional[Dict[str, Any]] = None
    """Information about the environment."""

    detection_methods: Optional[List[str]] = None
    """Methods used for detection."""

    @property
    def is_stdlib(self) -> bool:
        """Check if package is from standard library."""
        return self.origin == PackageOrigin.STDLIB

    @property
    def is_builtin(self) -> bool:
        """Check if package is built-in."""
        return self.origin == PackageOrigin.BUILTIN

    @property
    def is_installed(self) -> bool:
        """Check if package is installed (not builtin/stdlib)."""
        return self.origin not in [
            PackageOrigin.BUILTIN,
            PackageOrigin.STDLIB,
            PackageOrigin.NOT_FOUND,
        ]


# Platform-specific constants
WINDOWS_SITE_PATHS = [
    Path.home() / "AppData" / "Roaming" / "Python",
    Path.home() / "AppData" / "Local" / "Programs" / "Python",
    Path("C:\\Python*"),
]

LINUX_SITE_PATHS = [
    Path.home() / ".local" / "lib",
    Path("/usr/local/lib"),
    Path("/usr/lib"),
]

MACOS_SITE_PATHS = [
    Path.home() / "Library" / "Python",
    Path("/Library/Python"),
    Path("/usr/local/lib"),
]

# Common indicators for different installation types
EDITABLE_INDICATORS = {
    ".egg-link",
    "setup.py",
    "pyproject.toml",
    "setup.cfg",
    ".pth",
}

DEVELOPMENT_INDICATORS = {
    ".git",
    ".hg",
    ".svn",
    ".gitignore",
    "requirements.txt",
    "requirements-dev.txt",
    "tests",
    "docs",
}

WHEEL_INDICATORS = {
    ".dist-info",
    ".whl",
    "WHEEL",
}

EGG_INDICATORS = {
    ".egg-info",
    ".egg",
    "EGG-INFO",
}

# Confidence thresholds
CONFIDENCE_THRESHOLDS = {
    "high": 0.9,
    "medium": 0.7,
    "low": 0.5,
}
