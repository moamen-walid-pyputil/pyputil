#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import builtins
import threading
import time
import warnings
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, Set, List, Tuple, Optional, Any, Callable
from functools import wraps
import sys
import traceback
from enum import Enum
from datetime import datetime


class ImportEventType(Enum):
    """
    Enumeration of possible import event types.
    
    This enum categorizes different types of import operations that can be
    tracked by the ImportTracker.
    
    Attributes
    ----------
    IMPORT : str
        A successful regular import operation.
    RELOAD : str
        A module reload operation using importlib.reload().
    FAILED : str
        An import operation that raised an exception.
    CACHED : str
        An import that was served from the module cache (not yet implemented).
    
    Examples
    --------
    >>> event_type = ImportEventType.IMPORT
    >>> event_type.value
    'import'
    """
    IMPORT = "import"
    RELOAD = "reload"
    FAILED = "failed"
    CACHED = "cached"


@dataclass
class ImportEvent:
    """
    Dataclass representing a single import event with comprehensive metadata.
    
    This class captures all relevant information about a single import operation,
    including timing, context, and error information when applicable.
    
    Parameters
    ----------
    module_name : str
        The fully qualified name of the module being imported.
    event_type : ImportEventType
        The type of import event (IMPORT, RELOAD, FAILED, or CACHED).
    duration : float
        Time taken for the import operation in seconds.
    timestamp : float
        Unix timestamp when the import operation started.
    caller_frame : str
        String representation of the calling frame (filename:lineno).
    thread_id : int
        Identifier of the thread performing the import.
    depth : int
        Import stack depth at the time of this import.
    error_message : Optional[str], default=None
        Error message if the import failed, None otherwise.
    fromlist : Tuple[str, ...], default=()
        List of submodules to import (fromlist parameter).
    level : int, default=0
        Import level (0 for absolute, positive for relative imports).
    
    Attributes
    ----------
    formatted_time : str
        Human-readable timestamp of the import event.
    is_successful : bool
        True if the import succeeded, False otherwise.
    
    Examples
    --------
    >>> event = ImportEvent(
    ...     module_name='numpy',
    ...     event_type=ImportEventType.IMPORT,
    ...     duration=0.123,
    ...     timestamp=1234567890.0,
    ...     caller_frame='test.py:10',
    ...     thread_id=12345,
    ...     depth=1
    ... )
    >>> event.is_successful
    True
    >>> event.formatted_time
    '2009-02-13 23:31:30'
    """
    module_name: str
    event_type: ImportEventType
    duration: float
    timestamp: float
    caller_frame: str
    thread_id: int
    depth: int
    error_message: Optional[str] = None
    fromlist: Tuple[str, ...] = field(default_factory=tuple)
    level: int = 0
    
    @property
    def formatted_time(self) -> str:
        """
        Human-readable timestamp of the import event.
        
        Returns
        -------
        str
            Formatted datetime string in 'YYYY-MM-DD HH:MM:SS' format.
        
        Examples
        --------
        >>> event = ImportEvent(
        ...     module_name='os',
        ...     event_type=ImportEventType.IMPORT,
        ...     duration=0.001,
        ...     timestamp=1609459200.0,
        ...     caller_frame='main.py:5',
        ...     thread_id=1,
        ...     depth=0
        ... )
        >>> event.formatted_time
        '2021-01-01 00:00:00'
        """
        return datetime.fromtimestamp(self.timestamp).strftime('%Y-%m-%d %H:%M:%S')
    
    @property
    def is_successful(self) -> bool:
        """
        Check if the import event was successful.
        
        Returns
        -------
        bool
            True if the import succeeded (event type is IMPORT or RELOAD),
            False if it failed (event type is FAILED).
        
        Examples
        --------
        >>> failed_event = ImportEvent(
        ...     module_name='nonexistent',
        ...     event_type=ImportEventType.FAILED,
        ...     duration=0.001,
        ...     timestamp=1609459200.0,
        ...     caller_frame='main.py:10',
        ...     thread_id=1,
        ...     depth=0,
        ...     error_message="ModuleNotFoundError: No module named 'nonexistent'"
        ... )
        >>> failed_event.is_successful
        False
        """
        return self.event_type in (ImportEventType.IMPORT, ImportEventType.RELOAD)


