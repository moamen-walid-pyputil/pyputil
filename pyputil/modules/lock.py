#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import builtins
import sys
import types
from typing import Iterable, Optional, Dict, Any, Set

_ORIGINAL_IMPORT: Any = None
_ORIGINAL_META_PATH: list = []
_ORIGINAL_MODULES: Dict[str, Any] = {}
_ORIGINAL_PATH_HOOKS: list = []
_ORIGINAL_PATH_IMPORTER_CACHE: Dict[str, Any] = {}
_LOCKED: bool = False
_ALLOWED_IMPORT: Set[str] = set()
_ALLOWED_ACCESS: Set[str] = set()


class _DeadModule(types.ModuleType):
    """
    A dead module that raises RuntimeError on any attribute access.

    Parameters
    ----------
    name : str
        The name of the module (e.g., 'os', 'sys').

    Attributes
    ----------
    __name__ : str
        The name of the dead module.

    Examples
    --------
    >>> dead_os = _DeadModule('os')
    >>> dead_os.path  # Raises RuntimeError
    RuntimeError: Module access is locked. All modules are sealed.
    """

    def __init__(self, name: str):
        """
        Initialize a dead module with the given name.

        Parameters
        ----------
        name : str
            Name of the module to block.
        """
        super().__init__(name)
        self.__name__ = name

    def __getattr__(self, name: str) -> Any:
        """
        Raise RuntimeError when any attribute is accessed.

        Parameters
        ----------
        name : str
            Attribute name being accessed.

        Returns
        -------
        Any
            Never returns, always raises RuntimeError.

        Raises
        ------
        RuntimeError
            Always raised with a descriptive message.
        """
        raise RuntimeError(
            f"Module '{self.__name__}' is locked. Module access is disabled by the security system."
        )

    def __setattr__(self, name: str, value: Any) -> None:
        """
        Prevent attribute assignment.

        Parameters
        ----------
        name : str
            Attribute name to set.
        value : Any
            Value to assign.

        Raises
        ------
        RuntimeError
            Always raised to prevent modification.
        """
        if name == "__name__":
            super().__setattr__(name, value)
        else:
            raise RuntimeError(
                f"Cannot set attributes on locked module '{self.__name__}'"
            )

    def __repr__(self) -> str:
        """
        Return a representation indicating this is a locked module.

        Returns
        -------
        str
            String representation of the dead module.
        """
        return f"<DeadModule '{self.__name__}' (locked)>"


