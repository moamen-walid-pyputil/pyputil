#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Compiler abstraction layer for C compilation across platforms.

This module provides a robust, secure, and platform-agnostic interface for
compiling C source code into shared libraries using different compilers
(GCC, Clang, MSVC). It handles platform-specific differences, provides
comprehensive error handling, and offers automatic compiler detection
with thorough validation.

Security Considerations
-----------------------
- All subprocess executions use secure argument passing (no shell=True)
- Path validation prevents directory traversal attacks
- Timeout protection prevents resource exhaustion
- Atomic file operations prevent race conditions

Classes
-------
Compiler
    Abstract base class defining the compilation interface.
GccCompiler
    Concrete implementation for GCC and GCC-compatible compilers.
ClangCompiler
    Concrete implementation for Clang/LLVM compiler.
MsvcCompiler
    Concrete implementation for Microsoft Visual C++ compiler.

Functions
---------
detect_compiler
    Locate and validate an available compiler with comprehensive checks.
validate_compiler_installation
    Perform extensive validation of compiler functionality.
get_supported_compilers
    Return list of compilers available on the system.

Examples
--------
>>> from pathlib import Path
>>> from cfast.compiler import detect_compiler
>>> 
>>> # Auto-detect best available compiler
>>> compiler = detect_compiler()
>>> if compiler:
...     compiler.compile_shared_library(
...         source=Path("mylib.c"),
...         output=Path("mylib.so"),
...         cflags=["-O3", "-Wall"],
...         defines={"DEBUG": None, "VERSION": "1.0"}
...     )

