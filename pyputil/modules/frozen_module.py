#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Frozen Module Creator 
==============================================================

Features
--------
- Create frozen modules from source code or .py files
- Import frozen modules without any files on disk
- Handle circular imports and package hierarchies
- Comprehensive error handling and warnings
- Full type hints and documentation
- Optional bytecode caching for performance

Example
-------
>>> from pyputil.modules import FrozenModuleCreator
>>> creator = FrozenModuleCreator()
>>> creator.add_module('mypackage.math', '''
... def add(a, b):
...     return a + b
... PI = 3.14159
... ''')
>>> creator.freeze_all()
>>> creator.install_finder()
>>> import mypackage.math
>>> print(mypackage.math.PI)
3.14159
"""

import marshal
import importlib
import importlib.abc
import importlib.machinery
import types
import sys
import os
import warnings
import logging
import hashlib
import time
import ast
from typing import Dict, Optional, List, Set, Tuple, Any, Union, Callable
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from contextlib import contextmanager

from ._frozen_custom_warnings import ( 
    FrozenModuleError,
    ModuleCompilationError,
    ModuleNotFoundError,
    DuplicateModuleWarning,
    ImportCycleWarning,
    CompatibilityWarning
)


PY_VERSION = sys.version_info
PY36_PLUS = PY_VERSION >= (3, 6)
PY37_PLUS = PY_VERSION >= (3, 7)
PY38_PLUS = PY_VERSION >= (3, 8)
PY39_PLUS = PY_VERSION >= (3, 9)
PY310_PLUS = PY_VERSION >= (3, 10)
PY311_PLUS = PY_VERSION >= (3, 11)
PY312_PLUS = PY_VERSION >= (3, 12)

# Configure warnings
warnings.filterwarnings('default', category=UserWarning, module=__name__)


class FreezeMode(Enum):
    """Modes for freezing modules with different strictness levels."""
    STRICT = "strict"      # Fail on any warning/error
    LENIENT = "lenient"    # Continue with warnings (default)
    SILENT = "silent"      # Suppress most warnings
    DEBUG = "debug"        # Verbose output for debugging


# ============================================================================
# Version-Specific Utilities
# ============================================================================

def get_magic_number() -> bytes:
    """
    Get the Python magic number for .pyc files based on version.
    
    Returns
    -------
    bytes
        The magic number bytes (4-16 bytes depending on Python version)
    """
    if PY37_PLUS:
        return importlib.util.MAGIC_NUMBER
    else:
        # Python 3.5-3.6 compatibility
        try:
            import imp
            return imp.get_magic()
        except (ImportError, AttributeError):
            # Fallback - should work for most versions
            return b'\x33\x0d\x0a\x0a'


def get_pyc_header(source_hash: str = "") -> bytes:
    """
    Generate .pyc header for the current Python version.
    
    Parameters
    ----------
    source_hash : str, optional
        Source hash for Python 3.7+ hash-based .pyc
    
    Returns
    -------
    bytes
        Header bytes for .pyc file
    """
    magic = get_magic_number()
    
    if PY37_PLUS:
        # Python 3.7+ uses 16-byte header: magic(4) + bitfield(4) + hash(8)
        header = magic + b'\x00' * 4  # bitfield
        if source_hash:
            # Add hash if provided
            hash_bytes = source_hash.encode()[:8].ljust(8, b'\0')
            header += hash_bytes
        else:
            header += b'\0' * 8
        return header
    else:
        # Python 3.5-3.6 uses 12-byte header: magic(4) + timestamp(4) + size(4)
        import struct
        timestamp = int(time.time()).to_bytes(4, 'little')
        size = 0  # We don't know the size
        return magic + timestamp + size


# ============================================================================
# Bytecode Cache
# ============================================================================

class BytecodeCache:
    """
    Cache for compiled bytecode to avoid recompilation.
    
    Parameters
    ----------
    cache_dir : Optional[Path]
        Directory to store cached bytecode files. If None, caching is disabled.
    ttl : int, optional
        Time-to-live in seconds for cache entries (default: 86400 = 24 hours)
    """
    
    def __init__(self, cache_dir: Optional[Path] = None, ttl: int = 86400):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.ttl = ttl
        self._stats = {"hits": 0, "misses": 0, "writes": 0}
        
        if self.cache_dir:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
            except (IOError, OSError) as e:
                warnings.warn(f"Could not create cache directory: {e}", RuntimeWarning)
                self.cache_dir = None
    
    def _get_cache_key(self, name: str, source_hash: str) -> str:
        """Generate a cache key for a module."""
        safe_name = name.replace('.', '_').replace('-', '_')
        return f"{safe_name}_{source_hash}.pyc"
    
    def _get_cache_path(self, name: str, source_hash: str) -> Optional[Path]:
        """Get the full path to a cached bytecode file."""
        if not self.cache_dir:
            return None
        return self.cache_dir / self._get_cache_key(name, source_hash)
    
    def get_cached_bytecode(self, name: str, source: str) -> Optional[bytes]:
        """
        Get cached bytecode if it exists and is valid.
        
        Parameters
        ----------
        name : str
            Module name
        source : str
            Source code (for hash calculation)
            
        Returns
        -------
        Optional[bytes]
            Cached bytecode if available, None otherwise
        """
        if not self.cache_dir:
            return None
        
        source_hash = hashlib.sha256(source.encode()).hexdigest()[:16]
        cache_path = self._get_cache_path(name, source_hash)
        
        if not cache_path or not cache_path.exists():
            self._stats["misses"] += 1
            return None
        
        # Check TTL
        try:
            mtime = cache_path.stat().st_mtime
            if time.time() - mtime > self.ttl:
                # Cache expired
                try:
                    cache_path.unlink()
                except OSError:
                    pass
                self._stats["misses"] += 1
                return None
        except OSError:
            self._stats["misses"] += 1
            return None
        
        try:
            with open(cache_path, 'rb') as f:
                # Skip .pyc header
                header_size = 16 if PY37_PLUS else 12
                f.read(header_size)
                bytecode = f.read()
            
            self._stats["hits"] += 1
            return bytecode
        except (IOError, OSError) as e:
            warnings.warn(f"Failed to read cache for {name}: {e}", RuntimeWarning)
            self._stats["misses"] += 1
            return None
    
    def cache_bytecode(self, name: str, source: str, bytecode: bytes) -> bool:
        """
        Cache bytecode for future use.
        
        Parameters
        ----------
        name : str
            Module name
        source : str
            Source code (for hash calculation)
        bytecode : bytes
            Bytecode to cache
            
        Returns
        -------
        bool
            True if caching succeeded, False otherwise
        """
        if not self.cache_dir:
            return False
        
        source_hash = hashlib.sha256(source.encode()).hexdigest()[:16]
        cache_path = self._get_cache_path(name, source_hash)
        
        if not cache_path:
            return False
        
        try:
            header = get_pyc_header(source_hash)
            with open(cache_path, 'wb') as f:
                f.write(header)
                f.write(bytecode)
            
            self._stats["writes"] += 1
            return True
        except (IOError, OSError) as e:
            warnings.warn(f"Failed to cache {name}: {e}", RuntimeWarning)
            return False
    
    def clear(self, older_than: Optional[int] = None) -> int:
        """
        Clear cache entries.
        
        Parameters
        ----------
        older_than : Optional[int]
            Remove entries older than this many seconds
            
        Returns
        -------
        int
            Number of entries removed
        """
        if not self.cache_dir:
            return 0
        
        removed = 0
        now = time.time()
        
        for cache_file in self.cache_dir.glob("*.pyc"):
            try:
                if older_than:
                    mtime = cache_file.stat().st_mtime
                    if now - mtime > older_than:
                        cache_file.unlink()
                        removed += 1
                else:
                    cache_file.unlink()
                    removed += 1
            except OSError:
                continue
        
        return removed
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return self._stats.copy()


# ============================================================================
# Module Information Classes
# ============================================================================

@dataclass
class FrozenModuleInfo:
    """
    Information about a frozen module.
    
    Parameters
    ----------
    name : str
        Fully qualified module name
    source : str
        Original source code
    bytecode : bytes
        Marshalled bytecode
    """
    name: str
    source: str
    bytecode: bytes
    dependencies: Set[str] = field(default_factory=set)
    hash: str = field(init=False)
    size: int = field(init=False)
    compilation_time: float = field(default=0.0, init=False)
    timestamp: float = field(default_factory=time.time, init=False)
    
    def __post_init__(self):
        """Calculate derived fields after initialization."""
        self.hash = hashlib.sha256(self.bytecode).hexdigest()[:16]
        self.size = len(self.bytecode)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'name': self.name,
            'source': self.source,
            'bytecode': self.bytecode.hex() if self.bytecode else '',
            'dependencies': list(self.dependencies),
            'hash': self.hash,
            'size': self.size,
            'timestamp': self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FrozenModuleInfo':
        """Create from dictionary."""
        info = cls(
            name=data['name'],
            source=data['source'],
            bytecode=bytes.fromhex(data['bytecode']) if data.get('bytecode') else b''
        )
        info.dependencies = set(data.get('dependencies', []))
        info.timestamp = data.get('timestamp', time.time())
        return info
    
    def __repr__(self) -> str:
        return f"<FrozenModuleInfo {self.name} ({self.size} bytes, hash={self.hash})>"


@dataclass
class FreezeStats:
    """Statistics about the freezing process."""
    total_modules: int = 0
    successful_frozen: int = 0
    failed_modules: List[str] = field(default_factory=list)
    total_size: int = 0
    compilation_time: float = 0.0
    dependency_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage."""
        if self.total_modules == 0:
            return 0.0
        return (self.successful_frozen / self.total_modules) * 100
    
    @property
    def elapsed_time(self) -> float:
        """Get elapsed time."""
        end = self.end_time or time.time()
        return end - self.start_time
    
    def finish(self):
        """Mark the end of freezing."""
        self.end_time = time.time()
    
    def __str__(self) -> str:
        """Human-readable representation."""
        return (
            f"FreezeStats(total={self.total_modules}, "
            f"success={self.successful_frozen} ({self.success_rate:.1f}%), "
            f"size={self.total_size:,} bytes, "
            f"time={self.elapsed_time:.3f}s)"
        )


