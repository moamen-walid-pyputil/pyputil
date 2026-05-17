#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Module Management System.

This module provides a comprehensive interface for managing Python modules
with support for virtual modules, file-backed modules, sandboxed execution,
dependency injection, hot reloading, and cross-platform compatibility.

The system enables sophisticated module lifecycle management including:
- Hybrid storage modes (RAM, disk, cached, auto-sync)
- Secure sandboxed execution environments
- Real-time hot reloading without state loss
- Dependency injection and inversion of control
- AST-based code transformation and analysis
- Comprehensive metadata tracking
- Thread-safe operations
- Cross-platform path handling
- Performance optimization with caching

Features:
---------
- Multiple storage strategies (virtual, persistent, cached, auto-sync)
- Hot module reloading with state preservation
- Sandboxed execution for untrusted code
- AST-based code editing and refactoring
- Dependency injection system
- File watching and auto-reload
- Metadata versioning and integrity verification
- Cross-platform file path normalization
- Thread-safe concurrent access
- Comprehensive logging and auditing

Examples
--------
>>> # Create a virtual module
>>> module = open_module("my_virtual_module")
>>> module.write('''
... def hello(name):
...	 return f"Hello, {name}!"
... 
... result = hello("World")
... ''')
>>> module.exec()
>>> print(module.module.result)
'Hello, World!'

>>> # Hot reload with state preservation
>>> module.enable_hot_reload(check_interval=1.0)
>>> module.edit_function("hello", '''
... def hello(name):
...	 return f"Greetings, {name}!"
... ''')
>>> # Function automatically hot-reloaded

>>> # Sandboxed execution
>>> sandboxed = open_module("untrusted", enable_sandbox=True)
>>> sandboxed.write("print('Safe execution')")
>>> sandboxed.exec()  # Executes in isolated environment

