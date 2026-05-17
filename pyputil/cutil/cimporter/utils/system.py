#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    SYSTEM UTILITIES
==================================

Cross-platform system utilities for process execution, environment
management, resource monitoring, and system information.

This module provides comprehensive system-level operations:
- Process execution with timeout and output capture
- Synchronous and asynchronous command execution
- Environment variable management
- System resource monitoring (CPU, memory, disk)
- Process management (PID, parent, kill, check)
- Signal handling and process groups
- Temporary file and directory creation
- Path and executable searching
"""

import os
import sys
import time
import signal
import shutil
import shlex
import subprocess
import threading
import tempfile
import platform
import errno
import stat
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import (
    Any, Callable, Dict, Iterator, List, Optional, 
    Tuple, Union, IO, TextIO, BinaryIO
)
from concurrent.futures import ThreadPoolExecutor, Future
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# Platform Detection (Internal)
# ============================================================================

def _is_windows() -> bool:
    """Check if running on Windows."""
    return sys.platform == "win32"


def _is_linux() -> bool:
    """Check if running on Linux."""
    return sys.platform.startswith("linux")


def _is_macos() -> bool:
    """Check if running on macOS."""
    return sys.platform == "darwin"


def _is_unix() -> bool:
    """Check if running on Unix-like system."""
    return not _is_windows()


# ============================================================================
# Command Result
# ============================================================================

@dataclass
class CommandResult:
    """
    Result of a command execution.
    
    This dataclass contains comprehensive information about a completed
    command execution, including exit code, output, timing, and error details.
    
    Attributes
    ----------
    command : List[str]
        The command that was executed.
    return_code : int
        Process exit code (0 for success, non-zero for failure).
    stdout : str
        Standard output captured from the process.
    stderr : str
        Standard error captured from the process.
    execution_time : float
        Wall-clock execution time in seconds.
    cpu_time : float
        CPU time used in seconds (if available).
    memory_used_mb : float
        Peak memory used in megabytes (if available).
    success : bool
        True if return_code == 0.
    timed_out : bool
        True if execution exceeded timeout.
    killed : bool
        True if process was killed by signal.
    signal_received : Optional[int]
        Signal number that terminated the process (if killed).
    error : Optional[Exception]
        Exception that occurred during execution (if any).
    start_time : float
        Unix timestamp when command started.
    end_time : float
        Unix timestamp when command completed.
    working_directory : Optional[Path]
        Working directory used for execution.
    environment : Optional[Dict[str, str]]
        Environment variables used.
    pid : Optional[int]
        Process ID of the executed command.
    
    Examples
    --------
    >>> result = run_command(["gcc", "--version"])
    >>> if result.success:
    ...     print(f"GCC version: {result.stdout.split()[2]}")
    ...     print(f"Executed in {result.execution_time:.3f}s")
    >>> else:
    ...     print(f"Error: {result.stderr}")
    """
    
    command: List[str]
    return_code: int
    stdout: str = ""
    stderr: str = ""
    execution_time: float = 0.0
    cpu_time: float = 0.0
    memory_used_mb: float = 0.0
    success: bool = False
    timed_out: bool = False
    killed: bool = False
    signal_received: Optional[int] = None
    error: Optional[Exception] = None
    start_time: float = field(default_factory=time.time)
    end_time: float = field(default_factory=time.time)
    working_directory: Optional[Path] = None
    environment: Optional[Dict[str, str]] = None
    pid: Optional[int] = None
    
    def __post_init__(self):
        """Initialize computed fields after dataclass creation."""
        self.success = self.return_code == 0 and not self.timed_out and not self.killed and self.error is None
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert result to dictionary for serialization.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "command": self.command,
            "return_code": self.return_code,
            "stdout": self.stdout[:1000] if len(self.stdout) > 1000 else self.stdout,
            "stderr": self.stderr[:1000] if len(self.stderr) > 1000 else self.stderr,
            "execution_time": self.execution_time,
            "cpu_time": self.cpu_time,
            "memory_used_mb": self.memory_used_mb,
            "success": self.success,
            "timed_out": self.timed_out,
            "killed": self.killed,
            "signal_received": self.signal_received,
            "error": str(self.error) if self.error else None,
            "pid": self.pid,
            "working_directory": str(self.working_directory) if self.working_directory else None,
        }
    
    def get_summary(self) -> str:
        """
        Get human-readable summary of execution.
        
        Returns
        -------
        str
            Summary string.
        """
        if self.success:
            return f"SUCCESS (code={self.return_code}) in {self.execution_time:.3f}s"
        elif self.timed_out:
            return f"TIMEOUT after {self.execution_time:.3f}s"
        elif self.killed:
            sig_name = signal.Signals(self.signal_received).name if self.signal_received else "UNKNOWN"
            return f"KILLED by {sig_name}"
        elif self.error:
            return f"ERROR: {self.error}"
        else:
            return f"FAILED (code={self.return_code})"
    
    def __str__(self) -> str:
        """String representation."""
        return self.get_summary()


# ============================================================================
# Command Error
# ============================================================================

class CommandError(Exception):
    """
    Exception raised when command execution fails.
    
    This exception provides detailed information about command failures,
    including the command that failed, exit code, and output.
    
    Attributes
    ----------
    command : List[str]
        The command that was executed.
    return_code : int
        Process exit code.
    stdout : str
        Standard output captured.
    stderr : str
        Standard error captured.
    result : Optional[CommandResult]
        Full command result if available.
    
    Examples
    --------
    >>> try:
    ...     run_command(["gcc", "nonexistent.c"], check=True)
    ... except CommandError as e:
    ...     print(f"Command failed: {e.command}")
    ...     print(f"Error: {e.stderr}")
    """
    
    def __init__(
        self,
        message: str,
        command: List[str],
        return_code: Optional[int] = None,
        stdout: str = "",
        stderr: str = "",
        result: Optional[CommandResult] = None,
    ):
        self.command = command
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr
        self.result = result
        
        full_message = f"{message}: {' '.join(command)}"
        if return_code is not None:
            full_message += f" (exit code: {return_code})"
        if stderr:
            full_message += f"\nStderr: {stderr[:500]}"
        
        super().__init__(full_message)


class TimeoutError(CommandError):
    """
    Exception raised when command execution exceeds timeout.
    
    Attributes
    ----------
    timeout : float
        Timeout value in seconds.
    elapsed : float
        Actual elapsed time.
    """
    
    def __init__(self, command: List[str], timeout: float, elapsed: float):
        self.timeout = timeout
        self.elapsed = elapsed
        
        super().__init__(
            message=f"Command timed out after {elapsed:.2f}s (limit: {timeout}s)",
            command=command,
        )


# ============================================================================
# Core Execution Functions
# ============================================================================

def run_command(
    command: Union[str, List[str]],
    *,
    capture_output: bool = True,
    text: bool = True,
    check: bool = False,
    timeout: Optional[float] = None,
    cwd: Optional[Union[str, Path]] = None,
    env: Optional[Dict[str, str]] = None,
    shell: bool = False,
    input_data: Optional[str] = None,
    executable: Optional[Union[str, Path]] = None,
    encoding: str = "utf-8",
    errors: str = "replace",
    raise_on_error: bool = False,
) -> CommandResult:
    """
    Run a command and return comprehensive execution results.
    
    This is the primary function for executing system commands with
    full control over input/output, timeout, and environment.
    
    Parameters
    ----------
    command : Union[str, List[str]]
        Command to execute. If string and shell=False, it will be split
        using shlex.split(). If shell=True, passed directly to shell.
    capture_output : bool
        Capture stdout and stderr (default: True).
    text : bool
        Return output as string instead of bytes (default: True).
    check : bool
        Raise CommandError on non-zero exit (default: False).
    timeout : Optional[float]
        Maximum execution time in seconds. None for no limit.
    cwd : Optional[Union[str, Path]]
        Working directory for the command.
    env : Optional[Dict[str, str]]
        Environment variables. If None, inherits from parent.
    shell : bool
        Execute through shell (default: False).
    input_data : Optional[str]
        Data to send to stdin.
    executable : Optional[Union[str, Path]]
        Override the executable to run.
    encoding : str
        Encoding for text output (default: utf-8).
    errors : str
        Error handling for encoding (default: replace).
    raise_on_error : bool
        Alias for check (for backward compatibility).
        
    Returns
    -------
    CommandResult
        Comprehensive result object with all execution details.
        
    Raises
    ------
    CommandError
        If check=True and command fails, or if timeout occurs.
        
    Examples
    --------
    >>> # Simple command
    >>> result = run_command(["gcc", "--version"])
    >>> print(result.stdout)
    >>> 
    >>> # With timeout and error checking
    >>> result = run_command(
    ...     ["make", "-j4"],
    ...     cwd=Path("build"),
    ...     timeout=300,
    ...     check=True,
    ... )
    >>> 
    >>> # With input data
    >>> result = run_command(
    ...     ["python", "-c", "print(input().upper())"],
    ...     input_data="hello world",
    ... )
    >>> print(result.stdout)  # HELLO WORLD
    >>> 
    >>> # Shell command
    >>> result = run_command(
    ...     "echo $HOME",
    ...     shell=True,
    ...     capture_output=True,
    ... )
    """
    start_time = time.time()
    
    # Prepare command
    if isinstance(command, str):
        if shell:
            cmd_list = command
        else:
            cmd_list = shlex.split(command)
    else:
        cmd_list = command
        if shell:
            cmd_list = " ".join(shlex.quote(arg) for arg in cmd_list)
    
    # Prepare working directory
    work_dir = str(cwd) if cwd else None
    
    # Prepare environment
    process_env = None
    if env is not None:
        process_env = os.environ.copy()
        process_env.update(env)
    
    # Prepare stdin
    stdin_data = None
    if input_data is not None:
        stdin_data = subprocess.PIPE
    
    result = CommandResult(
        command=cmd_list if isinstance(cmd_list, list) else [cmd_list],
        return_code=-1,
        working_directory=Path(work_dir) if work_dir else None,
        environment=env,
        start_time=start_time,
    )
    
    try:
        # Execute command
        if shell:
            # Shell execution
            process = subprocess.Popen(
                cmd_list,
                cwd=work_dir,
                env=process_env,
                stdin=stdin_data,
                stdout=subprocess.PIPE if capture_output else None,
                stderr=subprocess.PIPE if capture_output else None,
                text=text,
                encoding=encoding if text else None,
                errors=errors if text else None,
                shell=True,
                executable=executable,
                universal_newlines=text,
            )
        else:
            # Direct execution
            process = subprocess.Popen(
                cmd_list,
                cwd=work_dir,
                env=process_env,
                stdin=stdin_data,
                stdout=subprocess.PIPE if capture_output else None,
                stderr=subprocess.PIPE if capture_output else None,
                text=text,
                encoding=encoding if text else None,
                errors=errors if text else None,
                executable=executable,
                universal_newlines=text,
            )
        
        result.pid = process.pid
        
        # Wait for completion with timeout
        try:
            stdout_data, stderr_data = process.communicate(
                input=input_data,
                timeout=timeout,
            )
            
            result.return_code = process.returncode
            result.stdout = stdout_data if stdout_data else ""
            result.stderr = stderr_data if stderr_data else ""
            
        except subprocess.TimeoutExpired as e:
            result.timed_out = True
            result.execution_time = time.time() - start_time
            result.end_time = time.time()
            
            # Try to terminate gracefully
            try:
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            
            # Capture any output
            if capture_output:
                result.stdout, result.stderr = process.communicate()
            
            if check or raise_on_error:
                raise TimeoutError(
                    command=cmd_list if isinstance(cmd_list, list) else [cmd_list],
                    timeout=timeout,
                    elapsed=result.execution_time,
                )
            
            return result
        
        result.execution_time = time.time() - start_time
        result.end_time = time.time()
        
        # Get resource usage if available
        if _is_unix():
            try:
                import resource
                rusage = resource.getrusage(resource.RUSAGE_CHILDREN)
                result.cpu_time = rusage.ru_utime + rusage.ru_stime
                result.memory_used_mb = rusage.ru_maxrss / 1024.0
            except (ImportError, AttributeError):
                pass
        
        # Check for non-zero exit code
        if result.return_code != 0:
            if check or raise_on_error:
                raise CommandError(
                    message="Command failed",
                    command=cmd_list if isinstance(cmd_list, list) else [cmd_list],
                    return_code=result.return_code,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    result=result,
                )
        
        # Check if killed by signal
        if result.return_code < 0:
            result.killed = True
            result.signal_received = -result.return_code
        
        return result
        
    except Exception as e:
        result.execution_time = time.time() - start_time
        result.end_time = time.time()
        result.error = e
        
        if check or raise_on_error:
            if not isinstance(e, CommandError):
                raise CommandError(
                    message=f"Command execution error: {e}",
                    command=cmd_list if isinstance(cmd_list, list) else [cmd_list],
                    result=result,
                ) from e
            raise
        
        return result


def run_command_sync(
    command: Union[str, List[str]],
    **kwargs,
) -> CommandResult:
    """
    Alias for run_command - synchronous execution.
    
    Parameters
    ----------
    command : Union[str, List[str]]
        Command to execute.
    **kwargs : Any
        Additional arguments passed to run_command.
        
    Returns
    -------
    CommandResult
        Command execution result.
    """
    return run_command(command, **kwargs)


def run_command_async(
    command: Union[str, List[str]],
    *,
    callback: Optional[Callable[[CommandResult], None]] = None,
    **kwargs,
) -> Future:
    """
    Run a command asynchronously in a background thread.
    
    This function executes the command in a separate thread and returns
    a Future that can be used to retrieve the result.
    
    Parameters
    ----------
    command : Union[str, List[str]]
        Command to execute.
    callback : Optional[Callable[[CommandResult], None]]
        Optional callback function called when command completes.
    **kwargs : Any
        Additional arguments passed to run_command.
        
    Returns
    -------
    Future
        Future object that will contain the CommandResult.
        
    Examples
    --------
    >>> # Async execution
    >>> future = run_command_async(["make", "-j8"])
    >>> 
    >>> # Do other work while command runs
    >>> time.sleep(1)
    >>> print("Still working...")
    >>> 
    >>> # Wait for result
    >>> result = future.result(timeout=300)
    >>> print(f"Build completed: {result.success}")
    >>> 
    >>> # With callback
    >>> def on_complete(result):
    ...     print(f"Command finished: {result.get_summary()}")
    >>> 
    >>> future = run_command_async(
    ...     ["gcc", "source.c"],
    ...     callback=on_complete,
    ... )
    """
    executor = ThreadPoolExecutor(max_workers=1)
    
    def _run() -> CommandResult:
        """Run the command in thread."""
        result = run_command(command, **kwargs)
        if callback:
            try:
                callback(result)
            except Exception as e:
                logger.error(f"Async command callback error: {e}")
        return result
    
    future = executor.submit(_run)
    
    # Clean up executor after completion
    def _cleanup(f: Future) -> None:
        executor.shutdown(wait=False)
    
    future.add_done_callback(_cleanup)
    
    return future


def run_commands_parallel(
    commands: List[Union[str, List[str]]],
    *,
    max_workers: Optional[int] = None,
    continue_on_error: bool = True,
    **kwargs,
) -> Dict[int, CommandResult]:
    """
    Run multiple commands in parallel.
    
    Parameters
    ----------
    commands : List[Union[str, List[str]]]
        List of commands to execute.
    max_workers : Optional[int]
        Maximum number of worker threads.
    continue_on_error : bool
        Continue executing remaining commands if one fails.
    **kwargs : Any
        Additional arguments passed to each run_command call.
        
    Returns
    -------
    Dict[int, CommandResult]
        Dictionary mapping command index to result.
        
    Examples
    --------
    >>> commands = [
    ...     ["gcc", "-c", "file1.c"],
    ...     ["gcc", "-c", "file2.c"],
    ...     ["gcc", "-c", "file3.c"],
    ... ]
    >>> results = run_commands_parallel(commands, max_workers=4)
    >>> for i, result in results.items():
    ...     print(f"Command {i}: {result.get_summary()}")
    """
    results: Dict[int, CommandResult] = {}
    
    max_workers = max_workers or min(len(commands), os.cpu_count() or 4)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures: Dict[Future, int] = {}
        
        for i, cmd in enumerate(commands):
            future = executor.submit(run_command, cmd, **kwargs)
            futures[future] = i
        
        for future in futures:
            index = futures[future]
            try:
                result = future.result()
                results[index] = result
            except Exception as e:
                if not continue_on_error:
                    # Cancel remaining futures
                    for f in futures:
                        f.cancel()
                    raise
                
                # Create error result
                cmd = commands[index]
                cmd_list = cmd if isinstance(cmd, list) else [cmd]
                results[index] = CommandResult(
                    command=cmd_list,
                    return_code=-1,
                    error=e,
                    success=False,
                )
    
    return results


# ============================================================================
# Environment Variables
# ============================================================================

def get_environment() -> Dict[str, str]:
    """
    Get a copy of the current environment variables.
    
    Returns
    -------
    Dict[str, str]
        Dictionary of environment variables.
        
    Examples
    --------
    >>> env = get_environment()
    >>> print(f"PATH: {env.get('PATH', 'not set')}")
    """
    return os.environ.copy()


def set_environment(
    variables: Dict[str, str],
    update: bool = True,
) -> None:
    """
    Set environment variables for the current process.
    
    Parameters
    ----------
    variables : Dict[str, str]
        Dictionary of variables to set.
    update : bool
        If True, update existing environment. If False, replace entirely.
        
    Examples
    --------
    >>> set_environment({"MY_VAR": "value"})
    >>> print(os.environ["MY_VAR"])
    value
    """
    if update:
        os.environ.update(variables)
    else:
        os.environ.clear()
        os.environ.update(variables)


def get_env(
    name: str,
    default: Optional[str] = None,
) -> Optional[str]:
    """
    Get an environment variable value.
    
    Parameters
    ----------
    name : str
        Variable name.
    default : Optional[str]
        Default value if not set.
        
    Returns
    -------
    Optional[str]
        Variable value or default.
        
    Examples
    --------
    >>> path = get_env("PATH")
    >>> custom = get_env("MY_CUSTOM_VAR", "default_value")
    """
    return os.environ.get(name, default)


def set_env(name: str, value: str) -> None:
    """
    Set an environment variable.
    
    Parameters
    ----------
    name : str
        Variable name.
    value : str
        Variable value.
        
    Examples
    --------
    >>> set_env("CC", "clang")
    >>> print(os.environ["CC"])
    clang
    """
    os.environ[name] = value


def unset_env(name: str) -> bool:
    """
    Unset (remove) an environment variable.
    
    Parameters
    ----------
    name : str
        Variable name.
        
    Returns
    -------
    bool
        True if variable was removed, False if it didn't exist.
        
    Examples
    --------
    >>> unset_env("TEMP_VAR")
    True
    """
    if name in os.environ:
        del os.environ[name]
        return True
    return False


def prepend_path(path: Union[str, Path]) -> None:
    """
    Prepend a directory to the PATH environment variable.
    
    Parameters
    ----------
    path : Union[str, Path]
        Directory to add to PATH.
        
    Examples
    --------
    >>> prepend_path("/usr/local/bin")
    >>> print(os.environ["PATH"])
    /usr/local/bin:/usr/bin:/bin
    """
    path_str = str(path)
    current_path = os.environ.get("PATH", "")
    
    if current_path:
        separator = ";" if _is_windows() else ":"
        paths = current_path.split(separator)
        
        # Remove if already present
        if path_str in paths:
            paths.remove(path_str)
        
        # Prepend
        paths.insert(0, path_str)
        os.environ["PATH"] = separator.join(paths)
    else:
        os.environ["PATH"] = path_str


def append_path(path: Union[str, Path]) -> None:
    """
    Append a directory to the PATH environment variable.
    
    Parameters
    ----------
    path : Union[str, Path]
        Directory to add to PATH.
        
    Examples
    --------
    >>> append_path("/opt/bin")
    """
    path_str = str(path)
    current_path = os.environ.get("PATH", "")
    
    if current_path:
        separator = ";" if _is_windows() else ":"
        paths = current_path.split(separator)
        
        # Remove if already present
        if path_str in paths:
            paths.remove(path_str)
        
        # Append
        paths.append(path_str)
        os.environ["PATH"] = separator.join(paths)
    else:
        os.environ["PATH"] = path_str


# ============================================================================
# System Resources
# ============================================================================

def get_cpu_count(logical: bool = True) -> int:
    """
    Get the number of CPU cores.
    
    Parameters
    ----------
    logical : bool
        If True, return logical cores (including hyperthreading).
        If False, return physical cores only.
        
    Returns
    -------
    int
        Number of CPU cores.
        
    Examples
    --------
    >>> logical = get_cpu_count()
    >>> physical = get_cpu_count(logical=False)
    >>> print(f"CPU cores: {physical} physical, {logical} logical")
    """
    if logical:
        return os.cpu_count() or 1
    
    # Try to get physical cores
    if _is_linux():
        try:
            with open("/proc/cpuinfo", "r") as f:
                content = f.read()
            
            # Count unique physical IDs
            physical_ids = set()
            for line in content.split("\n"):
                if line.startswith("physical id"):
                    physical_ids.add(line.split(":")[1].strip())
            
            if physical_ids:
                return len(physical_ids)
        except (IOError, OSError):
            pass
    elif _is_macos():
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.physicalcpu"],
                capture_output=True,
                text=True,
            )
            return int(result.stdout.strip())
        except (subprocess.SubprocessError, ValueError):
            pass
    elif _is_windows():
        try:
            import ctypes
            
            # This requires WMI for accurate count
            pass
        except ImportError:
            pass
    
    return os.cpu_count() or 1


def get_memory_info() -> Dict[str, int]:
    """
    Get system memory information.
    
    Returns
    -------
    Dict[str, int]
        Dictionary with keys:
        - total_bytes: Total physical memory
        - available_bytes: Available memory
        - used_bytes: Used memory
        - free_bytes: Free memory
        - total_mb, available_mb, used_mb, free_mb: Same in megabytes
        
    Examples
    --------
    >>> mem = get_memory_info()
    >>> print(f"Memory: {mem['used_mb']}MB / {mem['total_mb']}MB")
    >>> print(f"Available: {mem['available_mb']}MB")
    """
    info = {
        "total_bytes": 0,
        "available_bytes": 0,
        "used_bytes": 0,
        "free_bytes": 0,
    }
    
    if _is_linux():
        try:
            with open("/proc/meminfo", "r") as f:
                content = f.read()
            
            for line in content.split("\n"):
                if line.startswith("MemTotal:"):
                    info["total_bytes"] = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    info["available_bytes"] = int(line.split()[1]) * 1024
                elif line.startswith("MemFree:"):
                    info["free_bytes"] = int(line.split()[1]) * 1024
            
            info["used_bytes"] = info["total_bytes"] - info["available_bytes"]
            
        except (IOError, OSError, ValueError):
            pass
            
    elif _is_macos():
        try:
            # Total memory
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
            )
            info["total_bytes"] = int(result.stdout.strip())
            
            # Memory usage via vm_stat
            result = subprocess.run(
                ["vm_stat"],
                capture_output=True,
                text=True,
            )
            
            page_size = 4096
            for line in result.stdout.split("\n"):
                if "page size" in line.lower():
                    page_size = int(line.split(":")[1].strip())
                    break
            
            free_pages = 0
            for line in result.stdout.split("\n"):
                if "Pages free" in line:
                    free_pages = int(line.split(":")[1].strip().rstrip("."))
                    break
            
            info["free_bytes"] = free_pages * page_size
            info["available_bytes"] = info["free_bytes"]  # Approximation
            info["used_bytes"] = info["total_bytes"] - info["free_bytes"]
            
        except (subprocess.SubprocessError, ValueError):
            pass
            
    elif _is_windows():
        try:
            import ctypes
            
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            
            mem_status = MEMORYSTATUSEX()
            mem_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem_status))
            
            info["total_bytes"] = mem_status.ullTotalPhys
            info["available_bytes"] = mem_status.ullAvailPhys
            info["used_bytes"] = info["total_bytes"] - info["available_bytes"]
            info["free_bytes"] = info["available_bytes"]
            
        except (ImportError, AttributeError):
            pass
    
    # Add MB versions
    info["total_mb"] = info["total_bytes"] // (1024 * 1024)
    info["available_mb"] = info["available_bytes"] // (1024 * 1024)
    info["used_mb"] = info["used_bytes"] // (1024 * 1024)
    info["free_mb"] = info["free_bytes"] // (1024 * 1024)
    
    return info


def get_disk_usage(path: Optional[Union[str, Path]] = None) -> Dict[str, int]:
    """
    Get disk usage information for a path.
    
    Parameters
    ----------
    path : Optional[Union[str, Path]]
        Path to check. If None, uses current directory.
        
    Returns
    -------
    Dict[str, int]
        Dictionary with keys:
        - total_bytes: Total disk space
        - used_bytes: Used disk space
        - free_bytes: Free disk space
        - total_mb, used_mb, free_mb: Same in megabytes
        - usage_percent: Usage percentage
        
    Examples
    --------
    >>> disk = get_disk_usage("/")
    >>> print(f"Disk: {disk['used_mb']}MB / {disk['total_mb']}MB ({disk['usage_percent']:.1f}%)")
    """
    check_path = Path(path) if path else Path.cwd()
    
    info = {
        "total_bytes": 0,
        "used_bytes": 0,
        "free_bytes": 0,
    }
    
    try:
        usage = shutil.disk_usage(str(check_path))
        info["total_bytes"] = usage.total
        info["used_bytes"] = usage.used
        info["free_bytes"] = usage.free
        
        info["total_mb"] = usage.total // (1024 * 1024)
        info["used_mb"] = usage.used // (1024 * 1024)
        info["free_mb"] = usage.free // (1024 * 1024)
        
        if usage.total > 0:
            info["usage_percent"] = (usage.used / usage.total) * 100
        else:
            info["usage_percent"] = 0.0
            
    except (OSError, PermissionError):
        pass
    
    return info


# ============================================================================
# Process Management
# ============================================================================

def get_process_id() -> int:
    """
    Get the current process ID.
    
    Returns
    -------
    int
        Current process ID (PID).
        
    Examples
    --------
    >>> pid = get_process_id()
    >>> print(f"Current PID: {pid}")
    """
    return os.getpid()


def get_process_parent_id() -> int:
    """
    Get the parent process ID.
    
    Returns
    -------
    int
        Parent process ID (PPID).
        
    Examples
    --------
    >>> ppid = get_process_parent_id()
    >>> print(f"Parent PID: {ppid}")
    """
    return os.getppid()


def is_process_running(pid: int) -> bool:
    """
    Check if a process with given PID is running.
    
    Parameters
    ----------
    pid : int
        Process ID to check.
        
    Returns
    -------
    bool
        True if process exists and is running.
        
    Examples
    --------
    >>> if is_process_running(1234):
    ...     print("Process is running")
    """
    if pid <= 0:
        return False
    
    try:
        if _is_windows():
            import ctypes
            
            SYNCHRONIZE = 0x00100000
            handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            
            if handle:
                exit_code = ctypes.c_ulong()
                ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                ctypes.windll.kernel32.CloseHandle(handle)
                return exit_code.value == 259  # STILL_ACTIVE
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False
    except Exception:
        return False


def kill_process(
    pid: int,
    force: bool = False,
    timeout: float = 5.0,
) -> bool:
    """
    Kill a process by PID.
    
    Parameters
    ----------
    pid : int
        Process ID to kill.
    force : bool
        If True, use SIGKILL (force kill). If False, use SIGTERM (graceful).
    timeout : float
        Time to wait for process to terminate before force killing.
        
    Returns
    -------
    bool
        True if process was killed successfully.
        
    Examples
    --------
    >>> # Graceful termination
    >>> kill_process(1234)
    >>> 
    >>> # Force kill
    >>> kill_process(1234, force=True)
    >>> 
    >>> # Graceful with timeout then force
    >>> kill_process(1234, force=False, timeout=3.0)
    """
    if not is_process_running(pid):
        return True
    
    try:
        if _is_windows():
            import ctypes
            
            PROCESS_TERMINATE = 0x0001
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
            
            if handle:
                result = ctypes.windll.kernel32.TerminateProcess(handle, 1)
                ctypes.windll.kernel32.CloseHandle(handle)
                return bool(result)
            return False
        else:
            sig = signal.SIGKILL if force else signal.SIGTERM
            os.kill(pid, sig)
            
            if not force and timeout > 0:
                # Wait for graceful termination
                start = time.time()
                while time.time() - start < timeout:
                    if not is_process_running(pid):
                        return True
                    time.sleep(0.1)
                
                # Force kill if still running
                os.kill(pid, signal.SIGKILL)
            
            return True
            
    except (OSError, ProcessLookupError):
        return False
    except Exception:
        return False


def kill_process_tree(
    pid: int,
    force: bool = False,
    timeout: float = 5.0,
) -> int:
    """
    Kill a process and all its children.
    
    Parameters
    ----------
    pid : int
        Root process ID to kill.
    force : bool
        If True, use SIGKILL (force kill).
    timeout : float
        Time to wait for processes to terminate.
        
    Returns
    -------
    int
        Number of processes killed.
        
    Examples
    --------
    >>> killed = kill_process_tree(1234)
    >>> print(f"Killed {killed} processes")
    """
    killed = 0
    
    # Get child processes
    children = get_child_processes(pid)
    
    # Kill children first
    for child_pid in children:
        if kill_process_tree(child_pid, force, timeout):
            killed += 1
    
    # Kill the parent
    if kill_process(pid, force, timeout):
        killed += 1
    
    return killed


def get_child_processes(pid: Optional[int] = None) -> List[int]:
    """
    Get all child processes of a given PID.
    
    Parameters
    ----------
    pid : Optional[int]
        Parent process ID. If None, uses current process.
        
    Returns
    -------
    List[int]
        List of child process IDs.
        
    Examples
    --------
    >>> children = get_child_processes()
    >>> print(f"Child processes: {children}")
    """
    parent_pid = pid if pid is not None else os.getpid()
    children: List[int] = []
    
    if _is_linux():
        try:
            for proc in Path("/proc").iterdir():
                if proc.is_dir() and proc.name.isdigit():
                    try:
                        stat_file = proc / "stat"
                        with open(stat_file, "r") as f:
                            content = f.read()
                        
                        # PPID is the 4th field
                        fields = content.split()
                        if len(fields) >= 4:
                            ppid = int(fields[3])
                            child_pid = int(fields[0])
                            
                            if ppid == parent_pid:
                                children.append(child_pid)
                    except (IOError, OSError, ValueError):
                        continue
        except (IOError, OSError):
            pass
            
    elif _is_macos():
        try:
            result = subprocess.run(
                ["pgrep", "-P", str(parent_pid)],
                capture_output=True,
                text=True,
            )
            
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line:
                        children.append(int(line))
                        
        except (subprocess.SubprocessError, ValueError):
            pass
            
    elif _is_windows():
        try:
            import ctypes
            import ctypes.wintypes
            
            # This requires WMI or toolhelp32 snapshot
            # Simplified: use wmic command
            result = subprocess.run(
                ["wmic", "process", "where", f"ParentProcessId={parent_pid}", "get", "ProcessId"],
                capture_output=True,
                text=True,
            )
            
            for line in result.stdout.strip().split("\n")[1:]:
                line = line.strip()
                if line and line.isdigit():
                    children.append(int(line))
                    
        except (subprocess.SubprocessError, ValueError):
            pass
    
    return children


def get_process_info(pid: Optional[int] = None) -> Dict[str, Any]:
    """
    Get detailed information about a process.
    
    Parameters
    ----------
    pid : Optional[int]
        Process ID. If None, uses current process.
        
    Returns
    -------
    Dict[str, Any]
        Process information dictionary.
        
    Examples
    --------
    >>> info = get_process_info()
    >>> print(f"PID: {info['pid']}, PPID: {info['ppid']}")
    >>> print(f"Name: {info['name']}")
    >>> print(f"Memory: {info.get('memory_mb', 0):.1f}MB")
    """
    check_pid = pid if pid is not None else os.getpid()
    
    info: Dict[str, Any] = {
        "pid": check_pid,
        "ppid": 0,
        "name": "",
        "cmdline": [],
        "memory_bytes": 0,
        "memory_mb": 0.0,
        "cpu_percent": 0.0,
        "status": "unknown",
        "user": "",
        "create_time": 0,
    }
    
    if _is_linux():
        try:
            proc_path = Path(f"/proc/{check_pid}")
            
            # Read stat file
            stat_file = proc_path / "stat"
            with open(stat_file, "r") as f:
                content = f.read()
            
            fields = content.split()
            if len(fields) >= 22:
                info["name"] = fields[1].strip("()")
                info["status"] = fields[2]
                info["ppid"] = int(fields[3])
                info["memory_bytes"] = int(fields[23]) * 4096  # rss * page size
                info["memory_mb"] = info["memory_bytes"] / (1024 * 1024)
            
            # Read cmdline
            cmdline_file = proc_path / "cmdline"
            with open(cmdline_file, "r") as f:
                cmdline = f.read().replace("\x00", " ").strip()
                info["cmdline"] = cmdline.split()
                
        except (IOError, OSError, ValueError):
            pass
            
    elif _is_macos():
        try:
            result = subprocess.run(
                ["ps", "-p", str(check_pid), "-o", "ppid,comm,rss,%cpu,stat,user"],
                capture_output=True,
                text=True,
            )
            
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 2:
                fields = lines[1].split()
                if len(fields) >= 6:
                    info["ppid"] = int(fields[0])
                    info["name"] = fields[1]
                    info["memory_bytes"] = int(fields[2]) * 1024  # KB to bytes
                    info["memory_mb"] = info["memory_bytes"] / (1024 * 1024)
                    info["cpu_percent"] = float(fields[3])
                    info["status"] = fields[4]
                    info["user"] = fields[5]
                    
        except (subprocess.SubprocessError, ValueError, IndexError):
            pass
            
    elif _is_windows():
        try:
            result = subprocess.run(
                ["wmic", "process", "where", f"ProcessId={check_pid}",
                 "get", "ParentProcessId,Name,CommandLine,WorkingSetSize,UserModeTime,KernelModeTime,Status"],
                capture_output=True,
                text=True,
            )
            
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 2:
                # Parse header and values
                headers = lines[0].strip().split()
                values = lines[1].strip().split(None, len(headers) - 1)
                
                for i, header in enumerate(headers):
                    if i < len(values):
                        if header == "ParentProcessId":
                            info["ppid"] = int(values[i])
                        elif header == "Name":
                            info["name"] = values[i]
                        elif header == "CommandLine":
                            info["cmdline"] = values[i]
                        elif header == "WorkingSetSize":
                            info["memory_bytes"] = int(values[i])
                            info["memory_mb"] = info["memory_bytes"] / (1024 * 1024)
                        elif header == "Status":
                            info["status"] = values[i]
                            
        except (subprocess.SubprocessError, ValueError):
            pass
    
    return info


# ============================================================================
# Signal Handling
# ============================================================================

class SignalHandler:
    """
    Context manager for temporary signal handling.
    
    This class provides a context manager that temporarily sets a signal
    handler and restores the original when exiting the context.
    
    Parameters
    ----------
    signals : Union[int, List[int]]
        Signal number(s) to handle.
    handler : Callable
        Signal handler function.
    
    Attributes
    ----------
    signals : List[int]
        Signal numbers being handled.
    handler : Callable
        Current handler function.
    _original_handlers : Dict[int, Any]
        Original signal handlers.
    
    Examples
    --------
    >>> def handle_sigint(signum, frame):
    ...     print("SIGINT received, ignoring...")
    >>> 
    >>> with SignalHandler(signal.SIGINT, handle_sigint):
    ...     # SIGINT is handled by our function
    ...     time.sleep(10)
    >>> # Original SIGINT handler restored
    """
    
    def __init__(
        self,
        signals: Union[int, List[int]],
        handler: Callable,
    ):
        if isinstance(signals, int):
            self.signals = [signals]
        else:
            self.signals = signals
        
        self.handler = handler
        self._original_handlers: Dict[int, Any] = {}
    
    def __enter__(self) -> "SignalHandler":
        """Set temporary signal handlers."""
        for sig in self.signals:
            self._original_handlers[sig] = signal.signal(sig, self.handler)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Restore original signal handlers."""
        for sig, original in self._original_handlers.items():
            signal.signal(sig, original)


