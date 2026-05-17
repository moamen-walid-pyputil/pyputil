#!/usr/bin/env python3

# -*- coding: utf-8 -*-

# =========================
# plib_inspecter
# =========================
from .plib_inspecter import (
    Plib,
    PlibError,
    ModuleNotFoundError,
    SecurityViolationError,
    IntegrityVerificationError,
    VulnerabilityDetectedError,
    find_all_modules,
    compare_modules as plib_compare_modules,
    init_stdlibs as init_plib_stdlibs
)

# =========================
# compare
# =========================
from .compare import (
    FileComparisonError,
    ComparisonMethod,
    ModuleComparator,
    compare_modules,
    quick_compare,
)

# =========================
# iotm
# =========================
from . import iotm

# =========================
# watcher
# =========================
from .watcher import (
    PackageWatcher,
    WatchEventType,
)

# =========================
# pathmodkit
# =========================
from .pathmodkit import (
    # existence
    exists,
    batch_exists,
    subexists,

    # resource handling
    get_text_data,
    read_resource,
    clear_resource_cache,
    get_resource_stream,

    # path extensions
    extend_path,
    extend_path2,
    extend_namespace_path,
    ExtensionSearchDepth,

    # metadata
    get_native_extensions,
    getmetafilepkg,
    getmetapath,
    getlocation,
    get_all_meta_paths,

    # package splitting
    split_package,
    merge_splits,
    iter_package_files,
    split_by_file_count,
    split_by_size,
    SplitStrategy,
    SplitFileFilter,

    # removal
    remove,
    remove_module,
    remove_package,
    remove_pip_packages,
    preview_removal,

    # misc
    size,
    search_metapath,
)

# =========================
# transfer_metadata
# =========================
from .transfer_metadata import (
    ModuleOperationError,
    PathSecurityError,
    ModuleNotFoundInSysPath,
    ConflictResolution,
    info,
    sync,
    copy,
    move,
    patch_copy,
    patch_move,
    verify,
)

 
# Include paths
from .include import (
    resolve_import_paths,
    temporary_syspath,
    include
)

# =========================
# Exceptions collection
# =========================
exceptions = (
    PlibError,
    ModuleNotFoundError,
    SecurityViolationError,
    IntegrityVerificationError,
    VulnerabilityDetectedError,
    FileComparisonError,
    ModuleNotFoundInSysPath,
    PathSecurityError,
    ModuleOperationError,
)

# =========================
# Public API
# =========================
__all__ = [
    # compare
    'ComparisonMethod',
    'FileComparisonError',
    'ModuleComparator',
    'compare_modules',
    'quick_compare',

    # plib (Path library) 
    'Plib',
    'PlibError',
    'plib_compare_modules',
    'find_all_modules',
    'ModuleNotFoundError',
    'SecurityViolationError',
    'IntegrityVerificationError',
    'VulnerabilityDetectedError',
    'init_plib_stdlibs',

    # metadata transfer
    'ModuleNotFoundInSysPath',
    'PathSecurityError',
    'ModuleOperationError',
    'ConflictResolution',
    'info',
    'sync',
    'copy',
    'move',
    'patch_copy',
    'patch_move',
    'verify',

    # pathmodkit
    'exists',
    'batch_exists',
    'subexists',
    'get_text_data',
    'read_resource',
    'clear_resource_cache',
    'get_resource_stream',
    'extend_path',
    'extend_path2',
    'extend_namespace_path',
    'ExtensionSearchDepth',
    'get_native_extensions',
    'getmetafilepkg',
    'getmetapath',
    'getlocation',
    'get_all_meta_paths',
    'split_package',
    'merge_splits',
    'iter_package_files',
    'split_by_file_count',
    'split_by_size',
    'SplitStrategy',
    'SplitFileFilter',
    'remove',
    'remove_module',
    'remove_package',
    'remove_pip_packages',
    'preview_removal',
    'size',
    'search_metapath',
    
    # include
    'resolve_import_paths',
    'temporary_syspath',
    'include',

    # watcher
    'PackageWatcher',
    'WatchEventType',

    # IO module
    'iotm',

    # misc
    'exceptions',
]

# =========================
# Cleanup namespace
# =========================
from ..api import clean
clean(expose=__all__)