# ============================================================================
# Module Loader 
# ============================================================================

class FrozenModuleLoader(importlib.abc.Loader):
    """
    Loader for frozen modules that exist only in memory.
    
    This loader mimics how CPython loads internal frozen modules.
    
    Parameters
    ----------
    frozen_modules : Dict[str, FrozenModuleInfo]
        Dictionary mapping module names to their frozen information
    """
    
    def __init__(self, frozen_modules: Dict[str, FrozenModuleInfo]):
        self.frozen_modules = frozen_modules
        self._loading_modules: Set[str] = set()
        self._loaded_modules: Dict[str, types.ModuleType] = {}
    
    def create_module(self, spec) -> types.ModuleType:
        """
        Create a new module object.
        
        This method exists for Python 3.5+ compatibility.
        """
        return types.ModuleType(spec.name)
    
    def exec_module(self, module: types.ModuleType) -> None:
        """
        Execute the frozen bytecode in the module's namespace.
        
        Parameters
        ----------
        module : types.ModuleType
            The module object to execute in
            
        Raises
        ------
        ModuleNotFoundError
            If the module is not found in frozen modules
        ImportError
            If there's an error during execution
        """
        module_name = module.__name__
        
        # Check for circular imports
        if module_name in self._loading_modules:
            warnings.warn(
                f"Circular import detected while loading frozen module {module_name}",
                ImportCycleWarning,
                stacklevel=2
            )
            return
        
        if module_name not in self.frozen_modules:
            raise ModuleNotFoundError(f"No frozen module named {module_name}")
        
        frozen_info = self.frozen_modules[module_name]
        self._loading_modules.add(module_name)
        
        try:
            # Set standard module attributes
            module.__file__ = None
            module.__cached__ = None
            
            # Set package attribute
            if '.' in module_name:
                module.__package__ = module_name.rpartition('.')[0]
            else:
                module.__package__ = None
            
            # Add to loaded modules cache before execution
            self._loaded_modules[module_name] = module
            
            # Execute the bytecode
            code = marshal.loads(frozen_info.bytecode)
            
            # For Python 3.5+, we can just use exec
            exec(code, module.__dict__)
            
        except Exception as e:
            # Clean up on error
            self._loaded_modules.pop(module_name, None)
            raise ImportError(f"Failed to execute frozen module {module_name}: {e}") from e
        finally:
            self._loading_modules.remove(module_name)

    def load_module(self, fullname: str) -> types.ModuleType:
        """
        Legacy module loading method.
        
        Parameters
        ----------
        fullname : str
            Module name to load
            
        Returns
        -------
        types.ModuleType
            The loaded module
        """
        # Check if already loaded
        if fullname in sys.modules:
            return sys.modules[fullname]
        
        # Create a new module
        module = types.ModuleType(fullname)
        sys.modules[fullname] = module
        
        try:
            self.exec_module(module)
        except Exception:
            # Clean up on error
            if fullname in sys.modules:
                del sys.modules[fullname]
            raise
        
        return module
    
    def module_repr(self, module) -> str:
        """Return a string representation of the frozen module."""
        return f"<module '{module.__name__}' (frozen)>"


