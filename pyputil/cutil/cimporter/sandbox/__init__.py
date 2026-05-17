#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    COMPILATION SANDBOX SYSTEM
==================================

Secure isolation system for compilation processes with resource
limiting, filesystem restrictions, and cross-platform support.

This module provides comprehensive sandboxing capabilities:
- Process isolation and resource limiting
- Memory and CPU time restrictions
- Filesystem access control
- Network access blocking
- Temporary workspace management
- Cross-platform implementation (Linux, macOS, Windows)

Module Structure:
----------------
- isolate.py: Core process isolation and sandboxing infrastructure
- limits.py: Resource limiters (CPU, memory, disk, process, network)
- jail.py: Filesystem jail and path restrictions (Unix/Linux/macOS)
- windows.py: Windows-specific sandboxing utilities (Windows only)

Platform Support:
----------------
- Linux: Full support (process isolation, filesystem jail, cgroups, namespaces)
- macOS: Full support (process isolation, filesystem jail)
- Windows: Full support (job objects, restricted tokens, AppContainer)

Security Features:
-----------------
- Process isolation with resource limits
- Filesystem jail with read-only, whitelist, and blacklist paths
- Network access blocking
- Temporary workspace with automatic cleanup
- Chroot support (Unix, requires root)
- OverlayFS support for copy-on-write isolation
- Windows Job Objects for process group management
- Windows Restricted Tokens for privilege removal
- Windows Integrity Levels for mandatory access control

This module exports:
- SandboxManager: Main sandbox coordinator
- ResourceLimits: Resource limit configuration
- SandboxPolicy: Policy enumeration
- SandboxResult: Sandbox execution result
- SandboxError: Sandbox-related exceptions
- FilesystemJail: Filesystem restriction (Unix/macOS)
- WindowsJobObject: Windows job object wrapper

Examples
--------
>>> from cimporter.sandbox import SandboxManager, ResourceLimits, SandboxPolicy
>>> 
>>> # Basic sandbox with resource limits
>>> limits = ResourceLimits(
...     timeout_seconds=30,
...     memory_limit_mb=1024,
...     max_processes=1,
... )
>>> 
>>> sandbox = SandboxManager(
...     policy=SandboxPolicy.BASIC,
...     limits=limits,
... )
>>> 
>>> result = sandbox.run(["gcc", "-c", "source.c"])
>>> 
>>> if result.success:
...     print(f"Compilation completed in {result.execution_time:.2f}s")
...     print(f"Memory used: {result.memory_used_mb:.1f}MB")
... else:
...     print(f"Failed: {result.error_message}")
>>>     if result.violation:
...         print(f"Violation: {result.violation.value}")

>>> # Strict sandbox with filesystem restrictions
>>> sandbox = SandboxManager(
...     policy=SandboxPolicy.STRICT,
...     allowed_paths=[Path("/usr/bin"), Path("/lib"), Path("/tmp/build")],
...     read_only_paths=[Path("/usr"), Path("/etc")],
...     allow_network=False,
... )
>>> 
>>> with sandbox:
...     result = sandbox.run(["make", "-j4"], cwd=Path("/tmp/build"))

>>> # Custom resource limits
>>> limits = ResourceLimits(
...     timeout_seconds=120,
...     cpu_time_seconds=240,
...     memory_limit_mb=2048,
...     virtual_memory_limit_mb=4096,
...     max_processes=4,
...     max_threads=8,
...     max_open_files=256,
...     file_size_limit_mb=100,
...     disk_quota_mb=500,
... )
>>> 
>>> sandbox = SandboxManager(limits=limits)
>>> result = sandbox.run(["clang++", "-O3", "source.cpp"])

