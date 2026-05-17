#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Core type definitions and base classes for the import system.
"""

import types
from typing import Any, Dict, Optional, Union
import importlib.util


class LazyModule(types.ModuleType):
    """
    A module proxy that loads the actual module only when accessed.
    
    This class implements lazy loading by deferring module execution
    until an attribute is first accessed. Useful for reducing startup time
    in large applications.
    
    Attributes
    ----------
    _spec : importlib.machinery.ModuleSpec
        The module specification for lazy loading.
    _module : types.ModuleType | None
        The actual loaded module (None until first access).
    """
    
    def __init__(self, spec: importlib.machinery.ModuleSpec):
        """
        Initialize a lazy module proxy.
        
        Parameters
        ----------
        spec : importlib.machinery.ModuleSpec
            The module specification for lazy loading.
        """
        super().__init__(spec.name)
        self._spec = spec
        self._module = None
    
    def _load(self) -> None:
        """Load the actual module if not already loaded."""
        if self._module is None:
            self._module = importlib.util.module_from_spec(self._spec)
            self._spec.loader.exec_module(self._module)
    
    def __getattr__(self, name: str) -> Any:
        """
        Get attribute from the module, loading it first if necessary.
        
        Parameters
        ----------
        name : str
            Attribute name to access.
        
        Returns
        -------
        Any
            The attribute value from the loaded module.
        """
        self._load()
        return getattr(self._module, name)
    
    def __setattr__(self, name: str, value: Any) -> None:
        """
        Set attribute, loading module if necessary.
        
        Parameters
        ----------
        name : str
            Attribute name to set.
        value : Any
            Value to set.
        """
        if name in ('_spec', '_module'):
            super().__setattr__(name, value)
        else:
            self._load()
            setattr(self._module, name, value)


class LazyAttributeProxy:
    """
    Proxy for lazy loading of specific module attributes.
    
    Similar to LazyModule but for specific attributes within a module.
    Useful when only certain attributes are needed.
    
    Attributes
    ----------
    _module : types.ModuleType
        The module containing the attribute.
    _attr_name : str
        Name of the attribute to load lazily.
    _loaded_value : Any | None
        Cached loaded attribute value.
    """
    
    def __init__(self, module: types.ModuleType, attr_name: str):
        """
        Initialize lazy attribute proxy.
        
        Parameters
        ----------
        module : types.ModuleType
            The module containing the attribute.
        attr_name : str
            Name of the attribute to load lazily.
        """
        self._module = module
        self._attr_name = attr_name
        self._loaded_value = None
    
    def __call__(self, *args, **kwargs) -> Any:
        """
        Call the attribute if it's callable, loading it first.
        
        Returns
        -------
        Any
            Result of calling the attribute.
        """
        return self.get()(*args, **kwargs)
    
    def get(self) -> Any:
        """
        Get the actual attribute value, loading if necessary.
        
        Returns
        -------
        Any
            The attribute value.
        """
        if self._loaded_value is None:
            self._loaded_value = getattr(self._module, self._attr_name)
        return self._loaded_value


class ValidationError(Exception):
    """Raised when module validation fails."""
    pass


class ImportConfig:
    """
    Configuration container for import operations.
    
    This class holds all configuration parameters for a single import operation,
    making it easier to pass them between functions.
    """
    
    def __init__(
        self,
        target: str,
        attr: Optional[str] = None,
        auto_install: bool = False,
        version: Optional[str] = None,
        cache: bool = True,
        lazy: bool = False,
        reload: bool = False,
        default: Any = None,
        install_name: Optional[str] = None,
        package: Optional[str] = None,
        search_paths: Optional[list] = None,
        file_mode: bool = False,
        validate: bool = False,
        silent: bool = False,
        return_spec: bool = False,
        inject_globals: Optional[Dict] = None,
        strict_attr: bool = False,
        async_import: bool = False,
    ):
        self.target = target
        self.attr = attr
        self.auto_install = auto_install
        self.version = version
        self.cache = cache
        self.lazy = lazy
        self.reload = reload
        self.default = default
        self.install_name = install_name
        self.package = package
        self.search_paths = search_paths
        self.file_mode = file_mode
        self.validate = validate
        self.silent = silent
        self.return_spec = return_spec
        self.inject_globals = inject_globals
        self.strict_attr = strict_attr
        self.async_import = async_import