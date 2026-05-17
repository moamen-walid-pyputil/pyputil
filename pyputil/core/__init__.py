#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# =========================
# Explorer
# =========================
from .explorer import pmeX

# =========================
# Searcher
# =========================
from .searcher import (
    SearchStrategy,
    Searcher,
    search_package,
    search_sync,
)

# =========================
# Backup System
# =========================
from .backup.core import ModuleBackup

from .backup.base import (
    BackupCleanupResult as BackupCleanupResult,
    BackupEntry,
    BackupFormat,
    BackupInfo,
    BackupResult,
    BackupStatus,
    ErrorSeverity as BackupErrorSeverity,
    RestoreResult,
    VerificationResult as BackupVerificationResult,
)

from .backup.exceptions import (
    BackupCorruptedError,
    BackupError,
    BackupNotFoundError,
    ModuleNotFoundError,
)

# =========================
# Utilities
# =========================
from .zipmodule import ZipModule
from .importhub.import_module import import_module
from . import sca

# =========================
# Exceptions
# =========================
from ..PyputilException import PyputilException

# =========================
# Public API
# =========================
__all__ = [
    # Backup System
    "ModuleBackup",
    "BackupFormat",
    "BackupStatus",
    "BackupErrorSeverity",
    "BackupEntry",
    "BackupResult",
    "RestoreResult",
    "BackupVerificationResult",
    "BackupCleanupResult",
    "BackupInfo",

    # Backup Exceptions
    "ModuleNotFoundError",
    "BackupCorruptedError",
    "BackupNotFoundError",
    "BackupError",

    # Searcher
    "SearchStrategy",
    "Searcher",
    "search_sync",
    "search_package",

    # Explorer
    "pmeX",

    # Utilities
    "import_module",
    "ZipModule",
    "sca",

    # Exceptions
    "PyputilException",
]

# =========================
# Cleanup Namespace
# =========================
from ..api import clean

clean(expose=__all__)