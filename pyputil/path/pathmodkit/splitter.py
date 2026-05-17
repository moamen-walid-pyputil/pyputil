#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import shutil
from pathlib import Path
import importlib.util
from typing import Optional, Union, Iterable, Tuple, Dict, List, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import json
import hashlib
import logging
from dataclasses import dataclass, asdict
from enum import Enum
import time
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class SplitStrategy(Enum):
    """Enumeration of available splitting strategies."""
    SIZE = "size"      # Split by total file size
    COUNT = "count"    # Split by number of files
    SMART = "smart"    # Intelligent splitting based on file types and sizes
    CUSTOM = "custom"  # Custom splitting function


class SplitFileFilter(Enum):
    """Enumeration of file filtering options."""
    ALL = "all"
    PYTHON_ONLY = "python_only"
    NO_CACHE = "no_cache"  # Exclude __pycache__, .pyc files
    SOURCE_ONLY = "source_only"  # Only .py, .pyx, .pxd files


@dataclass
class SplitMetadata:
    """Metadata for a split operation."""
    package_name: str
    split_strategy: str
    limit_value: int
    total_files: int
    total_size: int
    splits_created: int
    split_details: List[Dict]
    duration_seconds: float
    timestamp: float
    flatten_structure: bool
    file_filter: str
    workers_used: int
    
    def save(self, filepath: Union[str, Path]) -> None:
        """
        Save metadata to JSON file.
        
        Parameters
        ----------
        filepath : str or Path
            Path where metadata JSON file will be saved.
        """
        with open(Path(filepath), 'w') as f:
            json.dump(asdict(self), f, indent=2)
    
    @classmethod
    def load(cls, filepath: Union[str, Path]) -> 'SplitMetadata':
        """
        Load metadata from JSON file.
        
        Parameters
        ----------
        filepath : str or Path
            Path to metadata JSON file.
        
        Returns
        -------
        SplitMetadata
            Loaded metadata object.
        """
        with open(Path(filepath), 'r') as f:
            data = json.load(f)
        return cls(**data)


@dataclass
class SplitResult:
    """Result of a split operation for a single file."""
    source: Path
    destination: Path
    size: int
    success: bool
    error: Optional[str] = None
    duration_ms: float = 0.0


def get_source_package(package: str, version_spec: Optional[str] = None) -> Optional[Path]:
    """
    Resolve the directory path of an installed Python package with optional version.
    
    Parameters
    ----------
    package : str
        Installed package name.
    version_spec : str, optional
        Specific version requirement (e.g., ">=1.0.0", "==2.0.0").
    
    Returns
    -------
    Path or None
        Package directory path if found.
    
    Examples
    --------
    >>> get_source_package("requests")
    PosixPath('/usr/lib/python3.9/site-packages/requests')
    >>> get_source_package("pandas", ">=1.3.0")
    PosixPath('/usr/lib/python3.9/site-packages/pandas')
    """
    spec = importlib.util.find_spec(package)
    
    if not (spec and spec.origin):
        logger.warning(f"Package '{package}' not found")
        return None
    
    # Check version if specified
    if version_spec:
        try:
            import pkg_resources
            installed_version = pkg_resources.get_distribution(package).version
            if not pkg_resources.evaluate_marker(f"{package}{version_spec}", 
                                                 {'extra': '', **pkg_resources.environment}):
                logger.warning(f"Version {installed_version} of '{package}' does not satisfy {version_spec}")
                return None
        except Exception as e:
            logger.debug(f"Version check failed: {e}")
    
    path = Path(spec.origin)
    
    if path.is_file() and path.name != "__init__.py":
        # Namespace package or single module
        return path.parent if path.name.endswith('.py') else None
    
    return path.parent if path.is_file() else path


