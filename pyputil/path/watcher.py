#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import sys
import time
import threading
import logging
import hashlib
from pathlib import Path
from typing import Dict, List, Callable, Optional, Set, Union, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import importlib
import importlib.util
import traceback
from weakref import WeakSet

# Configure module logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WatchEventType(Enum):
    """
    Enumeration of possible file system watch events.
    
    Attributes
    ----------
    CREATED : str
        File was created
    MODIFIED : str
        File content was modified
    DELETED : str
        File was deleted
    RENAMED : str
        File was renamed or moved
    """
    
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass
class FileChangeEvent:
    """
    Data class representing a file system change event.
    
    This class encapsulates all information about a single file change
    event detected by the watcher.
    
    Parameters
    ----------
    event_type : WatchEventType
        Type of change that occurred
    file_path : Path
        Path object to the affected file
    module_name : Optional[str]
        Python module name if file is a Python module
    timestamp : float
        Time when the change was detected (seconds since epoch)
    old_path : Optional[Path], default=None
        Previous path for rename events
    file_size : Optional[int], default=None
        Size of the file in bytes
    content_hash : Optional[str], default=None
        Hash of file content for verification
        
    Examples
    --------
    >>> event = FileChangeEvent(
    ...     event_type=WatchEventType.MODIFIED,
    ...     file_path=Path('/project/module.py'),
    ...     module_name='myproject.module',
    ...     timestamp=time.time()
    ... )
    """
    
    event_type: WatchEventType
    file_path: Path
    module_name: Optional[str]
    timestamp: float
    old_path: Optional[Path] = None
    file_size: Optional[int] = None
    content_hash: Optional[str] = None


@dataclass
class FileInfo:
    """
    Data class storing comprehensive metadata about a watched file.
    
    This class maintains all relevant information about a file being
    monitored by the PackageWatcher.
    
    Parameters
    ----------
    file_path : Path
        Path object to the file
    last_modified : float
        Last modification timestamp (seconds since epoch)
    file_hash : str
        SHA-256 hash of file content for detecting actual changes
    module_name : Optional[str]
        Corresponding Python module import name
    exists : bool, default=True
        Whether the file currently exists on disk
    file_size : int, default=0
        Size of the file in bytes
    last_checked : float, default=0.0
        Timestamp of last check
    change_count : int, default=0
        Number of times this file has changed
    """
    
    file_path: Path
    last_modified: float
    file_hash: str
    module_name: Optional[str]
    exists: bool = True
    file_size: int = 0
    last_checked: float = 0.0
    change_count: int = 0


@dataclass
class ReloadResult:
    """
    Data class representing the result of a module reload operation.
    
    This class captures all details about a module reload attempt.
    
    Parameters
    ----------
    module_name : str
        Name of the module that was reloaded
    success : bool
        Whether the reload was successful
    timestamp : float
        When the reload was attempted
    error_message : Optional[str], default=None
        Error message if reload failed
    duration : float, default=0.0
        Time taken for the reload operation in seconds
    affected_modules : List[str], default=field(default_factory=list)
        List of modules that were affected by this reload
    """
    
    module_name: str
    success: bool
    timestamp: float
    error_message: Optional[str] = None
    duration: float = 0.0
    affected_modules: List[str] = field(default_factory=list)


@dataclass
class WatcherStatistics:
    """
    Data class for watcher performance and activity statistics.
    
    This class tracks various metrics about the watcher's operation.
    
    Parameters
    ----------
    scans_performed : int, default=0
        Number of directory scans performed
    changes_detected : int, default=0
        Number of file changes detected
    reloads_attempted : int, default=0
        Number of reload attempts made
    reloads_succeeded : int, default=0
        Number of successful reloads
    reloads_failed : int, default=0
        Number of failed reload attempts
    errors_encountered : int, default=0
        Number of errors encountered
    total_watch_time : float, default=0.0
        Total time watcher has been running in seconds
    files_watched : int, default=0
        Current number of files being watched
    last_scan_duration : float, default=0.0
        Duration of last scan in seconds
    """
    
    scans_performed: int = 0
    changes_detected: int = 0
    reloads_attempted: int = 0
    reloads_succeeded: int = 0
    reloads_failed: int = 0
    errors_encountered: int = 0
    total_watch_time: float = 0.0
    files_watched: int = 0
    last_scan_duration: float = 0.0


