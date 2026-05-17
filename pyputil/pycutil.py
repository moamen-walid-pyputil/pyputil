#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import importlib.util
import marshal
import struct
import sys
import types
import dis
import tempfile
import subprocess
import hashlib
import logging
import platform
import warnings
import json
import os
import shutil
import re
import asyncio
import pickle
import time
from pathlib import Path
from typing import (
    Optional, Union, Dict, Any, Tuple, List, Callable,
    Type, TypeVar, Iterator, AsyncIterator, Coroutine, Set
)
from datetime import datetime, timezone
from enum import Enum, auto
from dataclasses import dataclass, field, asdict
from functools import lru_cache, wraps
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
import contextlib

# Configure module-level logger
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# Type variables for generic type hints
T = TypeVar('T')
ModuleType = types.ModuleType


# ============================================================================
# Enumerations
# ============================================================================

class BytecodeVersion(Enum):
    """
    Python bytecode version enumeration based on magic numbers.

    Each Python version has a unique magic number embedded in the first
    4 bytes of .pyc files. The high byte typically contains 0x0A0D
    (\\r\\n) to detect file corruption.

    Attributes
    ----------
    value : Tuple[int, int]
        The magic number bytes as (low_bytes, high_bytes).
        The low bytes represent the minor version offset,
        and the high bytes contain the carriage return/line feed signature.

    Notes
    -----
    Magic numbers change whenever the bytecode instruction set changes
    between Python releases. The mapping between version enumeration
    members and their corresponding Python versions is maintained
    internally via the `python_version` property.

    The magic number is stored in little-endian format. The complete
    32-bit value is constructed as `(high << 16) | low`, where `high`
    contains the 0x0A0D signature and `low` encodes the version-specific
    identifier.

    References
    ----------
    .. [1] PEP 3147 - PYC Repository Directories
           https://www.python.org/dev/peps/pep-3147/
    .. [2] Python/importlib/_bootstrap_external.py
           Contains the authoritative magic number definitions
           used by the CPython interpreter.

    Examples
    --------
    >>> version = BytecodeVersion.V3_11
    >>> version.full_magic
    3862
    >>> version.python_version
    (3, 11)

    >>> # Iterate over all known versions
    >>> for v in BytecodeVersion:
    ...     print(f"{v.name}: Python {v.python_version}")
    V3_0: Python (3, 0)
    V3_1: Python (3, 1)
    ...
    """
    V3_0 = (0x0a0d, 0x0bb8)   # Python 3.0
    V3_1 = (0x0a0d, 0x0c4e)   # Python 3.1
    V3_2 = (0x0a0d, 0x0c80)   # Python 3.2
    V3_3 = (0x0a0d, 0x0ce4)   # Python 3.3
    V3_4 = (0x0a0d, 0x0d56)   # Python 3.4
    V3_5 = (0x0a0d, 0x0dae)   # Python 3.5
    V3_6 = (0x0a0d, 0x0e10)   # Python 3.6
    V3_7 = (0x0a0d, 0x0e5a)   # Python 3.7
    V3_8 = (0x0a0d, 0x0e8a)   # Python 3.8
    V3_9 = (0x0a0d, 0x0eb2)   # Python 3.9
    V3_10 = (0x0a0d, 0x0edc)  # Python 3.10
    V3_11 = (0x0a0d, 0x0f0e)  # Python 3.11
    V3_12 = (0x0a0d, 0x0f44)  # Python 3.12
    V3_13 = (0x0a0d, 0x0f7e)  # Python 3.13

    @property
    def full_magic(self) -> int:
        """
        Get the full 4-byte magic number as a single integer.

        Constructs the complete 32-bit magic number by combining the
        high and low 16-bit words using bitwise operations. The high
        word contains the 0x0A0D signature bytes, and the low word
        contains the version-specific identifier.

        Returns
        -------
        int
            The complete 32-bit magic number computed as
            ``(high << 16) | low``. This value uniquely identifies
            the Python version that produced the bytecode.

        Notes
        -----
        The magic number is stored in little-endian byte order
        within .pyc files. This property returns the integer
        representation suitable for comparison with values read
        from file headers.

        Examples
        --------
        >>> BytecodeVersion.V3_11.full_magic
        3862
        >>> hex(BytecodeVersion.V3_11.full_magic)
        '0x0f0e'
        """
        low, high = self.value
        return (high << 16) | low

    @property
    def python_version(self) -> Tuple[int, int]:
        """
        Get the Python version tuple (major, minor).

        Maps each enumeration member to its corresponding Python
        version using an internal lookup table. Returns (0, 0) for
        unknown or unmapped versions.

        Returns
        -------
        Tuple[int, int]
            Version tuple of the form ``(major, minor)``, e.g.,
            ``(3, 11)`` for Python 3.11. If the version cannot
            be determined, returns ``(0, 0)``.

        Notes
        -----
        The version mapping is maintained as an internal dictionary
        within the property. When new `BytecodeVersion` members are
        added, they must be included in this mapping to be properly
        recognized.

        Examples
        --------
        >>> BytecodeVersion.V3_9.python_version
        (3, 9)
        >>> BytecodeVersion.V3_13.python_version
        (3, 13)
        """
        version_map = {
            BytecodeVersion.V3_0: (3, 0), BytecodeVersion.V3_1: (3, 1),
            BytecodeVersion.V3_2: (3, 2), BytecodeVersion.V3_3: (3, 3),
            BytecodeVersion.V3_4: (3, 4), BytecodeVersion.V3_5: (3, 5),
            BytecodeVersion.V3_6: (3, 6), BytecodeVersion.V3_7: (3, 7),
            BytecodeVersion.V3_8: (3, 8), BytecodeVersion.V3_9: (3, 9),
            BytecodeVersion.V3_10: (3, 10), BytecodeVersion.V3_11: (3, 11),
            BytecodeVersion.V3_12: (3, 12), BytecodeVersion.V3_13: (3, 13),
        }
        return version_map.get(self, (0, 0))


class LoadStrategy(Enum):
    """
    Enumeration of available loading strategies for .pyc files.

    Defines the ordered set of strategies that the loader can attempt
    when loading bytecode files. Strategies are attempted in order of
    efficiency and reliability, with each subsequent strategy serving
    as a fallback for the previous one.

    Strategy Order (by efficiency):

    1. DIRECT_IMPORT
       Fastest approach; requires exact Python version match.
       Uses the standard ``importlib`` machinery.
    2. MARSHAL_LOAD
       Direct bytecode reading using the ``marshal`` module,
       bypassing importlib for greater control.
    3. RECOMPILE
       Decompile the bytecode to source, then recompile for the
       current Python version.
    4. EXTRACT_SOURCE
       Decompile and execute the reconstructed source code directly
       without intermediate compilation to bytecode.
    5. TEMP_COMPILE
       Write decompiled source to a temporary file and compile it
       using the standard compilation pipeline.
    6. FALLBACK_INTERPRETER
       Locate and use a compatible Python interpreter installation
       to execute the bytecode.
    7. BYTECODE_TRANSFORM
       Apply bytecode-level transformations to adapt opcodes for
       cross-version compatibility.

    Notes
    -----
    The `auto()` function assigns automatically incrementing integer
    values to each member. The order of definition determines both
    the numeric values and the default strategy execution order.

    Examples
    --------
    >>> LoadStrategy.DIRECT_IMPORT.value
    1
    >>> LoadStrategy.BYTECODE_TRANSFORM.value
    7
    >>> list(LoadStrategy)
    [<LoadStrategy.DIRECT_IMPORT: 1>, ..., <LoadStrategy.BYTECODE_TRANSFORM: 7>]
    """
    DIRECT_IMPORT = auto()
    MARSHAL_LOAD = auto()
    RECOMPILE = auto()
    EXTRACT_SOURCE = auto()
    TEMP_COMPILE = auto()
    FALLBACK_INTERPRETER = auto()
    BYTECODE_TRANSFORM = auto()


# ============================================================================
# Dataclasses for Structured Outputs
# ============================================================================

@dataclass(frozen=True)
class PlatformInfo:
    """
    Platform identification information.

    Encapsulates the operating system, machine architecture, and
    pointer size (bit width) of the current or target platform.
    Used throughout the loader to track compatibility and provide
    diagnostic information.

    Parameters
    ----------
    system : str
        Operating system name in lowercase, e.g., ``'linux'``,
        ``'windows'``, ``'darwin'`` (macOS).
    machine : str
        Machine architecture identifier, e.g., ``'x86_64'``,
        ``'arm64'``, ``'aarch64'``.
    bits : int
        Architecture pointer size in bits, either ``32`` or ``64``.
        Determined via ``struct.calcsize("P") * 8``.

    Attributes
    ----------
    identifier : str
        Computed property returning the canonical platform identifier
        string in the format ``"system-machine-bits"``.

    Notes
    -----
    This dataclass is frozen (immutable) to ensure platform information
    remains consistent throughout the lifetime of loader operations.

    Examples
    --------
    >>> info = PlatformInfo("linux", "x86_64", 64)
    >>> str(info)
    'linux-x86_64-64'
    >>> info.identifier
    'linux-x86_64-64'
    >>> info.bits
    64
    """
    system: str
    machine: str
    bits: int

    @property
    def identifier(self) -> str:
        """
        Get the full platform identifier string.

        Combines system, machine, and bit width into a canonical
        string representation used for platform comparison and
        logging.

        Returns
        -------
        str
            Platform identifier in the format ``"system-machine-bits"``,
            e.g., ``"linux-x86_64-64"`` or ``"windows-arm64-64"``.

        Examples
        --------
        >>> PlatformInfo("darwin", "arm64", 64).identifier
        'darwin-arm64-64'
        """
        return f"{self.system}-{self.machine}-{self.bits}"

    def __str__(self) -> str:
        """
        Return the platform identifier as the string representation.

        Returns
        -------
        str
            The platform identifier string.
        """
        return self.identifier


@dataclass(frozen=True)
class CompilationFlags:
    """
    Compilation flags extracted from .pyc header.

    Represents the flags field from the bytecode file header, which
    encodes information about how the bytecode was compiled, including
    whether hash-based validation (PEP 552) is enabled and whether
    optimizations were applied.

    Parameters
    ----------
    hash_based : bool, optional
        Whether the .pyc was compiled with hash-based validation
        as specified in PEP 552. When ``True``, the timestamp field
        may be zero and validation is performed via source hash
        comparison. Default is ``False``.
    checked_hash : bool, optional
        Whether the hash has been verified against the source file.
        Relevant only when ``hash_based`` is ``True``. Default is
        ``False``.
    optimized : bool, optional
        Whether bytecode optimizations were applied during compilation
        (equivalent to the ``-O`` or ``-OO`` command-line flags).
        Default is ``False``.
    flags_raw : int, optional
        The raw 32-bit flags value as read from the .pyc header,
        before parsing into individual flag bits. Default is ``0``.

    Attributes
    ----------
    is_validated : bool
        Computed property returning ``True`` only when both
        ``hash_based`` and ``checked_hash`` are ``True``.

    Notes
    -----
    The flags field occupies bytes 4-7 (0-indexed) of the .pyc header
    for Python 3.7+ and is stored as a little-endian unsigned 32-bit
    integer. The bit layout is:

    - Bit 0 (0x1): Hash-based .pyc (PEP 552)
    - Bit 1 (0x2): Checked hash (PEP 552)
    - Other bits: Reserved for future use

    References
    ----------
    .. [1] PEP 552 - Deterministic pycs
           https://www.python.org/dev/peps/pep-0552/

    Examples
    --------
    >>> flags = CompilationFlags(hash_based=True, checked_hash=False, flags_raw=1)
    >>> flags.is_validated
    False

    >>> flags = CompilationFlags(hash_based=True, checked_hash=True, flags_raw=3)
    >>> flags.is_validated
    True
    """
    hash_based: bool = False
    checked_hash: bool = False
    optimized: bool = False
    flags_raw: int = 0

    @property
    def is_validated(self) -> bool:
        """
        Check if the bytecode has been fully validated.

        Returns ``True`` only when the bytecode was compiled with
        hash-based validation (PEP 552) and the hash has been
        verified against the source file.

        Returns
        -------
        bool
            ``True`` if both ``hash_based`` and ``checked_hash``
            are ``True``, indicating a fully validated .pyc file;
            ``False`` otherwise.

        Notes
        -----
        Unvalidated hash-based .pyc files (where ``hash_based`` is
        ``True`` but ``checked_hash`` is ``False``) may indicate
        that the source file was not available for validation at
        compile time.

        Examples
        --------
        >>> CompilationFlags(hash_based=True, checked_hash=True).is_validated
        True
        >>> CompilationFlags(hash_based=True, checked_hash=False).is_validated
        False
        """
        return self.hash_based and self.checked_hash


@dataclass(frozen=True)
class BytecodeMetadata:
    """
    Comprehensive metadata container for Python bytecode files.

    Aggregates all information extracted from a .pyc file header
    and additional computed properties such as file hash, platform
    information, and compatibility assessment. This dataclass is
    the primary structured output for version detection and
    inspection operations.

    Parameters
    ----------
    magic_number : int
        The 4-byte magic number identifying the Python version
        that produced the bytecode. Stored as a 32-bit integer.
    python_version : Tuple[int, int]
        The Python version tuple ``(major, minor)`` derived from
        the magic number.
    timestamp : datetime
        The compilation timestamp as a timezone-aware UTC datetime.
        For hash-based .pyc files (PEP 552), this may be set to the
        Unix epoch (1970-01-01).
    source_size : int
        The original .py source file size in bytes, as recorded in
        the .pyc header. Used for validation.
    code_hash : str
        SHA-256 hexadecimal digest of the entire .pyc file, used
        for integrity verification and cache key generation.
    platform : PlatformInfo
        Platform information where the bytecode file is being
        processed (not where it was originally compiled).
    file_size : int, optional
        Total size of the .pyc file on disk, in bytes. Default is 0.
    flags : CompilationFlags, optional
        Compilation flags parsed from the .pyc header. Default is
        a ``CompilationFlags`` instance with all fields set to
        their defaults.
    is_compatible : bool, optional
        Whether the bytecode is directly compatible with the current
        Python interpreter version. ``True`` when the bytecode version
        matches exactly. Default is ``False``.
    is_hash_based : bool, optional
        Whether this is a hash-based .pyc file as specified in PEP 552.
        Determined by checking if the timestamp is the Unix epoch.
        Default is ``False``.

    Attributes
    ----------
    version_string : str
        Computed property returning the Python version as a dotted
        string, e.g., ``"3.11"``.
    magic_hex : str
        Computed property returning the magic number as a hexadecimal
        string with ``0x`` prefix, e.g., ``"0x00000f0e"``.

    Notes
    -----
    The .pyc file header structure for Python 3.6+ is:

    =========== ====== =============================
    Bytes       Size   Field
    =========== ====== =============================
    0-1         2      Magic number (low 16 bits)
    2-3         2      Magic number (high 16 bits)
    4-7         4      Flags (PEP 552 bitfield)
    8-11        4      Timestamp (Unix timestamp)
    12-15       4      Source file size
    =========== ====== =============================

    References
    ----------
    .. [1] PEP 3147 - PYC Repository Directories
    .. [2] PEP 552 - Deterministic pycs

    Examples
    --------
    >>> meta = BytecodeMetadata(
    ...     magic_number=3423, python_version=(3, 9),
    ...     timestamp=datetime.now(timezone.utc), source_size=1024,
    ...     code_hash="abc123...", platform=PlatformInfo("linux", "x86_64", 64),
    ...     file_size=2048, flags=CompilationFlags()
    ... )
    >>> meta.version_string
    '3.9'
    >>> meta.magic_hex
    '0x00000d5f'
    >>> meta.is_compatible
    False
    """
    magic_number: int
    python_version: Tuple[int, int]
    timestamp: datetime
    source_size: int
    code_hash: str
    platform: PlatformInfo
    file_size: int = 0
    flags: CompilationFlags = field(default_factory=CompilationFlags)
    is_compatible: bool = False
    is_hash_based: bool = False

    @property
    def version_string(self) -> str:
        """
        Get the Python version as a dotted string.

        Formats the major and minor version components into a
        human-readable string.

        Returns
        -------
        str
            Version string in the format ``"major.minor"``, e.g.,
            ``"3.9"`` or ``"3.12"``.

        Examples
        --------
        >>> meta = BytecodeMetadata(..., python_version=(3, 11))
        >>> meta.version_string
        '3.11'
        """
        return f"{self.python_version[0]}.{self.python_version[1]}"

    @property
    def magic_hex(self) -> str:
        """
        Get the magic number as a hexadecimal string.

        Formats the 32-bit magic number as a zero-padded 8-digit
        hexadecimal value with ``0x`` prefix.

        Returns
        -------
        str
            Hexadecimal representation of the magic number, e.g.,
            ``"0x00000f0e"`` for Python 3.11.

        Examples
        --------
        >>> meta = BytecodeMetadata(..., magic_number=0x0f0e)
        >>> meta.magic_hex
        '0x00000f0e'
        """
        return f"0x{self.magic_number:08x}"


