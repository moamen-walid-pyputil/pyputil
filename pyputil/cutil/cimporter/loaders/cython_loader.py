#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    CYTHON MODULE LOADER
==================================

Advanced Cython module loader with automatic compilation,
dependency resolution, parallel processing, and hot reloading.
"""

import ast
import importlib.util
import os
import pickle
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# Import base components
from .base import (
    BaseLoader,
    LoaderConfig,
    LoaderState,
    LoaderEventType,
    ModuleMetadata,
    ModuleOrigin,
    ModuleProxy,
    BatchLoader,
)
from ..core.exceptions import (
    CompileError,
    ImportModuleError,
    DependencyError,
    ConfigError,
    ErrorCategory,
    ErrorSeverity,
)
from ..core.enums import (
    OptimizationLevel,
    BuildMode,
    CacheStrategy,
    ParallelStrategy,
    LogLevel,
    DependencyType,
    LanguageStandard,
)
from ..core.cache import CacheKey, CacheKeyBuilder, CacheManager


class CythonDirective(Enum):
    """
    Cython compiler directives enumeration.

    These directives control Cython's code generation and optimization
    behavior. Each directive maps to a specific Cython compiler setting.

    Attributes
    ----------
    BOUNDSCHECK : str
        Enable/disable array bounds checking.
    WRAPAROUND : str
        Enable/disable negative index wrapping.
    INITIALIZEDCHECK : str
        Enable/disable checks for uninitialized variables.
    NONECHECK : str
        Enable/disable None value checking.
    OVERFLOWCHECK : str
        Enable/disable overflow checking.
    CP_DIVISION : str
        Use C division semantics (truncates toward zero).
    C_DIVISION : str
        Alias for c_division.
    EMBEDSIGNATURE : str
        Embed function signatures in docstrings.
    FAST_FAIL : str
        Enable fast failure on errors.
    PROFILE : str
        Enable profiling support.
    LINETRACE : str
        Enable line tracing for coverage.
    INFER_TYPES : str
        Enable type inference.
    LANGUAGE_LEVEL : str
        Python language level to target.
    LEGACY_IMPORTS : str
        Use legacy import behavior.
    """

    BOUNDSCHECK = "boundscheck"
    WRAPAROUND = "wraparound"
    INITIALIZEDCHECK = "initializedcheck"
    NONECHECK = "nonecheck"
    OVERFLOWCHECK = "overflowcheck"
    CP_DIVISION = "cdivision"
    C_DIVISION = "cdivision"
    EMBEDSIGNATURE = "embedsignature"
    FAST_FAIL = "fast_fail"
    PROFILE = "profile"
    LINETRACE = "linetrace"
    INFER_TYPES = "infer_types"
    LANGUAGE_LEVEL = "language_level"
    LEGACY_IMPORTS = "legacy_imports"


class CythonBackend(Enum):
    """
    Cython compilation backend enumeration.

    Attributes
    ----------
    CYTHON : str
        Standard Cython compiler (generates C code).
    CYTHONIZE : str
        Cythonize utility (simplified compilation).
    PYXIMPORT : str
        Pyximport on-the-fly compilation.
    CYTHON_INLINE : str
        Inline Cython compilation.
    """

    CYTHON = "cython"
    CYTHONIZE = "cythonize"
    PYXIMPORT = "pyximport"
    CYTHON_INLINE = "cython_inline"


@dataclass
class CythonConfig:
    """
    Configuration for Cython compilation.

    Parameters
    ----------
    backend : CythonBackend
        Compilation backend to use.
    language_level : Union[int, str]
        Python language level (2, 3, '3str', etc.).
    directives : Dict[CythonDirective, Any]
        Cython compiler directives.
    extra_compile_args : List[str]
        Additional C compiler arguments.
    extra_link_args : List[str]
        Additional linker arguments.
    include_dirs : List[Path]
        Cython include directories.
    library_dirs : List[Path]
        Library search directories.
    libraries : List[str]
        Libraries to link against.
    define_macros : Dict[str, str]
        Preprocessor macro definitions.
    undef_macros : List[str]
        Macros to undefine.
    force_rebuild : bool
        Force rebuild even if up-to-date.
    keep_intermediates : bool
        Keep intermediate .c files.
    annotate : bool
        Generate HTML annotation file.
    annotate_html : bool
        Generate detailed HTML annotation.
    annotate_coverage : bool
        Include coverage in annotation.
    gdb_debug : bool
        Generate GDB debug information.
    no_docstrings : bool
        Strip docstrings from generated code.
    optimize_interned_strings : bool
        Optimize string interning.
    fast_fail : bool
        Enable fast failure mode.
    warning_errors : bool
        Treat warnings as errors.
    show_all_warnings : bool
        Show all compilation warnings.
    c_line_in_traceback : bool
        Show C line numbers in tracebacks.
    emit_linenums : bool
        Emit line number information.

    Attributes
    ----------
    backend : CythonBackend
        Compilation backend.
    language_level : Union[int, str]
        Language level.
    directives : Dict[CythonDirective, Any]
        Compiler directives.
    extra_compile_args : List[str]
        Extra compile args.
    extra_link_args : List[str]
        Extra link args.
    include_dirs : List[Path]
        Include directories.
    library_dirs : List[Path]
        Library directories.
    libraries : List[str]
        Libraries.
    define_macros : Dict[str, str]
        Macro definitions.
    undef_macros : List[str]
        Undefined macros.
    force_rebuild : bool
        Force rebuild flag.
    keep_intermediates : bool
        Keep intermediates flag.
    annotate : bool
        Annotation flag.
    annotate_html : bool
        HTML annotation flag.
    annotate_coverage : bool
        Coverage annotation flag.
    gdb_debug : bool
        GDB debug flag.
    no_docstrings : bool
        Strip docstrings flag.
    optimize_interned_strings : bool
        Optimize strings flag.
    fast_fail : bool
        Fast fail flag.
    warning_errors : bool
        Warnings as errors flag.
    show_all_warnings : bool
        Show all warnings flag.
    c_line_in_traceback : bool
        C line numbers flag.
    emit_linenums : bool
        Emit line numbers flag.

    Examples
    --------
    >>> config = CythonConfig(
    ...     language_level=3,
    ...     directives={
    ...         CythonDirective.BOUNDSCHECK: False,
    ...         CythonDirective.WRAPAROUND: False,
    ...         CythonDirective.EMBEDSIGNATURE: True
    ...     },
    ...     annotate=True,
    ...     extra_compile_args=["-O3", "-march=native"]
    ... )
    """

    # Backend selection
    backend: CythonBackend = CythonBackend.CYTHON

    # Language settings
    language_level: Union[int, str] = 3

    # Directives
    directives: Dict[CythonDirective, Any] = field(default_factory=dict)

    # Compilation flags
    extra_compile_args: List[str] = field(default_factory=list)
    extra_link_args: List[str] = field(default_factory=list)
    include_dirs: List[Path] = field(default_factory=list)
    library_dirs: List[Path] = field(default_factory=list)
    libraries: List[str] = field(default_factory=list)
    define_macros: Dict[str, str] = field(default_factory=dict)
    undef_macros: List[str] = field(default_factory=list)

    # Build control
    force_rebuild: bool = False
    keep_intermediates: bool = False

    # Annotation
    annotate: bool = False
    annotate_html: bool = False
    annotate_coverage: bool = False

    # Debugging
    gdb_debug: bool = False
    no_docstrings: bool = False
    optimize_interned_strings: bool = True

    # Error handling
    fast_fail: bool = True
    warning_errors: bool = False
    show_all_warnings: bool = False
    c_line_in_traceback: bool = True
    emit_linenums: bool = True

    def to_cython_args(self) -> List[str]:
        """
        Convert configuration to Cython command-line arguments.

        Returns
        -------
        List[str]
            List of command-line arguments for cython command.
        """
        args = []

        # Language level
        if self.language_level is not None:
            args.extend([f"-{self.language_level}"])

        # Directives
        for directive, value in self.directives.items():
            if isinstance(value, bool):
                value_str = "True" if value else "False"
            else:
                value_str = str(value)
            args.extend(["-X", f"{directive.value}={value_str}"])

        # Annotation
        if self.annotate:
            args.append("--annotate")
        if self.annotate_html:
            args.append("--annotate-fullc")
        if self.annotate_coverage:
            args.append("--annotate-coverage")

        # Debugging
        if self.gdb_debug:
            args.append("--gdb")
        if self.no_docstrings:
            args.append("--no-docstrings")
        if self.c_line_in_traceback:
            args.append("--c-line-in-traceback")
        if self.emit_linenums:
            args.append("--embed-positions")

        # Warnings
        if self.warning_errors:
            args.append("-Werror")
        if self.show_all_warnings:
            args.append("-Wall")

        # Optimization
        if self.optimize_interned_strings:
            args.append("--fast-fail" if self.fast_fail else "")

        return [arg for arg in args if arg]

    def to_setup_args(self) -> Dict[str, Any]:
        """
        Convert configuration to setuptools/distutils arguments.

        Returns
        -------
        Dict[str, Any]
            Dictionary of arguments for cythonize() or Extension().
        """
        args = {
            "language_level": self.language_level,
            "extra_compile_args": self.extra_compile_args,
            "extra_link_args": self.extra_link_args,
            "include_dirs": [str(p) for p in self.include_dirs],
            "library_dirs": [str(p) for p in self.library_dirs],
            "libraries": self.libraries,
            "define_macros": list(self.define_macros.items()),
            "undef_macros": self.undef_macros,
        }

        # Convert directives to compiler_directives format
        if self.directives:
            args["compiler_directives"] = {
                k.value: v for k, v in self.directives.items()
            }

        # Add cythonize-specific options
        if self.annotate:
            args["annotate"] = True

        return args


class CythonDependencyParser:
    """
    Advanced Cython dependency parser.

    This class analyzes .pyx and .pxd files to extract:
    - Import dependencies (cimport, import, from ... import)
    - Include dependencies (include statements)
    - Type dependencies (ctypedef, cdef class inheritance)
    - Conditional dependencies (platform-specific imports)

    Parameters
    ----------
    source_path : Path
        Path to the Cython source file.

    Attributes
    ----------
    source_path : Path
        Source file path.
    _imports : Set[str]
        Detected import dependencies.
    _cimports : Set[str]
        Detected cimport dependencies.
    _includes : Set[str]
        Detected include dependencies.
    _types : Set[str]
        Detected type dependencies.
    _conditionals : Dict[str, Set[str]]
        Conditional dependencies by platform.

    Examples
    --------
    >>> parser = CythonDependencyParser(Path("module.pyx"))
    >>> deps = parser.parse()
    >>> print(f"Imports: {parser.imports}")
    >>> print(f"C-Imports: {parser.cimports}")
    >>> print(f"Includes: {parser.includes}")
    """

    def __init__(self, source_path: Path):
        self.source_path = Path(source_path)
        self._imports: Set[str] = set()
        self._cimports: Set[str] = set()
        self._includes: Set[str] = set()
        self._types: Set[str] = set()
        self._conditionals: Dict[str, Set[str]] = {}
        self._parsed = False

    @property
    def imports(self) -> Set[str]:
        """Get Python import dependencies."""
        self._ensure_parsed()
        return self._imports

    @property
    def cimports(self) -> Set[str]:
        """Get C-import dependencies."""
        self._ensure_parsed()
        return self._cimports

    @property
    def includes(self) -> Set[str]:
        """Get include file dependencies."""
        self._ensure_parsed()
        return self._includes

    @property
    def types(self) -> Set[str]:
        """Get type dependencies."""
        self._ensure_parsed()
        return self._types

    @property
    def all_dependencies(self) -> Set[str]:
        """Get all dependencies combined."""
        self._ensure_parsed()
        return self._imports | self._cimports | self._includes | self._types

    def _ensure_parsed(self) -> None:
        """Ensure the file has been parsed."""
        if not self._parsed:
            self.parse()

    def parse(self) -> Dict[str, Set[str]]:
        """
        Parse the Cython file and extract all dependencies.

        Returns
        -------
        Dict[str, Set[str]]
            Dictionary with keys: 'imports', 'cimports', 'includes', 'types'
            and their corresponding dependencies.
        """
        if not self.source_path.exists():
            return {}

        try:
            with open(self.source_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Parse using multiple strategies
            self._parse_imports(content)
            self._parse_cimports(content)
            self._parse_includes(content)
            self._parse_type_dependencies(content)
            self._parse_conditional_imports(content)

            self._parsed = True

            return {
                "imports": self._imports,
                "cimports": self._cimports,
                "includes": self._includes,
                "types": self._types,
                "conditionals": {
                    k: list(v) for k, v in self._conditionals.items()
                },
            }

        except Exception as e:
            # Log but don't fail - dependency parsing is best-effort
            import logging
            logging.getLogger(__name__).debug(f"Dependency parsing failed: {e}")
            return {}

    def _parse_imports(self, content: str) -> None:
        """
        Parse Python import statements.

        Parameters
        ----------
        content : str
            Source file content.
        """
        # Pattern for: import module
        pattern1 = re.compile(r"^\s*import\s+(\w+(?:\s*,\s*\w+)*)", re.MULTILINE)

        # Pattern for: from module import something
        pattern2 = re.compile(r"^\s*from\s+(\w+)\s+import", re.MULTILINE)

        # Pattern for: import module as alias
        pattern3 = re.compile(r"^\s*import\s+(\w+)\s+as\s+\w+", re.MULTILINE)

        for match in pattern1.finditer(content):
            modules = match.group(1).split(",")
            for mod in modules:
                self._imports.add(mod.strip())

        for match in pattern2.finditer(content):
            self._imports.add(match.group(1))

        for match in pattern3.finditer(content):
            self._imports.add(match.group(1))

        # Filter out relative imports (starting with .)
        self._imports = {imp for imp in self._imports if not imp.startswith(".")}

    def _parse_cimports(self, content: str) -> None:
        """
        Parse Cython cimport statements.

        Parameters
        ----------
        content : str
            Source file content.
        """
        # Pattern for: cimport module
        pattern1 = re.compile(r"^\s*cimport\s+(\w+(?:\s*,\s*\w+)*)", re.MULTILINE)

        # Pattern for: from module cimport something
        pattern2 = re.compile(r"^\s*from\s+(\w+)\s+cimport", re.MULTILINE)

        for match in pattern1.finditer(content):
            modules = match.group(1).split(",")
            for mod in modules:
                self._cimports.add(mod.strip())

        for match in pattern2.finditer(content):
            self._cimports.add(match.group(1))

    def _parse_includes(self, content: str) -> None:
        """
        Parse Cython include statements.

        Parameters
        ----------
        content : str
            Source file content.
        """
        # Pattern for: include "file.pxi"
        pattern = re.compile(r'^\s*include\s+["\']([^"\']+)["\']', re.MULTILINE)

        for match in pattern.finditer(content):
            include_file = match.group(1)
            self._includes.add(include_file)

    def _parse_type_dependencies(self, content: str) -> None:
        """
        Parse type-related dependencies.

        Parameters
        ----------
        content : str
            Source file content.
        """
        # Pattern for: cdef class ClassName(BaseClass)
        pattern1 = re.compile(r"cdef\s+class\s+\w+\s*\(([^)]+)\)", re.MULTILINE)

        # Pattern for: ctypedef something
        pattern2 = re.compile(r"ctypedef\s+.*?\s+(\w+)\s*$", re.MULTILINE)

        for match in pattern1.finditer(content):
            bases = match.group(1).split(",")
            for base in bases:
                base = base.strip()
                if base and not base.startswith("object"):
                    self._types.add(base)

        for match in pattern2.finditer(content):
            type_name = match.group(1)
            if type_name and not type_name[0].islower():
                self._types.add(type_name)

    def _parse_conditional_imports(self, content: str) -> None:
        """
        Parse platform-conditional imports.

        Parameters
        ----------
        content : str
            Source file content.
        """
        # Look for IF/ELSE blocks
        pattern = re.compile(
            r"IF\s+(\w+):\s*\n(.*?)(?:ELSE:|ELIF|\n\n)",
            re.MULTILINE | re.DOTALL,
        )

        for match in pattern.finditer(content):
            condition = match.group(1)
            block = match.group(2)

            # Parse imports within the conditional block
            block_parser = CythonDependencyParser.__new__(CythonDependencyParser)
            block_parser._imports = set()
            block_parser._cimports = set()
            block_parser._parse_imports(block)
            block_parser._parse_cimports(block)

            if condition not in self._conditionals:
                self._conditionals[condition] = set()

            self._conditionals[condition].update(block_parser._imports)
            self._conditionals[condition].update(block_parser._cimports)

    def get_dependency_tree(self) -> Dict[str, Any]:
        """
        Build a dependency tree structure.

        Returns
        -------
        Dict[str, Any]
            Tree structure of dependencies.
        """
        self._ensure_parsed()

        return {
            "source": str(self.source_path),
            "python_imports": list(self._imports),
            "c_imports": list(self._cimports),
            "includes": list(self._includes),
            "type_dependencies": list(self._types),
            "conditional": {
                cond: list(deps) for cond, deps in self._conditionals.items()
            },
            "total_dependencies": len(self.all_dependencies),
        }


class CythonCompiler:
    """
    Cython compilation engine with multiple backend support.

    This class handles the actual compilation of .pyx files to
    Python extension modules using various backends.

    Parameters
    ----------
    config : CythonConfig
        Cython configuration.
    cache_manager : Optional[CacheManager]
        Cache manager instance.
    verbose : bool
        Whether to show verbose output.

    Attributes
    ----------
    config : CythonConfig
        Configuration.
    cache_manager : Optional[CacheManager]
        Cache manager.
    verbose : bool
        Verbose flag.
    _temp_dir : Optional[Path]
        Temporary directory for compilation.
    _lock : threading.RLock
        Thread lock for compilation.

    Examples
    --------
    >>> config = CythonConfig(annotate=True)
    >>> compiler = CythonCompiler(config, verbose=True)
    >>> output = compiler.compile(Path("module.pyx"), Path("module.so"))
    """

    def __init__(
        self,
        config: CythonConfig,
        cache_manager: Optional[CacheManager] = None,
        verbose: bool = False,
    ):
        self.config = config
        self.cache_manager = cache_manager
        self.verbose = verbose
        self._temp_dir: Optional[Path] = None
        self._lock = threading.RLock()

    def compile(
        self,
        source_path: Path,
        output_path: Path,
        force: bool = False,
    ) -> Tuple[bool, float, Optional[str]]:
        """
        Compile a Cython source file.

        Parameters
        ----------
        source_path : Path
            Path to .pyx source file.
        output_path : Path
            Path for output extension module.
        force : bool, optional
            Force recompilation.

        Returns
        -------
        Tuple[bool, float, Optional[str]]
            Tuple of (success, compile_time, error_message).
        """
        start_time = time.time()

        with self._lock:
            try:
                if self.config.backend == CythonBackend.CYTHON:
                    success = self._compile_with_cython(source_path, output_path, force)
                elif self.config.backend == CythonBackend.CYTHONIZE:
                    success = self._compile_with_cythonize(source_path, output_path)
                elif self.config.backend == CythonBackend.PYXIMPORT:
                    success = self._compile_with_pyximport(source_path, output_path)
                else:
                    raise ConfigError(
                        config_key="backend",
                        message=f"Unsupported backend: {self.config.backend}",
                    )

                compile_time = time.time() - start_time

                if success and output_path.exists():
                    return True, compile_time, None
                else:
                    return False, compile_time, "Compilation failed"

            except Exception as e:
                compile_time = time.time() - start_time
                return False, compile_time, str(e)

    def _compile_with_cython(
        self,
        source_path: Path,
        output_path: Path,
        force: bool = False,
    ) -> bool:
        """
        Compile using the cython command-line tool.

        Parameters
        ----------
        source_path : Path
            Source file.
        output_path : Path
            Output file.
        force : bool
            Force recompilation.

        Returns
        -------
        bool
            True if compilation succeeded.
        """
        # Check if up-to-date
        if not force and not self.config.force_rebuild:
            if self._is_up_to_date(source_path, output_path):
                return True

        # Create temporary directory for intermediate files
        with tempfile.TemporaryDirectory(prefix="cython_") as temp_dir:
            temp_path = Path(temp_dir)

            # Step 1: Generate C code
            c_file = temp_path / f"{source_path.stem}.c"
            cython_args = self._build_cython_command(source_path, c_file)

            if self.verbose:
                print(f"[Cython] {' '.join(cython_args)}")

            result = subprocess.run(
                cython_args,
                capture_output=not self.verbose,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                raise CompileError(
                    compiler="cython",
                    message="Cython compilation failed",
                    source_file=source_path,
                    stderr=result.stderr,
                )

            if not c_file.exists():
                raise CompileError(
                    compiler="cython",
                    message="C file not generated",
                    source_file=source_path,
                )

            # Step 2: Compile C code to extension module
            success = self._compile_c_code(c_file, output_path)

            # Generate annotation if requested
            if self.config.annotate:
                html_file = source_path.with_suffix(".html")
                if html_file.exists():
                    # Move to appropriate location
                    pass

            return success

    def _compile_with_cythonize(
        self,
        source_path: Path,
        output_path: Path,
    ) -> bool:
        """
        Compile using cythonize utility.

        Parameters
        ----------
        source_path : Path
            Source file.
        output_path : Path
            Output file.

        Returns
        -------
        bool
            True if compilation succeeded.
        """
        try:
            from Cython.Build import cythonize
            from setuptools import Extension
            from distutils.core import setup
        except ImportError as e:
            raise CompileError(
                compiler="cythonize",
                message=f"Cython/setuptools not available: {e}",
                source_file=source_path,
            )

        # Build extension
        ext_args = self.config.to_setup_args()
        ext_args["name"] = source_path.stem
        ext_args["sources"] = [str(source_path)]

        extension = Extension(**ext_args)

        # Build in temporary directory
        with tempfile.TemporaryDirectory(prefix="cythonize_") as temp_dir:
            # Save current directory
            old_cwd = os.getcwd()

            try:
                os.chdir(temp_dir)

                # Run cythonize
                cythonize(
                    [extension],
                    force=self.config.force_rebuild,
                    quiet=not self.verbose,
                    **{k: v for k, v in ext_args.items() if k in ("annotate",)},
                )

                # Find and copy output
                build_lib = Path(temp_dir) / "build" / "lib" / "lib." + sys.platform
                for ext in self._get_platform_extensions():
                    candidate = build_lib / f"{source_path.stem}{ext}"
                    if candidate.exists():
                        shutil.copy2(candidate, output_path)
                        return True

            finally:
                os.chdir(old_cwd)

        return False

    def _compile_with_pyximport(
        self,
        source_path: Path,
        output_path: Path,
    ) -> bool:
        """
        Compile using pyximport.

        Parameters
        ----------
        source_path : Path
            Source file.
        output_path : Path
            Output file.

        Returns
        -------
        bool
            True if compilation succeeded.
        """
        try:
            import pyximport
        except ImportError as e:
            raise CompileError(
                compiler="pyximport",
                message=f"pyximport not available: {e}",
                source_file=source_path,
            )

        # Configure pyximport
        pyximport.install(
            build_dir=str(output_path.parent),
            inplace=True,
            language_level=self.config.language_level,
        )

        # Import will trigger compilation
        try:
            sys.path.insert(0, str(source_path.parent))
            module_name = source_path.stem
            __import__(module_name)
            sys.path.pop(0)

            # Find compiled module
            for ext in self._get_platform_extensions():
                candidate = output_path.parent / f"{module_name}{ext}"
                if candidate.exists():
                    if candidate != output_path:
                        shutil.copy2(candidate, output_path)
                    return True

        except Exception as e:
            raise CompileError(
                compiler="pyximport",
                message=str(e),
                source_file=source_path,
            )

        return False

    def _build_cython_command(self, source_path: Path, output_path: Path) -> List[str]:
        """
        Build cython command-line arguments.

        Parameters
        ----------
        source_path : Path
            Source file.
        output_path : Path
            Output C file.

        Returns
        -------
        List[str]
            Command arguments.
        """
        cmd = [sys.executable, "-m", "cython"]

        # Add configuration arguments
        cmd.extend(self.config.to_cython_args())

        # Add output file
        cmd.extend(["-o", str(output_path)])

        # Add source file
        cmd.append(str(source_path))

        return cmd

    def _compile_c_code(self, c_file: Path, output_path: Path) -> bool:
        """
        Compile generated C code to extension module.

        Parameters
        ----------
        c_file : Path
            C source file.
        output_path : Path
            Output extension module.

        Returns
        -------
        bool
            True if compilation succeeded.
        """
        # Get Python compilation flags
        python_includes = self._get_python_includes()
        python_libs = self._get_python_libs()

        # Build compiler command
        if sys.platform == "win32":
            cmd = self._build_msvc_command(c_file, output_path, python_includes, python_libs)
        else:
            cmd = self._build_gcc_command(c_file, output_path, python_includes, python_libs)

        if self.verbose:
            print(f"[CC] {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=not self.verbose,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            raise CompileError(
                compiler="gcc" if sys.platform != "win32" else "cl",
                message="C compilation failed",
                source_file=c_file,
                stderr=result.stderr,
            )

        return output_path.exists()

    def _build_gcc_command(
        self,
        c_file: Path,
        output_path: Path,
        includes: List[Path],
        libs: List[Path],
    ) -> List[str]:
        """
        Build GCC/Clang compilation command.

        Parameters
        ----------
        c_file : Path
            C source file.
        output_path : Path
            Output file.
        includes : List[Path]
            Include directories.
        libs : List[Path]
            Library directories.

        Returns
        -------
        List[str]
            Compilation command.
        """
        cmd = ["gcc"]

        # Shared library
        cmd.append("-shared")
        cmd.append("-fPIC")

        # Optimization
        cmd.append("-O3")

        # Python includes
        for inc in includes:
            cmd.extend(["-I", str(inc)])

        # Extra compile args
        cmd.extend(self.config.extra_compile_args)

        # Source file
        cmd.append(str(c_file))

        # Output
        cmd.extend(["-o", str(output_path)])

        # Libraries
        for lib in libs:
            cmd.extend(["-L", str(lib)])
        cmd.extend(["-lpython" + sys.version[:3]])

        # Extra link args
        cmd.extend(self.config.extra_link_args)

        return cmd

    def _build_msvc_command(
        self,
        c_file: Path,
        output_path: Path,
        includes: List[Path],
        libs: List[Path],
    ) -> List[str]:
        """
        Build MSVC compilation command.

        Parameters
        ----------
        c_file : Path
            C source file.
        output_path : Path
            Output file.
        includes : List[Path]
            Include directories.
        libs : List[Path]
            Library directories.

        Returns
        -------
        List[str]
            Compilation command.
        """
        cmd = ["cl"]

        # DLL
        cmd.append("/LD")

        # Python includes
        for inc in includes:
            cmd.extend(["/I", str(inc)])

        # Extra compile args
        cmd.extend(self.config.extra_compile_args)

        # Source file
        cmd.append(str(c_file))

        # Output
        cmd.append(f"/Fe{output_path}")

        # Libraries
        for lib in libs:
            cmd.extend(["/LIBPATH:", str(lib)])

        python_lib = f"python{sys.version_info.major}{sys.version_info.minor}"
        cmd.append(f"{python_lib}.lib")

        # Extra link args
        cmd.extend(self.config.extra_link_args)

        return cmd

    def _get_python_includes(self) -> List[Path]:
        """
        Get Python include directories.

        Returns
        -------
        List[Path]
            List of include paths.
        """
        import sysconfig

        includes = []

        try:
            include_dir = sysconfig.get_path("include")
            if include_dir:
                includes.append(Path(include_dir))
        except Exception:
            pass

        # Fallback
        includes.append(Path(sys.prefix) / "include" / f"python{sys.version[:3]}")

        return [p for p in includes if p.exists()]

    def _get_python_libs(self) -> List[Path]:
        """
        Get Python library directories.

        Returns
        -------
        List[Path]
            List of library paths.
        """
        import sysconfig

        libs = []

        try:
            lib_dir = sysconfig.get_config_var("LIBDIR")
            if lib_dir:
                libs.append(Path(lib_dir))
        except Exception:
            pass

        # Fallback
        libs.append(Path(sys.prefix) / "lib")
        libs.append(Path(sys.prefix) / "libs")  # Windows

        return [p for p in libs if p.exists()]

    def _get_platform_extensions(self) -> List[str]:
        """
        Get platform-specific extension module suffixes.

        Returns
        -------
        List[str]
            List of possible extensions.
        """
        if sys.platform == "win32":
            return [".pyd", ".dll"]
        elif sys.platform == "darwin":
            return [".so", ".dylib"]
        else:
            return [".so"]

    def _is_up_to_date(self, source_path: Path, output_path: Path) -> bool:
        """
        Check if output is up-to-date relative to source.

        Parameters
        ----------
        source_path : Path
            Source file.
        output_path : Path
            Output file.

        Returns
        -------
        bool
            True if output is newer than source.
        """
        if not output_path.exists():
            return False

        source_mtime = source_path.stat().st_mtime
        output_mtime = output_path.stat().st_mtime

        # Check .pxd files as well
        pxd_path = source_path.with_suffix(".pxd")
        if pxd_path.exists():
            pxd_mtime = pxd_path.stat().st_mtime
            if pxd_mtime > output_mtime:
                return False

        return output_mtime >= source_mtime


class CythonLoader(BaseLoader):
    """
    Advanced Cython module loader with comprehensive features.

    This class provides a complete solution for loading Cython modules
    with features including:

    - Multiple compilation backends (cython, cythonize, pyximport)
    - Intelligent caching with dependency-aware invalidation
    - Automatic .pxd and .pxi dependency resolution
    - Parallel batch compilation
    - Hot reloading with file watching
    - Annotation generation for optimization
    - Type inference and optimization directives

    Parameters
    ----------
    config : Optional[LoaderConfig]
        Loader configuration.
    cython_config : Optional[CythonConfig]
        Cython-specific configuration.
    cache_manager : Optional[CacheManager]
        Cache manager instance.

    Attributes
    ----------
    cython_config : CythonConfig
        Cython configuration.
    compiler : CythonCompiler
        Cython compiler instance.
    _dependency_cache : Dict[str, Set[str]]
        Cache of parsed dependencies.
    _pxd_registry : Dict[str, Path]
        Registry of .pxd files.
    _watcher : Optional[Any]
        File watcher for hot reloading.

    Examples
    --------
    >>> # Basic usage
    >>> loader = CythonLoader()
    >>> module = loader.load("my_module.pyx")
    >>> result = module.my_function()

    >>> # Advanced configuration
    >>> config = LoaderConfig(
    ...     cache_enabled=True,
    ...     auto_reload=True,
    ...     track_dependencies=True
    ... )
    >>> cython_config = CythonConfig(
    ...     language_level=3,
    ...     directives={
    ...         CythonDirective.BOUNDSCHECK: False,
    ...         CythonDirective.EMBEDSIGNATURE: True
    ...     },
    ...     annotate=True
    ... )
    >>> loader = CythonLoader(
    ...     config=config,
    ...     cython_config=cython_config
    ... )
    >>> module = loader.load("optimized.pyx")

    >>> # Batch loading with dependency resolution
    >>> modules = loader.load_batch(["a.pyx", "b.pyx", "c.pyx"])
    >>> for name, mod in modules.items():
    ...     print(f"Loaded {name}")

    >>> # Hot reloading
    >>> loader.watch("live_module.pyx")
    >>> # Module reloads automatically when .pyx or .pxd changes
    """

    # File extensions
    PYX_EXTENSION = ".pyx"
    PXD_EXTENSION = ".pxd"
    PXI_EXTENSION = ".pxi"

    def __init__(
        self,
        config: Optional[LoaderConfig] = None,
        cython_config: Optional[CythonConfig] = None,
        cache_manager: Optional[CacheManager] = None,
    ):
        super().__init__(config=config, cache_manager=cache_manager)

        self.cython_config = cython_config or CythonConfig()
        self.compiler = CythonCompiler(
            self.cython_config,
            self.cache_manager,
            verbose=self.config.log_level.value >= LogLevel.DEBUG.value,
        )

        # Dependency tracking
        self._dependency_cache: Dict[str, Set[str]] = {}
        self._pxd_registry: Dict[str, Path] = {}

        # File watcher
        self._watcher = None
        if self.config.enable_hot_reload:
            self._setup_watcher()

        # Scan for .pxd files in Python path
        self._scan_pxd_files()

    def _setup_watcher(self) -> None:
        """Setup file watcher for hot reloading."""
        try:
            from ..monitors import FileWatcher
            self._watcher = FileWatcher()
            self._watcher.start()
        except ImportError:
            self.config.enable_hot_reload = False

    def _scan_pxd_files(self) -> None:
        """
        Scan Python path for .pxd definition files.
        """
        for path in sys.path:
            try:
                pxd_dir = Path(path)
                if pxd_dir.exists():
                    for pxd_file in pxd_dir.glob(f"*{self.PXD_EXTENSION}"):
                        self._pxd_registry[pxd_file.stem] = pxd_file
            except (OSError, PermissionError):
                continue

    def load(self, source: Union[str, Path], **kwargs) -> ModuleType:
        """
        Load a Cython module from source.

        Parameters
        ----------
        source : Union[str, Path]
            Path to .pyx source file.
        **kwargs : Any
            Additional options:
            - recompile : bool - Force recompilation.
            - module_name : str - Override module name.
            - force : bool - Alias for recompile.

        Returns
        -------
        ModuleType
            Loaded Python module.

        Raises
        ------
        CompileError
            If compilation fails.
        ImportModuleError
            If loading fails.
        """
        self._check_state(
            LoaderState.INITIALIZED,
            LoaderState.LOADED,
            LoaderState.RELOADING,
        )

        source_path = Path(source).resolve()

        # Handle .pyx extension
        if source_path.suffix != self.PYX_EXTENSION:
            source_path = source_path.with_suffix(self.PYX_EXTENSION)

        if not source_path.exists():
            raise FileNotFoundError(f"Cython source not found: {source_path}")

        recompile = kwargs.get("recompile", kwargs.get("force", False))
        module_name = kwargs.get("module_name") or source_path.stem

        # Check if already loaded
        if not recompile and self.is_loaded(module_name):
            self._trigger_event(LoaderEventType.CACHE_HIT, module_name)
            return self.get_module(module_name)

        self._set_state(LoaderState.LOADING)
        self._trigger_event(LoaderEventType.PRE_LOAD, module_name)

        try:
            with self._module_lock:
                # Parse dependencies
                dependencies = self._parse_dependencies(source_path)

                # Resolve and load dependencies
                if self.config.track_dependencies:
                    for dep in dependencies:
                        if not self.is_loaded(dep):
                            self._resolve_dependency(dep, source_path.parent)

                # Build cache key
                builder = CacheKeyBuilder(source_path)

                # Add .pxd dependencies to cache key
                for dep in dependencies:
                    pxd_path = self._find_pxd_file(dep)
                    if pxd_path:
                        builder.add_dependency(pxd_path)

                cache_key = builder.build(
                    compiler_name="cython",
                    optimization_flags=tuple(self.cython_config.extra_compile_args),
                    simd_level="none",
                    link_type="module",
                )

                # Determine output path
                output_path = self._get_output_path(source_path, cache_key)

                # Check cache
                if not recompile and self.cache_manager:
                    cached = self.cache_manager.get(cache_key)
                    if cached:
                        output_path = cached
                        origin = ModuleOrigin.CACHE
                        compile_time = 0.0
                        self._trigger_event(LoaderEventType.CACHE_HIT, module_name)
                    else:
                        # Compile
                        self._trigger_event(LoaderEventType.CACHE_MISS, module_name)
                        success, compile_time, error = self.compiler.compile(
                            source_path, output_path, force=recompile
                        )

                        if not success:
                            raise CompileError(
                                compiler="cython",
                                message=f"Compilation failed: {error}",
                                source_file=source_path,
                            )

                        origin = ModuleOrigin.SOURCE

                        # Store in cache
                        if self.cache_manager:
                            self.cache_manager.put(cache_key, output_path, compile_time)
                else:
                    # Compile without cache
                    success, compile_time, error = self.compiler.compile(
                        source_path, output_path, force=recompile
                    )

                    if not success:
                        raise CompileError(
                            compiler="cython",
                            message=f"Compilation failed: {error}",
                            source_file=source_path,
                        )

                    origin = ModuleOrigin.SOURCE

                # Load the module
                load_start = time.time()
                module = self._load_module(output_path, module_name)
                load_time = time.time() - load_start

                # Register module
                metadata = ModuleMetadata(
                    name=module_name,
                    source_path=source_path,
                    library_path=output_path,
                    origin=origin,
                    load_time=load_time,
                    compile_time=compile_time,
                    cache_key=cache_key,
                    dependencies=list(dependencies),
                    checksum=builder.compute_source_hash(),
                )

                self._register_module(module_name, module, metadata)

                # Register dependencies
                for dep in dependencies:
                    self.add_dependency(module_name, dep)

                self._set_state(LoaderState.LOADED)
                self._trigger_event(LoaderEventType.POST_LOAD, module_name)

                return module

        except Exception as e:
            self._set_state(LoaderState.FAILED)
            self._stats["error_count"] += 1
            raise

    def _parse_dependencies(self, source_path: Path) -> Set[str]:
        """
        Parse dependencies from a Cython source file.

        Parameters
        ----------
        source_path : Path
            Source file path.

        Returns
        -------
        Set[str]
            Set of dependency module names.
        """
        cache_key = str(source_path)

        if cache_key in self._dependency_cache:
            return self._dependency_cache[cache_key]

        parser = CythonDependencyParser(source_path)
        deps = parser.all_dependencies

        # Cache the result
        self._dependency_cache[cache_key] = deps

        return deps

    def _find_pxd_file(self, module_name: str) -> Optional[Path]:
        """
        Find a .pxd definition file for a module.

        Parameters
        ----------
        module_name : str
            Module name.

        Returns
        -------
        Optional[Path]
            Path to .pxd file or None.
        """
        # Check registry
        if module_name in self._pxd_registry:
            return self._pxd_registry[module_name]

        # Search in common locations
        search_paths = [
            Path.cwd(),
            Path(sys.prefix) / "share" / "cython",
        ]

        for base in search_paths:
            pxd_path = base / f"{module_name}{self.PXD_EXTENSION}"
            if pxd_path.exists():
                self._pxd_registry[module_name] = pxd_path
                return pxd_path

        return None

    def _resolve_dependency(self, module_name: str, search_dir: Path) -> Optional[ModuleType]:
        """
        Resolve and load a dependency.

        Parameters
        ----------
        module_name : str
            Module name.
        search_dir : Path
            Directory to search for the module.

        Returns
        -------
        Optional[ModuleType]
            Loaded module or None.
        """
        # Try to find .pyx file
        pyx_path = search_dir / f"{module_name}{self.PYX_EXTENSION}"
        if pyx_path.exists():
            return self.load(pyx_path)

        # Try to find .pxd file (header only, no compilation needed)
        pxd_path = self._find_pxd_file(module_name)
        if pxd_path:
            # Register as a dependency without loading
            return None

        # Try Python import
        try:
            import importlib
            return importlib.import_module(module_name)
        except ImportError:
            pass

        return None

    def _get_output_path(self, source_path: Path, cache_key: Optional[CacheKey] = None) -> Path:
        """
        Get output path for compiled module.

        Parameters
        ----------
        source_path : Path
            Source file.
        cache_key : Optional[CacheKey]
            Cache key.

        Returns
        -------
        Path
            Output path.
        """
        if cache_key and self.cache_manager:
            return self.cache_manager.backend._get_cache_path(cache_key)

        # Use build directory
        build_dir = source_path.parent / "build"
        build_dir.mkdir(exist_ok=True)

        ext = ".pyd" if sys.platform == "win32" else ".so"
        return build_dir / f"{source_path.stem}{ext}"

    def _load_module(self, library_path: Path, module_name: str) -> ModuleType:
        """
        Load a compiled Cython module.

        Parameters
        ----------
        library_path : Path
            Path to compiled extension.
        module_name : str
            Module name.

        Returns
        -------
        ModuleType
            Loaded module.
        """
        # Add to sys.path temporarily
        library_dir = str(library_path.parent)
        sys.path.insert(0, library_dir)

        try:
            spec = importlib.util.spec_from_file_location(
                module_name, str(library_path)
            )

            if spec is None or spec.loader is None:
                raise ImportModuleError(
                    module_name=module_name,
                    library_path=library_path,
                    message="Could not create module spec",
                )

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            return module

        except Exception as e:
            raise ImportModuleError(
                module_name=module_name,
                library_path=library_path,
                message=f"Failed to load Cython module: {e}",
                python_error=e,
            )
        finally:
            sys.path.pop(0)

    def unload(self, module_name: str) -> bool:
        """
        Unload a Cython module.

        Parameters
        ----------
        module_name : str
            Module name.

        Returns
        -------
        bool
            True if unloaded.
        """
        with self._module_lock:
            if module_name not in self._loaded_modules:
                return False

            # Remove from sys.modules
            if module_name in sys.modules:
                del sys.modules[module_name]

            # Clean up dependency cache
            metadata = self._module_metadata.get(module_name)
            if metadata:
                cache_key = str(metadata.source_path)
                self._dependency_cache.pop(cache_key, None)

            return self._unregister_module(module_name)

    def reload(self, module_name: str) -> ModuleType:
        """
        Reload a Cython module.

        Parameters
        ----------
        module_name : str
            Module name.

        Returns
        -------
        ModuleType
            Reloaded module.
        """
        metadata = self._module_metadata.get(module_name)
        if not metadata:
            raise ImportModuleError(
                module_name=module_name,
                library_path=Path("unknown"),
                message="Module not loaded",
            )

        self._set_state(LoaderState.RELOADING)
        self._trigger_event(LoaderEventType.PRE_RELOAD, module_name)
        self._stats["reload_count"] += 1

        # Clear dependency cache for this module
        cache_key = str(metadata.source_path)
        self._dependency_cache.pop(cache_key, None)

        # Invalidate dependents
        if self.config.track_dependencies:
            self.invalidate_dependents(module_name)

        # Unload and reload
        self.unload(module_name)
        module = self.load(metadata.source_path, recompile=True)

        self._trigger_event(LoaderEventType.POST_RELOAD, module_name)
        self._set_state(LoaderState.LOADED)

        return module

    def is_loaded(self, module_name: str) -> bool:
        """
        Check if module is loaded.

        Parameters
        ----------
        module_name : str
            Module name.

        Returns
        -------
        bool
            True if loaded.
        """
        return module_name in self._loaded_modules

    def get_metadata(self, module_name: str) -> Optional[ModuleMetadata]:
        """
        Get module metadata.

        Parameters
        ----------
        module_name : str
            Module name.

        Returns
        -------
        Optional[ModuleMetadata]
            Metadata or None.
        """
        return self._module_metadata.get(module_name)

    def load_batch(
        self,
        sources: List[Union[str, Path]],
        parallel: bool = True,
        **kwargs,
    ) -> Dict[str, ModuleType]:
        """
        Load multiple Cython modules in batch.

        Parameters
        ----------
        sources : List[Union[str, Path]]
            List of source files.
        parallel : bool, optional
            Use parallel compilation.
        **kwargs : Any
            Additional options.

        Returns
        -------
        Dict[str, ModuleType]
            Dictionary of loaded modules.
        """
        # First, parse all dependencies to determine build order
        all_deps: Dict[str, Set[str]] = {}
        source_map: Dict[str, Path] = {}

        for source in sources:
            path = Path(source)
            if path.suffix != self.PYX_EXTENSION:
                path = path.with_suffix(self.PYX_EXTENSION)
            name = path.stem
            source_map[name] = path
            all_deps[name] = self._parse_dependencies(path)

        # Topological sort for build order
        build_order = self._topological_sort(all_deps)

        if parallel and len(build_order) > 1:
            # Use batch loader
            batch = BatchLoader(self, self.config.parallel_strategy)
            ordered_sources = [source_map[name] for name in build_order]
            results = batch.load(ordered_sources, **kwargs)

            modules = {}
            for name, result in results.items():
                if result.success and result.module:
                    modules[name] = result.module
            return modules

        # Sequential loading in dependency order
        modules = {}
        for name in build_order:
            try:
                module = self.load(source_map[name], **kwargs)
                modules[name] = module
            except Exception as e:
                if not kwargs.get("continue_on_error", True):
                    raise
                self._trigger_event(LoaderEventType.LOAD_ERROR, name, error=e)

        return modules

    def _topological_sort(self, graph: Dict[str, Set[str]]) -> List[str]:
        """
        Perform topological sort on dependency graph.

        Parameters
        ----------
        graph : Dict[str, Set[str]]
            Dependency graph.

        Returns
        -------
        List[str]
            Sorted module names.
        """
        visited: Set[str] = set()
        temp_mark: Set[str] = set()
        order: List[str] = []

        def visit(node: str) -> None:
            if node in temp_mark:
                return  # Circular dependency, skip
            if node in visited:
                return

            temp_mark.add(node)

            for dep in graph.get(node, set()):
                if dep in graph:  # Only process known dependencies
                    visit(dep)

            temp_mark.remove(node)
            visited.add(node)
            order.append(node)

        for node in graph:
            if node not in visited:
                visit(node)

        return order

    def watch(self, source: Union[str, Path]) -> bool:
        """
        Watch a Cython source for changes.

        Parameters
        ----------
        source : Union[str, Path]
            Source file to watch.

        Returns
        -------
        bool
            True if watching started.
        """
        if not self._watcher:
            return False

        source_path = Path(source).resolve()
        if source_path.suffix != self.PYX_EXTENSION:
            source_path = source_path.with_suffix(self.PYX_EXTENSION)

        module_name = source_path.stem

        def on_change(path: Path) -> None:
            # Clear dependency cache
            cache_key = str(source_path)
            self._dependency_cache.pop(cache_key, None)

            # Reload if auto-reload enabled
            if self.config.auto_reload and self.is_loaded(module_name):
                self.reload(module_name)

        # Watch .pyx file
        self._watcher.add_watch(source_path, on_change)

        # Also watch associated .pxd file
        pxd_path = source_path.with_suffix(self.PXD_EXTENSION)
        if pxd_path.exists():
            self._watcher.add_watch(pxd_path, on_change)

        return True

    def unwatch(self, source: Union[str, Path]) -> bool:
        """
        Stop watching a source file.

        Parameters
        ----------
        source : Union[str, Path]
            Source file.

        Returns
        -------
        bool
            True if stopped.
        """
        if not self._watcher:
            return False

        source_path = Path(source).resolve()
        self._watcher.remove_watch(source_path)

        pxd_path = source_path.with_suffix(self.PXD_EXTENSION)
        self._watcher.remove_watch(pxd_path)

        return True

    def annotate(self, source: Union[str, Path]) -> Optional[Path]:
        """
        Generate HTML annotation for a Cython source.

        Parameters
        ----------
        source : Union[str, Path]
            Source file.

        Returns
        -------
        Optional[Path]
            Path to generated HTML file.
        """
        source_path = Path(source).resolve()

        # Enable annotation temporarily
        old_annotate = self.cython_config.annotate
        self.cython_config.annotate = True

        try:
            # Compile with annotation
            output_path = self._get_output_path(source_path, None)
            self.compiler.compile(source_path, output_path, force=True)

            # Find generated HTML
            html_path = source_path.with_suffix(".html")
            if html_path.exists():
                return html_path

        finally:
            self.cython_config.annotate = old_annotate

        return None

    def get_cython_version(self) -> str:
        """
        Get installed Cython version.

        Returns
        -------
        str
            Version string.
        """
        try:
            import Cython
            return Cython.__version__
        except ImportError:
            return "not installed"

    def close(self) -> None:
        """
        Close loader and release resources.
        """
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

        self._dependency_cache.clear()
        self._pxd_registry.clear()

        super().close()

    def __repr__(self) -> str:
        return (
            f"<CythonLoader "
            f"backend={self.cython_config.backend.value} "
            f"modules={len(self._loaded_modules)} "
            f"cython={self.get_cython_version()} "
            f"state={self.state.value}>"
        )


# Alias for backward compatibility
CyImport = CythonLoader