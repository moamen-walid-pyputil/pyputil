#!/usr/bin/env python3

# -*- coding: utf-8 -*-

class FrozenModuleError(Exception):
    """Base exception for frozen module related errors."""
    pass


class ModuleCompilationError(FrozenModuleError):
    """Raised when a module fails to compile."""
    pass


class ModuleNotFoundError(FrozenModuleError):
    """Raised when a module is not found in the frozen registry."""
    pass


class DuplicateModuleWarning(UserWarning):
    """Warning for duplicate module additions."""
    pass


class ImportCycleWarning(UserWarning):
    """Warning when circular imports are detected."""
    pass


class CompatibilityWarning(UserWarning):
    """Warning for Python version compatibility issues."""
    pass