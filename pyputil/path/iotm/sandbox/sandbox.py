#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Secure Python Sandbox Execution Environment.

This module provides a comprehensive sandbox for safely executing
untrusted Python code with fine-grained security controls,
resource monitoring, and cross-platform compatibility.

The sandbox implements multiple layers of security including:
- AST-based static analysis
- Runtime namespace restrictions  
- Resource usage monitoring and limits
- System call interception (where supported)
- Comprehensive audit logging

Examples
--------
>>> config = SandboxConfig.from_profile("standard")
>>> sandbox = Sandbox(config)
>>> result = sandbox.execute("print('Hello, Sandbox!')")
>>> sandbox.execute("x = sum(range(100))\\nx")
5050

>>> # Custom configuration
>>> config = SandboxConfig(
...     allow_imports=True,
...     allowed_modules={"math", "random"}
... )
>>> sandbox = Sandbox(config)
>>> sandbox.inject("data", [1, 2, 3])
>>> sandbox.execute("import math; math.sqrt(sum(data))")
2.449489742783178
"""

import ast
import sys
import os
import time
import threading
import signal
import resource
import platform
import traceback
import logging
import json
import hashlib
from pathlib import Path
from typing import (
    Any, Dict, Optional, List, Set, Union, Callable,
    Tuple, Type, Iterator, ContextManager, NamedTuple
)
from types import ModuleType, CodeType, FunctionType, TracebackType
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from functools import wraps, partial
import builtins
import io
import weakref
import gc
import inspect

from .config import SandboxConfig, SecurityLevel, ResourceLimits

# Platform-specific imports
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import resource
    RLIMIT_AVAILABLE = True
except ImportError:
    RLIMIT_AVAILABLE = False


class SandboxViolation(Exception):
    """
    Exception raised when sandbox security rules are violated.
    
    Attributes
    ----------
    violation_type : str
        Type of violation
    details : Dict[str, Any]
        Additional violation details
    """
    
    def __init__(self, message: str, violation_type: str = "security", **details):
        super().__init__(message)
        self.violation_type = violation_type
        self.details = details


class SandboxTimeoutError(TimeoutError):
    """Exception raised when sandbox execution exceeds time limit."""
    pass


class SandboxMemoryError(MemoryError):
    """Exception raised when sandbox exceeds memory limit."""
    pass


class SandboxResourceError(Exception):
    """Exception raised when sandbox exceeds resource limits."""
    pass


class ExecutionEventType(Enum):
    """Types of sandbox execution events."""
    EXECUTION_START = auto()
    EXECUTION_END = auto()
    IMPORT_ATTEMPT = auto()
    IMPORT_BLOCKED = auto()
    ATTRIBUTE_ACCESS = auto()
    ATTRIBUTE_BLOCKED = auto()
    FILE_ACCESS = auto()
    NETWORK_ACCESS = auto()
    RESOURCE_LIMIT = auto()
    SECURITY_VIOLATION = auto()


@dataclass
class ExecutionEvent:
    """
    Record of a sandbox execution event.
    
    Attributes
    ----------
    event_type : ExecutionEventType
        Type of event
    timestamp : datetime
        Event timestamp
    details : Dict[str, Any]
        Event-specific details
    stack_trace : Optional[str]
        Stack trace at event time
    """
    event_type: ExecutionEventType
    timestamp: datetime = field(default_factory=datetime.now)
    details: Dict[str, Any] = field(default_factory=dict)
    stack_trace: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'event_type': self.event_type.name,
            'timestamp': self.timestamp.isoformat(),
            'details': self.details,
            'stack_trace': self.stack_trace
        }


@dataclass
class ExecutionResult:
    """
    Result of sandbox code execution.
    
    Attributes
    ----------
    success : bool
        Whether execution completed successfully
    result : Any
        Execution result (if successful)
    error : Optional[Exception]
        Error that occurred (if any)
    execution_time : float
        Total execution time in seconds
    memory_used : int
        Peak memory usage in bytes
    events : List[ExecutionEvent]
        Execution events
    output : str
        Captured stdout/stderr output
    """
    success: bool
    result: Any = None
    error: Optional[Exception] = None
    execution_time: float = 0.0
    memory_used: int = 0
    events: List[ExecutionEvent] = field(default_factory=list)
    output: str = ""
    
    def __str__(self) -> str:
        """Return string representation."""
        if self.success:
            return f"Success (result={self.result}, time={self.execution_time:.3f}s)"
        return f"Failed (error={self.error}, time={self.execution_time:.3f}s)"


class SecureProxy:
    """
    Advanced proxy class for secure object wrapping.
    
    This class provides comprehensive security wrapping for objects,
    intercepting all attribute access and method calls with
    fine-grained permission checking.
    
    Attributes
    ----------
    _obj : Any
        Wrapped object
    _name : str
        Object name for debugging
    _config : SandboxConfig
        Sandbox configuration
    _allowed_attrs : Set[str]
        Explicitly allowed attributes
    _blocked_attrs : Set[str]
        Explicitly blocked attributes
    """
    
    __slots__ = ('_obj', '_name', '_config', '_allowed_attrs', '_blocked_attrs', '_cache')
    
    def __init__(
        self,
        obj: Any,
        name: str = "unknown",
        config: Optional[SandboxConfig] = None,
        allowed_attrs: Optional[Set[str]] = None,
        blocked_attrs: Optional[Set[str]] = None
    ):
        """
        Initialize secure proxy.
        
        Parameters
        ----------
        obj : Any
            Object to wrap securely
        name : str, optional
            Name for debugging purposes
        config : Optional[SandboxConfig], optional
            Sandbox configuration
        allowed_attrs : Optional[Set[str]], optional
            Explicitly allowed attributes
        blocked_attrs : Optional[Set[str]], optional
            Explicitly blocked attributes
        """
        self._obj = obj
        self._name = name
        self._config = config or SandboxConfig()
        self._allowed_attrs = allowed_attrs or set()
        self._blocked_attrs = blocked_attrs or set()
        self._cache: Dict[str, Any] = {}
    
    def __getattr__(self, name: str) -> Any:
        """
        Intercept attribute access with security checks.
        
        Parameters
        ----------
        name : str
            Attribute name
            
        Returns
        -------
        Any
            Securely wrapped attribute
            
        Raises
        ------
        SandboxViolation
            If attribute access is blocked
        """
        # Check cache
        if name in self._cache:
            return self._cache[name]
        
        # Check explicit blocks
        if name in self._blocked_attrs:
            raise SandboxViolation(
                f"Access to blocked attribute '{name}' is forbidden",
                violation_type="attribute_blocked",
                object_name=self._name,
                attribute=name
            )
        
        # Check configuration
        obj_type = type(self._obj).__name__
        if not self._config.is_attribute_allowed(name, obj_type):
            if name not in self._allowed_attrs:
                raise SandboxViolation(
                    f"Access to attribute '{name}' is not allowed",
                    violation_type="attribute_not_allowed",
                    object_name=self._name,
                    object_type=obj_type,
                    attribute=name
                )
        
        # Get attribute
        try:
            attr = getattr(self._obj, name)
        except AttributeError:
            # Check if it's a special method
            if name.startswith('__') and name.endswith('__'):
                # Allow some safe special methods
                safe_specials = {'__str__', '__repr__', '__len__', '__iter__', '__contains__'}
                if name in safe_specials:
                    attr = getattr(self._obj, name)
                else:
                    raise
            else:
                raise
        
        # Wrap if needed
        if callable(attr) or isinstance(attr, (ModuleType, type)):
            wrapped = SecureProxy(
                attr,
                f"{self._name}.{name}",
                self._config,
                self._allowed_attrs,
                self._blocked_attrs
            )
        elif isinstance(attr, (list, tuple, set, dict)):
            wrapped = self._wrap_collection(attr, f"{self._name}.{name}")
        else:
            wrapped = attr
        
        # Cache for performance
        if len(self._cache) < 100:  # Limit cache size
            self._cache[name] = wrapped
        
        return wrapped
    
    def __setattr__(self, name: str, value: Any) -> None:
        """Intercept attribute setting."""
        if name in self.__slots__:
            super().__setattr__(name, value)
        else:
            # Block setting attributes on wrapped objects
            raise SandboxViolation(
                f"Cannot set attribute '{name}' on proxied object",
                violation_type="attribute_set_blocked",
                object_name=self._name,
                attribute=name
            )
    
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """
        Allow calling proxied functions with security checks.
        
        Parameters
        ----------
        *args : Any
            Positional arguments
        **kwargs : Any
            Keyword arguments
            
        Returns
        -------
        Any
            Function result
        """
        # Validate arguments
        safe_args = [self._safe_value(arg) for arg in args]
        safe_kwargs = {k: self._safe_value(v) for k, v in kwargs.items()}
        
        # Check if call is allowed
        if not self._is_call_allowed(safe_args, safe_kwargs):
            raise SandboxViolation(
                f"Call to '{self._name}' is not allowed with these arguments",
                violation_type="call_blocked",
                function_name=self._name,
                args_count=len(args),
                kwargs_count=len(kwargs)
            )
        
        # Execute call
        try:
            result = self._obj(*safe_args, **safe_kwargs)
        except Exception as e:
            # Wrap exceptions
            raise SandboxViolation(
                f"Error calling '{self._name}': {str(e)}",
                violation_type="call_error",
                function_name=self._name,
                error_type=type(e).__name__
            ) from e
        
        # Wrap result
        return self._wrap_result(result)
    
    def __iter__(self) -> Iterator[Any]:
        """Allow iteration over proxied objects."""
        if hasattr(self._obj, '__iter__'):
            for item in self._obj:
                yield self._wrap_result(item)
        else:
            raise TypeError(f"'{self._name}' object is not iterable")
    
    def __getitem__(self, key: Any) -> Any:
        """Allow indexing proxied objects."""
        if hasattr(self._obj, '__getitem__'):
            safe_key = self._safe_value(key)
            result = self._obj[safe_key]
            return self._wrap_result(result)
        raise TypeError(f"'{self._name}' object is not subscriptable")
    
    def __len__(self) -> int:
        """Get length of proxied object."""
        if hasattr(self._obj, '__len__'):
            return len(self._obj)
        raise TypeError(f"'{self._name}' object has no length")
    
    def __contains__(self, item: Any) -> bool:
        """Check membership in proxied object."""
        if hasattr(self._obj, '__contains__'):
            safe_item = self._safe_value(item)
            return safe_item in self._obj
        raise TypeError(f"'{self._name}' object does not support membership test")
    
    def __str__(self) -> str:
        """Return string representation."""
        try:
            return str(self._obj)
        except Exception:
            return f"<SecureProxy {self._name}>"
    
    def __repr__(self) -> str:
        """Return detailed representation."""
        return f"<SecureProxy name='{self._name}' obj={type(self._obj).__name__}>"
    
    def _safe_value(self, value: Any) -> Any:
        """
        Ensure value is safe for passing to wrapped functions.
        
        Parameters
        ----------
        value : Any
            Value to check
            
        Returns
        -------
        Any
            Safe unwrapped value
        """
        if isinstance(value, SecureProxy):
            return value._obj
        elif isinstance(value, (list, tuple)):
            return type(value)(self._safe_value(v) for v in value)
        elif isinstance(value, dict):
            return {self._safe_value(k): self._safe_value(v) for k, v in value.items()}
        elif isinstance(value, set):
            return {self._safe_value(v) for v in value}
        return value
    
    def _wrap_result(self, result: Any) -> Any:
        """
        Wrap result safely for return to sandbox.
        
        Parameters
        ----------
        result : Any
            Result to wrap
            
        Returns
        -------
        Any
            Safely wrapped result
        """
        if result is None or isinstance(result, (bool, int, float, str, bytes)):
            return result
        elif isinstance(result, (list, tuple, set, dict)):
            return self._wrap_collection(result)
        elif callable(result) or isinstance(result, (ModuleType, type)):
            return SecureProxy(result, "result", self._config)
        elif hasattr(result, '__dict__'):
            return SecureProxy(result, type(result).__name__, self._config)
        return result
    
    def _wrap_collection(self, collection: Any, name: str = "collection") -> Any:
        """
        Wrap a collection with secure elements.
        
        Parameters
        ----------
        collection : Any
            Collection to wrap
        name : str, optional
            Name for wrapped collection
            
        Returns
        -------
        Any
            Securely wrapped collection
        """
        if isinstance(collection, list):
            return SecureList(collection, name, self._config)
        elif isinstance(collection, tuple):
            return SecureTuple(collection, name, self._config)
        elif isinstance(collection, set):
            return SecureSet(collection, name, self._config)
        elif isinstance(collection, dict):
            return SecureDict(collection, name, self._config)
        return collection
    
    def _is_call_allowed(self, args: Tuple, kwargs: Dict) -> bool:
        """
        Check if function call with these arguments is allowed.
        
        Parameters
        ----------
        args : Tuple
            Positional arguments
        kwargs : Dict
            Keyword arguments
            
        Returns
        -------
        bool
            True if call is allowed
        """
        # Check argument count limits
        if len(args) > 100 or len(kwargs) > 100:
            return False
        
        # Check for dangerous patterns
        dangerous_patterns = ['__', 'eval', 'exec', 'compile', 'open', 'file']
        for arg in args:
            if isinstance(arg, str):
                if any(pattern in arg.lower() for pattern in dangerous_patterns):
                    return False
        
        return True


class SecureList(list):
    """Secure wrapper for list objects."""
    
    def __init__(self, data: List, name: str, config: SandboxConfig):
        self._name = name
        self._config = config
        super().__init__(SecureProxy(item, f"{name}[{i}]", config) 
                        for i, item in enumerate(data))


class SecureTuple(tuple):
    """Secure wrapper for tuple objects."""
    
    def __new__(cls, data: Tuple, name: str, config: SandboxConfig):
        return super().__new__(cls, (SecureProxy(item, f"{name}[{i}]", config)
                                     for i, item in enumerate(data)))


class SecureSet(set):
    """Secure wrapper for set objects."""
    
    def __init__(self, data: Set, name: str, config: SandboxConfig):
        self._name = name
        self._config = config
        super().__init__(SecureProxy(item, f"{name}[{i}]", config)
                        for i, item in enumerate(data))


class SecureDict(dict):
    """Secure wrapper for dictionary objects."""
    
    def __init__(self, data: Dict, name: str, config: SandboxConfig):
        self._name = name
        self._config = config
        wrapped = {}
        for k, v in data.items():
            safe_key = SecureProxy(k, f"{name}.key", config) if isinstance(k, str) else k
            safe_value = SecureProxy(v, f"{name}[{k}]", config)
            wrapped[safe_key] = safe_value
        super().__init__(wrapped)


class RestrictedNamespace(dict):
    """
    Secure namespace for sandbox code execution.
    
    This dictionary subclass provides comprehensive security checks
    for all operations within the sandbox namespace.
    
    Attributes
    ----------
    _config : SandboxConfig
        Sandbox configuration
    _audit_log : List[ExecutionEvent]
        Audit log for namespace operations
    _proxy_cache : Dict[str, SecureProxy]
        Cache of proxied objects
    """
    
    def __init__(
        self,
        config: SandboxConfig,
        initial_values: Optional[Dict[str, Any]] = None,
        audit_log: Optional[List[ExecutionEvent]] = None
    ):
        """
        Initialize restricted namespace.
        
        Parameters
        ----------
        config : SandboxConfig
            Sandbox configuration
        initial_values : Optional[Dict[str, Any]], optional
            Initial namespace values
        audit_log : Optional[List[ExecutionEvent]], optional
            Audit log for events
        """
        super().__init__()
        self._config = config
        self._audit_log = audit_log or []
        self._proxy_cache = {}
        self._lock = threading.RLock()
        
        # Initialize with safe builtins
        self._init_safe_builtins()
        
        # Add initial values
        if initial_values:
            for name, value in initial_values.items():
                self[name] = value
        
        # Set special attributes
        super().__setitem__('__name__', '__sandbox__')
        super().__setitem__('__doc__', None)
        super().__setitem__('__sandbox_config__', config)
    
    def _init_safe_builtins(self) -> None:
        """Initialize safe builtins namespace."""
        safe_builtins = {}
        
        for name in self._config.safe_builtins:
            if hasattr(builtins, name):
                builtin_obj = getattr(builtins, name)
                safe_builtins[name] = SecureProxy(
                    builtin_obj,
                    f"builtins.{name}",
                    self._config
                )
        
        # Add some essential builtins
        safe_builtins.update({
            'print': SecureProxy(builtins.print, "builtins.print", self._config),
            'len': SecureProxy(builtins.len, "builtins.len", self._config),
            'range': SecureProxy(builtins.range, "builtins.range", self._config),
        })
        
        super().__setitem__('__builtins__', SecureDict(
            safe_builtins,
            "__builtins__",
            self._config
        ))
    
    def __getitem__(self, key: str) -> Any:
        """
        Get item with comprehensive security checks.
        
        Parameters
        ----------
        key : str
            Key to retrieve
            
        Returns
        -------
        Any
            Securely wrapped value
        """
        with self._lock:
            # Check cache
            if key in self._proxy_cache:
                return self._proxy_cache[key]
            
            # Security checks
            if key.startswith('__') and key.endswith('__'):
                if key not in {'__name__', '__doc__', '__sandbox_config__'}:
                    self._log_event(ExecutionEventType.ATTRIBUTE_BLOCKED, {
                        'key': key,
                        'reason': 'dunder_attribute'
                    })
                    raise SandboxViolation(
                        f"Access to '{key}' is forbidden",
                        violation_type="dunder_access_blocked"
                    )
            
            # Check if it's a blocked module
            if key in self._config.blocked_modules:
                self._log_event(ExecutionEventType.IMPORT_BLOCKED, {
                    'module': key,
                    'reason': 'explicitly_blocked'
                })
                raise SandboxViolation(
                    f"Module '{key}' is blocked for security reasons",
                    violation_type="module_blocked",
                    module=key
                )
            
            # Get value
            value = super().__getitem__(key)
            
            # Wrap if needed
            wrapped = self._wrap_value(value, key)
            
            # Cache
            if len(self._proxy_cache) < 1000:
                self._proxy_cache[key] = wrapped
            
            return wrapped
    
    def __setitem__(self, key: str, value: Any) -> None:
        """
        Set item with security checks.
        
        Parameters
        ----------
        key : str
            Key to set
        value : Any
            Value to set
        """
        with self._lock:
            # Security checks
            if key == '__builtins__':
                self._log_event(ExecutionEventType.SECURITY_VIOLATION, {
                    'key': key,
                    'reason': 'builtins_modification'
                })
                raise SandboxViolation(
                    "Cannot modify builtins",
                    violation_type="builtins_modification"
                )
            
            if key.startswith('__') and key.endswith('__'):
                if key not in {'__name__', '__doc__', '__sandbox_config__'}:
                    self._log_event(ExecutionEventType.SECURITY_VIOLATION, {
                        'key': key,
                        'reason': 'dunder_modification'
                    })
                    raise SandboxViolation(
                        f"Cannot set '{key}'",
                        violation_type="dunder_modification"
                    )
            
            # Clear cache for this key
            self._proxy_cache.pop(key, None)
            
            # Wrap value
            safe_value = self._sanitize_value(value, key)
            
            super().__setitem__(key, safe_value)
    
    def __delitem__(self, key: str) -> None:
        """Delete item with security checks."""
        with self._lock:
            # Block deletion of critical items
            if key in {'__builtins__', '__name__', '__sandbox_config__'}:
                raise SandboxViolation(
                    f"Cannot delete critical item '{key}'",
                    violation_type="critical_delete"
                )
            
            self._proxy_cache.pop(key, None)
            super().__delitem__(key)
    
    def _wrap_value(self, value: Any, name: str) -> Any:
        """
        Wrap value securely.
        
        Parameters
        ----------
        value : Any
            Value to wrap
        name : str
            Name for wrapped value
            
        Returns
        -------
        Any
            Securely wrapped value
        """
        if value is None or isinstance(value, (bool, int, float, str, bytes)):
            return value
        elif isinstance(value, ModuleType):
            return SecureProxy(value, name, self._config)
        elif isinstance(value, type):
            return SecureProxy(value, name, self._config)
        elif callable(value):
            return SecureProxy(value, name, self._config)
        elif isinstance(value, (list, tuple, set, dict)):
            return SecureProxy(value, name, self._config)
        elif hasattr(value, '__dict__'):
            return SecureProxy(value, name, self._config)
        return value
    
    def _sanitize_value(self, value: Any, name: str) -> Any:
        """
        Sanitize value before storing.
        
        Parameters
        ----------
        value : Any
            Value to sanitize
        name : str
            Name for the value
            
        Returns
        -------
        Any
            Sanitized value
        """
        # Block certain types
        if isinstance(value, (type, ModuleType)):
            # Allow only if explicitly configured
            if not self._config.allow_imports:
                raise SandboxViolation(
                    f"Cannot store module/class '{name}'",
                    violation_type="type_storage_blocked"
                )
            return SecureProxy(value, name, self._config)
        
        # Recursively sanitize collections
        if isinstance(value, list):
            return [self._sanitize_value(v, f"{name}[{i}]") 
                   for i, v in enumerate(value)]
        elif isinstance(value, dict):
            return {k: self._sanitize_value(v, f"{name}[{k}]") 
                   for k, v in value.items()}
        elif isinstance(value, tuple):
            return tuple(self._sanitize_value(v, f"{name}[{i}]") 
                        for i, v in enumerate(value))
        elif isinstance(value, set):
            return {self._sanitize_value(v, f"{name}.set") 
                   for v in value}
        
        return value
    
    def _log_event(self, event_type: ExecutionEventType, details: Dict) -> None:
        """Log an execution event."""
        if self._config.audit_events:
            event = ExecutionEvent(
                event_type=event_type,
                details=details,
                stack_trace=traceback.format_exc() if details else None
            )
            self._audit_log.append(event)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get item with default."""
        try:
            return self[key]
        except (KeyError, SandboxViolation):
            return default
    
    def copy(self) -> Dict[str, Any]:
        """Return a shallow copy of the namespace."""
        return {k: v for k, v in self.items()}
    
    def safe_keys(self) -> List[str]:
        """Get list of safe accessible keys."""
        return [k for k in self.keys() 
                if not (k.startswith('__') and k.endswith('__'))]


