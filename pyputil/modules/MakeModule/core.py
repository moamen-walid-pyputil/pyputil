#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Core module for creating and managing Python modules.

This module provides the MakeModule class for comprehensive module
management including creation, modification, building, publishing,
and profiling.
"""

import importlib
import inspect
import json
import os
import pickle
import shutil
import sys
import tempfile
import threading
import time
import tracemalloc
import weakref
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime
from functools import cached_property, lru_cache
from pathlib import Path
from types import FunctionType, ModuleType
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# Import local modules
from .cache import MakeCache
from .dataclasses import ModuleMetadata, ModuleStats, ProfileModule
from .enums import ModuleState
from .hasher import CryptographicHasher
from .registry import ThreadSafeRegistry
from .utils import SITE_PATH, atomic_write, compute_directory_size

try:
    import build
    from build import ProjectBuilder
except ImportError:
    build = None
    ProjectBuilder = None


from ...PyputilException import ModuleExistsError, PackageNotFoundError
from ...path.filetools import copy, move, read, write


class MakeModule:
    """
    Module creation and maker.

    Parameters
    ----------
    name : str
        Name of the module to create
    exist_ok : bool, default=False
        If True, don't raise error if module directory already exists
    enable_validation : bool, default=True
        Enable comprehensive module validation

    Attributes
    ----------
    name : str
        Module name
    path : Path
        Path to module directory
    location : Path
        Resolved location of module
    site : Optional[Path]
        Path in site-packages (if installed)
    history_file : Path
        Path to history tracking file
    metadata_file : Path
        Path to metadata file

    Raises
    ------
    TypeError
        If name is not a string
    ModuleExistsError
        If module already exists and exist_ok is False
    OSError
        If module directory creation fails

    Examples
    --------
    >>> module = MakeModule("mymodule")
    >>> module.add_file("__init__.py")
    >>> module.add_file("utils.py", "def hello(): return 'world'")
    >>> module.build()
    """

    # Class-level shared resources
    _global_registry = ThreadSafeRegistry()
    _cache_system = MakeCache(max_size=2000, ttl=7200)
    _hasher = CryptographicHasher("blake2b")

    def __init__(
        self, name: str, exist_ok: bool = False, enable_validation: bool = True
    ) -> None:
        """
        Initialize a new module creator with enhanced validation and tracking.

        Parameters
        ----------
        name : str
            Name of the module to create
        exist_ok : bool
            If True, don't raise error if module directory already exists
        enable_validation : bool
            Enable comprehensive module validation
        """
        # Validate input
        if not isinstance(name, str):
            raise TypeError(f"Expected str for 'name', got {type(name).__name__}")

        # Initialize instance variables
        self._validation_enabled = enable_validation
        self._state_history = []
        self._operation_lock = threading.RLock()
        self._metadata_cache = None
        self._observers = weakref.WeakSet()

        # Set up paths
        self.path = Path(name)
        self._original_path = self.path.resolve()

        # Check existence with caching
        if not self._check_existence(exist_ok):
            raise ModuleExistsError(f"Module '{name}' already exists in '{Path.cwd()}'")

        # Create module directory
        with self._operation_lock:
            self._create_module_directory()
            self._initialize_module_infrastructure()
            self._update_state(ModuleState.CREATED)
            self._global_registry.register(f"module_{self.name}", self)

    def _check_existence(self, exist_ok: bool) -> bool:
        """
        Check if module exists, respecting exist_ok parameter.

        Parameters
        ----------
        exist_ok : bool
            Whether existing modules are allowed

        Returns
        -------
        bool
            True if module can be created, False otherwise
        """
        cache_key = f"exists_{self.path}"
        cached_exists = self._cache_system.get(cache_key)

        if cached_exists is None:
            cached_exists = self.path.exists()
            self._cache_system.set(cache_key, cached_exists)

        return not cached_exists or exist_ok

    def _create_module_directory(self) -> None:
        """
        Create module directory with comprehensive error handling.

        Raises
        ------
        OSError
            If directory creation fails
        """
        try:
            self.path.mkdir(exist_ok=True, parents=True)
            self.name = self.path.name
            self.location = self.path.resolve()
            self.site = SITE_PATH / self.path if SITE_PATH else None
            self.history_file = self.path / Path(".history_data")
            self.metadata_file = self.path / Path(".module_metadata")
        except OSError as e:
            raise OSError(
                f"Failed to create module directory '{self.path}': {e}"
            ) from e

    def _initialize_module_infrastructure(self) -> None:
        """Initialize all module infrastructure components."""
        self._write_history(f"CREATR MODULE {self.name}")
        self._update_metadata()
        self._setup_file_watchers()

    def _setup_file_watchers(self) -> None:
        """Setup virtual file system watchers for monitoring changes."""
        # Placeholder for actual file watching implementation
        # In production, this could use watchdog or similar library
        pass

    def _update_state(self, state: ModuleState, details: str = "") -> None:
        """
        Update module state with comprehensive tracking.

        Parameters
        ----------
        state : ModuleState
            New state of the module
        details : str, optional
            Additional details about the state change
        """
        state_entry = {
            "state": state,
            "timestamp": datetime.now(),
            "details": details,
            "location": str(self.location),
        }
        self._state_history.append(state_entry)
        self._notify_observers("state_change", state_entry)

    def _compute_module_hash(self) -> str:
        """
        Compute cryptographic hash of entire module contents.

        Returns
        -------
        str
            Hexadecimal hash digest of module contents
        """
        module_data = b""
        for file_path in sorted(self.location.rglob("*")):
            if file_path.is_file():
                try:
                    module_data += file_path.read_bytes()
                    module_data += str(file_path.relative_to(self.location)).encode()
                except Exception:
                    continue

        return self._hasher.compute_hash(module_data, salt=self.name.encode())

    def _update_metadata(self) -> None:
        """Update comprehensive module metadata."""
        file_count = len([f for f in self.location.rglob("*") if f.is_file()])
        dir_count = len([d for d in self.location.rglob("*") if d.is_dir()])
        total_size = sum(
            f.stat().st_size for f in self.location.rglob("*") if f.is_file()
        )

        metadata = ModuleMetadata(
            name=self.name,
            path=self.location,
            created_at=datetime.now(),
            modified_at=datetime.now(),
            size_bytes=total_size,
            file_count=file_count,
            dir_count=dir_count,
            hash_digest=self._compute_module_hash(),
        )

        self.metadata_cache = metadata
        self._save_metadata_to_file(metadata)

    def _save_metadata_to_file(self, metadata: ModuleMetadata) -> None:
        """
        Save metadata to file using multiple serialization formats.

        Parameters
        ----------
        metadata : ModuleMetadata
            Metadata to save

        Raises
        ------
        OSError
            If file operations fail
        """
        try:
            metadata_dict = {
                "name": metadata.name,
                "path": str(metadata.path),
                "created_at": metadata.created_at.isoformat(),
                "modified_at": metadata.modified_at.isoformat(),
                "size_bytes": metadata.size_bytes,
                "file_count": metadata.file_count,
                "dir_count": metadata.dir_count,
                "hash_digest": metadata.hash_digest,
            }

            # Save as JSON for readability
            json_data = json.dumps(metadata_dict, indent=2)
            atomic_write(self.metadata_file, json_data)

            # Save as pickle for efficient loading
            pickle_file = self.metadata_file.with_suffix(".pickle")
            with open(pickle_file, "wb") as f:
                pickle.dump(metadata, f)

        except Exception as e:
            raise OSError(f"Failed to save metadata: {e}") from e

    def _load_metadata_from_file(self) -> Optional[ModuleMetadata]:
        """
        Load metadata from file with fallback strategies.

        Returns
        -------
        Optional[ModuleMetadata]
            Loaded metadata or None if not available
        """
        try:
            pickle_file = self.metadata_file.with_suffix(".pickle")
            if pickle_file.exists():
                with open(pickle_file, "rb") as f:
                    return pickle.load(f)

            if self.metadata_file.exists():
                json_data = self.metadata_file.read_text()
                if json_data:
                    metadata_dict = json.loads(json_data)
                    return ModuleMetadata(
                        name=metadata_dict["name"],
                        path=Path(metadata_dict["path"]),
                        created_at=datetime.fromisoformat(metadata_dict["created_at"]),
                        modified_at=datetime.fromisoformat(
                            metadata_dict["modified_at"]
                        ),
                        size_bytes=metadata_dict["size_bytes"],
                        file_count=metadata_dict["file_count"],
                        dir_count=metadata_dict["dir_count"],
                        hash_digest=metadata_dict["hash_digest"],
                    )
        except Exception as e:
            # Log error but don't fail
            pass

        return None

    @property
    def metadata_cache(self) -> Optional[ModuleMetadata]:
        """
        Get cached metadata with lazy loading.

        Returns
        -------
        Optional[ModuleMetadata]
            Cached metadata or None if not available
        """
        if self._metadata_cache is None:
            self._metadata_cache = self._load_metadata_from_file()
        return self._metadata_cache

    @metadata_cache.setter
    def metadata_cache(self, value: ModuleMetadata) -> None:
        """
        Set metadata cache with validation.

        Parameters
        ----------
        value : ModuleMetadata
            Metadata to cache

        Raises
        ------
        TypeError
            If value is not ModuleMetadata instance
        """
        if isinstance(value, ModuleMetadata):
            self._metadata_cache = value
            cache_key = f"metadata_{self.name}"
            self._cache_system.set(cache_key, value)
        else:
            raise TypeError("Expected ModuleMetadata instance")

    def _create(
        self, relative_path: Path, create_func: Callable, overwrite: bool = False
    ) -> None:
        """
        Internal method to create files/folders with transactional safety.

        Parameters
        ----------
        relative_path : Path
            Path relative to module root
        create_func : Callable
            Function that creates the file/folder
        overwrite : bool
            If True, overwrite existing files

        Raises
        ------
        FileExistsError
            If file exists and overwrite is False
        OSError
            If creation fails
        """
        target = self.location / relative_path

        if target.exists() and not overwrite:
            raise FileExistsError(
                f"'{relative_path}' already exists in '{self.location}'"
            )

        # Create temporary location for atomic operations
        temp_fd, temp_path_str = tempfile.mkstemp()
        temp_path = Path(temp_path_str)

        try:
            os.close(temp_fd)

            # Perform creation in temporary location
            create_func(temp_path)

            # Move to final location atomically
            if target.exists() and overwrite:
                target.unlink()

            shutil.move(str(temp_path), str(target))
            self._update_metadata()

        except Exception as e:
            # Cleanup on failure
            if temp_path.exists():
                temp_path.unlink()
            raise e
        finally:
            # Ensure temporary file is cleaned up
            if temp_path.exists():
                temp_path.unlink()

    def _read_history(self) -> str:
        """
        Enhanced history reading with caching and validation.

        Returns
        -------
        str
            History content
        """
        cache_key = f"history_{self.name}"
        cached_history = self._cache_system.get(cache_key)

        if cached_history is not None:
            return cached_history

        if not self.history_file.exists():
            self.history_file.touch()
            return ""

        try:
            history_content = self.history_file.read_text()
            self._cache_system.set(cache_key, history_content)
            return history_content
        except Exception:
            return ""

    def _write_history(self, data: str) -> None:
        """
        Enhanced history writing with atomic operations and caching.

        Parameters
        ----------
        data : str
            Data to write to history
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        entry = f"[{timestamp}] {data}\n"

        try:
            existing_content = self._read_history()
            new_content = existing_content + entry
            atomic_write(self.history_file, new_content)

            # Update cache
            cache_key = f"history_{self.name}"
            self._cache_system.set(cache_key, new_content)
        except Exception:
            # Silently fail on history write errors
            pass

    # Public API methods
    def add_file(
        self,
        filename: str,
        data: Any = None,
        encoding: str = "utf-8",
        overwrite: bool = False,
    ) -> None:
        """
        Add a file to the module with enhanced safety.

        Parameters
        ----------
        filename : str
            Name of the file to create
        data : Any, optional
            Content to write to file. Can be string, dict, list, or any object
        encoding : str, default='utf-8'
            File encoding
        overwrite : bool, default=False
            If True, overwrite existing file

        Raises
        ------
        FileExistsError
            If file exists and overwrite is False
        OSError
            If file creation fails

        Examples
        --------
        >>> module.add_file("utils.py", "def hello(): return 'world'")
        >>> module.add_file("config.yaml", {"key": "value"})
        """

        def create_file(p: Path):
            if data is None:
                p.touch()
            else:
                # Handle different data types
                if isinstance(data, (dict, list)):
                    try:
                        import yaml

                        processed_data = yaml.dump(
                            data, indent=2, default_flow_style=False
                        )
                    except ImportError:
                        import json

                        processed_data = json.dumps(data, indent=2)
                elif hasattr(data, "__dict__"):
                    processed_data = str(data)
                else:
                    processed_data = str(data)

                p.write_text(processed_data, encoding=encoding)

        self._create(Path(filename), create_file, overwrite)
        self._write_history(f"ADD FILE {filename}")
        self._update_state(ModuleState.MODIFIED, f"Added file: {filename}")

    def add_folder(
        self, foldername: str, recursive: bool = False, init_py: bool = True
    ) -> None:
        """
        Add a folder to the module.

        Parameters
        ----------
        foldername : str
            Name of the folder to create
        recursive : bool, default=False
            If True, create parent directories as needed
        init_py : bool, default=True
            If True, create __init__.py in the folder

        Raises
        ------
        FileExistsError
            If folder already exists

        Examples
        --------
        >>> module.add_folder("submodule")
        >>> module.add_folder("tests", init_py=False)
        """

        def create_folder(p: Path):
            if recursive:
                p.mkdir(parents=True, exist_ok=True)
            else:
                p.mkdir(exist_ok=True)

            if init_py:
                init_file = p / "__init__.py"
                if not init_file.exists():
                    init_file.touch()

        self._create(Path(foldername), create_folder)
        self._write_history(f"ADD FOLDER {foldername}")
        self._update_state(ModuleState.MODIFIED, f"Added folder: {foldername}")

    def to_site(self, editable: bool = False, force: bool = False) -> None:
        """
        Install module to site-packages.

        Parameters
        ----------
        editable : bool, default=False
            If True, create editable install with symlink
        force : bool, default=False
            If True, overwrite existing installation

        Raises
        ------
        RuntimeError
            If site-packages path cannot be determined
        FileExistsError
            If module exists in site-packages and force is False
        OSError
            If installation fails

        Examples
        --------
        >>> module.to_site()
        >>> module.to_site(editable=True)
        """
        if not SITE_PATH:
            raise RuntimeError("Cannot determine site-packages path")

        target = Path(SITE_PATH) / self.name
        original = self.location

        if target.exists() and not force:
            raise FileExistsError(f"Module already exists in site-packages: {target}")

        # Create backup for rollback capability
        backup_path = None
        if target.exists() and force:
            backup_path = target.with_suffix(".backup")
            try:
                shutil.move(str(target), str(backup_path))
            except Exception:
                backup_path = None

        try:
            # Move folder to site-packages
            shutil.move(str(original), str(target))

            if editable:
                try:
                    if original.exists():
                        original.unlink()
                    os.symlink(target, original)
                    self._write_history(f"CREATE SYMLINK FOR {self.name}")
                except OSError as e:
                    # Rollback on symlink failure
                    shutil.move(str(target), str(original))
                    if backup_path and backup_path.exists():
                        shutil.move(str(backup_path), str(target))
                    raise OSError(f"Failed to create symlink at {original}: {e}")

            # Update internal state
            self.location = target
            self.site = target
            self._write_history(f"MOVE {original} TO {target}")
            self._update_state(ModuleState.MOVED, f"To site: {target}")

        except Exception as e:
            # Comprehensive rollback
            if original.exists():
                shutil.move(str(target), str(original))
            if backup_path and backup_path.exists():
                shutil.move(str(backup_path), str(target))
            raise e
        finally:
            # Cleanup backup
            if backup_path and backup_path.exists():
                try:
                    shutil.rmtree(backup_path)
                except Exception:
                    pass

    def build(
        self, errors: bool = True, build_dir: str = "dist", clean: bool = True
    ) -> Union[bool, Exception]:
        """
        Build module distribution packages.

        Parameters
        ----------
        errors : bool, default=True
            If True, raise exceptions on error
        build_dir : str, default="dist"
            Directory for build artifacts
        clean : bool, default=True
            If True, clean build directory before building

        Returns
        -------
        Union[bool, Exception]
            True if successful, Exception if errors=False and build failed

        Raises
        ------
        PackageNotFoundError
            If build module is not installed

        Examples
        --------
        >>> module.build()
        True
        """
        if build is None:
            if errors:
                raise PackageNotFoundError("Module 'build' is not installed")
            return ImportError("Module 'build' is not installed")

        self._write_history(f"BUILD WHEEL FOR {self.name}")

        try:
            builder = build.ProjectBuilder(self.get_location())

            # Clean previous builds if requested
            if clean:
                build_path = Path(build_dir)
                if build_path.exists():
                    shutil.rmtree(build_path)

            # Build both wheel and sdist
            wheel_path = builder.build("wheel", build_dir)
            sdist_path = builder.build("sdist", build_dir)

            self._update_state(ModuleState.BUILT, f"Built: {wheel_path}, {sdist_path}")
            return True

        except Exception as e:
            if errors:
                raise
            return e

    def publish(
        self,
        dist_path: str = "dist/*",
        username: str = "__token__",
        password: str = None,
        test: bool = False,
        skip_build: bool = False,
    ) -> None:
        """
        Publish module to PyPI or TestPyPI.

        Parameters
        ----------
        dist_path : str, default="dist/*"
            Glob pattern for distribution files
        username : str, default="__token__"
            PyPI username or "__token__" for API token
        password : str, optional
            PyPI password or API token
        test : bool, default=False
            If True, publish to TestPyPI instead of PyPI
        skip_build : bool, default=False
            If True, skip building before publishing

        Raises
        ------
        ImportError
            If twine is not installed
        ValueError
            If token authentication is used without password
        FileNotFoundError
            If no distribution files found

        Examples
        --------
        >>> module.publish(username="__token__", password="pypi-token")
        """
        if not skip_build:
            self.build()

        try:
            from twine.settings import Settings
            from twine.commands import upload
        except ImportError:
            raise ImportError(
                "Twine must be installed to use publish(). "
                "Install with: pip install twine"
            ) from None

        from glob import glob

        files = glob(dist_path)
        if not files:
            raise FileNotFoundError(f"No distribution files found at path: {dist_path}")

        if username == "__token__" and not password:
            raise ValueError("API token must be provided when username='__token__'")

        repo_url = (
            "https://test.pypi.org/legacy/"
            if test
            else "https://upload.pypi.org/legacy/"
        )

        settings = Settings(
            repository_url=repo_url, username=username, password=password
        )

        # Validate files before upload
        for file_path in files:
            if not Path(file_path).exists():
                raise FileNotFoundError(f"Distribution file not found: {file_path}")

        # Create upload command and execute
        import sys as _sys
        from io import StringIO

        # Capture output
        old_stdout = _sys.stdout
        _sys.stdout = StringIO()

        try:
            upload.main(args=files)
        finally:
            _sys.stdout = old_stdout

        target = "TEST PYPI" if test else "PYPI"
        self._write_history(f"PUBLISH MODULE {self.name} TO {target}")
        self._update_state(ModuleState.PUBLISHED, f"Published to: {target}")

    def copy_to_site(self, overwrite: bool = False) -> None:
        """
        Copy module to site-packages without moving.

        Parameters
        ----------
        overwrite : bool, default=False
            If True, overwrite existing copy

        Raises
        ------
        RuntimeError
            If site-packages path cannot be determined
        FileExistsError
            If copy exists and overwrite is False

        Examples
        --------
        >>> module.copy_to_site()
        """
        if not SITE_PATH:
            raise RuntimeError("Cannot determine site-packages path")

        target = SITE_PATH / self.name
        if target.exists() and not overwrite:
            raise FileExistsError("Site path exists and cannot be copied")

        if target.exists():
            shutil.rmtree(target)

        shutil.copytree(self.get_location(), target, copy_function=shutil.copy2)
        self._write_history(f"COPY {self.location} TO {target}")
        self._update_state(ModuleState.MODIFIED, f"Copied to site: {target}")

    def remove(self, force: bool = False, backup: bool = True) -> None:
        """
        Remove module with backup and force options.

        Parameters
        ----------
        force : bool, default=False
            If True, skip confirmation
        backup : bool, default=True
            If True, create backup before removal

        Raises
        ------
        FileNotFoundError
            If module not found and force is False

        Examples
        --------
        >>> module.remove()
        >>> module.remove(force=True, backup=False)
        """
        removed_locations = []

        # Create backup if requested
        backup_path = None
        if backup and self.location.exists():
            timestamp = int(time.time())
            backup_path = self.location.with_suffix(f".backup.{timestamp}")
            try:
                shutil.copytree(self.location, backup_path)
            except Exception:
                backup_path = None

        try:
            # Remove from site-packages if present
            if self.site and self.site.exists():
                if force or self._confirm_removal(self.site):
                    shutil.rmtree(self.site)
                    removed_locations.append(("site", self.site))

            # Delete from original location
            if self.location.exists():
                if self.location.is_symlink():
                    self.location.unlink()
                    removed_locations.append(("symlink", self.location))
                elif force or self._confirm_removal(self.location):
                    shutil.rmtree(self.location)
                    removed_locations.append(("original", self.location))

            if not removed_locations and not force:
                raise FileNotFoundError("Module not found in any known location")

            self._update_state(
                ModuleState.REMOVED, f"Removed from: {removed_locations}"
            )

        except Exception as e:
            # Restore from backup if removal failed
            if backup_path and backup_path.exists():
                if self.location.exists():
                    try:
                        shutil.rmtree(self.location)
                    except Exception:
                        pass
                try:
                    shutil.move(backup_path, self.location)
                except Exception:
                    pass
            raise e

    def _confirm_removal(self, path: Path) -> bool:
        """
        Confirm removal of important paths.

        Parameters
        ----------
        path : Path
            Path to confirm removal for

        Returns
        -------
        bool
            True if removal should proceed
        """
        return True

    def call(self, subname: str = None, reload: bool = False) -> Optional[ModuleType]:
        """
        Import module with reload capability and caching.

        Parameters
        ----------
        subname : str, optional
            Submodule to import
        reload : bool, default=False
            If True, force reload of module

        Returns
        -------
        Optional[ModuleType]
            Imported module or None if import fails

        Examples
        --------
        >>> module.call()
        <module 'mymodule' from '...'>
        >>> module.call("submodule", reload=True)
        """
        cache_key = f"import_{self.name}_{subname if subname else ''}"

        if not reload:
            cached_module = self._cache_system.get(cache_key)
            if cached_module is not None:
                return cached_module

        try:
            fullname = self.name if not subname else f"{self.name}.{subname}"

            if reload and fullname in sys.modules:
                module = importlib.reload(sys.modules[fullname])
            else:
                module = importlib.import_module(fullname)

            self._cache_system.set(cache_key, module)
            return module

        except ImportError:
            return None

    def exists(self) -> bool:
        """
        Check if module exists in any known location.

        Returns
        -------
        bool
            True if module exists

        Examples
        --------
        >>> module.exists()
        True
        """
        locations_to_check = [self.location]
        if self.site:
            locations_to_check.append(self.site)

        return any(loc.exists() for loc in locations_to_check)

    def get_location(self) -> Path:
        """
        Get current module location with fallback strategy.

        Returns
        -------
        Path
            Current module location

        Examples
        --------
        >>> module.get_location()
        Path('/path/to/module')
        """
        locations = [self.site, self.location]
        for loc in locations:
            if loc and loc.exists():
                return loc
        return self.location

    def isvalidmodule(self, strict: bool = False) -> bool:
        """
        Validate module structure and integrity.

        Parameters
        ----------
        strict : bool, default=False
            If True, perform additional validation checks

        Returns
        -------
        bool
            True if module is valid

        Examples
        --------
        >>> module.isvalidmodule()
        True
        >>> module.isvalidmodule(strict=True)
        True
        """
        base = self.get_location()
        init_file = base / "__init__.py"

        basic_validation = init_file.exists() and base.is_dir()

        if not strict or not basic_validation:
            return basic_validation

        # Strict validation includes additional checks
        try:
            # Try to import the module
            module = self.call()
            if module is None:
                return False

            # Check for basic module attributes
            required_attrs = {"__name__", "__file__", "__package__"}
            return all(hasattr(module, attr) for attr in required_attrs)

        except Exception:
            return False

    def rename(self, target: str, update_references: bool = True) -> None:
        """
        Rename module and update internal references.

        Parameters
        ----------
        target : str
            New module name
        update_references : bool, default=True
            If True, update internal references

        Raises
        ------
        OSError
            If rename operation fails

        Examples
        --------
        >>> module.rename("new_module_name")
        """
        old_name = self.name
        base = self.get_location()
        new_path = base.parent / Path(target)

        # Update global registry
        self._global_registry.unregister(f"module_{old_name}")

        base.rename(new_path)
        self.name = target
        self.location = new_path

        if SITE_PATH:
            self.site = SITE_PATH / target

        if update_references:
            self._update_module_references(old_name, target)

        self._write_history(f"RENAME {old_name} TO {target}")
        self._global_registry.register(f"module_{self.name}", self)

    def _update_module_references(self, old_name: str, new_name: str) -> None:
        """
        Update internal references after renaming.

        Parameters
        ----------
        old_name : str
            Old module name
        new_name : str
            New module name

        Notes
        -----
        This is a placeholder for actual reference updating logic.
        In a complete implementation, this would update imports,
        metadata, and other references.
        """
        # Placeholder for reference updating logic
        # In production, this could update imports in files,
        # metadata references, etc.
        pass

    def list_content(
        self,
        fullpath: bool = False,
        pattern: str = "*",
        recursive: bool = True,
        include_dirs: bool = True,
        include_files: bool = True,
    ) -> List[str]:
        """
        List module contents with filtering options.

        Parameters
        ----------
        fullpath : bool, default=False
            If True, return full paths instead of names
        pattern : str, default="*"
            Glob pattern to match
        recursive : bool, default=True
            If True, search recursively
        include_dirs : bool, default=True
            If True, include directories in results
        include_files : bool, default=True
            If True, include files in results

        Returns
        -------
        List[str]
            List of matching items

        Examples
        --------
        >>> module.list_content()
        ['__init__.py', 'utils.py', 'tests']
        >>> module.list_content(pattern="*.py", recursive=False)
        ['__init__.py']
        """
        base = self.get_location()
        glob_pattern = "**/" + pattern if recursive else pattern

        items = []
        for item in base.glob(glob_pattern):
            if item == base:  # Skip root directory
                continue

            if (item.is_dir() and not include_dirs) or (
                item.is_file() and not include_files
            ):
                continue

            items.append(str(item) if fullpath else item.name)

        return sorted(items)

    @lru_cache(maxsize=512)
    def search(
        self,
        keyword: str,
        target: str = "*.py",
        case_sensitive: bool = False,
        use_regex: bool = False,
        max_workers: Optional[int] = None,
    ) -> List[str]:
        """
        Search for keyword in module files.

        Parameters
        ----------
        keyword : str
            Text or regex pattern to search for
        target : str, default="*.py"
            Glob pattern for files to search
        case_sensitive : bool, default=False
            If True, perform case-sensitive search
        use_regex : bool, default=False
            If True, treat keyword as regex pattern
        max_workers : int, optional
            Maximum number of worker threads

        Returns
        -------
        List[str]
            List of file paths containing the keyword

        Examples
        --------
        >>> module.search("def hello")
        ['/path/to/module/utils.py']
        >>> module.search("test.*function", use_regex=True)
        []
        """
        results = []
        base = self.get_location()
        files = list(base.rglob(target))

        if not files:
            return []

        def check(file_path: Path) -> Optional[str]:
            try:
                text = file_path.read_text(errors="ignore")

                if use_regex:
                    import re

                    pattern = (
                        re.compile(keyword)
                        if case_sensitive
                        else re.compile(keyword, re.IGNORECASE)
                    )
                    if pattern.search(text):
                        return str(file_path)
                else:
                    if not case_sensitive:
                        text = text.lower()
                        search_keyword = keyword.lower()
                    else:
                        search_keyword = keyword

                    if search_keyword in text:
                        return str(file_path)

            except Exception:
                return None
            return None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(check, f) for f in files]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    results.append(result)

        return sorted(results)

    def profile(self, iterations: int = 1, warmup: int = 0) -> Dict[str, Any]:
        """
        Profile module loading performance.

        Parameters
        ----------
        iterations : int, default=1
            Number of profiling iterations
        warmup : int, default=0
            Number of warmup iterations

        Returns
        -------
        Dict[str, Any]
            Profile results with timing and memory information

        Examples
        --------
        >>> module.profile(iterations=3)
        ProfileModule(load_time_avg=0.1, ...)
        """
        # Warmup runs
        for _ in range(warmup):
            self.call()
            if self.name in sys.modules:
                importlib.reload(sys.modules[self.name])

        load_times = []
        memory_usage = []
        sizes = []

        for _ in range(iterations):
            start_time = time.perf_counter()
            tracemalloc.start()

            mod = self.call()

            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            end_time = time.perf_counter()

            load_times.append(end_time - start_time)
            memory_usage.append(peak)
            sizes.append(sys.getsizeof(mod) if mod else 0)

        mod = self.call()
        funcs = (
            len([attr for attr in dir(mod) if callable(getattr(mod, attr))])
            if mod
            else 0
        )

        return ProfileModule(
            load_time_avg=sum(load_times) / len(load_times),
            load_time_min=min(load_times),
            load_time_max=max(load_times),
            peak_memory_avg=sum(memory_usage) / len(memory_usage),
            peak_memory_max=max(memory_usage),
            size_object_avg=sum(sizes) / len(sizes),
            functions=funcs,
            iterations=iterations,
        )

    @cached_property
    def stats(self) -> ModuleStats:
        """
        Get comprehensive module statistics.

        Returns
        -------
        ModuleStats
            Module statistics

        Examples
        --------
        >>> module.stats
        ModuleStats(name='mymodule', ...)
        """
        base = self.get_location()
        files = list(base.rglob("*"))

        file_list = [f for f in files if f.is_file()]
        dir_list = [d for d in files if d.is_dir()]

        total_size = compute_directory_size(base)

        return ModuleStats(
            name=self.name,
            path=str(base),
            files=len(file_list),
            dirs=len(dir_list),
            size=total_size,
        )

    def add_observer(self, observer: Callable) -> None:
        """
        Add observer for module events.

        Parameters
        ----------
        observer : Callable
            Callback function that takes (event_type, data, module) arguments

        Examples
        --------
        >>> def my_observer(event, data, module):
        ...     print(f"Event: {event}")
        >>> module.add_observer(my_observer)
        """
        self._observers.add(observer)

    def remove_observer(self, observer: Callable) -> None:
        """
        Remove observer from module.

        Parameters
        ----------
        observer : Callable
            Observer to remove
        """
        self._observers.discard(observer)

    def _notify_observers(self, event_type: str, data: Any) -> None:
        """
        Notify all observers of an event.

        Parameters
        ----------
        event_type : str
            Type of event
        data : Any
            Event data
        """
        for observer in list(self._observers):
            try:
                observer(event_type, data, self)
            except Exception:
                # Silently fail on observer errors
                continue

    @classmethod
    def get_registered_modules(cls) -> Dict[str, "MakeModule"]:
        """
        Get all registered MakeModule instances.

        Returns
        -------
        Dict[str, MakeModule]
            Dictionary of registered modules

        Examples
        --------
        >>> MakeModule.get_registered_modules()
        {'module_mymodule': <MakeModule object>, ...}
        """
        return cls._global_registry._registry.copy()

    @classmethod
    def clear_cache(cls) -> None:
        """
        Clear all module caches.

        Examples
        --------
        >>> MakeModule.clear_cache()
        """
        cls._cache_system.clear()
        cls._hasher.clear_cache()

    def __repr__(self) -> str:
        """
        String representation of MakeModule instance.

        Returns
        -------
        str
            Representation string
        """
        return f"MakeModule(name='{self.name}', location='{self.location}')"

    def __str__(self) -> str:
        """
        String description of MakeModule instance.

        Returns
        -------
        str
            Description string
        """
        return f"Module '{self.name}' at {self.location}"

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if exc_type is not None:
            # Log error but don't suppress it
            self._write_history(f"ERROR: {exc_type.__name__}: {exc_val}")
        return False  # Don't suppress exceptions