@dataclass(frozen=True)
class LoaderStatistics:
    """
    Runtime statistics for loader operations.

    Accumulates performance and usage metrics across all load
    operations performed by a PycLoader instance. Provides
    computed properties for derived statistics such as success
    rate and most-used strategy.

    Parameters
    ----------
    loads_attempted : int, optional
        Total number of load operations attempted. Default is 0.
    loads_succeeded : int, optional
        Number of load operations that completed successfully.
        Default is 0.
    loads_failed : int, optional
        Number of load operations that failed after exhausting
        all strategies. Default is 0.
    cache_hits : int, optional
        Number of loads served from the cache rather than by
        executing a strategy. Default is 0.
    strategies_used : Dict[str, int], optional
        Mapping from strategy name (as ``str``) to the number of
        times that strategy successfully loaded a module. Default
        is an empty dictionary.
    average_load_time_ms : float, optional
        Average load time across all operations, measured in
        milliseconds. Default is 0.0.
    cache_size : int, optional
        Current number of modules held in the memory cache.
        Default is 0.

    Attributes
    ----------
    success_rate : float
        Computed property returning the ratio of successful loads
        to total attempts as a float between 0.0 and 1.0.
    most_used_strategy : Optional[str]
        Computed property returning the name of the most frequently
        used strategy, or ``None`` if no strategies have been used.

    Notes
    -----
    Statistics are accumulated per ``PycLoader`` instance and are
    not shared between instances. Use the ``statistics`` property
    of a ``PycLoader`` to obtain a snapshot.

    Examples
    --------
    >>> stats = LoaderStatistics(
    ...     loads_attempted=10, loads_succeeded=8, loads_failed=2,
    ...     cache_hits=3, strategies_used={"DIRECT_IMPORT": 5, "MARSHAL_LOAD": 3},
    ...     average_load_time_ms=45.2, cache_size=5
    ... )
    >>> stats.success_rate
    0.8
    >>> stats.most_used_strategy
    'DIRECT_IMPORT'
    """
    loads_attempted: int = 0
    loads_succeeded: int = 0
    loads_failed: int = 0
    cache_hits: int = 0
    strategies_used: Dict[str, int] = field(default_factory=dict)
    average_load_time_ms: float = 0.0
    cache_size: int = 0

    @property
    def success_rate(self) -> float:
        """
        Calculate the success rate of load operations.

        Divides the number of successful loads by the total number
        of attempts. Returns 0.0 when no loads have been attempted
        to avoid division by zero.

        Returns
        -------
        float
            Success rate as a value between ``0.0`` (all failed)
            and ``1.0`` (all succeeded). Returns ``0.0`` when
            ``loads_attempted`` is 0.

        Examples
        --------
        >>> LoaderStatistics(loads_attempted=5, loads_succeeded=3).success_rate
        0.6
        >>> LoaderStatistics(loads_attempted=0).success_rate
        0.0
        """
        if self.loads_attempted == 0:
            return 0.0
        return self.loads_succeeded / self.loads_attempted

    @property
    def most_used_strategy(self) -> Optional[str]:
        """
        Get the most frequently used strategy name.

        Identifies the strategy with the highest usage count in
        the ``strategies_used`` dictionary.

        Returns
        -------
        Optional[str]
            The name of the most-used strategy as a string, or
            ``None`` if no strategies have been recorded.

        Notes
        -----
        If multiple strategies share the highest count, the one
        that appears first in dictionary iteration order is
        returned (behavior of ``max`` with a key function).

        Examples
        --------
        >>> stats = LoaderStatistics(
        ...     strategies_used={"DIRECT_IMPORT": 5, "RECOMPILE": 2}
        ... )
        >>> stats.most_used_strategy
        'DIRECT_IMPORT'
        """
        if not self.strategies_used:
            return None
        return max(self.strategies_used, key=self.strategies_used.get)


@dataclass(frozen=True)
class LoadResult:
    """
    Result of a bytecode loading operation.

    Encapsulates the loaded module, its metadata, the strategy
    that succeeded, timing information, and any warnings or
    extracted source code. This is the primary return type for
    the ``load()`` method.

    Parameters
    ----------
    module : ModuleType
        The successfully loaded Python module object. Contains
        all the module's attributes, functions, and classes as
        populated during execution.
    metadata : BytecodeMetadata
        Comprehensive metadata about the loaded bytecode file,
        including version, platform, and compilation flags.
    strategy_used : LoadStrategy
        The loading strategy that ultimately succeeded in loading
        the module after the fallback chain was exhausted.
    load_time_ms : float
        Total time taken to load the module, measured in milliseconds
        from the start of the ``load()`` call to the successful
        return.
    source : Optional[str], optional
        Extracted or decompiled source code, if the loading strategy
        involved decompilation. ``None`` otherwise. Default is ``None``.
    warnings : List[str], optional
        Any warning messages generated during the loading process,
        such as suspicious code patterns or deprecation notices.
        Default is an empty list.

    Attributes
    ----------
    has_source : bool
        Computed property returning ``True`` if non-empty source code
        was extracted during loading.

    Notes
    -----
    The ``module`` attribute is a standard Python module object and
    can be used directly to access module contents:

    >>> result.module.some_function()
    >>> result.module.SOME_CONSTANT

    Examples
    --------
    >>> result = loader.load("module.pyc", "mymodule")
    >>> print(f"Loaded using {result.strategy_used.name}")
    >>> print(f"Version: {result.metadata.version_string}")
    >>> result.module.my_function()
    >>> if result.has_source:
    ...     print("Source code is available")
    """
    module: ModuleType
    metadata: BytecodeMetadata
    strategy_used: LoadStrategy
    load_time_ms: float
    source: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def has_source(self) -> bool:
        """
        Check if source code was extracted during loading.

        Indicates whether the loading strategy produced readable
        Python source code (e.g., via decompilation). Source code
        is available when the ``source`` attribute is a non-empty
        string.

        Returns
        -------
        bool
            ``True`` if the ``source`` attribute is not ``None``
            and contains at least one character; ``False`` otherwise.

        Examples
        --------
        >>> result = loader.load("module.pyc")
        >>> if result.has_source:
        ...     with open("recovered.py", "w") as f:
        ...         f.write(result.source)
        """
        return self.source is not None and len(self.source) > 0


@dataclass(frozen=True)
class LoadError:
    """
    Detailed error information for a failed load operation.

    Provides structured diagnostic information when all loading
    strategies have been exhausted. Includes the error context,
    the strategy that failed last, actionable suggestions for
    resolution, and any available metadata from the bytecode file.

    Parameters
    ----------
    message : str
        Human-readable error description summarizing the failure.
    strategy : Optional[LoadStrategy], optional
        The last strategy that was attempted before the failure
        was recorded. ``None`` if no strategies were attempted.
        Default is ``None``.
    error_type : str, optional
        The fully qualified name of the exception class that caused
        the final failure, e.g., ``"ImportError"`` or ``"ValueError"``.
        Default is an empty string.
    error_message : str, optional
        The message string from the final exception. Truncated to
        500 characters in some contexts to avoid excessively long
        output. Default is an empty string.
    metadata : Optional[BytecodeMetadata], optional
        Bytecode metadata if it could be extracted before the
        failure occurred. ``None`` if the file could not be read
        at all. Default is ``None``.
    suggestions : List[str], optional
        Actionable suggestions for resolving the error, generated
        based on the patterns of failures observed. Default is an
        empty list.
    diagnostics : Dict[str, Any], optional
        Additional diagnostic information as key-value pairs, such
        as the number of strategies attempted and the file size.
        Default is an empty dictionary.
    timestamp : datetime, optional
        When the error occurred, as a timezone-aware UTC datetime.
        Default is the current time at instantiation.

    Notes
    -----
    This dataclass is typically wrapped in a ``PycLoadError``
    exception, accessible via the ``error_info`` attribute:

    >>> try:
    ...     loader.load("bad.pyc")
    ... except PycLoadError as e:
    ...     for suggestion in e.error_info.suggestions:
    ...         print(f"Suggestion: {suggestion}")

    Examples
    --------
    >>> error = LoadError(
    ...     message="File not found",
    ...     strategy=LoadStrategy.DIRECT_IMPORT,
    ...     error_type="FileNotFoundError",
    ...     error_message="No such file: missing.pyc",
    ...     suggestions=["Check the file path", "Ensure the file exists"]
    ... )
    >>> len(error.suggestions)
    2
    """
    message: str
    strategy: Optional[LoadStrategy] = None
    error_type: str = ""
    error_message: str = ""
    metadata: Optional[BytecodeMetadata] = None
    suggestions: List[str] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class DecompilerInfo:
    """
    Information about an available decompiler backend.

    Describes the capabilities, availability, and version of a
    decompiler backend. Used by the loader to select the most
    appropriate decompiler for a given task.

    Parameters
    ----------
    name : str
        Decompiler name identifier, e.g., ``"decompyle3"``,
        ``"uncompyle6"``, ``"pycdc"``, ``"dis"``.
    available : bool
        Whether the decompiler is currently available on the
        system. ``True`` if the package is installed or the
        external tool is found in PATH.
    version : Optional[str], optional
        Version string of the installed decompiler, if available.
        ``None`` if version cannot be determined. Default is ``None``.
    is_external : bool, optional
        Whether the decompiler requires external tools (separate
        process execution) rather than being a pure Python library.
        Default is ``False``.
    capabilities : List[str], optional
        List of supported feature strings, such as
        ``"full_decompile"``, ``"cross_version"``,
        ``"disassembly"``, or ``"external_tool"``. Default is an
        empty list.

    Notes
    -----
    The ``capabilities`` list is used for feature detection. The
    ``supports()`` method provides a convenient way to check for
    specific capabilities.

    Examples
    --------
    >>> info = DecompilerInfo(
    ...     name="decompyle3", available=True, version="1.0.0",
    ...     is_external=True, capabilities=["full_decompile", "cross_version"]
    ... )
    >>> info.supports("cross_version")
    True
    >>> info.supports("disassembly")
    False
    """
    name: str
    available: bool
    version: Optional[str] = None
    is_external: bool = False
    capabilities: List[str] = field(default_factory=list)

    def supports(self, capability: str) -> bool:
        """
        Check if this decompiler supports a specific capability.

        Tests whether the given capability string appears in the
        ``capabilities`` list.

        Parameters
        ----------
        capability : str
            The capability to check for, e.g., ``"full_decompile"``
            or ``"cross_version"``.

        Returns
        -------
        bool
            ``True`` if the capability is present in the
            ``capabilities`` list; ``False`` otherwise.

        Examples
        --------
        >>> info = DecompilerInfo(
        ...     name="dis", capabilities=["disassembly"]
        ... )
        >>> info.supports("disassembly")
        True
        >>> info.supports("full_decompile")
        False
        """
        return capability in self.capabilities


@dataclass(frozen=True)
class InspectionResult:
    """
    Detailed inspection results for a .pyc file.

    Provides comprehensive information about the code object stored
    within a .pyc file, including metadata, bytecode statistics,
    variable names, and structural information. Suitable for analysis
    and debugging of compiled Python modules.

    Parameters
    ----------
    metadata : BytecodeMetadata
        Full bytecode metadata including version, platform, and
        compilation information.
    code_name : str
        Name of the top-level code object, typically ``"<module>"``
        for module-level code or the function/class name for nested
        code objects.
    code_filename : str
        Original filename from which the code object was compiled,
        as stored in ``co_filename``.
    argument_count : int
        Number of positional arguments expected by the code object
        (``co_argcount``). Always 0 for module-level code.
    local_count : int
        Number of local variables used by the code object
        (``co_nlocals``).
    stack_size : int
        Maximum evaluation stack depth required by the code object
        (``co_stacksize``).
    code_flags : int
        Code object flags as a bitfield (``co_flags``). Determines
        properties such as whether the code accepts ``*args`` or
        ``**kwargs``.
    bytecode_size : int
        Total size of the raw bytecode instructions in bytes
        (length of ``co_code``).
    constants_count : int
        Number of constants in the code object's constant table
        (length of ``co_consts``).
    names : List[str]
        Names used in the code object (``co_names``), including
        global variable names, function names, and attribute names.
    variable_names : List[str]
        Local variable names used in the code object
        (``co_varnames``).
    nested_code_objects : int, optional
        Number of nested code objects found within the constants
        table, representing inner functions, classes, or
        comprehensions. Default is 0.
    instruction_count : int, optional
        Total number of bytecode instructions in the code object.
        Default is 0.

    Attributes
    ----------
    is_function : bool
        Computed property returning ``True`` if the code object
        represents a named function (``code_name != "<module>"``).

    Notes
    -----
    Inspection does not execute any bytecode; it only reads and
    analyzes the code object structure.

    References
    ----------
    .. [1] inspect — Inspect live objects
           https://docs.python.org/3/library/inspect.html
    .. [2] dis — Disassembler for Python bytecode
           https://docs.python.org/3/library/dis.html

    Examples
    --------
    >>> info = inspect_pyc("module.pyc")
    >>> print(f"Function: {info.code_name}")
    >>> print(f"Arguments: {info.argument_count}")
    >>> print(f"Bytecode size: {info.bytecode_size} bytes")
    >>> if info.is_function:
    ...     print("This is a function, not a module")
    """
    metadata: BytecodeMetadata
    code_name: str
    code_filename: str
    argument_count: int
    local_count: int
    stack_size: int
    code_flags: int
    bytecode_size: int
    constants_count: int
    names: List[str]
    variable_names: List[str]
    nested_code_objects: int = 0
    instruction_count: int = 0

    @property
    def is_function(self) -> bool:
        """
        Check if the code object represents a function.

        Determines whether the inspected code object is a named
        function (as opposed to module-level code) by checking if
        ``code_name`` is not the module sentinel ``"<module>"``.

        Returns
        -------
        bool
            ``True`` if ``code_name`` is not ``"<module>"``,
            indicating a function, class, or other named code block;
            ``False`` if it is module-level code.

        Examples
        --------
        >>> InspectionResult(..., code_name="my_function").is_function
        True
        >>> InspectionResult(..., code_name="<module>").is_function
        False
        """
        return self.code_name != '<module>'


@dataclass(frozen=True)
class BatchLoadResult:
    """
    Results from a batch loading operation.

    Aggregates the outcomes of loading multiple .pyc files in a
    single operation, separating successes from failures and
    providing timing information.

    Parameters
    ----------
    successful : Dict[str, LoadResult], optional
        Mapping from module names to their ``LoadResult`` objects
        for all modules loaded successfully. Default is an empty
        dictionary.
    failed : Dict[str, LoadError], optional
        Mapping from module names to their ``LoadError`` objects
        for all modules that failed to load. Default is an empty
        dictionary.
    total_time_ms : float, optional
        Total wall-clock time for the entire batch operation,
        measured in milliseconds. Default is 0.0.
    parallel : bool, optional
        Whether parallel (concurrent) loading was used for this
        batch operation. Default is ``False``.

    Attributes
    ----------
    success_rate : float
        Computed property returning the ratio of successful loads
        to total modules processed.
    all_modules : Dict[str, ModuleType]
        Computed property returning a dictionary of successfully
        loaded module objects, keyed by name.

    Notes
    -----
    The ``all_modules`` property provides direct access to module
    objects without the surrounding ``LoadResult`` wrappers:

    >>> batch_result.all_modules["my_module"].some_function()

    Examples
    --------
    >>> result = batch_load_pyc(["a.pyc", "b.pyc"], names=["mod_a", "mod_b"])
    >>> print(f"Loaded: {len(result.successful)}, Failed: {len(result.failed)}")
    >>> for name, error in result.failed.items():
    ...     print(f"  {name}: {error.message}")
    >>> for name, module in result.all_modules.items():
    ...     print(f"  {name}: {type(module).__name__}")
    """
    successful: Dict[str, LoadResult] = field(default_factory=dict)
    failed: Dict[str, LoadError] = field(default_factory=dict)
    total_time_ms: float = 0.0
    parallel: bool = False

    @property
    def success_rate(self) -> float:
        """
        Calculate the success rate of the batch operation.

        Divides the number of successful loads by the total number
        of modules processed (successful + failed).

        Returns
        -------
        float
            Success rate as a value between ``0.0`` (all failed)
            and ``1.0`` (all succeeded). Returns ``0.0`` if no
            modules were processed.

        Examples
        --------
        >>> BatchLoadResult(successful={"a": result1}, failed={"b": error1}).success_rate
        0.5
        """
        total = len(self.successful) + len(self.failed)
        return len(self.successful) / total if total > 0 else 0.0

    @property
    def all_modules(self) -> Dict[str, ModuleType]:
        """
        Get all successfully loaded modules.

        Extracts the ``module`` attribute from each successful
        ``LoadResult``, providing direct access to the module
        objects.

        Returns
        -------
        Dict[str, ModuleType]
            Dictionary mapping module names to their corresponding
            ``ModuleType`` objects for all successfully loaded
            modules.

        Examples
        --------
        >>> result = batch_load_pyc(["mod.pyc"], names=["mod"])
        >>> result.all_modules
        {'mod': <module 'mod' ...>}
        """
        return {name: result.module for name, result in self.successful.items()}