def send_signal(pid: int, signal_num: int) -> bool:
    """
    Send a signal to a process.
    
    Parameters
    ----------
    pid : int
        Process ID to signal.
    signal_num : int
        Signal number to send.
        
    Returns
    -------
    bool
        True if signal was sent successfully.
        
    Examples
    --------
    >>> # Send SIGTERM
    >>> send_signal(1234, signal.SIGTERM)
    >>> 
    >>> # Send SIGKILL
    >>> send_signal(1234, signal.SIGKILL)
    """
    try:
        if _is_windows():
            if signal_num in (signal.SIGTERM, signal.SIGKILL, signal.SIGINT):
                return kill_process(pid, force=(signal_num == signal.SIGKILL))
            else:
                return False
        else:
            os.kill(pid, signal_num)
            return True
    except (OSError, ProcessLookupError):
        return False


def send_signal_to_group(pgid: int, signal_num: int) -> bool:
    """
    Send a signal to a process group.
    
    Parameters
    ----------
    pgid : int
        Process group ID.
    signal_num : int
        Signal number to send.
        
    Returns
    -------
    bool
        True if signal was sent successfully.
        
    Examples
    --------
    >>> # Send SIGTERM to entire process group
    >>> send_signal_to_group(1234, signal.SIGTERM)
    """
    try:
        if _is_windows():
            return False
        else:
            os.killpg(pgid, signal_num)
            return True
    except (OSError, ProcessLookupError):
        return False