Notes
-----
- Some features require root/administrator privileges (chroot, some mount operations)
- Windows features may require specific Windows versions
- Filesystem jail on macOS has limitations compared to Linux
- Network blocking requires appropriate firewall privileges
"""

import sys
import os
import platform
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

# Setup module logger
logger = logging.getLogger(__name__)

# ============================================================================
# Platform Detection
# ============================================================================

def _get_platform_info() -> Dict[str, Any]:
    """
    Get detailed platform information for sandbox compatibility.
    
    Returns
    -------
    Dict[str, Any]
        Platform information dictionary.
    """
    info = {
        "system": sys.platform,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": sys.version,
        "is_windows": sys.platform == "win32",
        "is_linux": sys.platform.startswith("linux"),
        "is_macos": sys.platform == "darwin",
        "is_bsd": "bsd" in sys.platform,
        "is_root": False,
        "is_admin": False,
    }
    
    # Check root/admin privileges
    if info["is_windows"]:
        try:
            import ctypes
            info["is_admin"] = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            info["is_admin"] = False
    else:
        info["is_root"] = os.geteuid() == 0 if hasattr(os, "geteuid") else False
    
    return info


_PLATFORM_INFO = _get_platform_info()


def get_platform_info() -> Dict[str, Any]:
    """
    Get platform information for sandbox compatibility.
    
    Returns
    -------
    Dict[str, Any]
        Copy of platform information dictionary.
    """
    return _PLATFORM_INFO.copy()


def is_windows() -> bool:
    """Check if running on Windows."""
    return _PLATFORM_INFO["is_windows"]


def is_linux() -> bool:
    """Check if running on Linux."""
    return _PLATFORM_INFO["is_linux"]


def is_macos() -> bool:
    """Check if running on macOS."""
    return _PLATFORM_INFO["is_macos"]


def is_root() -> bool:
    """Check if running with root/admin privileges."""
    return _PLATFORM_INFO["is_root"] or _PLATFORM_INFO["is_admin"]


# ============================================================================
# Core Imports (Always Available)
# ============================================================================

# These modules work on all platforms
from .isolate import (
    SandboxManager,
    ProcessIsolator,
    ResourceLimits,
    SandboxPolicy,
    SandboxResult,
    SandboxError,
    SandboxViolation,
)

# Custom exceptions for better error handling
class SandboxTimeoutError(SandboxError):
    """Raised when execution exceeds time limit."""
    pass


class SandboxMemoryError(SandboxError):
    """Raised when memory limit is exceeded."""
    pass


class SandboxCPUError(SandboxError):
    """Raised when CPU time limit is exceeded."""
    pass


class SandboxDiskError(SandboxError):
    """Raised when disk quota is exceeded."""
    pass


class SandboxProcessError(SandboxError):
    """Raised when process limit is exceeded."""
    pass


class SandboxNetworkError(SandboxError):
    """Raised when unauthorized network access is attempted."""
    pass


class SandboxFilesystemError(SandboxError):
    """Raised when unauthorized filesystem access is attempted."""
    pass


# Import limiters (available on all platforms with fallbacks)
try:
    from .limits import (
        CPULimiter,
        MemoryLimiter,
        DiskLimiter,
        ProcessLimiter,
        NetworkBlocker,
        ResourceLimiterManager,
    )
    _LIMITS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Resource limiters not available: {e}")
    _LIMITS_AVAILABLE = False
    
    # Create placeholder classes for type hints
    class CPULimiter:
        """CPU limiter (not available on this platform)."""
        def __init__(self, *args, **kwargs):
            raise NotImplementedError("CPU limiter not available on this platform")
    
    class MemoryLimiter:
        """Memory limiter (not available on this platform)."""
        def __init__(self, *args, **kwargs):
            raise NotImplementedError("Memory limiter not available on this platform")
    
    class DiskLimiter:
        """Disk limiter (not available on this platform)."""
        def __init__(self, *args, **kwargs):
            raise NotImplementedError("Disk limiter not available on this platform")
    
    class ProcessLimiter:
        """Process limiter (not available on this platform)."""
        def __init__(self, *args, **kwargs):
            raise NotImplementedError("Process limiter not available on this platform")
    
    class NetworkBlocker:
        """Network blocker (not available on this platform)."""
        def __init__(self, *args, **kwargs):
            raise NotImplementedError("Network blocker not available on this platform")
    
    class ResourceLimiterManager:
        """Resource limiter manager (not available on this platform)."""
        def __init__(self, *args, **kwargs):
            raise NotImplementedError("Resource limiter manager not available on this platform")


# ============================================================================
# Filesystem Jail (Unix/Linux/macOS Only)
# ============================================================================

_FILESYSTEM_JAIL_AVAILABLE = False
FilesystemJail = None
TempWorkspace = None
PathRestriction = None
PathPermission = None
MountType = None
JailFeature = None
JailViolation = None
PathRestrictionEngine = None
MountManager = None
QuotaInfo = None

if not is_windows():
    try:
        from .jail import (
            FilesystemJail,
            TempWorkspace,
            PathRestriction,
            PathPermission,
            MountType,
            JailFeature,
            JailViolation,
            PathRestrictionEngine,
            MountManager,
            QuotaInfo,
            JailError,
            PathNotAllowedError,
            ReadOnlyViolationError,
            QuotaExceededError,
            SymlinkTraversalError,
        )
        _FILESYSTEM_JAIL_AVAILABLE = True
        logger.debug("Filesystem jail module loaded successfully")
        
    except ImportError as e:
        logger.warning(
            f"Filesystem jail not available on this platform: {e}\n"
            f"Platform: {_PLATFORM_INFO['system']}\n"
            f"This feature requires Unix-like operating system (Linux/macOS/BSD)."
        )
        
        # Create placeholder classes for documentation
        class FilesystemJail:
            """
            Filesystem jail for sandboxed execution.
            
            .. warning::
               This feature is only available on Unix-like systems (Linux, macOS, BSD).
               Current platform: {platform}
            """.format(platform=_PLATFORM_INFO['system'])
            
            def __init__(self, *args, **kwargs):
                raise NotImplementedError(
                    f"FilesystemJail is not available on {_PLATFORM_INFO['system']}. "
                    f"This feature requires a Unix-like operating system."
                )
        
        class TempWorkspace:
            """Temporary workspace manager (Unix only)."""
            def __init__(self, *args, **kwargs):
                raise NotImplementedError(
                    f"TempWorkspace is not available on {_PLATFORM_INFO['system']}."
                )
        
        class PathRestriction:
            """Path restriction rule (Unix only)."""
            def __init__(self, *args, **kwargs):
                raise NotImplementedError(
                    f"PathRestriction is not available on {_PLATFORM_INFO['system']}."
                )
        
        # Define placeholder enums for type hints
        class PathPermission:
            """Path permission flags (Unix only)."""
            NONE = 0
            READ = 1
            WRITE = 2
            EXECUTE = 4
        
        class MountType:
            """Mount types (Unix only)."""
            BIND = "bind"
            TMPFS = "tmpfs"
            PROC = "proc"
        
        class JailFeature:
            """Jail features (Unix only)."""
            NONE = 0
        
        class JailViolation:
            """Jail violations (Unix only)."""
            PATH_NOT_ALLOWED = "path_not_allowed"
        
        class PathRestrictionEngine:
            """Path restriction engine (Unix only)."""
            def __init__(self, *args, **kwargs):
                raise NotImplementedError(
                    f"PathRestrictionEngine is not available on {_PLATFORM_INFO['system']}."
                )
        
        class MountManager:
            """Mount manager (Unix only)."""
            def __init__(self, *args, **kwargs):
                raise NotImplementedError(
                    f"MountManager is not available on {_PLATFORM_INFO['system']}."
                )
        
        class QuotaInfo:
            """Quota information (Unix only)."""
            def __init__(self, *args, **kwargs):
                raise NotImplementedError(
                    f"QuotaInfo is not available on {_PLATFORM_INFO['system']}."
                )
        
        class JailError(Exception):
            """Jail error (Unix only)."""
            pass
        
        class PathNotAllowedError(JailError):
            """Path not allowed error (Unix only)."""
            pass
        
        class ReadOnlyViolationError(JailError):
            """Read-only violation error (Unix only)."""
            pass
        
        class QuotaExceededError(JailError):
            """Quota exceeded error (Unix only)."""
            pass
        
        class SymlinkTraversalError(JailError):
            """Symlink traversal error (Unix only)."""
            pass

else:
    # On Windows, create placeholder classes with helpful messages
    class FilesystemJail:
        """
        Filesystem jail for sandboxed execution.
        
        .. warning::
           FilesystemJail is not available on Windows.
           On Windows, consider using:
           - WindowsJobObject for resource limiting
           - WindowsRestrictedToken for privilege removal
           - AppContainer for capability-based sandboxing
        """
        def __init__(self, *args, **kwargs):
            raise NotImplementedError(
                "FilesystemJail is not available on Windows. "
                "Consider using WindowsJobObject and WindowsRestrictedToken instead."
            )
    
    class TempWorkspace:
        """Temporary workspace manager."""
        def __init__(self, *args, **kwargs):
            # TempWorkspace actually works on Windows too, but we'll implement it separately
            import tempfile
            import shutil
            self.path = Path(tempfile.mkdtemp(prefix="sandbox_"))
            self._created = True
        
        def cleanup(self):
            if hasattr(self, '_created') and self._created:
                shutil.rmtree(self.path, ignore_errors=True)
                self._created = False
        
        def __enter__(self):
            return self
        
        def __exit__(self, *args):
            self.cleanup()
    
    class PathRestriction:
        """Path restriction rule."""
        def __init__(self, *args, **kwargs):
            pass
    
    class PathPermission:
        """Path permission flags."""
        NONE = 0
        READ = 1
        WRITE = 2
        EXECUTE = 4
    
    class MountType:
        """Mount types."""
        BIND = "bind"
    
    class JailFeature:
        """Jail features."""
        NONE = 0
    
    class JailViolation:
        """Jail violations."""
        PATH_NOT_ALLOWED = "path_not_allowed"
    
    class PathRestrictionEngine:
        """Path restriction engine."""
        pass
    
    class MountManager:
        """Mount manager."""
        pass
    
    class QuotaInfo:
        """Quota information."""
        pass
    
    class JailError(Exception):
        """Jail error."""
        pass
    
    class PathNotAllowedError(JailError):
        """Path not allowed error."""
        pass
    
    class ReadOnlyViolationError(JailError):
        """Read-only violation error."""
        pass
    
    class QuotaExceededError(JailError):
        """Quota exceeded error."""
        pass
    
    class SymlinkTraversalError(JailError):
        """Symlink traversal error."""
        pass


# ============================================================================
# Windows-Specific Imports
# ============================================================================

_WINDOWS_FEATURES_AVAILABLE = False
WindowsJobObject = None
WindowsProcessGroup = None
WindowsTokenPrivileges = None
WindowsRestrictedToken = None
WindowsProcessMitigations = None
WindowsAppContainer = None
WindowsDesktopIsolation = None

if is_windows():
    try:
        from .windows import (
            WindowsJobObject,
            WindowsRestrictedToken,
            WindowsProcessMitigations,
        )
        
        # Optional Windows features
        try:
            from .windows import WindowsProcessGroup
        except ImportError:
            WindowsProcessGroup = None
            
        try:
            from .windows import WindowsTokenPrivileges
        except ImportError:
            WindowsTokenPrivileges = None
        
        _WINDOWS_FEATURES_AVAILABLE = True
        logger.debug("Windows sandbox features loaded successfully")
        
    except ImportError as e:
        logger.warning(
            f"Windows sandbox features not available: {e}\n"
            f"This may be due to missing dependencies or insufficient permissions.\n"
            f"Some features require Windows 8 or later."
        )
        
        # Create placeholder classes with helpful messages
        class WindowsJobObject:
            """
            Windows Job Object for process group management.
            
            .. warning::
               Windows Job Object features are not available.
               This may be due to:
               - Not running on Windows
               - Missing required DLLs
               - Insufficient permissions
            """
            def __init__(self, *args, **kwargs):
                raise NotImplementedError(
                    "WindowsJobObject is not available. "
                    "Ensure you are running on Windows with appropriate permissions."
                )
        
        class WindowsRestrictedToken:
            """Windows Restricted Token for privilege removal."""
            def __init__(self, *args, **kwargs):
                raise NotImplementedError(
                    "WindowsRestrictedToken is not available."
                )
        
        class WindowsProcessMitigations:
            """Windows Process Mitigation Policies."""
            def __init__(self, *args, **kwargs):
                raise NotImplementedError(
                    "WindowsProcessMitigations is not available."
                )
        
        class WindowsProcessGroup:
            """Windows Process Group management."""
            pass
        
        class WindowsTokenPrivileges:
            """Windows Token Privilege management."""
            pass

else:
    # On non-Windows, create placeholder classes with helpful messages
    class WindowsJobObject:
        """
        Windows Job Object for process group management.
        
        .. warning::
           This feature is only available on Windows.
           Current platform: {platform}
           
           For Unix-like systems, consider using:
           - Resource limits (setrlimit)
           - Cgroups for resource control
           - Process groups for signal propagation
        """.format(platform=_PLATFORM_INFO['system'])
        
        def __init__(self, *args, **kwargs):
            raise NotImplementedError(
                f"WindowsJobObject is only available on Windows. "
                f"Current platform: {_PLATFORM_INFO['system']}. "
                f"Use ResourceLimits for cross-platform resource limiting."
            )
    
    class WindowsRestrictedToken:
        """Windows Restricted Token (Windows only)."""
        def __init__(self, *args, **kwargs):
            raise NotImplementedError(
                f"WindowsRestrictedToken is only available on Windows."
            )
    
    class WindowsProcessMitigations:
        """Windows Process Mitigations (Windows only)."""
        def __init__(self, *args, **kwargs):
            raise NotImplementedError(
                f"WindowsProcessMitigations is only available on Windows."
            )
    
    class WindowsProcessGroup:
        """Windows Process Group (Windows only)."""
        pass
    
    class WindowsTokenPrivileges:
        """Windows Token Privileges (Windows only)."""
        pass


# Utility Functions
# ============================================================================

def get_available_features() -> Dict[str, bool]:
    """
    Get information about available sandbox features on current platform.
    
    Returns
    -------
    Dict[str, bool]
        Dictionary indicating which features are available.
        
    Examples
    --------
    >>> features = get_available_features()
    >>> print(f"Filesystem jail: {features['filesystem_jail']}")
    >>> print(f"Windows job objects: {features['windows_job_object']}")
    >>> print(f"Resource limiters: {features['resource_limiters']}")
    """
    return {
        "platform": _PLATFORM_INFO["system"],
        "is_windows": is_windows(),
        "is_linux": is_linux(),
        "is_macos": is_macos(),
        "is_root": is_root(),
        "filesystem_jail": _FILESYSTEM_JAIL_AVAILABLE,
        "windows_job_object": _WINDOWS_FEATURES_AVAILABLE,
        "resource_limiters": _LIMITS_AVAILABLE,
        "chroot_available": is_root() and not is_windows(),
        "overlayfs_available": is_linux() and os.path.exists("/sys/module/overlay"),
        "cgroups_available": is_linux() and os.path.exists("/sys/fs/cgroup"),
        "namespaces_available": is_linux() and os.path.exists("/proc/self/ns"),
        "appcontainer_available": is_windows(),  # Windows 8+
    }


def print_platform_info() -> None:
    """
    Print detailed platform information for debugging.
    
    Examples
    --------
    >>> print_platform_info()
    Platform Information:
    ====================
    System: linux
    Platform: Linux-5.15.0-generic-x86_64-with-glibc2.35
    Machine: x86_64
    Root: False
    
    Available Features:
    ==================
    Filesystem Jail: True
    Windows Job Object: False
    Resource Limiters: True
    Chroot: False (requires root)
    OverlayFS: True
    Cgroups: True
    Namespaces: True
    """
    print("Platform Information:")
    print("====================")
    for key, value in _PLATFORM_INFO.items():
        print(f"{key}: {value}")
    
    print("\nAvailable Features:")
    print("==================")
    features = get_available_features()
    for key, value in features.items():
        if key not in ["platform", "is_windows", "is_linux", "is_macos"]:
            print(f"{key}: {value}")


def create_sandbox(
    policy: SandboxPolicy = SandboxPolicy.BASIC,
    timeout_seconds: Optional[float] = 60,
    memory_limit_mb: Optional[int] = 1024,
    cpu_time_seconds: Optional[float] = None,
    max_processes: Optional[int] = None,
    allow_network: bool = False,
    allowed_paths: Optional[List[Path]] = None,
    read_only_paths: Optional[List[Path]] = None,
    workspace: Optional[Path] = None,
) -> SandboxManager:
    """
    Convenience function to create a sandbox with common settings.
    
    Parameters
    ----------
    policy : SandboxPolicy
        Sandbox security policy.
    timeout_seconds : Optional[float]
        Wall-clock timeout in seconds.
    memory_limit_mb : Optional[int]
        Memory limit in megabytes.
    cpu_time_seconds : Optional[float]
        CPU time limit in seconds.
    max_processes : Optional[int]
        Maximum number of child processes.
    allow_network : bool
        Whether to allow network access.
    allowed_paths : Optional[List[Path]]
        Paths allowed for filesystem access.
    read_only_paths : Optional[List[Path]]
        Read-only allowed paths.
    workspace : Optional[Path]
        Custom workspace directory.
        
    Returns
    -------
    SandboxManager
        Configured sandbox manager.
        
    Examples
    --------
    >>> sandbox = create_sandbox(
    ...     policy=SandboxPolicy.STRICT,
    ...     timeout_seconds=30,
    ...     memory_limit_mb=512,
    ...     allowed_paths=[Path("/tmp"), Path.cwd()],
    ... )
    >>> result = sandbox.run(["gcc", "source.c"])
    """
    limits = ResourceLimits(
        timeout_seconds=timeout_seconds,
        memory_limit_mb=memory_limit_mb,
        cpu_time_seconds=cpu_time_seconds,
        max_processes=max_processes,
    )
    
    return SandboxManager(
        policy=policy,
        limits=limits,
        workspace=workspace,
        allow_network=allow_network,
        allowed_paths=allowed_paths,
        read_only_paths=read_only_paths,
    )


# Module Exports
# ============================================================================

__all__ = [    
    # Platform utilities
    "get_platform_info",
    "is_windows",
    "is_linux",
    "is_macos",
    "is_root",
    "get_available_features",
    "print_platform_info",
    "create_sandbox",
    
    # Main classes
    "SandboxManager",
    "ProcessIsolator",
    "ResourceLimits",
    "SandboxPolicy",
    "SandboxResult",
    
    # Exceptions
    "SandboxError",
    "SandboxViolation",
    "SandboxTimeoutError",
    "SandboxMemoryError",
    "SandboxCPUError",
    "SandboxDiskError",
    "SandboxProcessError",
    "SandboxNetworkError",
    "SandboxFilesystemError",
    
    # Limiters
    "CPULimiter",
    "MemoryLimiter",
    "DiskLimiter",
    "ProcessLimiter",
    "NetworkBlocker",
    "ResourceLimiterManager",
    
    # Filesystem isolation
    "FilesystemJail",
    "TempWorkspace",
    "PathRestriction",
    "PathPermission",
    "MountType",
    "JailFeature",
    "JailViolation",
    "PathRestrictionEngine",
    "MountManager",
    "QuotaInfo",
    "JailError",
    "PathNotAllowedError",
    "ReadOnlyViolationError",
    "QuotaExceededError",
    "SymlinkTraversalError",
    
    # Windows-specific
    "WindowsJobObject",
    "WindowsProcessGroup",
    "WindowsTokenPrivileges",
    "WindowsRestrictedToken",
    "WindowsProcessMitigations",
]


# ============================================================================
# Module Initialization
# ============================================================================

def _initialize_module() -> None:
    """
    Initialize the sandbox module with platform-specific setup.
    """
    logger.debug(f"Initializing sandbox module on {_PLATFORM_INFO['system']}")
    
    # Log available features
    features = get_available_features()
    available = [k for k, v in features.items() if v and k not in ["platform", "is_windows", "is_linux", "is_macos"]]
    logger.debug(f"Available sandbox features: {', '.join(available)}")
    
    # Warn about missing features
    if not _LIMITS_AVAILABLE:
        logger.warning("Resource limiters are not fully available. Some limits may not be enforced.")
    
    if is_windows() and not _WINDOWS_FEATURES_AVAILABLE:
        logger.warning("Windows sandbox features are not available. Resource limiting may be limited.")
    
    if not is_windows() and not _FILESYSTEM_JAIL_AVAILABLE:
        logger.warning("Filesystem jail is not available. Path restrictions will not be enforced.")
    
    if not is_root() and not is_windows():
        logger.info("Not running as root. Some features (chroot, mount) will be unavailable.")


# Run initialization
_initialize_module()