def lock_modules(
    allow_import: Optional[Iterable[str]] = None,
    allow_access: Optional[Iterable[str]] = None,
    strict: bool = True,
) -> None:
    """
    Lock the Python import system and module access.

    Parameters
    ----------
    allow_import : Optional[Iterable[str]], default=None
        List of module names (or package roots) that are allowed
        to be imported after locking. Use '*' to allow all imports
        (only restricts access).

    allow_access : Optional[Iterable[str]], default=None
        List of module names that remain accessible in sys.modules
        after locking. These modules can still be used but new
        imports of them might still be blocked.

    strict : bool, default=True
        If True, raises ImportError/RuntimeError on violations.
        If False, violations return None or empty modules.

    Returns
    -------
    None

    Raises
    ------
    RuntimeError
        If the system is already locked.

    Notes
    -----
    - Module names in allow_import and allow_access should be
      root module names (e.g., 'os', not 'os.path')
    - The lock is global and affects the entire Python runtime
    - Use unlock_modules() to restore the original state

    Examples
    --------
    >>> # Allow only 'math' to be imported and accessed
    >>> lock_modules(allow_import=['math'], allow_access=['math'])
    >>>
    >>> # Allow all imports but restrict access to built-in modules
    >>> lock_modules(allow_import=['*'], allow_access=['myapp'])
    """
    global _LOCKED, _ORIGINAL_IMPORT, _ORIGINAL_META_PATH
    global _ORIGINAL_MODULES, _ALLOWED_IMPORT, _ALLOWED_ACCESS
    global _ORIGINAL_PATH_HOOKS, _ORIGINAL_PATH_IMPORTER_CACHE
    if _LOCKED:
        raise RuntimeError("Module system is already locked")
    _ORIGINAL_IMPORT = builtins.__import__
    _ORIGINAL_META_PATH = sys.meta_path[:]
    _ORIGINAL_PATH_HOOKS = sys.path_hooks[:]
    _ORIGINAL_PATH_IMPORTER_CACHE = sys.path_importer_cache.copy()
    _ORIGINAL_MODULES = sys.modules.copy()
    if allow_import is not None:
        _ALLOWED_IMPORT = set(allow_import)
    else:
        _ALLOWED_IMPORT = set()
    if allow_access is not None:
        _ALLOWED_ACCESS = set(allow_access)
    else:
        _ALLOWED_ACCESS = set()

    def restricted_import(name: str, *args, **kwargs) -> Any:
        """
        Restricted version of __import__ that checks permissions.

        Parameters
        ----------
        name : str
            Module name to import.
        *args : tuple
            Original __import__ arguments.
        **kwargs : dict
            Original __import__ keyword arguments.

        Returns
        -------
        Any
            Imported module if allowed, None or raises error otherwise.

        Raises
        ------
        ImportError
            If import is not allowed and strict=True.
        """
        root = name.split(".", 1)[0]
        if "*" in _ALLOWED_IMPORT or root in _ALLOWED_IMPORT:
            return _ORIGINAL_IMPORT(name, *args, **kwargs)
        if strict:
            raise ImportError(
                f"Import system is locked. Import of '{name}' is not allowed. Allowed imports: {sorted(_ALLOWED_IMPORT)}"
            )
        return None

    builtins.__import__ = restricted_import
    sys.meta_path.clear()
    sys.path_hooks.clear()
    sys.path_importer_cache.clear()
    for name, module in list(sys.modules.items()):
        if module is None:
            continue
        root = name.split(".", 1)[0]
        if root in _ALLOWED_ACCESS or name in _ALLOWED_ACCESS:
            continue
        dead = _DeadModule(name)
        sys.modules[name] = dead
    _LOCKED = True


def unlock_modules() -> None:
    """
    Unlock the module system and restore original state.

    Returns
    -------
    None

    Examples
    --------
    >>> lock_modules()
    >>> # ... restricted operations ...
    >>> unlock_modules()  # Restores everything
    """
    global _LOCKED
    if not _LOCKED:
        return
    if _ORIGINAL_IMPORT is not None:
        builtins.__import__ = _ORIGINAL_IMPORT
    if _ORIGINAL_META_PATH:
        sys.meta_path[:] = _ORIGINAL_META_PATH
    if _ORIGINAL_PATH_HOOKS:
        sys.path_hooks[:] = _ORIGINAL_PATH_HOOKS
    if _ORIGINAL_PATH_IMPORTER_CACHE:
        sys.path_importer_cache.clear()
        sys.path_importer_cache.update(_ORIGINAL_PATH_IMPORTER_CACHE)
    for name, module in _ORIGINAL_MODULES.items():
        if name in sys.modules and isinstance(sys.modules[name], _DeadModule):
            sys.modules[name] = module
    _LOCKED = False
    _ALLOWED_IMPORT.clear()
    _ALLOWED_ACCESS.clear()


def is_locked() -> bool:
    """
    Check if the module system is currently locked.

    Returns
    -------
    bool
        True if the module system is locked, False otherwise.

    Examples
    --------
    >>> lock_modules()
    >>> is_locked()
    True
    >>> unlock_modules()
    >>> is_locked()
    False
    """
    return _LOCKED


_ORIGINAL_IMPORT = builtins.__import__
_ORIGINAL_META_PATH = sys.meta_path[:]
_ORIGINAL_MODULES = sys.modules.copy()
_ORIGINAL_PATH_HOOKS = sys.path_hooks[:]
_ORIGINAL_PATH_IMPORTER_CACHE = sys.path_importer_cache.copy()
