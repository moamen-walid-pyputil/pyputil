#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Custom exceptions for the cfast C runtime compilation engine.

This module defines a comprehensive exception hierarchy used throughout cfast
to provide clear, actionable, and well-structured error messages for various
failure scenarios. All custom exceptions inherit from `CFastError` to allow
easy catching of any cfast-specific error.

Exception Categories
--------------------
The exceptions are organized by their source and severity:

1. Compilation Errors
   - Failures during C code compilation (compiler errors, linker errors)
   - Compiler detection and availability issues
   - Timeout and resource exhaustion during compilation

2. Parsing and Signature Detection Errors
   - Failures during pycparser-based AST analysis
   - Type conversion and struct definition issues
   - Missing headers and preprocessor problems

3. Cache System Errors
   - Cache storage and retrieval failures
   - Cache corruption and integrity issues
   - File locking and concurrency problems

4. Platform and System Errors
   - Platform-specific compatibility issues
   - Library loading failures
   - Architecture and OS detection problems

5. Configuration and Validation Errors
   - Invalid user input and parameters
   - Source code validation failures
   - Function name resolution issues

6. Runtime and Execution Errors
   - Errors during C function execution
   - Memory access violations
   - Type conversion failures at runtime

Exception Hierarchy
-------------------
CFastError (Base)
├── CompilationError
│   ├── CompilerNotFoundError
│   ├── CompilationTimeoutError
│   ├── LinkerError
│   ├── PreprocessorError
│   └── AssemblyError
├── SignatureDetectionError
│   ├── PycparserNotAvailableError
│   ├── ParseSyntaxError
│   ├── StructDefinitionError
│   ├── TypeConversionError
│   └── IncludeResolutionError
├── CacheError
│   ├── CacheIntegrityError
│   ├── CacheCorruptionError
│   ├── CacheLockError
│   │   └── StaleLockError
│   ├── CacheCapacityError
│   └── CacheIOError
├── PlatformError
│   ├── UnsupportedPlatformError
│   ├── LibraryLoadError
│   ├── ArchitectureMismatchError
│   └── PermissionError
├── ConfigurationError
│   ├── InvalidSourceCodeError
│   ├── FunctionNotFoundError
│   ├── MultipleFunctionsError
│   ├── InvalidCompilerFlagError
│   └── IncludePathError
└── RuntimeError
    ├── FunctionCallError
    ├── MemoryAccessError
    ├── TypeMismatchError
    └── NullPointerError

Usage Examples
--------------
>>> from cfast.exceptions import *

>>> # Catch all cfast errors
>>> try:
...     cfast.load_c("invalid C code")
... except CFastError as e:
...     print(f"cfast error: {e}")

>>> # Handle specific error types
>>> try:
...     cfast.load_c(code, cflags=["-invalid-flag"])
... except InvalidCompilerFlagError as e:
...     print(f"Invalid flag: {e.flag}")
...     print(f"Available: {e.supported_flags}")

>>> # Inspect error details
>>> try:
...     cfast.load_c(malformed_code)
... except CompilationError as e:
...     print(f"Compiler: {e.compiler_name}")
...     print(f"Exit code: {e.exit_code}")
...     print(f"Stderr:\n{e.compiler_output}")
...     if e.source_context:
...         print(f"Error at line {e.error_line}:")
...         print(e.source_context)

>>> # Platform-specific handling
>>> try:
...     lib = cfast.load_c(code)
... except UnsupportedPlatformError as e:
...     print(f"Platform '{e.platform_name}' not supported")
...     print(f"Supported: {e.supported_platforms}")
... except ArchitectureMismatchError as e:
...     print(f"Architecture mismatch: {e.expected} vs {e.actual}")
"""

import sys
import os
import textwrap
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto


# =============================================================================
# Error Severity Levels
# =============================================================================

class ErrorSeverity(Enum):
    """Severity level of an error."""
    DEBUG = auto()      # Debugging information
    INFO = auto()       # Informational message
    WARNING = auto()    # Warning, operation continues
    ERROR = auto()      # Error, operation fails
    CRITICAL = auto()   # Critical, system may be unstable
    FATAL = auto()      # Fatal, cannot recover


# =============================================================================
# Source Code Context Extraction
# =============================================================================

@dataclass
class SourceContext:
    """
    Context information for source code errors.
    
    Attributes
    ----------
    line_number : int
        Line number where error occurred (1-indexed).
    column : Optional[int]
        Column number where error occurred.
    line_content : str
        Content of the error line.
    context_before : List[str]
        Lines before the error line.
    context_after : List[str]
        Lines after the error line.
    """
    line_number: int
    column: Optional[int] = None
    line_content: str = ""
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)
    
    def format(self, context_lines: int = 3) -> str:
        """
        Format source context for error display.
        
        Parameters
        ----------
        context_lines : int
            Number of context lines to show before and after.
        
        Returns
        -------
        str
            Formatted source context.
        """
        lines = []
        
        # Add context before
        start_idx = max(0, len(self.context_before) - context_lines)
        for i, line in enumerate(self.context_before[start_idx:], start_idx + 1):
            lines.append(f"  {i:4d} | {line}")
        
        # Add error line with indicator
        lines.append(f"> {self.line_number:4d} | {self.line_content}")
        if self.column:
            lines.append(f"  {' ' * 4} | {' ' * (self.column - 1)}^")
        
        # Add context after
        for i, line in enumerate(self.context_after[:context_lines], 
                                  self.line_number + 1):
            lines.append(f"  {i:4d} | {line}")
        
        return "\n".join(lines)


def extract_source_context(
    code: str,
    line_number: int,
    column: Optional[int] = None,
    context_lines: int = 3
) -> SourceContext:
    """
    Extract source code context around an error location.
    
    Parameters
    ----------
    code : str
        Full source code.
    line_number : int
        Line number of the error (1-indexed).
    column : Optional[int]
        Column number of the error.
    context_lines : int
        Number of context lines to extract.
    
    Returns
    -------
    SourceContext
        Extracted context information.
    """
    lines = code.splitlines()
    
    if line_number < 1 or line_number > len(lines):
        return SourceContext(line_number=line_number, column=column)
    
    line_content = lines[line_number - 1]
    context_before = lines[max(0, line_number - context_lines - 1):line_number - 1]
    context_after = lines[line_number:min(len(lines), line_number + context_lines)]
    
    return SourceContext(
        line_number=line_number,
        column=column,
        line_content=line_content,
        context_before=context_before,
        context_after=context_after,
    )


# =============================================================================
# Base Exception
# =============================================================================

class CFastError(Exception):
    """
    Base exception class for all cfast-specific errors.
    
    All custom exceptions in cfast inherit from this class, allowing users
    to catch any cfast error with a single except clause.
    
    Attributes
    ----------
    severity : ErrorSeverity
        Severity level of the error.
    timestamp : float
        Unix timestamp when the error occurred.
    error_code : Optional[str]
        Machine-readable error code.
    details : Dict[str, Any]
        Additional error details.
    
    Parameters
    ----------
    message : str
        Human-readable error description.
    severity : ErrorSeverity, optional
        Error severity level (default: ERROR).
    error_code : str, optional
        Machine-readable error code.
    **details : Any
        Additional keyword arguments stored as error details.
    
    Examples
    --------
    >>> try:
    ...     # Some cfast operation
    ...     pass
    ... except CFastError as e:
    ...     print(f"[{e.severity.name}] {e}")
    ...     print(f"Error code: {e.error_code}")
    ...     print(f"Details: {e.details}")
    """
    
    def __init__(
        self,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        error_code: Optional[str] = None,
        **details: Any
    ):
        import time
        
        super().__init__(message)
        self.severity = severity
        self.timestamp = time.time()
        self.error_code = error_code
        self.details = details
    
    def __str__(self) -> str:
        """Return formatted error message."""
        base = super().__str__()
        if self.error_code:
            base = f"[{self.error_code}] {base}"
        return base
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert exception to dictionary for serialization.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of the error.
        """
        return {
            'type': self.__class__.__name__,
            'message': super().__str__(),
            'severity': self.severity.name,
            'error_code': self.error_code,
            'timestamp': self.timestamp,
            'details': self.details,
        }