class PackageWatcher:
    """
    Package watcher with comprehensive hot reload capabilities.
    
    This class provides robust file system monitoring for Python packages,
    with support for polling-based watching, content-based change detection,
    module dependency tracking, and flexible callback mechanisms.
    
    Features
    --------
    - Thread-safe operations with proper locking mechanisms
    - Content-based change detection using SHA-256 hashing
    - Module dependency tracking and intelligent reload ordering
    - Comprehensive error handling and logging
    - Support for nested packages and submodules
    - Graceful shutdown and resource cleanup
    - Change batching to avoid redundant reloads
    - Callback system for change notifications
    - Performance statistics tracking
    
    Parameters
    ----------
    package_name : str
        Name of the Python package to watch
    poll_interval : float, default=1.0
        Time in seconds between polling checks
    use_content_hashing : bool, default=True
        Whether to use file content hashing for change detection
    batch_changes : bool, default=True
        Whether to batch multiple changes within interval
    batch_interval : float, default=0.1
        Time in seconds to wait for batching changes
    track_dependencies : bool, default=True
        Whether to track module dependencies for intelligent reloading
    max_reload_history : int, default=100
        Maximum number of reload history entries to keep
        
    Examples
    --------
    >>> watcher = PackageWatcher('mypackage', poll_interval=0.5)
    >>> watcher.start_watching()
    >>> 
    >>> @watcher.on_change
    ... def handle_change(module_name: str, event: FileChangeEvent):
    ...     print(f"Module {module_name} was {event.event_type.value}")
    >>> 
    >>> # Later: watcher.stop_watching()
    >>> stats = watcher.get_statistics()
    >>> print(f"Processed {stats.changes_detected} changes")
    
    Notes
    -----
    The watcher runs in a daemon thread, so it will not prevent the
    Python interpreter from exiting when the main thread terminates.
    """
    
    def __init__(
        self, 
        package_name: str, 
        poll_interval: float = 1.0,
        use_content_hashing: bool = True,
        batch_changes: bool = True,
        batch_interval: float = 0.1,
        track_dependencies: bool = True,
        max_reload_history: int = 100
    ):
        """
        Initialize the PackageWatcher instance.
        
        Parameters
        ----------
        package_name : str
            Name of the Python package to watch
        poll_interval : float, default=1.0
            Time in seconds between polling checks
        use_content_hashing : bool, default=True
            Whether to use file content hashing for change detection
        batch_changes : bool, default=True
            Whether to batch multiple changes within interval
        batch_interval : float, default=0.1
            Time in seconds to wait for batching changes
        track_dependencies : bool, default=True
            Whether to track module dependencies for intelligent reloading
        max_reload_history : int, default=100
            Maximum number of reload history entries to keep
            
        Raises
        ------
        ValueError
            If package_name is empty or invalid parameters provided
        ImportError
            If package cannot be found or imported
            
        Examples
        --------
        >>> watcher = PackageWatcher('myapp', poll_interval=0.5)
        >>> watcher = PackageWatcher('myapp', use_content_hashing=False)
        """
        if not package_name or not isinstance(package_name, str):
            raise ValueError(f"Invalid package_name: {package_name}")
        
        if poll_interval < 0.1:
            raise ValueError(f"poll_interval must be >= 0.1, got {poll_interval}")
        
        if batch_interval < 0.01:
            raise ValueError(f"batch_interval must be >= 0.01, got {batch_interval}")
        
        self.package_name = package_name
        self.poll_interval = poll_interval
        self.use_content_hashing = use_content_hashing
        self.batch_changes = batch_changes
        self.batch_interval = batch_interval
        self.track_dependencies = track_dependencies
        self.max_reload_history = max_reload_history
        
        # Core data structures
        self.watched_files: Dict[Path, FileInfo] = {}
        self.callbacks: List[Callable[[str, FileChangeEvent], None]] = []
        self.pending_changes: Dict[Path, List[FileChangeEvent]] = defaultdict(list)
        self.module_dependencies: Dict[str, Set[str]] = defaultdict(set)
        self.reload_history: List[ReloadResult] = []
        self.package_path: Optional[Path] = None
        self.package_modules: Dict[str, Path] = {}  # module_name -> file_path
        
        # Threading control
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._batch_thread: Optional[threading.Thread] = None
        self._lock: threading.RLock = threading.RLock()
        self._batch_lock: threading.Lock = threading.Lock()
        self._batch_condition: threading.Condition = threading.Condition(self._batch_lock)
        self._start_time: Optional[float] = None
        
        # Statistics
        self._stats: WatcherStatistics = WatcherStatistics()
        
        # Initialize package
        try:
            self._initialize_package()
            logger.info(f"PackageWatcher initialized for '{package_name}' at {self.package_path}")
        except Exception as e:
            logger.error(f"Failed to initialize package watcher: {e}")
            raise ImportError(f"Cannot locate or import package '{package_name}': {e}")
    
    def _initialize_package(self) -> None:
        """
        Initialize package information and scan for modules.
        
        This method finds the package location using importlib, validates
        it's a proper Python package, and initializes the module structure.
        
        Raises
        ------
        ImportError
            If package cannot be found or is not a valid package
            
        Examples
        --------
        >>> watcher = PackageWatcher('mypackage')
        >>> watcher._initialize_package()  # Called automatically in __init__
        """
        try:
            spec = importlib.util.find_spec(self.package_name)
            if spec is None or spec.origin is None:
                raise ImportError(f"Package '{self.package_name}' not found")
            
            # Get package directory as Path object
            origin_path = Path(spec.origin)
            if origin_path.name == '__init__.py':
                self.package_path = origin_path.parent
            else:
                self.package_path = origin_path.parent
            
            if not self.package_path.exists():
                raise ImportError(f"Package directory not found: {self.package_path}")
            
            # Verify it's a Python package
            init_file = self.package_path / '__init__.py'
            if not init_file.exists():
                logger.warning(
                    f"Directory may not be a proper Python package: "
                    f"missing __init__.py at {init_file}"
                )
            
            # Initial scan
            self._scan_package()
            
        except Exception as e:
            logger.error(f"Error initializing package: {e}")
            raise ImportError(f"Cannot initialize package '{self.package_name}': {e}")
    
    def _compute_file_hash(self, file_path: Path) -> str:
        """
        Compute SHA-256 hash of file content.
        
        Parameters
        ----------
        file_path : Path
            Path to the file to hash
            
        Returns
        -------
        str
            Hexadecimal SHA-256 hash string, empty string if file cannot be read
            
        Examples
        --------
        >>> watcher = PackageWatcher('mypackage')
        >>> hash_value = watcher._compute_file_hash(Path('file.py'))
        >>> len(hash_value)  # SHA-256 produces 64 hex characters
        64
        """
        if not file_path.exists():
            return ""
        
        try:
            hasher = hashlib.sha256()
            with open(file_path, 'rb') as f:
                # Read in chunks to handle large files
                for chunk in iter(lambda: f.read(65536), b''):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (IOError, OSError) as e:
            logger.debug(f"Cannot compute hash for {file_path}: {e}")
            return ""
    
    def _path_to_module(self, file_path: Path) -> Optional[str]:
        """
        Convert file system path to Python module import name.
        
        This method converts a file path to its corresponding Python
        module name relative to the package root.
        
        Parameters
        ----------
        file_path : Path
            Path object of the Python file
            
        Returns
        -------
        Optional[str]
            Python module name (e.g., 'mypackage.submodule'), or None if
            conversion fails or file is outside package
            
        Examples
        --------
        >>> watcher = PackageWatcher('mypackage')
        >>> module = watcher._path_to_module(Path('/project/mypackage/sub/module.py'))
        >>> print(module)
        'mypackage.sub.module'
        """
        if not self.package_path:
            return None
        
        try:
            # Get relative path from package root
            rel_path = file_path.relative_to(self.package_path)
            
            # Remove .py extension and split into parts
            parts = list(rel_path.with_suffix('').parts)
            
            # Handle __init__.py files
            if parts and parts[-1] == '__init__':
                parts.pop()
                if not parts:
                    return self.package_name
                return f"{self.package_name}.{'.'.join(parts)}"
            
            # Normal module
            return f"{self.package_name}.{'.'.join(parts)}"
            
        except ValueError:
            # File is outside package directory
            return None
    
    def _scan_package(self) -> None:
        """
        Scan package directory for Python files and update watched files.
        
        This method recursively scans the package directory, identifies all
        Python files, and updates the watched files dictionary with their
        metadata. It also detects deleted files and updates statistics.
        
        Notes
        -----
        This method is thread-safe and uses the instance lock.
        """
        if not self.package_path:
            logger.warning("Package path not set, cannot scan")
            return
        
        scan_start_time = time.time()
        
        with self._lock:
            # Find all Python files recursively
            py_files = list(self.package_path.rglob("*.py"))
            current_files: Dict[Path, FileInfo] = {}
            
            # Process each Python file
            for file_path in py_files:
                try:
                    abs_path = file_path.resolve()
                    module_name = self._path_to_module(abs_path)
                    
                    if module_name:
                        # Get file statistics
                        stat = abs_path.stat()
                        last_modified = stat.st_mtime
                        file_size = stat.st_size
                        file_hash = self._compute_file_hash(abs_path) if self.use_content_hashing else ""
                        
                        # Create FileInfo object
                        file_info = FileInfo(
                            file_path=abs_path,
                            last_modified=last_modified,
                            file_hash=file_hash,
                            module_name=module_name,
                            exists=True,
                            file_size=file_size,
                            last_checked=time.time(),
                            change_count=0
                        )
                        
                        current_files[abs_path] = file_info
                        self.package_modules[module_name] = abs_path
                        
                        # Check if this is a new file
                        if abs_path not in self.watched_files:
                            logger.debug(f"Discovered new file: {abs_path} -> {module_name}")
                            
                except (OSError, IOError) as e:
                    logger.warning(f"Cannot access file {file_path}: {e}")
                    self._stats.errors_encountered += 1
                    continue
            
            # Handle deleted files
            for old_path, old_info in list(self.watched_files.items()):
                if old_path not in current_files and old_info.exists:
                    logger.debug(f"File no longer exists: {old_path}")
                    
                    # Mark as deleted
                    current_files[old_path] = FileInfo(
                        file_path=old_path,
                        last_modified=old_info.last_modified,
                        file_hash="",
                        module_name=old_info.module_name,
                        exists=False,
                        change_count=old_info.change_count + 1
                    )
                    
                    # Create deletion event
                    if self.batch_changes:
                        event = FileChangeEvent(
                            event_type=WatchEventType.DELETED,
                            file_path=old_path,
                            module_name=old_info.module_name,
                            timestamp=time.time()
                        )
                        self.pending_changes[old_path].append(event)
            
            # Update watched files
            self.watched_files = current_files
            
            # Update statistics
            self._stats.scans_performed += 1
            self._stats.files_watched = len(self.watched_files)
            self._stats.last_scan_duration = time.time() - scan_start_time
            
            logger.debug(f"Scan complete: {len(self.watched_files)} files watched")
    
    def _check_changes(self) -> List[FileChangeEvent]:
        """
        Check for file changes and return detected change events.
        
        This method compares current file states with previously recorded
        states to detect modifications, creations, and deletions.
        
        Returns
        -------
        List[FileChangeEvent]
            List of detected change events
            
        Notes
        -----
        This method is thread-safe and uses content hashing when enabled
        to avoid false positives from unchanged files.
        """
        changes: List[FileChangeEvent] = []
        
        with self._lock:
            for file_path, current_info in self.watched_files.items():
                try:
                    if not file_path.exists():
                        if current_info.exists:
                            # File was deleted
                            event = FileChangeEvent(
                                event_type=WatchEventType.DELETED,
                                file_path=file_path,
                                module_name=current_info.module_name,
                                timestamp=time.time()
                            )
                            changes.append(event)
                            current_info.exists = False
                        continue
                    
                    # File exists, check for changes
                    stat = file_path.stat()
                    current_mtime = stat.st_mtime
                    current_size = stat.st_size
                    
                    # Check if modification time changed
                    if current_mtime != current_info.last_modified:
                        # Verify with content hash if enabled
                        if self.use_content_hashing:
                            current_hash = self._compute_file_hash(file_path)
                            if current_hash == current_info.file_hash:
                                # No actual content change
                                current_info.last_modified = current_mtime
                                continue
                        
                        # File has actually changed
                        event = FileChangeEvent(
                            event_type=WatchEventType.MODIFIED,
                            file_path=file_path,
                            module_name=current_info.module_name,
                            timestamp=time.time(),
                            file_size=current_size,
                            content_hash=self._compute_file_hash(file_path) if self.use_content_hashing else None
                        )
                        changes.append(event)
                        
                        # Update file info
                        current_info.last_modified = current_mtime
                        current_info.file_size = current_size
                        current_info.change_count += 1
                        if self.use_content_hashing:
                            current_info.file_hash = self._compute_file_hash(file_path)
                        
                        logger.debug(f"Detected change in {current_info.module_name}")
                        
                except (OSError, IOError) as e:
                    logger.warning(f"Error checking file {file_path}: {e}")
                    self._stats.errors_encountered += 1
                    continue
            
            self._stats.changes_detected += len(changes)
            
        return changes
    
    def _reload_module(self, module_name: str) -> ReloadResult:
        """
        Reload a specific Python module.
        
        This method attempts to reload a module using importlib.reload
        and tracks dependencies if enabled.
        
        Parameters
        ----------
        module_name : str
            Name of the module to reload
            
        Returns
        -------
        ReloadResult
            Object containing reload operation results
            
        Notes
        -----
        This method also updates module dependency information and
        maintains reload history.
        """
        start_time = time.time()
        affected_modules: List[str] = []
        
        try:
            if module_name not in sys.modules:
                error_msg = f"Module {module_name} is not loaded"
                logger.warning(error_msg)
                return ReloadResult(
                    module_name=module_name,
                    success=False,
                    timestamp=time.time(),
                    error_message=error_msg,
                    duration=time.time() - start_time
                )
            
            # Get module and its dependencies before reload
            if self.track_dependencies:
                before_modules = set(sys.modules.keys())
            
            # Perform reload
            module = sys.modules[module_name]
            importlib.reload(module)
            
            # Track affected modules if tracking dependencies
            if self.track_dependencies:
                after_modules = set(sys.modules.keys())
                affected_modules = list(after_modules - before_modules)
                
                # Update dependency graph
                for affected in affected_modules:
                    self.module_dependencies[affected].add(module_name)
            
            duration = time.time() - start_time
            
            result = ReloadResult(
                module_name=module_name,
                success=True,
                timestamp=time.time(),
                duration=duration,
                affected_modules=affected_modules
            )
            
            self._stats.reloads_succeeded += 1
            logger.info(f"Successfully reloaded {module_name} in {duration:.3f}s")
            
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            
            result = ReloadResult(
                module_name=module_name,
                success=False,
                timestamp=time.time(),
                error_message=error_msg,
                duration=duration
            )
            
            self._stats.reloads_failed += 1
            logger.error(f"Failed to reload {module_name}: {e}")
        
        # Update reload history
        self.reload_history.append(result)
        if len(self.reload_history) > self.max_reload_history:
            self.reload_history.pop(0)
        
        self._stats.reloads_attempted += 1
        return result
    
    def _process_changes(self, changes: List[FileChangeEvent]) -> None:
        """
        Process detected changes and trigger reloads.
        
        This method processes a list of change events, determines which
        modules need reloading, and executes the reloads in the correct
        order based on dependencies.
        
        Parameters
        ----------
        changes : List[FileChangeEvent]
            List of change events to process
            
        Notes
        -----
        This method ensures modules are reloaded in dependency order
        and notifies all registered callbacks.
        """
        if not changes:
            return
        
        # Group changes by module
        modules_to_reload: Set[str] = set()
        for change in changes:
            if change.module_name and change.event_type != WatchEventType.DELETED:
                modules_to_reload.add(change.module_name)
        
        if not modules_to_reload:
            return
        
        # Sort modules by dependency depth (simple topological sort)
        if self.track_dependencies:
            reload_order: List[str] = []
            visited: Set[str] = set()
            
            def add_module(module: str, depth: int = 0):
                if module in visited:
                    return
                visited.add(module)
                
                # Add dependencies first
                for dep in self.module_dependencies.get(module, []):
                    if dep in modules_to_reload:
                        add_module(dep, depth + 1)
                
                reload_order.append((depth, module))
            
            for module in modules_to_reload:
                add_module(module)
            
            # Sort by depth (dependencies first)
            reload_order.sort(key=lambda x: x[0])
            sorted_modules = [module for _, module in reload_order]
        else:
            sorted_modules = list(modules_to_reload)
        
        # Reload modules
        for module_name in sorted_modules:
            # Execute callbacks before reload
            for change in changes:
                if change.module_name == module_name:
                    for callback in self.callbacks:
                        try:
                            callback(module_name, change)
                        except Exception as e:
                            logger.error(f"Callback error for {module_name}: {e}")
            
            # Reload the module
            result = self._reload_module(module_name)
            
            # Execute callbacks after reload if needed
            if not result.success and result.error_message:
                error_event = FileChangeEvent(
                    event_type=WatchEventType.MODIFIED,
                    file_path=Path(""),
                    module_name=module_name,
                    timestamp=time.time()
                )
                for callback in self.callbacks:
                    try:
                        callback(f"{module_name}_error", error_event)
                    except Exception:
                        pass
    
    def _watch_loop(self) -> None:
        """
        Main watching loop that continuously checks for changes.
        
        This method runs in a background thread and periodically scans
        for file changes. It handles change batching and processing.
        
        Notes
        -----
        This method runs until _running is set to False.
        """
        last_scan = time.time()
        
        while self._running:
            try:
                current_time = time.time()
                if current_time - last_scan >= self.poll_interval:
                    # Scan for changes
                    changes = self._check_changes()
                    
                    if changes:
                        if self.batch_changes:
                            # Batch changes with condition variable
                            with self._batch_lock:
                                for change in changes:
                                    self.pending_changes[change.file_path].append(change)
                                self._batch_condition.notify()
                        else:
                            # Process immediately
                            self._process_changes(changes)
                    
                    last_scan = current_time
                
                # Small sleep to prevent CPU spinning
                time.sleep(0.01)
                
            except Exception as e:
                logger.error(f"Error in watch loop: {e}")
                self._stats.errors_encountered += 1
                time.sleep(1)  # Back off on error
    
    def _batch_loop(self) -> None:
        """
        Background loop that processes batched change events.
        
        This method collects change events over a short interval and
        processes them together to avoid redundant reloads.
        
        Notes
        -----
        Only runs if batch_changes is True.
        """
        while self._running:
            try:
                with self._batch_lock:
                    # Wait for changes or timeout
                    self._batch_condition.wait(timeout=self.batch_interval)
                    
                    if not self.pending_changes:
                        continue
                    
                    # Collect all pending changes
                    all_changes: List[FileChangeEvent] = []
                    for changes in self.pending_changes.values():
                        all_changes.extend(changes)
                    
                    # Clear pending changes
                    self.pending_changes.clear()
                
                # Process batched changes
                if all_changes:
                    self._process_changes(all_changes)
                    
            except Exception as e:
                logger.error(f"Error in batch loop: {e}")
                self._stats.errors_encountered += 1
    
    def start_watching(self) -> None:
        """
        Start watching for changes in background threads.
        
        This method launches background threads to monitor the package
        for changes. It starts both the main watch loop and the batch
        processing loop if batching is enabled.
        
        Raises
        ------
        RuntimeError
            If watcher is already running
            
        Examples
        --------
        >>> watcher = PackageWatcher('mypackage')
        >>> watcher.start_watching()
        >>> # Watcher is now monitoring for changes
        """
        if self._running:
            raise RuntimeError("Watcher is already running")
        
        self._running = True
        self._start_time = time.time()
        
        # Start main watch thread
        self._thread = threading.Thread(
            target=self._watch_loop, 
            name=f"PackageWatcher-{self.package_name}",
            daemon=True
        )
        self._thread.start()
        
        # Start batch processing thread if enabled
        if self.batch_changes:
            self._batch_thread = threading.Thread(
                target=self._batch_loop,
                name=f"PackageWatcher-Batch-{self.package_name}",
                daemon=True
            )
            self._batch_thread.start()
        
        logger.info(f"Started watching package: {self.package_name}")
    
    def stop_watching(self, timeout: float = 5.0) -> None:
        """
        Stop watching for changes and clean up resources.
        
        This method stops the background threads and performs cleanup.
        It waits for threads to finish up to the specified timeout.
        
        Parameters
        ----------
        timeout : float, default=5.0
            Maximum time in seconds to wait for threads to finish
            
        Examples
        --------
        >>> watcher = PackageWatcher('mypackage')
        >>> watcher.start_watching()
        >>> # ... do work ...
        >>> watcher.stop_watching()
        """
        if not self._running:
            logger.debug("Watcher is not running")
            return
        
        self._running = False
        
        # Signal batch condition to wake up
        if self.batch_changes:
            with self._batch_lock:
                self._batch_condition.notify_all()
        
        # Wait for threads to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        
        if self._batch_thread and self._batch_thread.is_alive():
            self._batch_thread.join(timeout=timeout)
        
        # Update total watch time
        if self._start_time:
            self._stats.total_watch_time = time.time() - self._start_time
        
        logger.info(f"Stopped watching package: {self.package_name}")
    
    def on_change(self, callback: Callable[[str, FileChangeEvent], None]) -> Callable:
        """
        Decorator to register change callbacks.
        
        This method registers a callback function that will be called
        whenever a file change is detected. The callback receives the
        module name and the change event.
        
        Parameters
        ----------
        callback : Callable[[str, FileChangeEvent], None]
            Function to call on changes. Takes module_name (str) and
            event (FileChangeEvent) as arguments.
            
        Returns
        -------
        Callable
            The original callback function (for decorator use)
            
        Examples
        --------
        >>> watcher = PackageWatcher('mypackage')
        >>> 
        >>> @watcher.on_change
        ... def my_handler(module_name: str, event: FileChangeEvent):
        ...     print(f"Change detected: {module_name} - {event.event_type.value}")
        """
        self.callbacks.append(callback)
        logger.debug(f"Registered callback: {callback.__name__}")
        return callback
    
    def remove_callback(self, callback: Callable) -> bool:
        """
        Remove a previously registered callback.
        
        Parameters
        ----------
        callback : Callable
            The callback function to remove
            
        Returns
        -------
        bool
            True if callback was found and removed, False otherwise
            
        Examples
        --------
        >>> def handler(module, event):
        ...     print(f"Change: {module}")
        >>> 
        >>> watcher.on_change(handler)
        >>> watcher.remove_callback(handler)
        True
        """
        try:
            self.callbacks.remove(callback)
            logger.debug(f"Removed callback: {callback.__name__}")
            return True
        except ValueError:
            logger.warning(f"Callback {callback.__name__} not found")
            return False
    
    def force_scan(self) -> List[FileChangeEvent]:
        """
        Force an immediate scan for changes.
        
        This method performs an immediate scan of all watched files
        and returns any detected changes without waiting for the
        poll interval.
        
        Returns
        -------
        List[FileChangeEvent]
            List of detected change events
            
        Examples
        --------
        >>> watcher = PackageWatcher('mypackage')
        >>> changes = watcher.force_scan()
        >>> if changes:
        ...     print(f"Found {len(changes)} changes")
        """
        with self._lock:
            # Force a full scan
            self._scan_package()
            changes = self._check_changes()
            
            if changes and not self.batch_changes:
                self._process_changes(changes)
            
            return changes
    
    def get_statistics(self) -> WatcherStatistics:
        """
        Get current watcher statistics.
        
        Returns
        -------
        WatcherStatistics
            Object containing all watcher statistics
            
        Examples
        --------
        >>> watcher = PackageWatcher('mypackage')
        >>> watcher.start_watching()
        >>> time.sleep(10)
        >>> stats = watcher.get_statistics()
        >>> print(f"Scans: {stats.scans_performed}, Changes: {stats.changes_detected}")
        """
        # Update files watched count
        with self._lock:
            self._stats.files_watched = len(self.watched_files)
        
        return self._stats
    
    def get_reload_history(self) -> List[ReloadResult]:
        """
        Get the history of module reload attempts.
        
        Returns
        -------
        List[ReloadResult]
            List of reload results in chronological order
            
        Examples
        --------
        >>> watcher = PackageWatcher('mypackage')
        >>> history = watcher.get_reload_history()
        >>> for result in history:
        ...     print(f"{result.module_name}: {'Success' if result.success else 'Failed'}")
        """
        return self.reload_history.copy()
    
    def get_module_dependencies(self, module_name: str) -> Set[str]:
        """
        Get dependencies for a specific module.
        
        Parameters
        ----------
        module_name : str
            Name of the module to query
            
        Returns
        -------
        Set[str]
            Set of module names that depend on the given module
            
        Examples
        --------
        >>> watcher = PackageWatcher('mypackage')
        >>> deps = watcher.get_module_dependencies('mypackage.core')
        >>> print(f"Modules depending on core: {deps}")
        """
        return self.module_dependencies.get(module_name, set()).copy()
    
    def is_running(self) -> bool:
        """
        Check if the watcher is currently running.
        
        Returns
        -------
        bool
            True if watcher is actively monitoring, False otherwise
            
        Examples
        --------
        >>> watcher = PackageWatcher('mypackage')
        >>> watcher.start_watching()
        >>> watcher.is_running()
        True
        >>> watcher.stop_watching()
        >>> watcher.is_running()
        False
        """
        return self._running
    
    def get_watched_files(self) -> Dict[str, str]:
        """
        Get dictionary of watched files.
        
        Returns
        -------
        Dict[str, str]
            Dictionary mapping module names to file paths
            
        Examples
        --------
        >>> watcher = PackageWatcher('mypackage')
        >>> files = watcher.get_watched_files()
        >>> for module, path in files.items():
        ...     print(f"{module} -> {path}")
        """
        with self._lock:
            return {
                info.module_name: str(info.file_path)
                for info in self.watched_files.values()
                if info.module_name
            }