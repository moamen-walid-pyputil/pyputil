#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    CONFIGURATION MANAGEMENT
==================================

Hierarchical configuration system with validation,
inheritance, and environment variable support.
"""

import json
import os
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from .enums import (
    BuildMode,
    CacheStrategy,
    CompilerFamily,
    LanguageStandard,
    LogLevel,
    OptimizationLevel,
    ParallelStrategy,
    SIMDLevel,
    SandboxPolicy,
)
from .exceptions import ConfigError


@dataclass
class CompilerConfig:
    """
    Compiler-specific configuration settings.

    Parameters
    ----------
    name : str
        Compiler name (e.g., 'gcc', 'clang', 'cl').
    family : CompilerFamily
        Compiler family.
    executable : Optional[Path]
        Path to compiler executable.
    version : Optional[str]
        Compiler version string.
    extra_flags : List[str]
        Additional compiler flags.
    extra_link_flags : List[str]
        Additional linker flags.
    defines : Dict[str, str]
        Preprocessor definitions.
    include_paths : List[Path]
        Additional include directories.
    library_paths : List[Path]
        Additional library search paths.
    libraries : List[str]
        Libraries to link against.

    Attributes
    ----------
    _validated : bool
        Whether configuration has been validated.
    """

    name: str
    family: CompilerFamily = CompilerFamily.OTHER
    executable: Optional[Path] = None
    version: Optional[str] = None
    extra_flags: List[str] = field(default_factory=list)
    extra_link_flags: List[str] = field(default_factory=list)
    defines: Dict[str, str] = field(default_factory=dict)
    include_paths: List[Path] = field(default_factory=list)
    library_paths: List[Path] = field(default_factory=list)
    libraries: List[str] = field(default_factory=list)
    _validated: bool = field(default=False, init=False, repr=False)

    def validate(self) -> bool:
        """
        Validate compiler configuration.

        Returns
        -------
        bool
            True if configuration is valid.

        Raises
        ------
        ConfigError
            If configuration is invalid.
        """
        errors = []

        if not self.name:
            errors.append("Compiler name is required")

        if self.executable and not Path(self.executable).exists():
            errors.append(f"Compiler executable not found: {self.executable}")

        for path in self.include_paths:
            if not Path(path).exists():
                errors.append(f"Include path not found: {path}")

        for path in self.library_paths:
            if not Path(path).exists():
                errors.append(f"Library path not found: {path}")

        if errors:
            raise ConfigError(
                config_key="compiler",
                message="Compiler configuration validation failed",
                expected="Valid compiler settings",
                actual="; ".join(errors),
            )

        self._validated = True
        return True

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "name": self.name,
            "family": self.family.value,
            "executable": str(self.executable) if self.executable else None,
            "version": self.version,
            "extra_flags": self.extra_flags,
            "extra_link_flags": self.extra_link_flags,
            "defines": self.defines,
            "include_paths": [str(p) for p in self.include_paths],
            "library_paths": [str(p) for p in self.library_paths],
            "libraries": self.libraries,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompilerConfig":
        """
        Create from dictionary.

        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary representation.

        Returns
        -------
        CompilerConfig
            Reconstructed configuration.
        """
        return cls(
            name=data["name"],
            family=CompilerFamily(data.get("family", "other")),
            executable=Path(data["executable"]) if data.get("executable") else None,
            version=data.get("version"),
            extra_flags=data.get("extra_flags", []),
            extra_link_flags=data.get("extra_link_flags", []),
            defines=data.get("defines", {}),
            include_paths=[Path(p) for p in data.get("include_paths", [])],
            library_paths=[Path(p) for p in data.get("library_paths", [])],
            libraries=data.get("libraries", []),
        )


@dataclass
class OptimizationConfig:
    """
    Optimization-specific configuration settings.

    Parameters
    ----------
    level : OptimizationLevel
        Optimization level.
    simd_level : SIMDLevel
        SIMD instruction set level.
    enable_lto : bool
        Enable Link-Time Optimization.
    enable_pgo : bool
        Enable Profile-Guided Optimization.
    enable_openmp : bool
        Enable OpenMP parallelism.
    enable_autovectorize : bool
        Enable auto-vectorization.
    enable_inlining : bool
        Enable function inlining.
    inline_threshold : Optional[int]
        Inlining threshold (compiler-specific).
    unroll_loops : bool
        Enable loop unrolling.
    fast_math : bool
        Enable fast math optimizations.
    omit_frame_pointer : bool
        Omit frame pointer for better performance.

    Attributes
    ----------
    custom_flags : List[str]
        Custom optimization flags.
    """

    level: OptimizationLevel = OptimizationLevel.STANDARD
    simd_level: SIMDLevel = SIMDLevel.NONE
    enable_lto: bool = False
    enable_pgo: bool = False
    enable_openmp: bool = False
    enable_autovectorize: bool = True
    enable_inlining: bool = True
    inline_threshold: Optional[int] = None
    unroll_loops: bool = False
    fast_math: bool = False
    omit_frame_pointer: bool = True
    custom_flags: List[str] = field(default_factory=list)

    def get_optimization_level(self) -> OptimizationLevel:
        """
        Get the effective optimization level.

        Returns
        -------
        OptimizationLevel
            Effective optimization level.
        """
        return self.level

    def get_simd_level(self) -> SIMDLevel:
        """
        Get the SIMD instruction set level.

        Returns
        -------
        SIMDLevel
            SIMD level.
        """
        return self.simd_level

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "level": self.level.value,
            "simd_level": self.simd_level.value,
            "enable_lto": self.enable_lto,
            "enable_pgo": self.enable_pgo,
            "enable_openmp": self.enable_openmp,
            "enable_autovectorize": self.enable_autovectorize,
            "enable_inlining": self.enable_inlining,
            "inline_threshold": self.inline_threshold,
            "unroll_loops": self.unroll_loops,
            "fast_math": self.fast_math,
            "omit_frame_pointer": self.omit_frame_pointer,
            "custom_flags": self.custom_flags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OptimizationConfig":
        """
        Create from dictionary.

        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary representation.

        Returns
        -------
        OptimizationConfig
            Reconstructed configuration.
        """
        return cls(
            level=OptimizationLevel(data.get("level", "standard")),
            simd_level=SIMDLevel(data.get("simd_level", "none")),
            enable_lto=data.get("enable_lto", False),
            enable_pgo=data.get("enable_pgo", False),
            enable_openmp=data.get("enable_openmp", False),
            enable_autovectorize=data.get("enable_autovectorize", True),
            enable_inlining=data.get("enable_inlining", True),
            inline_threshold=data.get("inline_threshold"),
            unroll_loops=data.get("unroll_loops", False),
            fast_math=data.get("fast_math", False),
            omit_frame_pointer=data.get("omit_frame_pointer", True),
            custom_flags=data.get("custom_flags", []),
        )


@dataclass
class DebugConfig:
    """
    Debug and diagnostics configuration.

    Parameters
    ----------
    enabled : bool
        Enable debug mode.
    symbols : bool
        Include debug symbols.
    assertions : bool
        Enable assertions.
    bounds_checking : bool
        Enable bounds checking.
    address_sanitizer : bool
        Enable AddressSanitizer.
    thread_sanitizer : bool
        Enable ThreadSanitizer.
    undefined_sanitizer : bool
        Enable UndefinedBehaviorSanitizer.
    memory_sanitizer : bool
        Enable MemorySanitizer.
    leak_sanitizer : bool
        Enable LeakSanitizer.
    coverage : bool
        Enable code coverage instrumentation.
    profile : bool
        Enable profiling instrumentation.
    verbose_diagnostics : bool
        Enable verbose compiler diagnostics.

    Attributes
    ----------
    sanitizer_flags : List[str]
        Additional sanitizer flags.
    """

    enabled: bool = False
    symbols: bool = True
    assertions: bool = True
    bounds_checking: bool = False
    address_sanitizer: bool = False
    thread_sanitizer: bool = False
    undefined_sanitizer: bool = False
    memory_sanitizer: bool = False
    leak_sanitizer: bool = False
    coverage: bool = False
    profile: bool = False
    verbose_diagnostics: bool = False
    sanitizer_flags: List[str] = field(default_factory=list)

    def has_any_sanitizer(self) -> bool:
        """
        Check if any sanitizer is enabled.

        Returns
        -------
        bool
            True if at least one sanitizer is enabled.
        """
        return any([
            self.address_sanitizer,
            self.thread_sanitizer,
            self.undefined_sanitizer,
            self.memory_sanitizer,
            self.leak_sanitizer,
        ])

    def get_enabled_sanitizers(self) -> List[str]:
        """
        Get list of enabled sanitizer names.

        Returns
        -------
        List[str]
            List of enabled sanitizers.
        """
        sanitizers = []
        if self.address_sanitizer:
            sanitizers.append("address")
        if self.thread_sanitizer:
            sanitizers.append("thread")
        if self.undefined_sanitizer:
            sanitizers.append("undefined")
        if self.memory_sanitizer:
            sanitizers.append("memory")
        if self.leak_sanitizer:
            sanitizers.append("leak")
        return sanitizers

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "enabled": self.enabled,
            "symbols": self.symbols,
            "assertions": self.assertions,
            "bounds_checking": self.bounds_checking,
            "address_sanitizer": self.address_sanitizer,
            "thread_sanitizer": self.thread_sanitizer,
            "undefined_sanitizer": self.undefined_sanitizer,
            "memory_sanitizer": self.memory_sanitizer,
            "leak_sanitizer": self.leak_sanitizer,
            "coverage": self.coverage,
            "profile": self.profile,
            "verbose_diagnostics": self.verbose_diagnostics,
            "sanitizer_flags": self.sanitizer_flags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DebugConfig":
        """
        Create from dictionary.

        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary representation.

        Returns
        -------
        DebugConfig
            Reconstructed configuration.
        """
        return cls(
            enabled=data.get("enabled", False),
            symbols=data.get("symbols", True),
            assertions=data.get("assertions", True),
            bounds_checking=data.get("bounds_checking", False),
            address_sanitizer=data.get("address_sanitizer", False),
            thread_sanitizer=data.get("thread_sanitizer", False),
            undefined_sanitizer=data.get("undefined_sanitizer", False),
            memory_sanitizer=data.get("memory_sanitizer", False),
            leak_sanitizer=data.get("leak_sanitizer", False),
            coverage=data.get("coverage", False),
            profile=data.get("profile", False),
            verbose_diagnostics=data.get("verbose_diagnostics", False),
            sanitizer_flags=data.get("sanitizer_flags", []),
        )


@dataclass
class BuildConfig:
    """
    Build process configuration.

    Parameters
    ----------
    mode : BuildMode
        Build mode (debug, release, etc.).
    parallel_strategy : ParallelStrategy
        Parallel compilation strategy.
    max_workers : Optional[int]
        Maximum number of parallel workers.
    timeout_seconds : Optional[int]
        Compilation timeout in seconds.
    retry_count : int
        Number of compilation retries on failure.
    clean_before_build : bool
        Clean build directory before compilation.
    keep_temp_files : bool
        Keep temporary files after compilation.
    show_commands : bool
        Show compilation commands.
    show_progress : bool
        Show progress indicators.
    color_output : bool
        Enable colored terminal output.

    Attributes
    ----------
    build_dir : Optional[Path]
        Build directory path.
    temp_dir : Optional[Path]
        Temporary directory path.
    """

    mode: BuildMode = BuildMode.RELEASE
    parallel_strategy: ParallelStrategy = ParallelStrategy.AUTO
    max_workers: Optional[int] = None
    timeout_seconds: Optional[int] = 300
    retry_count: int = 2
    clean_before_build: bool = False
    keep_temp_files: bool = False
    show_commands: bool = False
    show_progress: bool = True
    color_output: bool = True
    build_dir: Optional[Path] = None
    temp_dir: Optional[Path] = None

    def get_effective_worker_count(self) -> int:
        """
        Get effective number of parallel workers.

        Returns
        -------
        int
            Number of workers.
        """
        if self.max_workers is not None:
            return self.max_workers
        return self.parallel_strategy.get_worker_count()

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "mode": self.mode.value,
            "parallel_strategy": self.parallel_strategy.value,
            "max_workers": self.max_workers,
            "timeout_seconds": self.timeout_seconds,
            "retry_count": self.retry_count,
            "clean_before_build": self.clean_before_build,
            "keep_temp_files": self.keep_temp_files,
            "show_commands": self.show_commands,
            "show_progress": self.show_progress,
            "color_output": self.color_output,
            "build_dir": str(self.build_dir) if self.build_dir else None,
            "temp_dir": str(self.temp_dir) if self.temp_dir else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BuildConfig":
        """
        Create from dictionary.

        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary representation.

        Returns
        -------
        BuildConfig
            Reconstructed configuration.
        """
        return cls(
            mode=BuildMode(data.get("mode", "release")),
            parallel_strategy=ParallelStrategy(data.get("parallel_strategy", "auto")),
            max_workers=data.get("max_workers"),
            timeout_seconds=data.get("timeout_seconds", 300),
            retry_count=data.get("retry_count", 2),
            clean_before_build=data.get("clean_before_build", False),
            keep_temp_files=data.get("keep_temp_files", False),
            show_commands=data.get("show_commands", False),
            show_progress=data.get("show_progress", True),
            color_output=data.get("color_output", True),
            build_dir=Path(data["build_dir"]) if data.get("build_dir") else None,
            temp_dir=Path(data["temp_dir"]) if data.get("temp_dir") else None,
        )


@dataclass
class CacheConfig:
    """
    Cache configuration settings.

    Parameters
    ----------
    enabled : bool
        Enable caching.
    strategy : CacheStrategy
        Caching strategy.
    directory : Optional[Path]
        Cache directory path.
    max_size_gb : Optional[float]
        Maximum cache size in gigabytes.
    max_age_days : Optional[int]
        Maximum age for cached items in days.
    compress : bool
        Compress cached files.
    validate_before_use : bool
        Validate cache entries before use.
    shared_cache : bool
        Enable shared/distributed cache.
    shared_cache_url : Optional[str]
        URL for shared cache server.

    Attributes
    ----------
    cache_key_components : Set[str]
        Components to include in cache key.
    """

    enabled: bool = True
    strategy: CacheStrategy = CacheStrategy.NORMAL
    directory: Optional[Path] = None
    max_size_gb: Optional[float] = 10.0
    max_age_days: Optional[int] = 30
    compress: bool = False
    validate_before_use: bool = True
    shared_cache: bool = False
    shared_cache_url: Optional[str] = None
    cache_key_components: Set[str] = field(default_factory=lambda: {
        "source",
        "compiler",
        "flags",
        "platform",
        "python",
    })

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "enabled": self.enabled,
            "strategy": self.strategy.value,
            "directory": str(self.directory) if self.directory else None,
            "max_size_gb": self.max_size_gb,
            "max_age_days": self.max_age_days,
            "compress": self.compress,
            "validate_before_use": self.validate_before_use,
            "shared_cache": self.shared_cache,
            "shared_cache_url": self.shared_cache_url,
            "cache_key_components": list(self.cache_key_components),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CacheConfig":
        """
        Create from dictionary.

        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary representation.

        Returns
        -------
        CacheConfig
            Reconstructed configuration.
        """
        return cls(
            enabled=data.get("enabled", True),
            strategy=CacheStrategy(data.get("strategy", "normal")),
            directory=Path(data["directory"]) if data.get("directory") else None,
            max_size_gb=data.get("max_size_gb", 10.0),
            max_age_days=data.get("max_age_days", 30),
            compress=data.get("compress", False),
            validate_before_use=data.get("validate_before_use", True),
            shared_cache=data.get("shared_cache", False),
            shared_cache_url=data.get("shared_cache_url"),
            cache_key_components=set(data.get("cache_key_components", [])),
        )


@dataclass
class SandboxConfig:
    """
    Sandbox/Isolation configuration.

    Parameters
    ----------
    policy : SandboxPolicy
        Sandbox policy.
    timeout_seconds : Optional[int]
        Execution timeout in seconds.
    memory_limit_mb : Optional[int]
        Memory limit in megabytes.
    cpu_limit_percent : Optional[int]
        CPU usage limit percentage.
    restrict_filesystem : bool
        Restrict filesystem access.
    allowed_paths : List[Path]
        Paths allowed for access.
    restrict_network : bool
        Restrict network access.
    restrict_subprocesses : bool
        Restrict spawning subprocesses.
    max_file_size_mb : Optional[int]
        Maximum output file size.
    max_output_lines : Optional[int]
        Maximum lines of compiler output.

    Attributes
    ----------
    _validated : bool
        Whether configuration has been validated.
    """

    policy: SandboxPolicy = SandboxPolicy.BASIC
    timeout_seconds: Optional[int] = None
    memory_limit_mb: Optional[int] = None
    cpu_limit_percent: Optional[int] = None
    restrict_filesystem: bool = False
    allowed_paths: List[Path] = field(default_factory=list)
    restrict_network: bool = True
    restrict_subprocesses: bool = True
    max_file_size_mb: Optional[int] = 100
    max_output_lines: Optional[int] = 10000
    _validated: bool = field(default=False, init=False, repr=False)

    def get_effective_timeout(self) -> Optional[int]:
        """
        Get effective timeout based on policy.

        Returns
        -------
        Optional[int]
            Timeout in seconds.
        """
        if self.timeout_seconds is not None:
            return self.timeout_seconds
        return self.policy.get_default_timeout()

    def get_effective_memory_limit(self) -> Optional[int]:
        """
        Get effective memory limit based on policy.

        Returns
        -------
        Optional[int]
            Memory limit in MB.
        """
        if self.memory_limit_mb is not None:
            return self.memory_limit_mb
        return self.policy.get_default_memory_limit_mb()

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "policy": self.policy.value,
            "timeout_seconds": self.timeout_seconds,
            "memory_limit_mb": self.memory_limit_mb,
            "cpu_limit_percent": self.cpu_limit_percent,
            "restrict_filesystem": self.restrict_filesystem,
            "allowed_paths": [str(p) for p in self.allowed_paths],
            "restrict_network": self.restrict_network,
            "restrict_subprocesses": self.restrict_subprocesses,
            "max_file_size_mb": self.max_file_size_mb,
            "max_output_lines": self.max_output_lines,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SandboxConfig":
        """
        Create from dictionary.

        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary representation.

        Returns
        -------
        SandboxConfig
            Reconstructed configuration.
        """
        return cls(
            policy=SandboxPolicy(data.get("policy", "basic")),
            timeout_seconds=data.get("timeout_seconds"),
            memory_limit_mb=data.get("memory_limit_mb"),
            cpu_limit_percent=data.get("cpu_limit_percent"),
            restrict_filesystem=data.get("restrict_filesystem", False),
            allowed_paths=[Path(p) for p in data.get("allowed_paths", [])],
            restrict_network=data.get("restrict_network", True),
            restrict_subprocesses=data.get("restrict_subprocesses", True),
            max_file_size_mb=data.get("max_file_size_mb", 100),
            max_output_lines=data.get("max_output_lines", 10000),
        )


@dataclass
class PythonConfig:
    """
    Python-specific configuration.

    Parameters
    ----------
    use_sysconfig : bool
        Use sysconfig for Python configuration.
    python_executable : Optional[Path]
        Path to Python executable.
    python_version : Optional[str]
        Python version string.
    python_include_dirs : List[Path]
        Python include directories.
    python_library_dirs : List[Path]
        Python library directories.
    python_libraries : List[str]
        Python libraries to link.
    extension_suffix : Optional[str]
        Extension module suffix.
    limited_api : bool
        Use Python limited API for ABI stability.
    limited_api_version : Optional[str]
        Limited API version (e.g., '3.10').

    Attributes
    ----------
    _detected : bool
        Whether Python configuration has been auto-detected.
    """

    use_sysconfig: bool = True
    python_executable: Optional[Path] = None
    python_version: Optional[str] = None
    python_include_dirs: List[Path] = field(default_factory=list)
    python_library_dirs: List[Path] = field(default_factory=list)
    python_libraries: List[str] = field(default_factory=list)
    extension_suffix: Optional[str] = None
    limited_api: bool = False
    limited_api_version: Optional[str] = None
    _detected: bool = field(default=False, init=False, repr=False)

    def detect(self) -> "PythonConfig":
        """
        Auto-detect Python configuration using sysconfig.

        Returns
        -------
        PythonConfig
            Self for method chaining.
        """
        import sys
        import sysconfig

        self.python_executable = Path(sys.executable)
        self.python_version = f"{sys.version_info.major}.{sys.version_info.minor}"

        if self.use_sysconfig:
            # Get include directories
            include_paths = sysconfig.get_paths()
            if "include" in include_paths:
                self.python_include_dirs.append(Path(include_paths["include"]))
            if "platinclude" in include_paths:
                self.python_include_dirs.append(Path(include_paths["platinclude"]))

            # Get library directories
            if "stdlib" in include_paths:
                lib_dir = Path(include_paths["stdlib"]).parent
                if lib_dir.exists():
                    self.python_library_dirs.append(lib_dir)

            # Get extension suffix
            self.extension_suffix = sysconfig.get_config_var("EXT_SUFFIX")

            # Detect Python library name
            lib_name = sysconfig.get_config_var("LDLIBRARY")
            if lib_name:
                # Strip 'lib' prefix and extension
                if lib_name.startswith("lib"):
                    lib_name = lib_name[3:]
                if "." in lib_name:
                    lib_name = lib_name.split(".")[0]
                self.python_libraries.append(lib_name)

        self._detected = True
        return self

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "use_sysconfig": self.use_sysconfig,
            "python_executable": str(self.python_executable) if self.python_executable else None,
            "python_version": self.python_version,
            "python_include_dirs": [str(p) for p in self.python_include_dirs],
            "python_library_dirs": [str(p) for p in self.python_library_dirs],
            "python_libraries": self.python_libraries,
            "extension_suffix": self.extension_suffix,
            "limited_api": self.limited_api,
            "limited_api_version": self.limited_api_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PythonConfig":
        """
        Create from dictionary.

        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary representation.

        Returns
        -------
        PythonConfig
            Reconstructed configuration.
        """
        return cls(
            use_sysconfig=data.get("use_sysconfig", True),
            python_executable=Path(data["python_executable"]) if data.get("python_executable") else None,
            python_version=data.get("python_version"),
            python_include_dirs=[Path(p) for p in data.get("python_include_dirs", [])],
            python_library_dirs=[Path(p) for p in data.get("python_library_dirs", [])],
            python_libraries=data.get("python_libraries", []),
            extension_suffix=data.get("extension_suffix"),
            limited_api=data.get("limited_api", False),
            limited_api_version=data.get("limited_api_version"),
        )


@dataclass
class CImporterConfig:
    """
    Master configuration for cimporter.

    This class aggregates all configuration sections and provides
    methods for loading, saving, and validating the complete configuration.

    Parameters
    ----------
    compiler : CompilerConfig
        Compiler configuration.
    optimization : OptimizationConfig
        Optimization configuration.
    debug : DebugConfig
        Debug configuration.
    build : BuildConfig
        Build configuration.
    cache : CacheConfig
        Cache configuration.
    sandbox : SandboxConfig
        Sandbox configuration.
    python : PythonConfig
        Python configuration.
    log_level : LogLevel
        Logging level.
    project_name : Optional[str]
        Project name for identification.

    Attributes
    ----------
    _validated : bool
        Whether configuration has been validated.
    _loaded_from : Optional[Path]
        Path configuration was loaded from.

    Examples
    --------
    >>> config = CImporterConfig.default()
    >>> config.optimization.level = OptimizationLevel.MAX
    >>> config.build.mode = BuildMode.RELEASE
    >>> config.validate()
    >>> config.save("cimporter.json")
    """

    compiler: CompilerConfig = field(default_factory=lambda: CompilerConfig(name="auto"))
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)
    build: BuildConfig = field(default_factory=BuildConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    python: PythonConfig = field(default_factory=PythonConfig)
    log_level: LogLevel = LogLevel.INFO
    project_name: Optional[str] = None
    _validated: bool = field(default=False, init=False, repr=False)
    _loaded_from: Optional[Path] = field(default=None, init=False, repr=False)

    @classmethod
    def default(cls) -> "CImporterConfig":
        """
        Create default configuration with auto-detection.

        Returns
        -------
        CImporterConfig
            Default configuration.
        """
        config = cls()
        config.python.detect()
        return config

    @classmethod
    def load(cls, path: Union[str, Path]) -> "CImporterConfig":
        """
        Load configuration from JSON file.

        Parameters
        ----------
        path : Union[str, Path]
            Path to JSON configuration file.

        Returns
        -------
        CImporterConfig
            Loaded configuration.

        Raises
        ------
        ConfigError
            If file cannot be loaded or parsed.
        """
        path = Path(path)

        if not path.exists():
            raise ConfigError(
                config_key="load",
                message=f"Configuration file not found: {path}",
                expected="Existing file path",
                actual=str(path),
            )

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            config = cls.from_dict(data)
            config._loaded_from = path
            return config
        except json.JSONDecodeError as e:
            raise ConfigError(
                config_key="load",
                message=f"Invalid JSON in configuration file: {e}",
                expected="Valid JSON",
                actual=str(e),
            )

    def save(self, path: Union[str, Path]) -> None:
        """
        Save configuration to JSON file.

        Parameters
        ----------
        path : Union[str, Path]
            Path to save configuration.

        Raises
        ------
        ConfigError
            If file cannot be written.
        """
        path = Path(path)

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2, default=str)
        except (OSError, IOError) as e:
            raise ConfigError(
                config_key="save",
                message=f"Failed to save configuration: {e}",
                expected="Writable file path",
                actual=str(path),
            )

    def validate(self) -> bool:
        """
        Validate complete configuration.

        Returns
        -------
        bool
            True if configuration is valid.

        Raises
        ------
        ConfigError
            If any configuration section is invalid.
        """
        errors = []

        try:
            self.compiler.validate()
        except ConfigError as e:
            errors.append(f"Compiler: {e}")

        try:
            self.python.validate()
        except ConfigError as e:
            errors.append(f"Python: {e}")

        # Validate build mode consistency
        if self.debug.enabled and self.build.mode != BuildMode.DEBUG:
            errors.append(
                "Debug config enabled but build mode is not DEBUG"
            )

        # Validate sanitizer compatibility
        if self.debug.has_any_sanitizer():
            if self.optimization.level != OptimizationLevel.NONE:
                errors.append(
                    "Sanitizers work best with OptimizationLevel.NONE"
                )
            if self.optimization.enable_lto:
                errors.append(
                    "LTO may interfere with sanitizers"
                )

        if errors:
            raise ConfigError(
                config_key="validation",
                message="Configuration validation failed",
                expected="Valid configuration",
                actual="; ".join(errors),
            )

        self._validated = True
        return True

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "version": "1.0",
            "project_name": self.project_name,
            "log_level": self.log_level.value,
            "compiler": self.compiler.to_dict(),
            "optimization": self.optimization.to_dict(),
            "debug": self.debug.to_dict(),
            "build": self.build.to_dict(),
            "cache": self.cache.to_dict(),
            "sandbox": self.sandbox.to_dict(),
            "python": self.python.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CImporterConfig":
        """
        Create from dictionary.

        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary representation.

        Returns
        -------
        CImporterConfig
            Reconstructed configuration.
        """
        return cls(
            compiler=CompilerConfig.from_dict(data.get("compiler", {})),
            optimization=OptimizationConfig.from_dict(data.get("optimization", {})),
            debug=DebugConfig.from_dict(data.get("debug", {})),
            build=BuildConfig.from_dict(data.get("build", {})),
            cache=CacheConfig.from_dict(data.get("cache", {})),
            sandbox=SandboxConfig.from_dict(data.get("sandbox", {})),
            python=PythonConfig.from_dict(data.get("python", {})),
            log_level=LogLevel(data.get("log_level", "info")),
            project_name=data.get("project_name"),
        )

    def merge(self, other: "CImporterConfig") -> "CImporterConfig":
        """
        Merge another configuration, overriding existing values.

        Parameters
        ----------
        other : CImporterConfig
            Configuration to merge.

        Returns
        -------
        CImporterConfig
            New merged configuration.
        """
        merged = deepcopy(self)

        if other.compiler.name != "auto":
            merged.compiler = other.compiler
        if other.optimization.level != OptimizationLevel.STANDARD:
            merged.optimization = other.optimization
        if other.debug.enabled:
            merged.debug = other.debug
        if other.build.mode != BuildMode.RELEASE:
            merged.build = other.build
        if not other.cache.enabled:
            merged.cache = other.cache
        if other.sandbox.policy != SandboxPolicy.BASIC:
            merged.sandbox = other.sandbox
        if other.log_level != LogLevel.INFO:
            merged.log_level = other.log_level
        if other.project_name:
            merged.project_name = other.project_name

        return merged

    def create_build_environment(self) -> Dict[str, str]:
        """
        Create environment variables for compilation.

        Returns
        -------
        Dict[str, str]
            Environment variable dictionary.
        """
        env = os.environ.copy()

        # Compiler overrides
        if self.compiler.executable:
            env["CC"] = str(self.compiler.executable)
            env["CXX"] = str(self.compiler.executable)

        # Additional paths
        include_paths = ":".join(str(p) for p in self.compiler.include_paths)
        if include_paths:
            env["C_INCLUDE_PATH"] = include_paths
            env["CPLUS_INCLUDE_PATH"] = include_paths

        library_paths = ":".join(str(p) for p in self.compiler.library_paths)
        if library_paths:
            if sys.platform == "darwin":
                env["DYLD_LIBRARY_PATH"] = library_paths
            else:
                env["LD_LIBRARY_PATH"] = library_paths

        return env

    def get_cache_key_builder(self, source_path: Path) -> "CacheKeyBuilder":
        """
        Create a CacheKeyBuilder configured with these settings.

        Parameters
        ----------
        source_path : Path
            Source file path.

        Returns
        -------
        CacheKeyBuilder
            Configured cache key builder.
        """
        from .cache import CacheKeyBuilder

        builder = CacheKeyBuilder(source_path)

        # Add relevant dependencies based on configuration
        if self.python.python_executable:
            builder.add_dependency(self.python.python_executable)

        return builder