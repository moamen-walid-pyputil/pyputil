#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Module Comparator Module
=======================

This module provides functionality to compare Python module directories with other
file system paths or archives. It supports multiple comparison methods including
hash-based, size-based, content-based, and modification time-based comparisons.
"""

import sys
import importlib
from pathlib import Path
import zipfile
import tarfile
import hashlib
import filecmp
import mmap
import os
import tempfile
import shutil
from typing import Union, List, Dict, Set, Optional, Tuple, Any, Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
import fnmatch
import logging
from functools import lru_cache
import gc
from collections import defaultdict

# Configure module logger
logger = logging.getLogger(__name__)


class FileComparisonError(Exception):
    """Exception raised for file comparison errors."""
    pass


class ComparisonMethod(Enum):
    """
    Available methods for comparing files.
    
    Attributes
    ----------
    HASH : str
        Compare using cryptographic hash (most accurate, slower)
    SIZE : str
        Compare only file sizes (fastest, least accurate)
    CONTENT : str
        Compare file contents byte by byte (accurate, moderate speed)
    MTIME : str
        Compare modification timestamps (fast, unreliable)
    """
    
    HASH = "hash"
    SIZE = "size"
    CONTENT = "content"
    MTIME = "mtime"


@dataclass
class ComparisonStats:
    """
    Statistics container for comparison results.
    
    Attributes
    ----------
    total_module_files : int
        Total number of files found in the module
    total_other_files : int
        Total number of files found in the other location
    common_files : int
        Number of files present in both locations
    different_files : int
        Number of common files that differ
    module_only : int
        Number of files only in module
    other_only : int
        Number of files only in other location
    comparison_time : float
        Time taken for comparison in seconds
    memory_used_mb : float
        Peak memory usage during comparison in MB
    cache_hits : int
        Number of cache hits during hash calculations
    cache_misses : int
        Number of cache misses during hash calculations
    """
    
    total_module_files: int = 0
    total_other_files: int = 0
    common_files: int = 0
    different_files: int = 0
    module_only: int = 0
    other_only: int = 0
    comparison_time: float = 0.0
    memory_used_mb: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0


@dataclass
class FileInfo:
    """
    Detailed information about a file.
    
    Attributes
    ----------
    path : Path
        Relative path of the file
    absolute_path : Path
        Absolute filesystem path
    size : int
        File size in bytes
    mtime : float
        Modification timestamp
    hash_value : Optional[str]
        Hash value if computed, None otherwise
    is_symlink : bool
        Whether the file is a symbolic link
    """
    
    path: str
    absolute_path: str
    size: int = -1
    mtime: float = -1.0
    hash_value: Optional[str] = None
    is_symlink: bool = False


@dataclass
class FileDifference:
    """
    Detailed difference information for a pair of files.
    
    Attributes
    ----------
    path : Path
        Relative path of the file
    module_info : FileInfo
        Information about module's file
    other_info : FileInfo
        Information about other location's file
    difference_type : str
        Type of difference ('size', 'content', 'hash', 'mtime', 'missing')
    """
    
    path: str
    module_info: Optional[FileInfo] = None
    other_info: Optional[FileInfo] = None
    difference_type: str = ""


@dataclass
class ComparisonResult:
    """
    Complete comparison results container.
    
    Attributes
    ----------
    module_name : str
        Name of the module being compared
    other_path : Path
        Path to the other location being compared
    comparison_method : ComparisonMethod
        Method used for comparison
    timestamp : float
        Timestamp when comparison was performed
    stats : ComparisonStats
        Statistical summary of the comparison
    left_only : List[FileInfo]
        Files present only in module
    right_only : List[FileInfo]
        Files present only in other location
    diff_files : List[FileDifference]
        Files that differ between locations
    common_files : List[FileInfo]
        Files that are identical in both locations
    """
    
    module_name: str
    other_path: str
    comparison_method: ComparisonMethod
    timestamp: float = field(default_factory=time.time)
    stats: ComparisonStats = field(default_factory=ComparisonStats)
    left_only: List[FileInfo] = field(default_factory=list)
    right_only: List[FileInfo] = field(default_factory=list)
    diff_files: List[FileDifference] = field(default_factory=list)
    common_files: List[FileInfo] = field(default_factory=list)
    
    def is_identical(self) -> bool:
        """
        Check if the modules are completely identical.
        
        Returns
        -------
        bool
            True if no differences found, False otherwise
        """
        return len(self.left_only) == 0 and len(self.right_only) == 0 and len(self.diff_files) == 0
    
    def get_similarity_score(self) -> float:
        """
        Calculate similarity score between the two locations.
        
        Returns
        -------
        float
            Similarity score between 0.0 (completely different) and 1.0 (identical)
        """
        total_files = self.stats.total_module_files + self.stats.total_other_files
        if total_files == 0:
            return 1.0
        
        common_count = self.stats.common_files
        return (2 * common_count) / total_files
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert result to dictionary format.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of the comparison result
        """
        return {
            "module_name": self.module_name,
            "other_path": str(self.other_path),
            "comparison_method": self.comparison_method.value,
            "timestamp": self.timestamp,
            "stats": asdict(self.stats),
            "left_only": [asdict(info) for info in self.left_only],
            "right_only": [asdict(info) for info in self.right_only],
            "diff_files": [
                {
                    "path": str(diff.path),
                    "difference_type": diff.difference_type,
                    "module_info": asdict(diff.module_info) if diff.module_info else None,
                    "other_info": asdict(diff.other_info) if diff.other_info else None,
                }
                for diff in self.diff_files
            ],
            "common_files": [asdict(info) for info in self.common_files],
        }