def create_process_group() -> int:
    """
    Create a new process group with current process as leader.
    
    Returns
    -------
    int
        Process group ID (same as current PID).
        
    Examples
    --------
    >>> pgid = create_process_group()
    >>> print(f"Process group ID: {pgid}")
    """
    if _is_windows():
        return os.getpid()
    else:
        os.setpgrp()
        return os.getpgrp()


def get_process_group(pid: Optional[int] = None) -> int:
    """
    Get the process group ID of a process.
    
    Parameters
    ----------
    pid : Optional[int]
        Process ID. If None, uses current process.
        
    Returns
    -------
    int
        Process group ID.
        
    Examples
    --------
    >>> pgid = get_process_group()
    >>> print(f"Current process group: {pgid}")
    """
    if pid is None:
        return os.getpgrp()
    else:
        return os.getpgid(pid)


# ============================================================================
# Temporary Files and Directories
# ============================================================================

@dataclass
class TempFile:
    """
    Temporary file wrapper with automatic cleanup.
    
    Attributes
    ----------
    path : Path
        Path to the temporary file.
    file : IO
        Open file object.
    _delete_on_close : bool
        Whether to delete on close.
    
    Examples
    --------
    >>> with TempFile(suffix=".c", text=True) as tmp:
    ...     tmp.file.write("int main() { return 0; }")
    ...     tmp.file.flush()
    ...     result = run_command(["gcc", "-c", str(tmp.path)])
    ... # File automatically deleted
    """
    
    path: Path
    file: IO
    _delete_on_close: bool = True
    
    def close(self) -> None:
        """Close and optionally delete the file."""
        if self.file:
            self.file.close()
        
        if self._delete_on_close and self.path.exists():
            try:
                self.path.unlink()
            except OSError:
                pass
    
    def __enter__(self) -> "TempFile":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
    
    def __fspath__(self) -> str:
        """Support for os.PathLike."""
        return str(self.path)