# =============================================================================
# Compilation Exceptions
# =============================================================================

class CompilationError(CFastError):
    """
    Raised when C code compilation fails.
    
    This exception indicates that the underlying C compiler (GCC, Clang, or
    MSVC) encountered an error while compiling the provided source code.
    The error message includes the compiler's stderr output and, when
    possible, source code context.
    
    Attributes
    ----------
    compiler_name : Optional[str]
        Name of the compiler that was used (e.g., 'gcc', 'clang', 'msvc').
    compiler_version : Optional[str]
        Version of the compiler.
    compiler_output : Optional[str]
        Raw output from the compiler (stderr).
    compiler_command : Optional[List[str]]
        The full compiler command that was executed.
    source_code : Optional[str]
        The C source code that failed to compile.
    source_context : Optional[SourceContext]
        Extracted source context around the error.
    exit_code : Optional[int]
        Exit code returned by the compiler.
    error_line : Optional[int]
        Line number where the error occurred (if parsable).
    
    Parameters
    ----------
    message : str
        Human-readable error description.
    compiler_name : str, optional
        Name of the compiler used.
    compiler_version : str, optional
        Version of the compiler.
    compiler_output : str, optional
        Raw compiler stderr output.
    compiler_command : List[str], optional
        The executed compiler command.
    source_code : str, optional
        The source code that caused the error.
    exit_code : int, optional
        Compiler exit code.
    error_line : int, optional
        Parsed error line number.
    error_column : int, optional
        Parsed error column number.
    **details : Any
        Additional error details.
    
    Examples
    --------
    >>> try:
    ...     cfast.load_c("int main() { return 0 }")  # Missing semicolon
    ... except CompilationError as e:
    ...     print(f"Compiler: {e.compiler_name}")
    ...     print(f"Exit code: {e.exit_code}")
    ...     if e.source_context:
    ...         print(e.source_context.format())
    ...     print(f"Stderr:\\n{e.compiler_output}")
    """
    
    def __init__(
        self,
        message: str,
        compiler_name: Optional[str] = None,
        compiler_version: Optional[str] = None,
        compiler_output: Optional[str] = None,
        compiler_command: Optional[List[str]] = None,
        source_code: Optional[str] = None,
        exit_code: Optional[int] = None,
        error_line: Optional[int] = None,
        error_column: Optional[int] = None,
        **details: Any
    ):
        super().__init__(
            message,
            severity=ErrorSeverity.ERROR,
            error_code="CFAST_COMPILE_001",
            **details
        )
        self.compiler_name = compiler_name
        self.compiler_version = compiler_version
        self.compiler_output = compiler_output
        self.compiler_command = compiler_command
        self.source_code = source_code
        self.exit_code = exit_code
        self.error_line = error_line
        
        # Extract source context if possible
        self.source_context = None
        if source_code and error_line:
            self.source_context = extract_source_context(
                source_code, error_line, error_column
            )
    
    def __str__(self) -> str:
        """Return formatted error message with context."""
        parts = [super().__str__()]
        
        if self.compiler_name:
            parts.append(f"Compiler: {self.compiler_name}")
            if self.compiler_version:
                parts[-1] += f" {self.compiler_version}"
        
        if self.exit_code is not None:
            parts.append(f"Exit code: {self.exit_code}")
        
        if self.source_context:
            parts.append("\nSource context:")
            parts.append(self.source_context.format())
        
        if self.compiler_output:
            parts.append("\nCompiler output:")
            parts.append(textwrap.indent(self.compiler_output.strip(), "  "))
        
        return "\n".join(parts)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with compilation-specific fields."""
        data = super().to_dict()
        data.update({
            'compiler_name': self.compiler_name,
            'compiler_version': self.compiler_version,
            'compiler_output': self.compiler_output,
            'compiler_command': self.compiler_command,
            'exit_code': self.exit_code,
            'error_line': self.error_line,
        })
        return data


class CompilerNotFoundError(CFastError):
    """
    Raised when no suitable C compiler can be found on the system.
    
    This exception indicates that cfast could not locate a working C compiler
    (GCC, Clang, or MSVC) in the system PATH. It provides platform-specific
    guidance on how to install or configure a compiler.
    
    Attributes
    ----------
    searched_paths : List[str]
        Paths that were searched for compilers.
    searched_executables : List[str]
        Executable names that were searched.
    platform_name : str
        Current platform identifier.
    platform_hint : str
        Platform-specific installation guidance.
    supported_compilers : List[str]
        List of supported compiler names.
    
    Parameters
    ----------
    message : str, optional
        Custom error message.
    searched_paths : List[str], optional
        Paths that were searched.
    searched_executables : List[str], optional
        Executables that were checked.
    **details : Any
        Additional error details.
    
    Examples
    --------
    >>> try:
    ...     compiler = detect_compiler()
    ... except CompilerNotFoundError as e:
    ...     print(e.platform_hint)
    ...     print(f"Searched: {e.searched_executables}")
    ...     print(f"Supported: {e.supported_compilers}")
    """
    
    # Platform-specific installation hints
    _PLATFORM_HINTS = {
        'linux': (
            "Install GCC with your package manager:\n"
            "  Ubuntu/Debian: sudo apt install build-essential\n"
            "  Fedora/RHEL: sudo dnf install gcc gcc-c++\n"
            "  Arch: sudo pacman -S gcc\n"
            "Or install Clang: sudo apt install clang"
        ),
        'darwin': (
            "Install Xcode Command Line Tools:\n"
            "  xcode-select --install\n"
            "Or install via Homebrew:\n"
            "  brew install gcc\n"
            "  brew install llvm"
        ),
        'win32': (
            "Install one of the following:\n"
            "  1. MinGW-w64: https://www.mingw-w64.org/\n"
            "  2. Microsoft Visual C++ Build Tools:\n"
            "     https://visualstudio.microsoft.com/downloads/\n"
            "  3. Clang: https://llvm.org/builds/\n"
            "Ensure the compiler is added to your PATH."
        ),
    }
    
    # Supported compilers by platform
    _SUPPORTED_COMPILERS = {
        'linux': ['gcc', 'clang'],
        'darwin': ['clang', 'gcc'],
        'win32': ['gcc', 'clang', 'msvc'],
    }
    
    def __init__(
        self,
        message: Optional[str] = None,
        searched_paths: Optional[List[str]] = None,
        searched_executables: Optional[List[str]] = None,
        **details: Any
    ):
        import sys
        
        self.platform_name = sys.platform
        self.searched_paths = searched_paths or self._get_path_directories()
        self.searched_executables = searched_executables or ['gcc', 'clang', 'cl']
        self.supported_compilers = self._SUPPORTED_COMPILERS.get(
            self._get_platform_key(), ['gcc', 'clang', 'msvc']
        )
        self.platform_hint = self._PLATFORM_HINTS.get(
            self._get_platform_key(),
            "Install a C compiler (GCC, Clang, or MSVC) and ensure it's in PATH."
        )
        
        if message is None:
            message = (
                f"No working C compiler found on {self.platform_name}.\n"
                f"Searched executables: {', '.join(self.searched_executables)}\n"
                f"Supported compilers: {', '.join(self.supported_compilers)}"
            )
        
        super().__init__(
            message,
            severity=ErrorSeverity.CRITICAL,
            error_code="CFAST_COMPILE_002",
            **details
        )
    
    def _get_platform_key(self) -> str:
        """Get normalized platform key."""
        if self.platform_name.startswith('linux'):
            return 'linux'
        elif self.platform_name == 'darwin':
            return 'darwin'
        elif self.platform_name.startswith('win'):
            return 'win32'
        return self.platform_name
    
    @staticmethod
    def _get_path_directories() -> List[str]:
        """Get directories in PATH environment variable."""
        path = os.environ.get('PATH', '')
        return [p for p in path.split(os.pathsep) if p]
    
    def __str__(self) -> str:
        """Return formatted error with installation hint."""
        parts = [super().__str__()]
        parts.append(f"\nInstallation Hint:\n{textwrap.indent(self.platform_hint, '  ')}")
        return "\n".join(parts)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with compiler-specific fields."""
        data = super().to_dict()
        data.update({
            'platform_name': self.platform_name,
            'searched_paths': self.searched_paths,
            'searched_executables': self.searched_executables,
            'supported_compilers': self.supported_compilers,
        })
        return data