class ModuleComparator:
    """
    Compare a Python module's directory with another file system location or archive.
    
    This class provides comprehensive functionality to compare files from a Python
    module with files from another directory, archive file (ZIP, TAR), or another
    module. It supports multiple comparison methods, parallel processing, caching,
    and detailed reporting.
    
    Parameters
    ----------
    module_name : str
        Name of the Python module to compare (must be importable)
    other_path : Union[str, Path]
        Path to the other location for comparison (directory or archive)
    temp_dir : Optional[Path], optional
        Temporary directory for extraction, by default None (uses system temp)
    comparison_method : Union[ComparisonMethod, str], optional
        Method to use for comparing files, by default ComparisonMethod.HASH
    parallel_processing : bool, optional
        Enable parallel processing for faster comparisons, by default True
    max_workers : Optional[int], optional
        Maximum number of worker threads, by default None (auto-determined)
    hash_algorithm : str, optional
        Hash algorithm to use (from hashlib), by default "md5"
    chunk_size : int, optional
        Size of chunks for reading files in bytes, by default 8192
    include_patterns : Optional[List[str]], optional
        Glob patterns for files to include, by default ["*"]
    exclude_patterns : Optional[List[str]], optional
        Glob patterns for files to exclude, by default []
    follow_symlinks : bool, optional
        Whether to follow symbolic links, by default False
    enable_caching : bool, optional
        Enable caching of file hashes and metadata, by default True
    cache_size_limit : int, optional
        Maximum number of items in cache, by default 10000
    log_level : Optional[int], optional
        Logging level, by default None (no logging)
    
    Attributes
    ----------
    module_path : Path
        Filesystem path to the module's directory
    other_path : Path
        Resolved path to the other location
    mod_files : Dict[Path, Path]
        Mapping of relative paths to absolute paths for module files
    other_files : Dict[Path, Path]
        Mapping of relative paths to absolute paths for other location files
    result : ComparisonResult
        Complete comparison results after execution
    
    Examples
    --------
    >>> comparator = ModuleComparator("json", "/path/to/other/dir")
    >>> print(comparator.result.is_identical())
    False
    
    >>> with ModuleComparator("requests", "backup.zip", 
    ...                       comparison_method=ComparisonMethod.CONTENT) as comp:
    ...     print(f"Similarity: {comp.result.get_similarity_score():.2f}")
    ...     comp.export_report("report.json")
    """
    
    # Class-level cache for hash computations across instances
    _global_hash_cache: Dict[Path, str] = {}
    _cache_size_limit: int = 10000
    
    def __init__(
        self,
        module_name: str,
        other_path: Union[str, Path],
        temp_dir: Optional[Path] = None,
        comparison_method: Union[ComparisonMethod, str] = ComparisonMethod.HASH,
        parallel_processing: bool = True,
        max_workers: Optional[int] = None,
        hash_algorithm: str = "md5",
        chunk_size: int = 8192,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        follow_symlinks: bool = False,
        enable_caching: bool = True,
        cache_size_limit: int = 10000,
        log_level: Optional[int] = None,
    ):
        # Initialize logging
        if log_level is not None:
            logging.basicConfig(level=log_level)
        
        # Store parameters
        self.module_name = module_name
        self.other_path = Path(other_path).resolve()
        self.temp_dir = temp_dir or Path(tempfile.gettempdir()) / f"module_comp_{int(time.time())}"
        self.comparison_method = self._parse_comparison_method(comparison_method)
        self.parallel_processing = parallel_processing
        self.max_workers = max_workers or min(32, (os.cpu_count() or 1) + 4)
        self.hash_algorithm = self._validate_hash_algorithm(hash_algorithm)
        self.chunk_size = chunk_size
        self.include_patterns = include_patterns or ["*"]
        self.exclude_patterns = exclude_patterns or []
        self.follow_symlinks = follow_symlinks
        self.enable_caching = enable_caching
        self._cache_size_limit = cache_size_limit
        
        # Instance caches
        self._hash_cache: Dict[Path, str] = {}
        self._metadata_cache: Dict[Path, Dict[str, Any]] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        
        # File collections
        self.mod_files: Dict[Path, Path] = {}
        self.other_files: Dict[Path, Path] = {}
        self._extracted_path: Optional[Path] = None
        
        # Result container
        self.result: Optional[ComparisonResult] = None
        
        # Track start time for statistics
        self._start_time: Optional[float] = None
        
        # Execute comparison
        try:
            self._execute_comparison()
        except Exception as e:
            logger.error(f"Comparison failed: {e}")
            self._cleanup()
            raise FileComparisonError(f"Comparison failed: {e}") from e
    
    def _validate_hash_algorithm(self, algorithm: str) -> str:
        """
        Validate that the hash algorithm is available.
        
        Parameters
        ----------
        algorithm : str
            Name of the hash algorithm
        
        Returns
        -------
        str
            Validated algorithm name
        
        Raises
        ------
        ValueError
            If algorithm is not available
        """
        if algorithm not in hashlib.algorithms_available:
            raise ValueError(
                f"Hash algorithm '{algorithm}' not available. "
                f"Available algorithms: {hashlib.algorithms_available}"
            )
        return algorithm
    
    def _parse_comparison_method(
        self, method: Union[ComparisonMethod, str]
    ) -> ComparisonMethod:
        """
        Parse and validate the comparison method.
        
        Parameters
        ----------
        method : Union[ComparisonMethod, str]
            Comparison method to validate
        
        Returns
        -------
        ComparisonMethod
            Validated comparison method enum
        
        Raises
        ------
        ValueError
            If method is invalid
        """
        if isinstance(method, ComparisonMethod):
            return method
        
        try:
            return ComparisonMethod(method.lower())
        except (ValueError, AttributeError):
            raise ValueError(
                f"Invalid comparison method: {method}. "
                f"Available methods: {[m.value for m in ComparisonMethod]}"
            )
    
    def _execute_comparison(self) -> None:
        """Execute the complete comparison workflow."""
        self._start_time = time.time()
        
        # Step 1: Initialize module
        self.module_path = self._initialize_module()
        logger.info(f"Module path: {self.module_path}")
        
        # Step 2: Setup temporary directory
        self._setup_temp_dir()
        
        # Step 3: Extract archive if needed
        self._extract_if_archive()
        
        # Step 4: Collect files
        self.mod_files = self._collect_files(self.module_path)
        self.other_files = self._collect_files(self.other_path)
        logger.info(f"Collected {len(self.mod_files)} module files, {len(self.other_files)} other files")
        
        # Step 5: Perform comparison
        comparison_result = self._perform_comparison()
        
        # Step 6: Create result object
        self.result = self._create_result_object(comparison_result)
        
        # Step 7: Cleanup
        self._cleanup()
    
    def _initialize_module(self) -> Path:
        """
        Load and validate the Python module.
        
        Returns
        -------
        Path
            Filesystem path to the module's directory
        
        Raises
        ------
        FileComparisonError
            If module cannot be imported or located
        """
        # Import module if not already imported
        if self.module_name not in sys.modules:
            try:
                logger.debug(f"Importing module: {self.module_name}")
                importlib.import_module(self.module_name)
            except ImportError as e:
                raise FileComparisonError(
                    f"Failed to import module '{self.module_name}': {e}"
                ) from e
        
        mod = sys.modules[self.module_name]
        
        # Get module file path
        if not hasattr(mod, "__file__") or not mod.__file__:
            raise FileComparisonError(
                f"Cannot locate source for module '{self.module_name}'. "
                f"This may be a built-in module."
            ) from None
        
        module_file = Path(mod.__file__).resolve()
        
        # Handle namespace packages and __init__.py
        if module_file.name == "__init__.py":
            return module_file.parent
        else:
            return module_file.parent
    
    def _setup_temp_dir(self) -> None:
        """Create and configure the temporary directory."""
        try:
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Created temp directory: {self.temp_dir}")
        except OSError as e:
            raise FileComparisonError(f"Failed to create temp directory: {e}") from e
    
    def _extract_if_archive(self) -> None:
        """
        Extract the other path if it's an archive file.
        
        Supports .zip, .tar, .gz, .bz2, .xz, .tgz, .tbz2 formats.
        """
        if not self.other_path.is_file():
            return
        
        # Check for archive extensions
        archive_extensions = {".zip", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".tbz2"}
        
        # Also check for .tar.gz pattern
        if self.other_path.suffix.lower() in archive_extensions:
            logger.info(f"Detected archive file: {self.other_path}")
            extract_to = self.temp_dir / f"extracted_{self.other_path.stem}"
            self.other_path = self._extract_archive(self.other_path, extract_to)
            self._extracted_path = self.other_path
        elif self.other_path.suffixes and len(self.other_path.suffixes) >= 2:
            # Handle .tar.gz, .tar.bz2, etc.
            combined_suffix = "".join(self.other_path.suffixes[-2:])
            if combined_suffix in {".tar.gz", ".tar.bz2", ".tar.xz"}:
                logger.info(f"Detected archive file: {self.other_path}")
                extract_to = self.temp_dir / f"extracted_{self.other_path.stem}"
                self.other_path = self._extract_archive(self.other_path, extract_to)
                self._extracted_path = self.other_path
    
    def _extract_archive(self, archive_path: Path, extract_to: Path) -> Path:
        """
        Extract archive to temporary directory.
        
        Parameters
        ----------
        archive_path : Path
            Path to the archive file
        extract_to : Path
            Directory to extract contents to
        
        Returns
        -------
        Path
            Path to the extracted directory
        
        Raises
        ------
        FileComparisonError
            If extraction fails
        """
        # Clean up existing extraction directory
        if extract_to.exists():
            shutil.rmtree(extract_to)
        
        extract_to.mkdir(parents=True, exist_ok=True)
        
        try:
            # Handle ZIP files
            if archive_path.suffix == ".zip":
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    # Security check: prevent path traversal
                    for member in zf.namelist():
                        if ".." in Path(member).parts:
                            raise FileComparisonError(f"Path traversal detected in archive: {member}")
                    zf.extractall(extract_to)
                    logger.info(f"Extracted ZIP archive to {extract_to}")
            
            # Handle TAR files (including compressed variants)
            elif any(archive_path.suffix in ext for ext in [".tar", ".gz", ".bz2", ".xz", ".tgz", ".tbz2"]):
                mode = "r:*"  # Auto-detect compression
                with tarfile.open(archive_path, mode) as tf:
                    # Security check
                    for member in tf.getmembers():
                        if ".." in Path(member.name).parts:
                            raise FileComparisonError(f"Path traversal detected in archive: {member.name}")
                    tf.extractall(extract_to)
                    logger.info(f"Extracted TAR archive to {extract_to}")
            
            else:
                raise ValueError(f"Unsupported archive format: {archive_path.suffix}")
        
        except (zipfile.BadZipFile, tarfile.TarError) as e:
            raise FileComparisonError(f"Archive extraction failed: {e}") from e
        
        return extract_to
    
    def _should_include_file(self, file_path: Path, base_path: Path) -> bool:
        """
        Determine if a file should be included based on patterns.
        
        Parameters
        ----------
        file_path : Path
            Absolute path to the file
        base_path : Path
            Base path for relative calculation
        
        Returns
        -------
        bool
            True if file should be included, False otherwise
        """
        try:
            rel_path = str(file_path.relative_to(base_path))
        except ValueError:
            return False
        
        # Check exclude patterns first (they take precedence)
        for pattern in self.exclude_patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                return False
        
        # Check include patterns
        for pattern in self.include_patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                return True
        
        return False
    
    def _collect_files(self, base_path: Path) -> Dict[Path, Path]:
        """
        Collect all files from a directory matching the patterns.
        
        Parameters
        ----------
        base_path : Path
            Base directory to scan
        
        Returns
        -------
        Dict[Path, Path]
            Dictionary mapping relative paths to absolute paths
        
        Raises
        ------
        FileComparisonError
            If file collection fails
        """
        files = {}
        
        if not base_path.exists():
            raise FileComparisonError(f"Path does not exist: {base_path}")
        
        if not base_path.is_dir():
            raise FileComparisonError(f"Path is not a directory: {base_path}")
        
        try:
            # Walk through directory
            for root, dirs, filenames in os.walk(base_path, followlinks=self.follow_symlinks):
                root_path = Path(root)
                
                # Skip symlinks if not following
                if not self.follow_symlinks and root_path.is_symlink():
                    continue
                
                for filename in filenames:
                    file_path = root_path / filename
                    
                    # Skip symlinks if not following
                    if not self.follow_symlinks and file_path.is_symlink():
                        continue
                    
                    # Check if file should be included
                    if self._should_include_file(file_path, base_path):
                        try:
                            rel_path = file_path.relative_to(base_path)
                            files[rel_path] = file_path
                        except ValueError:
                            continue
        
        except OSError as e:
            raise FileComparisonError(f"Failed to collect files from {base_path}: {e}") from e
        
        logger.debug(f"Collected {len(files)} files from {base_path}")
        return files
    
    def _perform_comparison(self) -> Dict[str, Any]:
        """
        Perform the actual file comparison.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary containing comparison results
        
        Raises
        ------
        FileComparisonError
            If comparison fails
        """
        # Get sets of relative paths
        module_paths = set(self.mod_files.keys())
        other_paths = set(self.other_files.keys())
        
        # Categorize paths
        common_paths = module_paths & other_paths
        left_only_paths = module_paths - other_paths
        right_only_paths = other_paths - module_paths
        
        # Compare common files
        if self.parallel_processing and len(common_paths) > 100:
            diff_paths = self._compare_files_parallel(common_paths)
        else:
            diff_paths = self._compare_files_sequential(common_paths)
        
        identical_paths = common_paths - diff_paths
        
        # Build detailed results
        result = {
            "left_only": left_only_paths,
            "right_only": right_only_paths,
            "diff_files": diff_paths,
            "common_files": identical_paths,
        }
        
        return result
    
    def _compare_files_sequential(self, common_paths: Set[Path]) -> Set[Path]:
        """
        Compare files sequentially.
        
        Parameters
        ----------
        common_paths : Set[Path]
            Set of relative paths for common files
        
        Returns
        -------
        Set[Path]
            Set of paths that are different
        """
        diff_paths = set()
        
        for rel_path in common_paths:
            if not self._files_equal(
                self.mod_files[rel_path], 
                self.other_files[rel_path]
            ):
                diff_paths.add(rel_path)
        
        return diff_paths
    
    def _compare_files_parallel(self, common_paths: Set[Path]) -> Set[Path]:
        """
        Compare files in parallel using thread pool.
        
        Parameters
        ----------
        common_paths : Set[Path]
            Set of relative paths for common files
        
        Returns
        -------
        Set[Path]
            Set of paths that are different
        """
        diff_paths = set()
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_path = {
                executor.submit(
                    self._files_equal,
                    self.mod_files[rel_path],
                    self.other_files[rel_path]
                ): rel_path
                for rel_path in common_paths
            }
            
            # Process completed tasks
            for future in as_completed(future_to_path):
                rel_path = future_to_path[future]
                try:
                    if not future.result():
                        diff_paths.add(rel_path)
                except Exception as e:
                    logger.warning(f"Comparison failed for {rel_path}: {e}")
                    diff_paths.add(rel_path)  # Treat errors as differences
        
        return diff_paths
    
    def _files_equal(self, file1: Path, file2: Path) -> bool:
        """
        Check if two files are equal using the configured comparison method.
        
        Parameters
        ----------
        file1 : Path
            First file path
        file2 : Path
            Second file path
        
        Returns
        -------
        bool
            True if files are considered equal, False otherwise
        """
        try:
            if self.comparison_method == ComparisonMethod.HASH:
                return self._get_file_hash(file1) == self._get_file_hash(file2)
            
            elif self.comparison_method == ComparisonMethod.SIZE:
                return self._get_file_size(file1) == self._get_file_size(file2)
            
            elif self.comparison_method == ComparisonMethod.CONTENT:
                return self._compare_files_content(file1, file2)
            
            elif self.comparison_method == ComparisonMethod.MTIME:
                return self._get_file_mtime(file1) == self._get_file_mtime(file2)
            
            else:
                raise ValueError(f"Unknown comparison method: {self.comparison_method}")
        
        except (OSError, IOError) as e:
            logger.debug(f"Error comparing {file1} and {file2}: {e}")
            return False
    
    def _get_file_hash(self, file_path: Path) -> str:
        """
        Calculate or retrieve cached hash of a file.
        
        Parameters
        ----------
        file_path : Path
            Path to the file
        
        Returns
        -------
        str
            Hexadecimal hash string, empty string on error
        """
        # Check instance cache
        if self.enable_caching and file_path in self._hash_cache:
            self._cache_hits += 1
            return self._hash_cache[file_path]
        
        # Check global cache
        if self.enable_caching and file_path in self._global_hash_cache:
            self._cache_hits += 1
            self._hash_cache[file_path] = self._global_hash_cache[file_path]
            return self._global_hash_cache[file_path]
        
        self._cache_misses += 1
        
        try:
            hasher = hashlib.new(self.hash_algorithm)
            
            with file_path.open("rb") as f:
                # Read file in chunks to handle large files
                for chunk in iter(lambda: f.read(self.chunk_size), b""):
                    hasher.update(chunk)
            
            hash_value = hasher.hexdigest()
            
            # Cache the result
            if self.enable_caching:
                self._hash_cache[file_path] = hash_value
                self._global_hash_cache[file_path] = hash_value
                
                # Manage cache size
                if len(self._global_hash_cache) > self._cache_size_limit:
                    # Remove oldest 20% of entries
                    items_to_remove = int(self._cache_size_limit * 0.2)
                    for _ in range(items_to_remove):
                        if self._global_hash_cache:
                            self._global_hash_cache.popitem(last=False)
            
            return hash_value
        
        except (IOError, OSError) as e:
            logger.debug(f"Failed to hash {file_path}: {e}")
            return ""
    
    def _get_file_size(self, file_path: Path) -> int:
        """
        Get file size.
        
        Parameters
        ----------
        file_path : Path
            Path to the file
        
        Returns
        -------
        int
            File size in bytes, -1 on error
        """
        try:
            return file_path.stat().st_size
        except (OSError, IOError):
            return -1
    
    def _get_file_mtime(self, file_path: Path) -> float:
        """
        Get file modification time.
        
        Parameters
        ----------
        file_path : Path
            Path to the file
        
        Returns
        -------
        float
            Modification timestamp, -1 on error
        """
        try:
            return file_path.stat().st_mtime
        except (OSError, IOError):
            return -1
    
    def _compare_files_content(self, file1: Path, file2: Path) -> bool:
        """
        Compare file contents byte by byte.
        
        Parameters
        ----------
        file1 : Path
            First file path
        file2 : Path
            Second file path
        
        Returns
        -------
        bool
            True if contents are identical, False otherwise
        """
        try:
            # Quick size check
            if self._get_file_size(file1) != self._get_file_size(file2):
                return False
            
            # Use filecmp for efficient comparison
            return filecmp.cmp(file1, file2, shallow=False)
        
        except (OSError, IOError) as e:
            logger.debug(f"Content comparison failed: {e}")
            return False
    
    def _get_file_info(self, rel_path: Path, abs_path: Path) -> FileInfo:
        """
        Create FileInfo object for a file.
        
        Parameters
        ----------
        rel_path : Path
            Relative path of the file
        abs_path : Path
            Absolute path of the file
        
        Returns
        -------
        FileInfo
            File information object
        """
        return FileInfo(
            path=str(rel_path),
            absolute_path=str(abs_path),
            size=self._get_file_size(abs_path),
            mtime=self._get_file_mtime(abs_path),
            hash_value=self._get_file_hash(abs_path) if self.comparison_method == ComparisonMethod.HASH else None,
            is_symlink=abs_path.is_symlink(),
        )
    
    def _create_result_object(self, comparison: Dict[str, Any]) -> ComparisonResult:
        """
        Create the final ComparisonResult object.
        
        Parameters
        ----------
        comparison : Dict[str, Any]
            Raw comparison results
        
        Returns
        -------
        ComparisonResult
            Structured comparison result object
        """
        # Build FileInfo objects
        left_only = [
            self._get_file_info(rel_path, self.mod_files[rel_path])
            for rel_path in sorted(comparison["left_only"])
        ]
        
        right_only = [
            self._get_file_info(rel_path, self.other_files[rel_path])
            for rel_path in sorted(comparison["right_only"])
        ]
        
        common_files = [
            self._get_file_info(rel_path, self.mod_files[rel_path])
            for rel_path in sorted(comparison["common_files"])
        ]
        
        # Build FileDifference objects for differing files
        diff_files = []
        for rel_path in sorted(comparison["diff_files"]):
            mod_file = self.mod_files[rel_path]
            other_file = self.other_files[rel_path]
            
            # Determine difference type
            if self._get_file_size(mod_file) != self._get_file_size(other_file):
                diff_type = "size"
            else:
                diff_type = "content"
            
            diff_files.append(FileDifference(
                path=str(rel_path),
                module_info=self._get_file_info(rel_path, mod_file),
                other_info=self._get_file_info(rel_path, other_file),
                difference_type=diff_type,
            ))
        
        # Calculate statistics
        stats = ComparisonStats(
            total_module_files=len(self.mod_files),
            total_other_files=len(self.other_files),
            common_files=len(common_files),
            different_files=len(diff_files),
            module_only=len(left_only),
            other_only=len(right_only),
            comparison_time=time.time() - (self._start_time or time.time()),
            memory_used_mb=self._get_memory_usage(),
            cache_hits=self._cache_hits,
            cache_misses=self._cache_misses,
        )
        
        return ComparisonResult(
            module_name=self.module_name,
            other_path=str(self.other_path),
            comparison_method=self.comparison_method,
            timestamp=self._start_time or time.time(),
            stats=stats,
            left_only=left_only,
            right_only=right_only,
            diff_files=diff_files,
            common_files=common_files,
        )
    
    def _get_memory_usage(self) -> float:
        """
        Get current memory usage of the process.
        
        Returns
        -------
        float
            Memory usage in megabytes, 0 if psutil not available
        """
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            return 0.0
    
    def _cleanup(self) -> None:
        """Clean up temporary resources."""
        try:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                logger.debug(f"Cleaned up temp directory: {self.temp_dir}")
        except OSError as e:
            logger.warning(f"Failed to clean up temp directory: {e}")
    
    def export_report(self, output_path: Union[str, Path],) -> None:
        """
        Export comparison report to a file.
        
        Parameters
        ----------
        output_path : Union[str, Path]
            Path where to save the report
        
        Raises
        ------
        ValueError
            If format is unsupported
        IOError
            If file writing fails
        """
        if self.result is None:
            raise FileComparisonError("No comparison result available")
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        report_data = self.result.to_dict()
            
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
            
        logger.info(f"Report exported to {output_path}")
    
    def __enter__(self) -> 'ModuleComparator':
        """Enter context manager."""
        return self
    
    def __exit__(self, exc_type: Optional[type], exc_val: Optional[Exception], exc_tb: Optional[Any]) -> None:
        """Exit context manager and clean up."""
        self._cleanup()
    
    def __repr__(self) -> str:
        """String representation of the comparator."""
        if self.result is None:
            return f"ModuleComparator(module='{self.module_name}', other='{self.other_path}', status='not executed')"
        
        return (
            f"ModuleComparator(module='{self.module_name}', "
            f"other='{self.other_path}', "
            f"status={'identical' if self.result.is_identical() else 'different'}, "
            f"similarity={self.result.get_similarity_score():.2%})"
        )