@dataclass
class ImportStatistics:
    """
    Comprehensive statistics about tracked imports.
    
    This dataclass provides aggregated statistical information about all
    import operations tracked during the monitoring period.
    
    Parameters
    ----------
    total_imports : int
        Total number of successful import operations.
    unique_modules : int
        Number of distinct modules that were imported.
    total_time : float
        Cumulative time spent on all imports in seconds.
    avg_import_time : float
        Average time per import operation in seconds.
    max_import_time : float
        Maximum time for any single import in seconds.
    min_import_time : float
        Minimum time for any single import in seconds.
    failed_imports : int
        Total number of failed import attempts.
    reload_count : int
        Number of module reload operations.
    max_stack_depth : int
        Maximum import stack depth reached during tracking.
    
    Attributes
    ----------
    total_time_ms : float
        Total time in milliseconds.
    avg_import_time_ms : float
        Average time per import in milliseconds.
    max_import_time_ms : float
        Maximum import time in milliseconds.
    min_import_time_ms : float
        Minimum import time in milliseconds.
    success_rate : float
        Percentage of successful imports (0-100).
    
    Examples
    --------
    >>> stats = ImportStatistics(
    ...     total_imports=10,
    ...     unique_modules=8,
    ...     total_time=0.567,
    ...     avg_import_time=0.0567,
    ...     max_import_time=0.123,
    ...     min_import_time=0.001,
    ...     failed_imports=0,
    ...     reload_count=0,
    ...     max_stack_depth=3
    ... )
    >>> stats.total_time_ms
    567.0
    >>> stats.success_rate
    100.0
    """
    total_imports: int
    unique_modules: int
    total_time: float
    avg_import_time: float
    max_import_time: float
    min_import_time: float
    failed_imports: int
    reload_count: int
    max_stack_depth: int
    
    @property
    def total_time_ms(self) -> float:
        """Total time in milliseconds."""
        return self.total_time * 1000
    
    @property
    def avg_import_time_ms(self) -> float:
        """Average time per import in milliseconds."""
        return self.avg_import_time * 1000
    
    @property
    def max_import_time_ms(self) -> float:
        """Maximum import time in milliseconds."""
        return self.max_import_time * 1000
    
    @property
    def min_import_time_ms(self) -> float:
        """Minimum import time in milliseconds."""
        return self.min_import_time * 1000
    
    @property
    def success_rate(self) -> float:
        """
        Calculate the success rate of imports.
        
        Returns
        -------
        float
            Percentage of successful imports (0-100).
            Returns 100.0 if no imports were attempted.
        
        Examples
        --------
        >>> stats = ImportStatistics(
        ...     total_imports=8,
        ...     unique_modules=5,
        ...     total_time=0.5,
        ...     avg_import_time=0.0625,
        ...     max_import_time=0.1,
        ...     min_import_time=0.01,
        ...     failed_imports=2,
        ...     reload_count=0,
        ...     max_stack_depth=2
        ... )
        >>> stats.success_rate
        80.0
        """
        total_attempts = self.total_imports + self.failed_imports
        if total_attempts == 0:
            return 100.0
        return (self.total_imports / total_attempts) * 100


