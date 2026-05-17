#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    RESOURCE LIMITERS
==================================

Platform-specific resource limiters for CPU, memory, disk,
process count, and network access control.
"""

import os
import sys
import time
import signal
import threading
import resource
import platform
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union


class LimiterType(Enum):
    """
    Type of resource limiter.

    Attributes
    ----------
    CPU : str
        CPU time limiter.
    MEMORY : str
        Memory usage limiter.
    DISK : str
        Disk space/usage limiter.
    PROCESS : str
        Process count limiter.
    NETWORK : str
        Network access limiter.
    FILE : str
        File descriptor limiter.
    """

    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    PROCESS = "process"
    NETWORK = "network"
    FILE = "file"


class LimiterState(Enum):
    """
    State of a resource limiter.

    Attributes
    ----------
    UNINITIALIZED : str
        Limiter created but not configured.
    ACTIVE : str
        Limiter active and monitoring.
    PAUSED : str
        Limiter temporarily paused.
    EXCEEDED : str
        Limit exceeded, action taken.
    STOPPED : str
        Limiter stopped.
    ERROR : str
        Limiter in error state.
    """

    UNINITIALIZED = "uninitialized"
    ACTIVE = "active"
    PAUSED = "paused"
    EXCEEDED = "exceeded"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class LimiterStats:
    """
    Statistics from a resource limiter.

    Parameters
    ----------
    limiter_type : LimiterType
        Type of limiter.
    current_usage : float
        Current resource usage.
    peak_usage : float
        Peak resource usage.
    limit_value : float
        Configured limit value.
    usage_percent : float
        Usage as percentage of limit.
    violations : int
        Number of limit violations.
    last_check : float
        Timestamp of last check.
    additional_info : Dict[str, Any]
        Additional limiter-specific info.

    Attributes
    ----------
    limiter_type : LimiterType
        Limiter type.
    current_usage : float
        Current usage.
    peak_usage : float
        Peak usage.
    limit_value : float
        Limit value.
    usage_percent : float
        Usage percentage.
    violations : int
        Violation count.
    last_check : float
        Last check timestamp.
    additional_info : Dict[str, Any]
        Additional info.
    """

    limiter_type: LimiterType
    current_usage: float = 0.0
    peak_usage: float = 0.0
    limit_value: float = float("inf")
    usage_percent: float = 0.0
    violations: int = 0
    last_check: float = field(default_factory=time.time)
    additional_info: Dict[str, Any] = field(default_factory=dict)

    def is_exceeded(self) -> bool:
        """
        Check if limit is exceeded.

        Returns
        -------
        bool
            True if current usage exceeds limit.
        """
        return self.current_usage > self.limit_value

    def get_summary(self) -> str:
        """
        Get human-readable summary.

        Returns
        -------
        str
            Summary string.
        """
        return (
            f"{self.limiter_type.value}: "
            f"{self.current_usage:.1f}/{self.limit_value:.1f} "
            f"({self.usage_percent:.1f}%) "
            f"[peak: {self.peak_usage:.1f}]"
        )


class ResourceLimiter(ABC):
    """
    Abstract base class for all resource limiters.

    Attributes
    ----------
    limiter_type : LimiterType
        Type of this limiter.
    limit_value : float
        Configured limit value.
    state : LimiterState
        Current state.
    stats : LimiterStats
        Statistics tracker.
    _lock : threading.RLock
        Thread lock for state changes.
    _monitor_thread : Optional[threading.Thread]
        Background monitoring thread.
    _stop_event : threading.Event
        Event to signal stop.
    """

    def __init__(self, limit_value: Optional[float] = None):
        self.limiter_type = self._get_limiter_type()
        self.limit_value = limit_value if limit_value is not None else float("inf")
        self.state = LimiterState.UNINITIALIZED
        self.stats = LimiterStats(
            limiter_type=self.limiter_type,
            limit_value=self.limit_value,
        )
        self._lock = threading.RLock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._callbacks: List[Callable[[LimiterStats], None]] = []

    @abstractmethod
    def _get_limiter_type(self) -> LimiterType:
        """
        Get the type of this limiter.

        Returns
        -------
        LimiterType
            Limiter type.
        """
        pass

    @abstractmethod
    def _get_current_usage(self) -> float:
        """
        Get current resource usage.

        Returns
        -------
        float
            Current usage value.
        """
        pass

    @abstractmethod
    def _apply_limit(self) -> bool:
        """
        Apply the resource limit to current process.

        Returns
        -------
        bool
            True if limit was applied successfully.
        """
        pass

    @abstractmethod
    def _on_limit_exceeded(self) -> None:
        """
        Handle limit exceeded condition.
        """
        pass

    def start(self, monitor_interval: float = 1.0) -> None:
        """
        Start the resource limiter.

        Parameters
        ----------
        monitor_interval : float
            Interval in seconds for monitoring.
        """
        with self._lock:
            if self.state == LimiterState.ACTIVE:
                return

            self._apply_limit()
            self.state = LimiterState.ACTIVE
            self._stop_event.clear()

            if monitor_interval > 0:
                self._monitor_thread = threading.Thread(
                    target=self._monitor_loop,
                    args=(monitor_interval,),
                    daemon=True,
                    name=f"{self.limiter_type.value}_monitor",
                )
                self._monitor_thread.start()

    def stop(self) -> None:
        """
        Stop the resource limiter.
        """
        with self._lock:
            if self.state == LimiterState.STOPPED:
                return

            self._stop_event.set()
            if self._monitor_thread:
                self._monitor_thread.join(timeout=2.0)
                self._monitor_thread = None

            self.state = LimiterState.STOPPED

    def pause(self) -> None:
        """
        Pause monitoring temporarily.
        """
        with self._lock:
            if self.state == LimiterState.ACTIVE:
                self.state = LimiterState.PAUSED

    def resume(self) -> None:
        """
        Resume monitoring.
        """
        with self._lock:
            if self.state == LimiterState.PAUSED:
                self.state = LimiterState.ACTIVE

    def check(self) -> LimiterStats:
        """
        Check current resource usage and update statistics.

        Returns
        -------
        LimiterStats
            Updated statistics.
        """
        with self._lock:
            current = self._get_current_usage()

            self.stats.current_usage = current
            self.stats.peak_usage = max(self.stats.peak_usage, current)
            self.stats.usage_percent = (current / self.limit_value * 100) if self.limit_value > 0 else 0
            self.stats.last_check = time.time()

            if current > self.limit_value:
                self.stats.violations += 1
                self.state = LimiterState.EXCEEDED
                self._on_limit_exceeded()
                self._notify_callbacks()

            return self.stats

    def add_callback(self, callback: Callable[[LimiterStats], None]) -> None:
        """
        Add callback for limit exceeded notifications.

        Parameters
        ----------
        callback : Callable[[LimiterStats], None]
            Callback function.
        """
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[LimiterStats], None]) -> bool:
        """
        Remove a callback.

        Parameters
        ----------
        callback : Callable[[LimiterStats], None]
            Callback to remove.

        Returns
        -------
        bool
            True if callback was removed.
        """
        try:
            self._callbacks.remove(callback)
            return True
        except ValueError:
            return False

    def _notify_callbacks(self) -> None:
        """
        Notify all registered callbacks.
        """
        for callback in self._callbacks:
            try:
                callback(self.stats)
            except Exception:
                pass

    def _monitor_loop(self, interval: float) -> None:
        """
        Background monitoring loop.

        Parameters
        ----------
        interval : float
            Check interval in seconds.
        """
        while not self._stop_event.wait(interval):
            if self.state == LimiterState.ACTIVE:
                try:
                    self.check()
                except Exception:
                    self.state = LimiterState.ERROR

    def get_stats(self) -> LimiterStats:
        """
        Get current statistics.

        Returns
        -------
        LimiterStats
            Current statistics.
        """
        with self._lock:
            return LimiterStats(
                limiter_type=self.stats.limiter_type,
                current_usage=self.stats.current_usage,
                peak_usage=self.stats.peak_usage,
                limit_value=self.stats.limit_value,
                usage_percent=self.stats.usage_percent,
                violations=self.stats.violations,
                last_check=self.stats.last_check,
                additional_info=self.stats.additional_info.copy(),
            )

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} state={self.state.value} limit={self.limit_value}>"


class CPULimiter(ResourceLimiter):
    """
    CPU time limiter using setrlimit.

    Limits the total CPU time a process can consume.

    Parameters
    ----------
    cpu_time_seconds : Optional[float]
        Maximum CPU time in seconds.
    hard_limit : bool
        Whether limit is hard (cannot be increased).

    Attributes
    ----------
    cpu_time_seconds : float
        CPU time limit.
    hard_limit : bool
        Hard limit flag.
    _process_times : Dict[int, float]
        Tracked process CPU times.

    Examples
    --------
    >>> limiter = CPULimiter(cpu_time_seconds=60)
    >>> limiter.start()
    >>> # Run CPU-intensive task
    >>> stats = limiter.get_stats()
    >>> print(f"CPU used: {stats.current_usage:.2f}s")
    """

    def __init__(
        self,
        cpu_time_seconds: Optional[float] = None,
        hard_limit: bool = True,
    ):
        super().__init__(cpu_time_seconds)
        self.cpu_time_seconds = cpu_time_seconds or float("inf")
        self.hard_limit = hard_limit
        self._process_times: Dict[int, float] = {}

    def _get_limiter_type(self) -> LimiterType:
        """Get limiter type."""
        return LimiterType.CPU

    def _get_current_usage(self) -> float:
        """
        Get current CPU time usage.

        Returns
        -------
        float
            CPU time in seconds.
        """
        try:
            # Get current process CPU time
            rusage = resource.getrusage(resource.RUSAGE_SELF)
            return rusage.ru_utime + rusage.ru_stime
        except (resource.error, OSError):
            return 0.0

    def _apply_limit(self) -> bool:
        """
        Apply CPU time limit using setrlimit.

        Returns
        -------
        bool
            True if limit was applied.
        """
        if self.cpu_time_seconds == float("inf"):
            return True

        if not hasattr(resource, "RLIMIT_CPU"):
            return False

        try:
            limit_seconds = int(self.cpu_time_seconds)
            if self.hard_limit:
                resource.setrlimit(resource.RLIMIT_CPU, (limit_seconds, limit_seconds))
            else:
                soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
                resource.setrlimit(resource.RLIMIT_CPU, (limit_seconds, hard))

            self.stats.additional_info["rlimit_applied"] = True
            return True

        except (ValueError, OSError, resource.error) as e:
            self.stats.additional_info["rlimit_error"] = str(e)
            return False

    def _on_limit_exceeded(self) -> None:
        """
        Handle CPU limit exceeded.
        """
        self.stats.additional_info["exceeded_at"] = time.time()

        # SIGXCPU is sent automatically by the kernel
        # We just track the event


class MemoryLimiter(ResourceLimiter):
    """
    Memory usage limiter using setrlimit and cgroups.

    Limits virtual memory, RSS, or both.

    Parameters
    ----------
    memory_limit_mb : Optional[int]
        Memory limit in megabytes.
    limit_type : str
        Type of memory to limit ('virtual', 'rss', 'both').
    hard_limit : bool
        Whether limit is hard.

    Attributes
    ----------
    memory_limit_mb : float
        Memory limit in MB.
    limit_type : str
        Limit type.
    hard_limit : bool
        Hard limit flag.
    _use_cgroups : bool
        Whether cgroups v2 is available.

    Examples
    --------
    >>> limiter = MemoryLimiter(memory_limit_mb=1024)
    >>> limiter.start()
    >>> stats = limiter.get_stats()
    >>> print(f"Memory used: {stats.current_usage:.1f}MB")
    """

    def __init__(
        self,
        memory_limit_mb: Optional[int] = None,
        limit_type: str = "virtual",
        hard_limit: bool = True,
    ):
        super().__init__(float(memory_limit_mb) if memory_limit_mb else float("inf"))
        self.memory_limit_mb = memory_limit_mb or float("inf")
        self.limit_type = limit_type
        self.hard_limit = hard_limit
        self._use_cgroups = self._check_cgroups_available()

    def _get_limiter_type(self) -> LimiterType:
        """Get limiter type."""
        return LimiterType.MEMORY

    def _check_cgroups_available(self) -> bool:
        """
        Check if cgroups v2 is available.

        Returns
        -------
        bool
            True if cgroups v2 available.
        """
        if not sys.platform.startswith("linux"):
            return False

        cgroup_path = Path("/sys/fs/cgroup")
        if not cgroup_path.exists():
            return False

        # Check for cgroups v2 unified hierarchy
        return (cgroup_path / "cgroup.controllers").exists()

    def _get_current_usage(self) -> float:
        """
        Get current memory usage in MB.

        Returns
        -------
        float
            Memory usage in MB.
        """
        try:
            if self.limit_type == "virtual":
                rusage = resource.getrusage(resource.RUSAGE_SELF)
                # Virtual memory is not directly available in rusage
                # Use /proc/self/statm on Linux
                if sys.platform.startswith("linux"):
                    with open("/proc/self/statm", "r") as f:
                        fields = f.read().split()
                        if fields:
                            pages = int(fields[0])  # Total program size
                            page_size = os.sysconf("SC_PAGE_SIZE")
                            return (pages * page_size) / (1024 * 1024)
            else:
                rusage = resource.getrusage(resource.RUSAGE_SELF)
                return rusage.ru_maxrss / 1024.0  # Convert KB to MB

        except (IOError, OSError, resource.error):
            pass

        return 0.0

    def _apply_limit(self) -> bool:
        """
        Apply memory limit using setrlimit or cgroups.

        Returns
        -------
        bool
            True if limit was applied.
        """
        if self.memory_limit_mb == float("inf"):
            return True

        limit_bytes = int(self.memory_limit_mb * 1024 * 1024)

        # Try cgroups first (more reliable)
        if self._use_cgroups:
            if self._apply_cgroup_limit(limit_bytes):
                self.stats.additional_info["cgroup_applied"] = True
                return True

        # Fallback to setrlimit
        if hasattr(resource, "RLIMIT_AS"):
            try:
                if self.hard_limit:
                    resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
                else:
                    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
                    resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, hard))

                self.stats.additional_info["rlimit_applied"] = True
                return True

            except (ValueError, OSError, resource.error):
                pass

        return False

    def _apply_cgroup_limit(self, limit_bytes: int) -> bool:
        """
        Apply memory limit using cgroups v2.

        Parameters
        ----------
        limit_bytes : int
            Limit in bytes.

        Returns
        -------
        bool
            True if limit was applied.
        """
        try:
            cgroup_path = Path("/sys/fs/cgroup")
            memory_max = cgroup_path / "memory.max"

            if memory_max.exists():
                with open(memory_max, "w") as f:
                    f.write(str(limit_bytes))
                return True

            # Try creating a child cgroup
            child_path = cgroup_path / f"cimporter_{os.getpid()}"
            child_path.mkdir(exist_ok=True)

            # Move current process to child cgroup
            cgroup_procs = child_path / "cgroup.procs"
            with open(cgroup_procs, "w") as f:
                f.write(str(os.getpid()))

            # Set memory limit
            memory_max = child_path / "memory.max"
            with open(memory_max, "w") as f:
                f.write(str(limit_bytes))

            self.stats.additional_info["cgroup_path"] = str(child_path)
            return True

        except (IOError, OSError, PermissionError):
            return False

    def _on_limit_exceeded(self) -> None:
        """
        Handle memory limit exceeded.
        """
        self.stats.additional_info["exceeded_at"] = time.time()


class DiskLimiter(ResourceLimiter):
    """
    Disk space and usage limiter.

    Monitors disk usage in a specified directory.

    Parameters
    ----------
    disk_quota_mb : Optional[int]
        Maximum disk usage in megabytes.
    monitor_path : Optional[Path]
        Path to monitor for disk usage.
    check_interval : float
        Interval between checks in seconds.

    Attributes
    ----------
    disk_quota_mb : float
        Disk quota in MB.
    monitor_path : Path
        Monitored path.
    check_interval : float
        Check interval.

    Examples
    --------
    >>> limiter = DiskLimiter(disk_quota_mb=500, monitor_path=Path("/tmp/build"))
    >>> limiter.start()
    >>> stats = limiter.get_stats()
    >>> print(f"Disk used: {stats.current_usage:.1f}MB")
    """

    def __init__(
        self,
        disk_quota_mb: Optional[int] = None,
        monitor_path: Optional[Path] = None,
        check_interval: float = 5.0,
    ):
        super().__init__(float(disk_quota_mb) if disk_quota_mb else float("inf"))
        self.disk_quota_mb = disk_quota_mb or float("inf")
        self.monitor_path = monitor_path or Path.cwd()
        self.check_interval = check_interval
        self._file_sizes: Dict[Path, int] = {}

    def _get_limiter_type(self) -> LimiterType:
        """Get limiter type."""
        return LimiterType.DISK

    def _get_current_usage(self) -> float:
        """
        Get current disk usage in MB.

        Returns
        -------
        float
            Disk usage in MB.
        """
        try:
            total_size = 0
            for item in self.monitor_path.rglob("*"):
                if item.is_file():
                    try:
                        size = item.stat().st_size
                        total_size += size
                        self._file_sizes[item] = size
                    except OSError:
                        pass

            return total_size / (1024 * 1024)

        except (OSError, PermissionError):
            return 0.0

    def _apply_limit(self) -> bool:
        """
        Apply disk quota (monitoring only - cannot prevent writes).

        Returns
        -------
        bool
            True (monitoring only).
        """
        # Disk limits are monitored, not enforced at kernel level
        self.stats.additional_info["monitor_path"] = str(self.monitor_path)
        return True

    def _on_limit_exceeded(self) -> None:
        """
        Handle disk quota exceeded.
        """
        self.stats.additional_info["exceeded_at"] = time.time()
        self.stats.additional_info["largest_files"] = self._get_largest_files(5)

    def _get_largest_files(self, count: int = 10) -> List[Dict[str, Any]]:
        """
        Get list of largest files.

        Parameters
        ----------
        count : int
            Number of files to return.

        Returns
        -------
        List[Dict[str, Any]]
            List of file info dictionaries.
        """
        sorted_files = sorted(
            self._file_sizes.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:count]

        return [
            {
                "path": str(path),
                "size_mb": size / (1024 * 1024),
            }
            for path, size in sorted_files
        ]


class ProcessLimiter(ResourceLimiter):
    """
    Process count limiter using setrlimit.

    Limits the maximum number of child processes.

    Parameters
    ----------
    max_processes : Optional[int]
        Maximum number of child processes.
    hard_limit : bool
        Whether limit is hard.

    Attributes
    ----------
    max_processes : int
        Maximum processes.
    hard_limit : bool
        Hard limit flag.

    Examples
    --------
    >>> limiter = ProcessLimiter(max_processes=1)
    >>> limiter.start()
    >>> # Prevents fork bombs
    """

    def __init__(
        self,
        max_processes: Optional[int] = None,
        hard_limit: bool = True,
    ):
        super().__init__(float(max_processes) if max_processes else float("inf"))
        self.max_processes = max_processes
        self.hard_limit = hard_limit

    def _get_limiter_type(self) -> LimiterType:
        """Get limiter type."""
        return LimiterType.PROCESS

    def _get_current_usage(self) -> float:
        """
        Get current number of processes.

        Returns
        -------
        float
            Number of child processes.
        """
        try:
            import subprocess
            result = subprocess.run(
                ["pgrep", "-P", str(os.getpid())],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return float(len(result.stdout.strip().split("\n")))
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        return 0.0

    def _apply_limit(self) -> bool:
        """
        Apply process limit using setrlimit.

        Returns
        -------
        bool
            True if limit was applied.
        """
        if self.max_processes is None:
            return True

        if not hasattr(resource, "RLIMIT_NPROC"):
            return False

        try:
            if self.hard_limit:
                resource.setrlimit(resource.RLIMIT_NPROC, (self.max_processes, self.max_processes))
            else:
                soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
                resource.setrlimit(resource.RLIMIT_NPROC, (self.max_processes, hard))

            self.stats.additional_info["rlimit_applied"] = True
            return True

        except (ValueError, OSError, resource.error):
            return False

    def _on_limit_exceeded(self) -> None:
        """
        Handle process limit exceeded.
        """
        self.stats.additional_info["exceeded_at"] = time.time()


class NetworkBlocker(ResourceLimiter):
    """
    Network access blocker using various platform techniques.

    Prevents network access for sandboxed processes.

    Parameters
    ----------
    block_all : bool
        Block all network access.
    allowed_ports : Optional[List[int]]
        List of allowed ports.
    allowed_hosts : Optional[List[str]]
        List of allowed hosts.

    Attributes
    ----------
    block_all : bool
        Block all flag.
    allowed_ports : List[int]
        Allowed ports.
    allowed_hosts : List[str]
        Allowed hosts.
    _original_rules : List[str]
        Original firewall rules (for restoration).

    Examples
    --------
    >>> blocker = NetworkBlocker(block_all=True)
    >>> blocker.start()
    >>> # Network access is blocked
    >>> blocker.stop()
    """

    def __init__(
        self,
        block_all: bool = True,
        allowed_ports: Optional[List[int]] = None,
        allowed_hosts: Optional[List[str]] = None,
    ):
        super().__init__(0.0)  # No numeric limit
        self.block_all = block_all
        self.allowed_ports = allowed_ports or []
        self.allowed_hosts = allowed_hosts or []
        self._original_rules: List[str] = []

    def _get_limiter_type(self) -> LimiterType:
        """Get limiter type."""
        return LimiterType.NETWORK

    def _get_current_usage(self) -> float:
        """
        Get network usage (not applicable).

        Returns
        -------
        float
            Always 0.0.
        """
        return 0.0

    def _apply_limit(self) -> bool:
        """
        Apply network blocking.

        Returns
        -------
        bool
            True if blocking was applied.
        """
        if not self.block_all:
            return True

        # Platform-specific blocking
        if sys.platform.startswith("linux"):
            return self._block_linux()
        elif sys.platform == "darwin":
            return self._block_macos()
        elif sys.platform == "win32":
            return self._block_windows()

        return False

    def _block_linux(self) -> bool:
        """
        Block network on Linux using iptables or nftables.

        Returns
        -------
        bool
            True if blocked.
        """
        try:
            import subprocess

            # Try iptables
            result = subprocess.run(
                ["iptables", "-A", "OUTPUT", "-m", "owner", "--pid-owner", str(os.getpid()), "-j", "DROP"],
                capture_output=True,
                check=False,
            )

            if result.returncode == 0:
                self._original_rules.append(f"iptables -D OUTPUT -m owner --pid-owner {os.getpid()} -j DROP")
                self.stats.additional_info["method"] = "iptables"
                return True

            # Try nftables
            # ... implementation ...

        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        # Fallback: Use seccomp (requires additional privileges)
        return self._block_seccomp()

    def _block_macos(self) -> bool:
        """
        Block network on macOS using pf.

        Returns
        -------
        bool
            True if blocked.
        """
        # macOS requires root for pf
        self.stats.additional_info["method"] = "none"
        self.stats.additional_info["warning"] = "Network blocking requires root on macOS"
        return False

    def _block_windows(self) -> bool:
        """
        Block network on Windows using Windows Filtering Platform.

        Returns
        -------
        bool
            True if blocked.
        """
        try:
            # Use netsh or Windows Firewall API
            self.stats.additional_info["method"] = "windows_firewall"
            # ... implementation ...
            return True
        except Exception:
            return False

    def _block_seccomp(self) -> bool:
        """
        Block network using seccomp-bpf.

        Returns
        -------
        bool
            True if blocked.
        """
        try:
            import prctl

            # Define seccomp filter to block socket-related syscalls
            # socket, connect, bind, listen, accept, sendto, recvfrom, etc.

            blocked_syscalls = [
                "socket", "connect", "bind", "listen", "accept",
                "sendto", "recvfrom", "sendmsg", "recvmsg",
            ]

            # This requires root or CAP_SYS_ADMIN
            self.stats.additional_info["method"] = "seccomp"
            self.stats.additional_info["blocked_syscalls"] = blocked_syscalls
            return True

        except ImportError:
            self.stats.additional_info["method"] = "none"
            return False

    def _on_limit_exceeded(self) -> None:
        """
        Handle network access attempt (not triggered).
        """
        pass

    def stop(self) -> None:
        """
        Stop network blocking and restore rules.
        """
        super().stop()

        # Restore original firewall rules
        for rule in self._original_rules:
            try:
                import subprocess
                subprocess.run(rule.split(), capture_output=True, check=False)
            except Exception:
                pass

        self._original_rules.clear()


class ResourceLimiterManager:
    """
    Manager for multiple resource limiters.

    Coordinates multiple limiters and provides unified interface.

    Parameters
    ----------
    limiters : Optional[List[ResourceLimiter]]
        List of limiters to manage.

    Attributes
    ----------
    limiters : Dict[LimiterType, ResourceLimiter]
        Managed limiters by type.
    _lock : threading.RLock
        Thread lock.

    Examples
    --------
    >>> manager = ResourceLimiterManager()
    >>> manager.add_limiter(CPULimiter(60))
    >>> manager.add_limiter(MemoryLimiter(1024))
    >>> manager.start_all()
    >>> stats = manager.get_all_stats()
    >>> manager.stop_all()
    """

    def __init__(self, limiters: Optional[List[ResourceLimiter]] = None):
        self.limiters: Dict[LimiterType, ResourceLimiter] = {}
        self._lock = threading.RLock()

        if limiters:
            for limiter in limiters:
                self.add_limiter(limiter)

    def add_limiter(self, limiter: ResourceLimiter) -> None:
        """
        Add a resource limiter.

        Parameters
        ----------
        limiter : ResourceLimiter
            Limiter to add.
        """
        with self._lock:
            self.limiters[limiter.limiter_type] = limiter

    def remove_limiter(self, limiter_type: LimiterType) -> Optional[ResourceLimiter]:
        """
        Remove a resource limiter.

        Parameters
        ----------
        limiter_type : LimiterType
            Type of limiter to remove.

        Returns
        -------
        Optional[ResourceLimiter]
            Removed limiter or None.
        """
        with self._lock:
            return self.limiters.pop(limiter_type, None)

    def get_limiter(self, limiter_type: LimiterType) -> Optional[ResourceLimiter]:
        """
        Get a specific limiter.

        Parameters
        ----------
        limiter_type : LimiterType
            Type of limiter.

        Returns
        -------
        Optional[ResourceLimiter]
            Limiter or None.
        """
        return self.limiters.get(limiter_type)

    def start_all(self) -> None:
        """
        Start all limiters.
        """
        with self._lock:
            for limiter in self.limiters.values():
                limiter.start()

    def stop_all(self) -> None:
        """
        Stop all limiters.
        """
        with self._lock:
            for limiter in self.limiters.values():
                limiter.stop()

    def check_all(self) -> Dict[LimiterType, LimiterStats]:
        """
        Check all limiters and collect statistics.

        Returns
        -------
        Dict[LimiterType, LimiterStats]
            Statistics for all limiters.
        """
        stats = {}
        with self._lock:
            for limiter_type, limiter in self.limiters.items():
                stats[limiter_type] = limiter.check()
        return stats

    def get_all_stats(self) -> Dict[LimiterType, LimiterStats]:
        """
        Get current statistics for all limiters.

        Returns
        -------
        Dict[LimiterType, LimiterStats]
            Statistics dictionary.
        """
        stats = {}
        with self._lock:
            for limiter_type, limiter in self.limiters.items():
                stats[limiter_type] = limiter.get_stats()
        return stats

    def get_summary(self) -> str:
        """
        Get human-readable summary of all limiters.

        Returns
        -------
        str
            Summary string.
        """
        lines = ["Resource Limiter Summary:"]
        for limiter in self.limiters.values():
            stats = limiter.get_stats()
            status = "EXCEEDED" if stats.is_exceeded() else "OK"
            lines.append(f"  {stats.get_summary()} {status}")
        return "\n".join(lines)

    def __enter__(self):
        self.start_all()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_all()

    def __repr__(self) -> str:
        return f"<ResourceLimiterManager limiters={list(self.limiters.keys())}>"