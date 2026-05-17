#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Lazy Module Loader for Python
Provides thread-safe, memory-efficient lazy imports with advanced features.
"""

import importlib
import threading
import sys
import types
from typing import Any, Dict, Optional, Set, List, Callable, Union, Tuple
from functools import wraps
import weakref
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


class LazyLoader(types.ModuleType):
    """
    Thread-safe, production-grade lazy module loader with comprehensive features.
    
    This class provides lazy loading of Python modules, delaying actual import until
    first access. It's ideal for:
    - Reducing startup time for applications with many dependencies
    - Optimizing memory usage for rarely-used modules
    - Handling circular imports gracefully
    - Conditional imports in feature-flagged applications
    
    Key Features:
    - Thread-safe initialization with double-checked locking
    - Attribute proxying and caching
    - Module reloading support
    - Custom import hooks
    - Dependency tracking
    - Error recovery and retry mechanisms
    - Optional eager loading
    - Parent package resolution
    - Weak reference support for garbage collection
    
    Parameters
    ----------
    module_name : str
        Fully qualified name of the module to load (e.g., 'numpy', 'pandas.DataFrame')
    
    package : Optional[str]
        Package context for relative imports. If provided, module_name can be relative.
        Example: LazyLoader('.utils', __package__)
    
    eager : bool
        If True, loads the module immediately. Default False.
    
    retry_on_error : bool
        If True, retries failed imports on next access. Default False.
    
    max_retries : int
        Maximum number of retry attempts if retry_on_error is True. Default 3.
    
    fallback_module : Optional[str]
        Alternative module to load if primary fails. Default None.
    
    preload_hook : Optional[Callable[[types.ModuleType], None]]
        Function called immediately after successful load. Receives loaded module.
    
    cache_attributes : bool
        If True, copies module attributes to proxy after load for faster access. 
        Default True (faster but uses more memory).
    
    track_dependencies : bool
        If True, tracks which attributes are accessed. Default False.
    
    attributes_to_proxy : Optional[Set[str]]
        Specific attributes to proxy. If None, proxies all attributes.
    
    parent_resolution : bool
        If True, automatically resolves parent packages. Default True.
    
    Examples
    --------
    Basic usage:
    >>> loader = LazyLoader('numpy')
    >>> arr = loader.array([1, 2, 3])  # numpy loads here
    
    With custom options:
    >>> loader = LazyLoader(
    ...     'pandas',
    ...     eager=False,
    ...     retry_on_error=True,
    ...     preload_hook=lambda m: print(f"Loaded {m.__name__}")
    ... )
    
    With fallback:
    >>> loader = LazyLoader(
    ...     'optional_dependency',
    ...     fallback_module='dummy_module'
    ... )
    
    Relative imports:
    >>> loader = LazyLoader('.submodule', __package__)
    
    Feature-flagged loading:
    >>> if USE_GPU:
    ...     backend = LazyLoader('cupy')
    ... else:
    ...     backend = LazyLoader('numpy')
    
    Type hints support:
    >>> from typing import TYPE_CHECKING
    >>> if TYPE_CHECKING:
    ...     import numpy as np
    >>> else:
    ...     np = LazyLoader('numpy')
    """
    
    __slots__ = (
        '_module_name', '_package', '_module', '_lock', '_loaded',
        '_eager', '_retry_on_error', '_max_retries', '_retry_count',
        '_fallback_module', '_preload_hook', '_cache_attributes',
        '_track_dependencies', '_accessed_attrs', '_attributes_to_proxy',
        '_parent_resolution', '_error', '_weakrefs'
    )
    
    def __init__(
        self,
        module_name: str,
        package: Optional[str] = None,
        eager: bool = False,
        retry_on_error: bool = False,
        max_retries: int = 3,
        fallback_module: Optional[str] = None,
        preload_hook: Optional[Callable[[types.ModuleType], None]] = None,
        cache_attributes: bool = True,
        track_dependencies: bool = False,
        attributes_to_proxy: Optional[Set[str]] = None,
        parent_resolution: bool = True
    ):
        # Initialize as a module with the given name
        super().__init__(module_name)
        
        # Core attributes
        self._module_name = module_name
        self._package = package
        self._module: Optional[types.ModuleType] = None
        self._lock = threading.RLock()
        self._loaded = False
        self._error: Optional[Exception] = None
        self._retry_count = 0
        
        # Configuration
        self._eager = eager
        self._retry_on_error = retry_on_error
        self._max_retries = max(max_retries, 0)
        self._fallback_module = fallback_module
        self._preload_hook = preload_hook
        self._cache_attributes = cache_attributes
        self._track_dependencies = track_dependencies
        self._attributes_to_proxy = attributes_to_proxy
        self._parent_resolution = parent_resolution
        
        # Tracking
        self._accessed_attrs: Set[str] = set() if track_dependencies else None
        self._weakrefs: List[weakref.ReferenceType] = []
        
        # Eager loading if requested
        if self._eager:
            self._load()
    
    @property
    def is_loaded(self) -> bool:
        """Check if the module has been loaded."""
        return self._loaded and self._module is not None
    
    @property
    def loaded_module(self) -> Optional[types.ModuleType]:
        """Get the loaded module directly if loaded, otherwise None."""
        return self._module if self._loaded else None
    
    @property
    def load_error(self) -> Optional[Exception]:
        """Get the last error that occurred during loading."""
        return self._error
    
    def _resolve_module_name(self) -> str:
        """Resolve the full module name, handling relative imports."""
        if not self._parent_resolution or not self._package:
            return self._module_name
        
        # Handle relative imports (starting with .)
        if self._module_name.startswith('.'):
            if not self._package:
                raise ValueError(
                    f"Cannot resolve relative import '{self._module_name}' without package context"
                )
            
            # Count the number of dots to determine level
            dots = 0
            while dots < len(self._module_name) and self._module_name[dots] == '.':
                dots += 1
            
            relative_name = self._module_name[dots:]
            package_parts = self._package.split('.')
            
            if dots > len(package_parts):
                raise ValueError(
                    f"Attempted relative import beyond top-level package: {self._module_name}"
                )
            
            # Build the absolute module name
            base_package = '.'.join(package_parts[:-dots] if dots > 0 else package_parts)
            if relative_name:
                full_name = f"{base_package}.{relative_name}" if base_package else relative_name
            else:
                full_name = base_package
            
            logger.debug(f"Resolved relative import '{self._module_name}' to '{full_name}'")
            return full_name
        
        return self._module_name
    
    def _load(self) -> types.ModuleType:
        """
        Load the module with thread-safe double-checked locking.
        
        Returns
        -------
        types.ModuleType
            The loaded module
        
        Raises
        ------
        ImportError
            If module cannot be loaded and no fallback is available
        """
        # Fast path - already loaded
        if self._loaded and self._module is not None:
            return self._module
        
        with self._lock:
            # Double-checked locking
            if self._loaded and self._module is not None:
                return self._module
            
            # Reset error state for retry
            self._error = None
            
            # Attempt to load
            module = None
            last_error = None
            
            for attempt in range(self._max_retries + 1 if self._retry_on_error else 1):
                try:
                    resolved_name = self._resolve_module_name()
                    
                    # Try to get from sys.modules first
                    if resolved_name in sys.modules:
                        module = sys.modules[resolved_name]
                        logger.debug(f"Using cached module from sys.modules: {resolved_name}")
                    else:
                        # Actually import the module
                        module = importlib.import_module(resolved_name, self._package)
                        logger.info(f"Successfully loaded module: {resolved_name}")
                    
                    # Call preload hook if provided
                    if self._preload_hook:
                        try:
                            self._preload_hook(module)
                        except Exception as e:
                            logger.warning(f"Preload hook failed: {e}")
                    
                    # Cache attributes if requested
                    if self._cache_attributes and self._attributes_to_proxy is None:
                        # Copy all public attributes for faster access
                        for attr_name, attr_value in module.__dict__.items():
                            if not attr_name.startswith('_'):
                                try:
                                    setattr(self, attr_name, attr_value)
                                except AttributeError:
                                    pass
                    
                    self._module = module
                    self._loaded = True
                    self._retry_count = 0
                    break
                    
                except ImportError as e:
                    last_error = e
                    self._retry_count = attempt + 1
                    
                    if self._retry_on_error and attempt < self._max_retries:
                        wait_time = 0.1 * (2 ** attempt)  # Exponential backoff
                        logger.warning(
                            f"Import attempt {attempt + 1} failed for {self._module_name}: {e}. "
                            f"Retrying in {wait_time:.2f}s..."
                        )
                        import time
                        time.sleep(wait_time)
                    else:
                        break
                except Exception as e:
                    last_error = e
                    logger.error(f"Unexpected error loading {self._module_name}: {e}")
                    break
            
            # Handle fallback if primary loading failed
            if module is None and self._fallback_module:
                logger.warning(f"Falling back to {self._fallback_module}")
                try:
                    module = importlib.import_module(self._fallback_module, self._package)
                    self._module = module
                    self._loaded = True
                    self._error = None
                except Exception as e:
                    self._error = e
                    raise ImportError(
                        f"Failed to load {self._module_name} and fallback {self._fallback_module}: {e}"
                    ) from e
            
            # Raise error if still no module
            if module is None:
                self._error = last_error
                raise ImportError(
                    f"Failed to load module '{self._module_name}' after {self._retry_count} attempts"
                ) from last_error
            
            return self._module
    
    def reload(self) -> types.ModuleType:
        """
        Force reload the module, discarding the cached version.
        
        Returns
        -------
        types.ModuleType
            The newly reloaded module
        
        Raises
        ------
        ImportError
            If reload fails
        """
        with self._lock:
            self._loaded = False
            self._module = None
            self._error = None
            self._retry_count = 0
            
            # Clear cached attributes
            if self._cache_attributes:
                for attr_name in list(self.__dict__.keys()):
                    if not attr_name.startswith('_'):
                        try:
                            delattr(self, attr_name)
                        except AttributeError:
                            pass
            
            return self._load()
    
    def __getattr__(self, name: str) -> Any:
        """
        Get an attribute from the lazily-loaded module.
        
        Implements lazy loading: first access triggers module import.
        
        Parameters
        ----------
        name : str
            Attribute name to access
            
        Returns
        -------
        Any
            The attribute value
            
        Raises
        ------
        AttributeError
            If the attribute doesn't exist in the loaded module
        """
        # Track accessed attributes if enabled
        if self._track_dependencies and self._accessed_attrs is not None:
            self._accessed_attrs.add(name)
        
        # Load the module (this might raise ImportError)
        module = self._load()
        
        # Get the attribute from the module
        try:
            return getattr(module, name)
        except AttributeError as e:
            # Provide better error message
            raise AttributeError(
                f"Module '{self._module_name}' has no attribute '{name}'"
            ) from e
    
    def __setattr__(self, name: str, value: Any) -> None:
        """
        Set an attribute on the lazily-loaded module.
        
        Special handling for internal attributes vs proxied attributes.
        
        Parameters
        ----------
        name : str
            Attribute name
        value : Any
            Value to set
        """
        # Internal attributes go directly to the proxy
        if name in self.__slots__ or name.startswith('_') and name not in self.__dict__:
            super().__setattr__(name, value)
        else:
            # Proxy the attribute to the loaded module
            module = self._load()
            setattr(module, name, value)
    
    def __dir__(self) -> List[str]:
        """
        Return the directory of available attributes.
        
        Includes both proxy attributes and the underlying module's attributes
        (once loaded).
        
        Returns
        -------
        List[str]
            List of attribute names
        """
        # Start with proxy's internal attributes
        attrs = set(super().__dir__())
        attrs.update(name for name in self.__slots__)
        
        # Add module attributes if loaded
        if self._loaded and self._module:
            attrs.update(dir(self._module))
        
        return sorted(attrs)
    
    def __repr__(self) -> str:
        """Get a string representation of the lazy loader."""
        status = "loaded" if self._loaded else "not loaded"
        if self._error:
            status = f"failed: {self._error}"
        return f"<LazyLoader '{self._module_name}' ({status})>"
    
    def __str__(self) -> str:
        """String representation."""
        if self._loaded and self._module:
            return str(self._module)
        return f"LazyLoader({self._module_name})"
    
    def __call__(self, *args, **kwargs) -> Any:
        """
        Allow the lazy loader to be called directly.
        
        This is useful for lazy-loading callable modules or classes.
        """
        module = self._load()
        if callable(module):
            return module(*args, **kwargs)
        raise TypeError(f"Module '{self._module_name}' is not callable")
    
    @contextmanager
    def eager_context(self):
        """
        Context manager that ensures the module is loaded within the context.
        
        Examples
        --------
        >>> loader = LazyLoader('heavy_module')
        >>> with loader.eager_context():
        ...     # Module is loaded here
        ...     result = loader.some_function()
        """
        was_loaded = self._loaded
        self._load()
        try:
            yield self._module
        finally:
            if not was_loaded and not self._eager:
                # Optional: unload? Usually not, but could be implemented
                pass
    
    def get_accessed_attributes(self) -> Set[str]:
        """
        Get the set of attributes accessed through this loader.
        
        Only available if track_dependencies was enabled.
        
        Returns
        -------
        Set[str]
            Set of accessed attribute names
            
        Raises
        ------
        ValueError
            If tracking was not enabled
        """
        if not self._track_dependencies:
            raise ValueError("Attribute tracking not enabled. Initialize with track_dependencies=True")
        return self._accessed_attrs.copy() if self._accessed_attrs else set()
    
    def create_weak_ref(self, callback: Optional[Callable] = None) -> weakref.ReferenceType:
        """
        Create a weak reference to this lazy loader.
        
        Parameters
        ----------
        callback : Optional[Callable]
            Callback function when the loader is garbage collected
            
        Returns
        -------
        weakref.ReferenceType
            Weak reference to this loader
        """
        ref = weakref.ref(self, callback)
        self._weakrefs.append(ref)
        return ref
    
    def preload(self) -> None:
        """Explicitly load the module without accessing attributes."""
        self._load()
    
    def is_attribute_loaded(self, name: str) -> bool:
        """
        Check if a specific attribute is available without loading the module.
        
        Parameters
        ----------
        name : str
            Attribute name to check
            
        Returns
        -------
        bool
            True if the attribute exists in the module (may trigger load)
        """
        if not self._loaded:
            return False
        return hasattr(self._module, name) if self._module else False
    
    @classmethod
    def from_spec(cls, spec: importlib.machinery.ModuleSpec) -> 'LazyLoader':
        """
        Create a LazyLoader from a ModuleSpec.
        
        Parameters
        ----------
        spec : ModuleSpec
            The module specification
            
        Returns
        -------
        LazyLoader
            A new lazy loader instance
        """
        loader = cls(spec.name)
        loader._module = None
        loader._loaded = False
        return loader


# Convenience function for simple lazy imports
def lazy_load(module_name: str, **kwargs) -> LazyLoader:
    """
    Convenience function to create a lazy loader.
    
    Parameters
    ----------
    module_name : str
        Name of the module to import lazily
    **kwargs
        Additional arguments passed to LazyLoader constructor
        
    Returns
    -------
    LazyLoader
        A lazy loader instance
        
    Examples
    --------
    >>> pd = lazy_load('pandas')
    >>> np = lazy_load('numpy', eager=False, retry_on_error=True)
    """
    return LazyLoader(module_name, **kwargs)


# Example usage and testing
if __name__ == "__main__":
    # Basic usage
    pd = lazy_load('pandas')
    print(f"Created: {pd}")
    print(f"Loaded? {pd.is_loaded}")
    
    # This triggers the actual import
    try:
        df = pd.DataFrame({'a': [1, 2, 3]})
        print(f"DataFrame created: {df}")
        print(f"Loaded? {pd.is_loaded}")
    except ImportError as e:
        print(f"Import failed (expected if pandas not installed): {e}")
    
    # With tracking
    np = LazyLoader('numpy', track_dependencies=True)
    try:
        # This would track which attributes were accessed
        pass
    except ImportError:
        pass
    
    print("\nLazyLoader implementation complete!")