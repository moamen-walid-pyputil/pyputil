#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Data classes for module maker.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class ProfileModule:
    """
    Profiling data for module performance analysis.

    Attributes
    ----------
    load_time_avg : float
        Average module loading time in seconds
    load_time_min : float
        Minimum module loading time in seconds
    load_time_max : float
        Maximum module loading time in seconds
    peak_memory_avg : float
        Average peak memory usage in bytes
    peak_memory_max : int
        Maximum peak memory usage in bytes
    size_object_avg : int
        Average object size in bytes
    functions : int
        Number of functions in the module
    iterations : int
        Number of profiling iterations performed
    """

    load_time_avg: float
    load_time_min: float
    load_time_max: float
    peak_memory_avg: float
    peak_memory_max: int
    size_object_avg: int
    functions: int
    iterations: int


@dataclass
class ModuleStats:
    """
    Statistical information about a module.

    Attributes
    ----------
    name : str
        Name of the module
    path : str
        Full path to the module
    files : int
        Number of files in the module
    dirs : int
        Number of directories in the module
    size : int
        Total size of module in bytes
    """

    name: str
    path: str
    files: int
    dirs: int
    size: int


@dataclass(frozen=True)
class ModuleMetadata:
    """
    Immutable metadata for a module.

    Attributes
    ----------
    name : str
        Name of the module
    path : Path
        Path object pointing to the module
    created_at : datetime
        Creation timestamp
    modified_at : datetime
        Last modification timestamp
    size_bytes : int
        Total size in bytes
    file_count : int
        Number of files
    dir_count : int
        Number of directories
    hash_digest : str
        Cryptographic hash of module contents
    """

    name: str
    path: Path
    created_at: datetime
    modified_at: datetime
    size_bytes: int
    file_count: int
    dir_count: int
    hash_digest: str
