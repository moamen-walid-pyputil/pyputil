#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Custom exceptions for the cfast library.

This module defines the exception hierarchy used throughout the cfast package.
All custom exceptions inherit from the base :class:`CfastError` class, allowing
users to catch all cfast-specific errors with a single except clause.
"""


class CfastError(Exception):
    """
    Base exception class for all cfast-specific errors.

    This class serves as the root of the cfast exception hierarchy. All custom
    exceptions raised by the library inherit from this class, enabling users
    to catch any cfast-related error with a single except block.

    Examples
    --------
    >>> try:
    ...     lib = load_c("int main() { return 0; }")
    ... except CfastError as e:
    ...     print(f"cfast error occurred: {e}")
    """
    pass


class CompilationError(CfastError):
    """
    Raised when C code compilation fails.

    This exception is raised when the underlying C compiler returns a non-zero
    exit code during the compilation process. The exception message includes
    the compiler's stderr output to aid in debugging.

    Parameters
    ----------
    message : str
        The error message describing the compilation failure.
    compiler_output : str, optional
        The raw stderr output from the compiler, if available.

    Attributes
    ----------
    compiler_output : str or None
        The raw stderr output captured from the compiler.

    Examples
    --------
    >>> try:
    ...     lib = load_c("this is not valid C code")
    ... except CompilationError as e:
    ...     print(f"Compilation failed: {e}")
    ...     if e.compiler_output:
    ...         print(f"Compiler said: {e.compiler_output}")
    """

    def __init__(self, message: str, compiler_output: str = None):
        super().__init__(message)
        self.compiler_output = compiler_output


class SignatureDetectionError(CfastError):
    """
    Raised when automatic function signature extraction fails.

    This exception is raised when pycparser fails to parse the C source code
    or when the extracted type information cannot be converted to ctypes types.
    This is typically a non-fatal error; the library will fall back to manual
    signature configuration.

    Parameters
    ----------
    message : str
        The error message describing the signature detection failure.
    source_line : int, optional
        The approximate line number in the source code where parsing failed.

    Attributes
    ----------
    source_line : int or None
        The line number where the parsing error occurred, if available.

    Examples
    --------
    >>> try:
    ...     lib = load_c(code_with_complex_macros)
    ... except SignatureDetectionError as e:
    ...     print(f"Could not detect signatures automatically: {e}")
    ...     # Fall back to manual signature configuration
    ...     lib.my_func.argtypes = [ctypes.c_int]
    ...     lib.my_func.restype = ctypes.c_int
    """

    def __init__(self, message: str, source_line: int = None):
        super().__init__(message)
        self.source_line = source_line


class LockError(CfastError):
    """
    Raised when file locking operations fail.

    This exception indicates that a cross-process file lock could not be
    acquired or released. This may occur on network filesystems that do not
    support locking, or when permission errors prevent lock file creation.

    Parameters
    ----------
    message : str
        The error message describing the lock failure.
    lock_path : str or Path, optional
        The path to the lock file that caused the error.

    Attributes
    ----------
    lock_path : str or Path or None
        The path to the problematic lock file.

    Examples
    --------
    >>> try:
    ...     lib = load_c(code, force_recompile=True)
    ... except LockError as e:
    ...     print(f"Lock acquisition failed on {e.lock_path}: {e}")
    ...     # Proceed without locking (race condition possible)
    """
    
    def __init__(self, message: str, lock_path: str = None):
        super().__init__(message)
        self.lock_path = lock_path


class CompilerNotFoundError(CfastError):
    """
    Raised when no suitable C compiler is found on the system.

    This exception is raised when :func:`~cfast.compiler.detect_compiler`
    cannot locate any supported C compiler (GCC, Clang, or MSVC) in the
    system PATH.

    Parameters
    ----------
    message : str
        The error message describing the compiler detection failure.
    preferred : str, optional
        The preferred compiler that was requested but not found.

    Attributes
    ----------
    preferred : str or None
        The name of the preferred compiler that was requested.

    Examples
    --------
    >>> try:
    ...     compiler = detect_compiler(preferred="gcc")
    ... except CompilerNotFoundError as e:
    ...     print(f"Compiler not found: {e}")
    ...     print(f"Preferred compiler was: {e.preferred}")
    """
    
    def __init__(self, message: str, preferred: str = None):
        super().__init__(message)
        self.preferred = preferred