>>> # Dependency injection
>>> module.inject({"database": db_connection, "config": app_config})
>>> module.exec()  # Uses injected dependencies
"""

import sys
import os
import time
import threading
import hashlib
import importlib
import importlib.util
import inspect
import traceback
import logging
import weakref
from types import ModuleType, CodeType, FunctionType
from typing import (
	Optional, Dict, Any, List, Set, Callable, Union,
	Tuple, Iterator, Type, cast, overload, TypeVar
)
from pathlib import Path
from enum import Enum, auto
from functools import wraps, lru_cache
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import warnings

# Import related modules
from .metadata import ModuleMetadata, IntegrityStatus, DependencySpec, DependencyType
from ..ast_editor.editor import ASTEditor
from ..sandbox.sandbox import Sandbox, SandboxConfig, SecurityLevel

# Platform-specific imports for file watching
try:
	from watchdog.observers import Observer
	from watchdog.events import FileSystemEventHandler
	WATCHDOG_AVAILABLE = True
except ImportError:
	WATCHDOG_AVAILABLE = False

# Type variable for generic methods
T = TypeVar('T')


class ModuleStorageMode(Enum):
	"""
	Storage modes for hybrid module management.
	
	Each mode defines how the module's source code is stored and synchronized
	between memory and persistent storage.
	
	Attributes
	----------
	VIRTUAL : Enum member
		Module exists only in RAM, never persisted to disk.
		Best for temporary or dynamically generated modules.
	
	PERSISTENT : Enum member
		Module is saved to disk on write operations.
		Standard mode for regular module files.
	
	CACHED : Enum member
		Module is automatically saved with intelligent caching.
		Only writes to disk when content actually changes.
	
	AUTO_SYNC : Enum member
		Bidirectional synchronization between RAM and disk.
		Changes on disk trigger reload, memory changes trigger save.
	
	APPEND : Enum member
		Append new code to existing file content.
		Useful for logging or incremental code generation.
	
	READONLY : Enum member
		Module can be read but not modified.
		Provides immutable module access.
	
	LAZY : Enum member
		Module is loaded on-demand and cached.
		Optimizes memory usage for large module collections.
	"""
	VIRTUAL = "virtual"
	PERSISTENT = "persistent"
	CACHED = "cached"
	AUTO_SYNC = "auto_sync"
	APPEND = "append"
	READONLY = "readonly"
	LAZY = "lazy"


class ModuleState(Enum):
	"""
	Current state of the module in its lifecycle.
	
	Attributes
	----------
	UNLOADED : Enum member
		Module not yet loaded into memory
	
	LOADED : Enum member
		Module loaded but not executed
	
	EXECUTED : Enum member
		Module successfully executed
	
	MODIFIED : Enum member
		Module content modified since last execution
	
	ERROR : Enum member
		Module is in error state
	
	RELOADING : Enum member
		Module currently being reloaded
	"""
	UNLOADED = "unloaded"
	LOADED = "loaded"
	EXECUTED = "executed"
	MODIFIED = "modified"
	ERROR = "error"
	RELOADING = "reloading"


@dataclass
class ModuleSnapshot:
	"""
	Snapshot of module state for rollback and history.
	
	This class captures the complete state of a module at a point in time,
	enabling rollback, comparison, and history tracking.
	
	Attributes
	----------
	source : str
		Module source code at snapshot time
	
	metadata : ModuleMetadata
		Module metadata snapshot
	
	attributes : Dict[str, Any]
		Module attributes snapshot
	
	timestamp : float
		When the snapshot was taken in seconds since epoch
	
	description : str
		Optional description of the snapshot
	
	Examples
	--------
	>>> snapshot = ModuleSnapshot(source="print('hello')", metadata=meta)
	>>> snapshot.restore(module)
	"""
	source: str
	metadata: ModuleMetadata
	attributes: Dict[str, Any] = field(default_factory=dict)
	timestamp: float = field(default_factory=time.time)
	description: str = ""
	
	def restore(self, module: 'IOTextModule') -> None:
		"""
		Restore module to this snapshot state.
		
		This method restores the module's source code, metadata, and
		attributes to the state captured in this snapshot.
		
		Parameters
		----------
		module : IOTextModule
			Module instance to restore to this snapshot's state
			
		Raises
		------
		ValueError
			If module is None or invalid
			
		Examples
		--------
		>>> snapshot = module.create_snapshot("Before changes")
		>>> module.write("new code")
		>>> snapshot.restore(module)  # Reverts to snapshot state
		"""
		if module is None:
			raise ValueError("Module cannot be None")
		
		# Restore source code
		module.write(self.source)
		
		# Restore metadata
		module.metadata = self.metadata.clone()
		
		# Restore attributes
		for key, value in self.attributes.items():
			if hasattr(module.module, key):
				setattr(module.module, key, value)


class ModuleEvent(Enum):
	"""
	Events emitted during module lifecycle.
	
	These events can be subscribed to for monitoring and reacting
	to module state changes. Each event carries relevant context
	data to the registered handlers.
	
	Attributes
	----------
	CREATED : Enum member
		Emitted when module is first created
		Context: module instance
	
	LOADED : Enum member
		Emitted when module is loaded from source
		Context: module instance
	
	EXECUTED : Enum member
		Emitted when module code is executed
		Context: module instance, result
	
	MODIFIED : Enum member
		Emitted when module source is modified
		Context: old_source, new_source
	
	SAVED : Enum member
		Emitted when module is saved to disk
		Context: file path
	
	RELOADED : Enum member
		Emitted when module is reloaded
		Context: hot_reload flag
	
	DELETED : Enum member
		Emitted when module is deleted
		Context: module name
	
	ERROR : Enum member
		Emitted when error occurs
		Context: error exception
	
	STATE_CHANGED : Enum member
		Emitted when module state changes
		Context: old_state, new_state
	"""
	CREATED = auto()
	LOADED = auto()
	EXECUTED = auto()
	MODIFIED = auto()
	SAVED = auto()
	RELOADED = auto()
	DELETED = auto()
	ERROR = auto()
	STATE_CHANGED = auto()


class IOTextModule:
	"""
	Advanced hybrid module manager with comprehensive lifecycle management.
	
	This class provides a complete interface for managing Python modules
	with sophisticated features including multiple storage strategies,
	hot reloading, sandboxing, and dependency management.
	
	Parameters
	----------
	module : Union[ModuleType, str]
		The Python module object to manage or module name string
		
	is_virtual : bool, optional
		Whether this is a virtual (RAM-only) module, by default False
		
	storage_mode : ModuleStorageMode, optional
		Storage mode for hybrid operation, by default PERSISTENT
		
	enable_sandbox : bool, optional
		Whether to enable sandboxed execution, by default False
		
	sandbox_config : Optional[SandboxConfig], optional
		Custom sandbox configuration if enabled
		
	enable_logging : bool, optional
		Enable detailed logging, by default False
		
	max_snapshots : int, optional
		Maximum number of snapshots to retain, by default 50
		
	auto_validate : bool, optional
		Automatically validate integrity after operations, by default True
	
	Attributes
	----------
	module : ModuleType
		The underlying Python module object
	
	name : str
		Module name (fully qualified)
	
	file : Optional[Path]
		Path to module file (if file-backed)
	
	is_virtual : bool
		Whether module exists only in memory
	
	storage_mode : ModuleStorageMode
		Current storage strategy
	
	enable_sandbox : bool
		Whether sandboxed execution is enabled
	
	sandbox : Optional[Sandbox]
		Sandbox instance if enabled
	
	metadata : ModuleMetadata
		Comprehensive module metadata
	
	state : ModuleState
		Current module state
	
	editor : Optional[ASTEditor]
		AST editor for code transformation
	
	Examples
	--------
	>>> # Create and manage a module
	>>> with open_module("myapp.core") as mod:
	...	 mod.write('''
	...	 def calculate(x):
	...		 return x * 2
	...	 ''')
	...	 mod.exec()
	...	 result = mod.module.calculate(21)
	...	 print(f"Result: {result}")
	
	>>> # Advanced hot reload example
	>>> mod = open_module("live_module", storage_mode=ModuleStorageMode.AUTO_SYNC)
	>>> mod.enable_hot_reload()
	>>> snapshot = mod.create_snapshot("Before changes")
	>>> mod.edit_function("calculate", "def calculate(x): return x * 3")
	>>> # Module automatically hot-reloaded
	>>> # Can rollback if needed
	>>> mod.rollback(snapshot)
	"""
	
	# Class-level registry of all managed modules
	_registry: Dict[str, weakref.ref] = {}
	_registry_lock = threading.RLock()
	
	# Class-level logger (for class-level operations)
	_class_logger: Optional[logging.Logger] = None
	
	def __init__(
		self,
		module: Union[ModuleType, str],
		is_virtual: bool = False,
		storage_mode: ModuleStorageMode = ModuleStorageMode.PERSISTENT,
		enable_sandbox: bool = False,
		sandbox_config: Optional[SandboxConfig] = None,
		enable_logging: bool = False,
		max_snapshots: int = 50,
		auto_validate: bool = True
	):
		"""
		Initialize an IOTextModule instance with comprehensive configuration.
		
		Parameters
		----------
		module : Union[ModuleType, str]
			The Python module object to manage or module name string
			
		is_virtual : bool, optional
			Whether this is a virtual (RAM-only) module, by default False
			
		storage_mode : ModuleStorageMode, optional
			Storage mode for hybrid operation, by default PERSISTENT
			
		enable_sandbox : bool, optional
			Whether to enable sandboxed execution, by default False
			
		sandbox_config : Optional[SandboxConfig], optional
			Custom sandbox configuration if enabled
			
		enable_logging : bool, optional
			Enable detailed logging, by default False
			
		max_snapshots : int, optional
			Maximum number of snapshots to retain, by default 50
			
		auto_validate : bool, optional
			Automatically validate integrity after operations, by default True
			
		Raises
		------
		ValueError
			If module configuration is invalid
		"""
		# Core attributes
		self.module = module if isinstance(module, ModuleType) else importlib.import_module(module)
		self.name = getattr(module, "__name__", module if isinstance(module, str) else str(module))
		self._source: Optional[str] = None
		self.is_virtual = is_virtual
		self.storage_mode = storage_mode
		self.enable_sandbox = enable_sandbox
		self.auto_validate = auto_validate
		self.state = ModuleState.UNLOADED
		
		# File handling
		self.file: Optional[Path] = None
		if hasattr(module, "__file__") and module.__file__:
			self.file = Path(module.__file__).resolve()
		
		# Logging 
		self._setup_logging(enable_logging)
		
		# Sandbox initialization
		self.sandbox: Optional[Sandbox] = None
		if enable_sandbox:
			self.sandbox = Sandbox(sandbox_config or SandboxConfig())
		
		# Metadata
		self.metadata = ModuleMetadata(name=self.name)
		if not is_virtual and self.file and self.file.exists():
			self._load_metadata()
		
		# AST Editor
		self.editor: Optional[ASTEditor] = None
		
		# Dependency injection
		self._injected_dependencies: Dict[str, Any] = {}
		self._original_attributes: Dict[str, Any] = {}
		
		# Hot reload
		self._hot_reload_enabled = False
		self._reload_thread: Optional[threading.Thread] = None
		self._file_watcher: Optional[Any] = None
		self._last_modified: Optional[float] = None
		
		# Event system
		self._event_handlers: Dict[ModuleEvent, List[Callable]] = {
			event: [] for event in ModuleEvent
		}
		
		# Snapshot management
		self._snapshots: List[ModuleSnapshot] = []
		self.max_snapshots = max_snapshots
		
		# Caching
		self._cache: Dict[str, Any] = {}
		self._function_cache: Dict[str, Callable] = {}
		
		# Thread safety
		self._lock = threading.RLock()
		
		# Load source
		if not is_virtual:
			self._load_source()
		
		# Initialize editor
		if self._source:
			self.editor = ASTEditor(self._source)
			self.metadata.update_content_hash(self._source)
			self.state = ModuleState.LOADED
		
		# Register in global registry
		self._register()
		
		# Emit creation event
		self._emit_event(ModuleEvent.CREATED, module=self.module)
		
		if self._logger:
			self._logger.info(
				f"Module '{self.name}' initialized (virtual={is_virtual}, "
				f"mode={storage_mode.value}, sandbox={enable_sandbox})"
			)
	
	def _setup_logging(self, enable: bool) -> None:
		"""
		Setup module-specific logging with proper initialization.
		
		This method creates both class-level and instance-level loggers.
		The instance logger is properly initialized to avoid NoneType errors.
		
		Parameters
		----------
		enable : bool
			Whether to enable logging (True) or disable it (False)
			
		Notes
		-----
		This method ensures that self._logger is never None after calling.
		If logging is disabled, the logger is set to disabled state.
		
		Examples
		--------
		>>> module = IOTextModule(some_module, enable_logging=True)
		>>> module._logger.info("This will be logged")
		"""
		# Always create an instance logger first - this prevents NoneType errors
		self._logger = logging.getLogger(f"IOTextModule.{self.name}")
		
		if enable:
			self._logger.setLevel(logging.INFO)
			
			# Add console handler if no handlers exist
			if not self._logger.handlers:
				handler = logging.StreamHandler()
				formatter = logging.Formatter(
					'%(asctime)s - %(name)s - %(levelname)s - %(message)s'
				)
				handler.setFormatter(formatter)
				self._logger.addHandler(handler)
			
			self._logger.disabled = False
			
			# Setup class-level logger for global operations
			if IOTextModule._class_logger is None:
				IOTextModule._class_logger = logging.getLogger("IOTextModule")
				IOTextModule._class_logger.setLevel(logging.INFO)
				
				if not IOTextModule._class_logger.handlers:
					handler = logging.StreamHandler()
					formatter = logging.Formatter(
						'%(asctime)s - IOTextModule - %(levelname)s - %(message)s'
					)
					handler.setFormatter(formatter)
					IOTextModule._class_logger.addHandler(handler)
		else:
			self._logger.disabled = True
	
	def _register(self) -> None:
		"""
		Register module in global registry.
		
		This method adds the current module instance to the class-level
		registry using a weak reference to prevent memory leaks.
		
		Notes
		-----
		Uses thread-safe operations for concurrent access.
		"""
		with self._registry_lock:
			IOTextModule._registry[self.name] = weakref.ref(self)
	
	def _unregister(self) -> None:
		"""
		Unregister module from global registry.
		
		This method removes the current module from the class-level registry.
		
		Notes
		-----
		Uses thread-safe operations for concurrent access.
		"""
		with self._registry_lock:
			IOTextModule._registry.pop(self.name, None)
	
	@classmethod
	def get_registered_modules(cls) -> List[str]:
		"""
		Get list of all registered module names.
		
		Returns
		-------
		List[str]
			Names of registered modules, sorted alphabetically
			
		Examples
		--------
		>>> modules = IOTextModule.get_registered_modules()
		>>> print(f"Active modules: {len(modules)}")
		"""
		with cls._registry_lock:
			return sorted(list(cls._registry.keys()))
	
	@classmethod
	def get_module(cls, name: str) -> Optional['IOTextModule']:
		"""
		Get registered module by name.
		
		Parameters
		----------
		name : str
			Module name to look up
			
		Returns
		-------
		Optional[IOTextModule]
			Module instance if found and still alive, None otherwise
			
		Examples
		--------
		>>> module = IOTextModule.get_module("my_module")
		>>> if module:
		...	 print(f"Found module: {module.name}")
		"""
		with cls._registry_lock:
			ref = cls._registry.get(name)
			if ref:
				return ref()
		return None
	
	def _load_source(self) -> None:
		"""
		Load source code from file if available.
		
		This method handles cross-platform file reading with proper
		encoding detection and error handling. It attempts multiple
		encodings for maximum compatibility.
		
		Raises
		------
		ValueError
			If file cannot be decoded with any supported encoding
		FileNotFoundError
			If the module file does not exist
		"""
		if not self.file:
			if self._logger:
				self._logger.warning(f"Module '{self.name}' has no associated file")
			return
		
		if not self.file.exists():
			if self._logger:
				self._logger.warning(f"Module file '{self.file}' does not exist")
			return
		
		try:
			# Try multiple encodings for cross-platform compatibility
			for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
				try:
					with open(self.file, 'r', encoding=encoding) as f:
						self._source = f.read()
					break
				except UnicodeDecodeError:
					continue
			
			if self._source is None:
				raise ValueError(f"Could not decode file '{self.file}' with any supported encoding")
			
			self._last_modified = self.file.stat().st_mtime
			self.state = ModuleState.LOADED
			
			if self._logger:
				self._logger.debug(f"Loaded source from '{self.file}' ({len(self._source)} bytes)")
			
		except Exception as e:
			self.state = ModuleState.ERROR
			if self._logger:
				self._logger.error(f"Failed to load source from '{self.file}': {e}")
			self._emit_event(ModuleEvent.ERROR, error=e)
			raise
	
	def _load_metadata(self) -> None:
		"""
		Load metadata from companion file if exists.
		
		Looks for .meta.json file alongside the module file.
		This method is safe to call even if no metadata file exists.
		
		Notes
		-----
		Metadata files are optional; this method fails silently
		if no metadata file is found.
		"""
		if not self.file:
			return
		
		meta_file = self.file.with_suffix('.meta.json')
		if meta_file.exists():
			try:
				self.metadata = ModuleMetadata.load_from_file(meta_file)
				if self._logger:
					self._logger.debug(f"Loaded metadata from '{meta_file}'")
			except Exception as e:
				if self._logger:
					self._logger.warning(f"Failed to load metadata: {e}")
	
	def _save_metadata(self) -> None:
		"""
		Save metadata to companion file.
		
		Creates or updates the .meta.json file alongside the module file.
		
		Notes
		-----
		Only saves if the module is not virtual and has a valid file path.
		Failures are logged but do not raise exceptions.
		"""
		if not self.file or self.is_virtual:
			return
		
		try:
			meta_file = self.file.with_suffix('.meta.json')
			self.metadata.save_to_file(meta_file)
			if self._logger:
				self._logger.debug(f"Saved metadata to '{meta_file}'")
		except Exception as e:
			if self._logger:
				self._logger.warning(f"Failed to save metadata: {e}")
	
	def read(self) -> str:
		"""
		Read the module's source code.
		
		Returns
		-------
		str
			Module source code content
			
		Raises
		------
		ValueError
			If no source is available
			
		Examples
		--------
		>>> mod = open_module("my_module")
		>>> source = mod.read()
		>>> print(f"Module has {len(source)} characters")
		"""
		with self._lock:
			if self._source is None:
				if self.storage_mode == ModuleStorageMode.LAZY:
					self._load_source()
				else:
					raise ValueError(f"No source available for '{self.name}'")
			
			return self._source
	
	def write(
		self,
		code: str,
		update_metadata: bool = True,
		auto_execute: bool = False
	) -> None:
		"""
		Write new source code to the module.
		
		This method updates the module's source code and handles
		persistence based on the configured storage mode.
		
		Parameters
		----------
		code : str
			New source code for the module
			
		update_metadata : bool, optional
			Whether to update metadata hash, by default True
			
		auto_execute : bool, optional
			Automatically execute after writing, by default False
			
		Raises
		------
		ValueError
			If module is readonly
			
		Examples
		--------
		>>> mod = open_module("my_module")
		>>> mod.write('''
		... def greet(name):
		...	 return f"Hello, {name}!"
		... ''')
		>>> mod.exec()
		"""
		with self._lock:
			if self.storage_mode == ModuleStorageMode.READONLY:
				raise ValueError(f"Cannot write to readonly module '{self.name}'")
			
			old_source = self._source
			self._source = code
			self.editor = ASTEditor(code)
			
			if update_metadata:
				self.metadata.update_content_hash(code)
				if self.auto_validate:
					self.metadata.verify_integrity(code)
			
			self.state = ModuleState.MODIFIED
			
			# Persist based on storage mode
			if self.storage_mode in [
				ModuleStorageMode.PERSISTENT,
				ModuleStorageMode.AUTO_SYNC,
				ModuleStorageMode.CACHED
			]:
				if not self.is_virtual and self.file:
					if self.storage_mode == ModuleStorageMode.CACHED:
						# Only save if content actually changed
						if old_source != code:
							self.save()
					else:
						self.save()
			
			self._emit_event(ModuleEvent.MODIFIED, old_source=old_source, new_source=code)
			if self._logger:
				self._logger.info(f"Module '{self.name}' source updated ({len(code)} bytes)")
			
			if auto_execute:
				self.exec()
	
	def exec(
		self,
		capture_output: bool = False,
		timeout: Optional[float] = None
	) -> Any:
		"""
		Execute the module's code in its namespace.
		
		This method executes the module code with support for sandboxing,
		dependency injection, output capture, and timeout control.
		
		Parameters
		----------
		capture_output : bool, optional
			Capture stdout/stderr during execution, by default False
			
		timeout : Optional[float], optional
			Maximum execution time in seconds, by default None
			
		Returns
		-------
		Any
			Execution result if any expression is evaluated,
			or dict with stdout/stderr if capture_output is True
			
		Raises
		------
		ValueError
			If no code to execute
		TimeoutError
			If execution exceeds timeout
		Exception
			Any exception raised during execution
			
		Examples
		--------
		>>> mod = open_module("calculator")
		>>> mod.write("result = sum(range(1, 101))")
		>>> mod.exec()
		>>> print(mod.module.result)
		5050
		"""
		with self._lock:
			if self._source is None:
				raise ValueError(f"No code to execute in module '{self.name}'")
			
			self.state = ModuleState.RELOADING
			
			# Create snapshot for rollback
			snapshot = self.create_snapshot("Auto-snapshot before execution")
			
			# Apply injected dependencies
			self._apply_dependencies()
			
			try:
				if self.enable_sandbox and self.sandbox:
					# Sandboxed execution
					result = self.sandbox.execute(
						self._source,
						timeout=timeout,
						capture_output=capture_output
					)
					
					if result.success:
						# Merge sandbox namespace back
						for key, value in self.sandbox.get_namespace_copy().items():
							if not key.startswith('__'):
								setattr(self.module, key, value)
					else:
						raise result.error or RuntimeError("Sandbox execution failed")
					
				else:
					# Standard execution
					compiled = compile(self._source, self.name, 'exec')
					
					if timeout:
						result = self._execute_with_timeout(compiled, timeout, capture_output)
					else:
						result = self._execute_standard(compiled, capture_output)
				
				self.state = ModuleState.EXECUTED
				self._emit_event(ModuleEvent.EXECUTED, result=result)
				if self._logger:
					self._logger.info(f"Module '{self.name}' executed successfully")
				
				return result
				
			except Exception as e:
				self.state = ModuleState.ERROR
				if self._logger:
					self._logger.error(f"Module '{self.name}' execution failed: {e}")
				self._emit_event(ModuleEvent.ERROR, error=e)
				
				# Rollback on error
				self.rollback(snapshot)
				
				raise
				
			finally:
				# Restore original attributes
				self._restore_attributes()
	
	def _apply_dependencies(self) -> None:
		"""
		Apply injected dependencies to module.
		
		This method stores original attributes that are being overridden
		and then applies the injected dependencies.
		"""
		self._original_attributes.clear()
		
		for name, value in self._injected_dependencies.items():
			if hasattr(self.module, name):
				self._original_attributes[name] = getattr(self.module, name)
			setattr(self.module, name, value)
	
	def _restore_attributes(self) -> None:
		"""
		Restore original module attributes.
		
		This method restores any attributes that were overridden by
		dependency injection, then clears the tracking dictionary.
		"""
		for name, value in self._original_attributes.items():
			setattr(self.module, name, value)
		self._original_attributes.clear()
	
	def _execute_standard(self, compiled: CodeType, capture_output: bool) -> Any:
		"""
		Execute compiled code in standard environment.
		
		Parameters
		----------
		compiled : CodeType
			Compiled code object to execute
			
		capture_output : bool
			Whether to capture stdout/stderr
			
		Returns
		-------
		Any
			None if capture_output is False,
			dict with 'stdout' and 'stderr' keys if capture_output is True
		"""
		if capture_output:
			import io
			from contextlib import redirect_stdout, redirect_stderr
			
			stdout_buffer = io.StringIO()
			stderr_buffer = io.StringIO()
			
			with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
				exec(compiled, self.module.__dict__)
			
			return {
				'stdout': stdout_buffer.getvalue(),
				'stderr': stderr_buffer.getvalue()
			}
		else:
			exec(compiled, self.module.__dict__)
			return None
	
	def _execute_with_timeout(
		self,
		compiled: CodeType,
		timeout: float,
		capture_output: bool
	) -> Any:
		"""
		Execute compiled code with timeout.
		
		Parameters
		----------
		compiled : CodeType
			Compiled code object to execute
			
		timeout : float
			Maximum execution time in seconds
			
		capture_output : bool
			Whether to capture output
			
		Returns
		-------
		Any
			Execution result as from _execute_standard
			
		Raises
		------
		TimeoutError
			If execution exceeds timeout
		"""
		result = [None]
		error = [None]
		
		def target():
			try:
				result[0] = self._execute_standard(compiled, capture_output)
			except Exception as e:
				error[0] = e
		
		thread = threading.Thread(target=target)
		thread.daemon = True
		thread.start()
		thread.join(timeout)
		
		if thread.is_alive():
			raise TimeoutError(f"Execution exceeded {timeout} seconds")
		
		if error[0]:
			raise error[0]
		
		return result[0]
	
	def save(self, force_save: bool = False, create_backup: bool = True) -> None:
		"""
		Save the module to disk with cross-platform support.
		
		Parameters
		----------
		force_save : bool, optional
			Save even if virtual module, by default False
			
		create_backup : bool, optional
			Create backup (.py.bak) before overwriting, by default True
			
		Raises
		------
		ValueError
			If module cannot be saved (virtual without force_save)
			
		Examples
		--------
		>>> mod = open_module("my_module", storage_mode=ModuleStorageMode.PERSISTENT)
		>>> mod.write("# My module")
		>>> mod.save()  # Saved to disk
		>>> mod.save(force_save=True)  # Force save even if virtual
		"""
		with self._lock:
			if self.is_virtual and not force_save:
				raise ValueError("Cannot save a virtual module without force_save")
			
			if self._source is None:
				raise ValueError("No source code to save")
			
			# Determine output file
			if self.file:
				output_file = self.file
			else:
				# Create file path from module name
				parts = self.name.split('.')
				if len(parts) > 1:
					output_file = Path(*parts[:-1]) / f"{parts[-1]}.py"
				else:
					output_file = Path(f"{self.name}.py")
				
				output_file = output_file.resolve()
				self.file = output_file
			
			# Create parent directories
			output_file.parent.mkdir(parents=True, exist_ok=True)
			
			# Create backup if file exists
			if create_backup and output_file.exists():
				backup_file = output_file.with_suffix('.py.bak')
				import shutil
				shutil.copy2(output_file, backup_file)
				if self._logger:
					self._logger.debug(f"Created backup at '{backup_file}'")
			
			# Determine write mode
			mode = 'a' if self.storage_mode == ModuleStorageMode.APPEND else 'w'
			
			# Write file
			with open(output_file, mode, encoding='utf-8') as f:
				f.write(self._source)
				if mode == 'a':
					f.write('\n')  # Add newline for append mode
			
			self._last_modified = output_file.stat().st_mtime
			self.metadata.modified_at = time.time()
			
			# Save metadata alongside
			self._save_metadata()
			
			self._emit_event(ModuleEvent.SAVED, file=str(output_file))
			if self._logger:
				self._logger.info(f"Module '{self.name}' saved to '{output_file}'")
	
	def reload(self, force: bool = False) -> ModuleType:
		"""
		Reload the module using standard importlib reload.
		
		Parameters
		----------
		force : bool, optional
			Force reload even if unchanged, by default False
			
		Returns
		-------
		ModuleType
			The reloaded module object
			
		Examples
		--------
		>>> mod = open_module("my_module")
		>>> mod.write("# Updated code")
		>>> mod.reload()
		"""
		with self._lock:
			self.state = ModuleState.RELOADING
			
			try:
				if self.is_virtual:
					self.exec()
					return self.module
				
				# Check if file changed
				if not force and self.file and self.file.exists():
					current_mtime = self.file.stat().st_mtime
					if self._last_modified and current_mtime <= self._last_modified:
						if self._logger:
							self._logger.debug("Module unchanged, skipping reload")
						return self.module
				
				# Reload module
				self.module = importlib.reload(self.module)
				self._load_source()
				
				self.state = ModuleState.LOADED
				self._emit_event(ModuleEvent.RELOADED, module=self.module)
				if self._logger:
					self._logger.info(f"Module '{self.name}' reloaded")
				
				return self.module
				
			except Exception as e:
				self.state = ModuleState.ERROR
				self._emit_event(ModuleEvent.ERROR, error=e)
				if self._logger:
					self._logger.error(f"Failed to reload module '{self.name}': {e}")
				raise
	
	def reload_hot(self, preserve_state: bool = True) -> None:
		"""
		Perform hot reload without losing module state.
		
		This method intelligently updates module code while preserving
		existing module attributes and state. Only changed functions
		and classes are updated.
		
		Parameters
		----------
		preserve_state : bool, optional
			Preserve module state during reload, by default True
			
		Raises
		------
		RuntimeError
			If hot reload fails
			
		Examples
		--------
		>>> mod = open_module("live_module")
		>>> mod.enable_hot_reload()
		>>> # Edit code externally, module auto-updates
		>>> # Or manually:
		>>> mod.reload_hot()
		"""
		with self._lock:
			if not self._source:
				if self._logger:
					self._logger.warning("No source to hot reload")
				return
			
			self.state = ModuleState.RELOADING
			
			try:
				if preserve_state:
					# Save current state
					old_state = {}
					for key, value in self.module.__dict__.items():
						if not key.startswith('__'):
							old_state[key] = value
					
					# Create temporary module with new code
					temp_module = ModuleType(f"_{self.name}_temp")
					exec(self._source, temp_module.__dict__)
					
					# Update existing module with new code
					for key, value in temp_module.__dict__.items():
						if not key.startswith('__'):
							if key in old_state:
								if callable(value) and callable(old_state[key]):
									# Update function while preserving closure
									self._update_function(old_state[key], value)
								elif isinstance(value, type) and isinstance(old_state[key], type):
									# Update class methods
									self._update_class(old_state[key], value)
								else:
									# Replace other attributes
									setattr(self.module, key, value)
							else:
								# New attribute
								setattr(self.module, key, value)
				else:
					# Simple reload without preservation
					self.module.__dict__.clear()
					exec(self._source, self.module.__dict__)
				
				self.metadata.modified_at = time.time()
				self.state = ModuleState.EXECUTED
				
				self._emit_event(ModuleEvent.RELOADED, hot_reload=True)
				if self._logger:
					self._logger.info(f"Module '{self.name}' hot reloaded (preserve_state={preserve_state})")
				
			except Exception as e:
				self.state = ModuleState.ERROR
				self._emit_event(ModuleEvent.ERROR, error=e)
				if self._logger:
					self._logger.error(f"Hot reload failed for '{self.name}': {e}")
				raise RuntimeError(f"Hot reload failed: {e}") from e
	
	def _update_function(self, old_func: FunctionType, new_func: FunctionType) -> None:
		"""
		Update function code while preserving closure and attributes.
		
		Parameters
		----------
		old_func : FunctionType
			Existing function to update
			
		new_func : FunctionType
			New function with updated code
		"""
		if hasattr(old_func, '__code__') and hasattr(new_func, '__code__'):
			# Update code object
			old_func.__code__ = new_func.__code__
			
			# Update other attributes
			if hasattr(new_func, '__defaults__'):
				old_func.__defaults__ = new_func.__defaults__
			if hasattr(new_func, '__annotations__'):
				old_func.__annotations__ = new_func.__annotations__
			if hasattr(new_func, '__doc__'):
				old_func.__doc__ = new_func.__doc__
	
	def _update_class(self, old_class: Type, new_class: Type) -> None:
		"""
		Update class methods and attributes.
		
		Parameters
		----------
		old_class : Type
			Existing class to update
			
		new_class : Type
			New class with updated code
		"""
		for name, value in new_class.__dict__.items():
			if name not in ['__dict__', '__weakref__']:
				if name in old_class.__dict__:
					old_value = old_class.__dict__[name]
					if callable(value) and callable(old_value):
						self._update_function(old_value, value)
					else:
						setattr(old_class, name, value)
				else:
					setattr(old_class, name, value)
	
	def inject(self, dependencies: Dict[str, Any], override: bool = True) -> None:
		"""
		Inject dependencies into the module.
		
		Parameters
		----------
		dependencies : Dict[str, Any]
			Dictionary of dependency names to values
			
		override : bool, optional
			Override existing attributes, by default True
			
		Examples
		--------
		>>> mod = open_module("app")
		>>> mod.inject({
		...	 "database": db_connection,
		...	 "config": {"debug": True},
		...	 "logger": custom_logger
		... })
		>>> mod.exec()  # Uses injected dependencies
		"""
		with self._lock:
			for name, value in dependencies.items():
				if override or not hasattr(self.module, name):
					self._injected_dependencies[name] = value
			
			if self._logger:
				self._logger.info(f"Injected {len(dependencies)} dependencies into '{self.name}'")
	
	def clear_injections(self) -> None:
		"""Clear all injected dependencies."""
		with self._lock:
			self._injected_dependencies.clear()
			if self._logger:
				self._logger.info(f"Cleared injections for '{self.name}'")
	
	def on(
		self,
		event: Union[ModuleEvent, str],
		callback: Callable
	) -> Callable:
		"""
		Register event handler.
		
		Parameters
		----------
		event : Union[ModuleEvent, str]
			Event to listen for (can be ModuleEvent enum or string name)
			
		callback : Callable
			Function to call when event occurs
			
		Returns
		-------
		Callable
			The registered callback (for decorator use)
			
		Examples
		--------
		>>> mod = open_module("my_module")
		>>> 
		>>> @mod.on(ModuleEvent.EXECUTED)
		... def on_executed(**kwargs):
		...	 print("Module executed!")
		>>> 
		>>> @mod.on(ModuleEvent.MODIFIED)
		... def on_modified(**kwargs):
		...	 print(f"Source changed to {len(kwargs['new_source'])} bytes")
		"""
		if isinstance(event, str):
			event = ModuleEvent[event.upper()]
		
		self._event_handlers[event].append(callback)
		return callback
	
	def off(
		self,
		event: Union[ModuleEvent, str],
		callback: Optional[Callable] = None
	) -> None:
		"""
		Remove event handler.
		
		Parameters
		----------
		event : Union[ModuleEvent, str]
			Event to remove handler from
			
		callback : Optional[Callable], optional
			Specific callback to remove, None to remove all handlers for event
		"""
		if isinstance(event, str):
			event = ModuleEvent[event.upper()]
		
		if callback is None:
			self._event_handlers[event].clear()
		else:
			self._event_handlers[event] = [
				cb for cb in self._event_handlers[event] if cb != callback
			]
	
	def _emit_event(self, event: ModuleEvent, **kwargs) -> None:
		"""
		Emit event to registered handlers.
		
		Parameters
		----------
		event : ModuleEvent
			Event to emit
			
		**kwargs
			Additional event data to pass to handlers
		"""
		for handler in self._event_handlers[event]:
			try:
				handler(module=self, event=event, **kwargs)
			except Exception as e:
				if self._logger:
					self._logger.error(f"Event handler error: {e}")
	
	def create_snapshot(self, description: str = "") -> ModuleSnapshot:
		"""
		Create a snapshot of current module state.
		
		Parameters
		----------
		description : str, optional
			Description of the snapshot
			
		Returns
		-------
		ModuleSnapshot
			Module state snapshot object
			
		Examples
		--------
		>>> mod = open_module("my_module")
		>>> snapshot = mod.create_snapshot("Before major changes")
		>>> # Make changes...
		>>> mod.rollback(snapshot)  # Restore to snapshot
		"""
		with self._lock:
			# Capture current attributes
			attributes = {}
			for key, value in self.module.__dict__.items():
				if not key.startswith('__'):
					try:
						# Only capture serializable or simple attributes
						if callable(value) or isinstance(value, (int, float, str, bool, list, dict, tuple)):
							attributes[key] = value
					except Exception:
						pass
			
			snapshot = ModuleSnapshot(
				source=self._source or "",
				metadata=self.metadata.clone(),
				attributes=attributes,
				description=description
			)
			
			self._snapshots.append(snapshot)
			
			# Limit snapshot count
			if len(self._snapshots) > self.max_snapshots:
				self._snapshots = self._snapshots[-self.max_snapshots:]
			
			if self._logger:
				self._logger.debug(f"Created snapshot '{description}' ({len(self._snapshots)} total)")
			
			return snapshot
	
	def rollback(self, snapshot: ModuleSnapshot) -> None:
		"""
		Rollback module to a previous snapshot.
		
		Parameters
		----------
		snapshot : ModuleSnapshot
			Snapshot to restore (must be from this module)
			
		Examples
		--------
		>>> mod = open_module("my_module")
		>>> snapshot = mod.create_snapshot()
		>>> mod.write("# Changed code")
		>>> mod.rollback(snapshot)  # Restored
		"""
		with self._lock:
			snapshot.restore(self)
			if self._logger:
				self._logger.info(f"Rolled back to snapshot '{snapshot.description}'")
	
	def get_snapshots(self) -> List[ModuleSnapshot]:
		"""
		Get list of all snapshots.
		
		Returns
		-------
		List[ModuleSnapshot]
			Copy of the snapshots list (modifications don't affect internal list)
		"""
		return self._snapshots.copy()
	
	def clear_snapshots(self) -> None:
		"""Clear all snapshots."""
		with self._lock:
			self._snapshots.clear()
			if self._logger:
				self._logger.debug("Cleared all snapshots")
	
	def enable_hot_reload(
		self,
		check_interval: float = 1.0,
		use_watchdog: bool = True
	) -> None:
		"""
		Enable automatic hot reloading when source changes.
		
		Parameters
		----------
		check_interval : float, optional
			How often to check for changes in seconds (for polling mode), by default 1.0
			
		use_watchdog : bool, optional
			Use watchdog for file monitoring if available, by default True
			
		Examples
		--------
		>>> mod = open_module("live_module")
		>>> mod.enable_hot_reload(check_interval=0.5)
		>>> # Edit file externally, module auto-reloads
		"""
		with self._lock:
			if self._hot_reload_enabled:
				return
			
			self._hot_reload_enabled = True
			
			if use_watchdog and WATCHDOG_AVAILABLE and self.file and self.file.exists():
				self._setup_watchdog()
			else:
				self._setup_polling(check_interval)
			
			if self._logger:
				self._logger.info(f"Hot reload enabled for '{self.name}'")
	
	def _setup_watchdog(self) -> None:
		"""
		Setup watchdog-based file monitoring.
		
		Uses the watchdog library for efficient file system event monitoring.
		Falls back to polling if watchdog is not available.
		"""
		if not WATCHDOG_AVAILABLE or not self.file:
			return
		
		class ModuleFileHandler(FileSystemEventHandler):
			"""Internal handler for file system events."""
			
			def __init__(self, module):
				self.module = module
				self._last_reload = 0
			
			def on_modified(self, event):
				"""Handle file modification events."""
				if event.src_path == str(self.module.file):
					now = time.time()
					if now - self._last_reload > 1.0:  # Debounce
						self._last_reload = now
						try:
							self.module._load_source()
							self.module.reload_hot()
						except Exception as e:
							if self.module._logger:
								self.module._logger.error(f"Auto-reload failed: {e}")
		
		handler = ModuleFileHandler(self)
		self._file_watcher = Observer()
		self._file_watcher.schedule(handler, str(self.file.parent), recursive=False)
		self._file_watcher.start()
	
	def _setup_polling(self, interval: float) -> None:
		"""
		Setup polling-based change detection.
		
		Parameters
		----------
		interval : float
			Polling interval in seconds
		"""
		def poll_loop():
			"""Background polling thread function."""
			while self._hot_reload_enabled:
				time.sleep(interval)
				
				if not self.file or not self.file.exists():
					continue
				
				try:
					current_mtime = self.file.stat().st_mtime
					if self._last_modified and current_mtime > self._last_modified:
						self._load_source()
						self.reload_hot()
						self._last_modified = current_mtime
				except Exception as e:
					if self._logger:
						self._logger.error(f"Poll check failed: {e}")
		
		self._reload_thread = threading.Thread(target=poll_loop, daemon=True)
		self._reload_thread.start()
	
	def disable_hot_reload(self) -> None:
		"""
		Disable automatic hot reloading.
		
		Examples
		--------
		>>> mod = open_module("live_module")
		>>> mod.disable_hot_reload()
		"""
		with self._lock:
			self._hot_reload_enabled = False
			
			if self._file_watcher:
				self._file_watcher.stop()
				self._file_watcher.join(timeout=2.0)
				self._file_watcher = None
			
			if self._reload_thread:
				self._reload_thread.join(timeout=2.0)
				self._reload_thread = None
			
			if self._logger:
				self._logger.info(f"Hot reload disabled for '{self.name}'")
	
	def edit_function(self, func_name: str, new_code: str) -> bool:
		"""
		Edit a specific function using AST transformation.
		
		Parameters
		----------
		func_name : str
			Name of function to edit
			
		new_code : str
			New function definition code (must be valid Python)
			
		Returns
		-------
		bool
			True if edit was successful, False otherwise
			
		Examples
		--------
		>>> mod = open_module("my_module")
		>>> mod.write("def hello(): return 'Hello'")
		>>> mod.edit_function("hello", "def hello(): return 'Greetings'")
		True
		>>> mod.exec()
		>>> print(mod.module.hello())
		'Greetings'
		"""
		with self._lock:
			if not self.editor:
				if self._logger:
					self._logger.error("No AST editor available")
				return False
			
			if self.editor.replace_function(func_name, new_code):
				new_source = self.editor.get_code()
				self.write(new_source)
				
				if self._logger:
					self._logger.info(f"Edited function '{func_name}' in '{self.name}'")
				return True
			
			return False
	
	def edit_class(self, class_name: str, new_code: str) -> bool:
		"""
		Edit a specific class using AST transformation.
		
		Parameters
		----------
		class_name : str
			Name of class to edit
			
		new_code : str
			New class definition code (must be valid Python)
			
		Returns
		-------
		bool
			True if edit was successful, False otherwise
			
		Examples
		--------
		>>> mod = open_module("my_module")
		>>> mod.write("class MyClass: pass")
		>>> mod.edit_class("MyClass", "class MyClass: def hello(self): return 'Hi'")
		True
		"""
		with self._lock:
			if not self.editor:
				if self._logger:
					self._logger.error("No AST editor available")
				return False
			
			if self.editor.replace_class(class_name, new_code):
				new_source = self.editor.get_code()
				self.write(new_source)
				
				if self._logger:
					self._logger.info(f"Edited class '{class_name}' in '{self.name}'")
				return True
			
			return False
	
	def add_import(self, module: str, alias: Optional[str] = None) -> bool:
		"""
		Add an import statement to the module.
		
		Parameters
		----------
		module : str
			Module to import
			
		alias : Optional[str], optional
			Import alias (e.g., 'np' for 'import numpy as np')
			
		Returns
		-------
		bool
			True if import was added successfully
			
		Examples
		--------
		>>> mod = open_module("my_module")
		>>> mod.add_import("numpy", "np")
		True
		"""
		with self._lock:
			if not self.editor:
				return False
			
			if self.editor.add_import(module, alias):
				self.write(self.editor.get_code())
				return True
			
			return False
	
	def get_functions(self) -> List[str]:
		"""
		Get all function names in the module.
		
		Returns
		-------
		List[str]
			List of function names (excluding private/internal ones starting with '_')
			
		Examples
		--------
		>>> mod = open_module("my_module")
		>>> functions = mod.get_functions()
		>>> print(f"Module has {len(functions)} functions")
		"""
		if self.editor:
			return self.editor.get_functions()
		
		# Fallback to inspection
		functions = []
		for name, value in self.module.__dict__.items():
			if callable(value) and not name.startswith('__'):
				functions.append(name)
		return functions
	
	def get_classes(self) -> List[str]:
		"""
		Get all class names in the module.
		
		Returns
		-------
		List[str]
			List of class names (excluding private/internal ones starting with '_')
		"""
		if self.editor:
			return self.editor.get_classes()
		
		# Fallback to inspection
		classes = []
		for name, value in self.module.__dict__.items():
			if isinstance(value, type) and not name.startswith('__'):
				classes.append(name)
		return classes
	
	def add_dependency(
		self,
		name: str,
		version_spec: str = "",
		dep_type: DependencyType = DependencyType.REQUIRED
	) -> None:
		"""
		Add a module dependency to metadata.
		
		Parameters
		----------
		name : str
			Dependency name (package/module name)
			
		version_spec : str, optional
			Version specification (e.g., ">=1.0.0")
			
		dep_type : DependencyType, optional
			Type of dependency (REQUIRED, OPTIONAL, DEV, TEST)
		"""
		self.metadata.add_dependency(name, version_spec, dep_type)
	
	def validate(self) -> Tuple[bool, List[str]]:
		"""
		Validate module integrity and dependencies.
		
		Checks:
		- Source code integrity (hash verification)
		- Dependency availability
		- Python syntax validity
		
		Returns
		-------
		Tuple[bool, List[str]]
			(is_valid, list_of_issues)
			- is_valid: True if no issues found
			- list_of_issues: List of validation issue descriptions
			
		Examples
		--------
		>>> mod = open_module("my_module")
		>>> valid, issues = mod.validate()
		>>> if not valid:
		...	 for issue in issues:
		...		 print(f"Issue: {issue}")
		"""
		issues = []
		
		# Validate source integrity
		if self._source:
			if not self.metadata.verify_integrity(self._source):
				issues.append("Source code integrity check failed")
		
		# Validate dependencies
		dep_valid, dep_issues = self.metadata.validate_dependencies()
		if not dep_valid:
			issues.extend(dep_issues)
		
		# Validate syntax
		if self._source:
			try:
				compile(self._source, self.name, 'exec')
			except SyntaxError as e:
				issues.append(f"Syntax error: {e}")
		
		return len(issues) == 0, issues
	
	def get_cache(self, key: str) -> Any:
		"""
		Get cached value.
		
		Parameters
		----------
		key : str
			Cache key to look up
			
		Returns
		-------
		Any
			Cached value if exists and not expired, None otherwise
		"""
		with self._lock:
			cached = self._cache.get(key)
			if cached:
				value, expires = cached
				if expires is None or time.time() < expires:
					return value
				else:
					del self._cache[key]
		return None
	
	def set_cache(
		self,
		key: str,
		value: Any,
		ttl: Optional[float] = None
	) -> None:
		"""
		Set cached value with optional TTL.
		
		Parameters
		----------
		key : str
			Cache key
			
		value : Any
			Value to cache
			
		ttl : Optional[float], optional
			Time to live in seconds (None = never expire)
		"""
		with self._lock:
			expires = time.time() + ttl if ttl else None
			self._cache[key] = (value, expires)
	
	def clear_cache(self) -> None:
		"""Clear all cached values."""
		with self._lock:
			self._cache.clear()
			self._function_cache.clear()
	
	def cache_function(self, ttl: Optional[float] = None) -> Callable:
		"""
		Decorator to cache function results.
		
		Parameters
		----------
		ttl : Optional[float], optional
			Cache TTL in seconds (None = never expire)
			
		Returns
		-------
		Callable
			Decorator function
			
		Examples
		--------
		>>> mod = open_module("my_module")
		>>> 
		>>> @mod.cache_function(ttl=60)
		... def expensive_calculation(x):
		...	 # Expensive operation
		...	 return x * 2
		"""
		def decorator(func: Callable) -> Callable:
			@wraps(func)
			def wrapper(*args, **kwargs):
				cache_key = f"{func.__name__}:{hash((args, tuple(kwargs.items())))}"
				cached = self.get_cache(cache_key)
				if cached is not None:
					return cached
				
				result = func(*args, **kwargs)
				self.set_cache(cache_key, result, ttl)
				return result
			
			self._function_cache[func.__name__] = wrapper
			return wrapper
		
		return decorator
	
	def get_metadata(self) -> ModuleMetadata:
		"""
		Get module metadata.
		
		Returns
		-------
		ModuleMetadata
			Module metadata object (clone, modifications don't affect original)
		"""
		return self.metadata.clone()
	
	def get_size(self) -> int:
		"""
		Get module source size in bytes.
		
		Returns
		-------
		int
			Source size in bytes (UTF-8 encoded)
		"""
		return len(self._source.encode('utf-8')) if self._source else 0
	
	def get_hash(self, algorithm: str = "sha256") -> str:
		"""
		Get module source hash.
		
		Parameters
		----------
		algorithm : str
			Hash algorithm to use ('sha256', 'md5', etc.)
			
		Returns
		-------
		str
			Hexadecimal hash string
			
		Raises
		------
		ValueError
			If algorithm is not supported
		"""
		if not self._source:
			return ""
		
		if algorithm == "sha256":
			return hashlib.sha256(self._source.encode()).hexdigest()
		elif algorithm == "md5":
			return hashlib.md5(self._source.encode()).hexdigest()
		else:
			raise ValueError(f"Unsupported hash algorithm: {algorithm}")
	
	def export(self, path: Union[str, Path]) -> None:
		"""
		Export module to a file.
		
		Parameters
		----------
		path : Union[str, Path]
			Export file path (will create parent directories)
		"""
		path = Path(path).resolve()
		path.parent.mkdir(parents=True, exist_ok=True)
		
		with open(path, 'w', encoding='utf-8') as f:
			f.write(self._source or "")
		
		if self._logger:
			self._logger.info(f"Exported module '{self.name}' to '{path}'")
	
	def __enter__(self) -> 'IOTextModule':
		"""
		Enter context manager.
		
		Returns
		-------
		IOTextModule
			Self reference for context management
		"""
		return self
	
	def __exit__(self, exc_type, exc_val, exc_tb) -> None:
		"""
		Exit context manager with cleanup.
		
		Parameters
		----------
		exc_type : type or None
			Exception type if an exception was raised
			
		exc_val : Exception or None
			Exception value if an exception was raised
			
		exc_tb : traceback or None
			Traceback if an exception was raised
		"""
		self.disable_hot_reload()
		self._unregister()
		
		if exc_type and self._logger:
			self._logger.error(f"Module '{self.name}' exited with error: {exc_val}")
	
	def __del__(self) -> None:
		"""Cleanup on deletion (destructor)."""
		try:
			self.disable_hot_reload()
			self._unregister()
		except Exception:
			pass
	
	def __repr__(self) -> str:
		"""
		Return string representation for debugging.
		
		Returns
		-------
		str
			Detailed representation string
		"""
		kind = "virtual" if self.is_virtual else "file"
		mode = self.storage_mode.value
		state = self.state.value
		return (f"<IOTextModule {kind} mode={mode} state={state} "
				f"name='{self.name}' size={self.get_size()}>")
	
	def __str__(self) -> str:
		"""
		Return user-friendly string representation.
		
		Returns
		-------
		str
			Human-readable description
		"""
		return f"Module('{self.name}', {self.storage_mode.value}, {self.state.value})"


def open_module(
	module_or_string: Union[str, ModuleType],
	storage_mode: ModuleStorageMode = ModuleStorageMode.PERSISTENT,
	enable_sandbox: bool = False,
	sandbox_config: Optional[SandboxConfig] = None,
	is_virtual: Optional[bool] = None,
	**kwargs
) -> IOTextModule:
	"""
	Open or create a module with comprehensive feature support.
	
	This function provides a unified interface for accessing modules,
	creating virtual modules, and configuring their behavior with
	extensive options.
	
	Parameters
	----------
	module_or_string : Union[str, ModuleType]
		Module name, file path, or existing module object
		
	storage_mode : ModuleStorageMode, optional
		Storage mode for the module, by default PERSISTENT
		
	enable_sandbox : bool, optional
		Whether to enable sandboxed execution, by default False
		
	sandbox_config : Optional[SandboxConfig], optional
		Custom sandbox configuration
		
	is_virtual : Optional[bool], optional
		Force virtual/real mode, auto-detected if None
		
	**kwargs
		Additional arguments passed to IOTextModule constructor
		
	Returns
	-------
	IOTextModule
		Configured IOTextModule instance
		
	Examples
	--------
	>>> # Open existing module
	>>> mod = open_module("math")
	>>> 
	>>> # Create virtual module
	>>> mod = open_module("my_virtual_module", is_virtual=True)
	>>> mod.write("def hello(): return 'Hello'")
	>>> 
	>>> # Open with sandbox and custom storage
	>>> mod = open_module(
	...	 "untrusted_code",
	...	 enable_sandbox=True,
	...	 storage_mode=ModuleStorageMode.CACHED
	... )
	>>> 
	>>> # Open from file path
	>>> mod = open_module("/path/to/module.py")
	"""
	# Check if already an IOTextModule in registry
	if isinstance(module_or_string, str):
		existing = IOTextModule.get_registered_modules()
		if module_or_string in existing:
			mod = IOTextModule.get_module(module_or_string)
			if mod:
				return mod
	
	# Handle module object
	if isinstance(module_or_string, ModuleType):
		module = module_or_string
		name = module.__name__
	else:
		name = module_or_string
		
		# Check if it's a file path
		if os.path.exists(name) and name.endswith('.py'):
			path = Path(name).resolve()
			spec = importlib.util.spec_from_file_location(path.stem, path)
			if spec and spec.loader:
				module = importlib.util.module_from_spec(spec)
				sys.modules[path.stem] = module
				is_virtual = False
				storage_mode = ModuleStorageMode.PERSISTENT
				return IOTextModule(
					module,
					is_virtual=False,
					storage_mode=storage_mode,
					enable_sandbox=enable_sandbox,
					sandbox_config=sandbox_config,
					**kwargs
				)
		
		# Check if already in sys.modules
		if name in sys.modules:
			module = sys.modules[name]
			if is_virtual is None:
				is_virtual = not hasattr(module, '__file__') or not module.__file__
			return IOTextModule(
				module,
				is_virtual=is_virtual,
				storage_mode=storage_mode,
				enable_sandbox=enable_sandbox,
				sandbox_config=sandbox_config,
				**kwargs
			)
		
		# Try to import
		try:
			module = importlib.import_module(name)
			if is_virtual is None:
				is_virtual = False
			return IOTextModule(
				module,
				is_virtual=is_virtual,
				storage_mode=storage_mode,
				enable_sandbox=enable_sandbox,
				sandbox_config=sandbox_config,
				**kwargs
			)
		except ModuleNotFoundError:
			# Create virtual module
			module = ModuleType(name)
			sys.modules[name] = module
			if is_virtual is None:
				is_virtual = True
			return IOTextModule(
				module,
				is_virtual=is_virtual,
				storage_mode=storage_mode,
				enable_sandbox=enable_sandbox,
				sandbox_config=sandbox_config,
				**kwargs
			)


def create_virtual_module(
	name: str,
	code: Optional[str] = None,
	**kwargs
) -> IOTextModule:
	"""
	Create a virtual module with optional initial code.
	
	Parameters
	----------
	name : str
		Module name (unique identifier)
		
	code : Optional[str], optional
		Initial module code to write
		
	**kwargs
		Additional arguments passed to IOTextModule constructor
		
	Returns
	-------
	IOTextModule
		Virtual module instance (RAM-only)
		
	Examples
	--------
	>>> mod = create_virtual_module(
	...	 "dynamic_module",
	...	 code="def greet(): return 'Hello'"
	... )
	>>> mod.exec()
	>>> print(mod.module.greet())
	'Hello'
	"""
	module = ModuleType(name)
	sys.modules[name] = module
	
	mod = IOTextModule(
		module,
		is_virtual=True,
		storage_mode=ModuleStorageMode.VIRTUAL,
		**kwargs
	)
	
	if code:
		mod.write(code)
	
	return mod


def load_module_from_file(
	path: Union[str, Path],
	module_name: Optional[str] = None,
	**kwargs
) -> IOTextModule:
	"""
	Load a module from a file path.
	
	Parameters
	----------
	path : Union[str, Path]
		Path to Python file (.py)
		
	module_name : Optional[str], optional
		Module name (derived from filename if None)
		
	**kwargs
		Additional arguments for IOTextModule
		
	Returns
	-------
	IOTextModule
		Loaded module instance
		
	Raises
	------
	FileNotFoundError
		If the file does not exist
	ImportError
		If the module cannot be loaded
		
	Examples
	--------
	>>> mod = load_module_from_file("/path/to/module.py")
	>>> print(mod.get_functions())
	"""
	path = Path(path).resolve()
	
	if not path.exists():
		raise FileNotFoundError(f"Module file not found: {path}")
	
	if module_name is None:
		module_name = path.stem
	
	spec = importlib.util.spec_from_file_location(module_name, path)
	if spec is None or spec.loader is None:
		raise ImportError(f"Could not load module from {path}")
	
	module = importlib.util.module_from_spec(spec)
	sys.modules[module_name] = module
	
	return IOTextModule(
		module,
		is_virtual=False,
		storage_mode=ModuleStorageMode.PERSISTENT,
		**kwargs
	)


# Export public interface
__all__ = [
	'IOTextModule',
	'ModuleStorageMode',
	'ModuleState',
	'ModuleEvent',
	'ModuleSnapshot',
	'open_module',
	'create_virtual_module',
	'load_module_from_file',
]