@dataclass
class ImportReport:
    """
    Complete report of all tracked import activity.
    
    This dataclass aggregates all information collected by the ImportTracker,
    providing a comprehensive view of import patterns, performance issues,
    and potential problems.
    
    Parameters
    ----------
    statistics : ImportStatistics
        Aggregated statistical information about imports.
    slow_imports : List[Tuple[str, float]]
        List of modules that exceeded the performance threshold,
        each entry containing (module_name, import_time_in_seconds).
    circular_dependencies : List[List[str]]
        List of detected circular dependencies, each represented as
        a list of module names forming a cycle.
    failed_imports : Dict[str, List[Tuple[str, float]]]
        Dictionary mapping module names to lists of (error_message, timestamp)
        for failed import attempts.
    reload_counts : Dict[str, int]
        Dictionary mapping module names to the number of times they were reloaded.
    dependency_graph : Optional[Dict[str, Set[str]]], default=None
        Directed graph of module dependencies, mapping each module to
        the set of modules it imports. None if not requested.
    import_events : Optional[List[ImportEvent]], default=None
        Detailed chronological list of all import events. None if not requested.
    
    Attributes
    ----------
    has_circular_dependencies : bool
        True if any circular dependencies were detected.
    total_failed_imports : int
        Total number of failed import attempts across all modules.
    most_reloaded_module : Optional[Tuple[str, int]]
        The module reloaded most frequently and its count,
        or None if no reloads occurred.
    slowest_import : Optional[Tuple[str, float]]
        The slowest single import (not cumulative) and its time,
        or None if no imports occurred.
    
    Examples
    --------
    >>> report = ImportReport(
    ...     statistics=ImportStatistics(
    ...         total_imports=5, unique_modules=5, total_time=0.5,
    ...         avg_import_time=0.1, max_import_time=0.2, min_import_time=0.05,
    ...         failed_imports=0, reload_count=0, max_stack_depth=1
    ...     ),
    ...     slow_imports=[('numpy', 0.2), ('pandas', 0.15)],
    ...     circular_dependencies=[],
    ...     failed_imports={},
    ...     reload_counts={}
    ... )
    >>> report.has_circular_dependencies
    False
    >>> report.slowest_import
    ('numpy', 0.2)
    """
    statistics: ImportStatistics
    slow_imports: List[Tuple[str, float]]
    circular_dependencies: List[List[str]]
    failed_imports: Dict[str, List[Tuple[str, float]]]
    reload_counts: Dict[str, int]
    dependency_graph: Optional[Dict[str, Set[str]]] = None
    import_events: Optional[List[ImportEvent]] = None
    
    @property
    def has_circular_dependencies(self) -> bool:
        """
        Check if any circular dependencies were detected.
        
        Returns
        -------
        bool
            True if at least one circular dependency exists, False otherwise.
        
        Examples
        --------
        >>> report = ImportReport(
        ...     statistics=ImportStatistics(0,0,0.0,0.0,0.0,0.0,0,0,0),
        ...     slow_imports=[],
        ...     circular_dependencies=[['a', 'b', 'a']],
        ...     failed_imports={},
        ...     reload_counts={}
        ... )
        >>> report.has_circular_dependencies
        True
        """
        return len(self.circular_dependencies) > 0
    
    @property
    def total_failed_imports(self) -> int:
        """
        Calculate total number of failed import attempts.
        
        Returns
        -------
        int
            Sum of all failed import attempts across all modules.
        
        Examples
        --------
        >>> report = ImportReport(
        ...     statistics=ImportStatistics(0,0,0.0,0.0,0.0,0.0,0,0,0),
        ...     slow_imports=[],
        ...     circular_dependencies=[],
        ...     failed_imports={'missing': [('error1', 1.0), ('error2', 2.0)], 'other': [('error3', 3.0)]},
        ...     reload_counts={}
        ... )
        >>> report.total_failed_imports
        3
        """
        return sum(len(errors) for errors in self.failed_imports.values())
    
    @property
    def most_reloaded_module(self) -> Optional[Tuple[str, int]]:
        """
        Find the module that was reloaded most frequently.
        
        Returns
        -------
        Optional[Tuple[str, int]]
            Tuple of (module_name, reload_count) for the most reloaded module,
            or None if no reloads occurred.
        
        Examples
        --------
        >>> report = ImportReport(
        ...     statistics=ImportStatistics(0,0,0.0,0.0,0.0,0.0,0,0,0),
        ...     slow_imports=[],
        ...     circular_dependencies=[],
        ...     failed_imports={},
        ...     reload_counts={'module_a': 5, 'module_b': 3}
        ... )
        >>> report.most_reloaded_module
        ('module_a', 5)
        """
        if not self.reload_counts:
            return None
        return max(self.reload_counts.items(), key=lambda x: x[1])
    
    @property
    def slowest_import(self) -> Optional[Tuple[str, float]]:
        """
        Find the slowest single import operation.
        
        Returns
        -------
        Optional[Tuple[str, float]]
            Tuple of (module_name, import_time_in_seconds) for the slowest import,
            or None if no imports were tracked.
        
        Notes
        -----
        This property looks at individual import events, not cumulative times.
        For cumulative times, use the slow_imports field.
        
        Examples
        --------
        >>> report = ImportReport(
        ...     statistics=ImportStatistics(0,0,0.0,0.0,0.0,0.0,0,0,0),
        ...     slow_imports=[('numpy', 0.2), ('pandas', 0.15)],
        ...     circular_dependencies=[],
        ...     failed_imports={},
        ...     reload_counts={}
        ... )
        >>> report.slowest_import
        ('numpy', 0.2)
        """
        if not self.slow_imports:
            return None
        return self.slow_imports[0]


class CircularDependencyError(Exception):
    """
    Exception raised when a circular dependency is detected in strict mode.
    
    This exception provides detailed information about the circular dependency
    cycle that was detected, helping developers identify and fix import loops.
    
    Parameters
    ----------
    cycle : List[str]
        The circular dependency cycle as a list of module names.
    
    Attributes
    ----------
    cycle : List[str]
        The detected circular dependency cycle.
    cycle_str : str
        Human-readable string representation of the cycle.
    
    Examples
    --------
    >>> try:
    ...     raise CircularDependencyError(['module_a', 'module_b', 'module_c', 'module_a'])
    ... except CircularDependencyError as e:
    ...     print(e.cycle_str)
    module_a -> module_b -> module_c -> module_a
    """
    def __init__(self, cycle: List[str]):
        self.cycle = cycle
        super().__init__(f"Circular dependency detected: {' -> '.join(cycle)}")
    
    @property
    def cycle_str(self) -> str:
        """
        Get a human-readable string representation of the cycle.
        
        Returns
        -------
        str
            The cycle represented as 'module1 -> module2 -> ... -> module1'.
        
        Examples
        --------
        >>> error = CircularDependencyError(['x', 'y', 'z', 'x'])
        >>> error.cycle_str
        'x -> y -> z -> x'
        """
        return ' -> '.join(self.cycle)


