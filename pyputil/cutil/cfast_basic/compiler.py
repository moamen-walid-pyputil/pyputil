#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Compiler abstraction and factory for C compilation across platforms.

This module provides a unified interface for compiling C source code into
shared libraries using different compilers (GCC, Clang, MSVC). It handles
platform-specific differences and offers automatic compiler detection.

The main components are:
    - :class:`Compiler`: Abstract base class defining the compilation interface
    - :class:`GccCompiler`: Implementation for GCC-compatible compilers
    - :class:`ClangCompiler`: Implementation for Clang/LLVM
    - :class:`MsvcCompiler`: Implementation for Microsoft Visual C++
    - :func:`detect_compiler`: Factory function to locate an available compiler

Examples
--------
Auto-detect and compile:

>>> from cfast_basic.compiler import detect_compiler
>>> compiler = detect_compiler()
>>> if compiler:
...     compiler.compile_shared_library(
...         source=Path("example.c"),
...         output=Path("example.so"),
...         cflags=["-O2"]
...     )

Force a specific compiler:

>>> from cfast_basic.compiler import GccCompiler
>>> gcc = GccCompiler()
>>> gcc.compile_shared_library(
...     source=Path("example.c"),
...     output=Path("example.so"),
...     cflags=["-O2", "-Wall"]
... )
"""

import subprocess
import shutil
import sys
import warnings
from pathlib import Path
from typing import List, Optional, Dict, Any, Type, Union
from abc import ABC, abstractmethod

from .exceptions import CompilationError, CompilerNotFoundError
from .platform import PlatformInfo


class Compiler(ABC):
    """
    Abstract base class for a C compiler.

    This class defines the interface that all concrete compiler implementations
    must follow. It provides common attributes and requires subclasses to
    implement the :meth:`compile_shared_library` method with platform-specific
    command construction.

    Parameters
    ----------
    name : str
        Short identifier for the compiler (e.g., 'gcc', 'clang', 'msvc').
    executable : str
        Path or name of the compiler executable. This should be accessible
        via the system PATH or be an absolute path.

    Attributes
    ----------
    name : str
        The compiler identifier.
    executable : str
        The compiler executable path or name.

    Methods
    -------
    compile_shared_library(source, output, cflags, includes, defines, libraries, link_args)
        Compile a C source file into a shared library. Must be implemented
        by subclasses.

    Notes
    -----
    This is an abstract base class. Instantiate one of the concrete subclasses:
    :class:`GccCompiler`, :class:`ClangCompiler`, or :class:`MsvcCompiler`.
    """

    def __init__(self, name: str, executable: str):
        """
        Initialize a compiler instance.

        Parameters
        ----------
        name : str
            Identifier for the compiler (e.g., 'gcc', 'clang').
        executable : str
            Compiler executable name or path.
        """
        self.name = name
        self.executable = executable

    def __repr__(self) -> str:
        """Return a string representation of the compiler."""
        return f"{self.__class__.__name__}(name='{self.name}', executable='{self.executable}')"

    @abstractmethod
    def compile_shared_library(
        self,
        source: Path,
        output: Path,
        cflags: Optional[List[str]] = None,
        includes: Optional[List[str]] = None,
        defines: Optional[Dict[str, Optional[str]]] = None,
        libraries: Optional[List[str]] = None,
        link_args: Optional[List[str]] = None,
    ) -> None:
        """
        Compile a C source file into a shared library.

        Parameters
        ----------
        source : Path
            Path to the C source file to compile.
        output : Path
            Desired output path for the compiled shared library.
        cflags : list of str, optional
            Compiler flags (e.g., ``['-O3', '-Wall']``). Defaults to empty list.
        includes : list of str, optional
            Additional include directories. Each entry is passed as ``-I<dir>``
            (or ``/I<dir>`` on MSVC). Defaults to empty list.
        defines : dict of {str: str or None}, optional
            Macro definitions. If value is None, defined as ``-DNAME``.
            Otherwise defined as ``-DNAME=value``. Defaults to empty dict.
        libraries : list of str, optional
            Libraries to link against. The actual flag is compiler-specific
            (``-l`` for GCC/Clang, ``.lib`` suffix for MSVC). Defaults to empty list.
        link_args : list of str, optional
            Additional linker flags passed directly to the linker. Defaults to empty list.

        Raises
        ------
        CompilationError
            If the compilation command returns a non-zero exit code.
            The exception includes the compiler's stderr output.

        Notes
        -----
        This method does not return anything; success is indicated by the
        absence of an exception.
        """
        raise NotImplementedError("Subclasses must implement compile_shared_library")

    def _run_command(self, cmd: List[str]) -> None:
        """
        Execute a compilation command and handle errors.

        Parameters
        ----------
        cmd : list of str
            The command to execute as a list of arguments.

        Raises
        ------
        CompilationError
            If the command returns a non-zero exit code.
        """
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=300  # 5-minute timeout for large compilations
            )
        except subprocess.CalledProcessError as e:
            raise CompilationError(
                f"Compilation failed with {self.name}:\n{e.stderr}",
                compiler_output=e.stderr
            ) from e
        except subprocess.TimeoutExpired as e:
            raise CompilationError(
                f"Compilation timed out after 300 seconds with {self.name}",
                compiler_output=e.stderr if e.stderr else None
            ) from e


class GccCompiler(Compiler):
    """
    GCC-compatible compiler (gcc, clang in gcc-compatible mode).

    This class supports GCC and any compiler that accepts GCC-style command-line
    options (e.g., ``-shared``, ``-fPIC``, ``-I``, ``-D``, ``-l``). It is the
    default for Unix-like systems.

    Parameters
    ----------
    executable : str, default "gcc"
        Path or name of the GCC-compatible executable.

    Examples
    --------
    >>> from pathlib import Path
    >>> gcc = GccCompiler()
    >>> gcc.compile_shared_library(
    ...     source=Path("add.c"),
    ...     output=Path("add.so"),
    ...     cflags=["-O2"],
    ...     libraries=["m"]
    ... )
    """

    def __init__(self, executable: str = "gcc"):
        """
        Initialize a GCC compiler.

        Parameters
        ----------
        executable : str, default "gcc"
            Path or name of the GCC-compatible executable.
        """
        super().__init__("gcc", executable)

    def compile_shared_library(
        self,
        source: Path,
        output: Path,
        cflags: Optional[List[str]] = None,
        includes: Optional[List[str]] = None,
        defines: Optional[Dict[str, Optional[str]]] = None,
        libraries: Optional[List[str]] = None,
        link_args: Optional[List[str]] = None,
    ) -> None:
        """
        Compile using GCC-style command line.

        The command is built as::

            {executable} -shared -fPIC {cflags} {includes} {defines}
            {link_args} {libraries} {source} -o {output}

        Parameters
        ----------
        source : Path
            Path to the C source file.
        output : Path
            Output path for the shared library.
        cflags : list of str, optional
            Compiler flags.
        includes : list of str, optional
            Include directories (prepended with ``-I``).
        defines : dict, optional
            Macro definitions (prepended with ``-D``).
        libraries : list of str, optional
            Library names (prepended with ``-l``).
        link_args : list of str, optional
            Additional linker flags.

        Raises
        ------
        CompilationError
            If compilation fails.
        """
        cmd = [self.executable, "-shared", "-fPIC"]

        if cflags:
            cmd.extend(cflags)

        if includes:
            for inc in includes:
                cmd.extend(["-I", str(inc)])

        if defines:
            for macro, value in defines.items():
                if value is None:
                    cmd.append(f"-D{macro}")
                else:
                    cmd.append(f"-D{macro}={value}")

        if link_args:
            cmd.extend(link_args)

        cmd.append(str(source))

        if libraries:
            for lib in libraries:
                cmd.extend(["-l", lib])

        cmd.extend(["-o", str(output)])

        self._run_command(cmd)


class ClangCompiler(GccCompiler):
    """
    Clang compiler (LLVM's C frontend).

    Clang is largely command-line compatible with GCC, so this class inherits
    from :class:`GccCompiler` and only overrides the default executable name.

    Parameters
    ----------
    executable : str, default "clang"
        Path or name of the clang executable.

    Examples
    --------
    >>> from pathlib import Path
    >>> clang = ClangCompiler()
    >>> clang.compile_shared_library(
    ...     source=Path("add.c"),
    ...     output=Path("add.so"),
    ...     cflags=["-O2", "-Wall"]
    ... )
    """

    def __init__(self, executable: str = "clang"):
        """
        Initialize a Clang compiler.

        Parameters
        ----------
        executable : str, default "clang"
            Path or name of the clang executable.
        """
        super().__init__("clang", executable)


class MsvcCompiler(Compiler):
    """
    Microsoft Visual C++ compiler (MSVC).

    This class supports the MSVC toolchain, typically invoked via ``cl.exe``.
    It uses MSVC-style flags: ``/LD`` for shared library, ``/I`` for includes,
    ``/D`` for defines, and expects library names without the ``.lib`` suffix.

    Parameters
    ----------
    executable : str, default "cl"
        Path or name of the MSVC compiler driver.

    Examples
    --------
    >>> from pathlib import Path
    >>> msvc = MsvcCompiler()
    >>> msvc.compile_shared_library(
    ...     source=Path("add.c"),
    ...     output=Path("add.dll"),
    ...     cflags=["/O2"],
    ...     libraries=["kernel32", "user32"]
    ... )

    Notes
    -----
    Ensure that the Visual C++ environment is properly set up (e.g., by running
    ``vcvarsall.bat``) or provide the full path to ``cl.exe``.
    """

    def __init__(self, executable: str = "cl"):
        """
        Initialize an MSVC compiler.

        Parameters
        ----------
        executable : str, default "cl"
            Path or name of the MSVC compiler driver.
        """
        super().__init__("msvc", executable)

    def compile_shared_library(
        self,
        source: Path,
        output: Path,
        cflags: Optional[List[str]] = None,
        includes: Optional[List[str]] = None,
        defines: Optional[Dict[str, Optional[str]]] = None,
        libraries: Optional[List[str]] = None,
        link_args: Optional[List[str]] = None,
    ) -> None:
        """
        Compile using MSVC-style command line.

        The command is built as::

            {executable} /LD /nologo {cflags} {includes} {defines}
            {link_args} {libraries}.lib {source} /Fe:{output}

        Parameters
        ----------
        source : Path
            Path to the C source file.
        output : Path
            Output path for the shared library (DLL).
        cflags : list of str, optional
            Compiler flags.
        includes : list of str, optional
            Include directories (prepended with ``/I``).
        defines : dict, optional
            Macro definitions (prepended with ``/D``).
        libraries : list of str, optional
            Library names (appended with ``.lib``).
        link_args : list of str, optional
            Additional linker flags.

        Raises
        ------
        CompilationError
            If compilation fails.

        Notes
        -----
        - ``/LD`` creates a DLL.
        - ``/Fe:`` specifies the output file name.
        - Library names are automatically appended with ``.lib``.
        - For custom library paths, include them in ``link_args`` as
          ``/LIBPATH:path``.
        """
        cmd = [self.executable, "/LD", "/nologo"]

        if cflags:
            cmd.extend(cflags)

        if includes:
            for inc in includes:
                cmd.append(f"/I{inc}")

        if defines:
            for macro, value in defines.items():
                if value is None:
                    cmd.append(f"/D{macro}")
                else:
                    cmd.append(f"/D{macro}={value}")

        if link_args:
            cmd.extend(link_args)

        cmd.append(str(source))

        if libraries:
            for lib in libraries:
                cmd.append(f"{lib}.lib")

        cmd.append(f"/Fe:{output}")

        self._run_command(cmd)


def detect_compiler(preferred: Optional[str] = None) -> Compiler:
    """
    Detect an available C compiler on the system.

    This function searches for known compilers (GCC, Clang, MSVC) by checking
    if their executables are present in the system PATH. The detection order
    can be influenced by the ``preferred`` argument.

    Parameters
    ----------
    preferred : str, optional
        Name of the preferred compiler. Valid values:
            - ``'gcc'`` - GCC compiler
            - ``'clang'`` - Clang compiler
            - ``'msvc'`` or ``'cl'`` - Microsoft Visual C++

        If the preferred compiler is not available, the function falls back
        to auto-detection and may return a different compiler. A warning is
        issued if the preferred compiler is missing.

    Returns
    -------
    Compiler
        An instance of a concrete compiler subclass.

    Raises
    ------
    CompilerNotFoundError
        If no supported compiler is detected on the system.

    Examples
    --------
    Auto-detect any available compiler:

    >>> compiler = detect_compiler()
    >>> print(f"Using {compiler.name}")

    Prefer Clang, but accept GCC if Clang is not available:

    >>> compiler = detect_compiler(preferred="clang")

    On Windows, prefer MSVC:

    >>> compiler = detect_compiler(preferred="msvc")
    """
    # Map preferred names to canonical names
    preferred_canonical: Optional[str] = None
    if preferred:
        preferred_lower = preferred.lower()
        if preferred_lower in ("gcc",):
            preferred_canonical = "gcc"
        elif preferred_lower in ("clang",):
            preferred_canonical = "clang"
        elif preferred_lower in ("msvc", "cl"):
            preferred_canonical = "msvc"

    # Define compiler classes and their executables in priority order
    compiler_specs: List[tuple] = [
        ("gcc", GccCompiler, "gcc"),
        ("clang", ClangCompiler, "clang"),
    ]

    if PlatformInfo.is_windows():
        compiler_specs.append(("msvc", MsvcCompiler, "cl"))

    # If preferred is specified, try it first
    if preferred_canonical:
        for name, cls, exe in compiler_specs:
            if name == preferred_canonical and shutil.which(exe):
                return cls(exe)
        warnings.warn(
            f"Preferred compiler '{preferred}' not available. Falling back to auto-detection.",
            UserWarning,
            stacklevel=2
        )

    # Auto-detect: try each compiler in order
    for name, cls, exe in compiler_specs:
        if shutil.which(exe):
            return cls(exe)

    # No compiler found
    raise CompilerNotFoundError(
        "No C compiler found on the system. "
        "Please install GCC, Clang, or MSVC and ensure it is in your PATH.",
        preferred=preferred
    )


def get_compiler_version(compiler: Compiler) -> Optional[str]:
    """
    Attempt to get the version string of a compiler.

    Parameters
    ----------
    compiler : Compiler
        The compiler instance to query.

    Returns
    -------
    str or None
        The version string if successfully retrieved, else None.

    Examples
    --------
    >>> compiler = detect_compiler()
    >>> version = get_compiler_version(compiler)
    >>> if version:
    ...     print(f"{compiler.name} version: {version}")
    """
    version_flags = {
        "gcc": ["--version"],
        "clang": ["--version"],
        "msvc": [],  # MSVC doesn't have a simple version flag
    }

    flag = version_flags.get(compiler.name)
    if not flag:
        return None

    try:
        result = subprocess.run(
            [compiler.executable] + flag,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout.split('\n')[0].strip()
    except (subprocess.SubprocessError, OSError):
        return None