def create_temp_file(
    suffix: Optional[str] = None,
    prefix: Optional[str] = None,
    dir: Optional[Union[str, Path]] = None,
    text: bool = False,
    mode: str = "w",
    encoding: str = "utf-8",
    delete: bool = True,
) -> TempFile:
    """
    Create a temporary file.
    
    Parameters
    ----------
    suffix : Optional[str]
        File suffix (e.g., '.c', '.txt').
    prefix : Optional[str]
        File prefix.
    dir : Optional[Union[str, Path]]
        Directory for the file.
    text : bool
        Open in text mode (default: False = binary).
    mode : str
        File mode ('w', 'r', 'a', 'w+', etc.).
    encoding : str
        Encoding for text mode.
    delete : bool
        Delete file on close.
        
    Returns
    -------
    TempFile
        Temporary file object.
        
    Examples
    --------
    >>> with create_temp_file(suffix=".c", text=True) as tmp:
    ...     tmp.file.write("#include <stdio.h>\\n")
    ...     tmp.file.write("int main() { printf(\"Hello\"); return 0; }\\n")
    ...     tmp.file.flush()
    ...     run_command(["gcc", str(tmp.path), "-o", "/tmp/test"])
    """
    if text:
        fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=str(dir) if dir else None, text=True)
        file_obj = open(fd, mode=mode, encoding=encoding)
    else:
        fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=str(dir) if dir else None)
        file_obj = open(fd, mode=mode + "b")
    
    return TempFile(path=Path(path), file=file_obj, _delete_on_close=delete)