@dataclass
class LoaderConfig:
    """
    Configuration settings for customizing PycLoader behavior.

    Provides fine-grained control over all aspects of the loading
    process, including strategy selection, caching, security,
    parallelism, and logging. All fields have sensible defaults
    suitable for most use cases.

    Parameters
    ----------
    strategies : List[LoadStrategy], optional
        Ordered list of strategies to attempt during loading. The
        loader will try each strategy in sequence until one succeeds.
        Default: all seven strategies in order of efficiency
        (DIRECT_IMPORT through BYTECODE_TRANSFORM).
    timeout : int, optional
        Maximum time in seconds for decompilation and subprocess
        operations. Prevents hanging on external tool calls.
        Default is 30.
    secure_mode : bool, optional
        When ``True``, enables security restrictions including:
        disabling external decompilers, blocking suspicious bytecode
        patterns, and preventing fallback interpreter usage. Default
        is ``False``.
    temp_dir : Optional[Path], optional
        Custom directory for temporary files created during loading
        (e.g., by the TEMP_COMPILE strategy). Uses the system
        temporary directory when ``None``. Default is ``None``.
    preserve_temp : bool, optional
        When ``True``, temporary files are kept after loading for
        debugging purposes. When ``False``, they are cleaned up
        automatically. Default is ``False``.
    log_level : int, optional
        Python logging level constant (e.g., ``logging.DEBUG``,
        ``logging.INFO``, ``logging.WARNING``). Controls the
        verbosity of log output. Default is ``logging.WARNING``.
    max_recursion : int, optional
        Maximum recursion depth allowed for code object validation.
        Prevents stack overflow attacks from deeply nested bytecode.
        Default is 100.
    cache_enabled : bool, optional
        When ``True``, enables multi-level caching (memory + disk)
        of loaded modules. Cached modules are validated by file
        modification time. Default is ``True``.
    cache_dir : Optional[Path], optional
        Directory for persistent disk cache. When ``None``, uses
        ``<tempdir>/pyputil.pyc_cache``. Default is ``None``.
    max_cache_size : int, optional
        Maximum number of entries in the in-memory cache. When
        exceeded, the oldest entry is evicted (LRU policy).
        Default is 100.
    parallel_loading : bool, optional
        When ``True``, strategies are attempted in parallel using
        a thread pool rather than sequentially. May provide faster
        loading for complex files. Default is ``False``.
    max_workers : int, optional
        Maximum number of worker threads in the thread pool used
        for parallel loading. Only relevant when ``parallel_loading``
        is ``True``. Default is 4.
    validate_bytecode : bool, optional
        When ``True``, enables bytecode validation that checks for
        excessive code size, deep recursion, and suspicious patterns.
        Default is ``True``.
    decompiler_preference : List[str], optional
        Ordered list of preferred decompiler names. The loader will
        attempt to use decompilers in this order. Default:
        ``["decompyle3", "uncompyle6", "pycdc", "dis"]``.

    Notes
    -----
    This is a mutable dataclass (not frozen), allowing configuration
    to be modified after creation. The ``__repr__`` method provides
    a concise summary of the most important settings.

    Examples
    --------
    >>> # Basic configuration with enhanced security
    >>> config = LoaderConfig(secure_mode=True, cache_enabled=False)

    >>> # Performance-optimized configuration
    >>> config = LoaderConfig(
    ...     parallel_loading=True,
    ...     max_workers=8,
    ...     cache_enabled=True,
    ...     max_cache_size=200
    ... )

    >>> # Debugging configuration
    >>> config = LoaderConfig(
    ...     log_level=logging.DEBUG,
    ...     preserve_temp=True,
    ...     timeout=120
    ... )
    """
    strategies: List[LoadStrategy] = field(default_factory=lambda: [
        LoadStrategy.DIRECT_IMPORT,
        LoadStrategy.MARSHAL_LOAD,
        LoadStrategy.RECOMPILE,
        LoadStrategy.EXTRACT_SOURCE,
        LoadStrategy.TEMP_COMPILE,
        LoadStrategy.FALLBACK_INTERPRETER,
        LoadStrategy.BYTECODE_TRANSFORM,
    ])
    timeout: int = 30
    secure_mode: bool = False
    temp_dir: Optional[Path] = None
    preserve_temp: bool = False
    log_level: int = logging.WARNING
    max_recursion: int = 100
    cache_enabled: bool = True
    cache_dir: Optional[Path] = None
    max_cache_size: int = 100
    parallel_loading: bool = False
    max_workers: int = 4
    validate_bytecode: bool = True
    decompiler_preference: List[str] = field(default_factory=lambda: [
        "decompyle3", "uncompyle6", "pycdc", "dis"
    ])

    def __repr__(self) -> str:
        """
        Return a concise string representation of the configuration.

        Formats the most important configuration parameters into a
        compact, human-readable string.

        Returns
        -------
        str
            String representation showing timeout, secure mode,
            cache status, and parallel loading status.
        """
        return (
            f"LoaderConfig(timeout={self.timeout}s, "
            f"secure={self.secure_mode}, "
            f"cache={'on' if self.cache_enabled else 'off'}, "
            f"parallel={'on' if self.parallel_loading else 'off'})"
        )


@dataclass(frozen=True)
class CacheEntry:
    """
    A single entry in the module cache.

    Stores a cached module along with its metadata and access
    statistics. Used by the internal caching system to avoid
    redundant loading of previously processed modules.

    Parameters
    ----------
    module : ModuleType
        The cached Python module object. This field is excluded
        from hash and equality comparisons due to potential issues
        with comparing module objects.
    metadata : BytecodeMetadata
        Metadata associated with the cached module, including
        version and platform information.
    cached_at : datetime, optional
        When the module was added to the cache, as a timezone-aware
        UTC datetime. Default is the current time at instantiation.
    file_mtime : float, optional
        The modification time of the .pyc file when it was cached,
        used to detect stale cache entries. Default is 0.0.
    access_count : int, optional
        Number of times this cache entry has been accessed (cache
        hits). Not currently automatically incremented. Default is 0.

    Attributes
    ----------
    age_seconds : float
        Computed property returning the age of this cache entry in
        seconds since ``cached_at``.

    Notes
    -----
    The ``module`` and ``metadata`` fields use ``compare=False``
    and ``hash=False`` to prevent issues with module comparison
    and to keep the dataclass hashable for use in dictionaries.

    Examples
    --------
    >>> entry = CacheEntry(module=my_module, metadata=meta)
    >>> entry.age_seconds > 0
    True
    """
    module: ModuleType = field(compare=False, hash=False)
    metadata: BytecodeMetadata = field(compare=False, hash=False)
    cached_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    file_mtime: float = 0.0
    access_count: int = 0

    @property
    def age_seconds(self) -> float:
        """
        Get the age of this cache entry in seconds.

        Computes the elapsed time since the entry was cached by
        subtracting ``cached_at`` from the current UTC time.

        Returns
        -------
        float
            Age of the cache entry in seconds, as a floating-point
            number. Always non-negative.

        Examples
        --------
        >>> import time
        >>> entry = CacheEntry(module=mod, metadata=meta)
        >>> time.sleep(0.1)
        >>> entry.age_seconds >= 0.1
        True
        """
        return (datetime.now(timezone.utc) - self.cached_at).total_seconds()


# ============================================================================
# Custom Exceptions
# ============================================================================

class PycLoadError(Exception):
    """
    Custom exception for bytecode loading failures with detailed diagnostics.

    Raised when all loading strategies have been exhausted without
    successfully loading the bytecode. Wraps a ``LoadError`` dataclass
    that contains comprehensive diagnostic information.

    Parameters
    ----------
    error_info : LoadError
        A populated ``LoadError`` instance containing the failure
        details, attempted strategy, error messages, and actionable
        suggestions.

    Attributes
    ----------
    error_info : LoadError
        The structured error information dataclass.

    Notes
    -----
    The ``__str__`` method provides a detailed, multi-line formatted
    error message suitable for logging and debugging. It includes:

    - The main error message
    - Timestamp of the failure
    - The strategy that was last attempted
    - The underlying exception type and message
    - Bytecode metadata (if available)
    - Additional diagnostics
    - Actionable suggestions

    Examples
    --------
    >>> try:
    ...     loader.load("corrupted.pyc")
    ... except PycLoadError as e:
    ...     print(e.error_info.message)
    ...     for suggestion in e.error_info.suggestions:
    ...         print(f"  - {suggestion}")
    ...     # Print the full formatted error
    ...     print(e)
    """

    def __init__(self, error_info: LoadError):
        """
        Initialize the exception with structured error information.

        Parameters
        ----------
        error_info : LoadError
            A ``LoadError`` instance containing the failure details.
        """
        super().__init__(error_info.message)
        self.error_info = error_info

    def __str__(self) -> str:
        """
        Format error with full diagnostic information.

        Constructs a multi-line string containing all available
        error details in a structured, human-readable format.

        Returns
        -------
        str
            Multi-line formatted error message containing the
            message, timestamp, strategy, cause, metadata,
            diagnostics, and suggestions.
        """
        info = self.error_info
        parts = [
            f"PycLoadError: {info.message}",
            f"Timestamp: {info.timestamp.isoformat()}",
        ]
        if info.strategy:
            parts.append(f"Strategy: {info.strategy.name}")
        if info.error_type:
            parts.append(f"Cause: {info.error_type}: {info.error_message[:200]}")
        if info.metadata:
            parts.append(f"Version: {info.metadata.version_string}")
            parts.append(f"Platform: {info.metadata.platform.identifier}")
        if info.diagnostics:
            parts.append("Diagnostics:")
            for key, value in info.diagnostics.items():
                parts.append(f"  {key}: {value}")
        if info.suggestions:
            parts.append("Suggestions:")
            for i, suggestion in enumerate(info.suggestions, 1):
                parts.append(f"  {i}. {suggestion}")
        return "\n".join(parts)


# ============================================================================
# Utility Decorators
# ============================================================================

