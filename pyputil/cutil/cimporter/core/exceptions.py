#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    CORE EXCEPTION HIERARCHY
==================================

Unified exception system for cross-platform compilation errors.
Provides normalized error handling across different compilers and platforms.
"""

from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any
import traceback
import sys
import time
import re


class ErrorSeverity(Enum):
    """
    Severity level enumeration for compilation and loading errors.

    This enum categorizes errors by their impact on the compilation process,
    enabling appropriate handling strategies and user feedback.

    Attributes
    ----------
    FATAL : str
        Unrecoverable error that halts the entire process.
    ERROR : str
        Compilation or loading error for a specific module.
    WARNING : str
        Non-critical issue that doesn't prevent compilation.
    INFO : str
        Informational message about potential improvements.
    DEBUG : str
        Detailed diagnostic information for debugging.
    """

    FATAL = "fatal"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    DEBUG = "debug"


class ErrorCategory(Enum):
    """
    Categorization of error types for structured error handling.

    This enum classifies errors by their source or nature, enabling
    targeted recovery strategies and user guidance.

    Attributes
    ----------
    COMPILER_NOT_FOUND : str
        Required compiler is not installed or not in PATH.
    COMPILATION_FAILED : str
        Compiler reported errors during compilation.
    LINK_FAILED : str
        Linking stage failed.
    CACHE_CORRUPTION : str
        Cached binary is corrupted or incompatible.
    IMPORT_FAILED : str
        Python module import failed after successful compilation.
    DEPENDENCY_MISSING : str
        Required dependency module not found.
    PLATFORM_INCOMPATIBLE : str
        Operation not supported on current platform.
    SANDBOX_VIOLATION : str
        Compilation exceeded resource limits or security boundaries.
    CONFIGURATION_ERROR : str
        Invalid configuration or malformed flags.
    I_O_ERROR : str
        File system or input/output operation failed.
    TIMEOUT : str
        Operation exceeded time limit.
    MEMORY_LIMIT : str
        Operation exceeded memory limit.
    NOT_FOUND : str
        Requested resource not found.
    UNKNOWN : str
        Unclassified error type.
    """

    COMPILER_NOT_FOUND = "compiler_not_found"
    COMPILATION_FAILED = "compilation_failed"
    LINK_FAILED = "linker_error"  # Keep value for backward compatibility
    LINKER_ERROR = "linker_error"
    CACHE_CORRUPTION = "cache_corruption"
    IMPORT_FAILED = "import_failed"
    DEPENDENCY_MISSING = "dependency_missing"
    PLATFORM_INCOMPATIBLE = "platform_incompatible"
    SANDBOX_VIOLATION = "sandbox_violation"
    CONFIGURATION_ERROR = "configuration_error"
    I_O_ERROR = "io_error"
    TIMEOUT = "timeout"
    MEMORY_LIMIT = "memory_limit"
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"


class CImporterBaseException(Exception):
    """
    Base exception class for all cimporter-specific exceptions.

    This abstract base class provides common functionality for error
    handling including severity levels, error categorization, and
    structured error context.

    Parameters
    ----------
    message : str
        Human-readable error message.
    severity : ErrorSeverity, optional
        Severity level of the error (default: ErrorSeverity.ERROR).
    category : ErrorCategory, optional
        Category of the error (default: ErrorCategory.UNKNOWN).
    context : Optional[Dict[str, Any]], optional
        Additional contextual information about the error.
    cause : Optional[Exception], optional
        Original exception that caused this error.

    Attributes
    ----------
    message : str
        Error message.
    severity : ErrorSeverity
        Error severity level.
    category : ErrorCategory
        Error category.
    context : Dict[str, Any]
        Contextual information dictionary.
    cause : Optional[Exception]
        Original cause exception.
    timestamp : float
        Unix timestamp when the exception was created.
    traceback_str : str
        Formatted traceback string.

    Examples
    --------
    >>> try:
    ...     compile_file("source.c")
    ... except CompileError as e:
    ...     print(f"Severity: {e.severity}")
    ...     print(f"Category: {e.category}")
    ...     print(f"Context: {e.context}")
    """

    def __init__(
        self,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        self.message = message
        self.severity = severity
        self.category = category
        self.context = context or {}
        self.cause = cause
        self.timestamp = time.time()
        
        # Capture traceback
        try:
            self.traceback_str = "".join(traceback.format_stack()[:-1])
        except Exception:
            self.traceback_str = ""

        # Build comprehensive error message
        full_message = self._build_message()
        super().__init__(full_message)

    def _build_message(self) -> str:
        """
        Build a comprehensive error message with all available context.

        Returns
        -------
        str
            Formatted error message including severity, category, and context.
        """
        parts = [
            f"[{self.severity.value.upper()}]",
            f"[{self.category.value}]",
            self.message,
        ]

        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            parts.append(f"Context: {{{context_str}}}")

        if self.cause:
            parts.append(f"Caused by: {type(self.cause).__name__}: {str(self.cause)}")

        return " ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert exception to a serializable dictionary.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation of the exception suitable for logging.
        """
        return {
            "type": self.__class__.__name__,
            "message": self.message,
            "severity": self.severity.value,
            "category": self.category.value,
            "context": self.context,
            "timestamp": self.timestamp,
            "cause": str(self.cause) if self.cause else None,
        }

    def is_recoverable(self) -> bool:
        """
        Determine if this error is potentially recoverable.

        Returns
        -------
        bool
            True if the error can be recovered from, False otherwise.
        """
        return self.severity not in (ErrorSeverity.FATAL, ErrorSeverity.ERROR)