class ResourceMonitor:
    """
    Monitor and enforce resource limits during execution.
    
    This class provides comprehensive resource monitoring including
    CPU time, memory usage, file handles, and other system resources.
    
    Attributes
    ----------
    limits : ResourceLimits
        Resource limits configuration
    start_time : float
        Execution start time
    start_memory : int
        Initial memory usage
    peak_memory : int
        Peak memory usage observed
    """
    
    def __init__(self, limits: ResourceLimits):
        """
        Initialize resource monitor.
        
        Parameters
        ----------
        limits : ResourceLimits
            Resource limits to enforce
        """
        self.limits = limits
        self.start_time: Optional[float] = None
        self.start_memory: Optional[int] = None
        self.peak_memory: int = 0
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._process = psutil.Process() if PSUTIL_AVAILABLE else None
    
    def start(self) -> None:
        """Start resource monitoring."""
        self.start_time = time.time()
        
        if self._process:
            mem_info = self._process.memory_info()
            self.start_memory = mem_info.rss
            self.peak_memory = self.start_memory
        
        # Set resource limits if available
        if RLIMIT_AVAILABLE:
            self._set_rlimits()
        
        # Set recursion limit
        sys.setrecursionlimit(self.limits.max_recursion_depth)
        
        self._monitoring = True
        
        # Start monitoring thread
        if self._process:
            self._monitor_thread = threading.Thread(
                target=self._monitor_resources,
                daemon=True
            )
            self._monitor_thread.start()
    
    def stop(self) -> Tuple[float, int]:
        """
        Stop resource monitoring.
        
        Returns
        -------
        Tuple[float, int]
            (execution_time, peak_memory_bytes)
        """
        self._monitoring = False
        self._stop_event.set()
        
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1.0)
        
        execution_time = time.time() - self.start_time if self.start_time else 0
        
        # Check time limit
        if execution_time > self.limits.cpu_time_seconds:
            raise SandboxTimeoutError(
                f"Execution exceeded time limit of {self.limits.cpu_time_seconds}s"
            )
        
        return execution_time, self.peak_memory
    
    def _set_rlimits(self) -> None:
        """Set system resource limits."""
        try:
            # CPU time limit
            if self.limits.cpu_time_seconds > 0:
                resource.setrlimit(
                    resource.RLIMIT_CPU,
                    (int(self.limits.cpu_time_seconds), 
                     int(self.limits.cpu_time_seconds))
                )
            
            # Memory limit
            if self.limits.memory_mb > 0:
                memory_bytes = self.limits.memory_mb * 1024 * 1024
                resource.setrlimit(
                    resource.RLIMIT_AS,
                    (memory_bytes, memory_bytes)
                )
            
            # File handle limit
            if self.limits.max_open_files > 0:
                resource.setrlimit(
                    resource.RLIMIT_NOFILE,
                    (self.limits.max_open_files, self.limits.max_open_files)
                )
            
            # Process limit
            if self.limits.max_processes >= 0:
                resource.setrlimit(
                    resource.RLIMIT_NPROC,
                    (self.limits.max_processes, self.limits.max_processes)
                )
                
        except (ValueError, resource.error) as e:
            # Some limits may not be supported on all platforms
            logging.warning(f"Failed to set resource limit: {e}")
    
    def _monitor_resources(self) -> None:
        """Monitor thread for continuous resource checking."""
        while self._monitoring and not self._stop_event.is_set():
            try:
                if self._process:
                    # Check memory usage
                    mem_info = self._process.memory_info()
                    current_memory = mem_info.rss
                    
                    if current_memory > self.peak_memory:
                        self.peak_memory = current_memory
                    
                    memory_mb = current_memory / (1024 * 1024)
                    if memory_mb > self.limits.memory_mb:
                        raise SandboxMemoryError(
                            f"Memory usage exceeded limit: {memory_mb:.1f}MB > {self.limits.memory_mb}MB"
                        )
                    
                    # Check file handles
                    if self.limits.max_open_files > 0:
                        open_files = len(self._process.open_files())
                        if open_files > self.limits.max_open_files:
                            raise SandboxResourceError(
                                f"File handle limit exceeded: {open_files} > {self.limits.max_open_files}"
                            )
                
            except Exception as e:
                if not isinstance(e, SandboxViolation):
                    logging.error(f"Resource monitor error: {e}")
            
            self._stop_event.wait(0.1)  # Check every 100ms
    
    def check_timeout(self) -> None:
        """Check if execution has exceeded time limit."""
        if self.start_time:
            elapsed = time.time() - self.start_time
            if elapsed > self.limits.cpu_time_seconds:
                raise SandboxTimeoutError(
                    f"Execution exceeded time limit of {self.limits.cpu_time_seconds}s"
                )