def timed_operation(func: Callable[..., T]) -> Callable[..., T]:
    """
    Decorator to measure and log the execution time of operations.

    Wraps a function to record its execution time using
    ``time.perf_counter()`` for high-resolution timing. The
    elapsed time is logged at the ``DEBUG`` level. If the function
    raises an exception, the elapsed time before failure is also
    logged.

    Parameters
    ----------
    func : Callable[..., T]
        The function or method to be timed. Can accept any arguments
        and return any type.

    Returns
    -------
    Callable[..., T]
        Wrapped function that transparently adds timing measurement
        and logging. Preserves the original function's signature,
        name, and docstring via ``functools.wraps``.

    Notes
    -----
    Timing is measured using ``time.perf_counter()``, which provides
    the highest available resolution and is not affected by system
    clock adjustments. The elapsed time is formatted to 3 decimal
    places.

    Log Messages
    ------------
    On success:
        ``"<func_name> completed in <elapsed>s"`` at DEBUG level
    On failure:
        ``"<func_name> failed after <elapsed>s: <exception>"`` at
        DEBUG level

    Examples
    --------
    >>> @timed_operation
    ... def expensive_calculation(n):
    ...     return sum(range(n))
    ...
    >>> result = expensive_calculation(1000000)
    # DEBUG: expensive_calculation completed in 0.015s
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        """
        Execute the wrapped function with timing measurement.

        Records the start time before calling the function and
        logs the elapsed time after completion. If the function
        raises an exception, the time to failure is logged before
        re-raising.

        Parameters
        ----------
        *args : Any
            Positional arguments passed to the wrapped function.
        **kwargs : Any
            Keyword arguments passed to the wrapped function.

        Returns
        -------
        T
            The return value of the wrapped function.

        Raises
        ------
        Exception
            Any exception raised by the wrapped function is re-raised
            after logging the timing information.
        """
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            logger.debug("%s completed in %.3fs", func.__name__, elapsed)
            return result
        except Exception as e:
            elapsed = time.perf_counter() - start
            logger.debug("%s failed after %.3fs: %s", func.__name__, elapsed, e)
            raise
    return wrapper


def validate_path(func: Callable) -> Callable:
    """
    Decorator to validate file paths before processing.

    Performs comprehensive security and existence checks on file
    paths passed as the second argument (after ``self``) to bound
    methods. Designed for use with ``PycLoader`` methods.

    Checks performed:

    1. **Path resolution**: Converts to absolute path via
       ``Path.resolve()``.
    2. **Traversal detection**: Rejects paths containing ``".."``
       to prevent directory traversal attacks.
    3. **Existence check**: Verifies the path exists on the
       filesystem.
    4. **Type check**: Ensures the path refers to a regular file,
       not a directory or special file.
    5. **Permission check**: Verifies read access via
       ``os.access(path, os.R_OK)``.

    Parameters
    ----------
    func : Callable
        The bound method to decorate. Must accept ``self`` as the
        first argument and a path as the second argument.

    Returns
    -------
    Callable
        Wrapped function that validates the path argument before
        calling the original function. Preserves the original
        function's metadata via ``functools.wraps``.

    Raises
    ------
    ValueError
        If the path contains ``".."`` (path traversal detected)
        or if the path exists but is not a regular file.
    FileNotFoundError
        If the path does not exist on the filesystem.
    PermissionError
        If the file exists but is not readable by the current
        process.

    Notes
    -----
    This decorator is designed to work with instance methods where
    the path is the second positional argument:

    >>> @validate_path
    ... def load(self, path, name="loaded_module"):
    ...     pass

    Examples
    --------
    >>> @validate_path
    ... def process_file(self, path, *args, **kwargs):
    ...     return path.read_text()
    ...
    >>> process_file(obj, "/etc/passwd")  # May raise PermissionError
    >>> process_file(obj, "../secret.pyc")  # Raises ValueError
    """
    @wraps(func)
    def wrapper(self: Any, path: Union[str, Path], *args: Any, **kwargs: Any) -> Any:
        """
        Validate path before calling the wrapped function.

        Parameters
        ----------
        self : Any
            The instance the method is bound to.
        path : Union[str, Path]
            File path to validate. Both string and ``Path``
            objects are accepted.
        *args : Any
            Additional positional arguments forwarded to the
            wrapped function.
        **kwargs : Any
            Additional keyword arguments forwarded to the
            wrapped function.

        Returns
        -------
        Any
            The return value of the wrapped function.

        Raises
        ------
        ValueError
            If path traversal detected or path is not a regular file.
        FileNotFoundError
            If the file does not exist.
        PermissionError
            If the file is not readable.
        """
        path = Path(path).resolve()

        if ".." in str(path):
            raise ValueError(f"Path traversal detected: {path}")
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not path.is_file():
            raise ValueError(f"Path is not a file: {path}")
        if not os.access(path, os.R_OK):
            raise PermissionError(f"Cannot read file: {path}")

        return func(self, path, *args, **kwargs)
    return wrapper


# ============================================================================
# Core Loader Implementation
# ============================================================================

class PycLoader:
    """
     Python bytecode file loader with multi-strategy fallback.

    Implements multiple loading strategies with automatic fallback,
    comprehensive caching, and detailed diagnostics. All outputs use
    structured dataclasses for type safety and IDE support.

    The loader attempts strategies in the order specified by the
    configuration (or the default order) until one succeeds. It
    supports parallel strategy execution, secure mode for untrusted
    bytecode, and multiple decompilation backends for recovering
    source code from compiled files.

    Parameters
    ----------
    config : LoaderConfig, optional
        Configuration object controlling all aspects of the loader's
        behavior. If ``None``, a default ``LoaderConfig`` is used
        with all standard settings.

    Attributes
    ----------
    config : LoaderConfig
        The active configuration object. Modifications to this
        object after initialization will affect subsequent
        operations.
    decompilers : Dict[str, DecompilerInfo]
        Dictionary mapping decompiler names to their information
        objects. Populated during initialization based on
        availability.
    active_decompiler : Optional[str]
        The name of the currently preferred decompiler, selected
        as the first available decompiler from the preference list.
    statistics : LoaderStatistics (property)
        Current runtime statistics as a ``LoaderStatistics``
        dataclass. Updated after each load operation.

    Notes
    -----
    The class supports the context manager protocol, ensuring
    proper cleanup of thread pools and temporary resources:

    >>> with PycLoader() as loader:
    ...     result = loader.load("module.pyc")

    **Security**: When ``secure_mode`` is enabled, external
    decompilers and fallback interpreters are disabled, and
    bytecode validation scans for suspicious patterns.

    Examples
    --------
    >>> # Basic usage
    >>> loader = PycLoader()
    >>> result = loader.load("compiled.cpython-39.pyc", "mymodule")
    >>> print(result.metadata.version_string)
    3.9
    >>> result.module.my_function()

    >>> # With custom configuration
    >>> config = LoaderConfig(secure_mode=True, parallel_loading=True)
    >>> loader = PycLoader(config)
    >>> result = loader.load("module.pyc")
    >>> print(result.statistics.success_rate)

    >>> # Using context manager
    >>> with PycLoader() as loader:
    ...     result = loader.load("module.pyc")
    """

    MODULE_NAME_PATTERN = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
    """
    Regular expression pattern for validating Python module names.

    Module names must:
    - Start with a letter or underscore
    - Contain only letters, digits, and underscores
    - Be non-empty
    """

    def __init__(self, config: Optional[LoaderConfig] = None):
        """
        Initialize the smart bytecode loader.

        Sets up all internal components including decompiler
        backends, caching system, thread pool executor, and
        environment validation.

        Parameters
        ----------
        config : LoaderConfig, optional
            Configuration object. If ``None``, a default
            ``LoaderConfig`` is used.

        Raises
        ------
        RuntimeError
            If the Python version is earlier than 3.6, which is
            the minimum supported version.

        Notes
        -----
        The initialization process performs the following steps:

        1. Stores the configuration (or creates a default)
        2. Sets the logging level from the configuration
        3. Initializes decompiler backends (``_setup_decompiler``)
        4. Initializes the caching system (``_setup_cache``)
        5. Initializes the thread pool executor (``_setup_executor``)
        6. Validates the runtime environment (``_validate_environment``)
        7. Initializes internal state dictionaries for statistics
        """
        self.config = config or LoaderConfig()
        logger.setLevel(self.config.log_level)

        # Initialize components
        self._setup_decompiler()
        self._setup_cache()
        self._setup_executor()
        self._validate_environment()

        # Internal state
        self._cache_entries: Dict[str, CacheEntry] = {}
        self._load_times: List[float] = []
        self._stats = {
            'loads_attempted': 0,
            'loads_succeeded': 0,
            'loads_failed': 0,
            'strategies_used': {},
            'cache_hits': 0,
        }

        logger.info(
            "PycLoader initialized with %d strategies, cache=%s, parallel=%s",
            len(self.config.strategies),
            self.config.cache_enabled,
            self.config.parallel_loading,
        )

    def _setup_decompiler(self) -> None:
        """
        Initialize decompilation backends.

        Attempts to initialize each decompiler in the preference
        order specified by ``config.decompiler_preference``. Sets
        ``self.active_decompiler`` to the first available
        decompiler. If no external decompilers are available,
        falls back to the built-in ``dis`` module backend.

        The following backends are attempted:

        - ``decompyle3``: Full decompiler with cross-version support
        - ``uncompyle6``: Alternative full decompiler
        - ``pycdc``: External C++ decompiler (requires command-line tool)
        - ``dis``: Built-in disassembler (always available)

        Returns
        -------
        None

        Notes
        -----
        Each backend setup method returns a ``DecompilerInfo`` object
        indicating availability. Failed setups are logged at DEBUG
        level and do not prevent other backends from being used.

        If ``secure_mode`` is enabled, only the ``dis`` backend is
        configured (this is handled in ``_validate_environment``).
        """
        self.decompilers: Dict[str, DecompilerInfo] = {}
        self.active_decompiler: Optional[str] = None

        decompiler_setups = {
            "decompyle3": self._setup_decompyle3,
            "uncompyle6": self._setup_uncompyle6,
            "pycdc": self._setup_pycdc,
            "dis": self._setup_dis_backend,
        }

        for name in self.config.decompiler_preference:
            if name in decompiler_setups:
                try:
                    info = decompiler_setups[name]()
                    if info and info.available:
                        self.decompilers[name] = info
                        if not self.active_decompiler:
                            self.active_decompiler = name
                        logger.debug("Decompiler '%s' initialized", name)
                except Exception as e:
                    logger.debug("Failed to init decompiler '%s': %s", name, e)

        if not self.decompilers:
            logger.warning("No decompilers available - limited functionality")
            self.decompilers["dis"] = DecompilerInfo(
                name="dis", available=True, is_external=False,
                capabilities=["disassembly"]
            )
            self.active_decompiler = "dis"

    def _setup_decompyle3(self) -> Optional[DecompilerInfo]:
        """
        Attempt to setup decompyle3 backend.

        Tries to import the ``decompyle3`` package and retrieve
        its version information.

        Returns
        -------
        Optional[DecompilerInfo]
            A ``DecompilerInfo`` object with ``available=True`` and
            version information if the package is installed;
            otherwise, an object with ``available=False``.

        Notes
        -----
        ``decompyle3`` is the primary decompilation backend,
        supporting full source reconstruction and cross-version
        compatibility. It is an external package that must be
        installed separately:

        >>> pip install decompyle3
        """
        try:
            import decompyle3
            version = getattr(decompyle3, '__version__', 'unknown')
            return DecompilerInfo(
                name="decompyle3", available=True, version=version,
                is_external=True,
                capabilities=["full_decompile", "cross_version"]
            )
        except ImportError:
            return DecompilerInfo(name="decompyle3", available=False, is_external=True)

    def _setup_uncompyle6(self) -> Optional[DecompilerInfo]:
        """
        Attempt to setup uncompyle6 backend.

        Tries to import the ``uncompyle6`` package and retrieve
        its version information.

        Returns
        -------
        Optional[DecompilerInfo]
            A ``DecompilerInfo`` object with ``available=True`` and
            version information if the package is installed;
            otherwise, an object with ``available=False``.

        Notes
        -----
        ``uncompyle6`` is a well-established decompiler supporting
        Python versions up to 3.8 (and partially beyond). It serves
        as an alternative when ``decompyle3`` is not available.

        >>> pip install uncompyle6
        """
        try:
            import uncompyle6
            version = getattr(uncompyle6, '__version__', 'unknown')
            return DecompilerInfo(
                name="uncompyle6", available=True, version=version,
                is_external=True,
                capabilities=["full_decompile", "cross_version"]
            )
        except ImportError:
            return DecompilerInfo(name="uncompyle6", available=False, is_external=True)

    def _setup_pycdc(self) -> Optional[DecompilerInfo]:
        """
        Attempt to setup pycdc backend.

        Checks for the ``pycdc`` command-line tool in the system
        PATH using ``shutil.which``.

        Returns
        -------
        Optional[DecompilerInfo]
            A ``DecompilerInfo`` object with ``available=True`` if
            ``pycdc`` is found in PATH; otherwise, an object with
            ``available=False``.

        Notes
        -----
        ``pycdc`` is an external C++ decompiler that runs as a
        separate process. It must be compiled and installed
        separately from a source distribution.

        Because it runs as an external process, ``pycdc`` is not
        subject to Python-level sandboxing and is disabled in
        ``secure_mode``.
        """
        if shutil.which("pycdc"):
            return DecompilerInfo(
                name="pycdc", available=True, is_external=True,
                capabilities=["full_decompile", "external_tool"]
            )
        return DecompilerInfo(name="pycdc", available=False, is_external=True)

    def _setup_dis_backend(self) -> Optional[DecompilerInfo]:
        """
        Setup built-in dis module backend.

        Configures the standard library ``dis`` module as a
        decompiler backend. This backend is always available as
        it uses only built-in functionality.

        Returns
        -------
        Optional[DecompilerInfo]
            Always returns a ``DecompilerInfo`` with
            ``available=True`` and capability ``"disassembly"``.

        Notes
        -----
        The ``dis`` backend does not perform full decompilation;
        it produces a disassembly with pseudo-code structure rather
        than reconstructing the original Python source. It serves
        as a fallback when no full decompiler is available.
        """
        return DecompilerInfo(
            name="dis", available=True, is_external=False,
            capabilities=["disassembly"]
        )

    def _setup_cache(self) -> None:
        """
        Initialize caching system.

        Creates the cache directory for persistent disk caching
        if ``cache_enabled`` is ``True`` in the configuration.
        The default cache directory is ``<tempdir>/pyputil.pyc_cache``.

        Returns
        -------
        None

        Notes
        -----
        The cache directory is created with ``parents=True`` to
        ensure all parent directories exist. If the directory
        already exists, no error is raised (``exist_ok=True``).
        """
        if self.config.cache_enabled:
            self.cache_dir = (
                self.config.cache_dir
                or Path(tempfile.gettempdir()) / "pyputil.pyc_cache"
            )
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _setup_executor(self) -> None:
        """
        Initialize thread pool executor.

        Creates a ``ThreadPoolExecutor`` for parallel strategy
        execution if ``parallel_loading`` is enabled in the
        configuration.

        Returns
        -------
        None

        Notes
        -----
        The executor is configured with:
        - ``max_workers``: Number of worker threads from config
        - ``thread_name_prefix``: ``"pyputil.pyc"`` for debugging

        When ``parallel_loading`` is ``False``, ``self._executor``
        is set to ``None``.
        """
        if self.config.parallel_loading:
            self._executor = ThreadPoolExecutor(
                max_workers=self.config.max_workers,
                thread_name_prefix="pyputil.pyc",
            )
        else:
            self._executor = None

    def _validate_environment(self) -> None:
        """
        Validate runtime environment.

        Performs initial checks on the Python runtime environment:

        1. Verifies Python version >= 3.6
        2. If ``secure_mode`` is enabled, restricts decompiler
           preference to ``["dis"]`` only (disabling external tools)
           and re-initializes decompilers
        3. If a custom ``temp_dir`` is specified, ensures it exists

        Returns
        -------
        None

        Raises
        ------
        RuntimeError
            If the Python version is earlier than 3.6.

        Notes
        -----
        Secure mode restriction of decompilers is important because
        external decompilers may execute code or interact with the
        filesystem in ways that bypass Python-level sandboxing.
        """
        if sys.version_info < (3, 6):
            raise RuntimeError("PycLoader requires Python 3.6 or later")

        if self.config.secure_mode:
            logger.warning("Secure mode enabled - external tools disabled")
            self.config.decompiler_preference = ["dis"]
            self._setup_decompiler()

        if self.config.temp_dir:
            self.config.temp_dir = Path(self.config.temp_dir)
            self.config.temp_dir.mkdir(parents=True, exist_ok=True)

    def get_decompiler_info(self, name: str) -> Optional[DecompilerInfo]:
        """
        Get information about a specific decompiler.

        Queries the internal decompiler registry for information
        about a named decompiler backend.

        Parameters
        ----------
        name : str
            Decompiler name to query. Valid names include
            ``"decompyle3"``, ``"uncompyle6"``, ``"pycdc"``,
            and ``"dis"``.

        Returns
        -------
        Optional[DecompilerInfo]
            A ``DecompilerInfo`` object if the decompiler is
            registered; ``None`` if the name is not recognized.

        Examples
        --------
        >>> loader = PycLoader()
        >>> info = loader.get_decompiler_info("dis")
        >>> info.available
        True
        >>> info = loader.get_decompiler_info("nonexistent")
        >>> info is None
        True
        """
        return self.decompilers.get(name)

    def list_decompilers(self) -> List[DecompilerInfo]:
        """
        List all configured decompilers.

        Returns information about all decompiler backends that
        were successfully configured, whether available or not.

        Returns
        -------
        List[DecompilerInfo]
            List of ``DecompilerInfo`` objects, one for each
            configured decompiler. The order reflects the
            configuration preference.

        Examples
        --------
        >>> loader = PycLoader()
        >>> for info in loader.list_decompilers():
        ...     status = "available" if info.available else "unavailable"
        ...     print(f"{info.name}: {status}")
        decompyle3: unavailable
        uncompyle6: unavailable
        pycdc: unavailable
        dis: available
        """
        return list(self.decompilers.values())

    def get_current_platform(self) -> PlatformInfo:
        """
        Get current platform information.

        Queries the operating system and hardware platform using
        the standard library ``platform`` and ``struct`` modules.

        Returns
        -------
        PlatformInfo
            A ``PlatformInfo`` object containing the current
            system name, machine architecture, and pointer size.

        Notes
        -----
        Platform detection uses:
        - ``platform.system().lower()`` for OS name
        - ``platform.machine().lower()`` for architecture
        - ``struct.calcsize("P") * 8`` for bit width (32 or 64)

        Examples
        --------
        >>> loader = PycLoader()
        >>> info = loader.get_current_platform()
        >>> print(info.identifier)
        linux-x86_64-64
        """
        return PlatformInfo(
            system=platform.system().lower(),
            machine=platform.machine().lower(),
            bits=struct.calcsize("P") * 8,
        )

    @property
    def statistics(self) -> LoaderStatistics:
        """
        Get current loader statistics as a structured dataclass.

        Computes a snapshot of all accumulated runtime statistics,
        including success rates, strategy usage counts, and
        performance metrics.

        Returns
        -------
        LoaderStatistics
            A ``LoaderStatistics`` dataclass populated with current
            values. The ``average_load_time_ms`` is computed from
            the internal ``_load_times`` list.

        Notes
        -----
        The statistics are computed on each access and reflect the
        current state. The internal ``_load_times`` list stores
        times in seconds; the average is converted to milliseconds
        for the output.

        Examples
        --------
        >>> loader = PycLoader()
        >>> result = loader.load("module.pyc")
        >>> stats = loader.statistics
        >>> print(f"Success rate: {stats.success_rate:.1%}")
        >>> print(f"Cache hits: {stats.cache_hits}")
        """
        avg_time = 0.0
        if self._load_times:
            avg_time = sum(self._load_times) / len(self._load_times) * 1000

        return LoaderStatistics(
            loads_attempted=self._stats['loads_attempted'],
            loads_succeeded=self._stats['loads_succeeded'],
            loads_failed=self._stats['loads_failed'],
            cache_hits=self._stats['cache_hits'],
            strategies_used=dict(self._stats['strategies_used']),
            average_load_time_ms=avg_time,
            cache_size=len(self._cache_entries),
        )

    @validate_path
    @timed_operation
    def load(
        self,
        path: Union[str, Path],
        name: str = "loaded_module",
    ) -> LoadResult:
        """
        Load a Python bytecode file with automatic fallback strategies.

        This is the primary method for loading .pyc files. It attempts
        to load the bytecode using the configured strategies in order
        until one succeeds. Supports caching, parallel execution,
        and comprehensive error reporting.

        Parameters
        ----------
        path : Union[str, Path]
            Path to the .pyc file to load. Can be a string or
            ``Path`` object. The path is validated and resolved
            to an absolute path before processing.
        name : str, optional
            The name to assign to the loaded module. Must be a
            valid Python identifier (start with a letter or
            underscore, contain only letters, digits, and
            underscores). Default is ``"loaded_module"``.

        Returns
        -------
        LoadResult
            A ``LoadResult`` dataclass containing the loaded module,
            bytecode metadata, the strategy that succeeded, timing
            information, and any warnings.

        Raises
        ------
        PycLoadError
            If all loading strategies fail. The exception wraps a
            ``LoadError`` dataclass with detailed diagnostics and
            actionable suggestions.
        ValueError
            If the module name is not a valid Python identifier.
        FileNotFoundError
            If the specified file does not exist.
        PermissionError
            If the file is not readable.

        Notes
        -----
        The loading process follows these steps:

        1. Validate the module name against ``MODULE_NAME_PATTERN``
        2. Increment the attempt counter
        3. Check the cache (if enabled) and return immediately on hit
        4. Detect bytecode version and extract metadata
        5. Attempt strategies in order (or in parallel if configured)
        6. Update the cache with the loaded module
        7. Update statistics and return the result

        Examples
        --------
        >>> loader = PycLoader()
        >>> result = loader.load("module.cpython-39.pyc", "mymodule")
        >>> result.module.my_function()
        >>> print(f"Loaded with: {result.strategy_used.name}")
        >>> print(f"Version: {result.metadata.version_string}")

        >>> # With secure mode
        >>> config = LoaderConfig(secure_mode=True)
        >>> loader = PycLoader(config)
        >>> result = loader.load("trusted.pyc")
        """
        if not self.MODULE_NAME_PATTERN.match(name):
            raise ValueError(f"Invalid module name: {name}")

        self._stats['loads_attempted'] += 1
        path = Path(path).resolve()
        start_time = time.perf_counter()

        # Check cache
        if self.config.cache_enabled:
            cached_entry = self._check_cache(path, name)
            if cached_entry:
                self._stats['cache_hits'] += 1
                self._stats['loads_succeeded'] += 1
                load_time = (time.perf_counter() - start_time) * 1000
                return LoadResult(
                    module=cached_entry.module,
                    metadata=cached_entry.metadata,
                    strategy_used=LoadStrategy.DIRECT_IMPORT,
                    load_time_ms=load_time,
                )

        # Detect metadata
        metadata = self.detect_version(path)

        # Try loading
        warnings_list = []
        if self.config.parallel_loading and self._executor:
            module, strategy = self._parallel_load(path, name, metadata)
        else:
            module, strategy = self._sequential_load(path, name, metadata, warnings_list)

        # Cache
        if self.config.cache_enabled:
            self._update_cache(path, name, module, metadata)

        load_time = (time.perf_counter() - start_time) * 1000
        self._load_times.append(load_time / 1000)
        self._stats['loads_succeeded'] += 1

        return LoadResult(
            module=module,
            metadata=metadata,
            strategy_used=strategy,
            load_time_ms=load_time,
            warnings=warnings_list,
        )

    def _sequential_load(
        self, path: Path, name: str, metadata: BytecodeMetadata, warnings_list: List[str]
    ) -> Tuple[ModuleType, LoadStrategy]:
        """
        Load module using sequential strategy attempts.

        Iterates through the configured strategies in order,
        attempting each one until a module is successfully loaded.
        Collects errors from failed attempts for diagnostic purposes.

        Parameters
        ----------
        path : Path
            Resolved absolute path to the .pyc file.
        name : str
            Module name to assign.
        metadata : BytecodeMetadata
            Pre-extracted bytecode metadata.
        warnings_list : List[str]
            Mutable list to collect warning messages during loading.

        Returns
        -------
        Tuple[ModuleType, LoadStrategy]
            A tuple containing the loaded module and the
            ``LoadStrategy`` that succeeded.

        Raises
        ------
        PycLoadError
            If all strategies fail. The ``LoadError`` includes
            details of the last error, all attempted strategies,
            and generated suggestions.

        Notes
        -----
        Each strategy execution is wrapped in a try-except block.
        Failures are logged at WARNING level before the next
        strategy is attempted. The strategy usage counter is
        incremented only for the successful strategy.
        """
        errors: List[Tuple[LoadStrategy, Exception]] = []

        for strategy in self.config.strategies:
            try:
                logger.debug("Attempting strategy: %s", strategy.name)
                module = self._execute_strategy(strategy, path, name, metadata)

                strategy_name = strategy.name
                self._stats['strategies_used'][strategy_name] = (
                    self._stats['strategies_used'].get(strategy_name, 0) + 1
                )

                return module, strategy
            except Exception as e:
                logger.warning("Strategy %s failed: %s", strategy.name, e)
                errors.append((strategy, e))
                continue

        self._stats['loads_failed'] += 1

        last_strategy = errors[-1][0] if errors else None
        last_error = errors[-1][1] if errors else None

        error_info = LoadError(
            message=f"All loading strategies exhausted for {path}",
            strategy=last_strategy,
            error_type=type(last_error).__name__ if last_error else "",
            error_message=str(last_error)[:500] if last_error else "",
            metadata=metadata,
            suggestions=self._generate_suggestions(errors, metadata),
            diagnostics={
                'strategies_attempted': len(errors),
                'failed_strategies': [s.name for s, _ in errors],
                'file_size': metadata.file_size,
            }
        )
        raise PycLoadError(error_info)

    def _parallel_load(
        self, path: Path, name: str, metadata: BytecodeMetadata
    ) -> Tuple[ModuleType, LoadStrategy]:
        """
        Attempt multiple loading strategies in parallel.

        Submits all configured strategies to a thread pool executor
        for concurrent execution. Returns the result of the first
        strategy that succeeds, canceling any remaining futures.

        Parameters
        ----------
        path : Path
            Resolved absolute path to the .pyc file.
        name : str
            Module name to assign.
        metadata : BytecodeMetadata
            Pre-extracted bytecode metadata.

        Returns
        -------
        Tuple[ModuleType, LoadStrategy]
            A tuple containing the loaded module and the
            ``LoadStrategy`` that succeeded first.

        Raises
        ------
        PycLoadError
            If all strategies fail or the overall timeout is
            exceeded.

        Notes
        -----
        Strategies are submitted to the executor with
        ``_execute_strategy_safe``, which catches exceptions
        and returns ``None`` on failure. The first non-``None``
        result is used. Futures that complete after a result is
        found are canceled.

        The operation respects ``config.timeout`` as a maximum
        wait time via ``as_completed_with_timeout``.
        """
        futures: Dict[Future, LoadStrategy] = {}

        for strategy in self.config.strategies:
            future = self._executor.submit(
                self._execute_strategy_safe, strategy, path, name, metadata
            )
            futures[future] = strategy

        errors = []
        for future in as_completed_with_timeout(futures.keys(), timeout=self.config.timeout):
            strategy = futures[future]
            try:
                module = future.result()
                if module:
                    for f in futures:
                        if not f.done():
                            f.cancel()

                    strategy_name = strategy.name
                    self._stats['strategies_used'][strategy_name] = (
                        self._stats['strategies_used'].get(strategy_name, 0) + 1
                    )
                    return module, strategy
            except Exception as e:
                errors.append((strategy, e))

        self._stats['loads_failed'] += 1

        error_info = LoadError(
            message=f"All parallel strategies failed for {path}",
            metadata=metadata,
            suggestions=self._generate_suggestions(errors, metadata),
        )
        raise PycLoadError(error_info)

    def _execute_strategy_safe(
        self, strategy: LoadStrategy, path: Path, name: str, metadata: BytecodeMetadata
    ) -> Optional[ModuleType]:
        """
        Execute a strategy safely, returning None on failure.

        Wraps ``_execute_strategy`` to catch any exception and
        return ``None`` instead of propagating the error. Used
        in parallel loading to allow other strategies to continue.

        Parameters
        ----------
        strategy : LoadStrategy
            The strategy to execute.
        path : Path
            Path to the .pyc file.
        name : str
            Module name.
        metadata : BytecodeMetadata
            Bytecode metadata.

        Returns
        -------
        Optional[ModuleType]
            The loaded module if successful; ``None`` if any
            exception occurs.
        """
        try:
            return self._execute_strategy(strategy, path, name, metadata)
        except Exception:
            return None

    def _execute_strategy(
        self, strategy: LoadStrategy, path: Path, name: str, metadata: BytecodeMetadata
    ) -> ModuleType:
        """
        Execute a specific loading strategy.

        Dispatches to the appropriate strategy handler method based
        on the ``LoadStrategy`` enum value.

        Parameters
        ----------
        strategy : LoadStrategy
            The strategy to execute. Must be one of the seven
            defined strategies.
        path : Path
            Path to the .pyc file.
        name : str
            Module name.
        metadata : BytecodeMetadata
            Bytecode metadata for version-aware strategies.

        Returns
        -------
        ModuleType
            The loaded Python module.

        Raises
        ------
        ValueError
            If the strategy is not recognized (no handler mapped).
        ImportError, ValueError, RuntimeError, TypeError
            Various strategy-specific errors propagated from the
            handler methods.

        Notes
        -----
        Strategy handlers are mapped via an internal dictionary
        for O(1) dispatch. Each handler method follows the same
        signature pattern: ``(path, name, metadata) -> ModuleType``.
        """
        strategy_map = {
            LoadStrategy.DIRECT_IMPORT: self._strategy_direct_import,
            LoadStrategy.MARSHAL_LOAD: self._strategy_marshal_load,
            LoadStrategy.RECOMPILE: self._strategy_recompile,
            LoadStrategy.EXTRACT_SOURCE: self._strategy_extract_source,
            LoadStrategy.TEMP_COMPILE: self._strategy_temp_compile,
            LoadStrategy.FALLBACK_INTERPRETER: self._strategy_fallback_interpreter,
            LoadStrategy.BYTECODE_TRANSFORM: self._strategy_bytecode_transform,
        }

        handler = strategy_map.get(strategy)
        if not handler:
            raise ValueError(f"Unknown strategy: {strategy}")

        return handler(path, name, metadata)

    def _strategy_direct_import(
        self, path: Path, name: str, metadata: BytecodeMetadata
    ) -> ModuleType:
        """
        Strategy 1: Attempt direct import using importlib machinery.

        Uses the standard Python import system to load the .pyc file.
        This is the fastest strategy but requires an exact version
        match between the bytecode and the current interpreter.

        Parameters
        ----------
        path : Path
            Path to the .pyc file.
        name : str
            Module name.
        metadata : BytecodeMetadata
            Bytecode metadata for compatibility check.

        Returns
        -------
        ModuleType
            The loaded module.

        Raises
        ------
        ImportError
            If the Python version does not match (``is_compatible``
            is ``False``) or if the module spec cannot be created.

        Notes
        -----
        Uses ``importlib.util.spec_from_file_location`` to create
        a module spec, then creates the module and executes it.
        The module is registered in ``sys.modules`` to support
        subsequent imports of the same module by name.
        """
        if not metadata.is_compatible:
            raise ImportError(
                f"Bytecode version mismatch: {metadata.version_string} "
                f"vs current {sys.version_info[0]}.{sys.version_info[1]}"
            )

        spec = importlib.util.spec_from_file_location(name, str(path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    def _strategy_marshal_load(
        self, path: Path, name: str, metadata: BytecodeMetadata
    ) -> ModuleType:
        """
        Strategy 2: Load bytecode using marshal module directly.

        Reads the raw code object from the .pyc file using the
        ``marshal`` module, bypassing the import system for greater
        control. Performs bytecode validation if configured.

        Parameters
        ----------
        path : Path
            Path to the .pyc file.
        name : str
            Module name.
        metadata : BytecodeMetadata
            Bytecode metadata for header size calculation.

        Returns
        -------
        ModuleType
            The loaded module.

        Raises
        ------
        TypeError
            If the unmarshalled object is not a ``CodeType``.
        ValueError
            If bytecode validation fails (suspicious patterns,
            excessive size, or deep recursion).

        Notes
        -----
        The header size varies:
        - Python 3.6+: 16 bytes (magic + flags + timestamp + source size)
        - Earlier versions: 12 bytes (magic + timestamp + source size)

        The module is created as a bare ``ModuleType`` and its
        ``__dict__`` is populated by executing the code object
        via ``exec()``.
        """
        with open(path, "rb") as f:
            header_size = 16 if metadata.python_version >= (3, 6) else 12
            f.seek(header_size)
            code = marshal.load(f)

        if not isinstance(code, types.CodeType):
            raise TypeError(f"Invalid code object type: {type(code)}")

        if self.config.validate_bytecode:
            self._validate_code_object(code)

        module = types.ModuleType(name)
        module.__file__ = str(path)
        module.__loader__ = self
        module.__cached__ = str(path)
        exec(code, module.__dict__)
        return module

    def _strategy_recompile(
        self, path: Path, name: str, metadata: BytecodeMetadata
    ) -> ModuleType:
        """
        Strategy 3: Decompile bytecode and recompile for current Python.

        Reads the code object, decompiles it to source, then
        compiles the source for the current Python version. This
        enables cross-version compatibility when the bytecode
        format has changed.

        Parameters
        ----------
        path : Path
            Path to the .pyc file.
        name : str
            Module name.
        metadata : BytecodeMetadata
            Bytecode metadata.

        Returns
        -------
        ModuleType
            The loaded module with recompiled bytecode.

        Raises
        ------
        TypeError
            If the unmarshalled object is not a ``CodeType``.
        RuntimeError
            If decompilation produces empty or whitespace-only source.

        Notes
        -----
        The decompiled source is compiled with ``compile(source, ...,
        "exec")``, which generates bytecode for the current interpreter.
        This effectively performs a version upgrade/downgrade of the
        bytecode.
        """
        with open(path, "rb") as f:
            f.seek(16)
            code = marshal.load(f)

        if not isinstance(code, types.CodeType):
            raise TypeError(f"Invalid code object: {type(code)}")

        source = self.decompile_bytecode(code)
        if not source or source.isspace():
            raise RuntimeError("Decompilation produced empty source")

        new_code = compile(source, f"<recompiled_{name}>", "exec")
        module = types.ModuleType(name)
        module.__file__ = str(path)
        exec(new_code, module.__dict__)
        return module

    def _strategy_extract_source(
        self, path: Path, name: str, metadata: BytecodeMetadata
    ) -> ModuleType:
        """
        Strategy 4: Extract and execute source code from bytecode.

        Similar to RECOMPILE but executes the decompiled source
        directly without an intermediate compilation step. The
        source code is attached to the module as ``__source__``.

        Parameters
        ----------
        path : Path
            Path to the .pyc file.
        name : str
            Module name.
        metadata : BytecodeMetadata
            Bytecode metadata.

        Returns
        -------
        ModuleType
            The loaded module with attached source code.

        Raises
        ------
        TypeError
            If the unmarshalled object is not a ``CodeType``.
        RuntimeError
            If decompilation produces empty source.

        Notes
        -----
        The source is stored in ``module.__source__`` for later
        inspection or saving. Executing source directly (via
        ``exec(source, module.__dict__)``) bypasses bytecode
        compilation but may be slightly slower for repeated use.
        """
        with open(path, "rb") as f:
            f.seek(16)
            code = marshal.load(f)

        if not isinstance(code, types.CodeType):
            raise TypeError(f"Invalid code object: {type(code)}")

        source = self.decompile_bytecode(code)
        if not source or source.isspace():
            raise RuntimeError("Decompilation produced empty source")

        module = types.ModuleType(name)
        module.__file__ = str(path)
        module.__source__ = source
        exec(source, module.__dict__)
        return module

    def _strategy_temp_compile(
        self, path: Path, name: str, metadata: BytecodeMetadata
    ) -> ModuleType:
        """
        Strategy 5: Compile extracted source in temporary location.

        Decompiles to source, writes to a temporary .py file,
        compiles that file, and executes the resulting code object.
        The temporary file is cleaned up unless ``preserve_temp``
        is enabled.

        Parameters
        ----------
        path : Path
            Path to the .pyc file.
        name : str
            Module name.
        metadata : BytecodeMetadata
            Bytecode metadata.

        Returns
        -------
        ModuleType
            The loaded module.

        Raises
        ------
        TypeError
            If the unmarshalled object is not a ``CodeType``.
        RuntimeError
            If decompilation produces empty source.

        Notes
        -----
        The temporary file is created in the configured ``temp_dir``
        or the system default. A hash suffix is added to the filename
        to prevent collisions. The ``__pycache__`` directory that
        Python may create for the temporary file is also cleaned up.

        When ``preserve_temp`` is ``True``, the temporary .py file
        is kept for debugging purposes.
        """
        with open(path, "rb") as f:
            f.seek(16)
            code = marshal.load(f)

        if not isinstance(code, types.CodeType):
            raise TypeError(f"Invalid code object: {type(code)}")

        temp_dir = self.config.temp_dir or Path(tempfile.gettempdir())
        hash_suffix = hashlib.md5(str(path).encode()).hexdigest()[:8]
        temp_py = temp_dir / f"{name}_extracted_{hash_suffix}.py"

        try:
            source = self.decompile_bytecode(code)
            if not source or source.isspace():
                raise RuntimeError("Decompilation produced empty source")

            temp_py.write_text(source, encoding='utf-8')
            compiled = compile(source, str(temp_py), "exec")

            module = types.ModuleType(name)
            module.__file__ = str(temp_py)
            exec(compiled, module.__dict__)
            return module
        finally:
            if not self.config.preserve_temp:
                with contextlib.suppress(OSError):
                    temp_py.unlink()
                    pycache = temp_py.parent / "__pycache__"
                    if pycache.exists():
                        for cached in pycache.glob(f"{temp_py.stem}*"):
                            cached.unlink()
                        if not list(pycache.iterdir()):
                            pycache.rmdir()

    def _strategy_fallback_interpreter(
        self, path: Path, name: str, metadata: BytecodeMetadata
    ) -> ModuleType:
        """
        Strategy 6: Use a compatible Python interpreter as fallback.

        Finds and invokes a Python interpreter matching the bytecode's
        version, transfers the module state back to the current process
        via pickle serialization.

        Parameters
        ----------
        path : Path
            Path to the .pyc file.
        name : str
            Module name.
        metadata : BytecodeMetadata
            Bytecode metadata for version matching.

        Returns
        -------
        ModuleType
            The loaded module with state transferred from the
            fallback interpreter.

        Raises
        ------
        RuntimeError
            If ``secure_mode`` is enabled (external interpreters
            are disabled), if no compatible interpreter is found,
            if the subprocess returns a non-zero exit code, or
            if the subprocess times out.

        Notes
        -----
        The fallback interpreter executes a small inline script that:
        1. Loads the code object from the .pyc file
        2. Executes it in a new module
        3. Pickles the module's public attributes
        4. Prints the hex-encoded pickle data

        The current process deserializes this data and populates
        a new module. Only attributes not starting with ``_`` are
        transferred (public API).

        The module is marked with ``__fallback__ = True`` for
        identification.
        """
        if self.config.secure_mode:
            raise RuntimeError("Fallback interpreter disabled in secure mode")

        ver = metadata.python_version
        interpreter = self._find_compatible_interpreter(ver)
        if not interpreter:
            raise RuntimeError(
                f"No compatible interpreter found for Python {ver[0]}.{ver[1]}"
            )

        loader_script = f"""