# Convenience functions
def compare_modules(
    module_name: str,
    other_path: Union[str, Path],
    **kwargs
) -> ComparisonResult:
    """
    Convenience function for quick module comparison.
    
    Parameters
    ----------
    module_name : str
        Name of the Python module to compare
    other_path : Union[str, Path]
        Path to compare against
    **kwargs
        Additional arguments passed to ModuleComparator
    
    Returns
    -------
    ComparisonResult
        Complete comparison results
    
    Examples
    --------
    >>> result = compare_modules("json", "/backup/json_backup")
    >>> print(result.is_identical())
    >>> print(result.get_similarity_score())
    """
    with ModuleComparator(module_name, other_path, **kwargs) as comparator:
        return comparator.result


def quick_compare(
    module_name: str,
    other_path: Union[str, Path],
    method: Union[ComparisonMethod, str] = ComparisonMethod.SIZE
) -> bool:
    """
    Quick comparison using specified method.
    
    Parameters
    ----------
    module_name : str
        Name of the Python module to compare
    other_path : Union[str, Path]
        Path to compare against
    method : Union[ComparisonMethod, str], optional
        Comparison method to use, by default ComparisonMethod.SIZE
    
    Returns
    -------
    bool
        True if modules appear identical using the specified method
    """
    with ModuleComparator(module_name, other_path, comparison_method=method) as comparator:
        return comparator.result.is_identical()