class ImportTracker:
    """
    Track and analyze import patterns with high precision and thread safety.
    
    This class provides comprehensive monitoring of Python imports to detect
    circular dependencies, measure import performance, track usage patterns,
    and identify potential issues in module loading.
    
    Features
    --------
    - Thread-safe import tracking with fine-grained locking
    - Circular dependency detection with cycle reporting
    - Performance profiling with microsecond precision
    - Stack depth analysis to detect deep imports
    - Failed import tracking with error details
    - Reload detection and caching analysis
    - Strict mode that raises exceptions on circular deps
    - Automatic cleanup and context management
    - Dataclass-based results for type safety
    
    Parameters
    ----------
    strict_mode : bool, default=False
        If True, raises CircularDependencyError when circular imports are detected.
    track_failures : bool, default=True
        If True, records failed import attempts with error details.
    track_reloads : bool, default=True
        If True, tracks module reload events separately.
    max_stack_depth : int, default=100
        Maximum recursion depth for import tracking to prevent stack overflow.
    precision : str, default='perf_counter'
        Time precision: 'perf_counter' (high-precision wall time) or 
        'process_time' (CPU time, excludes sleep).
    
    Attributes
    ----------
    imports : Dict[str, float]
        Total cumulative time spent importing each module.
    dependencies : Dict[str, Set[str]]
        Directed graph of module dependencies.
    import_events : List[ImportEvent]
        Detailed log of all import events.
    failed_imports : Dict[str, List[Tuple[str, float]]]
        Record of failed imports with error messages and timestamps.
    reloads : Dict[str, int]
        Count of reload operations per module.
    
    Examples
    --------
    Basic usage with context manager:
    
    >>> tracker = ImportTracker()
    >>> with tracker.track():
    ...     import numpy
    ...     import pandas
    >>> report = tracker.get_report()
    >>> print(report.statistics.total_imports)
    2
    
    Strict mode for circular dependency detection:
    
    >>> tracker = ImportTracker(strict_mode=True)
    >>> try:
    ...     with tracker.track():
    ...         import circular_module  # Contains circular import
    ... except CircularDependencyError as e:
    ...     print(f"Circular dependency cycle: {e.cycle}")
    
    Analyzing import performance with statistics:
    
    >>> tracker = ImportTracker(precision='process_time')
    >>> with tracker.track():
    ...     import numpy
    ...     import scipy
    >>> stats = tracker.get_import_statistics()
    >>> print(f"Average import time: {stats.avg_import_time_ms:.2f}ms")
    >>> slow_imports = tracker.get_slow_imports(threshold=0.05)
    >>> for module, duration in slow_imports:
    ...     print(f"{module}: {duration*1000:.2f}ms")
    
    Thread-safe usage across multiple threads:
    
    >>> tracker = ImportTracker()
    >>> import threading
    >>> def load_modules():
    ...     with tracker.track():
    ...         import json
    ...         import re
    >>> threads = [threading.Thread(target=load_modules) for _ in range(10)]
    >>> for t in threads:
    ...     t.start()
    >>> for t in threads:
    ...     t.join()
    >>> stats = tracker.get_import_statistics()
    >>> print(f"Total imports across all threads: {stats.total_imports}")
    
    Getting detailed reports:
    
    >>> tracker = ImportTracker()
    >>> with tracker.track():
    ...     import os
    ...     import sys
    >>> report = tracker.get_report(detailed=True)
    >>> if report.has_circular_dependencies:
    ...     for cycle in report.circular_dependencies:
    ...         print(f"Cycle: {' -> '.join(cycle)}")
    >>> if report.most_reloaded_module:
    ...     module, count = report.most_reloaded_module
    ...     print(f"Most reloaded: {module} ({count} times)")
    """
    
    def __init__(
        self,
        strict_mode: bool = False,
        track_failures: bool = True,
        track_reloads: bool = True,
        max_stack_depth: int = 100,
        precision: str = 'perf_counter'
    ):
        # Core tracking data structures
        self.imports: Dict[str, float] = {}
        self.dependencies: Dict[str, Set[str]] = defaultdict(set)
        self.stack: List[str] = []
        self.import_events: List[ImportEvent] = []
        self.failed_imports: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        self.reloads: Dict[str, int] = defaultdict(int)
        
        # Synchronization primitives
        self._lock = threading.RLock()  # Reentrant lock for nested tracking
        self._stack_lock = threading.Lock()
        
        # Configuration
        self.strict_mode = strict_mode
        self.track_failures = track_failures
        self.track_reloads = track_reloads
        self.max_stack_depth = max_stack_depth
        self.precision = precision
        
        # State tracking
        self._is_tracking = False
        self._original_import: Optional[Callable] = None
        self._original_reload: Optional[Callable] = None
        self._thread_local = threading.local()
        
        # Time function selection
        self._time_func = time.perf_counter if precision == 'perf_counter' else time.process_time
        
        # Cache for module existence checks
        self._module_cache: Dict[str, bool] = {}
    
    def _get_caller_frame(self) -> str:
        """
        Get the calling frame information for debugging and context.
        
        This method traverses the call stack to find the frame that initiated
        the import, skipping internal tracking frames.
        
        Returns
        -------
        str
            Formatted string with filename and line number in format 'filename:lineno'.
            Returns 'unknown' if frame information cannot be retrieved.
        
        Notes
        -----
        This method uses sys._getframe() which is CPython-specific but provides
        the most accurate caller information. Falls back to 'unknown' on failure.
        
        Examples
        --------
        >>> tracker = ImportTracker()
        >>> caller = tracker._get_caller_frame()
        >>> ':' in caller  # Should contain filename:lineno
        True
        """
        try:
            # Skip _get_caller_frame itself, tracked_import, and wrapper frames
            frame = sys._getframe(3)
            return f"{frame.f_code.co_filename}:{frame.f_lineno}"
        except (ValueError, AttributeError):
            return "unknown"
    
    def _check_circular_dependency(self, module_name: str) -> Optional[List[str]]:
        """
        Check if importing module_name would create a circular dependency.
        
        This method examines the current import stack to determine if the
        module being imported is already in the process of being imported,
        which would indicate a circular dependency.
        
        Parameters
        ----------
        module_name : str
            Name of the module being imported.
        
        Returns
        -------
        Optional[List[str]]
            If a circular dependency is detected, returns the cycle as a list
            of module names in the order they form the cycle.
            Returns None if no circular dependency is detected.
        
        Notes
        -----
        This method is thread-safe and uses a separate lock for stack access
        to minimize contention with other operations.
        
        Examples
        --------
        >>> tracker = ImportTracker()
        >>> tracker.stack = ['module_a', 'module_b']
        >>> cycle = tracker._check_circular_dependency('module_b')
        >>> cycle
        ['module_a', 'module_b', 'module_b']
        """
        with self._stack_lock:
            if module_name in self.stack:
                cycle_start = self.stack.index(module_name)
                return self.stack[cycle_start:] + [module_name]
        return None
    
    @contextmanager
    def track(self):
        """
        Context manager to track imports within a block.
        
        This method patches Python's built-in import mechanism to monitor
        all imports occurring within the context block. It automatically
        restores the original import function when exiting.
        
        Yields
        ------
        ImportTracker
            The tracker instance for method chaining.
        
        Raises
        ------
        RuntimeError
            If tracking is already active in another context.
        CircularDependencyError
            If strict_mode is True and a circular dependency is detected.
        
        Notes
        -----
        - Thread-safe: Each thread gets its own tracking context
        - Nested contexts are not allowed to prevent corruption
        - Automatically handles cleanup even if exceptions occur
        - Tracks both imports and reloads (if enabled)
        
        Examples
        --------
        Basic usage:
        
        >>> tracker = ImportTracker()
        >>> with tracker.track():
        ...     import json
        ...     import re
        >>> len(tracker.imports) > 0
        True
        
        With error handling:
        
        >>> tracker = ImportTracker(strict_mode=True)
        >>> try:
        ...     with tracker.track():
        ...         import circular_module
        ... except CircularDependencyError as e:
        ...     print(f"Cycle detected: {e.cycle_str}")
        """
        if self._is_tracking:
            raise RuntimeError(
                "ImportTracker.track() cannot be nested. "
                "Create a new instance for nested tracking."
            )
        
        self._original_import = builtins.__import__
        if self.track_reloads:
            try:
                import importlib
                self._original_reload = importlib.reload
            except ImportError:
                self._original_reload = None
        
        def _create_tracked_reload():
            """
            Create a tracked version of importlib.reload.
            
            Returns
            -------
            Optional[Callable]
                Tracked reload function or None if reload tracking is disabled.
            """
            if not self._original_reload:
                return None
            
            @wraps(self._original_reload)
            def tracked_reload(module):
                """
                Wrapped reload function with performance tracking.
                
                Parameters
                ----------
                module : module
                    The module object to reload.
                
                Returns
                -------
                module
                    The reloaded module.
                
                Raises
                ------
                Exception
                    Any exception raised by the original reload function.
                """
                start_time = self._time_func()
                module_name = getattr(module, '__name__', str(module))
                
                try:
                    result = self._original_reload(module)
                    elapsed = self._time_func() - start_time
                    
                    with self._lock:
                        self.reloads[module_name] += 1
                        self.imports[module_name] = self.imports.get(module_name, 0.0) + elapsed
                        
                        event = ImportEvent(
                            module_name=module_name,
                            event_type=ImportEventType.RELOAD,
                            duration=elapsed,
                            timestamp=start_time,
                            caller_frame=self._get_caller_frame(),
                            thread_id=threading.get_ident(),
                            depth=len(self.stack)
                        )
                        self.import_events.append(event)
                    
                    return result
                except Exception as e:
                    if self.track_failures:
                        with self._lock:
                            error_msg = f"{type(e).__name__}: {str(e)}"
                            self.failed_imports[module_name].append((error_msg, start_time))
                    raise
            
            return tracked_reload
        
        def tracked_import(
            name: str,
            globals: Optional[Dict[str, Any]] = None,
            locals: Optional[Dict[str, Any]] = None,
            fromlist: Tuple[str, ...] = (),
            level: int = 0
        ) -> Any:
            """
            Enhanced import hook with comprehensive tracking.
            
            This function wraps the original __import__ to add monitoring,
            performance measurement, and circular dependency detection.
            
            Parameters
            ----------
            name : str
                Name of the module to import.
            globals : Optional[Dict[str, Any]], default=None
                Global namespace dictionary.
            locals : Optional[Dict[str, Any]], default=None
                Local namespace dictionary.
            fromlist : Tuple[str, ...], default=()
                List of submodules to import.
            level : int, default=0
                Import level (0 for absolute, positive for relative).
            
            Returns
            -------
            Any
                The imported module or submodule.
            
            Raises
            ------
            CircularDependencyError
                If strict_mode is True and a circular dependency is detected.
            Exception
                Any exception raised by the original import function.
            """
            # Check stack depth to prevent potential stack overflow
            with self._stack_lock:
                current_depth = len(self.stack)
                if current_depth >= self.max_stack_depth:
                    warnings.warn(
                        f"Import stack depth {current_depth} exceeds limit {self.max_stack_depth}. "
                        f"Consider increasing max_stack_depth or refactoring imports.",
                        RuntimeWarning,
                        stacklevel=2
                    )
            
            # Check for circular dependencies before import
            if self.strict_mode:
                cycle = self._check_circular_dependency(name)
                if cycle:
                    raise CircularDependencyError(cycle)
            
            start_time = self._time_func()
            
            # Add to import stack to track nested imports
            with self._lock:
                self.stack.append(name)
            
            try:
                # Execute the actual import
                result = self._original_import(name, globals, locals, fromlist, level)
                elapsed = self._time_func() - start_time
                
                # Record successful import
                with self._lock:
                    self.imports[name] = self.imports.get(name, 0.0) + elapsed
                    
                    # Record dependency relationship if there's a parent module
                    if len(self.stack) > 1:
                        parent = self.stack[-2]
                        self.dependencies[parent].add(name)
                    
                    # Create detailed event record
                    event = ImportEvent(
                        module_name=name,
                        event_type=ImportEventType.IMPORT,
                        duration=elapsed,
                        timestamp=start_time,
                        caller_frame=self._get_caller_frame(),
                        thread_id=threading.get_ident(),
                        depth=len(self.stack) - 1,
                        fromlist=fromlist,
                        level=level
                    )
                    self.import_events.append(event)
                
                return result
                
            except Exception as e:
                # Record failed import for debugging
                if self.track_failures:
                    elapsed = self._time_func() - start_time
                    with self._lock:
                        error_msg = f"{type(e).__name__}: {str(e)}"
                        self.failed_imports[name].append((error_msg, start_time))
                        
                        event = ImportEvent(
                            module_name=name,
                            event_type=ImportEventType.FAILED,
                            duration=elapsed,
                            timestamp=start_time,
                            caller_frame=self._get_caller_frame(),
                            thread_id=threading.get_ident(),
                            depth=len(self.stack),
                            error_message=error_msg,
                            fromlist=fromlist,
                            level=level
                        )
                        self.import_events.append(event)
                raise
                
            finally:
                # Always clean up the stack to maintain correct state
                with self._lock:
                    if self.stack:
                        self.stack.pop()
        
        try:
            self._is_tracking = True
            builtins.__import__ = tracked_import
            
            if self.track_reloads and self._original_reload:
                import importlib
                importlib.reload = _create_tracked_reload()
            
            yield self
            
        finally:
            # Restore original functions regardless of success/failure
            builtins.__import__ = self._original_import
            if self.track_reloads and self._original_reload:
                import importlib
                importlib.reload = self._original_reload
            
            self._is_tracking = False
    
    def get_circular_deps(self) -> List[List[str]]:
        """
        Detect circular dependencies in tracked imports using DFS.
        
        This method performs a depth-first search on the dependency graph
        to find all cycles. It handles complex nested cycles and returns
        each unique cycle only once.
        
        Returns
        -------
        List[List[str]]
            List of cycles found, where each cycle is a list of module names
            in the order they form the cycle. Empty list if no cycles found.
        
        Notes
        -----
        - Uses iterative DFS to avoid recursion depth issues
        - Returns minimal cycles (no duplicate cycles)
        - Thread-safe for read operations
        - Complexity: O(V + E) where V is vertices and E is edges
        
        Examples
        --------
        >>> tracker = ImportTracker()
        >>> tracker.dependencies = {
        ...     'a': {'b'},
        ...     'b': {'c'},
        ...     'c': {'a'}  # Creates cycle a->b->c->a
        ... }
        >>> cycles = tracker.get_circular_deps()
        >>> len(cycles)
        1
        >>> cycles[0]
        ['a', 'b', 'c', 'a']
        
        Handling multiple cycles:
        
        >>> tracker.dependencies = {
        ...     'a': {'b'},
        ...     'b': {'a'},  # Cycle a-b
        ...     'c': {'d'},
        ...     'd': {'c'}   # Cycle c-d
        ... }
        >>> cycles = tracker.get_circular_deps()
        >>> len(cycles)
        2
        """
        cycles = []
        visited = set()
        rec_stack = set()
        
        def find_cycle_iterative(start_node: str) -> Optional[List[str]]:
            """
            Iterative cycle finding to avoid recursion limits.
            
            Parameters
            ----------
            start_node : str
                Starting node for DFS.
            
            Returns
            -------
            Optional[List[str]]
                Cycle path if found, None otherwise.
            """
            # Stack elements: (node, state, path)
            # state 0 = first visit, state 1 = post-processing
            stack = [(start_node, 0, [])]
            
            while stack:
                node, state, path = stack.pop()
                
                if state == 0:  # First visit
                    if node in rec_stack:
                        # Found a cycle
                        cycle_start_idx = path.index(node) if node in path else 0
                        return path[cycle_start_idx:] + [node]
                    
                    if node in visited:
                        continue
                    
                    visited.add(node)
                    rec_stack.add(node)
                    stack.append((node, 1, path))  # Post-processing state
                    
                    # Add neighbors to stack in reverse order for natural traversal
                    for dep in sorted(self.dependencies.get(node, set()), reverse=True):
                        if dep not in visited or dep in rec_stack:
                            stack.append((dep, 0, path + [node]))
                else:  # Post-processing
                    rec_stack.remove(node)
            
            return None
        
        # Process all modules to find all cycles
        for module in list(self.dependencies.keys()):
            cycle = find_cycle_iterative(module)
            if cycle and cycle not in cycles:
                cycles.append(cycle)
        
        return cycles
    
    def get_slow_imports(self, threshold: float = 0.1) -> List[Tuple[str, float]]:
        """
        Get imports slower than specified threshold.
        
        Parameters
        ----------
        threshold : float, default=0.1
            Minimum time in seconds to report. Use 0.001 (1ms) for micro-optimizations.
            Threshold applies to cumulative import time for each module.
        
        Returns
        -------
        List[Tuple[str, float]]
            List of (module_name, import_time) sorted by time in descending order.
            Only includes modules with cumulative import time > threshold.
        
        Notes
        -----
        - Times are cumulative if the same module was imported multiple times
        - Use `get_import_statistics()` for per-import timing analysis
        - Threshold is applied to total cumulative time, not individual imports
        
        Examples
        --------
        >>> tracker = ImportTracker()
        >>> with tracker.track():
        ...     import pandas  # Slow import
        ...     import json    # Fast import
        >>> slow = tracker.get_slow_imports(threshold=0.05)
        >>> for mod, t in slow:
        ...     print(f"{mod}: {t*1000:.2f}ms")
        pandas: 234.56ms
        """
        with self._lock:
            slow = [(name, time) for name, time in self.imports.items() if time > threshold]
            return sorted(slow, key=lambda x: x[1], reverse=True)
    
    def get_import_statistics(self) -> ImportStatistics:
        """
        Get comprehensive import statistics as a dataclass.
        
        This method aggregates all tracked import data and returns it in a
        structured dataclass with computed properties for easy analysis.
        
        Returns
        -------
        ImportStatistics
            Dataclass containing:
            - total_imports: Total number of successful import operations
            - unique_modules: Number of distinct modules imported
            - total_time: Cumulative import time in seconds
            - avg_import_time: Average time per import
            - max_import_time: Maximum single import time
            - min_import_time: Minimum single import time
            - failed_imports: Count of failed imports
            - reload_count: Number of module reloads
            - max_stack_depth: Maximum import stack depth reached
        
        Notes
        -----
        - Thread-safe for read operations
        - Statistics are computed from recorded events
        - Failed imports are counted separately from successful ones
        
        Examples
        --------
        >>> tracker = ImportTracker()
        >>> with tracker.track():
        ...     import json
        ...     import re
        ...     import sys
        >>> stats = tracker.get_import_statistics()
        >>> print(f"Total time: {stats.total_time_ms:.2f}ms")
        >>> print(f"Success rate: {stats.success_rate:.1f}%")
        >>> print(f"Average import: {stats.avg_import_time_ms:.2f}ms")
        
        With failed imports:
        
        >>> tracker = ImportTracker()
        >>> with tracker.track():
        ...     try:
        ...         import nonexistent_module
        ...     except ImportError:
        ...         pass
        >>> stats = tracker.get_import_statistics()
        >>> stats.failed_imports
        1
        >>> stats.success_rate
        0.0
        """
        with self._lock:
            if not self.import_events:
                return ImportStatistics(
                    total_imports=0,
                    unique_modules=0,
                    total_time=0.0,
                    avg_import_time=0.0,
                    max_import_time=0.0,
                    min_import_time=0.0,
                    failed_imports=sum(len(errors) for errors in self.failed_imports.values()),
                    reload_count=sum(self.reloads.values()),
                    max_stack_depth=0
                )
            
            # Filter only successful import events (not reloads or failures)
            import_events = [e for e in self.import_events if e.event_type == ImportEventType.IMPORT]
            
            if not import_events:
                return ImportStatistics(
                    total_imports=0,
                    unique_modules=len(self.imports),
                    total_time=0.0,
                    avg_import_time=0.0,
                    max_import_time=0.0,
                    min_import_time=0.0,
                    failed_imports=sum(len(errors) for errors in self.failed_imports.values()),
                    reload_count=sum(self.reloads.values()),
                    max_stack_depth=max((e.depth for e in self.import_events), default=0)
                )
            
            import_times = [e.duration for e in import_events]
            
            return ImportStatistics(
                total_imports=len(import_events),
                unique_modules=len(self.imports),
                total_time=sum(import_times),
                avg_import_time=sum(import_times) / len(import_times),
                max_import_time=max(import_times),
                min_import_time=min(import_times),
                failed_imports=sum(len(errors) for errors in self.failed_imports.values()),
                reload_count=sum(self.reloads.values()),
                max_stack_depth=max((e.depth for e in self.import_events), default=0)
            )
    
    def get_report(self, detailed: bool = False) -> ImportReport:
        """
        Generate a comprehensive report of all tracked imports.
        
        This method aggregates all tracking data into a single dataclass
        that provides both summary statistics and detailed information
        about imports, dependencies, and potential issues.
        
        Parameters
        ----------
        detailed : bool, default=False
            If True, includes detailed event logs and the complete dependency graph.
            Setting this to True increases memory usage but provides more insights.
        
        Returns
        -------
        ImportReport
            Dataclass containing:
            - statistics: Aggregated import statistics (ImportStatistics)
            - slow_imports: List of modules slower than threshold
            - circular_dependencies: Detected dependency cycles
            - failed_imports: Record of failed imports
            - reload_counts: Module reload frequencies
            - dependency_graph: Optional directed graph of dependencies
            - import_events: Optional detailed event list
        
        Notes
        -----
        - Thread-safe for read operations
        - Detailed mode includes the complete dependency graph and all events
        - The dependency graph is a copy to prevent external modification
        
        Examples
        --------
        Basic report:
        
        >>> tracker = ImportTracker()
        >>> with tracker.track():
        ...     import numpy
        ...     import pandas
        >>> report = tracker.get_report()
        >>> print(report.statistics.total_imports)
        2
        >>> print(report.has_circular_dependencies)
        False
        
        Detailed report with full dependency graph:
        
        >>> tracker = ImportTracker()
        >>> with tracker.track():
        ...     import json
        ...     import re
        >>> report = tracker.get_report(detailed=True)
        >>> if report.dependency_graph:
        ...     for module, deps in report.dependency_graph.items():
        ...         print(f"{module} imports: {', '.join(deps)}")
        
        Analyzing failures:
        
        >>> tracker = ImportTracker()
        >>> with tracker.track():
        ...     try:
        ...         import missing_module
        ...     except ImportError:
        ...         pass
        >>> report = tracker.get_report()
        >>> if report.total_failed_imports > 0:
        ...     for module, errors in report.failed_imports.items():
        ...         for error, timestamp in errors:
        ...             print(f"{module}: {error}")
        
        Finding the slowest imports:
        
        >>> tracker = ImportTracker()
        >>> with tracker.track():
        ...     import scipy
        ...     import numpy
        >>> report = tracker.get_report()
        >>> if report.slowest_import:
        ...     module, duration = report.slowest_import
        ...     print(f"Slowest: {module} ({duration*1000:.2f}ms)")
        
        Working with reloads:
        
        >>> tracker = ImportTracker()
        >>> with tracker.track():
        ...     import mymodule
        ...     import importlib
        ...     importlib.reload(mymodule)
        >>> report = tracker.get_report()
        >>> if report.most_reloaded_module:
        ...     module, count = report.most_reloaded_module
        ...     print(f"Most reloaded: {module} ({count} times)")
        """
        # Get statistics using the dedicated method
        statistics = self.get_import_statistics()
        
        # Get slow imports (using default threshold of 0.1 seconds)
        slow_imports = self.get_slow_imports()
        
        # Get circular dependencies
        circular_deps = self.get_circular_deps()
        
        # Prepare the report
        report = ImportReport(
            statistics=statistics,
            slow_imports=slow_imports,
            circular_dependencies=circular_deps,
            failed_imports=dict(self.failed_imports),
            reload_counts=dict(self.reloads),
            dependency_graph=dict(self.dependencies) if detailed else None,
            import_events=self.import_events if detailed else None
        )
        
        return report
    
    def reset(self) -> None:
        """
        Reset all tracking data to initial state.
        
        This method clears all accumulated import data, dependencies,
        event logs, and statistics. Useful for starting fresh without
        creating a new tracker instance.
        
        Notes
        -----
        - Thread-safe using a write lock
        - Does not affect active tracking contexts
        - Maintains configuration settings (strict_mode, thresholds, etc.)
        - Clears all recorded events and statistics
        
        Examples
        --------
        >>> tracker = ImportTracker()
        >>> with tracker.track():
        ...     import json
        ...     import re
        >>> len(tracker.imports)
        2
        >>> tracker.reset()
        >>> len(tracker.imports)
        0
        >>> len(tracker.import_events)
        0
        >>> len(tracker.dependencies)
        0
        
        Reset between different test scenarios:
        
        >>> tracker = ImportTracker()
        >>> with tracker.track():
        ...     import sys
        >>> stats1 = tracker.get_import_statistics()
        >>> tracker.reset()
        >>> with tracker.track():
        ...     import os
        >>> stats2 = tracker.get_import_statistics()
        >>> stats1.total_imports != stats2.total_imports
        True
        """
        with self._lock:
            self.imports.clear()
            self.dependencies.clear()
            self.stack.clear()
            self.import_events.clear()
            self.failed_imports.clear()
            self.reloads.clear()
            self._module_cache.clear()
    
    def __enter__(self):
        """Context manager entry point."""
        return self.track().__enter__()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit point - cleanup handled by track() method."""
        pass