class CompilationTimeoutError(CompilationError):
    """
    Raised when compilation exceeds the maximum allowed time.
    
    This exception indicates that the compilation process took longer than
    the configured timeout and was forcefully terminated.
    
    Attributes
    ----------
    timeout_seconds : float
        The timeout duration that was exceeded.
    elapsed_seconds : Optional[float]
        How long the compilation ran before timeout.
    
    Parameters
    ----------
    timeout_seconds : float
        The timeout value in seconds.
    elapsed_seconds : float, optional
        Elapsed time before timeout.
    message : str, optional
        Custom error message.
    **details : Any
        Additional error details.
    
    Examples
    --------
    >>> try:
    ...     compiler = GccCompiler(timeout=30)
    ...     compile_c_code(large_code, compiler=compiler)
    ... except CompilationTimeoutError as e:
    ...     print(f"Timeout after {e.timeout_seconds}s")
    ...     if e.elapsed_seconds:
    ...         print(f"Elapsed: {e.elapsed_seconds}s")
    """
    
    def __init__(
        self,
        timeout_seconds: float,
        elapsed_seconds: Optional[float] = None,
        message: Optional[str] = None,
        **details: Any
    ):
        self.timeout_seconds = timeout_seconds
        self.elapsed_seconds = elapsed_seconds
        
        if message is None:
            message = f"Compilation timed out after {timeout_seconds} seconds"
            if elapsed_seconds:
                message += f" (elapsed: {elapsed_seconds:.2f}s)"
        
        super().__init__(
            message,
            error_code="CFAST_COMPILE_003",
            **details
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with timeout fields."""
        data = super().to_dict()
        data.update({
            'timeout_seconds': self.timeout_seconds,
            'elapsed_seconds': self.elapsed_seconds,
        })
        return data


class LinkerError(CompilationError):
    """
    Raised when linking fails during shared library creation.
    
    This exception specifically indicates a linker error as opposed to a
    compiler syntax or semantic error. It typically occurs when required
    libraries are missing, symbols are undefined, or there are incompatible
    object files.
    
    Attributes
    ----------
    missing_symbols : List[str]
        List of undefined symbols reported by the linker.
    library_paths : List[str]
        Library search paths that were used.
    linked_libraries : List[str]
        Libraries that were linked.
    linker_script : Optional[str]
        Linker script used, if any.
    
    Parameters
    ----------
    message : str
        Error description.
    missing_symbols : List[str], optional
        Undefined symbols.
    library_paths : List[str], optional
        Search paths used.
    linked_libraries : List[str], optional
        Libraries that were linked.
    **details : Any
        Additional error details.
    
    Examples
    --------
    >>> try:
    ...     cfast.load_c(code, libraries=["m", "pthread"])
    ... except LinkerError as e:
    ...     print(f"Missing symbols: {e.missing_symbols}")
    ...     print(f"Library paths: {e.library_paths}")
    """
    
    def __init__(
        self,
        message: str,
        missing_symbols: Optional[List[str]] = None,
        library_paths: Optional[List[str]] = None,
        linked_libraries: Optional[List[str]] = None,
        linker_script: Optional[str] = None,
        **details: Any
    ):
        self.missing_symbols = missing_symbols or []
        self.library_paths = library_paths or []
        self.linked_libraries = linked_libraries or []
        self.linker_script = linker_script
        
        super().__init__(
            message,
            error_code="CFAST_COMPILE_004",
            **details
        )
    
    def __str__(self) -> str:
        """Return formatted linker error with context."""
        parts = [super().__str__()]
        
        if self.missing_symbols:
            parts.append(f"\nMissing symbols ({len(self.missing_symbols)}):")
            for sym in self.missing_symbols[:10]:
                parts.append(f"  - {sym}")
            if len(self.missing_symbols) > 10:
                parts.append(f"  ... and {len(self.missing_symbols) - 10} more")
        
        if self.linked_libraries:
            parts.append(f"\nLinked libraries: {', '.join(self.linked_libraries)}")
        
        if self.library_paths:
            parts.append(f"\nLibrary search paths:")
            for path in self.library_paths[:5]:
                parts.append(f"  - {path}")
            if len(self.library_paths) > 5:
                parts.append(f"  ... and {len(self.library_paths) - 5} more")
        
        return "\n".join(parts)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with linker fields."""
        data = super().to_dict()
        data.update({
            'missing_symbols': self.missing_symbols,
            'library_paths': self.library_paths,
            'linked_libraries': self.linked_libraries,
            'linker_script': self.linker_script,
        })
        return data


class PreprocessorError(CompilationError):
    """
    Raised when the C preprocessor fails.
    
    This exception indicates an error during the preprocessing phase,
    such as missing include files, invalid macro definitions, or
    preprocessor directive errors.
    
    Attributes
    ----------
    missing_includes : List[str]
        Include files that could not be found.
    include_paths : List[str]
        Paths searched for includes.
    macro_errors : List[str]
        Errors related to macro definitions.
    
    Parameters
    ----------
    message : str
        Error description.
    missing_includes : List[str], optional
        Missing include files.
    include_paths : List[str], optional
        Searched include paths.
    macro_errors : List[str], optional
        Macro-related errors.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        message: str,
        missing_includes: Optional[List[str]] = None,
        include_paths: Optional[List[str]] = None,
        macro_errors: Optional[List[str]] = None,
        **details: Any
    ):
        self.missing_includes = missing_includes or []
        self.include_paths = include_paths or []
        self.macro_errors = macro_errors or []
        
        super().__init__(
            message,
            error_code="CFAST_COMPILE_005",
            **details
        )
    
    def __str__(self) -> str:
        """Return formatted preprocessor error."""
        parts = [super().__str__()]
        
        if self.missing_includes:
            parts.append(f"\nMissing includes: {', '.join(self.missing_includes)}")
            parts.append("Try adding include paths via the 'includes' parameter.")
        
        if self.macro_errors:
            parts.append(f"\nMacro errors:")
            for err in self.macro_errors:
                parts.append(f"  - {err}")
        
        return "\n".join(parts)


class AssemblyError(CompilationError):
    """
    Raised when the assembler fails.
    
    This exception indicates an error during the assembly phase,
    typically due to inline assembly syntax errors or unsupported
    instructions.
    
    Attributes
    ----------
    assembly_line : Optional[int]
        Line number where assembly error occurred.
    instruction : Optional[str]
        The problematic assembly instruction.
    
    Parameters
    ----------
    message : str
        Error description.
    assembly_line : int, optional
        Error line number.
    instruction : str, optional
        Problematic instruction.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        message: str,
        assembly_line: Optional[int] = None,
        instruction: Optional[str] = None,
        **details: Any
    ):
        self.assembly_line = assembly_line
        self.instruction = instruction
        
        super().__init__(
            message,
            error_code="CFAST_COMPILE_006",
            **details
        )