import sys, marshal, types, pickle
with open('{path}', 'rb') as f:
    f.seek(16)
    code = marshal.load(f)
module = types.ModuleType('{name}')
exec(code, module.__dict__)
print(pickle.dumps({{k: v for k, v in module.__dict__.items()
                      if not k.startswith('_')}}).hex())
"""

        try:
            result = subprocess.run(
                [interpreter, "-c", loader_script],
                capture_output=True, text=True,
                timeout=self.config.timeout, check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(f"Fallback interpreter failed: {result.stderr[:500]}")

            module = types.ModuleType(name)
            module.__fallback__ = True

            try:
                state = pickle.loads(bytes.fromhex(result.stdout.strip()))
                module.__dict__.update(state)
            except Exception as e:
                logger.warning("Could not deserialize module state: %s", e)

            return module
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"Fallback interpreter timed out after {self.config.timeout}s"
            ) from e

    def _strategy_bytecode_transform(
        self, path: Path, name: str, metadata: BytecodeMetadata
    ) -> ModuleType:
        """
        Strategy 7: Transform bytecode for cross-version compatibility.

        Currently delegates to decompilation and recompilation for
        cross-version support. Future versions may implement direct
        opcode-level transformations for adjacent Python versions.

        Parameters
        ----------
        path : Path
            Path to the .pyc file.
        name : str
            Module name.
        metadata : BytecodeMetadata
            Bytecode metadata for version-aware transformation.

        Returns
        -------
        ModuleType
            The loaded module with transformed bytecode.

        Raises
        ------
        TypeError
            If the unmarshalled object is not a ``CodeType``.

        Notes
        -----
        The module is marked with ``__transformed__ = True`` for
        identification. The transformation pipeline is:
        1. Read code object
        2. Transform via ``_transform_bytecode`` (decompile + recompile)
        3. Execute transformed code
        """
        with open(path, "rb") as f:
            f.seek(16)
            code = marshal.load(f)

        if not isinstance(code, types.CodeType):
            raise TypeError(f"Invalid code object: {type(code)}")

        transformed_code = self._transform_bytecode(code, metadata)

        module = types.ModuleType(name)
        module.__transformed__ = True
        module.__file__ = str(path)
        exec(transformed_code, module.__dict__)
        return module

    def _transform_bytecode(
        self, code: types.CodeType, metadata: BytecodeMetadata
    ) -> types.CodeType:
        """
        Transform bytecode for cross-version compatibility.

        If the current Python version matches the bytecode's version,
        returns the original code object unchanged. Otherwise,
        decompiles to source and recompiles for the current version.

        Parameters
        ----------
        code : types.CodeType
            The original code object to potentially transform.
        metadata : BytecodeMetadata
            Metadata containing the target (original) Python version.

        Returns
        -------
        types.CodeType
            Either the original code object (if versions match)
            or a newly compiled code object for the current version.

        Notes
        -----
        This method provides semantic cross-version support via
        the source level. Direct opcode translation (e.g., handling
        instruction changes between adjacent versions) is a
        potential future enhancement.
        """
        current_version = sys.version_info[:2]
        target_version = metadata.python_version

        if current_version == target_version:
            return code

        source = self.decompile_bytecode(code)
        return compile(source, f"<transformed_{id(code)}>", "exec")

    def _validate_code_object(self, code: types.CodeType) -> None:
        """
        Validate a code object for safety and integrity.

        Performs security checks on the code object:
        1. Size limit: Raw bytecode must not exceed 10 MB
        2. Recursion depth: Must not exceed ``config.max_recursion``
        3. Suspicious patterns: Scans bytecode for dangerous builtins

        Parameters
        ----------
        code : types.CodeType
            The code object to validate.

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If the code object is too large (possible overflow attack),
            exceeds maximum recursion depth, or (in secure mode)
            contains suspicious bytecode patterns.

        Notes
        -----
        Suspicious patterns checked for (as byte strings within the
        bytecode):
        - ``os.system``
        - ``subprocess``
        - ``eval``
        - ``exec``
        - ``__import__``
        - ``compile``
        - ``open``

        In non-secure mode, suspicious patterns generate warnings
        rather than errors, allowing inspection while still alerting
        the user.
        """
        if len(code.co_code) > 10_000_000:
            raise ValueError("Code object too large (possible overflow attack)")

        if self._count_recursion(code) > self.config.max_recursion:
            raise ValueError("Maximum recursion depth exceeded")

        suspicious_patterns = [
            b'os.system', b'subprocess', b'eval', b'exec',
            b'__import__', b'compile', b'open',
        ]

        for pattern in suspicious_patterns:
            if pattern in code.co_code:
                if self.config.secure_mode:
                    raise ValueError(f"Suspicious pattern detected: {pattern}")
                else:
                    logger.warning("Suspicious pattern detected: %s", pattern)

    def _count_recursion(self, code: types.CodeType, depth: int = 0) -> int:
        """
        Count maximum recursion depth in a code object tree.

        Recursively traverses nested code objects (found in
        ``co_consts``) to determine the maximum nesting depth.
        Used for stack overflow prevention.

        Parameters
        ----------
        code : types.CodeType
            The root code object to inspect.
        depth : int, optional
            Current recursion depth. Default is 0 for the root call.

        Returns
        -------
        int
            The maximum recursion depth found in the code object
            tree. Upper-bounded by ``config.max_recursion`` to
            prevent infinite recursion in pathological cases.

        Notes
        -----
        Nested code objects are found in the ``co_consts`` tuple
        and represent inner functions, classes, list/dict/set
        comprehensions, and generator expressions. Each level of
        nesting increases the counter by 1.
        """
        if depth > self.config.max_recursion:
            return depth

        max_depth = depth
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                child_depth = self._count_recursion(const, depth + 1)
                max_depth = max(max_depth, child_depth)

        return max_depth

    @timed_operation
    def detect_version(self, path: Union[str, Path]) -> BytecodeMetadata:
        """
        Detect Python version and extract metadata from bytecode file.

        Reads and parses the .pyc file header to extract the magic
        number, version, flags, timestamp, source size, and other
        metadata. Also computes file hash and platform information.

        Parameters
        ----------
        path : Union[str, Path]
            Path to the .pyc file to analyze. The path is resolved
            to an absolute path.

        Returns
        -------
        BytecodeMetadata
            Comprehensive metadata about the bytecode file, including
            version, platform, flags, hash, and compatibility
            assessment.

        Raises
        ------
        FileNotFoundError
            If the specified file does not exist.
        ValueError
            If the file is too small to contain a valid .pyc header
            (fewer than 4 bytes).

        Notes
        -----
        The header parsing follows the .pyc file format:

        ======= ====== ========================
        Offset  Size   Field
        ======= ====== ========================
        0       2      Magic number (low word)
        2       2      Magic number (high word)
        4       4      Flags (PEP 552 bitfield)
        8       4      Timestamp (Unix time)
        12      4      Source file size
        ======= ====== ========================

        Compatibility is determined by comparing the detected
        version against ``sys.version_info[:2]``.

        Examples
        --------
        >>> loader = PycLoader()
        >>> meta = loader.detect_version("module.cpython-39.pyc")
        >>> print(meta.version_string)
        3.9
        >>> print(meta.magic_hex)
        0x00000eb2
        >>> print(f"Compatible: {meta.is_compatible}")
        """
        path = Path(path).resolve()

        if not path.exists():
            raise FileNotFoundError(f"Bytecode file not found: {path}")

        file_size = path.stat().st_size

        with open(path, "rb") as f:
            header = f.read(16)

            if len(header) < 4:
                raise ValueError(f"File too small to be valid .pyc: {len(header)} bytes")

            magic_low = struct.unpack("<H", header[0:2])[0]
            magic_high = struct.unpack("<H", header[2:4])[0]
            full_magic = (magic_high << 16) | magic_low

            py_version = self._magic_to_version(full_magic)

            flags = CompilationFlags()
            if len(header) >= 8:
                flags_raw = struct.unpack("<I", header[4:8])[0]
                flags = CompilationFlags(
                    hash_based=bool(flags_raw & 0x1),
                    checked_hash=bool(flags_raw & 0x2),
                    flags_raw=flags_raw,
                )

            if len(header) >= 12:
                timestamp_raw = struct.unpack("<I", header[8:12])[0]
                if timestamp_raw == 0 and flags.hash_based:
                    timestamp = datetime.fromtimestamp(0, tz=timezone.utc)
                elif timestamp_raw:
                    timestamp = datetime.fromtimestamp(timestamp_raw, tz=timezone.utc)
                else:
                    timestamp = datetime.fromtimestamp(0, tz=timezone.utc)
            else:
                timestamp = datetime.fromtimestamp(0, tz=timezone.utc)

            source_size = 0
            if len(header) >= 16:
                source_size = struct.unpack("<I", header[12:16])[0]

            code_hash = self._calculate_file_hash(path)

            platform_info = self.get_current_platform()

            is_compatible = py_version == sys.version_info[:2]
            is_hash_based = timestamp.timestamp() == 0

            return BytecodeMetadata(
                magic_number=full_magic,
                python_version=py_version,
                timestamp=timestamp,
                source_size=source_size,
                code_hash=code_hash,
                platform=platform_info,
                file_size=file_size,
                flags=flags,
                is_compatible=is_compatible,
                is_hash_based=is_hash_based,
            )

    def _calculate_file_hash(
        self,
        path: Path,
        algorithm: str = 'sha256',
        chunk_size: int = 65536,
    ) -> str:
        """
        Calculate file hash using chunked reading.

        Computes a cryptographic hash of the file contents using
        the specified algorithm. Chunked reading prevents memory
        issues with large files.

        Parameters
        ----------
        path : Path
            Path to the file to hash.
        algorithm : str, optional
            Hash algorithm name as recognized by ``hashlib.new()``.
            Common values: ``'sha256'``, ``'md5'``, ``'sha512'``.
            Default is ``'sha256'``.
        chunk_size : int, optional
            Size of each read chunk in bytes. Larger values may
            improve throughput for large files. Default is 65536
            (64 KB).

        Returns
        -------
        str
            The hexadecimal digest of the file hash, e.g.,
            ``"e3b0c44298fc1c149afbf4c8996fb924..."`` for an
            empty file.

        Notes
        -----
        SHA-256 is the default algorithm for its balance of speed
        and collision resistance. For cache key generation, a
        truncated SHA-256 is used elsewhere in the codebase.

        Examples
        --------
        >>> loader = PycLoader()
        >>> h = loader._calculate_file_hash(Path("module.pyc"), algorithm="md5")
        >>> len(h)
        32
        """
        hasher = hashlib.new(algorithm)
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _magic_to_version(self, magic: int) -> Tuple[int, int]:
        """
        Convert a magic number to a Python version tuple.

        First attempts exact matching against known ``BytecodeVersion``
        values. If no exact match is found, uses a heuristic based on
        the offset from the known base magic number (0x0BB8 for
        Python 3.0).

        Parameters
        ----------
        magic : int
            The 32-bit magic number to interpret.

        Returns
        -------
        Tuple[int, int]
            Python version tuple ``(major, minor)``. For unrecognized
            magic numbers where the high word contains the 0x0A0D
            signature, returns ``(3, minor_offset)`` where
            ``minor_offset = low_word - 0x0BB8``. For completely
            unrecognized magic numbers, returns the raw high and
            low words as ``(high, low)``.

        Notes
        -----
        The magic number format is ``(0x0A0D << 16) | version_specific``,
        where ``version_specific`` starts at 0x0BB8 for Python 3.0
        and increments for each release.

        Examples
        --------
        >>> loader = PycLoader()
        >>> loader._magic_to_version(0x0F0E)  # Python 3.11
        (3, 11)
        """
        for version_enum in BytecodeVersion:
            if version_enum.full_magic == magic:
                return version_enum.python_version

        major = (magic >> 16) & 0xFFFF
        minor = magic & 0xFFFF

        if major >= 0x0a0d and minor >= 0x0bb8:
            minor_version = minor - 0x0bb8
            return (3, minor_version)

        logger.warning("Unknown magic number: 0x%x", magic)
        return (major, minor)

    def decompile_bytecode(
        self,
        code: types.CodeType,
        preferred_decompiler: Optional[str] = None,
    ) -> str:
        """
        Decompile a code object to Python source code.

        Attempts decompilation using the preferred decompiler,
        falling back to other available decompilers if the
        preferred one fails.

        Parameters
        ----------
        code : types.CodeType
            The compiled code object to decompile. Must be a valid
            Python code object.
        preferred_decompiler : str, optional
            Name of the preferred decompiler to try first. If
            ``None``, uses ``self.active_decompiler`` (the first
            available decompiler from the preference list).
            Default is ``None``.

        Returns
        -------
        str
            Reconstructed Python source code as a string. The
            quality and completeness depend on the decompiler used.

        Raises
        ------
        RuntimeError
            If ``secure_mode`` is enabled and an external decompiler
            is requested, or if all decompilation backends fail.
        TypeError
            If ``code`` is not a ``types.CodeType`` instance.

        Notes
        -----
        The decompilation pipeline:
        1. Check secure mode restrictions on external decompilers
        2. Validate that ``code`` is a ``CodeType``
        3. Attempt the preferred decompiler
        4. If that fails, iterate through all other available decompilers
        5. Raise ``RuntimeError`` if all backends fail

        Examples
        --------
        >>> loader = PycLoader()
        >>> code = compile("x = 42", "<test>", "exec")
        >>> source = loader.decompile_bytecode(code)
        >>> print(source)
        x = 42

        >>> # With explicit decompiler preference
        >>> source = loader.decompile_bytecode(code, preferred_decompiler="dis")
        """
        if self.config.secure_mode and preferred_decompiler != "dis":
            raise RuntimeError("External decompilation disabled in secure mode")

        if not isinstance(code, types.CodeType):
            raise TypeError(f"Expected CodeType, got {type(code)}")

        decompiler_name = preferred_decompiler or self.active_decompiler

        if decompiler_name and decompiler_name in self.decompilers:
            try:
                return self._run_decompiler(decompiler_name, code)
            except Exception as e:
                logger.warning("Decompiler '%s' failed: %s", decompiler_name, e)

        for name in self.decompilers:
            if name != decompiler_name:
                try:
                    return self._run_decompiler(name, code)
                except Exception as e:
                    logger.debug("Decompiler '%s' failed: %s", name, e)

        raise RuntimeError("All decompilation backends failed")

    def _run_decompiler(self, name: str, code: types.CodeType) -> str:
        """
        Run a specific decompiler backend.

        Dispatches to the appropriate backend method based on the
        decompiler name. Validates that the output is non-empty.

        Parameters
        ----------
        name : str
            Decompiler name. Must be one of ``"decompyle3"``,
            ``"uncompyle6"``, ``"pycdc"``, or ``"dis"``.
        code : types.CodeType
            Code object to decompile.

        Returns
        -------
        str
            The decompiled source code.

        Raises
        ------
        ValueError
            If the decompiler name is not recognized.
        RuntimeError
            If the decompiler produces empty or whitespace-only
            output (indicating decompilation failure).

        Notes
        -----
        Backend methods are responsible for the actual decompilation
        logic. The dispatch is via an internal dictionary for O(1)
        lookup.
        """
        backend_map = {
            "decompyle3": self._decompyle3_backend,
            "uncompyle6": self._uncompyle6_backend,
            "pycdc": self._pycdc_backend,
            "dis": self._dis_backend,
        }

        backend = backend_map.get(name)
        if not backend:
            raise ValueError(f"Unknown decompiler: {name}")

        result = backend(code)
        if not result or result.isspace():
            raise RuntimeError(f"Decompiler '{name}' produced empty output")
        return result

    def _decompyle3_backend(self, code: types.CodeType) -> str:
        """
        Decompile using decompyle3 library.

        Uses the ``decompyle3.main.decompile`` function to produce
        source code from a code object.

        Parameters
        ----------
        code : types.CodeType
            Code object to decompile.

        Returns
        -------
        str
            Decompiled source code as returned by decompyle3.

        Notes
        -----
        Requires ``decompyle3`` to be installed. The ``magic``
        argument (2.7 in the call) refers to the decompyle3 API
        version, not the Python version.

        Output is captured via a ``StringIO`` buffer.
        """
        from decompyle3.main import decompile
        import io

        out = io.StringIO()
        decompile(2.7, code, out)
        result = out.getvalue()
        return result

    def _uncompyle6_backend(self, code: types.CodeType) -> str:
        """
        Decompile using uncompyle6 library.

        Uses the ``uncompyle6.decompile`` function with the current
        Python version to produce source code.

        Parameters
        ----------
        code : types.CodeType
            Code object to decompile.

        Returns
        -------
        str
            Decompiled source code as returned by uncompyle6.

        Notes
        -----
        Requires ``uncompyle6`` to be installed. The version
        parameters are taken from ``sys.version_info``.

        Output is captured via a ``StringIO`` buffer.
        """
        import uncompyle6
        import io

        out = io.StringIO()
        uncompyle6.decompile(
            sys.version_info.major,
            sys.version_info.minor,
            code,
            out,
        )
        return out.getvalue()

    def _pycdc_backend(self, code: types.CodeType) -> str:
        """
        Decompile using pycdc external tool.

        Writes the code object to a temporary .pyc file, invokes
        the ``pycdc`` command-line tool on it, and returns the
        captured stdout.

        Parameters
        ----------
        code : types.CodeType
            Code object to decompile.

        Returns
        -------
        str
            Decompiled source code from pycdc's stdout.

        Raises
        ------
        RuntimeError
            If pycdc exits with a non-zero return code.

        Notes
        -----
        Creates a temporary .pyc file with a valid header (using
        Python 3.9 magic number) before invoking pycdc. The
        temporary file is always cleaned up after use.

        The subprocess is subject to ``config.timeout`` to prevent
        hanging on large or complex code objects.
        """
        with tempfile.NamedTemporaryFile(suffix=".pyc", delete=False, mode='wb') as tmp:
            import time as time_module
            header = struct.pack(
                "<HHII",
                *BytecodeVersion.V3_9.value,
                int(time_module.time()),
                0,
            )
            tmp.write(header)
            tmp.write(marshal.dumps(code))
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                ["pycdc", tmp_path],
                capture_output=True, text=True,
                timeout=self.config.timeout, check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(f"pycdc failed (exit {result.returncode}): {result.stderr[:200]}")

            output = result.stdout.strip()
            return output
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

    def _dis_backend(self, code: types.CodeType) -> str:
        """
        Fallback decompiler using dis module.

        Produces a human-readable disassembly with pseudo-code
        structure. This is not true decompilation but provides
        insight into the bytecode instructions.

        Parameters
        ----------
        code : types.CodeType
            Code object to disassemble.

        Returns
        -------
        str
            Disassembly text with header comments, argument list
            (for functions), and instruction listing.

        Notes
        -----
        The output includes:
        - A header indicating auto-generation
        - Original filename and code name
        - For named functions: a ``def`` signature with arguments
        - For modules: a ``# Module-level code`` comment
        - Numbered bytecode instructions with argument resolution
        - A ``pass`` placeholder indicating incomplete decompilation

        Variable and name lookups resolve instruction arguments to
        their symbolic names where possible.
        """
        import io

        out = io.StringIO()
        out.write(f"# Auto-generated from bytecode (Python {sys.version})\n")
        out.write(f"# Original: {code.co_filename}\n")
        out.write(f"# Name: {code.co_name}\n\n")

        names = list(code.co_names)
        varnames = list(code.co_varnames)

        if code.co_name == '<module>':
            out.write("# Module-level code\n")
        else:
            args = varnames[:code.co_argcount]
            out.write(f"def {code.co_name}({', '.join(args)}):\n")

        instructions = list(dis.get_instructions(code))
        out.write("    # Bytecode instructions:\n")

        indent = "    " if code.co_name != '<module>' else ""
        for instr in instructions:
            out.write(f"    {indent}# {instr.offset:4d} {instr.opname:<20s}")
            if instr.arg is not None:
                out.write(f" {instr.arg:4d}")
                if instr.arg < len(names):
                    out.write(f" ({names[instr.arg]})")
            out.write("\n")

        out.write(f"\n{indent}# Unable to fully decompile bytecode\n")
        out.write(f"{indent}pass  # Placeholder\n")

        return out.getvalue()

    def _find_compatible_interpreter(
        self, version: Tuple[int, int]
    ) -> Optional[str]:
        """
        Find a Python interpreter matching the specified version.

        Searches for Python interpreters in common locations and
        verifies their version by running a small script.

        Parameters
        ----------
        version : Tuple[int, int]
            The target Python version as ``(major, minor)``, e.g.,
            ``(3, 9)``.

        Returns
        -------
        Optional[str]
            Path to a compatible Python interpreter executable, or
            ``None`` if no matching interpreter could be found.

        Notes
        -----
        The search checks the following candidates (in order):
        - ``python{major}.{minor}`` (e.g., ``python3.9``)
        - ``python{major}{minor}`` (e.g., ``python39``)
        - ``python{major}`` (e.g., ``python3``)
        - On Windows: ``py -{major}.{minor}``
        - ``/usr/bin/python{major}.{minor}``
        - ``/usr/local/bin/python{major}.{minor}``

        Each candidate is verified by running it with ``-c "import
        sys; print(sys.version_info[:2])"`` and comparing the output.
        """
        major, minor = version

        candidates = [
            f"python{major}.{minor}",
            f"python{major}{minor}",
            f"python{major}",
            f"py -{major}.{minor}" if platform.system() == "Windows" else None,
            f"/usr/bin/python{major}.{minor}",
            f"/usr/local/bin/python{major}.{minor}",
        ]

        for candidate in filter(None, candidates):
            found = shutil.which(candidate)
            if not found and Path(candidate).exists():
                found = candidate

            if found:
                try:
                    result = subprocess.run(
                        [found, "-c", "import sys; print(sys.version_info[:2])"],
                        capture_output=True, text=True, timeout=5, check=False,
                    )

                    if result.returncode == 0:
                        found_version = tuple(
                            map(int, result.stdout.strip().strip('()').split(','))
                        )
                        if found_version == version:
                            return found
                except (subprocess.TimeoutExpired, OSError, ValueError):
                    continue

        return None

    def _check_cache(
        self, path: Path, name: str
    ) -> Optional[CacheEntry]:
        """
        Check if module is in cache and still valid.

        Searches the in-memory cache first, then the disk cache
        if enabled. Validates cache entries by comparing file
        modification times.

        Parameters
        ----------
        path : Path
            Path to the .pyc file.
        name : str
            Module name.

        Returns
        -------
        Optional[CacheEntry]
            A ``CacheEntry`` if a valid cached version is found;
            ``None`` if no cache entry exists or the cached entry
            is stale (file modification time has changed).

        Notes
        -----
        Cache validation uses ``path.stat().st_mtime`` to detect
        changes to the underlying file. If the file has been
        modified since it was cached, the cache entry is considered
        stale and is not returned.

        Disk cache entries are loaded into memory on hit for faster
        subsequent access.
        """
        cache_key = self._get_cache_key(path, name)

        if cache_key in self._cache_entries:
            entry = self._cache_entries[cache_key]
            if path.stat().st_mtime <= entry.file_mtime:
                logger.debug("Memory cache hit for '%s'", name)
                return entry

        if self.config.cache_enabled:
            cache_file = self.cache_dir / f"{cache_key}.pickle"
            if cache_file.exists():
                try:
                    with open(cache_file, "rb") as f:
                        cached = pickle.load(f)

                    if cached['mtime'] == path.stat().st_mtime:
                        logger.debug("Disk cache hit for '%s'", name)
                        entry = CacheEntry(
                            module=importlib.import_module(cached['module_name']),
                            metadata=cached['metadata'],
                            file_mtime=cached['mtime'],
                        )
                        self._cache_entries[cache_key] = entry
                        return entry
                except (pickle.PickleError, KeyError, OSError, EOFError, ModuleNotFoundError):
                    with contextlib.suppress(OSError):
                        cache_file.unlink()

        return None

    def _update_cache(
        self,
        path: Path,
        name: str,
        module: ModuleType,
        metadata: BytecodeMetadata,
    ) -> None:
        """
        Update cache with loaded module.

        Adds the module to the in-memory cache and persists it to
        disk (if disk caching is enabled). Enforces the maximum
        cache size by evicting the oldest entry (LRU policy) when
        the limit is exceeded.

        Parameters
        ----------
        path : Path
            Path to the .pyc file.
        name : str
            Module name.
        module : ModuleType
            The loaded module to cache.
        metadata : BytecodeMetadata
            Metadata associated with the module.

        Returns
        -------
        None

        Notes
        -----
        - **Eviction**: When the in-memory cache size exceeds
          ``config.max_cache_size``, the entry with the earliest
          ``cached_at`` timestamp is removed.
        - **Persistence**: Disk cache files are written using
          ``pickle.HIGHEST_PROTOCOL`` for efficiency. Corruption
          during write is logged but does not raise an exception.
        - **Cache key**: Generated by ``_get_cache_key`` using
          the file path, module name, and Python version.
        """
        cache_key = self._get_cache_key(path, name)
        file_mtime = path.stat().st_mtime

        entry = CacheEntry(
            module=module,
            metadata=metadata,
            file_mtime=file_mtime,
        )
        self._cache_entries[cache_key] = entry

        if len(self._cache_entries) > self.config.max_cache_size:
            oldest_key = min(
                self._cache_entries,
                key=lambda k: self._cache_entries[k].cached_at
            )
            del self._cache_entries[oldest_key]

        if self.config.cache_enabled:
            try:
                cache_file = self.cache_dir / f"{cache_key}.pickle"
                with open(cache_file, "wb") as f:
                    pickle.dump({
                        'module_name': module.__name__,
                        'metadata': metadata,
                        'mtime': file_mtime,
                        'timestamp': datetime.now(timezone.utc),
                    }, f, protocol=pickle.HIGHEST_PROTOCOL)
            except (pickle.PickleError, OSError) as e:
                logger.warning("Failed to write cache: %s", e)

    def _get_cache_key(self, path: Path, name: str) -> str:
        """
        Generate a unique cache key.

        Creates a deterministic key based on the absolute file path,
        module name, and current Python version. Uses SHA-256 hashing
        to produce a fixed-length, filesystem-safe identifier.

        Parameters
        ----------
        path : Path
            Absolute path to the .pyc file.
        name : str
            Module name.

        Returns
        -------
        str
            A 16-character hexadecimal string (truncated SHA-256)
            that uniquely identifies the cache entry.

        Notes
        -----
        The Python version is included in the key to prevent cache
        collisions between different Python versions that might
        produce different loading behavior for the same .pyc file.
        """
        unique = f"{path.absolute()}:{name}:{sys.version_info[:2]}"
        return hashlib.sha256(unique.encode()).hexdigest()[:16]

    def clear_cache(self) -> None:
        """
        Clear all cached modules.

        Removes all entries from the in-memory cache and deletes
        all pickle files from the disk cache directory (if caching
        is enabled).

        Returns
        -------
        None

        Notes
        -----
        Disk cache deletion targets all ``*.pickle`` files in the
        cache directory. Individual file deletion failures are
        silently suppressed to avoid masking other cleanup actions.

        Examples
        --------
        >>> loader = PycLoader()
        >>> loader.clear_cache()
        >>> loader.statistics.cache_size
        0
        """
        self._cache_entries.clear()

        if self.config.cache_enabled:
            for cache_file in self.cache_dir.glob("*.pickle"):
                with contextlib.suppress(OSError):
                    cache_file.unlink()

        logger.info("Cache cleared")

    def _generate_suggestions(
        self,
        errors: List[Tuple[LoadStrategy, Exception]],
        metadata: BytecodeMetadata,
    ) -> List[str]:
        """
        Generate human-readable suggestions based on errors.

        Analyzes the pattern of failures across strategies and
        produces actionable suggestions for resolving the loading
        problem. Suggestions are capped at 5 to avoid overwhelming
        the user.

        Parameters
        ----------
        errors : List[Tuple[LoadStrategy, Exception]]
            List of (strategy, exception) pairs from all failed
            strategy attempts.
        metadata : BytecodeMetadata
            Bytecode metadata for version-specific suggestions.

        Returns
        -------
        List[str]
            List of suggestion strings, each describing one
            potential remediation action. Limited to a maximum
            of 5 suggestions.

        Notes
        -----
        Suggestion generation checks for specific failure patterns:
        - **Version mismatch**: Suggests using the correct Python version
        - **Decompilation failure**: Suggests installing decompilers
        - **Corrupted file**: Suggests obtaining the original source
        - **Permission errors**: Suggests checking file permissions
        - **No interpreter found**: Suggests installing Python

        Generic fallback suggestions are always appended.
        """
        suggestions = []

        if not metadata.is_compatible:
            suggestions.append(
                f"Bytecode compiled for Python {metadata.version_string}, "
                f"but running Python {sys.version_info[0]}.{sys.version_info[1]}. "
                f"Use Python {metadata.version_string} to load directly."
            )

        recompile_failed = any(s == LoadStrategy.RECOMPILE for s, _ in errors)
        if recompile_failed:
            suggestions.extend([
                "Install decompyle3: pip install decompyle3",
                "Install uncompyle6: pip install uncompyle6",
            ])

        marshal_failed = any(
            s == LoadStrategy.MARSHAL_LOAD and isinstance(e, (EOFError, ValueError))
            for s, e in errors
        )
        if marshal_failed:
            suggestions.append(
                "The .pyc file may be corrupted. Try obtaining the original .py file."
            )

        permission_errors = any("Permission" in str(e) for _, e in errors)
        if permission_errors:
            suggestions.append("Check file permissions: ensure the file is readable")

        if not shutil.which("python3"):
            suggestions.append("No Python interpreter found in PATH for fallback")

        suggestions.extend([
            "Check if the .pyc file is from a compatible Python version",
            "Try loading the original .py source file if available",
            "Use inspect_pyc() to examine the file before loading",
        ])

        return suggestions[:5]

    def __repr__(self) -> str:
        """
        Return string representation of the loader.

        Includes the number of configured strategies, security
        mode status, cache status, and current Python version.

        Returns
        -------
        str
            String like
            ``"PycLoader(strategies=7, secure=False, cache=enabled, py=3.11)"``.
        """
        return (
            f"PycLoader(strategies={len(self.config.strategies)}, "
            f"secure={self.config.secure_mode}, "
            f"cache={'enabled' if self.config.cache_enabled else 'disabled'}, "
            f"py={sys.version_info[0]}.{sys.version_info[1]})"
        )

    def __enter__(self):
        """
        Context manager entry.

        Returns the loader instance for use in a ``with`` statement.

        Returns
        -------
        PycLoader
            The loader instance (``self``).

        Examples
        --------
        >>> with PycLoader() as loader:
        ...     result = loader.load("module.pyc")
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Context manager exit with cleanup.

        Shuts down the thread pool executor if one was created.
        Does not suppress exceptions.

        Parameters
        ----------
        exc_type : Optional[Type[BaseException]]
            Exception type if an exception occurred in the context.
        exc_val : Optional[BaseException]
            Exception value if an exception occurred.
        exc_tb : Optional[TracebackType]
            Traceback if an exception occurred.

        Returns
        -------
        None
            Does not suppress exceptions.
        """
        if self._executor:
            self._executor.shutdown(wait=False)


# ============================================================================
# Async PycLoader
# ============================================================================

class AsyncPycLoader(PycLoader):
    """
    Async wrapper for PycLoader with non-blocking operations.

    Provides async/await versions of all major methods by offloading
    blocking operations to a thread pool executor. Designed for use
    in asyncio-based applications where synchronous I/O would block
    the event loop.

    Inherits all functionality from ``PycLoader``.

    Parameters
    ----------
    config : LoaderConfig, optional
        Configuration object passed through to ``PycLoader.__init__``.

    Notes
    -----
    All async methods use ``asyncio.get_running_loop()`` and
    ``loop.run_in_executor()`` to execute the synchronous version
    in a thread pool, returning an awaitable coroutine.

    Supports the async context manager protocol for proper cleanup:

    >>> async with AsyncPycLoader() as loader:
    ...     result = await loader.load_async("module.pyc")

    Examples
    --------
    >>> async def main():
    ...     loader = AsyncPycLoader()
    ...     result = await loader.load_async("module.pyc", "mod")
    ...     print(result.module.my_function())
    ...     print(result.metadata.version_string)

    >>> async with AsyncPycLoader() as loader:
    ...     meta = await loader.detect_version_async("module.pyc")
    ...     result = await loader.load_async("module.pyc")
    """

    def __init__(self, config: Optional[LoaderConfig] = None):
        """
        Initialize async bytecode loader.

        Creates an additional thread pool executor for async
        operations alongside the parent class executor.

        Parameters
        ----------
        config : LoaderConfig, optional
            Configuration object. Passed to ``PycLoader.__init__``.
        """
        super().__init__(config)
        self._async_executor = ThreadPoolExecutor(
            max_workers=self.config.max_workers,
            thread_name_prefix="async_pyc",
        )

    async def load_async(
        self,
        path: Union[str, Path],
        name: str = "loaded_module",
    ) -> LoadResult:
        """
        Async version of :meth:`PycLoader.load`.

        Offloads the synchronous ``load()`` call to a thread pool
        executor to avoid blocking the event loop.

        Parameters
        ----------
        path : Union[str, Path]
            Path to the .pyc file.
        name : str, optional
            Module name. Default is ``"loaded_module"``.

        Returns
        -------
        LoadResult
            A ``LoadResult`` dataclass with the loaded module,
            metadata, strategy, and timing.

        Examples
        --------
        >>> async def main():
        ...     loader = AsyncPycLoader()
        ...     result = await loader.load_async("module.pyc")
        ...     print(result.metadata.version_string)
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._async_executor,
            super().load,
            path,
            name,
        )

    async def detect_version_async(
        self,
        path: Union[str, Path],
    ) -> BytecodeMetadata:
        """
        Async version of :meth:`PycLoader.detect_version`.

        Offloads the synchronous ``detect_version()`` call to a
        thread pool executor.

        Parameters
        ----------
        path : Union[str, Path]
            Path to the .pyc file.

        Returns
        -------
        BytecodeMetadata
            Comprehensive bytecode metadata.

        Examples
        --------
        >>> async def main():
        ...     loader = AsyncPycLoader()
        ...     meta = await loader.detect_version_async("module.pyc")
        ...     print(meta.version_string)
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._async_executor,
            super().detect_version,
            path,
        )

    async def __aenter__(self):
        """
        Async context manager entry.

        Returns the loader instance for use in an ``async with``
        statement.

        Returns
        -------
        AsyncPycLoader
            The loader instance (``self``).
        """
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        Async context manager exit with cleanup.

        Shuts down both the async executor and the parent class
        executor.

        Parameters
        ----------
        exc_type : Optional[Type[BaseException]]
            Exception type if an exception occurred.
        exc_val : Optional[BaseException]
            Exception value if an exception occurred.
        exc_tb : Optional[TracebackType]
            Traceback if an exception occurred.
        """
        if self._async_executor:
            self._async_executor.shutdown(wait=False)
        if self._executor:
            self._executor.shutdown(wait=False)


