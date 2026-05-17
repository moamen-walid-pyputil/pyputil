#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    UTILITY MODULES
==================================

Cross-platform utility functions and helpers for the CImporter system.
Provides platform detection, checksums, path handling, and system operations.

This module exports:
- Platform utilities: Platform detection, architecture info
- Checksum utilities: File hashing, integrity verification

Examples
--------
>>> from pyputil.cutil.cimporter.utils import (
...     get_platform_info,
...     compute_checksum,
...     normalize_path,
...     find_executable,
... )
>>> 
>>> info = get_platform_info()
>>> print(f"Running on {info['system']} {info['machine']}")
>>> 
>>> checksum = compute_checksum(Path("source.c"))
>>> print(f"SHA256: {checksum}")
>>> 
"""

from .platform_ import (
    # Enums
    PlatformType,
    ArchitectureType,
    PythonImplementation,
    
    # Data classes
    PlatformInfo,
    
    # Cache management
    clear_platform_cache,
    
    # Platform detection
    get_platform,
    get_platform_info,
    get_architecture,
    get_system,
    get_machine,
    get_processor,
    
    # Python info
    get_python_version,
    get_python_version_tuple,
    get_python_implementation,
    get_python_abi,
    
    # Extensions
    get_shared_library_extension,
    get_executable_extension,
    get_object_extension,
    get_static_library_extension,
    get_python_extension_module_extension,
    
    # Boolean checks
    is_windows,
    is_linux,
    is_macos,
    is_bsd,
    is_wsl,
    is_cygwin,
    is_msys,
    is_android,
    is_ios,
    is_unix,
    is_windows_family,
    is_64bit,
    is_32bit,
    is_arm,
    is_x86,
    
    # System resources
    get_cpu_count,
    get_cpu_count_physical,
    get_total_memory,
    get_available_memory,
    
    # Directories
    get_user_cache_dir,
    get_user_config_dir,
    get_user_data_dir,
    get_temp_directory,

    get_python_include_paths,
    get_python_library_paths,
    get_python_library_name,
    get_python_library_full_path,
    get_python_config_var,
    get_python_extension_suffix,

    __all__ as __all_platform__
)

from .checksum import (
    # Enums
    HashAlgorithm,
    
    # Exceptions
    ChecksumError,
    
    # Data classes
    ChecksumResult,
    BatchChecksumResult,
    
    # Classes
    StreamingHashReader,
    IncrementalHasher,
    
    # Core functions
    compute_file_hash,
    compute_checksum,
    compute_string_hash,
    compute_bytes_hash,
    compute_stream_hash,
    
    # Verification
    verify_checksum,
    compare_files,
    
    # Parallel
    compute_checksums_parallel,
    
    # Convenience
    hash_string,
    hash_file,
    get_file_checksum,
    hash_algorithm,
    __all__ as __all_checksum__
)

from .system import (
    CommandResult,
    CommandError,
    TimeoutError,
    run_command,
    run_command_sync,
    run_command_async,
    run_commands_parallel,
    get_environment,
    set_environment,
    get_env,
    set_env,
    unset_env,
    prepend_path,
    append_path,
    get_cpu_count,
    get_memory_info,
    get_disk_usage,
    get_process_id,
    get_process_parent_id,
    is_process_running,
    kill_process,
    kill_process_tree,
    get_child_processes,
    get_process_info,
    SignalHandler,
    send_signal,
    send_signal_to_group,
    create_process_group,
    get_process_group,
    TempFile,
    TempDirectory,
    create_temp_file,
    create_temp_directory,
    __all__ as __all_system__
)

__all__ = (
    __all_platform__ + 
    __all_checksum__ + 
    __all_system__
)