# =============================================================================
# Parsing and Signature Detection Exceptions
# =============================================================================

class SignatureDetectionError(CFastError):
    """
    Base exception for signature detection failures.
    
    Raised when automatic function signature extraction fails due to
    parsing errors, missing dependencies, or unsupported C features.
    
    Attributes
    ----------
    parse_error : Optional[Exception]
        The underlying parsing exception.
    suggestion : str
        Recommended action to resolve the error.
    
    Parameters
    ----------
    message : str
        Error description.
    parse_error : Exception, optional
        Original parsing error.
    suggestion : str, optional
        Suggested fix.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        message: str,
        parse_error: Optional[Exception] = None,
        suggestion: Optional[str] = None,
        **details: Any
    ):
        self.parse_error = parse_error
        self.suggestion = suggestion or (
            "Try adding include paths via extra_includes parameter, "
            "or disable auto_signatures and set argtypes/restype manually."
        )
        
        full_message = f"{message}\n\nSuggestion: {self.suggestion}"
        
        super().__init__(
            full_message,
            severity=ErrorSeverity.WARNING,
            error_code="CFAST_PARSE_001",
            **details
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with parse fields."""
        data = super().to_dict()
        data.update({
            'parse_error': str(self.parse_error) if self.parse_error else None,
            'suggestion': self.suggestion,
        })
        return data


class PycparserNotAvailableError(SignatureDetectionError):
    """
    Raised when pycparser is required but not installed.
    
    This exception indicates that automatic signature detection was requested
    but the pycparser library is not available in the Python environment.
    
    Attributes
    ----------
    install_command : str
        Command to install pycparser.
    
    Parameters
    ----------
    message : str, optional
        Custom error message.
    **details : Any
        Additional error details.
    
    Examples
    --------
    >>> try:
    ...     cfunc(code, auto_signatures=True)
    ... except PycparserNotAvailableError as e:
    ...     print(e.install_command)
    ...     # Optionally install automatically
    ...     import subprocess
    ...     subprocess.check_call(e.install_command.split())
    """
    
    def __init__(
        self,
        message: Optional[str] = None,
        **details: Any
    ):
        self.install_command = "pip install pycparser"
        
        if message is None:
            message = (
                "pycparser is required for automatic signature detection.\n"
                f"Install with: {self.install_command}"
            )
        
        suggestion = f"Run: {self.install_command}"
        
        super().__init__(
            message,
            suggestion=suggestion,
            error_code="CFAST_PARSE_002",
            **details
        )


class ParseSyntaxError(SignatureDetectionError):
    """
    Raised when C code contains syntax errors during parsing.
    
    This exception indicates that pycparser encountered a syntax error
    while parsing the C source code.
    
    Attributes
    ----------
    line_number : Optional[int]
        Line number where syntax error occurred.
    column : Optional[int]
        Column number where error occurred.
    near_text : Optional[str]
        Text near the error location.
    expected_tokens : List[str]
        Tokens that were expected.
    
    Parameters
    ----------
    message : str
        Error description.
    line_number : int, optional
        Error line number.
    column : int, optional
        Error column number.
    near_text : str, optional
        Text near error.
    expected_tokens : List[str], optional
        Expected tokens.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        message: str,
        line_number: Optional[int] = None,
        column: Optional[int] = None,
        near_text: Optional[str] = None,
        expected_tokens: Optional[List[str]] = None,
        **details: Any
    ):
        self.line_number = line_number
        self.column = column
        self.near_text = near_text
        self.expected_tokens = expected_tokens or []
        
        super().__init__(
            message,
            error_code="CFAST_PARSE_003",
            **details
        )
    
    def __str__(self) -> str:
        """Return formatted syntax error."""
        parts = [super().__str__()]
        
        if self.line_number:
            location = f"Line {self.line_number}"
            if self.column:
                location += f", Column {self.column}"
            parts.append(f"\nLocation: {location}")
        
        if self.near_text:
            parts.append(f"Near: {self.near_text}")
        
        if self.expected_tokens:
            parts.append(f"Expected: {', '.join(self.expected_tokens)}")
        
        return "\n".join(parts)


class StructDefinitionError(SignatureDetectionError):
    """
    Raised when struct definition extraction fails.
    
    This exception indicates that while parsing struct definitions from C code,
    an error occurred (e.g., recursive struct without proper forward declaration,
    unsupported field types, or anonymous struct issues).
    
    Attributes
    ----------
    struct_name : str
        Name of the struct that caused the error.
    field_name : Optional[str]
        Specific field that triggered the error.
    error_type : str
        Type of struct error.
    
    Parameters
    ----------
    struct_name : str
        The problematic struct name.
    message : str
        Error description.
    field_name : str, optional
        Problematic field name.
    error_type : str, optional
        Error classification.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        struct_name: str,
        message: str,
        field_name: Optional[str] = None,
        error_type: str = "definition",
        **details: Any
    ):
        self.struct_name = struct_name
        self.field_name = field_name
        self.error_type = error_type
        
        full_message = f"Error in struct '{struct_name}'"
        if field_name:
            full_message += f", field '{field_name}'"
        full_message += f": {message}"
        
        suggestion = (
            "Check struct definition syntax. For self-referential structs, "
            "use forward declaration: 'struct Name;' before definition."
        )
        
        super().__init__(
            full_message,
            suggestion=suggestion,
            error_code="CFAST_PARSE_004",
            **details
        )


class TypeConversionError(SignatureDetectionError):
    """
    Raised when a C type cannot be converted to a ctypes type.
    
    This exception indicates that the parser encountered a C type that cannot
    be mapped to a corresponding ctypes type, such as complex numbers,
    vector types, or platform-specific extensions.
    
    Attributes
    ----------
    c_type_str : str
        String representation of the C type.
    context : Optional[str]
        Context where the type appeared (e.g., 'return type', 'parameter 2').
    fallback_type : Optional[str]
        Fallback type that will be used.
    
    Parameters
    ----------
    c_type_str : str
        The type that could not be converted.
    message : str, optional
        Custom error message.
    context : str, optional
        Context of the type.
    fallback_type : str, optional
        Fallback type to use.
    **details : Any
        Additional error details.
    
    Examples
    --------
    >>> try:
    ...     parse_c_code("__m128 vector_add(__m128 a, __m128 b);")
    ... except TypeConversionError as e:
    ...     print(f"Cannot convert: {e.c_type_str}")
    ...     print(f"Fallback: {e.fallback_type}")
    """
    
    def __init__(
        self,
        c_type_str: str,
        message: Optional[str] = None,
        context: Optional[str] = None,
        fallback_type: str = "c_void_p",
        **details: Any
    ):
        self.c_type_str = c_type_str
        self.context = context
        self.fallback_type = fallback_type
        
        if message is None:
            message = f"Cannot convert C type '{c_type_str}' to ctypes type"
            if context:
                message += f" in {context}"
            message += f". Using fallback: {fallback_type}"
        
        suggestion = (
            f"Type '{c_type_str}' is not directly supported. "
            f"Consider using {fallback_type} and manual conversion."
        )
        
        super().__init__(
            message,
            suggestion=suggestion,
            error_code="CFAST_PARSE_005",
            **details
        )