# ============================================================================
# Utility Functions
# ============================================================================

def as_completed_with_timeout(
    futures: List[Future],
    timeout: Optional[float] = None,
) -> Iterator[Future]:
    """
    Wait for futures to complete with optional timeout.

    Yields completed futures as they finish, respecting an optional
    maximum wait time. After the timeout expires, no more futures
    are yielded.

    Parameters
    ----------
    futures : List[Future]
        List of ``concurrent.futures.Future`` objects to wait for.
        If the list is empty, the generator yields nothing and
        returns immediately.
    timeout : float, optional
        Maximum time to wait in seconds. If ``None``, waits
        indefinitely for all futures to complete. Default is
        ``None``.

    Yields
    ------
    Future
        Completed futures in the order they finish. Futures that
        time out are not yielded.

    Notes
    -----
    Wraps ``concurrent.futures.as_completed`` with a try-except
    for ``TimeoutError``. When a timeout occurs, the generator
    stops yielding, but incomplete futures are not canceled—they
    continue running in the background.

    Examples
    --------
    >>> from concurrent.futures import ThreadPoolExecutor
    >>> with ThreadPoolExecutor() as executor:
    ...     futures = [executor.submit(time.sleep, i) for i in range(3)]
    ...     for completed in as_completed_with_timeout(futures, timeout=2):
    ...         result = completed.result()  # First two futures complete
    """
    if not futures:
        return

    from concurrent.futures import TimeoutError as FuturesTimeoutError

    try:
        for completed in as_completed(futures, timeout=timeout):
            yield completed
    except FuturesTimeoutError:
        pass