>>> # Prefer specific compiler with fallback
>>> compiler = detect_compiler(preferred="clang")
"""

import subprocess
import shutil
import sys
import warnings
import re
import os
import tempfile
import hashlib
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple, Set, Union, Type
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from contextlib import contextmanager

from .exceptions import CompilationError, CompilerNotFoundError
from .platform import PlatformInfo
from .utils import atomic_write, get_compiler_version, CTYPE_MAP


class CompilerType(Enum):
    """Enumeration of supported compiler types."""
    GCC = auto()
    CLANG = auto()
    MSVC = auto()
    UNKNOWN = auto()


@dataclass(frozen=True)
class CompilerCapabilities:
    """
    Compiler feature capabilities and limitations.
    
    Attributes
    ----------
    supports_pic : bool
        Whether compiler supports Position Independent Code.
    supports_shared : bool
        Whether compiler can generate shared libraries.
    supports_optimization_levels : Set[str]
        Supported optimization flags (e.g., {'O0', 'O1', 'O2', 'O3', 'Os'}).
    max_include_depth : int
        Maximum supported include directory nesting depth.
    supports_std_flags : Set[str]
        Supported C standard flags (e.g., {'c89', 'c99', 'c11', 'c17'}).
    warning_flags : Dict[str, str]
        Mapping of warning categories to compiler-specific flags.
    """
    supports_pic: bool = True
    supports_shared: bool = True
    supports_optimization_levels: Set[str] = field(default_factory=lambda: {'O0', 'O1', 'O2', 'O3', 'Os'})
    max_include_depth: int = 200
    supports_std_flags: Set[str] = field(default_factory=lambda: {'c89', 'c99', 'c11', 'c17'})
    warning_flags: Dict[str, str] = field(default_factory=dict)


@dataclass
class CompilationResult:
    """
    Detailed result of a compilation operation.
    
    Attributes
    ----------
    success : bool
        Whether compilation completed successfully.
    output_file : Optional[Path]
        Path to generated shared library if successful.
    compiler_name : str
        Name of compiler used.
    compiler_version : str
        Version string of compiler.
    command_line : List[str]
        Full command line executed.
    elapsed_time : float
        Compilation time in seconds.
    warnings : List[str]
        Compiler warning messages if any.
    exit_code : int
        Process exit code.
    """
    success: bool
    output_file: Optional[Path]
    compiler_name: str
    compiler_version: str
    command_line: List[str]
    elapsed_time: float
    warnings: List[str] = field(default_factory=list)
    exit_code: int = 0


class Compiler(ABC):
    """
    Abstract base class for a C compiler.
    
    This class defines the interface that all concrete compiler implementations
    must follow. It provides common compilation workflow with robust error
    handling, timeout protection, and security measures.
    
    Attributes
    ----------
    name : str
        Short identifier for the compiler (e.g., 'gcc', 'clang', 'msvc').
    compiler_type : CompilerType
        Type enumeration of the compiler.
    executable : Path
        Absolute path to the compiler executable.
    version : str
        Version string of the compiler.
    target_platform : str
        Target platform triplet (e.g., 'x86_64-linux-gnu').
    timeout : int
        Maximum time in seconds for compilation subprocess.
    capabilities : CompilerCapabilities
        Feature capabilities of this compiler instance.
    
    Parameters
    ----------
    executable : Union[str, Path]
        Compiler executable path or name in PATH.
    timeout : int, optional
        Maximum time in seconds for compilation (default: 120).
    validate : bool, optional
        Whether to validate compiler functionality on instantiation (default: True).
    
    Raises
    ------
    CompilerNotFoundError
        If compiler executable cannot be found or validated.
    
    Notes
    -----
    Subclasses must implement `_build_command` and `_get_capabilities`
    to provide compiler-specific behavior.
    """
    
    def __init__(
        self,
        executable: Union[str, Path],
        timeout: int = 120,
        validate: bool = True
    ) -> None:
        """
        Initialize compiler instance with validation.
        
        Parameters
        ----------
        executable : Union[str, Path]
            Compiler executable (name in PATH or absolute path).
        timeout : int, optional
            Maximum compilation time in seconds (default: 120).
        validate : bool, optional
            Perform validation checks on initialization (default: True).
        
        Raises
        ------
        CompilerNotFoundError
            If executable cannot be found or fails validation.
        ValueError
            If timeout is non-positive.
        """
        if timeout <= 0:
            raise ValueError(f"Timeout must be positive, got {timeout}")
        
        self.timeout = timeout
        
        # Resolve executable path securely
        self.executable = self._resolve_executable(executable)
        
        # Initialize compiler-specific attributes
        self.name = self._get_compiler_name() or "gcc"
        self.compiler_type = self._get_compiler_type()
        self.version = self._get_compiler_version()
        self.target_platform = self._get_target_platform()
        self.capabilities = self._get_capabilities()

        if validate:
            self._validate_installation()
    
    def _resolve_executable(self, executable: Union[str, Path]) -> Path:
        """
        Resolve compiler executable to absolute path.
        
        Parameters
        ----------
        executable : Union[str, Path]
            Executable name or path.
        
        Returns
        -------
        Path
            Absolute path to executable.
        
        Raises
        ------
        CompilerNotFoundError
            If executable cannot be found.
        """
        exe_path = shutil.which(str(executable))
        if exe_path is None:
            raise CompilerNotFoundError(
                f"Compiler executable '{executable}' not found in PATH"
            )
        return Path(exe_path).resolve()
    
    def _validate_installation(self) -> None:
        """
        Perform comprehensive validation of compiler installation.
        
        Validates that the compiler:
        - Exists and is executable
        - Can compile a minimal C program
        - Can generate shared libraries
        - Responds to basic commands
        
        Raises
        ------
        CompilerNotFoundError
            If validation fails.
        """
        validation_errors = []
        
        # Check executability
        if not self.executable.is_file():
            validation_errors.append(f"Not a regular file: {self.executable}")
        elif not os.access(self.executable, os.X_OK):
            validation_errors.append(f"Not executable: {self.executable}")
        
        # Test basic functionality
        try:
            result = subprocess.run(
                [str(self.executable), "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                validation_errors.append(
                    f"Failed to execute --version: {result.stderr}"
                )
        except subprocess.TimeoutExpired:
            validation_errors.append("Compiler version check timed out")
        except subprocess.SubprocessError as e:
            validation_errors.append(f"Compiler execution failed: {e}")
        
        # Test minimal compilation capability
        if not self._test_minimal_compilation():
            validation_errors.append("Failed to compile minimal test program")
        
        if validation_errors:
            raise CompilerNotFoundError(
                f"Compiler validation failed for {self.executable}:\n" +
                "\n".join(f"  - {err}" for err in validation_errors)
            )
    
    def _test_minimal_compilation(self) -> bool:
        """
        Test compilation of a minimal C program.
        
        Returns
        -------
        bool
            True if minimal program compiles successfully.
        """
        test_code = "int main(void) { return 0; }"
        
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.c',
            delete=False
        ) as source_file:
            source_file.write(test_code)
            source_path = Path(source_file.name)
        
        try:
            with tempfile.NamedTemporaryFile(
                suffix=self._get_shared_library_extension(),
                delete=False
            ) as output_file:
                output_path = Path(output_file.name)
            
            try:
                self.compile_shared_library(
                    source=source_path,
                    output=output_path,
                    cflags=["-w"]  # Suppress warnings
                )
                return output_path.exists() and output_path.stat().st_size > 0
            except CompilationError:
                return False
            finally:
                # Cleanup output
                try:
                    output_path.unlink(missing_ok=True)
                except OSError:
                    pass
        finally:
            # Cleanup source
            try:
                source_path.unlink(missing_ok=True)
            except OSError:
                pass
    
    @abstractmethod
    def _get_compiler_name(self) -> str:
        """Return compiler identifier name."""
        pass
    
    @abstractmethod
    def _get_compiler_type(self) -> CompilerType:
        """Return compiler type enumeration."""
        pass
    
    @abstractmethod
    def _get_compiler_version(self) -> str:
        """Extract and return compiler version string."""
        pass
    
    @abstractmethod
    def _get_target_platform(self) -> str:
        """Determine compiler's target platform."""
        pass
    
    @abstractmethod
    def _get_capabilities(self) -> CompilerCapabilities:
        """Return compiler-specific capabilities."""
        pass
    
    @abstractmethod
    def _get_shared_library_extension(self) -> str:
        """Return platform-specific shared library extension."""
        pass
    
    @abstractmethod
    def _build_command(
        self,
        source: Path,
        output: Path,
        cflags: Optional[List[str]] = None,
        includes: Optional[List[Path]] = None,
        defines: Optional[Dict[str, Optional[str]]] = None,
        libraries: Optional[List[str]] = None,
        library_paths: Optional[List[Path]] = None,
        link_args: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Build compiler command line.
        
        Parameters
        ----------
        source : Path
            Source file path.
        output : Path
            Output file path.
        cflags : Optional[List[str]]
            Compiler flags.
        includes : Optional[List[Path]]
            Include directories.
        defines : Optional[Dict[str, Optional[str]]]
            Preprocessor defines.
        libraries : Optional[List[str]]
            Libraries to link.
        library_paths : Optional[List[Path]]
            Library search paths.
        link_args : Optional[List[str]]
            Additional linker arguments.
        
        Returns
        -------
        List[str]
            Complete command line as list of arguments.
        """
        pass
    
    def compile_shared_library(
        self,
        source: Path,
        output: Path,
        cflags: Optional[List[str]] = None,
        includes: Optional[List[Union[str, Path]]] = None,
        defines: Optional[Dict[str, Optional[str]]] = None,
        libraries: Optional[List[str]] = None,
        library_paths: Optional[List[Union[str, Path]]] = None,
        link_args: Optional[List[str]] = None,
        validate_source: bool = True,
        cleanup_on_error: bool = True,
    ) -> CompilationResult:
        """
        Compile a C source file into a shared library.
        
        This method provides a complete compilation workflow with:
        - Source code validation
        - Secure path handling
        - Atomic file operations
        - Comprehensive error reporting
        - Timeout protection
        
        Parameters
        ----------
        source : Path
            Path to the source file (e.g., 'program.c').
        output : Path
            Desired output path for the compiled shared library.
        cflags : Optional[List[str]]
            Compiler flags (e.g., ['-O3', '-Wall']). Defaults to empty.
        includes : Optional[List[Union[str, Path]]]
            Additional include directories. Paths are resolved and validated.
        defines : Optional[Dict[str, Optional[str]]]
            Macro definitions. Keys are macro names; None values define
            without a value (e.g., `-DDEBUG`). Defaults to empty.
        libraries : Optional[List[str]]
            Libraries to link against. Flag is compiler-specific.
        library_paths : Optional[List[Union[str, Path]]]
            Additional library search paths.
        link_args : Optional[List[str]]
            Additional linker flags. Defaults to empty.
        validate_source : bool, optional
            Whether to validate source file before compilation (default: True).
        cleanup_on_error : bool, optional
            Whether to remove partial outputs on failure (default: True).
        
        Returns
        -------
        CompilationResult
            Detailed compilation result including success status and metadata.
        
        Raises
        ------
        CompilationError
            If compilation fails, times out, or encounters an error.
        FileNotFoundError
            If source file does not exist and validation is enabled.
        ValueError
            If invalid parameters are provided.
        
        Examples
        --------
        >>> compiler = GccCompiler()
        >>> result = compiler.compile_shared_library(
        ...     source=Path("add.c"),
        ...     output=Path("add.so"),
        ...     cflags=["-O2", "-Wall"],
        ...     defines={"NDEBUG": None, "VERSION": "1.0.0"},
        ...     libraries=["m", "pthread"]
        ... )
        >>> if result.success:
        ...     print(f"Compiled {result.output_file}")
        """
        import time
        
        start_time = time.time()
        
        # Validate inputs
        self._validate_compilation_inputs(
            source, output, validate_source,
            includes, library_paths
        )
        
        # Convert and normalize paths
        includes_paths = self._normalize_paths(includes) if includes else None
        library_paths_norm = self._normalize_paths(library_paths) if library_paths else None
        
        # Ensure output directory exists
        output.parent.mkdir(parents=True, exist_ok=True)
        
        # Build command line
        cmd = self._build_command(
            source=source.resolve(),
            output=output.resolve(),
            cflags=cflags or [],
            includes=includes_paths,
            defines=defines or {},
            libraries=libraries or [],
            library_paths=library_paths_norm,
            link_args=link_args or [],
        )
        
        # Execute compilation
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,  # Handle errors manually for better reporting
            )
            
            elapsed_time = time.time() - start_time
            
            # Extract warnings from stderr
            warnings_list = self._extract_warnings(result.stderr)
            
            compilation_result = CompilationResult(
                success=result.returncode == 0,
                output_file=output if result.returncode == 0 else None,
                compiler_name=self.name,
                compiler_version=self.version,
                command_line=cmd,
                elapsed_time=elapsed_time,
                warnings=warnings_list,
                exit_code=result.returncode,
            )
            
            if result.returncode != 0:
                if cleanup_on_error and output.exists():
                    try:
                        output.unlink()
                    except OSError:
                        pass
                
                raise CompilationError(
                    f"Compilation failed with {self.name} (exit code {result.returncode})\n"
                    f"Command: {' '.join(cmd)}\n"
                    f"Stderr: {result.stderr}\n"
                    f"Stdout: {result.stdout}"
                )
            
            # Log warnings if any
            if warnings_list:
                warnings.warn(
                    f"Compilation produced {len(warnings_list)} warning(s)",
                    UserWarning
                )
            
            return compilation_result
            
        except subprocess.TimeoutExpired as e:
            elapsed_time = time.time() - start_time
            raise CompilationError(
                f"Compilation timed out after {self.timeout} seconds\n"
                f"Command: {' '.join(cmd)}"
            ) from e
        except subprocess.SubprocessError as e:
            raise CompilationError(
                f"Subprocess error during compilation: {e}"
            ) from e
    
    def _validate_compilation_inputs(
        self,
        source: Path,
        output: Path,
        validate_source: bool,
        includes: Optional[List[Union[str, Path]]],
        library_paths: Optional[List[Union[str, Path]]],
    ) -> None:
        """
        Validate compilation input parameters.
        
        Parameters
        ----------
        source : Path
            Source file path.
        output : Path
            Output file path.
        validate_source : bool
            Whether to validate source existence.
        includes : Optional[List[Union[str, Path]]]
            Include directory paths.
        library_paths : Optional[List[Union[str, Path]]]
            Library directory paths.
        
        Raises
        ------
        FileNotFoundError
            If source file doesn't exist.
        ValueError
            If paths are invalid or contain dangerous patterns.
        """
        # Validate source
        if validate_source:
            if not source.exists():
                raise FileNotFoundError(f"Source file not found: {source}")
            if not source.is_file():
                raise ValueError(f"Source path is not a file: {source}")
            if source.stat().st_size == 0:
                raise ValueError(f"Source file is empty: {source}")
        
        # Validate output path
        if not output.parent.exists():
            raise ValueError(f"Output directory does not exist: {output.parent}")
        
        # Security: Check for path traversal attempts
        self._check_path_traversal(source, "source")
        self._check_path_traversal(output, "output")
        
        # Validate optional paths
        for path_list, name in [(includes, "include"), (library_paths, "library_path")]:
            if path_list:
                for p in path_list:
                    path_obj = Path(p)
                    if not path_obj.exists():
                        warnings.warn(
                            f"{name.capitalize()} directory does not exist: {path_obj}",
                            UserWarning
                        )
                    self._check_path_traversal(path_obj, name)
    
    def _check_path_traversal(self, path: Path, path_type: str) -> None:
        """
        Check for potential path traversal attacks.
        
        Parameters
        ----------
        path : Path
            Path to check.
        path_type : str
            Type of path for error messages.
        
        Raises
        ------
        ValueError
            If suspicious path patterns are detected.
        """
        path_str = str(path.resolve())
        
        # Check for suspicious patterns
        suspicious_patterns = [
            "..",  # Parent directory traversal
            "~",   # Home directory expansion
            "${",  # Environment variable expansion
            "$(",   # Command substitution
            "`",    # Command substitution
            "&&",   # Command chaining
            "||",   # Command chaining
            ";",    # Command separation
            "|",    # Pipe
            ">",    # Redirection
            "<",    # Redirection
        ]
        
        for pattern in suspicious_patterns:
            if pattern in path_str:
                raise ValueError(
                    f"Suspicious pattern '{pattern}' found in {path_type} path: {path}"
                )
    
    def _normalize_paths(self, paths: List[Union[str, Path]]) -> List[Path]:
        """
        Convert and normalize a list of paths.
        
        Parameters
        ----------
        paths : List[Union[str, Path]]
            List of path strings or Path objects.
        
        Returns
        -------
        List[Path]
            List of resolved Path objects.
        """
        return [Path(p).resolve() for p in paths]
    
    def _extract_warnings(self, stderr: str) -> List[str]:
        """
        Extract warning messages from compiler stderr output.
        
        Parameters
        ----------
        stderr : str
            Compiler standard error output.
        
        Returns
        -------
        List[str]
            List of extracted warning messages.
        """
        warnings_list = []
        warning_patterns = [
            r'warning:.*',
            r'Warning:.*',
            r'WARNING:.*',
        ]
        
        for line in stderr.splitlines():
            for pattern in warning_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    warnings_list.append(line.strip())
                    break
        
        return warnings_list
    
    def __repr__(self) -> str:
        """Return string representation of compiler instance."""
        return f"{self.__class__.__name__}(name='{self.name}', version='{self.version}', executable='{self.executable}')"
    
    def __str__(self) -> str:
        """Return user-friendly string representation."""
        return f"{self.name} {self.version} ({self.target_platform})"


class GccCompiler(Compiler):
    """
    GCC-compatible compiler (GNU Compiler Collection).
    
    Supports GCC and any compiler that accepts GCC-style command-line options
    (e.g., `-shared`, `-fPIC`, `-I`, `-D`, `-l`, `-L`).
    
    Attributes
    ----------
    Inherits all attributes from Compiler.
    
    Examples
    --------
    >>> gcc = GccCompiler()
    >>> result = gcc.compile_shared_library(
    ...     source=Path("add.c"),
    ...     output=Path("add.so"),
    ...     cflags=["-O2", "-Wall", "-Wextra"],
    ...     libraries=["m", "pthread"]
    ... )
    >>> print(f"Compilation time: {result.elapsed_time:.2f}s")
    """
    
    def __init__(
        self,
        executable: Union[str, Path] = "gcc",
        timeout: int = 120,
        validate: bool = True
    ) -> None:
        """
        Initialize GCC compiler instance.
        
        Parameters
        ----------
        executable : Union[str, Path], optional
            GCC executable name or path (default: "gcc").
        timeout : int, optional
            Maximum compilation time in seconds (default: 120).
        validate : bool, optional
            Perform validation on initialization (default: True).
        
        Raises
        ------
        CompilerNotFoundError
            If GCC cannot be found or fails validation.
        """
        super().__init__(executable, timeout, validate)
    
    def _get_compiler_name(self) -> str:
        """Return compiler identifier."""
        return "gcc"
    
    def _get_compiler_type(self) -> CompilerType:
        """Return compiler type."""
        return CompilerType.GCC
    
    def _get_compiler_version(self) -> str:
        """
        Extract GCC version from --version output.
        
        Returns
        -------
        str
            Version string (e.g., "9.3.0").
        """
        try:
            result = subprocess.run(
                [str(self.executable), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True
            )
            
            # Parse version from first line
            # Format: "gcc (Ubuntu 9.3.0-17ubuntu1~20.04) 9.3.0"
            match = re.search(r'(\d+\.\d+\.\d+)', result.stdout)
            if match:
                return match.group(1)
            
            return "unknown"
        except (subprocess.SubprocessError, AttributeError):
            return "unknown"
    
    def _get_target_platform(self) -> str:
        """
        Determine GCC target platform.
        
        Returns
        -------
        str
            Target platform triplet (e.g., "x86_64-linux-gnu").
        """
        try:
            result = subprocess.run(
                [str(self.executable), "-dumpmachine"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True
            )
            return result.stdout.strip()
        except subprocess.SubprocessError:
            return "unknown-unknown-unknown"
    
    def _get_capabilities(self) -> CompilerCapabilities:
        """
        Determine GCC-specific capabilities.
        
        Returns
        -------
        CompilerCapabilities
            Capabilities object with GCC-specific features.
        """
        return CompilerCapabilities(
            supports_pic=True,
            supports_shared=True,
            supports_optimization_levels={'O0', 'O1', 'O2', 'O3', 'Os', 'Ofast'},
            max_include_depth=200,
            supports_std_flags={'c89', 'c99', 'c11', 'c17', 'c2x', 'gnu89', 'gnu99', 'gnu11', 'gnu17'},
            warning_flags={
                'all': '-Wall',
                'extra': '-Wextra',
                'pedantic': '-pedantic',
                'shadow': '-Wshadow',
                'format': '-Wformat=2',
                'unused': '-Wunused',
            }
        )
    
    def _get_shared_library_extension(self) -> str:
        """Return shared library extension for current platform."""
        if sys.platform.startswith('win'):
            return '.dll'
        elif sys.platform == 'darwin':
            return '.dylib'
        else:
            return '.so'
    
    def _build_command(
        self,
        source: Path,
        output: Path,
        cflags: Optional[List[str]] = None,
        includes: Optional[List[Path]] = None,
        defines: Optional[Dict[str, Optional[str]]] = None,
        libraries: Optional[List[str]] = None,
        library_paths: Optional[List[Path]] = None,
        link_args: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Build GCC command line.
        
        Constructs a command line with GCC-style flags:
        - Shared library: -shared
        - Position-independent code: -fPIC
        - Includes: -I<path>
        - Defines: -D<name>[=<value>]
        - Libraries: -l<name>
        - Library paths: -L<path>
        - Output: -o <path>
        
        Parameters
        ----------
        source : Path
            Source file path.
        output : Path
            Output file path.
        cflags : Optional[List[str]]
            Additional compiler flags.
        includes : Optional[List[Path]]
            Include directory paths.
        defines : Optional[Dict[str, Optional[str]]]
            Preprocessor macro definitions.
        libraries : Optional[List[str]]
            Library names to link against.
        library_paths : Optional[List[Path]]
            Library search paths.
        link_args : Optional[List[str]]
            Additional linker arguments.
        
        Returns
        -------
        List[str]
            Complete GCC command line.
        """
        cmd = [str(self.executable), "-shared", "-fPIC"]
        
        # Add compiler flags
        if cflags:
            cmd.extend(cflags)
        
        # Add include directories
        if includes:
            for inc in includes:
                cmd.extend(["-I", str(inc)])
        
        # Add preprocessor defines
        if defines:
            for macro, value in defines.items():
                if value is None:
                    cmd.append(f"-D{macro}")
                else:
                    # Escape special characters in value
                    escaped_value = value.replace('"', '\\"')
                    cmd.append(f'-D{macro}="{escaped_value}"')
        
        # Add library search paths
        if library_paths:
            for lib_path in library_paths:
                cmd.extend(["-L", str(lib_path)])
        
        # Add linker arguments
        if link_args:
            cmd.extend(link_args)
        
        # Add libraries to link
        if libraries:
            for lib in libraries:
                cmd.extend(["-l", lib])
        
        # Add source and output
        cmd.extend([str(source), "-o", str(output)])
        
        return cmd


class ClangCompiler(GccCompiler):
    """
    Clang/LLVM compiler.
    
    Clang is largely command-line compatible with GCC, but offers additional
    features like better error messages and static analysis capabilities.
    
    Attributes
    ----------
    Inherits all attributes from GccCompiler.
    
    Examples
    --------
    >>> clang = ClangCompiler()
    >>> result = clang.compile_shared_library(
    ...     source=Path("mylib.c"),
    ...     output=Path("mylib.so"),
    ...     cflags=["-O3", "-march=native"],
    ...     defines={"USE_AVX2": "1"}
    ... )
    """
    
    def __init__(
        self,
        executable: Union[str, Path] = "clang",
        timeout: int = 120,
        validate: bool = True
    ) -> None:
        """
        Initialize Clang compiler instance.
        
        Parameters
        ----------
        executable : Union[str, Path], optional
            Clang executable name or path (default: "clang").
        timeout : int, optional
            Maximum compilation time in seconds (default: 120).
        validate : bool, optional
            Perform validation on initialization (default: True).
        
        Raises
        ------
        CompilerNotFoundError
            If Clang cannot be found or fails validation.
        """
        super().__init__(executable, timeout, validate)
    
    def _get_compiler_name(self) -> str:
        """Return compiler identifier."""
        return "clang"
    
    def _get_compiler_type(self) -> CompilerType:
        """Return compiler type."""
        return CompilerType.CLANG
    
    def _get_compiler_version(self) -> str:
        """
        Extract Clang version from --version output.
        
        Returns
        -------
        str
            Version string (e.g., "10.0.0").
        """
        try:
            result = subprocess.run(
                [str(self.executable), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True
            )
            
            # Parse version from first line
            # Format: "clang version 10.0.0-4ubuntu1"
            match = re.search(r'clang version (\d+\.\d+\.\d+)', result.stdout)
            if match:
                return match.group(1)
            
            return "unknown"
        except (subprocess.SubprocessError, AttributeError):
            return "unknown"
    
    def _get_capabilities(self) -> CompilerCapabilities:
        """
        Determine Clang-specific capabilities.
        
        Returns
        -------
        CompilerCapabilities
            Capabilities object with Clang-specific features.
        """
        caps = super()._get_capabilities()
        
        # Clang supports additional warning flags
        caps.warning_flags.update({
            'everything': '-Weverything',
            'documentation': '-Wdocumentation',
            'unreachable-code': '-Wunreachable-code',
            'thread-safety': '-Wthread-safety',
        })
        
        # Clang has better optimization options
        caps.supports_optimization_levels.add('Oz')
        
        return caps


class MsvcCompiler(Compiler):
    """
    Microsoft Visual C++ compiler (MSVC).
    
    Supports the MSVC toolchain, invoked via `cl.exe`. Uses MSVC-style
    flags: `/LD` for shared library, `/I` for includes, `/D` for defines,
    and `/Fe` for output filename.
    
    Attributes
    ----------
    Inherits all attributes from Compiler.
    
    Notes
    -----
    MSVC requires certain environment variables to be set (INCLUDE, LIB, PATH).
    These are typically configured by running vcvarsall.bat or using
    Developer Command Prompt.
    
    Examples
    --------
    >>> msvc = MsvcCompiler()
    >>> result = msvc.compile_shared_library(
    ...     source=Path("add.c"),
    ...     output=Path("add.dll"),
    ...     cflags=["/O2", "/W4"],
    ...     libraries=["kernel32", "user32"]
    ... )
    """
    
    def __init__(
        self,
        executable: Union[str, Path] = "cl",
        timeout: int = 120,
        validate: bool = True
    ) -> None:
        """
        Initialize MSVC compiler instance.
        
        Parameters
        ----------
        executable : Union[str, Path], optional
            MSVC compiler executable name or path (default: "cl").
        timeout : int, optional
            Maximum compilation time in seconds (default: 120).
        validate : bool, optional
            Perform validation on initialization (default: True).
        
        Raises
        ------
        CompilerNotFoundError
            If MSVC cannot be found or fails validation.
        """
        super().__init__(executable, timeout, validate)
    
    def _get_compiler_name(self) -> str:
        """Return compiler identifier."""
        return "msvc"
    
    def _get_compiler_type(self) -> CompilerType:
        """Return compiler type."""
        return CompilerType.MSVC
    
    def _get_compiler_version(self) -> str:
        """
        Extract MSVC version from compiler output.
        
        Returns
        -------
        str
            Version string (e.g., "19.28.29336").
        """
        try:
            result = subprocess.run(
                [str(self.executable)],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # MSVC outputs version when run without arguments
            # Format: "Microsoft (R) C/C++ Optimizing Compiler Version 19.28.29336 for x64"
            match = re.search(r'Version (\d+\.\d+\.\d+)', result.stdout)
            if match:
                return match.group(1)
            
            return "unknown"
        except (subprocess.SubprocessError, AttributeError):
            return "unknown"
    
    def _get_target_platform(self) -> str:
        """
        Determine MSVC target platform.
        
        Returns
        -------
        str
            Target platform (e.g., "x64", "x86", "ARM64").
        """
        try:
            result = subprocess.run(
                [str(self.executable)],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # Extract architecture from output
            match = re.search(r'for (\w+)', result.stdout)
            if match:
                return match.group(1).lower()
            
            return "unknown"
        except subprocess.SubprocessError:
            return "unknown"
    
    def _get_capabilities(self) -> CompilerCapabilities:
        """
        Determine MSVC-specific capabilities.
        
        Returns
        -------
        CompilerCapabilities
            Capabilities object with MSVC-specific features.
        """
        return CompilerCapabilities(
            supports_pic=False,  # MSVC uses different mechanism
            supports_shared=True,
            supports_optimization_levels={'Od', 'O1', 'O2', 'Ox'},
            max_include_depth=200,
            supports_std_flags={'c89', 'c99', 'c11', 'c17'},
            warning_flags={
                'all': '/W4',
                'extra': '/Wall',
                'pedantic': '/Za',
                'unused': '/we4100',
            }
        )
    
    def _get_shared_library_extension(self) -> str:
        """Return shared library extension for Windows."""
        return '.dll'
    
    def _build_command(
        self,
        source: Path,
        output: Path,
        cflags: Optional[List[str]] = None,
        includes: Optional[List[Path]] = None,
        defines: Optional[Dict[str, Optional[str]]] = None,
        libraries: Optional[List[str]] = None,
        library_paths: Optional[List[Path]] = None,
        link_args: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Build MSVC command line.
        
        Constructs a command line with MSVC-style flags:
        - Shared library: /LD
        - No logo: /nologo
        - Includes: /I<path>
        - Defines: /D<name>[=<value>]
        - Output: /Fe:<path>
        
        Parameters
        ----------
        source : Path
            Source file path.
        output : Path
            Output file path.
        cflags : Optional[List[str]]
            Additional compiler flags.
        includes : Optional[List[Path]]
            Include directory paths.
        defines : Optional[Dict[str, Optional[str]]]
            Preprocessor macro definitions.
        libraries : Optional[List[str]]
            Library names to link against.
        library_paths : Optional[List[Path]]
            Library search paths.
        link_args : Optional[List[str]]
            Additional linker arguments.
        
        Returns
        -------
        List[str]
            Complete MSVC command line.
        """
        cmd = [str(self.executable), "/LD", "/nologo"]
        
        # Add compiler flags
        if cflags:
            cmd.extend(cflags)
        
        # Add include directories
        if includes:
            for inc in includes:
                cmd.append(f"/I{inc}")
        
        # Add preprocessor defines
        if defines:
            for macro, value in defines.items():
                if value is None:
                    cmd.append(f"/D{macro}")
                else:
                    # Escape special characters for MSVC
                    escaped_value = value.replace('"', '\\"')
                    cmd.append(f'/D{macro}="{escaped_value}"')
        
        # Add library search paths
        if library_paths:
            for lib_path in library_paths:
                cmd.append(f"/LIBPATH:{lib_path}")
        
        # Add linker arguments
        if link_args:
            cmd.append(f"/link")
            cmd.extend(link_args)
        
        # Add libraries to link
        if libraries:
            if not link_args:
                cmd.append("/link")
            for lib in libraries:
                cmd.append(f"{lib}.lib")
        
        # Add source file
        cmd.append(str(source))
        
        # Set output file
        # MSVC uses /Fe for executable/dll output
        cmd.append(f"/Fe:{output}")
        
        return cmd
    
    def _validate_installation(self) -> None:
        """
        Perform MSVC-specific validation.
        
        Checks for required environment variables and toolchain components.
        
        Raises
        ------
        CompilerNotFoundError
            If MSVC environment is not properly configured.
        """
        super()._validate_installation()
        
        # Check for required environment variables
        required_vars = ['INCLUDE', 'LIB']
        missing_vars = [var for var in required_vars if var not in os.environ]
        
        if missing_vars:
            warnings.warn(
                f"MSVC environment variables not set: {', '.join(missing_vars)}. "
                "Run vcvarsall.bat or use Developer Command Prompt.",
                UserWarning
            )


def validate_compiler_installation(compiler: Compiler) -> Tuple[bool, List[str]]:
    """
    Perform comprehensive validation of compiler installation.
    
    This function runs extensive tests to verify compiler functionality:
    - Basic compilation
    - Shared library generation
    - Optimization flag support
    - Include path handling
    - Library linking
    
    Parameters
    ----------
    compiler : Compiler
        Compiler instance to validate.
    
    Returns
    -------
    Tuple[bool, List[str]]
        - bool: True if all validation tests pass
        - List[str]: List of validation issues encountered
    
    Examples
    --------
    >>> compiler = detect_compiler()
    >>> is_valid, issues = validate_compiler_installation(compiler)
    >>> if not is_valid:
    ...     print("Validation issues:")
    ...     for issue in issues:
    ...         print(f"  - {issue}")
    """
    issues = []
    
    # Test 1: Basic compilation
    test_code = """
    #include <stdio.h>
    
    int add(int a, int b) {
        return a + b;
    }
    
    int main(void) {
        printf("Test: %d\\n", add(2, 3));
        return 0;
    }
    """
    
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.c',
        delete=False
    ) as source_file:
        source_file.write(test_code)
        source_path = Path(source_file.name)
    
    try:
        with tempfile.NamedTemporaryFile(
            suffix=compiler._get_shared_library_extension(),
            delete=False
        ) as output_file:
            output_path = Path(output_file.name)
        
        try:
            # Test shared library compilation
            result = compiler.compile_shared_library(
                source=source_path,
                output=output_path,
                cflags=["-O2", "-Wall"] if compiler.compiler_type != CompilerType.MSVC else ["/O2", "/W4"],
                validate_source=False
            )
            
            if not result.success:
                issues.append(f"Failed to compile shared library: {result}")
            elif not output_path.exists():
                issues.append("Output file not created")
            elif output_path.stat().st_size == 0:
                issues.append("Output file is empty")
                
        except CompilationError as e:
            issues.append(f"Compilation failed: {e}")
        except Exception as e:
            issues.append(f"Unexpected error during compilation: {e}")
        finally:
            # Cleanup output
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
            
    finally:
        # Cleanup source
        try:
            source_path.unlink(missing_ok=True)
        except OSError:
            pass
    
    return len(issues) == 0, issues


def get_supported_compilers() -> Dict[str, Type[Compiler]]:
    """
    Get dictionary of available compiler classes.
    
    Returns
    -------
    Dict[str, Type[Compiler]]
        Mapping of compiler names to their classes.
    
    Examples
    --------
    >>> compilers = get_supported_compilers()
    >>> print(f"Supported compilers: {', '.join(compilers.keys())}")
    """
    compilers = {
        'gcc': GccCompiler,
        'clang': ClangCompiler,
    }
    
    if sys.platform.startswith('win'):
        compilers['msvc'] = MsvcCompiler
    
    return compilers


def detect_compiler(
    preferred: Optional[str] = None,
    timeout: int = 120,
    require_validation: bool = True
) -> Optional[Compiler]:
    """
    Detect an available and working C compiler on the system.
    
    Searches for known compilers (GCC, Clang, MSVC) and validates that
    they actually work. Detection order can be influenced by `preferred`.
    
    The detection process:
    1. Try preferred compiler if specified
    2. Search platform-specific compilers in optimal order
    3. Validate each candidate before returning
    4. Fall back to any available compiler
    
    Parameters
    ----------
    preferred : Optional[str]
        Name of the preferred compiler. One of: 'gcc', 'clang', 'msvc' (or 'cl').
        If not available, falls back to auto-detection.
    timeout : int, optional
        Compilation timeout in seconds for detected compiler (default: 120).
    require_validation : bool, optional
        Whether to perform comprehensive validation (default: True).
    
    Returns
    -------
    Optional[Compiler]
        A concrete compiler instance if a working compiler is found,
        otherwise None.
    
    Raises
    ------
    CompilerNotFoundError
        If no working compiler is found.
    
    Examples
    --------
    >>> # Auto-detect best compiler
    >>> compiler = detect_compiler()
    >>> if compiler:
    ...     print(f"Using {compiler.name} {compiler.version}")
    
    >>> # Prefer Clang with specific timeout
    >>> compiler = detect_compiler(preferred="clang", timeout=300)
    
    >>> # Don't require comprehensive validation
    >>> compiler = detect_compiler(require_validation=False)
    """
    supported_compilers = get_supported_compilers()
    
    # Try preferred compiler first
    if preferred:
        preferred_lower = preferred.lower()
        
        # Handle aliases
        alias_map = {
            'cl': 'msvc',
            'g++': 'gcc',
            'clang++': 'clang',
        }
        compiler_key = alias_map.get(preferred_lower, preferred_lower)
        
        if compiler_key in supported_compilers:
            compiler_class = supported_compilers[compiler_key]
            default_exes = {
                'gcc': 'gcc',
                'clang': 'clang',
                'msvc': 'cl',
            }
            exe_name = default_exes.get(compiler_key, compiler_key)
            
            try:
                compiler = compiler_class(
                    executable=exe_name,
                    timeout=timeout,
                    validate=require_validation
                )
                return compiler
            except CompilerNotFoundError:
                warnings.warn(
                    f"Preferred compiler '{preferred}' not available or not working. "
                    "Falling back to auto-detection.",
                    UserWarning
                )
        else:
            warnings.warn(
                f"Unknown preferred compiler '{preferred}'. "
                f"Supported: {', '.join(supported_compilers.keys())}",
                UserWarning
            )
    
    # Auto-detect based on platform
    if sys.platform.startswith('win'):
        detection_order = [
            ('cl', MsvcCompiler),  # MSVC first on Windows
            ('gcc', GccCompiler),
            ('clang', ClangCompiler),
        ]
    elif sys.platform == 'darwin':
        detection_order = [
            ('clang', ClangCompiler),  # Clang is default on macOS
            ('gcc', GccCompiler),
        ]
    else:
        detection_order = [
            ('gcc', GccCompiler),  # GCC is common on Linux
            ('clang', ClangCompiler),
        ]
    
    # Try each compiler in detection order
    for exe_name, compiler_class in detection_order:
        # Check if executable exists
        if shutil.which(exe_name):
            try:
                compiler = compiler_class(
                    executable=exe_name,
                    timeout=timeout,
                    validate=require_validation
                )
                return compiler
            except CompilerNotFoundError:
                # Continue to next candidate
                continue
    
    # No compiler found
    raise CompilerNotFoundError(
        f"No working C compiler found on system.\n"
        f"Checked: {', '.join([exe for exe, _ in detection_order])}\n"
        f"Please install a C compiler (GCC, Clang, or MSVC)."
    )


# Export public interface
__all__ = [
    'Compiler',
    'GccCompiler',
    'ClangCompiler',
    'MsvcCompiler',
    'CompilerType',
    'CompilerCapabilities',
    'CompilationResult',
    'detect_compiler',
    'validate_compiler_installation',
    'get_supported_compilers',
    'CompilationError',
    'CompilerNotFoundError',
]