class IncludeResolutionError(SignatureDetectionError):
    """
    Raised when include files cannot be resolved during parsing.
    
    This exception indicates that pycparser could not find one or more
    header files referenced by #include directives.
    
    Attributes
    ----------
    missing_headers : List[str]
        Headers that could not be found.
    include_paths : List[str]
        Paths that were searched.
    
    Parameters
    ----------
    missing_headers : List[str]
        Headers that could not be found.
    include_paths : List[str], optional
        Searched include paths.
    message : str, optional
        Custom error message.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        missing_headers: List[str],
        include_paths: Optional[List[str]] = None,
        message: Optional[str] = None,
        **details: Any
    ):
        self.missing_headers = missing_headers
        self.include_paths = include_paths or []
        
        if message is None:
            message = f"Could not resolve include(s): {', '.join(missing_headers)}"
        
        suggestion = (
            "Add include paths via extra_includes parameter. "
            "System headers may require additional configuration."
        )
        
        super().__init__(
            message,
            suggestion=suggestion,
            error_code="CFAST_PARSE_006",
            **details
        )
    
    def __str__(self) -> str:
        """Return formatted include error."""
        parts = [super().__str__()]
        
        if self.include_paths:
            parts.append("\nSearched include paths:")
            for path in self.include_paths[:10]:
                parts.append(f"  - {path}")
            if len(self.include_paths) > 10:
                parts.append(f"  ... and {len(self.include_paths) - 10} more")
        
        return "\n".join(parts)


# =============================================================================
# Cache Exceptions
# =============================================================================

class CacheError(CFastError):
    """
    Base exception for cache-related errors.
    
    Raised when operations on the compilation cache fail, such as
    read/write errors, corruption, or lock acquisition failures.
    
    Attributes
    ----------
    cache_key : Optional[str]
        The cache key involved in the error.
    cache_dir : Optional[str]
        The cache directory path.
    
    Parameters
    ----------
    message : str
        Error description.
    cache_key : str, optional
        Cache key involved.
    cache_dir : Union[str, Path], optional
        Cache directory path.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        message: str,
        cache_key: Optional[str] = None,
        cache_dir: Optional[Union[str, Path]] = None,
        **details: Any
    ):
        self.cache_key = cache_key
        self.cache_dir = str(cache_dir) if cache_dir else None
        
        super().__init__(
            message,
            severity=ErrorSeverity.WARNING,
            error_code="CFAST_CACHE_001",
            cache_key=cache_key,
            cache_dir=self.cache_dir,
            **details
        )
    
    def __str__(self) -> str:
        """Return formatted cache error."""
        parts = [super().__str__()]
        if self.cache_key:
            parts.append(f"Cache key: {self.cache_key[:16]}...")
        if self.cache_dir:
            parts.append(f"Cache dir: {self.cache_dir}")
        return "\n".join(parts)


class CacheIntegrityError(CacheError):
    """
    Raised when cache integrity validation fails.
    
    This exception indicates that cached data fails integrity checks,
    such as hash mismatch, incomplete files, or metadata corruption.
    
    Attributes
    ----------
    expected_hash : Optional[str]
        Expected hash value.
    actual_hash : Optional[str]
        Actual computed hash.
    corrupted_file : Optional[str]
        Path to corrupted file.
    
    Parameters
    ----------
    message : str
        Error description.
    expected_hash : str, optional
        Expected hash.
    actual_hash : str, optional
        Actual hash.
    corrupted_file : str, optional
        Corrupted file path.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        message: str,
        expected_hash: Optional[str] = None,
        actual_hash: Optional[str] = None,
        corrupted_file: Optional[str] = None,
        **details: Any
    ):
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        self.corrupted_file = corrupted_file
        
        super().__init__(
            message,
            error_code="CFAST_CACHE_002",
            **details
        )


class CacheCorruptionError(CacheError):
    """
    Raised when cached data appears to be corrupted.
    
    This exception indicates that a cached library exists but cannot be
    loaded, likely due to file corruption, incomplete writes, or
    filesystem errors.
    
    Attributes
    ----------
    cache_path : str
        Path to the corrupted cache file.
    
    Parameters
    ----------
    cache_path : Union[str, Path]
        Path to corrupted cache file.
    message : str, optional
        Custom error message.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        cache_path: Union[str, Path],
        message: Optional[str] = None,
        **details: Any
    ):
        self.cache_path = str(cache_path)
        
        if message is None:
            message = f"Cached library appears corrupted: {self.cache_path}"
        
        suggestion = (
            "The cache entry will be automatically cleaned. "
            "Run cfast.clear_cache() to remove all corrupted entries."
        )
        
        super().__init__(
            message,
            error_code="CFAST_CACHE_003",
            **details
        )
        self.suggestion = suggestion


class CacheLockError(CacheError):
    """
    Raised when cache locking operations fail.
    
    This exception indicates a failure in acquiring or releasing a file lock
    on a cache directory, which may prevent safe concurrent compilation.
    
    Attributes
    ----------
    lock_path : str
        Path to the lock file.
    blocking : bool
        Whether the lock attempt was blocking.
    timeout : Optional[float]
        Lock acquisition timeout.
    held_by_pid : Optional[int]
        PID of the process holding the lock.
    
    Parameters
    ----------
    lock_path : Union[str, Path]
        Path to lock file.
    message : str
        Error description.
    blocking : bool
        Whether attempt was blocking.
    timeout : float, optional
        Timeout value.
    held_by_pid : int, optional
        PID holding the lock.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        lock_path: Union[str, Path],
        message: str,
        blocking: bool = True,
        timeout: Optional[float] = None,
        held_by_pid: Optional[int] = None,
        **details: Any
    ):
        self.lock_path = str(lock_path)
        self.blocking = blocking
        self.timeout = timeout
        self.held_by_pid = held_by_pid
        
        full_message = f"Lock error on {self.lock_path}: {message}"
        if held_by_pid:
            full_message += f" (held by PID {held_by_pid})"
        if timeout:
            full_message += f" (timeout: {timeout}s)"
        
        super().__init__(
            full_message,
            error_code="CFAST_CACHE_004",
            **details
        )


class StaleLockError(CacheLockError):
    """
    Raised when a stale lock is detected and cannot be cleaned up.
    
    This exception indicates that a lock file exists from a crashed or
    terminated process but could not be automatically removed.
    
    Attributes
    ----------
    stale_pid : Optional[int]
        PID of the dead process.
    lock_age_seconds : Optional[float]
        Age of the lock in seconds.
    
    Parameters
    ----------
    lock_path : Union[str, Path]
        Path to stale lock file.
    stale_pid : int, optional
        PID of dead process.
    lock_age_seconds : float, optional
        Lock age in seconds.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        lock_path: Union[str, Path],
        stale_pid: Optional[int] = None,
        lock_age_seconds: Optional[float] = None,
        **details: Any
    ):
        self.stale_pid = stale_pid
        self.lock_age_seconds = lock_age_seconds
        
        message = f"Stale lock detected at {lock_path}"
        if stale_pid:
            message += f" (PID {stale_pid} no longer exists)"
        if lock_age_seconds:
            message += f" (age: {lock_age_seconds:.1f}s)"
        
        suggestion = (
            "Remove the lock file manually, or run cfast.cleanup_stale_locks()."
        )
        
        super().__init__(
            lock_path,
            message,
            blocking=False,
            held_by_pid=stale_pid,
            error_code="CFAST_CACHE_005",
            **details
        )
        self.suggestion = suggestion


