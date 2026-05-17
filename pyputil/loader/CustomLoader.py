#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Custom Module Loader System for Python.

This module provides an extensible system for custom module loaders,
allowing dynamic control over the import process with support for
hooks, module transformation, and custom module creation.
"""

import sys
import importlib.abc
import importlib.util
import importlib.machinery
from types import ModuleType
from typing import Callable, Optional, List, Dict, Any, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum
import inspect
import marshal
import types


class CustomLoaderPriority(Enum):
    """Priority levels for custom finders."""

    HIGHEST = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    LOWEST = 4


class CustomModuleHook(Enum):
    """Hook points for module lifecycle."""

    PRE_CREATE = "pre_create"
    POST_CREATE = "post_create"
    PRE_EXEC = "pre_exec"
    POST_EXEC = "post_exec"
    PRE_LOAD = "pre_load"
    POST_LOAD = "post_load"


@dataclass
class CustomLoaderConfig:
    """
    Configuration for custom loaders.

    Attributes
    ----------
    module_type : str
            The module name prefix to match
    handler : Callable
            Main handler function for module loading
    priority : CustomLoaderPriority
            Priority level for this loader
    enabled : bool
            Whether this loader is active
    metadata : Dict[str, Any]
            Additional metadata for the loader
    hooks : Dict[CustomModuleHook, List[Callable]]
            Lifecycle hooks for module handling
    create_module_func : Optional[Callable]
            Custom module creation function
    module_code : Optional[str]
            Custom module source code
    """

    module_type: str
    handler: Callable[[ModuleType, str], None]
    priority: CustomLoaderPriority = CustomLoaderPriority.NORMAL
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    hooks: Dict[CustomModuleHook, List[Callable]] = field(default_factory=dict)
    create_module_func: Optional[Callable[[str], ModuleType]] = None
    module_code: Optional[str] = None


class CustomLoader(importlib.abc.Loader):
    """
    Custom loader that creates and executes modules.

    This loader takes complete control over module creation and execution,
    allowing for dynamic module generation and transformation.

    Parameters
    ----------
    config : CustomLoaderConfig
            Configuration for this loader instance
    """

    def __init__(self, config: CustomLoaderConfig):
        self.config = config
        self._module_cache: Dict[str, ModuleType] = {}

    def _run_hooks(
        self, hook_type: CustomModuleHook, module: ModuleType, module_name: str
    ) -> None:
        """Run all hooks of a specific type."""
        if hook_type in self.config.hooks:
            for hook in self.config.hooks[hook_type]:
                hook(module, module_name, self.config)

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        """
        Create the module.

        Parameters
        ----------
        spec : importlib.machinery.ModuleSpec
                The module specification

        Returns
        -------
        ModuleType
                The newly created module
        """
        module_name = spec.name

        # Check cache first
        if module_name in self._module_cache:
            return self._module_cache[module_name]

        # Run pre-create hooks
        dummy_module = ModuleType(module_name)
        self._run_hooks(CustomModuleHook.PRE_CREATE, dummy_module, module_name)

        # Create module using custom function if provided
        if self.config.create_module_func:
            module = self.config.create_module_func(module_name)
        else:
            # Create a new module with proper attributes
            module = ModuleType(module_name)
            module.__file__ = f"<custom-{self.config.module_type}>"
            module.__package__ = module_name.rpartition(".")[0] or None
            module.__loader__ = self
            module.__spec__ = spec

        # Run post-create hooks
        self._run_hooks(CustomModuleHook.POST_CREATE, module, module_name)

        # Cache the module
        self._module_cache[module_name] = module

        return module

    def exec_module(self, module: ModuleType) -> None:
        """
        Execute the module with full control.

        This method can inject custom code, modify the module's dict,
        or execute custom handlers.

        Parameters
        ----------
        module : ModuleType
                The module to execute
        """
        module_name = module.__name__

        if not self.config.enabled:
            return

        # Run pre-exec hooks
        self._run_hooks(CustomModuleHook.PRE_EXEC, module, module_name)

        # If custom code is provided, execute it
        if self.config.module_code:
            # Create a new namespace from the module's dict
            namespace = module.__dict__

            # Add __name__ and __file__ if not present
            if "__name__" not in namespace:
                namespace["__name__"] = module_name
            if "__file__" not in namespace:
                namespace["__file__"] = f"<custom-{module_name}>"

            # Execute the code in the module's namespace
            try:
                compiled_code = compile(
                    self.config.module_code, f"<string:{module_name}>", "exec"
                )
                exec(compiled_code, namespace)
            except Exception as e:
                raise ImportError(
                    f"Failed to execute custom code for {module_name}: {e}"
                )

        # Run the main handler
        try:
            self.config.handler(module, self.config.module_type)
        except Exception as e:
            raise ImportError(f"Handler failed for {module_name}: {e}")

        # Run post-exec hooks
        self._run_hooks(CustomModuleHook.POST_EXEC, module, module_name)


class CustomFinder(importlib.abc.MetaPathFinder):
    """
    Meta path finder for custom module loading with priority support.

    Parameters
    ----------
    config : CustomLoaderConfig
            Configuration for this finder instance
    """

    def __init__(self, config: CustomLoaderConfig):
        self.config = config
        self.priority = config.priority

    def find_spec(
        self,
        fullname: str,
        path: Optional[List[str]],
        target: Optional[ModuleType] = None,
    ) -> Optional[importlib.machinery.ModuleSpec]:
        """
        Find the module specification for the given fullname.

        Parameters
        ----------
        fullname : str
                Fully qualified module name
        path : Optional[List[str]]
                Submodule search path (if any)
        target : Optional[ModuleType]
                Existing module to reload (if any)

        Returns
        -------
        Optional[importlib.machinery.ModuleSpec]
                Module specification if module matches, None otherwise
        """
        if not self.config.enabled:
            return None

        if fullname.startswith(self.config.module_type):
            loader = CustomLoader(self.config)
            spec = importlib.machinery.ModuleSpec(fullname, loader)

            # Set additional spec attributes
            spec.is_package = self._is_package(fullname)
            spec.origin = f"custom:{self.config.module_type}"
            spec.has_location = False
            spec.cached = None
            spec.loader_state = self.config.metadata

            return spec

        return None

    def _is_package(self, fullname: str) -> bool:
        """Determine if the module is a package."""
        # Check if there are no more dots after the module type
        remainder = fullname[len(self.config.module_type) :]
        return "." not in remainder


class AddCustomLoader:
    """
    Loader for custom module loaders with priority-based ordering.

    Parameters
    ----------
    auto_register : bool, default=True
            Whether to automatically register finders in sys.meta_path

    Examples
    --------
    >>> loader = AddCustomLoader()
    >>>
    >>> def version_handler(module, prefix):
    ...     module.__version__ = "2.0.0"
    >>>
    >>> loader.add_custom_loader("app.", version_handler, priority=CustomLoaderPriority.HIGH)
    >>>
    >>> # Add a loader with custom module creation
    >>> def custom_creator(module_name):
    ...     module = ModuleType(module_name)
    ...     module.custom_attr = "created by custom function"
    ...     return module
    >>>
    >>> loader.add_custom_loader(
    ...     "dynamic.",
    ...     lambda m, p: setattr(m, 'loaded', True),
    ...     create_module_func=custom_creator
    ... )
    >>>
    >>> # Add a loader with hooks
    >>> def pre_exec_hook(module, name, config):
    ...     module._pre_executed = True
    >>>
    >>> loader.add_custom_loader(
    ...     "hooked.",
    ...     lambda m, p: None,
    ...     hooks={CustomModuleHook.PRE_EXEC: [pre_exec_hook]}
    ... )
    """

    def __init__(self, auto_register: bool = True):
        self._configs: List[CustomLoaderConfig] = []
        self._finders: List[CustomFinder] = []
        self.auto_register = auto_register

    def add_custom_loader(
        self,
        module_type: str,
        handler: Callable[[ModuleType, str], None],
        priority: Union[CustomLoaderPriority, int] = CustomLoaderPriority.NORMAL,
        enabled: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
        hooks: Optional[Dict[CustomModuleHook, List[Callable]]] = None,
        create_module_func: Optional[Callable[[str], ModuleType]] = None,
        module_code: Optional[str] = None,
    ) -> "AddCustomLoader":
        """
        Add a new custom loader.

        Parameters
        ----------
        module_type : str
                Module name prefix to match
        handler : Callable[[ModuleType, str], None]
                Function to execute when module is loaded
        priority : Union[CustomLoaderPriority, int], default=CustomLoaderPriority.NORMAL
                Priority level for this loader
        enabled : bool, default=True
                Whether this loader is initially enabled
        metadata : Optional[Dict[str, Any]]
                Additional metadata for this loader
        hooks : Optional[Dict[CustomModuleHook, List[Callable]]]
                Lifecycle hooks for module handling
        create_module_func : Optional[Callable[[str], ModuleType]]
                Custom function to create modules
        module_code : Optional[str]
                Custom source code for the module

        Returns
        -------
        AddCustomLoader
                Self for method chaining
        """
        # Convert int priority to enum if needed
        if isinstance(priority, int):
            try:
                priority = CustomLoaderPriority(priority)
            except ValueError:
                priority = CustomLoaderPriority.NORMAL

        config = CustomLoaderConfig(
            module_type=module_type,
            handler=handler,
            priority=priority,
            enabled=enabled,
            metadata=metadata or {},
            hooks=hooks or {},
            create_module_func=create_module_func,
            module_code=module_code,
        )

        self._configs.append(config)
        self._reorder_finders()

        if self.auto_register:
            self.register()

        return self

    def _reorder_finders(self) -> None:
        """Reorder finders based on priority."""
        # Sort configs by priority (lower number = higher priority)
        self._configs.sort(key=lambda c: c.priority.value)

        # Recreate finders in priority order
        self._finders = [CustomFinder(config) for config in self._configs]

    def remove_loader(self, module_type: str) -> bool:
        """
        Remove a loader by module type.

        Parameters
        ----------
        module_type : str
                Module type prefix to remove

        Returns
        -------
        bool
                True if loader was found and removed, False otherwise
        """
        initial_count = len(self._configs)
        self._configs = [c for c in self._configs if c.module_type != module_type]

        if len(self._configs) != initial_count:
            self._reorder_finders()
            if self.auto_register:
                self.register()
            return True

        return False

    def enable_loader(self, module_type: str, enabled: bool = True) -> bool:
        """
        Enable or disable a loader.

        Parameters
        ----------
        module_type : str
                Module type prefix to modify
        enabled : bool, default=True
                New enabled state

        Returns
        -------
        bool
                True if loader was found and modified, False otherwise
        """
        for config in self._configs:
            if config.module_type == module_type:
                config.enabled = enabled
                if self.auto_register:
                    self.register()
                return True
        return False

    def register(self) -> None:
        """Register finders in sys.meta_path."""
        # Remove any existing finders from this loader
        self.unregister()

        # Insert finders at the beginning of meta_path in priority order
        for finder in reversed(self._finders):
            sys.meta_path.insert(0, finder)

    def unregister(self) -> None:
        """Remove all finders from this loader from sys.meta_path."""
        sys.meta_path = [f for f in sys.meta_path if f not in self._finders]

    def clear(self) -> None:
        """Remove all loaders and unregister from sys.meta_path."""
        self.unregister()
        self._configs.clear()
        self._finders.clear()


# Global instance
default_loader = AddCustomLoader()


def add_custom_loader(
    module_type: str,
    handler: Callable[[ModuleType, str], None],
    priority: Union[CustomLoaderPriority, int] = CustomLoaderPriority.NORMAL,
    enabled: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
    hooks: Optional[Dict[CustomModuleHook, List[Callable]]] = None,
    create_module_func: Optional[Callable[[str], ModuleType]] = None,
    module_code: Optional[str] = None,
) -> None:
    """
    Add a custom loader using the default loader.

    Parameters
    ----------
    module_type : str
            Module name prefix to match
    handler : Callable[[ModuleType, str], None]
            Function to execute when module is loaded
    priority : Union[CustomLoaderPriority, int], default=CustomLoaderPriority.NORMAL
            Priority level for this loader
    enabled : bool, default=True
            Whether this loader is initially enabled
    metadata : Optional[Dict[str, Any]]
            Additional metadata for this loader
    hooks : Optional[Dict[CustomModuleHook, List[Callable]]]
            Lifecycle hooks for module handling
    create_module_func : Optional[Callable[[str], ModuleType]]
            Custom function to create modules
    module_code : Optional[str]
            Custom source code for the module

    Examples
    --------
    >>> # Simple loader
    >>> add_custom_loader("myapp.", lambda m, p: setattr(m, 'x', 42))
    >>>
    >>> # Loader with custom module creation
    >>> def creator(name):
    ...     mod = ModuleType(name)
    ...     mod.initialized = True
    ...     return mod
    >>>
    >>> add_custom_loader("dynamic.", lambda m, p: None, create_module_func=creator)
    >>>
    >>> # Loader with hooks
    >>> def pre_hook(m, n, c):
    ...     m._pre = True
    >>>
    >>> add_custom_loader("hooked.", lambda m, p: m.run(),
    ...            hooks={CustomModuleHook.PRE_EXEC: [pre_hook]})
    >>>
    >>> # Loader with custom code
    >>> code = '''
    ... def hello():
    ...     return "Hello from custom module!"
    ... '''
    >>> add_custom_loader("code.", lambda m, p: None, module_code=code)
    """
    default_loader.add_custom_loader(
        module_type=module_type,
        handler=handler,
        priority=priority,
        enabled=enabled,
        metadata=metadata,
        hooks=hooks,
        create_module_func=create_module_func,
        module_code=module_code,
    )
