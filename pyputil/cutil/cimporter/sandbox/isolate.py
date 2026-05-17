#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    PROCESS ISOLATION CORE
==================================

Core process isolation and sandboxing infrastructure with
cross-platform resource limiting and security controls.
"""

import os
import sys
import time
import signal
import threading
import subprocess
import tempfile
import shutil
import platform
import resource
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union


class SandboxPolicy(Enum):
    """
    Sandbox security policy enumeration.

    Attributes
    ----------
    NONE : str
        No sandboxing applied. Full system access.
    MINIMAL : str
        Minimal restrictions - only basic resource limits.
    BASIC : str
        Basic sandbox - resource limits and temp workspace.
    STRICT : str
        Strict sandbox - filesystem restrictions and network blocking.
    MAXIMUM : str
        Maximum security - all restrictions enabled.
    CUSTOM : str
        Custom policy defined by user.
    """

    NONE = "none"
    MINIMAL = "minimal"
    BASIC = "basic"
    STRICT = "strict"
    MAXIMUM = "maximum"
    CUSTOM = "custom"

    def get_description(self) -> str:
        """
        Get human-readable description of policy.

        Returns
        -------
        str
            Policy description.
        """
        descriptions = {
            self.NONE: "No sandboxing - full system access",
            self.MINIMAL: "Minimal restrictions - only basic resource limits",
            self.BASIC: "Basic sandbox - resource limits and temp workspace",
            self.STRICT: "Strict sandbox - filesystem restrictions and network blocking",
            self.MAXIMUM: "Maximum security - all restrictions enabled",
            self.CUSTOM: "Custom policy defined by user",
        }
        return descriptions.get(self, "Unknown policy")

    def has_resource_limits(self) -> bool:
        """
        Check if resource limits are enabled.

        Returns
        -------
        bool
            True if resource limits should be applied.
        """
        return self != self.NONE

    def has_filesystem_restrictions(self) -> bool:
        """
        Check if filesystem restrictions are enabled.

        Returns
        -------
        bool
            True if filesystem should be restricted.
        """
        return self in (self.STRICT, self.MAXIMUM)

    def has_network_blocking(self) -> bool:
        """
        Check if network blocking is enabled.

        Returns
        -------
        bool
            True if network access should be blocked.
        """
        return self in (self.STRICT, self.MAXIMUM)

    def use_temp_workspace(self) -> bool:
        """
        Check if temporary workspace should be used.

        Returns
        -------
        bool
            True if temp workspace should be created.
        """
        return self in (self.BASIC, self.STRICT, self.MAXIMUM)


class SandboxViolation(Enum):
    """
    Types of sandbox violations.

    Attributes
    ----------
    TIMEOUT : str
        Execution exceeded time limit.
    MEMORY_EXCEEDED : str
        Memory limit exceeded.
    CPU_EXCEEDED : str
        CPU time limit exceeded.
    DISK_EXCEEDED : str
        Disk space/usage limit exceeded.
    PROCESS_LIMIT : str
        Maximum process limit exceeded.
    FILESYSTEM_ACCESS : str
        Unauthorized filesystem access attempted.
    NETWORK_ACCESS : str
        Unauthorized network access attempted.
    SYSTEM_CALL : str
        Unauthorized system call attempted.
    CHILD_PROCESS : str
        Unauthorized child process creation.
    SIGNAL_RECEIVED : str
        Process received terminating signal.
    """

    TIMEOUT = "timeout"
    MEMORY_EXCEEDED = "memory_exceeded"
    CPU_EXCEEDED = "cpu_exceeded"
    DISK_EXCEEDED = "disk_exceeded"
    PROCESS_LIMIT = "process_limit"
    FILESYSTEM_ACCESS = "filesystem_access"
    NETWORK_ACCESS = "network_access"
    SYSTEM_CALL = "system_call"
    CHILD_PROCESS = "child_process"
    SIGNAL_RECEIVED = "signal_received"


class SandboxError(Exception):
    """
    Base exception for sandbox-related errors.

    Parameters
    ----------
    message : str
        Error message.
    violation : Optional[SandboxViolation]
        Type of violation that occurred.
    details : Optional[Dict[str, Any]]
        Additional error details.

    Attributes
    ----------
    message : str
        Error message.
    violation : Optional[SandboxViolation]
        Violation type.
    details : Dict[str, Any]
        Error details.
    timestamp : float
        When the error occurred.

    Examples
    --------
    >>> try:
    ...     result = sandbox.run(["gcc", "source.c"])
    ... except SandboxError as e:
    ...     print(f"Sandbox violation: {e.violation}")
    ...     print(f"Details: {e.details}")
    """

    def __init__(
        self,
        message: str,
        violation: Optional[SandboxViolation] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.violation = violation
        self.details = details or {}
        self.timestamp = time.time()
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """
        Format error message with violation details.

        Returns
        -------
        str
            Formatted error message.
        """
        parts = [self.message]
        if self.violation:
            parts.append(f"[{self.violation.value}]")
        if self.details:
            detail_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            parts.append(f"({detail_str})")
        return " ".join(parts)


class TimeoutError(SandboxError):
    """
    Exception raised when execution exceeds time limit.

    Parameters
    ----------
    timeout_seconds : float
        Timeout limit that was exceeded.
    elapsed_seconds : float
        Actual elapsed time.
    """

    def __init__(self, timeout_seconds: float, elapsed_seconds: float):
        super().__init__(
            message=f"Execution timed out after {elapsed_seconds:.2f}s",
            violation=SandboxViolation.TIMEOUT,
            details={
                "timeout": timeout_seconds,
                "elapsed": elapsed_seconds,
            },
        )
        self.timeout_seconds = timeout_seconds
        self.elapsed_seconds = elapsed_seconds


class MemoryLimitError(SandboxError):
    """
    Exception raised when memory limit is exceeded.

    Parameters
    ----------
    limit_mb : int
        Memory limit in megabytes.
    attempted_mb : int
        Attempted memory usage.
    """

    def __init__(self, limit_mb: int, attempted_mb: int):
        super().__init__(
            message=f"Memory limit exceeded: {attempted_mb}MB > {limit_mb}MB",
            violation=SandboxViolation.MEMORY_EXCEEDED,
            details={
                "limit_mb": limit_mb,
                "attempted_mb": attempted_mb,
            },
        )
        self.limit_mb = limit_mb
        self.attempted_mb = attempted_mb


class CPULimitError(SandboxError):
    """
    Exception raised when CPU time limit is exceeded.

    Parameters
    ----------
    limit_seconds : float
        CPU time limit in seconds.
    used_seconds : float
        Actual CPU time used.
    """

    def __init__(self, limit_seconds: float, used_seconds: float):
        super().__init__(
            message=f"CPU time limit exceeded: {used_seconds:.2f}s > {limit_seconds:.2f}s",
            violation=SandboxViolation.CPU_EXCEEDED,
            details={
                "limit_seconds": limit_seconds,
                "used_seconds": used_seconds,
            },
        )
        self.limit_seconds = limit_seconds
        self.used_seconds = used_seconds


class FilesystemAccessError(SandboxError):
    """
    Exception raised when unauthorized filesystem access is attempted.

    Parameters
    ----------
    path : Path
        Path that was accessed.
    operation : str
        Operation attempted (read/write/execute).
    allowed_paths : List[Path]
        List of allowed paths.
    """

    def __init__(self, path: Path, operation: str, allowed_paths: List[Path]):
        super().__init__(
            message=f"Unauthorized filesystem {operation} access: {path}",
            violation=SandboxViolation.FILESYSTEM_ACCESS,
            details={
                "path": str(path),
                "operation": operation,
                "allowed_paths": [str(p) for p in allowed_paths],
            },
        )
        self.path = path
        self.operation = operation
        self.allowed_paths = allowed_paths


@dataclass
class ResourceLimits:
    """
    Comprehensive resource limits for sandboxed execution.

    Parameters
    ----------
    timeout_seconds : Optional[float]
        Wall-clock time limit in seconds.
    cpu_time_seconds : Optional[float]
        CPU time limit in seconds.
    memory_limit_mb : Optional[int]
        Maximum memory (RSS) in megabytes.
    virtual_memory_limit_mb : Optional[int]
        Maximum virtual memory in megabytes.
    stack_size_mb : Optional[int]
        Maximum stack size in megabytes.
    file_size_limit_mb : Optional[int]
        Maximum file size that can be created.
    max_open_files : Optional[int]
        Maximum number of open file descriptors.
    max_processes : Optional[int]
        Maximum number of child processes.
    max_threads : Optional[int]
        Maximum number of threads per process.
    disk_quota_mb : Optional[int]
        Maximum total disk usage in workspace.
    nice_priority : Optional[int]
        Process nice priority (-20 to 19).
    io_priority : Optional[str]
        I/O priority ('idle', 'low', 'normal', 'high').

    Attributes
    ----------
    timeout_seconds : Optional[float]
        Wall-clock timeout.
    cpu_time_seconds : Optional[float]
        CPU time limit.
    memory_limit_mb : Optional[int]
        Memory limit.
    virtual_memory_limit_mb : Optional[int]
        Virtual memory limit.
    stack_size_mb : Optional[int]
        Stack size limit.
    file_size_limit_mb : Optional[int]
        File size limit.
    max_open_files : Optional[int]
        Max open files.
    max_processes : Optional[int]
        Max child processes.
    max_threads : Optional[int]
        Max threads.
    disk_quota_mb : Optional[int]
        Disk quota.
    nice_priority : Optional[int]
        Nice priority.
    io_priority : Optional[str]
        I/O priority.

    Examples
    --------
    >>> limits = ResourceLimits(
    ...     timeout_seconds=30,
    ...     memory_limit_mb=1024,
    ...     cpu_time_seconds=60,
    ...     max_processes=1,
    ... )
    >>> print(limits.get_summary())
    """

    # Time limits
    timeout_seconds: Optional[float] = None
    cpu_time_seconds: Optional[float] = None

    # Memory limits
    memory_limit_mb: Optional[int] = None
    virtual_memory_limit_mb: Optional[int] = None
    stack_size_mb: Optional[int] = None

    # File limits
    file_size_limit_mb: Optional[int] = None
    max_open_files: Optional[int] = None

    # Process limits
    max_processes: Optional[int] = None
    max_threads: Optional[int] = None

    # Disk limits
    disk_quota_mb: Optional[int] = None

    # Priority
    nice_priority: Optional[int] = None
    io_priority: Optional[str] = None

    def validate(self) -> List[str]:
        """
        Validate resource limits and return warnings.

        Returns
        -------
        List[str]
            List of validation warnings.
        """
        warnings = []

        if self.nice_priority is not None and not (-20 <= self.nice_priority <= 19):
            warnings.append(f"Invalid nice_priority: {self.nice_priority} (should be -20 to 19)")

        if self.io_priority and self.io_priority not in ("idle", "low", "normal", "high"):
            warnings.append(f"Invalid io_priority: {self.io_priority}")

        if self.memory_limit_mb is not None and self.memory_limit_mb < 16:
            warnings.append(f"Memory limit too low: {self.memory_limit_mb}MB")

        return warnings

    def get_summary(self) -> str:
        """
        Get human-readable summary of limits.

        Returns
        -------
        str
            Summary string.
        """
        parts = []
        if self.timeout_seconds:
            parts.append(f"timeout={self.timeout_seconds}s")
        if self.cpu_time_seconds:
            parts.append(f"cpu={self.cpu_time_seconds}s")
        if self.memory_limit_mb:
            parts.append(f"memory={self.memory_limit_mb}MB")
        if self.max_processes:
            parts.append(f"max_procs={self.max_processes}")
        if self.disk_quota_mb:
            parts.append(f"disk={self.disk_quota_mb}MB")
        return ", ".join(parts) if parts else "no limits"

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "timeout_seconds": self.timeout_seconds,
            "cpu_time_seconds": self.cpu_time_seconds,
            "memory_limit_mb": self.memory_limit_mb,
            "virtual_memory_limit_mb": self.virtual_memory_limit_mb,
            "stack_size_mb": self.stack_size_mb,
            "file_size_limit_mb": self.file_size_limit_mb,
            "max_open_files": self.max_open_files,
            "max_processes": self.max_processes,
            "max_threads": self.max_threads,
            "disk_quota_mb": self.disk_quota_mb,
            "nice_priority": self.nice_priority,
            "io_priority": self.io_priority,
        }

    @classmethod
    def from_policy(cls, policy: SandboxPolicy) -> "ResourceLimits":
        """
        Create default limits based on policy.

        Parameters
        ----------
        policy : SandboxPolicy
            Sandbox policy.

        Returns
        -------
        ResourceLimits
            Configured resource limits.
        """
        if policy == SandboxPolicy.NONE:
            return cls()

        elif policy == SandboxPolicy.MINIMAL:
            return cls(
                timeout_seconds=300,
                memory_limit_mb=4096,
            )

        elif policy == SandboxPolicy.BASIC:
            return cls(
                timeout_seconds=120,
                cpu_time_seconds=240,
                memory_limit_mb=2048,
                max_processes=4,
                max_open_files=256,
            )

        elif policy == SandboxPolicy.STRICT:
            return cls(
                timeout_seconds=60,
                cpu_time_seconds=120,
                memory_limit_mb=1024,
                virtual_memory_limit_mb=2048,
                max_processes=1,
                max_threads=4,
                max_open_files=64,
                file_size_limit_mb=100,
                disk_quota_mb=500,
            )

        elif policy == SandboxPolicy.MAXIMUM:
            return cls(
                timeout_seconds=30,
                cpu_time_seconds=60,
                memory_limit_mb=512,
                virtual_memory_limit_mb=1024,
                stack_size_mb=8,
                max_processes=1,
                max_threads=2,
                max_open_files=32,
                file_size_limit_mb=50,
                disk_quota_mb=200,
            )

        return cls()


@dataclass
class SandboxResult:
    """
    Result of a sandboxed execution.

    Parameters
    ----------
    success : bool
        Whether execution succeeded.
    return_code : int
        Process return code.
    stdout : str
        Standard output.
    stderr : str
        Standard error.
    execution_time : float
        Wall-clock execution time in seconds.
    cpu_time : float
        CPU time used in seconds.
    memory_used_mb : float
        Peak memory usage in megabytes.
    timed_out : bool
        Whether execution timed out.
    violation : Optional[SandboxViolation]
        Violation that occurred, if any.
    error_message : Optional[str]
        Error message if failed.
    process_info : Dict[str, Any]
        Additional process information.

    Attributes
    ----------
    success : bool
        Success flag.
    return_code : int
        Return code.
    stdout : str
        Standard output.
    stderr : str
        Standard error.
    execution_time : float
        Execution time.
    cpu_time : float
        CPU time.
    memory_used_mb : float
        Memory used.
    timed_out : bool
        Timeout flag.
    violation : Optional[SandboxViolation]
        Violation type.
    error_message : Optional[str]
        Error message.
    process_info : Dict[str, Any]
        Process info.

    Examples
    --------
    >>> result = sandbox.run(["gcc", "source.c"])
    >>> if result.success:
    ...     print(f"Compiled in {result.execution_time:.2f}s")
    ...     print(f"Memory used: {result.memory_used_mb:.1f}MB")
    >>> else:
    ...     print(f"Failed: {result.error_message}")
    """

    success: bool
    return_code: int = 0
    stdout: str = ""
    stderr: str = ""
    execution_time: float = 0.0
    cpu_time: float = 0.0
    memory_used_mb: float = 0.0
    timed_out: bool = False
    violation: Optional[SandboxViolation] = None
    error_message: Optional[str] = None
    process_info: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "success": self.success,
            "return_code": self.return_code,
            "execution_time": self.execution_time,
            "cpu_time": self.cpu_time,
            "memory_used_mb": self.memory_used_mb,
            "timed_out": self.timed_out,
            "violation": self.violation.value if self.violation else None,
            "error_message": self.error_message,
            "process_info": self.process_info,
        }

    def get_summary(self) -> str:
        """
        Get human-readable summary.

        Returns
        -------
        str
            Summary string.
        """
        if self.success:
            return (
                f"SUCCESS (code={self.return_code}) "
                f"in {self.execution_time:.2f}s, "
                f"{self.memory_used_mb:.1f}MB"
            )
        elif self.timed_out:
            return f"TIMEOUT after {self.execution_time:.2f}s"
        elif self.violation:
            return f"VIOLATION [{self.violation.value}]: {self.error_message}"
        else:
            return f"FAILED (code={self.return_code}): {self.error_message}"


class ProcessIsolator(ABC):
    """
    Abstract base class for process isolation strategies.

    Different platforms require different isolation mechanisms.
    This class defines the interface for all isolator implementations.

    Attributes
    ----------
    limits : ResourceLimits
        Resource limits to apply.
    workspace : Optional[Path]
        Temporary workspace path.

    Examples
    --------
    >>> class UnixIsolator(ProcessIsolator):
    ...     def run(self, cmd, **kwargs):
    ...         # Unix-specific isolation
    ...         pass
    """

    def __init__(
        self,
        limits: ResourceLimits,
        workspace: Optional[Path] = None,
    ):
        self.limits = limits
        self.workspace = workspace
        self._start_time: Optional[float] = None
        self._process: Optional[subprocess.Popen] = None

    @abstractmethod
    def run(
        self,
        cmd: List[str],
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[Path] = None,
        input_data: Optional[str] = None,
        capture_output: bool = True,
        **kwargs,
    ) -> SandboxResult:
        """
        Run a command in isolation.

        Parameters
        ----------
        cmd : List[str]
            Command to execute.
        env : Optional[Dict[str, str]]
            Environment variables.
        cwd : Optional[Path]
            Working directory.
        input_data : Optional[str]
            Data to send to stdin.
        capture_output : bool
            Whether to capture stdout/stderr.
        **kwargs : Any
            Additional platform-specific options.

        Returns
        -------
        SandboxResult
            Execution result.
        """
        pass

    @abstractmethod
    def terminate(self) -> None:
        """
        Terminate the running process.
        """
        pass

    @abstractmethod
    def kill(self) -> None:
        """
        Force kill the running process.
        """
        pass

    @abstractmethod
    def get_resource_usage(self) -> Dict[str, Any]:
        """
        Get current resource usage of the process.

        Returns
        -------
        Dict[str, Any]
            Resource usage statistics.
        """
        pass

    def _pre_exec(self) -> Callable:
        """
        Get pre-execution function for process setup.

        Returns
        -------
        Callable
            Pre-exec function.
        """
        def setup():
            # Set process group
            os.setpgrp()

            # Apply resource limits
            self._apply_resource_limits()

            # Change to workspace
            if self.workspace:
                os.chdir(str(self.workspace))

        return setup

    def _apply_resource_limits(self) -> None:
        """
        Apply resource limits to current process.
        """
        if not hasattr(resource, "RLIMIT_AS"):
            return

        try:
            # Memory limit (virtual)
            if self.limits.virtual_memory_limit_mb:
                limit = self.limits.virtual_memory_limit_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

            # CPU time limit
            if self.limits.cpu_time_seconds:
                limit = int(self.limits.cpu_time_seconds)
                resource.setrlimit(resource.RLIMIT_CPU, (limit, limit))

            # File size limit
            if self.limits.file_size_limit_mb:
                limit = self.limits.file_size_limit_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))

            # Open files limit
            if self.limits.max_open_files:
                limit = self.limits.max_open_files
                resource.setrlimit(resource.RLIMIT_NOFILE, (limit, limit))

            # Stack size limit
            if self.limits.stack_size_mb:
                limit = self.limits.stack_size_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_STACK, (limit, limit))

            # Process limit
            if self.limits.max_processes:
                limit = self.limits.max_processes
                resource.setrlimit(resource.RLIMIT_NPROC, (limit, limit))

        except (ValueError, OSError):
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.terminate()


class UnixProcessIsolator(ProcessIsolator):
    """
    Unix/Linux/macOS process isolator using setrlimit and process groups.

    This isolator uses:
    - setrlimit for resource limits
    - Process groups for signal propagation
    - setpgid for process isolation
    - prctl for additional security (Linux)

    Parameters
    ----------
    limits : ResourceLimits
        Resource limits.
    workspace : Optional[Path]
        Temporary workspace.
    use_prctl : bool
        Use prctl for additional restrictions (Linux only).
    """

    def __init__(
        self,
        limits: ResourceLimits,
        workspace: Optional[Path] = None,
        use_prctl: bool = True,
    ):
        super().__init__(limits, workspace)
        self.use_prctl = use_prctl and sys.platform.startswith("linux")

    def run(
        self,
        cmd: List[str],
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[Path] = None,
        input_data: Optional[str] = None,
        capture_output: bool = True,
        **kwargs,
    ) -> SandboxResult:
        """
        Run command with Unix isolation.

        Parameters
        ----------
        cmd : List[str]
            Command to execute.
        env : Optional[Dict[str, str]]
            Environment variables.
        cwd : Optional[Path]
            Working directory.
        input_data : Optional[str]
            Stdin data.
        capture_output : bool
            Capture output.

        Returns
        -------
        SandboxResult
            Execution result.
        """
        start_time = time.time()
        self._start_time = start_time

        # Prepare environment
        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        # Prepare working directory
        work_dir = str(cwd) if cwd else (str(self.workspace) if self.workspace else None)

        try:
            self._process = subprocess.Popen(
                cmd,
                env=process_env,
                cwd=work_dir,
                stdin=subprocess.PIPE if input_data else None,
                stdout=subprocess.PIPE if capture_output else None,
                stderr=subprocess.PIPE if capture_output else None,
                text=True,
                preexec_fn=self._pre_exec() if not self.use_prctl else os.setsid,
                start_new_session=True,
            )

            # Apply Linux-specific restrictions
            if self.use_prctl and self._process.pid:
                self._apply_prctl_restrictions(self._process.pid)

            # Wait with timeout
            stdout, stderr = "", ""
            timed_out = False
            memory_used = 0.0
            cpu_time = 0.0

            try:
                stdout, stderr = self._process.communicate(
                    input=input_data,
                    timeout=self.limits.timeout_seconds,
                )

                # Get resource usage
                if self._process.returncode is not None:
                    usage = self.get_resource_usage()
                    memory_used = usage.get("memory_mb", 0.0)
                    cpu_time = usage.get("cpu_time", 0.0)

            except subprocess.TimeoutExpired:
                timed_out = True
                self.terminate()
                try:
                    stdout, stderr = self._process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    self.kill()
                    stdout, stderr = self._process.communicate()

            execution_time = time.time() - start_time
            return_code = self._process.returncode if self._process.returncode is not None else -1

            # Check for violations
            violation = None
            error_message = None

            if timed_out:
                violation = SandboxViolation.TIMEOUT
                error_message = f"Execution exceeded timeout of {self.limits.timeout_seconds}s"

            elif return_code == -9:  # SIGKILL
                violation = SandboxViolation.SIGNAL_RECEIVED
                error_message = "Process was killed"

            elif return_code == -6:  # SIGABRT
                violation = SandboxViolation.SIGNAL_RECEIVED
                error_message = "Process aborted"

            elif self.limits.memory_limit_mb and memory_used > self.limits.memory_limit_mb:
                violation = SandboxViolation.MEMORY_EXCEEDED
                error_message = f"Memory limit exceeded: {memory_used:.1f}MB > {self.limits.memory_limit_mb}MB"

            return SandboxResult(
                success=return_code == 0 and not timed_out and violation is None,
                return_code=return_code,
                stdout=stdout or "",
                stderr=stderr or "",
                execution_time=execution_time,
                cpu_time=cpu_time,
                memory_used_mb=memory_used,
                timed_out=timed_out,
                violation=violation,
                error_message=error_message,
                process_info={
                    "pid": self._process.pid,
                    "cmd": cmd,
                },
            )

        except Exception as e:
            execution_time = time.time() - start_time
            return SandboxResult(
                success=False,
                execution_time=execution_time,
                error_message=str(e),
                violation=SandboxViolation.SYSTEM_CALL,
            )

    def _apply_prctl_restrictions(self, pid: int) -> None:
        """
        Apply Linux prctl restrictions to process.

        Parameters
        ----------
        pid : int
            Process ID.
        """
        try:
            import ctypes
            import ctypes.util

            libc = ctypes.CDLL(ctypes.util.find_library("c"))

            PR_SET_PDEATHSIG = 1
            PR_SET_DUMPABLE = 4
            PR_SET_NO_NEW_PRIVS = 38
            PR_SET_SECCOMP = 22
            SECCOMP_MODE_FILTER = 2

            # Die when parent dies
            libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL)

            # Disable core dumps
            libc.prctl(PR_SET_DUMPABLE, 0)

            # Prevent privilege escalation
            libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)

        except (ImportError, AttributeError, OSError):
            pass

    def terminate(self) -> None:
        """
        Terminate the process group.
        """
        if self._process and self._process.poll() is None:
            try:
                if sys.platform != "win32":
                    os.killpg(self._process.pid, signal.SIGTERM)
                else:
                    self._process.terminate()
            except (ProcessLookupError, OSError):
                pass

    def kill(self) -> None:
        """
        Force kill the process group.
        """
        if self._process and self._process.poll() is None:
            try:
                if sys.platform != "win32":
                    os.killpg(self._process.pid, signal.SIGKILL)
                else:
                    self._process.kill()
            except (ProcessLookupError, OSError):
                pass

    def get_resource_usage(self) -> Dict[str, Any]:
        """
        Get resource usage for the process.

        Returns
        -------
        Dict[str, Any]
            Resource usage statistics.
        """
        usage: Dict[str, Any] = {
            "cpu_time": 0.0,
            "memory_mb": 0.0,
            "peak_memory_mb": 0.0,
        }

        if not self._process or self._process.pid is None:
            return usage

        try:
            rusage = resource.getrusage(resource.RUSAGE_CHILDREN)
            usage["cpu_time"] = rusage.ru_utime + rusage.ru_stime
            usage["memory_mb"] = rusage.ru_maxrss / 1024.0
            usage["peak_memory_mb"] = usage["memory_mb"]

            # Try to get current memory from /proc
            if sys.platform.startswith("linux"):
                try:
                    with open(f"/proc/{self._process.pid}/statm", "r") as f:
                        fields = f.read().split()
                        if len(fields) >= 2:
                            # Resident memory in pages
                            pages = int(fields[1])
                            page_size = os.sysconf("SC_PAGE_SIZE")
                            usage["current_memory_mb"] = (pages * page_size) / (1024 * 1024)
                except (IOError, OSError):
                    pass

        except (resource.error, OSError):
            pass

        return usage


class WindowsProcessIsolator(ProcessIsolator):
    """
    Windows process isolator using Job Objects.

    This isolator uses Windows Job Objects for:
    - Resource limiting (CPU, memory, processes)
    - Process group management
    - Automatic cleanup of child processes

    Parameters
    ----------
    limits : ResourceLimits
        Resource limits.
    workspace : Optional[Path]
        Temporary workspace.
    """

    def __init__(
        self,
        limits: ResourceLimits,
        workspace: Optional[Path] = None,
    ):
        super().__init__(limits, workspace)
        self._job_object = None
        self._process_group = None

    def _create_job_object(self) -> Any:
        """
        Create and configure Windows Job Object.

        Returns
        -------
        Any
            Job object handle.
        """
        try:
            from .windows import WindowsJobObject

            job = WindowsJobObject()

            # Configure limits
            if self.limits.memory_limit_mb:
                job.set_memory_limit(self.limits.memory_limit_mb)

            if self.limits.cpu_time_seconds:
                job.set_cpu_limit(self.limits.cpu_time_seconds)

            if self.limits.max_processes:
                job.set_process_limit(self.limits.max_processes)

            job.set_kill_on_close(True)

            return job

        except ImportError:
            return None

    def run(
        self,
        cmd: List[str],
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[Path] = None,
        input_data: Optional[str] = None,
        capture_output: bool = True,
        **kwargs,
    ) -> SandboxResult:
        """
        Run command with Windows isolation.

        Parameters
        ----------
        cmd : List[str]
            Command to execute.
        env : Optional[Dict[str, str]]
            Environment variables.
        cwd : Optional[Path]
            Working directory.
        input_data : Optional[str]
            Stdin data.
        capture_output : bool
            Capture output.

        Returns
        -------
        SandboxResult
            Execution result.
        """
        start_time = time.time()
        self._start_time = start_time

        # Create job object
        self._job_object = self._create_job_object()

        # Prepare environment
        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        # Prepare working directory
        work_dir = str(cwd) if cwd else (str(self.workspace) if self.workspace else None)

        try:
            # Create process with job object
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

            if self._job_object:
                creation_flags |= subprocess.CREATE_BREAKAWAY_FROM_JOB

            self._process = subprocess.Popen(
                cmd,
                env=process_env,
                cwd=work_dir,
                stdin=subprocess.PIPE if input_data else None,
                stdout=subprocess.PIPE if capture_output else None,
                stderr=subprocess.PIPE if capture_output else None,
                text=True,
                creationflags=creation_flags,
            )

            # Assign to job object
            if self._job_object and self._process.pid:
                self._job_object.assign_process(self._process.pid)

            # Wait with timeout
            stdout, stderr = "", ""
            timed_out = False

            try:
                stdout, stderr = self._process.communicate(
                    input=input_data,
                    timeout=self.limits.timeout_seconds,
                )

            except subprocess.TimeoutExpired:
                timed_out = True
                self.terminate()
                try:
                    stdout, stderr = self._process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    self.kill()
                    stdout, stderr = self._process.communicate()

            execution_time = time.time() - start_time
            return_code = self._process.returncode if self._process.returncode is not None else -1

            # Get resource usage
            memory_used = 0.0
            cpu_time = 0.0

            if self._job_object:
                usage = self._job_object.get_usage()
                memory_used = usage.get("peak_memory_mb", 0.0)
                cpu_time = usage.get("cpu_time", 0.0)

            # Check for violations
            violation = None
            error_message = None

            if timed_out:
                violation = SandboxViolation.TIMEOUT
                error_message = f"Execution exceeded timeout of {self.limits.timeout_seconds}s"

            return SandboxResult(
                success=return_code == 0 and not timed_out,
                return_code=return_code,
                stdout=stdout or "",
                stderr=stderr or "",
                execution_time=execution_time,
                cpu_time=cpu_time,
                memory_used_mb=memory_used,
                timed_out=timed_out,
                violation=violation,
                error_message=error_message,
                process_info={
                    "pid": self._process.pid,
                    "cmd": cmd,
                },
            )

        except Exception as e:
            execution_time = time.time() - start_time
            return SandboxResult(
                success=False,
                execution_time=execution_time,
                error_message=str(e),
                violation=SandboxViolation.SYSTEM_CALL,
            )

    def terminate(self) -> None:
        """
        Terminate the job object (kills all processes).
        """
        if self._job_object:
            self._job_object.terminate()
        elif self._process:
            self._process.terminate()

    def kill(self) -> None:
        """
        Force kill the job object.
        """
        if self._job_object:
            self._job_object.kill()
        elif self._process:
            self._process.kill()

    def get_resource_usage(self) -> Dict[str, Any]:
        """
        Get resource usage from job object.

        Returns
        -------
        Dict[str, Any]
            Resource usage statistics.
        """
        if self._job_object:
            return self._job_object.get_usage()
        return {
            "cpu_time": 0.0,
            "memory_mb": 0.0,
            "peak_memory_mb": 0.0,
        }


class SandboxManager:
    """
    Main sandbox manager coordinating isolation and resource limiting.

    This class provides a unified interface for sandboxed execution
    across all platforms, automatically selecting the appropriate
    isolation strategy.

    Parameters
    ----------
    policy : SandboxPolicy
        Sandbox security policy.
    limits : Optional[ResourceLimits]
        Custom resource limits (overrides policy defaults).
    workspace : Optional[Path]
        Custom workspace directory.
    allow_network : bool
        Allow network access.
    allowed_paths : Optional[List[Path]]
        Paths allowed for filesystem access.
    denied_paths : Optional[List[Path]]
        Paths explicitly denied.
    read_only_paths : Optional[List[Path]]
        Read-only allowed paths.

    Attributes
    ----------
    policy : SandboxPolicy
        Security policy.
    limits : ResourceLimits
        Resource limits.
    workspace : Path
        Workspace directory.
    allow_network : bool
        Network allowed flag.
    allowed_paths : List[Path]
        Allowed paths.
    denied_paths : List[Path]
        Denied paths.
    read_only_paths : List[Path]
        Read-only paths.
    _isolator : Optional[ProcessIsolator]
        Current process isolator.
    _jail : Optional[Any]
        Filesystem jail (if enabled).
    _temp_workspace : Optional[TempWorkspace]
        Temporary workspace manager.

    Examples
    --------
    >>> # Basic usage
    >>> sandbox = SandboxManager(policy=SandboxPolicy.BASIC)
    >>> result = sandbox.run(["gcc", "-c", "source.c"])
    >>> print(result.get_summary())

    >>> # Custom limits
    >>> limits = ResourceLimits(
    ...     timeout_seconds=30,
    ...     memory_limit_mb=512,
    ...     max_processes=1,
    ... )
    >>> sandbox = SandboxManager(
    ...     policy=SandboxPolicy.CUSTOM,
    ...     limits=limits,
    ...     allowed_paths=[Path("/tmp"), Path.cwd()],
    ... )
    >>> result = sandbox.run(["make", "-j4"])

    >>> # Context manager
    >>> with SandboxManager(policy=SandboxPolicy.STRICT) as sandbox:
    ...     result = sandbox.run(["clang", "source.c"])
    """

    def __init__(
        self,
        policy: SandboxPolicy = SandboxPolicy.BASIC,
        limits: Optional[ResourceLimits] = None,
        workspace: Optional[Path] = None,
        allow_network: bool = False,
        allowed_paths: Optional[List[Path]] = None,
        denied_paths: Optional[List[Path]] = None,
        read_only_paths: Optional[List[Path]] = None,
    ):
        self.policy = policy
        self.allow_network = allow_network
        self.allowed_paths = allowed_paths or []
        self.denied_paths = denied_paths or []
        self.read_only_paths = read_only_paths or []

        # Configure limits
        if limits:
            self.limits = limits
        else:
            self.limits = ResourceLimits.from_policy(policy)

        # Validate limits
        warnings = self.limits.validate()
        if warnings:
            import logging
            for warning in warnings:
                logging.getLogger(__name__).warning(f"Resource limit warning: {warning}")

        # Setup workspace
        self._temp_workspace = None
        if workspace:
            self.workspace = workspace
        elif getattr(policy, "use_temp_workspace", lambda: False)():
            self._temp_workspace = TempWorkspace(prefix="sandbox_")
            self.workspace = self._temp_workspace.path
        else:
            self.workspace = Path.cwd()

        # Initialize isolator and jail
        self._isolator: Optional[ProcessIsolator] = None
        self._jail: Optional[Any] = None

        if getattr(policy, "has_filesystem_restrictions", lambda: False)():
            self._setup_jail()

    def _setup_jail(self) -> None:
        """
        Setup filesystem jail for strict policies.
        """
        try:
            from .jail import FilesystemJail

            self._jail = FilesystemJail(
                root_path=self.workspace,
                allowed_paths=self.allowed_paths,
                denied_paths=self.denied_paths,
                read_only_paths=self.read_only_paths,
                allow_network=self.allow_network,
            )

        except ImportError:
            import logging
            logging.getLogger(__name__).warning("Filesystem jail not available on this platform")

    def _get_isolator(self) -> ProcessIsolator:
        """
        Get appropriate process isolator for current platform.

        Returns
        -------
        ProcessIsolator
            Process isolator instance.
        """
        if self._isolator:
            return self._isolator

        if sys.platform == "win32":
            self._isolator = WindowsProcessIsolator(
                limits=self.limits,
                workspace=self.workspace,
            )
        else:
            self._isolator = UnixProcessIsolator(
                limits=self.limits,
                workspace=self.workspace,
                use_prctl=True,
            )

        return self._isolator

    def run(
        self,
        cmd: List[str],
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[Path] = None,
        input_data: Optional[str] = None,
        capture_output: bool = True,
        **kwargs,
    ) -> SandboxResult:
        """
        Run a command in the sandbox.

        Parameters
        ----------
        cmd : List[str]
            Command to execute.
        env : Optional[Dict[str, str]]
            Environment variables.
        cwd : Optional[Path]
            Working directory (relative to workspace).
        input_data : Optional[str]
            Data to send to stdin.
        capture_output : bool
            Whether to capture stdout/stderr.
        **kwargs : Any
            Additional platform-specific options.

        Returns
        -------
        SandboxResult
            Execution result.

        Raises
        ------
        SandboxError
            If sandbox setup fails.
        """
        if self.policy == SandboxPolicy.NONE:
            # Direct execution without sandbox
            return self._run_direct(cmd, env, cwd, input_data, capture_output)

        # Resolve working directory
        work_dir = self.workspace
        if cwd:
            work_dir = work_dir / cwd

        # Check path restrictions
        if self._jail:
            if not self._jail.is_path_allowed(work_dir):
                raise FilesystemAccessError(
                    path=work_dir,
                    operation="cwd",
                    allowed_paths=self._jail.allowed_paths,
                )

        # Get isolator and run
        isolator = self._get_isolator()

        # Add jail environment if needed
        if self._jail:
            jail_env = self._jail.get_environment()
            if env:
                jail_env.update(env)
            env = jail_env

        return isolator.run(
            cmd=cmd,
            env=env,
            cwd=work_dir,
            input_data=input_data,
            capture_output=capture_output,
            **kwargs,
        )

    def _run_direct(
        self,
        cmd: List[str],
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[Path] = None,
        input_data: Optional[str] = None,
        capture_output: bool = True,
    ) -> SandboxResult:
        """
        Run command directly without sandbox.

        Parameters
        ----------
        cmd : List[str]
            Command to execute.
        env : Optional[Dict[str, str]]
            Environment variables.
        cwd : Optional[Path]
            Working directory.
        input_data : Optional[str]
            Stdin data.
        capture_output : bool
            Capture output.

        Returns
        -------
        SandboxResult
            Execution result.
        """
        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                env=env,
                cwd=str(cwd) if cwd else None,
                input=input_data,
                capture_output=capture_output,
                text=True,
                timeout=self.limits.timeout_seconds,
            )

            execution_time = time.time() - start_time

            return SandboxResult(
                success=result.returncode == 0,
                return_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                execution_time=execution_time,
            )

        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            return SandboxResult(
                success=False,
                execution_time=execution_time,
                timed_out=True,
                violation=SandboxViolation.TIMEOUT,
                error_message=f"Timeout after {self.limits.timeout_seconds}s",
            )

        except Exception as e:
            execution_time = time.time() - start_time
            return SandboxResult(
                success=False,
                execution_time=execution_time,
                error_message=str(e),
            )

    def cleanup(self) -> None:
        """
        Cleanup sandbox resources.
        """
        if self._isolator:
            self._isolator.terminate()
            self._isolator = None

        if self._jail:
            self._jail.cleanup()
            self._jail = None

        if self._temp_workspace:
            self._temp_workspace.cleanup()
            self._temp_workspace = None

    def get_stats(self) -> Dict[str, Any]:
        """
        Get sandbox statistics.

        Returns
        -------
        Dict[str, Any]
            Statistics dictionary.
        """
        stats = {
            "policy": self.policy.value,
            "workspace": str(self.workspace),
            "limits": self.limits.to_dict(),
            "allow_network": self.allow_network,
            "allowed_paths": [str(p) for p in self.allowed_paths],
            "platform": sys.platform,
        }

        if self._isolator:
            stats["resource_usage"] = self._isolator.get_resource_usage()

        return stats

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def __repr__(self) -> str:
        return f"<SandboxManager policy={self.policy.value} workspace={self.workspace}>"


class TempWorkspace:
    """
    Temporary workspace manager for sandboxed execution.

    Creates and manages a temporary directory that is automatically
    cleaned up when the workspace is destroyed.

    Parameters
    ----------
    prefix : str
        Prefix for temporary directory name.
    base_dir : Optional[Path]
        Base directory for temp workspace.
    cleanup_on_exit : bool
        Automatically cleanup on exit.

    Attributes
    ----------
    path : Path
        Workspace directory path.
    cleanup_on_exit : bool
        Cleanup flag.
    _created : bool
        Whether directory was created.

    Examples
    --------
    >>> with TempWorkspace(prefix="compile_") as ws:
    ...     print(f"Workspace: {ws.path}")
    ...     # Files created here will be cleaned up
    """

    def __init__(
        self,
        prefix: str = "sandbox_",
        base_dir: Optional[Path] = None,
        cleanup_on_exit: bool = True,
    ):
        self.prefix = prefix
        self.base_dir = base_dir
        self.cleanup_on_exit = cleanup_on_exit
        self.path: Path = self._create()
        self._created = True

    def _create(self) -> Path:
        """
        Create temporary workspace directory.

        Returns
        -------
        Path
            Created directory path.
        """
        if self.base_dir:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            return Path(tempfile.mkdtemp(prefix=self.prefix, dir=str(self.base_dir)))
        else:
            return Path(tempfile.mkdtemp(prefix=self.prefix))

    def cleanup(self) -> None:
        """
        Clean up workspace directory.
        """
        if self._created and self.path.exists():
            try:
                shutil.rmtree(self.path, ignore_errors=True)
                self._created = False
            except (OSError, PermissionError):
                import logging
                logging.getLogger(__name__).warning(f"Failed to cleanup workspace: {self.path}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cleanup_on_exit:
            self.cleanup()

    def __repr__(self) -> str:
        return f"<TempWorkspace path={self.path}>"