class CacheCapacityError(CacheError):
    """
    Raised when cache capacity is exceeded and cannot be reduced.
    
    This exception indicates that the cache has reached its maximum size
    and automatic eviction could not free enough space.
    
    Attributes
    ----------
    current_size : int
        Current cache size in bytes.
    max_size : int
        Maximum configured cache size.
    needed_space : int
        Additional space needed.
    
    Parameters
    ----------
    current_size : int
        Current cache size.
    max_size : int
        Maximum cache size.
    needed_space : int
        Space needed.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        current_size: int,
        max_size: int,
        needed_space: int,
        **details: Any
    ):
        self.current_size = current_size
        self.max_size = max_size
        self.needed_space = needed_space
        
        message = (
            f"Cache capacity exceeded: {_format_bytes(current_size)} / {_format_bytes(max_size)}. "
            f"Need {_format_bytes(needed_space)} more."
        )
        
        suggestion = (
            "Increase cache size with max_cache_size parameter, "
            "or clear cache with cfast.clear_cache()."
        )
        
        super().__init__(
            message,
            error_code="CFAST_CACHE_006",
            **details
        )
        self.suggestion = suggestion


class CacheIOError(CacheError):
    """
    Raised when filesystem I/O operations on cache fail.
    
    This exception indicates a filesystem error such as permission denied,
    disk full, or I/O error during cache operations.
    
    Attributes
    ----------
    operation : str
        The I/O operation that failed (read, write, delete, etc.).
    path : str
        Path involved in the operation.
    os_error : Optional[OSError]
        Original OS error.
    
    Parameters
    ----------
    operation : str
        Failed operation.
    path : Union[str, Path]
        Path involved.
    message : str
        Error description.
    os_error : OSError, optional
        Original OS error.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        operation: str,
        path: Union[str, Path],
        message: str,
        os_error: Optional[OSError] = None,
        **details: Any
    ):
        self.operation = operation
        self.path = str(path)
        self.os_error = os_error
        
        full_message = f"Cache {operation} failed on {self.path}: {message}"
        
        super().__init__(
            full_message,
            error_code="CFAST_CACHE_007",
            **details
        )


# =============================================================================
# Platform Exceptions
# =============================================================================

class PlatformError(CFastError):
    """
    Base exception for platform-specific errors.
    
    Raised for errors related to platform detection, system configuration,
    or unsupported environments.
    
    Attributes
    ----------
    platform_name : str
        Current platform identifier.
    platform_info : Dict[str, Any]
        Diagnostic information about the platform.
    
    Parameters
    ----------
    message : str
        Error description.
    platform_info : Dict, optional
        Platform diagnostic data.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        message: str,
        platform_info: Optional[Dict[str, Any]] = None,
        **details: Any
    ):
        import sys
        
        self.platform_name = sys.platform
        self.platform_info = platform_info or {
            "system": sys.platform,
            "python_version": sys.version,
            "python_implementation": sys.implementation.name,
            "machine": sys.implementation._machine if hasattr(sys.implementation, '_machine') else None,
        }
        
        super().__init__(
            message,
            severity=ErrorSeverity.ERROR,
            error_code="CFAST_PLATFORM_001",
            **details
        )


class UnsupportedPlatformError(PlatformError):
    """
    Raised when the current platform is not supported.
    
    This exception indicates that cfast cannot operate on the current
    operating system or architecture.
    
    Attributes
    ----------
    supported_platforms : List[str]
        List of supported platform identifiers.
    reason : str
        Why the platform is unsupported.
    
    Parameters
    ----------
    platform_name : str, optional
        Unsupported platform name.
    reason : str, optional
        Why it's unsupported.
    supported_platforms : List[str], optional
        Supported platforms.
    **details : Any
        Additional error details.
    """
    
    _SUPPORTED_PLATFORMS = ['linux', 'darwin', 'win32']
    
    def __init__(
        self,
        platform_name: Optional[str] = None,
        reason: Optional[str] = None,
        supported_platforms: Optional[List[str]] = None,
        **details: Any
    ):
        import sys
        
        self.platform_name = platform_name or sys.platform
        self.reason = reason or "Platform not supported by cfast"
        self.supported_platforms = supported_platforms or self._SUPPORTED_PLATFORMS
        
        message = (
            f"Unsupported platform '{self.platform_name}': {self.reason}\n"
            f"Supported platforms: {', '.join(self.supported_platforms)}"
        )
        
        super().__init__(
            message,
            error_code="CFAST_PLATFORM_002",
            **details
        )


class LibraryLoadError(PlatformError):
    """
    Raised when a compiled shared library cannot be loaded.
    
    This exception indicates that although compilation succeeded, the
    resulting shared library could not be loaded via ctypes, typically
    due to missing dependencies, permission issues, or architecture mismatch.
    
    Attributes
    ----------
    library_path : str
        Path to the library that failed to load.
    dlerror : Optional[str]
        Platform-specific dynamic linker error message.
    missing_dependencies : List[str]
        Missing library dependencies.
    
    Parameters
    ----------
    library_path : Union[str, Path]
        Path to library.
    message : str
        Error description.
    dlerror : str, optional
        Dynamic linker error.
    missing_dependencies : List[str], optional
        Missing dependencies.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        library_path: Union[str, Path],
        message: str,
        dlerror: Optional[str] = None,
        missing_dependencies: Optional[List[str]] = None,
        **details: Any
    ):
        self.library_path = str(library_path)
        self.dlerror = dlerror
        self.missing_dependencies = missing_dependencies or []
        
        full_message = f"Failed to load library '{self.library_path}': {message}"
        
        super().__init__(
            full_message,
            error_code="CFAST_PLATFORM_003",
            **details
        )
    
    def __str__(self) -> str:
        """Return formatted library load error."""
        parts = [super().__str__()]
        
        if self.dlerror:
            parts.append(f"\nLinker error: {self.dlerror}")
        
        if self.missing_dependencies:
            parts.append(f"\nMissing dependencies:")
            for dep in self.missing_dependencies:
                parts.append(f"  - {dep}")
        
        return "\n".join(parts)


class ArchitectureMismatchError(PlatformError):
    """
    Raised when architecture mismatch prevents library loading.
    
    This exception indicates that the compiled library's architecture
    does not match the current Python process architecture.
    
    Attributes
    ----------
    library_arch : str
        Architecture of the library.
    python_arch : str
        Architecture of the Python process.
    
    Parameters
    ----------
    library_arch : str
        Library architecture.
    python_arch : str
        Python architecture.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        library_arch: str,
        python_arch: str,
        **details: Any
    ):
        self.library_arch = library_arch
        self.python_arch = python_arch
        
        message = (
            f"Architecture mismatch: library is {library_arch}, "
            f"but Python is {python_arch}"
        )
        
        suggestion = (
            f"Recompile the library for {python_arch} using a compatible compiler."
        )
        
        super().__init__(
            message,
            error_code="CFAST_PLATFORM_004",
            **details
        )
        self.suggestion = suggestion


class PermissionError(PlatformError):
    """
    Raised when permission issues prevent operations.
    
    This exception indicates insufficient permissions for file operations,
    such as writing to cache directory or creating temporary files.
    
    Attributes
    ----------
    path : str
        Path with permission issues.
    required_permission : str
        Permission that was required (read, write, execute).
    
    Parameters
    ----------
    path : Union[str, Path]
        Path with permission issue.
    required_permission : str
        Required permission.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        path: Union[str, Path],
        required_permission: str,
        **details: Any
    ):
        self.path = str(path)
        self.required_permission = required_permission
        
        message = f"Permission denied: cannot {required_permission} '{self.path}'"
        
        suggestion = (
            f"Check file permissions or change cache directory with "
            f"cfast.set_cache_root()."
        )
        
        super().__init__(
            message,
            error_code="CFAST_PLATFORM_005",
            **details
        )
        self.suggestion = suggestion