# ============================================================================
# Module Finder 
# ============================================================================

class FrozenModuleFinder(importlib.abc.MetaPathFinder):
    """
    Meta path finder that locates frozen modules before the regular import system.
    
    Parameters
    ----------
    frozen_modules : Dict[str, FrozenModuleInfo]
        Dictionary mapping module names to their frozen information
    """
    
    def __init__(self, frozen_modules: Dict[str, FrozenModuleInfo]):
        self.frozen_modules = frozen_modules
        self.loader = FrozenModuleLoader(frozen_modules)
        self._package_cache: Dict[str, bool] = {}
    
    def find_spec(self, fullname: str, path=None, target=None) -> Optional[importlib.machinery.ModuleSpec]:
        """
        Find the spec for a frozen module.
        
        Parameters
        ----------
        fullname : str
            Fully qualified module name
        path : optional
            Submodule path (unused for frozen modules)
        target : optional
            Target module (unused)
            
        Returns
        -------
        Optional[ModuleSpec]
            Module spec if the module is frozen, None otherwise
        """
        if fullname in self.frozen_modules:
            # Determine if this is a package
            is_package = self._is_package(fullname)
            
            return importlib.machinery.ModuleSpec(
                fullname,
                self.loader,
                origin='frozen',
                is_package=is_package
            )
        
        return None

    def find_module(self, fullname: str, path=None) -> Optional[FrozenModuleLoader]:
        """
        Legacy find method for older Python versions.
        
        Parameters
        ----------
        fullname : str
            Module name
        path : optional
            Search path
            
        Returns
        -------
        Optional[FrozenModuleLoader]
            Loader if module exists, None otherwise
        """
        if fullname in self.frozen_modules:
            return self.loader
        return None
    
    def _is_package(self, fullname: str) -> bool:
        """
        Determine if a frozen module is a package.
        
        A module is considered a package if another frozen module has it as a prefix
        or if its name ends with '.__init__' (for package initialization modules).
        """
        if fullname in self._package_cache:
            return self._package_cache[fullname]
        
        # Check if any other module has this as a prefix
        prefix = fullname + '.'
        is_package = any(name.startswith(prefix) for name in self.frozen_modules)
        
        # Also check for __init__ modules
        if fullname.endswith('.__init__'):
            is_package = True
        
        self._package_cache[fullname] = is_package
        return is_package
    
    def invalidate_caches(self):
        """Invalidate internal caches."""
        self._package_cache.clear()