@dataclass(frozen=True)
class LoaderSystemInfo:
    """
    System information relevant to bytecode loading.

    Aggregates information about the current Python runtime
    environment, including version, platform, and available
    decompilation tools.

    Parameters
    ----------
    python_version : Tuple[int, int]
        Current Python version as ``(major, minor)``, e.g.,
        ``(3, 11)``.
    python_full_version : str
        Full Python version string as reported by
        ``sys.version.split()[0]``, e.g., ``"3.11.5"``.
    platform : PlatformInfo
        Platform information for the current system.
    available_decompilers : List[DecompilerInfo]
        List of decompiler backends available on this system,
        including both available and unavailable ones.

    Attributes
    ----------
    python_version_string : str
        Computed property returning the major.minor version as
        a dotted string.

    Examples
    --------
    >>> info = get_system_info()
    >>> print(info.python_version_string)
    3.11
    >>> print(info.platform.identifier)
    linux-x86_64-64
    >>> for d in info.available_decompilers:
    ...     print(f"{d.name}: {'available' if d.available else 'not available'}")
    """
    python_version: Tuple[int, int]
    python_full_version: str
    platform: PlatformInfo
    available_decompilers: List[DecompilerInfo]

    @property
    def python_version_string(self) -> str:
        """
        Get Python version as a dotted string.

        Returns
        -------
        str
            Version string like ``"3.11"``.
        """
        return f"{self.python_version[0]}.{self.python_version[1]}"