# =============================================================================
# Configuration Exceptions
# =============================================================================

class ConfigurationError(CFastError):
    """
    Base exception for configuration and validation errors.
    
    Raised when user provides invalid parameters, incompatible options,
    or malformed input.
    
    Attributes
    ----------
    parameter : Optional[str]
        The problematic parameter name.
    value : Any
        The invalid value that was provided.
    expected : Optional[str]
        Description of expected values.
    
    Parameters
    ----------
    message : str
        Error description.
    parameter : str, optional
        Problematic parameter.
    value : Any, optional
        Invalid value.
    expected : str, optional
        Expected value description.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        message: str,
        parameter: Optional[str] = None,
        value: Any = None,
        expected: Optional[str] = None,
        **details: Any
    ):
        self.parameter = parameter
        self.value = value
        self.expected = expected
        
        full_message = message
        if parameter:
            full_message = f"Invalid value for '{parameter}': {message}"
            if expected:
                full_message += f" (expected: {expected})"
            if value is not None:
                full_message += f", got: {repr(value)}"
        
        super().__init__(
            full_message,
            severity=ErrorSeverity.ERROR,
            error_code="CFAST_CONFIG_001",
            **details
        )


class InvalidSourceCodeError(ConfigurationError):
    """
    Raised when provided C source code is invalid or empty.
    
    This exception indicates that the source code provided for compilation
    is empty, contains only whitespace, or otherwise cannot be processed.
    
    Attributes
    ----------
    source_preview : Optional[str]
        Preview of the problematic source (truncated).
    issue : str
        Description of the issue with the source.
    
    Parameters
    ----------
    message : str, optional
        Custom error message.
    source_preview : str, optional
        Preview of invalid source.
    issue : str, optional
        Issue description.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        message: str = "C source code cannot be empty or whitespace-only",
        source_preview: Optional[str] = None,
        issue: str = "empty",
        **details: Any
    ):
        self.source_preview = source_preview
        self.issue = issue
        
        if source_preview:
            preview = source_preview[:200] + "..." if len(source_preview) > 200 else source_preview
            message += f"\nSource preview: {preview}"
        
        super().__init__(
            message,
            parameter="code",
            error_code="CFAST_CONFIG_002",
            **details
        )


class FunctionNotFoundError(ConfigurationError):
    """
    Raised when a requested function is not found in compiled code.
    
    This exception indicates that the specified function name does not exist
    in the compiled shared library.
    
    Attributes
    ----------
    func_name : str
        The requested function name.
    available_functions : List[str]
        Functions that are actually available.
    similar_names : List[str]
        Functions with similar names (typo suggestion).
    
    Parameters
    ----------
    func_name : str
        Requested function name.
    available_functions : List[str], optional
        Available functions.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        func_name: str,
        available_functions: Optional[List[str]] = None,
        **details: Any
    ):
        self.func_name = func_name
        self.available_functions = available_functions or []
        self.similar_names = self._find_similar_names(func_name, self.available_functions)
        
        message = f"Function '{func_name}' not found in compiled library"
        
        if self.similar_names:
            message += f"\nDid you mean: {', '.join(self.similar_names)}?"
        elif available_functions:
            message += f"\nAvailable functions: {', '.join(available_functions[:10])}"
            if len(available_functions) > 10:
                message += f" ... and {len(available_functions) - 10} more"
        
        super().__init__(
            message,
            parameter="func_name",
            value=func_name,
            error_code="CFAST_CONFIG_003",
            **details
        )
    
    @staticmethod
    def _find_similar_names(target: str, candidates: List[str], threshold: float = 0.6) -> List[str]:
        """Find similar names using Levenshtein distance."""
        similar = []
        for cand in candidates:
            distance = _levenshtein_distance(target.lower(), cand.lower())
            max_len = max(len(target), len(cand))
            if max_len > 0:
                similarity = 1 - (distance / max_len)
                if similarity >= threshold:
                    similar.append(cand)
        return similar[:5]


class MultipleFunctionsError(ConfigurationError):
    """
    Raised when multiple functions exist but none was specified.
    
    This exception indicates that the source code contains multiple function
    definitions, but the user did not specify which one to extract.
    
    Attributes
    ----------
    functions : List[str]
        The function names that were detected.
    
    Parameters
    ----------
    functions : List[str]
        Detected function names.
    message : str, optional
        Custom error message.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        functions: List[str],
        message: Optional[str] = None,
        **details: Any
    ):
        self.functions = functions
        
        if message is None:
            message = (
                f"Code contains {len(functions)} functions; "
                f"please specify func_name.\n"
                f"Available functions: {', '.join(functions)}"
            )
        
        super().__init__(
            message,
            parameter="func_name",
            error_code="CFAST_CONFIG_004",
            **details
        )


class InvalidCompilerFlagError(ConfigurationError):
    """
    Raised when an invalid compiler flag is provided.
    
    This exception indicates that a user-provided compiler flag is not
    recognized or not supported by the current compiler.
    
    Attributes
    ----------
    flag : str
        The invalid flag.
    compiler_name : str
        Name of the compiler.
    supported_flags : List[str]
        List of supported/common flags.
    
    Parameters
    ----------
    flag : str
        Invalid flag.
    compiler_name : str
        Compiler name.
    supported_flags : List[str], optional
        Supported flags.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        flag: str,
        compiler_name: str,
        supported_flags: Optional[List[str]] = None,
        **details: Any
    ):
        self.flag = flag
        self.compiler_name = compiler_name
        self.supported_flags = supported_flags or self._get_common_flags(compiler_name)
        
        message = f"Invalid or unsupported flag for {compiler_name}: '{flag}'"
        
        super().__init__(
            message,
            parameter="cflags",
            value=flag,
            error_code="CFAST_CONFIG_005",
            **details
        )
    
    @staticmethod
    def _get_common_flags(compiler: str) -> List[str]:
        """Get common flags for a compiler."""
        if compiler == 'msvc':
            return ['/O1', '/O2', '/Ox', '/Od', '/Zi', '/W0', '/W1', '/W2', '/W3', '/W4']
        else:
            return ['-O0', '-O1', '-O2', '-O3', '-Os', '-g', '-Wall', '-Wextra', '-fPIC']


class IncludePathError(ConfigurationError):
    """
    Raised when an include path is invalid or inaccessible.
    
    This exception indicates that a user-provided include directory does
    not exist, is not a directory, or cannot be accessed.
    
    Attributes
    ----------
    path : str
        The problematic include path.
    reason : str
        Reason why the path is invalid.
    
    Parameters
    ----------
    path : Union[str, Path]
        Problematic path.
    reason : str
        Reason for invalidity.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        path: Union[str, Path],
        reason: str,
        **details: Any
    ):
        self.path = str(path)
        self.reason = reason
        
        message = f"Invalid include path '{self.path}': {reason}"
        
        super().__init__(
            message,
            parameter="includes",
            value=str(path),
            error_code="CFAST_CONFIG_006",
            **details
        )


# =============================================================================
# Runtime Exceptions
# =============================================================================