class CompileError(CImporterBaseException):
    """
    Unified compilation error across all compilers and platforms.

    This exception normalizes error messages from different compilers
    (GCC, Clang, MSVC, ICC) into a consistent format for easier debugging
    and cross-platform error handling.

    Parameters
    ----------
    compiler : str
        Name of the compiler that produced the error.
    message : str
        Error message describing the compilation failure.
    source_file : Optional[Path], optional
        Path to the source file that failed to compile.
    command : Optional[List[str]], optional
        The compilation command that was executed.
    stderr : Optional[str], optional
        Raw stderr output from the compiler.
    stdout : Optional[str], optional
        Raw stdout output from the compiler.
    return_code : Optional[int], optional
        Exit code returned by the compiler.
    line_errors : Optional[List[Dict[str, Any]]], optional
        Parsed line-by-line error information.
    severity : ErrorSeverity, optional
        Error severity (default: ErrorSeverity.ERROR).
    cause : Optional[Exception], optional
        Original cause exception.

    Attributes
    ----------
    compiler : str
        Compiler name.
    source_file : Optional[Path]
        Source file path.
    command : Optional[List[str]]
        Compilation command.
    stderr : Optional[str]
        Standard error output.
    stdout : Optional[str]
        Standard output.
    return_code : Optional[int]
        Process return code.
    line_errors : List[Dict[str, Any]]
        Structured error information per source line.

    Examples
    --------
    >>> try:
    ...     result = compile_source("module.c", compiler="gcc")
    ... except CompileError as e:
    ...     print(f"Compiler: {e.compiler}")
    ...     print(f"Source: {e.source_file}")
    ...     print(f"Errors: {e.parse_error_lines()}")
    ...     if e.stderr:
    ...         print(f"Details: {e.stderr}")
    """

    def __init__(
        self,
        compiler: str,
        message: str,
        source_file: Optional[Path] = None,
        command: Optional[List[str]] = None,
        stderr: Optional[str] = None,
        stdout: Optional[str] = None,
        return_code: Optional[int] = None,
        line_errors: Optional[List[Dict[str, Any]]] = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        category: Optional[ErrorCategory] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        # Build context
        ctx = context.copy() if context else {}
        ctx.update({
            "compiler": compiler,
            "source_file": str(source_file) if source_file else None,
            "return_code": return_code,
        })

        # FIXED: Remove 'category' from kwargs before passing to super()
        # Use provided category or default to COMPILATION_FAILED
        cat = category if category is not None else ErrorCategory.COMPILATION_FAILED

        super().__init__(
            message=message,
            severity=severity,
            category=cat,
            context=ctx,
            cause=cause,
        )

        self.compiler = compiler
        self.source_file = source_file
        self.command = command
        self.stderr = stderr
        self.stdout = stdout
        self.return_code = return_code
        self.line_errors = line_errors or self._parse_error_lines()

    def _parse_error_lines(self) -> List[Dict[str, Any]]:
        """
        Parse compiler stderr output to extract structured error information.

        This method attempts to extract file names, line numbers, and error
        messages from compiler output, handling the different formats used
        by GCC/Clang and MSVC.

        Returns
        -------
        List[Dict[str, Any]]
            List of parsed error entries, each containing:
            - file: Source file name
            - line: Line number (if available)
            - column: Column number (if available)
            - message: Error message
            - severity: 'error', 'warning', or 'note'
            - raw: Original line from compiler output
        """
        if not self.stderr:
            return []

        errors = []
        lines = self.stderr.split("\n")

        # GCC/Clang format: filename:line:column: severity: message
        gcc_pattern = re.compile(
            r"^([^:]+):(\d+):(\d+):\s*(error|warning|note):\s*(.+)$"
        )

        # MSVC format: filename(line) : severity C####: message
        msvc_pattern = re.compile(
            r"^([^(]+)\((\d+)\)\s*:\s*(error|warning)\s+(\w+):\s*(.+)$"
        )

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Try GCC/Clang pattern
            match = gcc_pattern.match(line)
            if match:
                errors.append({
                    "file": match.group(1),
                    "line": int(match.group(2)),
                    "column": int(match.group(3)),
                    "severity": match.group(4),
                    "message": match.group(5),
                    "raw": line,
                })
                continue

            # Try MSVC pattern
            match = msvc_pattern.match(line)
            if match:
                errors.append({
                    "file": match.group(1),
                    "line": int(match.group(2)),
                    "column": None,
                    "severity": match.group(3),
                    "code": match.group(4),
                    "message": match.group(5),
                    "raw": line,
                })

        return errors

    def get_error_summary(self) -> str:
        """
        Generate a concise summary of compilation errors.

        Returns
        -------
        str
            Formatted summary of all compilation errors.
        """
        if not self.line_errors:
            return self.message

        error_count = sum(1 for e in self.line_errors if e.get("severity") == "error")
        warning_count = sum(1 for e in self.line_errors if e.get("severity") == "warning")

        summary = [f"Compilation failed with {error_count} error(s)"]
        if warning_count:
            summary.append(f"and {warning_count} warning(s)")

        for err in self.line_errors[:5]:  # Show first 5 errors
            loc = f"{err.get('file', 'unknown')}:{err.get('line', '?')}"
            summary.append(f"  {loc}: {err.get('message', 'unknown error')}")

        if len(self.line_errors) > 5:
            summary.append(f"  ... and {len(self.line_errors) - 5} more")

        return "\n".join(summary)


class LinkerError(CompileError):
    """
    Error occurring during the linking phase of compilation.

    Parameters
    ----------
    compiler : str
        Compiler/linker name.
    message : str
        Error message.
    object_files : Optional[List[Path]], optional
        List of object files being linked.
    undefined_symbols : Optional[List[str]], optional
        List of undefined symbols reported by the linker.
    duplicate_symbols : Optional[List[str]], optional
        List of duplicate symbols reported by the linker.
    severity : ErrorSeverity, optional
        Error severity (default: ErrorSeverity.ERROR).
    category : ErrorCategory, optional
        Error category (default: ErrorCategory.LINK_FAILED).

    Attributes
    ----------
    object_files : List[Path]
        Object files involved in linking.
    undefined_symbols : List[str]
        Undefined symbols.
    duplicate_symbols : List[str]
        Duplicate symbols.
    """

    def __init__(
        self,
        compiler: str,
        message: str,
        source_file: Optional[Path] = None,
        command: Optional[List[str]] = None,
        stderr: Optional[str] = None,
        stdout: Optional[str] = None,
        return_code: Optional[int] = None,
        object_files: Optional[List[Path]] = None,
        undefined_symbols: Optional[List[str]] = None,
        duplicate_symbols: Optional[List[str]] = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        category: Optional[ErrorCategory] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        # Build context
        ctx = context.copy() if context else {}
        ctx.update({
            "object_files": [str(f) for f in object_files] if object_files else [],
            "undefined_symbols": undefined_symbols or [],
            "duplicate_symbols": duplicate_symbols or [],
        })

        # FIXED: Use LINK_FAILED as default category
        cat = category if category is not None else ErrorCategory.LINK_FAILED

        super().__init__(
            compiler=compiler,
            message=message,
            source_file=source_file,
            command=command,
            stderr=stderr,
            stdout=stdout,
            return_code=return_code,
            severity=severity,
            category=cat,
            context=ctx,
            cause=cause,
        )

        self.object_files = object_files or []
        self.undefined_symbols = undefined_symbols or []
        self.duplicate_symbols = duplicate_symbols or []

        # Parse linker-specific errors if not provided
        if stderr and (not undefined_symbols or not duplicate_symbols):
            self._parse_linker_errors()

    def _parse_linker_errors(self) -> None:
        """
        Parse linker output to extract undefined and duplicate symbols.
        """
        if not self.stderr:
            return

        # Pattern for undefined reference (GCC/Clang)
        undefined_pattern = re.compile(
            r"undefined reference to [`']([^`']+)'"
        )

        # Pattern for multiple definition (GCC/Clang)
        duplicate_pattern = re.compile(r"multiple definition of [`']([^`']+)'")

        for line in self.stderr.split("\n"):
            match = undefined_pattern.search(line)
            if match:
                self.undefined_symbols.append(match.group(1))

            match = duplicate_pattern.search(line)
            if match:
                self.duplicate_symbols.append(match.group(1))


class CacheError(CImporterBaseException):
    """
    Error related to cache operations (read, write, validation).

    Parameters
    ----------
    message : str
        Error message.
    cache_path : Optional[Path], optional
        Path to the cache directory or file.
    cache_key : Optional[str], optional
        Cache key involved in the operation.
    operation : Optional[str], optional
        Operation being performed ('read', 'write', 'validate', 'clean').
    severity : ErrorSeverity, optional
        Error severity (default: ErrorSeverity.ERROR).

    Attributes
    ----------
    cache_path : Optional[Path]
        Cache path.
    cache_key : Optional[str]
        Cache key.
    operation : Optional[str]
        Operation type.
    """

    def __init__(
        self,
        message: str,
        cache_path: Optional[Path] = None,
        cache_key: Optional[str] = None,
        operation: Optional[str] = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        category: Optional[ErrorCategory] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        ctx = context.copy() if context else {}
        ctx.update({
            "cache_path": str(cache_path) if cache_path else None,
            "cache_key": cache_key,
            "operation": operation,
        })

        cat = category if category is not None else ErrorCategory.CACHE_CORRUPTION

        super().__init__(
            message=message,
            severity=severity,
            category=cat,
            context=ctx,
            cause=cause,
        )

        self.cache_path = cache_path
        self.cache_key = cache_key
        self.operation = operation


class ImportModuleError(CImporterBaseException):
    """
    Error occurring during Python module import after compilation.

    Parameters
    ----------
    module_name : str
        Name of the module being imported.
    library_path : Path
        Path to the compiled shared library.
    message : str
        Error message.
    python_error : Optional[Exception], optional
        Original Python import exception.
    severity : ErrorSeverity, optional
        Error severity (default: ErrorSeverity.ERROR).

    Attributes
    ----------
    module_name : str
        Module name.
    library_path : Path
        Library path.
    python_error : Optional[Exception]
        Original Python exception.
    """

    def __init__(
        self,
        module_name: str,
        library_path: Path,
        message: str,
        python_error: Optional[Exception] = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        category: Optional[ErrorCategory] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        ctx = context.copy() if context else {}
        ctx.update({
            "module_name": module_name,
            "library_path": str(library_path)
        })

        cat = category if category is not None else ErrorCategory.IMPORT_FAILED

        super().__init__(
            message=message,
            severity=severity,
            category=cat,
            context=ctx,
            cause=python_error or cause,
        )

        self.module_name = module_name
        self.library_path = library_path
        self.python_error = python_error


class DependencyError(CImporterBaseException):
    """
    Error related to module dependency resolution.

    Parameters
    ----------
    module_name : str
        Module with dependency issues.
    missing_deps : List[str]
        List of missing dependencies.
    circular_deps : Optional[List[List[str]]], optional
        List of circular dependency chains.
    severity : ErrorSeverity, optional
        Error severity (default: ErrorSeverity.ERROR).

    Attributes
    ----------
    module_name : str
        Module name.
    missing_deps : List[str]
        Missing dependencies.
    circular_deps : List[List[str]]
        Circular dependency chains.
    """

    def __init__(
        self,
        module_name: str,
        missing_deps: List[str],
        circular_deps: Optional[List[List[str]]] = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        category: Optional[ErrorCategory] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        ctx = context.copy() if context else {}
        ctx.update({
            "module_name": module_name,
            "missing_dependencies": missing_deps,
            "circular_dependencies": circular_deps or [],
        })

        message = f"Dependency resolution failed for '{module_name}'"
        if missing_deps:
            message += f": missing {', '.join(missing_deps)}"
        if circular_deps:
            message += f": circular dependency detected: {' -> '.join(circular_deps[0])}"

        cat = category if category is not None else ErrorCategory.DEPENDENCY_MISSING

        super().__init__(
            message=message,
            severity=severity,
            category=cat,
            context=ctx,
            cause=cause,
        )

        self.module_name = module_name
        self.missing_deps = missing_deps
        self.circular_deps = circular_deps or []


class PlatformError(CImporterBaseException):
    """
    Error indicating platform incompatibility.

    Parameters
    ----------
    operation : str
        Operation that is not supported.
    message : str
        Error message.
    required_platform : Optional[str], optional
        Platform required for the operation.
    current_platform : str, optional
        Current platform identifier (default: sys.platform).
    severity : ErrorSeverity, optional
        Error severity (default: ErrorSeverity.ERROR).

    Attributes
    ----------
    operation : str
        Operation name.
    required_platform : Optional[str]
        Required platform.
    current_platform : str
        Current platform.
    """

    def __init__(
        self,
        operation: str,
        message: str,
        required_platform: Optional[str] = None,
        current_platform: str = sys.platform,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        category: Optional[ErrorCategory] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        ctx = context.copy() if context else {}
        ctx.update({
            "operation": operation,
            "required_platform": required_platform,
            "current_platform": current_platform,
        })

        cat = category if category is not None else ErrorCategory.PLATFORM_INCOMPATIBLE

        super().__init__(
            message=message,
            severity=severity,
            category=cat,
            context=ctx,
            cause=cause,
        )

        self.operation = operation
        self.required_platform = required_platform
        self.current_platform = current_platform


class SandboxError(CImporterBaseException):
    """
    Error indicating a sandbox violation (resource limit exceeded).

    Parameters
    ----------
    violation_type : str
        Type of violation ('timeout', 'memory', 'filesystem', 'network').
    message : str
        Error message.
    limit : Any, optional
        Limit that was exceeded.
    actual : Any, optional
        Actual value that exceeded the limit.
    severity : ErrorSeverity, optional
        Error severity (default: ErrorSeverity.ERROR).

    Attributes
    ----------
    violation_type : str
        Violation type.
    limit : Any
        Limit value.
    actual : Any
        Actual value.
    """

    def __init__(
        self,
        violation_type: str,
        message: str,
        limit: Any = None,
        actual: Any = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        category: Optional[ErrorCategory] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        ctx = context.copy() if context else {}
        ctx.update({
            "violation_type": violation_type,
            "limit": limit,
            "actual": actual
        })

        cat = category if category is not None else ErrorCategory.SANDBOX_VIOLATION

        super().__init__(
            message=message,
            severity=severity,
            category=cat,
            context=ctx,
            cause=cause,
        )

        self.violation_type = violation_type
        self.limit = limit
        self.actual = actual


class ConfigError(CImporterBaseException):
    """
    Error related to configuration issues.

    Parameters
    ----------
    config_key : str
        Configuration key with issue.
    message : str
        Error message.
    expected : Any, optional
        Expected value or type.
    actual : Any, optional
        Actual value provided.
    severity : ErrorSeverity, optional
        Error severity (default: ErrorSeverity.ERROR).

    Attributes
    ----------
    config_key : str
        Configuration key.
    expected : Any
        Expected value.
    actual : Any
        Actual value.
    """

    def __init__(
        self,
        config_key: str,
        message: str,
        expected: Any = None,
        actual: Any = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        category: Optional[ErrorCategory] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        ctx = context.copy() if context else {}
        ctx.update({
            "config_key": config_key,
            "expected": expected,
            "actual": actual
        })

        cat = category if category is not None else ErrorCategory.CONFIGURATION_ERROR

        super().__init__(
            message=message,
            severity=severity,
            category=cat,
            context=ctx,
            cause=cause,
        )

        self.config_key = config_key
        self.expected = expected
        self.actual = actual