@dataclass
class TempDirectory:
    """
    Temporary directory wrapper with automatic cleanup.
    
    Attributes
    ----------
    path : Path
        Path to the temporary directory.
    _delete_on_exit : bool
        Whether to delete on exit.
    
    Examples
    --------
    >>> with TempDirectory(prefix="build_") as tmp_dir:
    ...     source_file = tmp_dir.path / "test.c"
    ...     source_file.write_text("int main() { return 0; }")
    ...     run_command(["gcc", str(source_file), "-o", str(tmp_dir.path / "test")])
    ... # Directory and contents automatically deleted
    """
    
    path: Path
    _delete_on_exit: bool = True
    
    def cleanup(self) -> None:
        """Delete the directory and all contents."""
        if self._delete_on_exit and self.path.exists():
            try:
                shutil.rmtree(self.path, ignore_errors=True)
            except OSError:
                pass
    
    def __enter__(self) -> "TempDirectory":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()
    
    def __fspath__(self) -> str:
        """Support for os.PathLike."""
        return str(self.path)


def create_temp_directory(
    prefix: Optional[str] = None,
    suffix: Optional[str] = None,
    dir: Optional[Union[str, Path]] = None,
    delete: bool = True,
) -> TempDirectory:
    """
    Create a temporary directory.
    
    Parameters
    ----------
    prefix : Optional[str]
        Directory prefix.
    suffix : Optional[str]
        Directory suffix.
    dir : Optional[Union[str, Path]]
        Parent directory.
    delete : bool
        Delete directory on exit.
        
    Returns
    -------
    TempDirectory
        Temporary directory object.
        
    Examples
    --------
    >>> with create_temp_directory(prefix="sandbox_") as tmp_dir:
    ...     print(f"Temp directory: {tmp_dir.path}")
    ...     # Use directory...
    """
    path = tempfile.mkdtemp(prefix=prefix, suffix=suffix, dir=str(dir) if dir else None)
    return TempDirectory(path=Path(path), _delete_on_exit=delete)


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Command execution
    "CommandResult",
    "CommandError",
    "TimeoutError",
    "run_command",
    "run_command_sync",
    "run_command_async",
    "run_commands_parallel",
    
    # Environment
    "get_environment",
    "set_environment",
    "get_env",
    "set_env",
    "unset_env",
    "prepend_path",
    "append_path",
    
    # System resources
    "get_cpu_count",
    "get_memory_info",
    "get_disk_usage",
    
    # Process management
    "get_process_id",
    "get_process_parent_id",
    "is_process_running",
    "kill_process",
    "kill_process_tree",
    "get_child_processes",
    "get_process_info",
    
    # Signal handling
    "SignalHandler",
    "send_signal",
    "send_signal_to_group",
    "create_process_group",
    "get_process_group",
    
    # Temporary files
    "TempFile",
    "TempDirectory",
    "create_temp_file",
    "create_temp_directory",
]