class RuntimeError(CFastError):
    """
    Base exception for runtime errors during C function execution.
    
    Raised when errors occur while calling compiled C functions, such as
    type mismatches, memory access violations, or null pointer dereferences.
    
    Attributes
    ----------
    function_name : Optional[str]
        Name of the C function being called.
    arguments : Optional[Tuple]
        Arguments passed to the function.
    
    Parameters
    ----------
    message : str
        Error description.
    function_name : str, optional
        Function name.
    arguments : Tuple, optional
        Function arguments.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        message: str,
        function_name: Optional[str] = None,
        arguments: Optional[Tuple] = None,
        **details: Any
    ):
        self.function_name = function_name
        self.arguments = arguments
        
        full_message = message
        if function_name:
            full_message = f"Error calling '{function_name}': {message}"
        
        super().__init__(
            full_message,
            severity=ErrorSeverity.ERROR,
            error_code="CFAST_RUNTIME_001",
            **details
        )


class FunctionCallError(RuntimeError):
    """
    Raised when a C function call fails.
    
    This exception indicates that the actual function call failed, possibly
    due to incorrect argument types, wrong number of arguments, or calling
    convention mismatch.
    
    Attributes
    ----------
    expected_argtypes : Optional[List]
        Expected argument types.
    actual_argtypes : Optional[List]
        Actual argument types passed.
    
    Parameters
    ----------
    message : str
        Error description.
    function_name : str
        Function name.
    expected_argtypes : List, optional
        Expected types.
    actual_argtypes : List, optional
        Actual types.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        message: str,
        function_name: str,
        expected_argtypes: Optional[List] = None,
        actual_argtypes: Optional[List] = None,
        **details: Any
    ):
        self.expected_argtypes = expected_argtypes
        self.actual_argtypes = actual_argtypes
        
        super().__init__(
            message,
            function_name=function_name,
            error_code="CFAST_RUNTIME_002",
            **details
        )


class MemoryAccessError(RuntimeError):
    """
    Raised when memory access violation occurs.
    
    This exception indicates a segmentation fault, access violation,
    or other memory-related error during C function execution.
    
    Attributes
    ----------
    address : Optional[int]
        Memory address involved.
    access_type : str
        Type of access (read, write, execute).
    
    Parameters
    ----------
    message : str
        Error description.
    function_name : str, optional
        Function name.
    address : int, optional
        Memory address.
    access_type : str, optional
        Access type.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        message: str,
        function_name: Optional[str] = None,
        address: Optional[int] = None,
        access_type: str = "unknown",
        **details: Any
    ):
        self.address = address
        self.access_type = access_type
        
        full_message = message
        if address:
            full_message += f" at address 0x{address:x}"
        
        super().__init__(
            full_message,
            function_name=function_name,
            error_code="CFAST_RUNTIME_003",
            **details
        )


class TypeMismatchError(RuntimeError):
    """
    Raised when argument type doesn't match expected signature.
    
    This exception indicates that a Python argument cannot be converted
    to the expected C type.
    
    Attributes
    ----------
    param_index : int
        Index of the problematic parameter.
    expected_type : str
        Expected C type.
    actual_type : str
        Actual Python type provided.
    value : Any
        The value that caused the error.
    
    Parameters
    ----------
    param_index : int
        Parameter index.
    expected_type : str
        Expected type.
    actual_type : str
        Actual type.
    value : Any
        Problematic value.
    function_name : str, optional
        Function name.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        param_index: int,
        expected_type: str,
        actual_type: str,
        value: Any,
        function_name: Optional[str] = None,
        **details: Any
    ):
        self.param_index = param_index
        self.expected_type = expected_type
        self.actual_type = actual_type
        self.value = value
        
        message = (
            f"Parameter {param_index}: expected {expected_type}, "
            f"got {actual_type} (value: {repr(value)})"
        )
        
        super().__init__(
            message,
            function_name=function_name,
            error_code="CFAST_RUNTIME_004",
            **details
        )


class NullPointerError(RuntimeError):
    """
    Raised when a null pointer is passed where non-null is required.
    
    This exception indicates that None was passed for a pointer parameter
    that does not accept null values.
    
    Attributes
    ----------
    param_name : Optional[str]
        Name of the parameter.
    param_index : int
        Index of the parameter.
    
    Parameters
    ----------
    param_index : int
        Parameter index.
    param_name : str, optional
        Parameter name.
    function_name : str, optional
        Function name.
    **details : Any
        Additional error details.
    """
    
    def __init__(
        self,
        param_index: int,
        param_name: Optional[str] = None,
        function_name: Optional[str] = None,
        **details: Any
    ):
        self.param_index = param_index
        self.param_name = param_name
        
        param_desc = param_name or f"parameter {param_index}"
        message = f"Cannot pass None/null pointer for {param_desc}"
        
        super().__init__(
            message,
            function_name=function_name,
            error_code="CFAST_RUNTIME_005",
            **details
        )


# =============================================================================
# Aliases for Backward Compatibility
# =============================================================================

# Legacy alias
LockAcquisitionError = CacheLockError
ParseError = ParseSyntaxError


# =============================================================================
# Utility Functions
# =============================================================================

def _format_bytes(size: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


# =============================================================================
# Exception Registration for Serialization
# =============================================================================

_EXCEPTION_REGISTRY: Dict[str, type] = {}


def register_exception(cls: type) -> type:
    """Register an exception class for deserialization."""
    _EXCEPTION_REGISTRY[cls.__name__] = cls
    return cls


def deserialize_exception(data: Dict[str, Any]) -> Optional[CFastError]:
    """
    Deserialize an exception from dictionary.
    
    Parameters
    ----------
    data : Dict[str, Any]
        Serialized exception data.
    
    Returns
    -------
    Optional[CFastError]
        Deserialized exception or None.
    """
    exc_type = data.get('type')
    if exc_type and exc_type in _EXCEPTION_REGISTRY:
        cls = _EXCEPTION_REGISTRY[exc_type]
        return cls(data.get('message', ''))
    return None


# Register all exceptions
for _name, _obj in list(locals().items()):
    if isinstance(_obj, type) and issubclass(_obj, CFastError) and _obj != CFastError:
        register_exception(_obj)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Base
    "CFastError",
    "ErrorSeverity",
    "SourceContext",
    
    # Compilation
    "CompilationError",
    "CompilerNotFoundError",
    "CompilationTimeoutError",
    "LinkerError",
    "PreprocessorError",
    "AssemblyError",
    
    # Parsing
    "SignatureDetectionError",
    "PycparserNotAvailableError",
    "ParseSyntaxError",
    "StructDefinitionError",
    "TypeConversionError",
    "IncludeResolutionError",
    
    # Cache
    "CacheError",
    "CacheIntegrityError",
    "CacheCorruptionError",
    "CacheLockError",
    "StaleLockError",
    "CacheCapacityError",
    "CacheIOError",
    
    # Platform
    "PlatformError",
    "UnsupportedPlatformError",
    "LibraryLoadError",
    "ArchitectureMismatchError",
    "PermissionError",
    
    # Configuration
    "ConfigurationError",
    "InvalidSourceCodeError",
    "FunctionNotFoundError",
    "MultipleFunctionsError",
    "InvalidCompilerFlagError",
    "IncludePathError",
    
    # Runtime
    "RuntimeError",
    "FunctionCallError",
    "MemoryAccessError",
    "TypeMismatchError",
    "NullPointerError",
    
    # Aliases (backward compatibility)
    "LockAcquisitionError",
    "ParseError",
    
    # Utilities
    "extract_source_context",
    "deserialize_exception",
]