# ============================================================================
# Main Creator Class
# ============================================================================

class FrozenModuleCreator:
    """
    Create true frozen modules that are compiled into memory.
    
    Parameters
    ----------
    mode : FreezeMode, optional
        Freezing mode (STRICT, LENIENT, SILENT, DEBUG). Default is LENIENT.
    cache_dir : Optional[Path], optional
        Directory for caching compiled bytecode
    log_level : int, optional
        Logging level (default: logging.WARNING)
    name_prefix : str, optional
        Prefix to add to all module names (for namespacing)
    
    Attributes
    ----------
    modules : Dict[str, str]
        Dictionary of module names to source code
    frozen : Dict[str, FrozenModuleInfo]
        Dictionary of successfully frozen modules
    stats : FreezeStats
        Statistics about the freezing process
    bytecode_cache : BytecodeCache
        Cache for compiled bytecode
    
    Examples
    --------
    >>> creator = FrozenModuleCreator()
    >>> creator.add_module('hello', 'def greet(): return "Hello World"')
    >>> creator.freeze_all()
    >>> creator.install_finder()
    >>> import hello
    >>> print(hello.greet())
    Hello World
    """
    
    def __init__(
        self,
        mode: FreezeMode = FreezeMode.LENIENT,
        cache_dir: Optional[Path] = None,
        log_level: int = logging.WARNING,
        name_prefix: str = ""
    ):
        self.mode = mode
        self.name_prefix = name_prefix
        self.modules: Dict[str, str] = {}
        self.frozen: Dict[str, FrozenModuleInfo] = {}
        self.bytecode_cache = BytecodeCache(cache_dir)
        self.stats = FreezeStats()
        self._finder: Optional[FrozenModuleFinder] = None
        self._compilation_warnings: List[str] = []
        
        # Set up logging
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(log_level)
        if not self.logger.handlers and mode == FreezeMode.DEBUG:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
            self.logger.addHandler(handler)
        
        # Check compatibility
        self._check_compatibility()
    
    def _check_compatibility(self) -> None:
        """Check Python version compatibility and issue appropriate warnings."""
        if PY_VERSION < (3, 5):
            warnings.warn(
                "Python < 3.5 is not officially supported. "
                "Some features may not work correctly.",
                CompatibilityWarning,
                stacklevel=2
            )
        elif PY_VERSION >= (3, 12):
            warnings.warn(
                f"Python {PY_VERSION.major}.{PY_VERSION.minor} may have changes "
                "to the import system. Test thoroughly with your target version.",
                CompatibilityWarning,
                stacklevel=2
            )
        
        if PY_VERSION < (3, 7) and self.mode == FreezeMode.DEBUG:
            warnings.warn(
                "Debug mode may have limited functionality in Python < 3.7",
                CompatibilityWarning,
                stacklevel=2
            )
    
    def _warn(self, message: str, category: type = UserWarning, stacklevel: int = 2) -> None:
        """
        Issue a warning based on the current mode.
        
        Parameters
        ----------
        message : str
            Warning message
        category : type
            Warning category class
        stacklevel : int
            Stack level for warning
        """
        if self.mode == FreezeMode.SILENT:
            return
        elif self.mode == FreezeMode.STRICT:
            raise category(message)
        else:
            if self.mode == FreezeMode.DEBUG:
                print(f"WARNING: {message}")
            warnings.warn(message, category, stacklevel=stacklevel)
            self._compilation_warnings.append(message)
    
    def _get_fullname(self, name: str) -> str:
        """Apply name prefix to module name."""
        if self.name_prefix and not name.startswith(self.name_prefix):
            return f"{self.name_prefix}{name}"
        return name
    
    def add_module(self, name: str, source: str, force: bool = False) -> str:
        """
        Add a module to be frozen from source code.
        
        Parameters
        ----------
        name : str
            Full module name (e.g., 'mypackage.mymodule')
        source : str
            Python source code for the module
        force : bool, optional
            If True, overwrite existing module with same name
            
        Returns
        -------
        str
            The full module name (with prefix applied)
            
        Raises
        ------
        ValueError
            If module name is invalid
        DuplicateModuleWarning
            If module already exists and force=False (in LENIENT mode)
        """
        fullname = self._get_fullname(name)
        self._validate_module_name(fullname)
        
        if fullname in self.modules and not force:
            self._warn(
                f"Module {fullname} already exists. Use force=True to overwrite.",
                DuplicateModuleWarning
            )
            return fullname
        
        self.modules[fullname] = source
        self.logger.info(f"Added module: {fullname} ({len(source)} bytes)")
        
        if self.mode == FreezeMode.DEBUG:
            print(f"✓ Added module: {fullname}")
        
        return fullname
    
    def add_module_from_file(
        self,
        name: str,
        filename: Union[str, Path],
        encoding: str = 'utf-8',
        force: bool = False
    ) -> str:
        """
        Add a module from an existing .py file.
        
        Parameters
        ----------
        name : str
            Full module name
        filename : Union[str, Path]
            Path to .py file
        encoding : str, optional
            File encoding (default: utf-8)
        force : bool, optional
            If True, overwrite existing module
            
        Returns
        -------
        str
            The full module name (with prefix applied)
            
        Raises
        ------
        FileNotFoundError
            If the file doesn't exist
        IOError
            If there's an error reading the file
        """
        filepath = Path(filename)
        fullname = self._get_fullname(name)
        
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        
        if filepath.suffix != '.py':
            self._warn(
                f"File {filepath} does not have .py extension",
                UserWarning
            )
        
        try:
            source = filepath.read_text(encoding=encoding)
            self.add_module(fullname, source, force)
            self.logger.info(f"Added module from file: {fullname} -> {filepath}")
            
            if self.mode == FreezeMode.DEBUG:
                print(f"✓ Added module from file: {fullname} -> {filepath}")
            
            return fullname
        except (IOError, OSError) as e:
            raise IOError(f"Failed to read {filepath}: {e}") from e
    
    def add_module_from_package(
        self,
        package_path: Union[str, Path],
        prefix: str = "",
        recursive: bool = True,
        exclude: Optional[List[str]] = None
    ) -> List[str]:
        """
        Add all modules from a package directory.
        
        Parameters
        ----------
        package_path : Union[str, Path]
            Path to package directory
        prefix : str, optional
            Module name prefix (applied before the global name_prefix)
        recursive : bool, optional
            If True, recursively add submodules
        exclude : Optional[List[str]], optional
            List of module names to exclude
            
        Returns
        -------
        List[str]
            List of added module names
            
        Raises
        ------
        NotADirectoryError
            If package_path is not a directory
        """
        package_dir = Path(package_path)
        added_modules = []
        exclude = exclude or []
        
        if not package_dir.is_dir():
            raise NotADirectoryError(f"Not a directory: {package_dir}")
        
        # Check for __init__.py to confirm it's a package
        init_file = package_dir / '__init__.py'
        if not init_file.exists():
            self._warn(
                f"Directory {package_dir} may not be a valid package (no __init__.py)",
                UserWarning
            )
        
        # Add modules recursively
        pattern = '**/*.py' if recursive else '*.py'
        for py_file in sorted(package_dir.glob(pattern)):
            if py_file.name in exclude:
                continue
            
            # Calculate module name
            if py_file.name == '__init__.py':
                # Package __init__ module
                rel_path = py_file.parent.relative_to(package_dir.parent if recursive else package_dir)
                module_name = prefix + str(rel_path).replace('/', '.')
            else:
                # Regular module
                rel_path = py_file.relative_to(package_dir.parent if recursive else package_dir)
                module_name = prefix + str(rel_path.with_suffix('')).replace('/', '.')
            
            if module_name in exclude:
                continue
            
            try:
                self.add_module_from_file(module_name, py_file)
                added_modules.append(module_name)
            except Exception as e:
                self._warn(f"Failed to add {module_name}: {e}", UserWarning)
        
        return added_modules
    
    def _validate_module_name(self, name: str) -> None:
        """Validate a module name."""
        if not name:
            raise ValueError("Module name cannot be empty")
        
        if '..' in name:
            raise ValueError(f"Invalid module name (contains '..'): {name}")
        
        parts = name.split('.')
        for part in parts:
            if not part:
                raise ValueError(f"Invalid module name (empty part): {name}")
            if part in ('', '.', '..'):
                raise ValueError(f"Invalid module name part: {part}")
    
    def _compile_to_bytecode(self, name: str, source: str) -> Tuple[bytes, float, bool]:
        """
        Compile source code to bytecode.
        
        Parameters
        ----------
        name : str
            Module name (for error messages)
        source : str
            Python source code
            
        Returns
        -------
        Tuple[bytes, float, bool]
            (marshalled bytecode, compilation time, from_cache)
            
        Raises
        ------
        ModuleCompilationError
            If compilation fails
        """
        # Check cache first
        cached = self.bytecode_cache.get_cached_bytecode(name, source)
        if cached is not None:
            return cached, 0.0, True
        
        # Compile
        start_time = time.perf_counter()
        try:
            # Use appropriate optimization level
            optimize = 2 if PY37_PLUS else 0
            code = compile(source, f'<frozen {name}>', 'exec', optimize=optimize)
            bytecode = marshal.dumps(code)
        except SyntaxError as e:
            raise ModuleCompilationError(f"Syntax error in {name}: {e}") from e
        except Exception as e:
            raise ModuleCompilationError(f"Failed to compile {name}: {e}") from e
        
        compilation_time = time.perf_counter() - start_time
        
        # Cache the result
        self.bytecode_cache.cache_bytecode(name, source, bytecode)
        
        return bytecode, compilation_time, False
    
    def _analyze_dependencies(self, source: str) -> Set[str]:
        """
        Analyze source code to find import dependencies.
        
        Parameters
        ----------
        source : str
            Python source code
            
        Returns
        -------
        Set[str]
            Set of module dependencies
        """
        dependencies = set()
        
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        # Get top-level module name
                        deps = alias.name.split('.')[0]
                        dependencies.add(deps)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        # Get top-level module name
                        deps = node.module.split('.')[0]
                        dependencies.add(deps)
        except SyntaxError:
            # If we can't parse, use simple string search as fallback
            import_lines = [line for line in source.split('\n') 
                          if line.strip().startswith(('import ', 'from '))]
            for line in import_lines:
                parts = line.split()
                if len(parts) > 1:
                    deps = parts[1].split('.')[0]
                    dependencies.add(deps)
        except Exception:
            # Ignore other errors during analysis
            pass
        
        return dependencies
    
    def freeze_all(self, show_progress: bool = False) -> FreezeStats:
        """
        Compile all added modules to frozen bytecode.
        
        Parameters
        ----------
        show_progress : bool, optional
            If True, show progress bar (only in DEBUG mode)
            
        Returns
        -------
        FreezeStats
            Statistics about the freezing process
        """
        self.stats = FreezeStats(total_modules=len(self.modules))
        self._compilation_warnings = []
        
        modules_list = list(self.modules.items())
        
        for idx, (name, source) in enumerate(modules_list, 1):
            try:
                # Compile
                bytecode, comp_time, from_cache = self._compile_to_bytecode(name, source)
                
                # Analyze dependencies
                dependencies = self._analyze_dependencies(source)
                
                # Create module info
                frozen_info = FrozenModuleInfo(name, source, bytecode)
                frozen_info.dependencies = dependencies
                frozen_info.compilation_time = comp_time
                
                # Store
                self.frozen[name] = frozen_info
                
                # Update stats
                self.stats.successful_frozen += 1
                self.stats.total_size += len(bytecode)
                self.stats.compilation_time += comp_time
                self.stats.dependency_count += len(dependencies)
                
                if from_cache:
                    self.stats.cache_hits += 1
                else:
                    self.stats.cache_misses += 1
                
                # Progress reporting
                if show_progress and self.mode == FreezeMode.DEBUG:
                    cache_status = " (cached)" if from_cache else ""
                
                self.logger.info(
                    f"Frozen: {name} ({len(bytecode)} bytes, {comp_time:.3f}s, "
                    f"{len(dependencies)} deps)"
                )
                
            except Exception as e:
                self.stats.failed_modules.append(name)
                error_msg = f"Failed to freeze {name}: {e}"
                
                if self.mode == FreezeMode.STRICT:
                    self.stats.finish()
                    raise ModuleCompilationError(error_msg) from e
                else:
                    self._warn(error_msg, UserWarning)
        
        self.stats.finish()
        
        return self.stats
    
    def install_finder(self, at_front: bool = True) -> bool:
        """
        Install the frozen module finder in sys.meta_path.
        
        Parameters
        ----------
        at_front : bool, optional
            If True, insert at beginning (highest priority)
            
        Returns
        -------
        bool
            True if installed successfully
            
        Raises
        ------
        RuntimeError
            If no modules have been frozen yet (in STRICT mode)
        """
        if not self.frozen:
            if self.mode == FreezeMode.STRICT:
                raise RuntimeError("No frozen modules available. Call freeze_all() first.")
            else:
                self._warn("No frozen modules available. Call freeze_all() first.", UserWarning)
                return False
        
        # Remove existing finder if present
        self.uninstall_finder()
        
        # Create and install finder
        self._finder = FrozenModuleFinder(self.frozen)
        
        if at_front:
            sys.meta_path.insert(0, self._finder)
        else:
            sys.meta_path.append(self._finder)
        
        self.logger.info(f"Frozen module finder installed (position: {'front' if at_front else 'back'})")
        
        return True
    
    def uninstall_finder(self) -> bool:
        """
        Remove the frozen module finder from sys.meta_path.
        
        Returns
        -------
        bool
            True if finder was found and removed, False otherwise
        """
        for i, finder in enumerate(sys.meta_path):
            if isinstance(finder, FrozenModuleFinder):
                sys.meta_path.pop(i)
                self._finder = None
                self.logger.info("Frozen module finder uninstalled")
                return True
        return False
    
    def is_finder_installed(self) -> bool:
        """Check if the frozen module finder is currently installed."""
        return any(isinstance(f, FrozenModuleFinder) for f in sys.meta_path)
    
    def get_module_info(self, name: str) -> Optional[FrozenModuleInfo]:
        """Get information about a frozen module."""
        fullname = self._get_fullname(name)
        return self.frozen.get(fullname)
    
    def list_modules(self) -> List[str]:
        """Return a sorted list of all frozen module names."""
        return sorted(self.frozen.keys())
    
    def list_sources(self) -> List[str]:
        """Return a sorted list of all added module sources."""
        return sorted(self.modules.keys())
    
    def get_stats(self) -> FreezeStats:
        """Get current freezing statistics."""
        return self.stats
    
    def get_warnings(self) -> List[str]:
        """Get all warnings that occurred during freezing."""
        return self._compilation_warnings.copy()
    
    def clear(self) -> None:
        """Clear all modules and reset statistics."""
        self.modules.clear()
        self.frozen.clear()
        self.stats = FreezeStats()
        self._compilation_warnings.clear()
        self.logger.info("Cleared all modules and statistics")
    
    def remove_module(self, name: str) -> bool:
        """
        Remove a module from the list to be frozen.
        
        Parameters
        ----------
        name : str
            Module name to remove
            
        Returns
        -------
        bool
            True if module was removed, False if not found
        """
        fullname = self._get_fullname(name)
        removed = False
        
        if fullname in self.modules:
            del self.modules[fullname]
            removed = True
        
        if fullname in self.frozen:
            del self.frozen[fullname]
            removed = True
        
        return removed
    
    def export_frozen_modules(self) -> Dict[str, bytes]:
        """
        Export the frozen modules as a dictionary of bytecode.
        
        Returns
        -------
        Dict[str, bytes]
            Dictionary mapping module names to bytecode
        """
        return {name: info.bytecode for name, info in self.frozen.items()}
    
    def export_module_info(self) -> Dict[str, Dict[str, Any]]:
        """
        Export complete module information as serializable dictionaries.
        
        Returns
        -------
        Dict[str, Dict[str, Any]]
            Serializable module information
        """
        return {name: info.to_dict() for name, info in self.frozen.items()}
    
    def import_frozen_modules(self, modules: Dict[str, Union[bytes, Dict[str, Any]]]) -> int:
        """
        Import previously frozen modules.
        
        Parameters
        ----------
        modules : Dict[str, Union[bytes, Dict[str, Any]]]
            Either bytecode dictionaries or info dictionaries
            
        Returns
        -------
        int
            Number of modules imported
        """
        count = 0
        
        for name, data in modules.items():
            try:
                if isinstance(data, bytes):
                    # Simple bytecode only
                    frozen_info = FrozenModuleInfo(name, "", data)
                else:
                    # Full info dictionary
                    frozen_info = FrozenModuleInfo.from_dict(data)
                
                self.frozen[name] = frozen_info
                count += 1
            except Exception as e:
                self._warn(f"Failed to import module {name}: {e}", UserWarning)
        
        return count
    
    def save_state(self, filepath: Union[str, Path]) -> None:
        """
        Save the current state to a file for later loading.
        
        Parameters
        ----------
        filepath : Union[str, Path]
            Path to save the state
        """
        import json
        import base64
        
        output_path = Path(filepath)
        
        state = {
            'version': 1,
            'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            'mode': self.mode.value,
            'name_prefix': self.name_prefix,
            'modules': self.modules.copy(),
            'frozen': {
                name: info.to_dict()
                for name, info in self.frozen.items()
            }
        }
        
        # Convert bytecode in frozen dict to base64 for JSON
        for info in state['frozen'].values():
            if 'bytecode' in info and isinstance(info['bytecode'], str):
                # Already encoded
                pass
            elif 'bytecode' in info:
                info['bytecode'] = base64.b64encode(info['bytecode']).decode('ascii')
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        
        self.logger.info(f"State saved to: {output_path}")
    
    def load_state(self, filepath: Union[str, Path]) -> bool:
        """
        Load a previously saved state.
        
        Parameters
        ----------
        filepath : Union[str, Path]
            Path to load the state from
            
        Returns
        -------
        bool
            True if loaded successfully
        """
        import json
        import base64
        
        input_path = Path(filepath)
        
        if not input_path.exists():
            raise FileNotFoundError(f"State file not found: {input_path}")
        
        with open(input_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
        
        # Clear current state
        self.clear()
        
        # Restore state
        self.mode = FreezeMode(state.get('mode', 'lenient'))
        self.name_prefix = state.get('name_prefix', '')
        
        # Restore modules
        self.modules.update(state.get('modules', {}))
        
        # Restore frozen modules
        for name, info_dict in state.get('frozen', {}).items():
            if 'bytecode' in info_dict and isinstance(info_dict['bytecode'], str):
                info_dict['bytecode'] = base64.b64decode(info_dict['bytecode'])
            self.frozen[name] = FrozenModuleInfo.from_dict(info_dict)
        
        self.logger.info(f"State loaded from: {input_path}")
        return True


# ============================================================================
# Context Manager for Temporary Finder Installation
# ============================================================================

@contextmanager
def frozen_modules_context(creator: FrozenModuleCreator):
    """
    Context manager for temporarily using frozen modules.
    
    Parameters
    ----------
    creator : FrozenModuleCreator
        Creator instance with frozen modules
        
    Example
    -------
    >>> creator = FrozenModuleCreator()
    >>> creator.add_module('temp', 'x = 123')
    >>> creator.freeze_all()
    >>> 
    >>> with frozen_modules_context(creator):
    ...     import temp
    ...     print(temp.x)
    """
    try:
        creator.install_finder()
        yield
    finally:
        creator.uninstall_finder()


# ============================================================================
# High-Level Convenience Functions
# ============================================================================

def freeze_module(
    name: str,
    source: str,
    install: bool = True,
    **kwargs
) -> FrozenModuleCreator:
    """
    Convenience function to create and freeze a single module.
    
    Parameters
    ----------
    name : str
        Module name
    source : str
        Python source code
    install : bool, optional
        If True, install the finder immediately
    **kwargs
        Additional arguments for FrozenModuleCreator
        
    Returns
    -------
    FrozenModuleCreator
        Configured creator instance
        
    Example
    -------
    >>> creator = freeze_module('hello', 'def hi(): return "Hello"', install=True)
    >>> import hello
    >>> print(hello.hi())
    Hello
    """
    creator = FrozenModuleCreator(**kwargs)
    creator.add_module(name, source)
    creator.freeze_all()
    if install:
        creator.install_finder()
    return creator


def freeze_file(
    name: str,
    filename: Union[str, Path],
    install: bool = True,
    **kwargs
) -> FrozenModuleCreator:
    """
    Convenience function to freeze a module from a file.
    
    Parameters
    ----------
    name : str
        Module name
    filename : Union[str, Path]
        Path to .py file
    install : bool, optional
        If True, install the finder immediately
    **kwargs
        Additional arguments for FrozenModuleCreator
        
    Returns
    -------
    FrozenModuleCreator
        Configured creator instance
    """
    creator = FrozenModuleCreator(**kwargs)
    creator.add_module_from_file(name, filename)
    creator.freeze_all()
    if install:
        creator.install_finder()
    return creator


def freeze_package(
    package_path: Union[str, Path],
    prefix: str = "",
    recursive: bool = True,
    **kwargs
) -> FrozenModuleCreator:
    """
    Convenience function to freeze an entire package.
    
    Parameters
    ----------
    package_path : Union[str, Path]
        Path to package directory
    prefix : str, optional
        Module name prefix
    recursive : bool, optional
        If True, recursively freeze submodules
    **kwargs
        Additional arguments for FrozenModuleCreator
        
    Returns
    -------
    FrozenModuleCreator
        Configured creator instance
    """
    creator = FrozenModuleCreator(**kwargs)
    creator.add_module_from_package(package_path, prefix, recursive)
    creator.freeze_all()
    return creator


def get_frozen_module_names() -> List[str]:
    """
    Get names of all currently installed frozen modules.
    
    Returns
    -------
    List[str]
        List of frozen module names
    """
    for finder in sys.meta_path:
        if isinstance(finder, FrozenModuleFinder):
            return list(finder.frozen_modules.keys())
    return []


__all__ = [
    'FrozenModuleCreator',
    'FrozenModuleInfo',
    'FrozenModuleLoader',
    'FrozenModuleFinder',
    'FreezeMode',
    'FreezeStats',
    'frozen_modules_context',
    'freeze_module',
    'freeze_file',
    'freeze_package',
    'get_frozen_module_names',
    'FrozenModuleError',
    'ModuleCompilationError',
    'ModuleNotFoundError',
]