def iter_package_files(
    source: Union[str, Path],
    file_filter: SplitFileFilter = SplitFileFilter.ALL,
    exclude_patterns: Optional[List[str]] = None,
    include_patterns: Optional[List[str]] = None
) -> Iterable[Tuple[str, str, int]]:
    """
    Lazily iterate through package files with filtering.
    
    Parameters
    ----------
    source : str or Path
        Package name (installed package) or path to package directory.
    file_filter : SplitFileFilter
        Filter to apply to files.
    exclude_patterns : list of str, optional
        Glob patterns to exclude.
    include_patterns : list of str, optional
        Glob patterns to include (overrides exclude).
    
    Yields
    ------
    tuple
        (relative_path, absolute_path, size)
    
    Examples
    --------
    >>> # Using package name
    >>> for rel_path, abs_path, size in iter_package_files("requests"):
    ...     print(rel_path)
    
    >>> # Using direct path
    >>> for rel_path, abs_path, size in iter_package_files("/path/to/package"):
    ...     print(rel_path)
    """
    # Convert package name to path if needed
    if isinstance(source, str) and not Path(source).exists():
        source_path = get_source_package(source)
        if not source_path:
            raise ValueError(f"Package '{source}' not found")
    else:
        source_path = Path(source)
    
    if not source_path.exists():
        raise ValueError(f"Source path '{source_path}' does not exist")
    
    exclude_patterns = exclude_patterns or []
    include_patterns = include_patterns or []
    
    for file in source_path.rglob("*"):
        if not file.is_file():
            continue
        
        rel_path = file.relative_to(source_path)
        
        # Apply filters
        if file_filter == SplitFileFilter.PYTHON_ONLY:
            if not file.suffix in ('.py', '.pyx', '.pxd', '.so', '.pyd'):
                continue
        elif file_filter == SplitFileFilter.NO_CACHE:
            if '__pycache__' in str(rel_path) or file.suffix == '.pyc':
                continue
        elif file_filter == SplitFileFilter.SOURCE_ONLY:
            if not file.suffix in ('.py', '.pyx', '.pxd'):
                continue
        
        # Apply exclude patterns
        excluded = False
        for pattern in exclude_patterns:
            if rel_path.match(pattern):
                excluded = True
                break
        if excluded:
            continue
        
        # Apply include patterns (if any)
        if include_patterns:
            included = False
            for pattern in include_patterns:
                if rel_path.match(pattern):
                    included = True
                    break
            if not included:
                continue
        
        yield str(rel_path), str(file), file.stat().st_size


def _copy_with_verification(src: Path, dest: Path, verify: bool = True) -> Tuple[bool, Optional[str]]:
    """
    Copy file with optional integrity verification.
    
    Parameters
    ----------
    src : Path
        Source file path.
    dest : Path
        Destination file path.
    verify : bool, default=True
        Whether to verify the copy integrity.
    
    Returns
    -------
    tuple
        (success, error_message)
    """
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        
        if verify:
            # Verify file was copied correctly
            if not dest.exists():
                return False, "Destination file not created"
            if dest.stat().st_size != src.stat().st_size:
                return False, "Size mismatch after copy"
            
            # Optional: verify content hash for critical files
            if src.stat().st_size < 10 * 1024 * 1024:  # Only for files < 10MB
                with open(src, 'rb') as f_src, open(dest, 'rb') as f_dest:
                    if f_src.read() != f_dest.read():
                        return False, "Content mismatch after copy"
        
        return True, None
    except Exception as e:
        return False, str(e)