def get_system_info() -> LoaderSystemInfo:
    """
    Get comprehensive system information for bytecode loading.

    Creates a temporary ``PycLoader`` instance to query platform
    and decompiler information, then returns a structured
    ``LoaderSystemInfo`` dataclass.

    Returns
    -------
    LoaderSystemInfo
        Structured system information including Python version,
        platform details, and available decompilers.

    Notes
    -----
    This function instantiates a ``PycLoader``, which may trigger
    decompiler detection (import attempts) but does not load any
    bytecode.

    Examples
    --------
    >>> info = get_system_info()
    >>> print(f"Python {info.python_version_string} on {info.platform.identifier}")
    Python 3.11 on linux-x86_64-64
    """
    loader = PycLoader()
    return LoaderSystemInfo(
        python_version=sys.version_info[:2],
        python_full_version=sys.version.split()[0],
        platform=loader.get_current_platform(),
        available_decompilers=loader.list_decompilers(),
    )


def load_pyc(
    path: Union[str, Path],
    name: str = "loaded_module",
    *,
    secure: bool = False,
    config: Optional[LoaderConfig] = None,
    **kwargs: Any,
) -> LoadResult:
    """
    Load a Python bytecode file with intelligent cross-version support.

    Convenience function that creates a ``PycLoader`` with the
    specified configuration and calls ``load()``.

    Parameters
    ----------
    path : Union[str, Path]
        Path to the .pyc file to load.
    name : str, optional
        Module name to assign. Default is ``"loaded_module"``.
    secure : bool, optional
        Enable secure mode (disables external tools, validates
        bytecode more strictly). Default is ``False``.
    config : LoaderConfig, optional
        Full configuration object. If provided, the ``secure``
        parameter and ``**kwargs`` are applied as overrides on
        top of this configuration. Default is ``None``.
    **kwargs : Any
        Additional configuration overrides. Any keyword argument
        matching a ``LoaderConfig`` field name will be set on the
        configuration before loading.

    Returns
    -------
    LoadResult
        Structured result with module, metadata, and strategy info.

    Raises
    ------
    PycLoadError
        If all loading strategies fail.

    Examples
    --------
    >>> result = load_pyc("compiled.cpython-39.pyc", "my_module")
    >>> result.module.calculate(10, 20)
    >>> print(f"Loaded with: {result.strategy_used.name}")
    >>> print(f"Time: {result.load_time_ms:.1f}ms")

    >>> # With configuration overrides
    >>> result = load_pyc("module.pyc", cache_enabled=False, timeout=60)
    """
    loader_config = config or LoaderConfig(secure_mode=secure)

    for key, value in kwargs.items():
        if hasattr(loader_config, key):
            setattr(loader_config, key, value)

    loader = PycLoader(loader_config)
    return loader.load(path, name)


def detect_pyc_version(path: Union[str, Path]) -> BytecodeMetadata:
    """
    Quick detection of Python version from a .pyc file.

    Convenience function that creates a ``PycLoader`` and calls
    ``detect_version()``.

    Parameters
    ----------
    path : Union[str, Path]
        Path to the .pyc file to analyze.

    Returns
    -------
    BytecodeMetadata
        Metadata including Python version, magic number, flags,
        and compatibility information.

    Examples
    --------
    >>> meta = detect_pyc_version("module.cpython-39.pyc")
    >>> print(f"Python {meta.version_string}")
    Python 3.9
    >>> print(f"Magic: {meta.magic_hex}")
    Magic: 0x00000eb2
    """
    loader = PycLoader()
    return loader.detect_version(path)


def decompile_pyc(
    path: Union[str, Path],
    *,
    preferred_decompiler: Optional[str] = None,
) -> str:
    """
    Extract readable Python source code from a .pyc file.

    Reads the code object from the .pyc file and attempts to
    decompile it back to Python source code.

    Parameters
    ----------
    path : Union[str, Path]
        Path to the .pyc file.
    preferred_decompiler : str, optional
        Name of the preferred decompiler backend. If ``None``,
        uses the first available decompiler. Default is ``None``.

    Returns
    -------
    str
        Reconstructed Python source code. Quality depends on
        the decompiler used and the complexity of the original
        code.

    Examples
    --------
    >>> source = decompile_pyc("compiled.pyc")
    >>> print(source)
    def hello():
        print("Hello, World!")

    >>> # Save decompiled source
    >>> source = decompile_pyc("module.pyc", preferred_decompiler="decompyle3")
    >>> with open("recovered.py", "w") as f:
    ...     f.write(source)
    """
    loader = PycLoader()

    with open(path, "rb") as f:
        f.seek(16)
        code = marshal.load(f)

    return loader.decompile_bytecode(code, preferred_decompiler=preferred_decompiler)


def batch_load_pyc(
    paths: List[Union[str, Path]],
    names: Optional[List[str]] = None,
    *,
    config: Optional[LoaderConfig] = None,
    parallel: bool = True,
) -> BatchLoadResult:
    """
    Load multiple .pyc files efficiently.

    Processes a list of .pyc files, optionally in parallel, and
    returns aggregated results.

    Parameters
    ----------
    paths : List[Union[str, Path]]
        List of paths to .pyc files to load.
    names : List[str], optional
        List of module names corresponding to each path. If
        ``None``, auto-generates names as ``"module_0"``,
        ``"module_1"``, etc. Default is ``None``.
    config : LoaderConfig, optional
        Loader configuration. If ``None``, uses default
        configuration with ``parallel_loading`` set to the
        ``parallel`` parameter. Default is ``None``.
    parallel : bool, optional
        Whether to load modules in parallel using a thread pool.
        Default is ``True``.

    Returns
    -------
    BatchLoadResult
        Structured batch results with successful loads, failures,
        timing, and success rate.

    Raises
    ------
    ValueError
        If the number of ``paths`` does not match the number of
        ``names`` (when names are provided).

    Notes
    -----
    Parallel loading uses the thread pool executor from a shared
    ``PycLoader`` instance. Each module is loaded independently,
    and failures in one module do not prevent others from being
    loaded.

    Examples
    --------
    >>> result = batch_load_pyc(
    ...     ["a.pyc", "b.pyc", "c.pyc"],
    ...     names=["mod_a", "mod_b", "mod_c"]
    ... )
    >>> for name, module in result.all_modules.items():
    ...     print(f"{name}: loaded successfully")
    >>> print(f"Failed: {list(result.failed.keys())}")
    >>> print(f"Success rate: {result.success_rate:.1%}")
    """
    if names is None:
        names = [f"module_{i}" for i in range(len(paths))]

    if len(paths) != len(names):
        raise ValueError("Number of paths must match number of names")

    loader_config = config or LoaderConfig(parallel_loading=parallel)
    loader = PycLoader(loader_config)

    start_time = time.perf_counter()
    successful: Dict[str, LoadResult] = {}
    failed: Dict[str, LoadError] = {}

    if parallel and loader._executor:
        futures: Dict[Future, Tuple[str, Path]] = {}
        for path, name in zip(paths, names):
            future = loader._executor.submit(loader.load, path, name)
            futures[future] = (name, Path(path))

        for future in as_completed_with_timeout(futures.keys(), timeout=loader_config.timeout):
            name, path = futures[future]
            try:
                result = future.result()
                successful[name] = result
            except PycLoadError as e:
                failed[name] = e.error_info
            except Exception as e:
                failed[name] = LoadError(
                    message=str(e),
                    error_type=type(e).__name__,
                )
    else:
        for path, name in zip(paths, names):
            try:
                result = loader.load(path, name)
                successful[name] = result
            except PycLoadError as e:
                failed[name] = e.error_info
            except Exception as e:
                failed[name] = LoadError(
                    message=str(e),
                    error_type=type(e).__name__,
                )

    total_time = (time.perf_counter() - start_time) * 1000

    if failed:
        logger.warning(
            "Failed to load %d/%d modules: %s",
            len(failed), len(paths),
            ', '.join(f"{k}: {v.message}" for k, v in failed.items()),
        )

    return BatchLoadResult(
        successful=successful,
        failed=failed,
        total_time_ms=total_time,
        parallel=parallel,
    )


def inspect_pyc(path: Union[str, Path]) -> InspectionResult:
    """
    Inspect a .pyc file and return detailed structured information.

    Reads the .pyc header and code object to produce comprehensive
    inspection results without executing any bytecode.

    Parameters
    ----------
    path : Union[str, Path]
        Path to the .pyc file to inspect.

    Returns
    -------
    InspectionResult
        Detailed inspection results including metadata, code
        structure, variable names, bytecode statistics, and
        instruction count.

    Notes
    -----
    If the code object cannot be read (e.g., corrupted file), a
    minimal ``InspectionResult`` is returned with ``code_name``
    set to ``"<error>"`` and most fields zeroed out.

    Examples
    --------
    >>> info = inspect_pyc("module.pyc")
    >>> print(f"Name: {info.code_name}")
    >>> print(f"Arguments: {info.argument_count}")
    >>> print(f"Instructions: {info.instruction_count}")
    >>> print(f"Is function: {info.is_function}")
    >>> print(f"Bytecode size: {info.bytecode_size} bytes")
    """
    loader = PycLoader()
    metadata = loader.detect_version(path)

    try:
        with open(path, "rb") as f:
            f.seek(16)
            code = marshal.load(f)

        instruction_count = len(list(dis.get_instructions(code)))
        nested_count = sum(
            1 for const in code.co_consts if isinstance(const, types.CodeType)
        )

        return InspectionResult(
            metadata=metadata,
            code_name=code.co_name,
            code_filename=code.co_filename,
            argument_count=code.co_argcount,
            local_count=code.co_nlocals,
            stack_size=code.co_stacksize,
            code_flags=code.co_flags,
            bytecode_size=len(code.co_code),
            constants_count=len(code.co_consts),
            names=list(code.co_names),
            variable_names=list(code.co_varnames),
            nested_code_objects=nested_count,
            instruction_count=instruction_count,
        )
    except Exception as e:
        return InspectionResult(
            metadata=metadata,
            code_name="<error>",
            code_filename=str(path),
            argument_count=0,
            local_count=0,
            stack_size=0,
            code_flags=0,
            bytecode_size=0,
            constants_count=0,
            names=[],
            variable_names=[],
        )


# ============================================================================
# CLI Interface
# ============================================================================

def main() -> None:
    """
    Command-line interface for PycLoader.

    Provides subcommands for loading, inspecting, decompiling, and
    batch-processing .pyc files from the terminal.

    Subcommands
    -----------
    load
        Load a .pyc file and display information about the loaded module.
    inspect
        Inspect a .pyc file and display detailed metadata and code
        structure.
    decompile
        Decompile a .pyc file and output the reconstructed source code.
    batch
        Batch-process multiple .pyc files.

    Options
    -------
    For detailed usage, run with ``--help``:

    .. code-block:: bash

        python -m pyputil.pyc --help
        python -m pyputil.pyc load --help
        python -m pyputil.pyc inspect --help
        python -m pyputil.pyc decompile --help
        python -m pyputil.pyc batch --help

    Examples
    --------
    .. code-block:: bash

        # Load a module
        python -m pyputil.pyc load module.pyc -n mymodule

        # Inspect with verbose output
        python -m pyputil.pyc inspect module.pyc -v

        # Decompile to file
        python -m pyputil.pyc decompile module.pyc -o recovered.py

        # Batch load with parallel execution
        python -m pyputil.pyc batch a.pyc b.pyc c.pyc --parallel
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Python Bytecode (.pyc) Loader and Inspector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s load module.pyc
  %(prog)s inspect module.pyc
  %(prog)s decompile module.pyc
  %(prog)s batch load *.pyc
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Load command
    load_parser = subparsers.add_parser("load", help="Load a .pyc file")
    load_parser.add_argument("path", help="Path to .pyc file")
    load_parser.add_argument("-n", "--name", default="loaded_module", help="Module name")
    load_parser.add_argument("--secure", action="store_true", help="Enable secure mode")
    load_parser.add_argument("--no-cache", action="store_true", help="Disable caching")
    load_parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity")

    # Inspect command
    inspect_parser = subparsers.add_parser("inspect", help="Inspect a .pyc file")
    inspect_parser.add_argument("path", help="Path to .pyc file")
    inspect_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # Decompile command
    decompile_parser = subparsers.add_parser("decompile", help="Decompile a .pyc file")
    decompile_parser.add_argument("path", help="Path to .pyc file")
    decompile_parser.add_argument("-o", "--output", help="Output file")
    decompile_parser.add_argument("-d", "--decompiler", help="Preferred decompiler")

    # Batch command
    batch_parser = subparsers.add_parser("batch", help="Batch operations")
    batch_parser.add_argument("paths", nargs="+", help=".pyc files")
    batch_parser.add_argument("--parallel", action="store_true", help="Load in parallel")

    args = parser.parse_args()

    log_levels = [logging.WARNING, logging.INFO, logging.DEBUG]
    log_level = log_levels[min(args.verbose, len(log_levels) - 1)] if hasattr(args, 'verbose') else logging.WARNING

    logging.basicConfig(level=log_level, format='%(levelname)s: %(message)s')

    if args.command == "load":
        loader = PycLoader(LoaderConfig(
            secure_mode=args.secure,
            cache_enabled=not args.no_cache,
            log_level=log_level,
        ))

        try:
            result = loader.load(args.path, args.name)
            print(f"Successfully loaded module '{args.name}'")
            print(f"Strategy: {result.strategy_used.name}")
            print(f"Load time: {result.load_time_ms:.1f}ms")
            print(f"Python version: {result.metadata.version_string}")

            public_members = [
                k for k in dir(result.module)
                if not k.startswith('_') or k in ('__version__', '__author__')
            ]
            if public_members:
                print(f"Public members: {', '.join(public_members)}")

        except PycLoadError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "inspect":
        try:
            info = inspect_pyc(args.path)
            if args.json:
                print(json.dumps(asdict(info), indent=2, default=str))
            else:
                print(f"File: {args.path}")
                print(f"Python Version: {info.metadata.version_string}")
                print(f"Magic Number: {info.metadata.magic_hex}")
                print(f"Timestamp: {info.metadata.timestamp.isoformat()}")
                print(f"Source Size: {info.metadata.source_size} bytes")
                print(f"File Size: {info.metadata.file_size} bytes")
                print(f"Platform: {info.metadata.platform.identifier}")
                print(f"Compatible: {info.metadata.is_compatible}")
                print(f"\nCode Name: {info.code_name}")
                print(f"Arguments: {info.argument_count}")
                print(f"Locals: {info.local_count}")
                print(f"Stack Size: {info.stack_size}")
                print(f"Instructions: {info.instruction_count}")
                print(f"Nested Code Objects: {info.nested_code_objects}")

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "decompile":
        try:
            source = decompile_pyc(args.path, preferred_decompiler=args.decompiler)

            if args.output:
                Path(args.output).write_text(source)
                print(f"Source written to {args.output}")
            else:
                print(source)

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "batch":
        result = batch_load_pyc(args.paths, parallel=args.parallel)
        print(f"Loaded {len(result.successful)} modules successfully")
        print(f"Failed: {len(result.failed)}")
        print(f"Total time: {result.total_time_ms:.1f}ms")
        print(f"Success rate: {result.success_rate:.1%}")

        for name in result.successful:
            print(f"  OK  - {name}")
        for name, error in result.failed.items():
            print(f"  FAIL - {name}: {error.message[:100]}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()