class ASTSecurityValidator(ast.NodeVisitor):
    """
    Static AST validator for security analysis.
    
    This class performs comprehensive static analysis of Python code
    before execution to detect and block potentially dangerous patterns.
    
    Attributes
    ----------
    config : SandboxConfig
        Sandbox configuration    violations : List[Tuple[int, str]]
        List of (line_number, violation_message)
    current_function : Optional[str]
        Currently analyzed function name
    import_aliases : Dict[str, str]
        Mapping of import aliases to module names
    """
    
    def __init__(self, config: SandboxConfig):
        """
        Initialize AST validator.
        
        Parameters
        ----------
        config : SandboxConfig
            Sandbox configuration
        """
        self.config = config
        self.violations: List[Tuple[int, str]] = []
        self.current_function: Optional[str] = None
        self.import_aliases: Dict[str, str] = {}
        self._variable_types: Dict[str, str] = {}
    
    def validate(self, tree: ast.AST) -> List[Tuple[int, str]]:
        """
        Validate AST for security issues.
        
        Parameters
        ----------
        tree : ast.AST
            AST to validate
            
        Returns
        -------
        List[Tuple[int, str]]
            List of violations with line numbers
        """
        self.violations = []
        self.visit(tree)
        return self.violations
    
    def visit_Import(self, node: ast.Import) -> None:
        """Validate import statements."""
        if not self.config.allow_imports:
            self.violations.append((
                node.lineno,
                "Imports are not allowed"
            ))
            return
        
        for alias in node.names:
            module_name = alias.name
            
            # Check if module is allowed
            if not self.config.is_module_allowed(module_name):
                self.violations.append((
                    node.lineno,
                    f"Import of '{module_name}' is forbidden"
                ))
            
            # Track alias
            if alias.asname:
                self.import_aliases[alias.asname] = module_name
            else:
                self.import_aliases[module_name.split('.')[0]] = module_name
        
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Validate from-import statements."""
        if not self.config.allow_imports:
            self.violations.append((
                node.lineno,
                "Imports are not allowed"
            ))
            return
        
        if node.module:
            if not self.config.is_module_allowed(node.module):
                self.violations.append((
                    node.lineno,
                    f"Import from '{node.module}' is forbidden"
                ))
        
        for alias in node.names:
            if alias.asname:
                self.import_aliases[alias.asname] = f"{node.module}.{alias.name}"
            else:
                self.import_aliases[alias.name] = f"{node.module}.{alias.name}"
        
        self.generic_visit(node)
    
    def visit_Call(self, node: ast.Call) -> None:
        """Validate function calls."""
        # Check for dangerous builtins
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            
            dangerous_funcs = {'eval', 'exec', 'compile', '__import__', 'open', 'input'}
            if func_name in dangerous_funcs:
                self.violations.append((
                    node.lineno,
                    f"Call to dangerous function '{func_name}' is forbidden"
                ))
            
            # Check if function is allowed builtin
            if func_name in dir(builtins) and func_name not in self.config.safe_builtins:
                self.violations.append((
                    node.lineno,
                    f"Builtin function '{func_name}' is not allowed"
                ))
        
        # Check for dangerous method calls
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            
            dangerous_methods = {
                '__subclasses__', '__bases__', '__mro__', '__globals__',
                '__getattribute__', '__setattr__', '__delattr__',
                '__reduce__', '__reduce_ex__'
            }
            
            if attr_name in dangerous_methods:
                self.violations.append((
                    node.lineno,
                    f"Call to dangerous method '{attr_name}' is forbidden"
                ))
        
        self.generic_visit(node)
    
    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Validate attribute access."""
        attr_name = node.attr
        
        # Check blocked attributes
        if attr_name in self.config.blocked_attributes:
            self.violations.append((
                node.lineno,
                f"Access to blocked attribute '{attr_name}' is forbidden"
            ))
        
        # Check dunder attributes
        if attr_name.startswith('__') and attr_name.endswith('__'):
            safe_dunders = {'__name__', '__doc__', '__class__'}
            if attr_name not in safe_dunders:
                self.violations.append((
                    node.lineno,
                    f"Access to dunder attribute '{attr_name}' is restricted"
                ))
        
        self.generic_visit(node)
    
    def visit_Delete(self, node: ast.Delete) -> None:
        """Validate delete operations."""
        for target in node.targets:
            if isinstance(target, ast.Name):
                if target.id in {'__builtins__', '__name__', '__doc__'}:
                    self.violations.append((
                        node.lineno,
                        f"Cannot delete critical variable '{target.id}'"
                    ))
        
        self.generic_visit(node)
    
    def visit_With(self, node: ast.With) -> None:
        """Validate with statements."""
        for item in node.items:
            if isinstance(item.context_expr, ast.Call):
                if isinstance(item.context_expr.func, ast.Name):
                    if item.context_expr.func.id == 'open':
                        if not self.config.allow_file_io:
                            self.violations.append((
                                node.lineno,
                                "File I/O is not allowed"
                            ))
        
        self.generic_visit(node)
    
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Validate class definitions."""
        # Check inheritance for dangerous bases
        for base in node.bases:
            if isinstance(base, ast.Name):
                if base.id in {'type', 'object'}:
                    continue  # Allow common bases
                # Check if base class might be dangerous
                if any(dangerous in base.id.lower() 
                      for dangerous in ['exec', 'eval', 'code', 'compile']):
                    self.violations.append((
                        node.lineno,
                        f"Suspicious base class '{base.id}'"
                    ))
        
        self.generic_visit(node)
    
    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        """Validate f-strings for potential code injection."""
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                if isinstance(value.value, ast.Name):
                    # Check for dangerous variable access in f-strings
                    pass  # Could add specific checks here
        
        self.generic_visit(node)
    
    def visit_Global(self, node: ast.Global) -> None:
        """Block global variable modifications."""
        self.violations.append((
            node.lineno,
            "Global variable modification is not allowed"
        ))
    
    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        """Block nonlocal variable modifications."""
        self.violations.append((
            node.lineno,
            "Nonlocal variable modification is not allowed"
        ))


class Sandbox:
    """
    Advanced Secure Python Sandbox Execution Environment.
    
    This class provides a comprehensive sandbox for safely executing
    untrusted Python code with multiple security layers.
    
    Attributes
    ----------
    config : SandboxConfig
        Sandbox configuration
    namespace : RestrictedNamespace
        Secure execution namespace
    history : List[ExecutionResult]
        Execution history
    logger : logging.Logger
        Sandbox logger
    
    Methods
    -------
    execute(code, timeout=None, capture_output=True)
        Execute code safely in sandbox
    execute_file(path)
        Execute Python file in sandbox
    inject(name, value)
        Inject object into sandbox
    get_namespace_copy()
        Get safe copy of namespace
    reset()
        Reset sandbox to initial state
    get_report()
        Generate execution report
    
    Examples
    --------
    >>> config = SandboxConfig.from_profile("standard")
    >>> sandbox = Sandbox(config)
    >>> result = sandbox.execute("print('Hello, World!')")
    >>> print(result.result)
    Hello, World!
    
    >>> sandbox.inject("data", [1, 2, 3, 4, 5])
    >>> result = sandbox.execute("sum(data) / len(data)")
    >>> print(result.result)
    3.0
    """
    
    def __init__(
        self,
        config: Optional[SandboxConfig] = None,
        namespace: Optional[Dict[str, Any]] = None,
        enable_logging: Optional[bool] = None
    ):
        """
        Initialize sandbox with configuration.
        
        Parameters
        ----------
        config : Optional[SandboxConfig], optional
            Sandbox configuration (default creates STANDARD)
        namespace : Optional[Dict[str, Any]], optional
            Initial namespace values
        enable_logging : Optional[bool], optional
            Override logging configuration
        """
        self.config = config or SandboxConfig.from_profile(SecurityLevel.STANDARD)
        
        if enable_logging is not None:
            self.config.enable_logging = enable_logging
        
        # Initialize namespace
        self.namespace = RestrictedNamespace(self.config, namespace)
        
        # History and state
        self.history: List[ExecutionResult] = []
        self._execution_count = 0
        self._audit_log: List[ExecutionEvent] = []
        
        # Setup logging
        self.logger = self._setup_logging()
        
        # Locks for thread safety
        self._execution_lock = threading.RLock()
        
        # Validator
        self.validator = ASTSecurityValidator(self.config)
        
        # Signal handlers
        self._original_sigint = None
        self._original_sigalrm = None
        
        self.logger.info(f"Sandbox initialized with {self.config.security_level.name} security level")
    
    def _setup_logging(self) -> logging.Logger:
        """
        Setup sandbox logging.
        
        Returns
        -------
        logging.Logger
            Configured logger
        """
        logger = logging.getLogger(f"sandbox_{id(self)}")
        logger.setLevel(logging.INFO)
        
        if self.config.enable_logging:
            if self.config.log_file:
                handler = logging.FileHandler(self.config.log_file)
                formatter = logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                )
                handler.setFormatter(formatter)
                logger.addHandler(handler)
        
        return logger
    
    def execute(
        self,
        code: str,
        timeout: Optional[float] = None,
        capture_output: bool = True,
        return_result: bool = True
    ) -> ExecutionResult:
        """
        Execute code safely in sandbox with comprehensive monitoring.
        
        Parameters
        ----------
        code : str
            Python code to execute
        timeout : Optional[float], optional
            Maximum execution time in seconds (overrides config)
        capture_output : bool, optional
            Capture stdout/stderr output (default True)
        return_result : bool, optional
            Return the execution result (default True)
            
        Returns
        -------
        ExecutionResult
            Execution result with details
            
        Raises
        ------
        SandboxViolation
            If code violates security rules
        SandboxTimeoutError
            If execution exceeds time limit
        SandboxMemoryError
            If memory limit is exceeded
        """
        with self._execution_lock:
            start_time = time.time()
            events: List[ExecutionEvent] = []
            output_buffer = io.StringIO() if capture_output else None
            
            # Log execution start
            events.append(ExecutionEvent(
                event_type=ExecutionEventType.EXECUTION_START,
                details={'code_size': len(code)}
            ))
            
            # Validate code size
            if len(code.encode()) > self.config.resource_limits.max_code_size_bytes:
                raise SandboxViolation(
                    f"Code size exceeds maximum ({self.config.resource_limits.max_code_size_bytes} bytes)",
                    violation_type="code_size_exceeded"
                )
            
            try:
                # Parse and validate AST
                tree = ast.parse(code)
                violations = self.validator.validate(tree)
                
                if violations:
                    error_msg = "\n".join(f"Line {line}: {msg}" for line, msg in violations)
                    events.append(ExecutionEvent(
                        event_type=ExecutionEventType.SECURITY_VIOLATION,
                        details={'violations': violations}
                    ))
                    raise SandboxViolation(
                        f"Security violations found:\n{error_msg}",
                        violation_type="ast_validation_failed",
                        violations=violations
                    )
                
                # Setup resource monitoring
                monitor = ResourceMonitor(self.config.resource_limits)
                monitor.start()
                
                # Prepare execution environment
                exec_globals = self.namespace
                exec_locals = {}
                
                # Setup timeout
                effective_timeout = timeout or self.config.resource_limits.cpu_time_seconds
                result_value = None
                execution_error = None
                
                def execute_code():
                    nonlocal result_value, execution_error
                    try:
                        if capture_output:
                            with redirect_stdout(output_buffer), redirect_stderr(output_buffer):
                                exec(compile(tree, '<sandbox>', 'exec'), exec_globals, exec_locals)
                        else:
                            exec(compile(tree, '<sandbox>', 'exec'), exec_globals, exec_locals)
                        
                        # Try to get the last expression result
                        if return_result:
                            # Find the last expression
                            if tree.body and isinstance(tree.body[-1], ast.Expr):
                                last_expr = compile(
                                    ast.Expression(tree.body[-1].value),
                                    '<sandbox>',
                                    'eval'
                                )
                                result_value = eval(last_expr, exec_globals, exec_locals)
                            else:
                                result_value = exec_locals.get('_', None)
                        
                    except Exception as e:
                        execution_error = e
                        events.append(ExecutionEvent(
                            event_type=ExecutionEventType.SECURITY_VIOLATION,
                            details={'error': str(e), 'type': type(e).__name__},
                            stack_trace=traceback.format_exc()
                        ))
                
                # Execute with timeout
                exec_thread = threading.Thread(target=execute_code)
                exec_thread.daemon = True
                exec_thread.start()
                exec_thread.join(effective_timeout)
                
                if exec_thread.is_alive():
                    # Timeout occurred
                    execution_time, peak_memory = monitor.stop()
                    events.append(ExecutionEvent(
                        event_type=ExecutionEventType.RESOURCE_LIMIT,
                        details={'limit_type': 'timeout', 'limit': effective_timeout}
                    ))
                    raise SandboxTimeoutError(
                        f"Code execution exceeded {effective_timeout} seconds"
                    )
                
                # Stop monitoring
                execution_time, peak_memory = monitor.stop()
                
                # Check for execution errors
                if execution_error:
                    raise execution_error
                
                # Update namespace with local changes
                for key, value in exec_locals.items():
                    if not key.startswith('_'):
                        self.namespace[key] = value
                
                # Log successful execution
                events.append(ExecutionEvent(
                    event_type=ExecutionEventType.EXECUTION_END,
                    details={
                        'execution_time': execution_time,
                        'memory_used': peak_memory,
                        'success': True
                    }
                ))
                
                result = ExecutionResult(
                    success=True,
                    result=result_value,
                    execution_time=execution_time,
                    memory_used=peak_memory,
                    events=events,
                    output=output_buffer.getvalue() if output_buffer else ""
                )
                
                self.history.append(result)
                self._execution_count += 1
                
                self.logger.info(
                    f"Execution #{self._execution_count} succeeded in {execution_time:.3f}s"
                )
                
                return result
                
            except Exception as e:
                execution_time = time.time() - start_time
                
                # Determine error type
                if isinstance(e, SandboxViolation):
                    error = e
                elif isinstance(e, SandboxTimeoutError):
                    error = e
                elif isinstance(e, SandboxMemoryError):
                    error = e
                else:
                    # Wrap unknown errors
                    error = SandboxViolation(
                        f"Execution error: {str(e)}",
                        violation_type="execution_error",
                        original_error=type(e).__name__
                    )
                
                events.append(ExecutionEvent(
                    event_type=ExecutionEventType.EXECUTION_END,
                    details={
                        'execution_time': execution_time,
                        'success': False,
                        'error': str(error)
                    }
                ))
                
                result = ExecutionResult(
                    success=False,
                    error=error,
                    execution_time=execution_time,
                    memory_used=0,
                    events=events,
                    output=output_buffer.getvalue() if output_buffer else ""
                )
                
                self.history.append(result)
                self._execution_count += 1
                
                self.logger.error(
                    f"Execution #{self._execution_count} failed: {str(error)}"
                )
                
                if isinstance(e, (SandboxViolation, SandboxTimeoutError, SandboxMemoryError)):
                    raise
                
                return result
    
    def execute_file(
        self,
        path: Union[str, Path],
        **kwargs
    ) -> ExecutionResult:
        """
        Execute Python file in sandbox.
        
        Parameters
        ----------
        path : Union[str, Path]
            Path to Python file
        **kwargs
            Additional arguments for execute()
            
        Returns
        -------
        ExecutionResult
            Execution result
        """
        path = Path(path)
        
        if not self.config.allow_file_io:
            raise SandboxViolation(
                "File I/O is not allowed",
                violation_type="file_io_blocked"
            )
        
        # Check if path is allowed
        if self.config.custom_allowed_paths:
            if not any(path.resolve().is_relative_to(allowed.resolve()) 
                      for allowed in self.config.custom_allowed_paths):
                raise SandboxViolation(
                    f"File '{path}' is not in allowed paths",
                    violation_type="path_not_allowed",
                    path=str(path)
                )
        
        with open(path, 'r', encoding='utf-8') as f:
            code = f.read()
        
        return self.execute(code, **kwargs)
    
    def inject(self, name: str, value: Any, safe: bool = True) -> None:
        """
        Inject an object into sandbox namespace.
        
        Parameters
        ----------
        name : str
            Variable name to inject
        value : Any
            Value to inject
        safe : bool, optional
            Whether to wrap value securely (default True)
        """
        with self._execution_lock:
            if safe:
                self.namespace[name] = value  # Will be wrapped automatically
            else:
                # Inject without wrapping (use with caution)
                super(RestrictedNamespace, self.namespace).__setitem__(name, value)
            
            self.logger.info(f"Injected '{name}' into sandbox")
    
    def inject_function(
        self,
        name: str,
        func: Callable,
        safe_wrapper: bool = True
    ) -> None:
        """
        Inject a function into sandbox.
        
        Parameters
        ----------
        name : str
            Function name
        func : Callable
            Function to inject
        safe_wrapper : bool, optional
            Whether to wrap with security checks
        """
        if safe_wrapper:
            @wraps(func)
            def safe_func(*args, **kwargs):
                # Validate arguments
                if len(args) > 100 or len(kwargs) > 100:
                    raise SandboxViolation("Too many arguments")
                return func(*args, **kwargs)
            
            self.inject(name, safe_func)
        else:
            self.inject(name, func)
    
    def inject_module(self, module_name: str, alias: Optional[str] = None) -> bool:
        """
        Import and inject a module into sandbox.
        
        Parameters
        ----------
        module_name : str
            Name of module to import
        alias : Optional[str], optional
            Alias for the module
            
        Returns
        -------
        bool
            True if module was injected successfully
        """
        if not self.config.is_module_allowed(module_name):
            self.logger.warning(f"Module '{module_name}' is not allowed")
            return False
        
        try:
            module = __import__(module_name)
            inject_name = alias or module_name.split('.')[0]
            self.inject(inject_name, module)
            self.logger.info(f"Injected module '{module_name}' as '{inject_name}'")
            return True
        except ImportError as e:
            self.logger.error(f"Failed to import '{module_name}': {e}")
            return False
    
    def get_namespace_copy(self, safe: bool = True) -> Dict[str, Any]:
        """
        Get a copy of the sandbox namespace.
        
        Parameters
        ----------
        safe : bool, optional
            Whether to unwrap secure proxies (default True)
            
        Returns
        -------
        Dict[str, Any]
            Copy of namespace
        """
        with self._execution_lock:
            if safe:
                result = {}
                for key, value in self.namespace.items():
                    if isinstance(value, SecureProxy):
                        result[key] = value._obj
                    elif isinstance(value, (SecureList, SecureTuple, SecureSet, SecureDict)):
                        result[key] = value._obj if hasattr(value, '_obj') else value
                    else:
                        result[key] = value
                return result
            else:
                return dict(self.namespace)
    
    def get_variable(self, name: str) -> Optional[Any]:
        """
        Get a specific variable from sandbox.
        
        Parameters
        ----------
        name : str
            Variable name
            
        Returns
        -------
        Optional[Any]
            Variable value or None
        """
        try:
            value = self.namespace.get(name)
            if isinstance(value, SecureProxy):
                return value._obj
            return value
        except (KeyError, SandboxViolation):
            return None
    
    def set_variable(self, name: str, value: Any) -> None:
        """
        Set a variable in sandbox (alias for inject).
        
        Parameters
        ----------
        name : str
            Variable name
        value : Any
            Variable value
        """
        self.inject(name, value)
    
    def remove_variable(self, name: str) -> bool:
        """
        Remove a variable from sandbox.
        
        Parameters
        ----------
        name : str
            Variable name
            
        Returns
        -------
        bool
            True if variable was removed
        """
        with self._execution_lock:
            try:
                del self.namespace[name]
                return True
            except (KeyError, SandboxViolation):
                return False
    
    def clear_namespace(self, keep_builtins: bool = True) -> None:
        """
        Clear sandbox namespace.
        
        Parameters
        ----------
        keep_builtins : bool, optional
            Whether to keep builtins (default True)
        """
        with self._execution_lock:
            keys_to_keep = {'__builtins__', '__name__', '__doc__', '__sandbox_config__'} if keep_builtins else set()
            
            for key in list(self.namespace.keys()):
                if key not in keys_to_keep:
                    try:
                        del self.namespace[key]
                    except SandboxViolation:
                        pass  # Skip protected items
    
    def reset(self) -> None:
        """Reset sandbox to initial state."""
        with self._execution_lock:
            self.namespace = RestrictedNamespace(self.config)
            self.history.clear()
            self._audit_log.clear()
            self._execution_count = 0
            self.logger.info("Sandbox reset to initial state")
    
    def get_history(self) -> List[ExecutionResult]:
        """
        Get execution history.
        
        Returns
        -------
        List[ExecutionResult]
            Copy of execution history
        """
        return self.history.copy()
    
    def get_last_result(self) -> Optional[ExecutionResult]:
        """
        Get last execution result.
        
        Returns
        -------
        Optional[ExecutionResult]
            Last result or None
        """
        return self.history[-1] if self.history else None
    
    def get_audit_log(self) -> List[Dict[str, Any]]:
        """
        Get audit log of security events.
        
        Returns
        -------
        List[Dict[str, Any]]
            Audit log entries
        """
        return [event.to_dict() for event in self._audit_log]
    
    def save_state(self, path: Union[str, Path]) -> None:
        """
        Save sandbox state to file.
        
        Parameters
        ----------
        path : Union[str, Path]
            Path to save state
        """
        path = Path(path)
        
        state = {
            'config': self.config.to_dict(),
            'namespace': self.get_namespace_copy(),
            'execution_count': self._execution_count,
            'history': [
                {
                    'success': r.success,
                    'result': str(r.result) if r.result else None,
                    'execution_time': r.execution_time,
                    'memory_used': r.memory_used,
                    'output': r.output,
                    'error': str(r.error) if r.error else None
                }
                for r in self.history[-10:]  # Save last 10 executions
            ]
        }
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, default=str)
        
        self.logger.info(f"Sandbox state saved to {path}")
    
    def load_state(self, path: Union[str, Path]) -> None:
        """
        Load sandbox state from file.
        
        Parameters
        ----------
        path : Union[str, Path]
            Path to state file
        """
        path = Path(path)
        
        with open(path, 'r', encoding='utf-8') as f:
            state = json.load(f)
        
        # Reset current state
        self.reset()
        
        # Restore namespace
        for key, value in state.get('namespace', {}).items():
            if key not in {'__builtins__', '__name__', '__doc__'}:
                self.inject(key, value, safe=False)
        
        self._execution_count = state.get('execution_count', 0)
        
        self.logger.info(f"Sandbox state loaded from {path}")
    
    def __enter__(self) -> 'Sandbox':
        """Enter context manager."""
        return self
    
    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType]
    ) -> None:
        """Exit context manager with cleanup."""
        self.reset()
    
    def __repr__(self) -> str:
        """Return string representation."""
        return f"<Sandbox level={self.config.security_level.name} executions={self._execution_count}>"
    
    def __str__(self) -> str:
        """Return user-friendly string."""
        return f"Secure Python Sandbox ({self.config.security_level.name} level)"


# Pre-configured sandbox instances
def create_math_sandbox() -> Sandbox:
    """Create sandbox with math and statistics modules."""
    config = SandboxConfig.from_profile(SecurityLevel.STRICT)
    config.allow_module("math")
    config.allow_module("statistics")
    return Sandbox(config)


def create_data_sandbox() -> Sandbox:
    """Create sandbox for data processing."""
    config = SandboxConfig.from_profile(SecurityLevel.STANDARD)
    config.allow_module("json")
    config.allow_module("csv")
    config.allow_module("collections")
    config.allow_module("itertools")
    return Sandbox(config)


def create_test_sandbox() -> Sandbox:
    """Create sandbox for testing purposes."""
    config = SandboxConfig.from_profile(SecurityLevel.MINIMAL)
    config.resource_limits.cpu_time_seconds = 1.0
    config.resource_limits.memory_mb = 50
    return Sandbox(config)


# Export public interface
__all__ = [
    'Sandbox',
    'SandboxConfig',
    'SecurityLevel',
    'ResourceLimits',
    'SandboxViolation',
    'SandboxTimeoutError',
    'SandboxMemoryError',
    'SandboxResourceError',
    'ExecutionResult',
    'ExecutionEvent',
    'ExecutionEventType',
    'SecureProxy',
    'RestrictedNamespace',
    'ResourceMonitor',
    'ASTSecurityValidator',
    'create_math_sandbox',
    'create_data_sandbox',
    'create_test_sandbox',
]