def analyze_package(source: Union[str, Path]) -> Dict:
    """
    Analyze package structure and provide statistics for optimal splitting.
    
    Parameters
    ----------
    source : str or Path
        Package name (installed package) or path to package directory.
    
    Returns
    -------
    dict
        Analysis results including file distribution, sizes, and recommendations.
    
    Examples
    --------
    >>> # Analyze installed package
    >>> analysis = analyze_package("numpy")
    >>> print(f"Total files: {analysis['total_files']}")
    
    >>> # Analyze local package directory
    >>> analysis = analyze_package("./my_package")
    >>> print(f"Total size: {analysis['total_size_mb']:.2f} MB")
    """
    # Convert package name to path if needed
    if isinstance(source, str) and not Path(source).exists():
        source_path = get_source_package(source)
        if not source_path:
            return {"error": f"Package '{source}' not found"}
    else:
        source_path = Path(source)
    
    if not source_path.exists():
        return {"error": f"Source path '{source_path}' does not exist"}
    
    files = []
    total_size = 0
    extensions = defaultdict(int)
    sizes_by_extension = defaultdict(int)
    
    for rel_path, abs_path, size in iter_package_files(source_path):
        abs_path = Path(abs_path)
        files.append({
            "path": str(rel_path),
            "size": size,
            "ext": abs_path.suffix or ""
        })
        total_size += size
        extensions[abs_path.suffix or "no_ext"] += 1
        sizes_by_extension[abs_path.suffix or "no_ext"] += size
    
    # Calculate percentiles
    sizes = [f["size"] for f in files]
    sizes.sort()
    
    percentiles = {
        "50th": sizes[len(sizes)//2] if sizes else 0,
        "90th": sizes[int(len(sizes)*0.9)] if sizes else 0,
        "95th": sizes[int(len(sizes)*0.95)] if sizes else 0,
        "99th": sizes[int(len(sizes)*0.99)] if sizes else 0,
    }
    
    # Generate recommendations
    avg_size = total_size / max(len(files), 1)
    recommendations = {
        "optimal_split_mode": "size" if max(sizes) > avg_size * 10 else "count",
        "suggested_limit": max(int(avg_size * 100), 1024*1024) if len(files) > 100 else int(total_size / 10),
        "notes": []
    }
    
    if len([s for s in sizes if s > 10*1024*1024]) > 0:  # Files > 10MB
        recommendations["notes"].append("Large files detected (>10MB), consider size-based splitting")
    if len(files) > 1000:
        recommendations["notes"].append("Many small files, count-based splitting may be more appropriate")
    
    return {
        "total_files": len(files),
        "total_size_bytes": total_size,
        "total_size_mb": total_size / (1024*1024),
        "avg_file_size_bytes": avg_size,
        "max_file_size_bytes": max(sizes) if sizes else 0,
        "min_file_size_bytes": min(sizes) if sizes else 0,
        "size_percentiles": percentiles,
        "extensions": dict(extensions),
        "sizes_by_extension_mb": {k: v/(1024*1024) for k, v in sizes_by_extension.items()},
        "recommendations": recommendations
    }


def smart_splitting_decision(analysis: Dict, target_split_count: Optional[int] = None) -> Tuple[str, int]:
    """
    Make intelligent splitting decisions based on package analysis.
    
    Parameters
    ----------
    analysis : dict
        Output from analyze_package().
    target_split_count : int, optional
        Desired number of splits.
    
    Returns
    -------
    tuple
        (split_mode, limit_value)
    
    Examples
    --------
    >>> analysis = analyze_package("requests")
    >>> mode, limit = smart_splitting_decision(analysis, target_split_count=5)
    >>> print(f"Use {mode}-based splitting with limit {limit}")
    """
    if "error" in analysis:
        return ("size", 100 * 1024 * 1024)  # Default 100MB
    
    total_files = analysis["total_files"]
    total_size = analysis["total_size_bytes"]
    
    if target_split_count:
        # Target specific number of splits
        if analysis["recommendations"]["optimal_split_mode"] == "size":
            limit = total_size // target_split_count
        else:
            limit = total_files // target_split_count
        return (analysis["recommendations"]["optimal_split_mode"], max(limit, 1))
    
    # Auto-decide based on package characteristics
    if total_files < 50:
        # Small package, no splitting needed
        return ("size", total_size + 1)
    elif analysis["max_file_size_bytes"] > total_size * 0.3:
        # One very large file dominates
        return ("size", int(analysis["max_file_size_bytes"] * 1.1))
    elif analysis["avg_file_size_bytes"] < 10000 and total_files > 500:
        # Many small files
        return ("count", max(100, total_files // 10))
    else:
        # Default to size-based with 100MB chunks
        return ("size", 100 * 1024 * 1024)


def split_package(
    source: Union[str, Path],
    output_base: Union[str, Path],
    split_mode: Union[str, SplitStrategy] = "smart",
    limit: Optional[int] = None,
    flatten: bool = False,
    workers: Optional[int] = None,
    file_filter: SplitFileFilter = SplitFileFilter.ALL,
    exclude_patterns: Optional[List[str]] = None,
    include_patterns: Optional[List[str]] = None,
    verify_copies: bool = True,
    create_metadata: bool = True,
    dry_run: bool = False,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    version_spec: Optional[str] = None,
    target_splits: Optional[int] = None,
    custom_split_func: Optional[Callable[[List[Tuple[Path, Path, int]], int], List[List]]] = None,
) -> SplitMetadata:
    """
    Split a Python package into smaller directories with advanced options.
    
    Parameters
    ----------
    source : str or Path
        Package name (installed package) or path to package directory.
    output_base : str or Path
        Directory where split folders will be created.
    split_mode : {'size', 'count', 'smart', 'custom'} or SplitStrategy
        Splitting strategy.
    limit : int, optional
        Maximum bytes (size mode) or files (count mode) per split.
        Required for 'size'/'count', ignored for 'smart'/'custom'.
    flatten : bool, default=False
        If True, directory structure is removed.
    workers : int, optional
        Number of parallel copy threads.
    file_filter : SplitFileFilter, default=SplitFileFilter.ALL
        Filter for files to include.
    exclude_patterns : list of str, optional
        Glob patterns to exclude (e.g., ["*.pyc", "tests/*"]).
    include_patterns : list of str, optional
        Glob patterns to include (overrides exclude).
    verify_copies : bool, default=True
        Verify file integrity after copy.
    create_metadata : bool, default=True
        Save split metadata to JSON file.
    dry_run : bool, default=False
        Simulate split without copying files.
    progress_callback : callable, optional
        Function called with (completed, total) for progress updates.
    version_spec : str, optional
        Version requirement for package (only applicable when source is package name).
    target_splits : int, optional
        Desired number of splits (for smart mode).
    custom_split_func : callable, optional
        Custom function to determine split boundaries.
        Signature: func(files, limit) -> List[List[file_tuples]]
    
    Returns
    -------
    SplitMetadata
        Metadata about the split operation.
    
    Examples
    --------
    >>> # Split installed package with smart mode
    >>> result = split_package("numpy", "./splits", split_mode="smart")
    
    >>> # Split local package directory
    >>> result = split_package("./my_package", "./splits", split_mode="size", limit=50*1024*1024)
    
    >>> # Split Python files only, exclude tests, target 5 splits
    >>> result = split_package("pandas", "./splits", split_mode="smart", 
    ...                        file_filter=SplitFileFilter.PYTHON_ONLY,
    ...                        exclude_patterns=["*/tests/*"], target_splits=5)
    
    >>> # Custom splitting function
    >>> def split_by_directory(files, _):
    ...     splits = defaultdict(list)
    ...     for rel_path, abs_path, size in files:
    ...         top_dir = rel_path.parts[0] if rel_path.parts else "root"
    ...         splits[top_dir].append((rel_path, abs_path, size))
    ...     return list(splits.values())
    >>> result = split_package("requests", "./splits", split_mode="custom",
    ...                        custom_split_func=split_by_directory)
    """
    
    start_time = time.time()
    
    # Handle enum split_mode
    if isinstance(split_mode, SplitStrategy):
        split_mode = split_mode.value
    
    # Validate parameters
    if split_mode not in [s.value for s in SplitStrategy]:
        raise ValueError(f"split_mode must be one of {[s.value for s in SplitStrategy]}")
    
    # Get source path (convert package name to path if needed)
    if isinstance(source, str) and not Path(source).exists():
        source_path = get_source_package(source, version_spec)
        if not source_path:
            raise ValueError(f"Package '{source}' not found" + 
                           (f" with version spec '{version_spec}'" if version_spec else ""))
        package_name = source
    else:
        source_path = Path(source)
        if not source_path.exists():
            raise ValueError(f"Source path '{source_path}' does not exist")
        package_name = source_path.name
    
    logger.info(f"Splitting from '{source_path}'")
    
    # Analyze package for smart decisions
    if split_mode == "smart":
        analysis = analyze_package(source_path)
        if "error" in analysis:
            raise ValueError(f"Analysis failed: {analysis['error']}")
        split_mode, auto_limit = smart_splitting_decision(analysis, target_splits)
        if limit is None:
            limit = auto_limit
        logger.info(f"Smart decision: using {split_mode}-based splitting with limit={limit}")
    
    # Validate limit
    if split_mode in ("size", "count"):
        if limit is None:
            raise ValueError(f"limit required for {split_mode} mode")
        if limit <= 0:
            raise ValueError("limit must be positive")
    
    # Setup output
    out_base = Path(output_base)
    if not dry_run:
        out_base.mkdir(parents=True, exist_ok=True)
    
    # Collect all files
    all_files = list(iter_package_files(
        source_path, file_filter, exclude_patterns, include_patterns
    ))
    
    if not all_files:
        raise ValueError(f"No files found in source '{source}' after filtering")
    
    total_files = len(all_files)
    total_size = sum(size for _, _, size in all_files)
    
    logger.info(f"Found {total_files} files, total size: {total_size/(1024*1024):.2f} MB")
    
    # Determine splits based on mode
    splits = []
    
    if split_mode == "custom" and custom_split_func:
        splits = custom_split_func(all_files, limit)
    elif split_mode == "size":
        current_split = []
        current_size = 0
        for file_tuple in all_files:
            _, _, size = file_tuple
            if current_size + size > limit and current_split:
                splits.append(current_split)
                current_split = []
                current_size = 0
            current_split.append(file_tuple)
            current_size += size
        if current_split:
            splits.append(current_split)
    elif split_mode == "count":
        for i in range(0, len(all_files), limit):
            splits.append(all_files[i:i+limit])
    else:
        raise ValueError(f"Unknown split mode: {split_mode}")
    
    logger.info(f"Created {len(splits)} splits")
    
    # Prepare split details
    split_details = []
    
    if dry_run:
        for idx, split_files in enumerate(splits):
            split_size = sum(size for _, _, size in split_files)
            split_details.append({
                "index": idx,
                "file_count": len(split_files),
                "total_size_bytes": split_size,
                "total_size_mb": split_size / (1024*1024)
            })
        logger.info("Dry run completed - no files were copied")
    else:
        # Copy files with parallel execution
        workers = workers or min(32, (os.cpu_count() or 1) + 4)
        logger.info(f"Using {workers} worker threads")
        
        completed = 0
        results = []
        
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            
            for split_idx, split_files in enumerate(splits):
                split_dir = out_base / f"{package_name}_{split_idx}"
                if not dry_run:
                    split_dir.mkdir(exist_ok=True)
                
                for rel_path, abs_path, size in split_files:
                    dest = split_dir / rel_path.name if flatten else split_dir / rel_path
                    future = executor.submit(_copy_with_verification, abs_path, dest, verify_copies)
                    futures.append((future, abs_path, dest, size, split_idx))
            
            # Collect results with progress tracking
            for future, src, dest, size, split_idx in futures:
                try:
                    copy_start = time.time()
                    success, error = future.result(timeout=30)
                    duration_ms = (time.time() - copy_start) * 1000
                    
                    results.append(SplitResult(
                        source=src,
                        destination=dest,
                        size=size,
                        success=success,
                        error=error,
                        duration_ms=duration_ms
                    ))
                    
                    if not success:
                        logger.error(f"Failed to copy {src} to {dest}: {error}")
                    
                except Exception as e:
                    results.append(SplitResult(
                        source=src,
                        destination=dest,
                        size=size,
                        success=False,
                        error=str(e)
                    ))
                    logger.error(f"Exception copying {src}: {e}")
                
                completed += 1
                if progress_callback:
                    progress_callback(completed, total_files)
                
                if completed % 100 == 0:
                    logger.info(f"Progress: {completed}/{total_files} files copied")
        
        # Calculate split statistics
        split_stats = defaultdict(lambda: {"files": 0, "size": 0, "successful": 0, "failed": 0})
        for result in results:
            # Determine split index from destination path
            try:
                if flatten:
                    split_idx = int(result.destination.parent.name.split('_')[-1])
                else:
                    split_idx = int(result.destination.parents[1].name.split('_')[-1])
                split_stats[split_idx]["files"] += 1
                split_stats[split_idx]["size"] += result.size
                if result.success:
                    split_stats[split_idx]["successful"] += 1
                else:
                    split_stats[split_idx]["failed"] += 1
            except (IndexError, ValueError) as e:
                logger.warning(f"Could not determine split index for {result.destination}: {e}")
        
        for idx in range(len(splits)):
            stats = split_stats.get(idx, {"files": 0, "size": 0, "successful": 0, "failed": 0})
            split_details.append({
                "index": idx,
                "file_count": stats["files"],
                "successful_copies": stats["successful"],
                "failed_copies": stats["failed"],
                "total_size_bytes": stats["size"],
                "total_size_mb": stats["size"] / (1024*1024),
                "path": str(out_base / f"{package_name}_{idx}")
            })
        
        failed_count = sum(1 for r in results if not r.success)
        if failed_count > 0:
            logger.warning(f"{failed_count} files failed to copy")
    
    # Create metadata
    duration = time.time() - start_time
    metadata = SplitMetadata(
        package_name=package_name,
        split_strategy=split_mode,
        limit_value=limit or 0,
        total_files=total_files,
        total_size=total_size,
        splits_created=len(splits),
        split_details=split_details,
        duration_seconds=duration,
        timestamp=time.time(),
        flatten_structure=flatten,
        file_filter=file_filter.value,
        workers_used=workers or 0
    )
    
    if create_metadata and not dry_run:
        metadata_file = out_base / f"{package_name}_split_metadata.json"
        metadata.save(metadata_file)
        logger.info(f"Metadata saved to {metadata_file}")
    
    logger.info(f"Split completed in {duration:.2f} seconds, created {len(splits)} splits")
    
    return metadata


# Convenience functions for common use cases
def split_by_size(
    source: Union[str, Path], 
    output_base: Union[str, Path], 
    max_size_mb: int, 
    **kwargs
) -> SplitMetadata:
    """
    Split package into chunks of max_size_mb megabytes.
    
    Parameters
    ----------
    source : str or Path
        Package name or path to package directory.
    output_base : str or Path
        Directory where split folders will be created.
    max_size_mb : int
        Maximum size in megabytes per split.
    **kwargs : dict
        Additional arguments passed to split_package().
    
    Returns
    -------
    SplitMetadata
        Metadata about the split operation.
    
    Examples
    --------
    >>> # Split into 50MB chunks
    >>> result = split_by_size("numpy", "./splits", 50)
    """
    return split_package(source, output_base, split_mode="size", 
                        limit=max_size_mb * 1024 * 1024, **kwargs)


def split_by_file_count(
    source: Union[str, Path], 
    output_base: Union[str, Path], 
    files_per_split: int, 
    **kwargs
) -> SplitMetadata:
    """
    Split package into chunks with files_per_split files each.
    
    Parameters
    ----------
    source : str or Path
        Package name or path to package directory.
    output_base : str or Path
        Directory where split folders will be created.
    files_per_split : int
        Maximum number of files per split.
    **kwargs : dict
        Additional arguments passed to split_package().
    
    Returns
    -------
    SplitMetadata
        Metadata about the split operation.
    
    Examples
    --------
    >>> # Split into chunks of 100 files each
    >>> result = split_by_file_count("requests", "./splits", 100)
    """
    return split_package(source, output_base, split_mode="count", 
                        limit=files_per_split, **kwargs)


def merge_splits(
    split_dirs: List[Union[str, Path]], 
    output_dir: Union[str, Path], 
    overwrite: bool = False
) -> bool:
    """
    Merge previously split package directories back together.
    
    Parameters
    ----------
    split_dirs : list of str or Path
        Directories containing split packages.
    output_dir : str or Path
        Directory where merged package will be created.
    overwrite : bool, default=False
        Overwrite existing files.
    
    Returns
    -------
    bool
        True if merge was successful.
    
    Examples
    --------
    >>> # Merge splits back together
    >>> success = merge_splits(["./splits/numpy_0", "./splits/numpy_1"], "./merged_numpy")
    >>> if success:
    ...     print("Merge completed successfully")
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    for split_dir in split_dirs:
        split_path = Path(split_dir)
        if not split_path.exists():
            logger.error(f"Split directory not found: {split_path}")
            return False
        
        for file in split_path.rglob("*"):
            if file.is_file():
                rel_path = file.relative_to(split_path)
                dest = output_path / rel_path
                
                if dest.exists() and not overwrite:
                    logger.warning(f"Skipping existing file: {dest}")
                    continue
                
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, dest)
                logger.debug(f"Merged: {file} -> {dest}")
    
    logger.info(f"Merge completed to {output_path}")
    return True

