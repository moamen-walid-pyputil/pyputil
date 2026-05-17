#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Module protection and feature management.

Provides methods to disable, freeze, and protect module attributes.
"""

from typing import Dict, Optional, Any, List


class ProtectionManager:
    """
    Manager for module protection and feature management.

    This class handles feature disabling, freezing, and read-only protection
    of modules and their attributes.
    """

    def __init__(self, module, module_name):
        """
        Initialize ProtectionManager.

        Parameters
        ----------
        module : ModuleType
            The target module
        module_name : str
            Name of the module
        """
        self.module = module
        self.name = module_name

    def disable_feature(
        self, name: str, behavior: str = "raise", message: str = None
    ) -> dict:
        """
        Disable a feature (function or class) in the module.

        Parameters
        ----------
        name : str
            Attribute name to disable (must exist in module)
        behavior : str, optional
            Disable behavior mode. Options:
            - "raise": Disabled callable raises RuntimeError (default)
            - "noop": Disabled callable returns None
            - "stub": Replace class with stub that raises on instantiation
        message : str, optional
            Custom error message for raise behavior

        Returns
        -------
        dict
            Disable operation summary with keys:
            - "disabled": Name of disabled feature
            - "original_type": Type of disabled feature ("function", "class", or "other")

        Raises
        ------
        AttributeError
            If specified feature doesn't exist in module

        Side Effects
        ------------
        - Creates/updates module.__disable_backup__ to store original values

        Examples
        --------
        >>> pme = pmeX("math")
        >>> result = pme.disable_feature("sqrt")
        >>> print(result)
        {'disabled': 'sqrt', 'original_type': 'function'}
        """
        module = self.module
        if not hasattr(module, name):
            raise AttributeError(f"Module '{self.name}' has no attribute '{name}'")

        orig = getattr(module, name)
        # ensure backup dict exists
        if not hasattr(module, "__disable_backup__"):
            module.__disable_backup__ = {}

        # don't overwrite existing backup for same name
        if name not in module.__disable_backup__:
            module.__disable_backup__[name] = orig

        msg = message or f"Feature '{name}' is disabled."

        # function-like
        if callable(orig) and not isinstance(orig, type):
            if behavior == "noop":

                def _noop(*args, **kwargs):
                    """Disabled function stub that returns None"""
                    return None

                setattr(module, name, _noop)
            else:  # default raise

                def _raise(*args, **kwargs):
                    """Disabled function stub that raises RuntimeError"""
                    raise RuntimeError(msg)

                setattr(module, name, _raise)
            return {"disabled": name, "original_type": "function"}

        # class
        if isinstance(orig, type):
            if behavior == "noop":
                # stub class that constructs but does nothing
                class _NoopClass:
                    """Disabled class stub that does nothing"""

                    def __init__(self, *a, **k):
                        return None

                setattr(module, name, _NoopClass)
            else:
                # stub class that raises on instantiation or attribute access
                class _DisabledClass:
                    """Disabled class stub that raises RuntimeError"""

                    def __init__(self, *a, **k):
                        raise RuntimeError(msg)

                    def __getattribute__(self, item):
                        raise RuntimeError(msg)

                setattr(module, name, _DisabledClass)
            return {"disabled": name, "original_type": "class"}

        # other objects (constants, modules, etc.) -> replace with None but keep backup
        setattr(module, name, None)
        return {"disabled": name, "original_type": "other"}

    def revert_feature(self, name: str = None, restore_all: bool = False) -> dict:
        """
        Revert disabled features previously disabled by disable_feature.

        Parameters
        ----------
        name : str, optional
            Specific attribute to restore
        restore_all : bool, optional
            Whether to restore all disabled features

        Returns
        -------
        dict
            Restore operation summary with keys:
            - "restored": List of successfully restored attributes
            - "missing": List of attributes not found in backup

        Examples
        --------
        >>> pme = pmeX("math")
        >>> pme.disable_feature("sqrt")
        >>> result = pme.revert_feature("sqrt")
        >>> print(result)
        {'restored': ['sqrt'], 'missing': []}
        """
        module = self.module
        if not hasattr(module, "__disable_backup__"):
            return {"restored": [], "missing": []}

        restored = []
        missing = []

        def _restore_one(n):
            """Internal helper to restore a single feature"""
            if n in module.__disable_backup__:
                setattr(module, n, module.__disable_backup__.pop(n))
                restored.append(n)
            else:
                missing.append(n)

        if restore_all:
            for n in list(module.__disable_backup__.keys()):
                _restore_one(n)
        else:
            if name is None:
                return {"restored": [], "missing": []}
            _restore_one(name)

        return {"restored": restored, "missing": missing}

    def freeze(self, message: str) -> None:
        """
        Make the module completely immutable by preventing attribute modifications.

        Parameters
        ----------
        message : str
            Error message to display on modification attempts

        Side Effects
        ------------
        - Sets module.__frozen__ = True
        - Replaces module.__setattr__ with raising stub

        Examples
        --------
        >>> pme = pmeX("math")
        >>> pme.freeze("Module is frozen!")
        """
        module = self.module
        module.__frozen__ = True
        orig_setattr = module.__setattr__
        msg = message or f"Module '{module.__name__}' is frozen"

        def _locked(*a, **k):
            """Replacement __setattr__ that prevents modifications"""
            raise RuntimeError(msg)

        module.__setattr__ = _locked

    def readonly(self, freeze=False) -> None:
        """
        Freeze the module by wrapping its functions, classes, and attributes.

        Provides two levels of protection:
        - freeze=False: Makes attributes read-only but preserves functionality
        - freeze=True: Completely disables functionality with error stubs

        Parameters
        ----------
        freeze : bool, optional
            Protection level. Defaults to False.
            - False: Read-only access to original functionality
            - True: Complete lockdown with RuntimeError on usage

        Side Effects
        ------------
        - Creates module.__readonly_backup__ to store original attributes
        - Replaces module attributes with protected versions
        - Preserves internal attributes (starting with '__')

        Note
        ----
        Once applied, the module cannot be modified or extended until reverted

        Examples
        --------
        >>> pme = pmeX("math")
        >>> pme.readonly(freeze=True)
        """
        module = self.module

        # Create backup storage for original attributes
        if not hasattr(module, "__readonly_backup__"):
            module.__readonly_backup__ = {}

        for name in dir(module):
            if name.startswith("__"):
                continue  # Ignore internal attributes

            if name in module.__readonly_backup__:
                continue  # Skip already backed-up attributes

            try:
                attr = getattr(module, name)
            except Exception:
                continue  # Skip lazy-loaded or broken attributes

            # Store original attribute
            module.__readonly_backup__[name] = attr

            if freeze:
                # Wrap functions
                if callable(attr) and not isinstance(attr, type):

                    def _raise_fn(*args, **kwargs):
                        """Frozen function stub that raises RuntimeError"""
                        raise RuntimeError(
                            f"Function '{name}' is readonly and cannot be modified or called"
                        )

                    setattr(module, name, _raise_fn)

                # Wrap classes
                elif isinstance(attr, type):

                    class _DisabledClass:
                        """Frozen class stub that raises RuntimeError"""

                        def __init__(self, *a, **k):
                            raise RuntimeError(
                                f"Class '{name}' is readonly and cannot be instantiated"
                            )

                        def __getattribute__(self, item):
                            raise RuntimeError(f"Class '{name}' is readonly")

                    setattr(module, name, _DisabledClass)

                # Wrap other attributes (constants, objects)
                else:
                    setattr(module, name, property(lambda self: attr))
            else:
                # If freeze=False, only make attributes read-only but keep functionality
                if callable(attr) and not isinstance(attr, type):
                    # Keep function callable but prevent modification
                    setattr(module, name, property(lambda self: attr))
                elif isinstance(attr, type):
                    # Keep class accessible but prevent instantiation and modification
                    class _ReadonlyClass:
                        """Read-only class wrapper preserving inspection capabilities"""

                        def __init__(self, *a, **k):
                            raise RuntimeError(
                                f"Class '{name}' is readonly and cannot be instantiated"
                            )

                        def __getattribute__(self, item):
                            # Allow access to class methods and attributes for inspection
                            if item in [
                                "__class__",
                                "__name__",
                                "__module__",
                                "__doc__",
                            ]:
                                return super().__getattribute__(item)
                            raise RuntimeError(
                                f"Class '{name}' is readonly - cannot access instance attributes"
                            )

                    # Preserve class metadata
                    _ReadonlyClass.__name__ = attr.__name__
                    _ReadonlyClass.__module__ = attr.__module__
                    _ReadonlyClass.__doc__ = attr.__doc__
                    setattr(module, name, _ReadonlyClass)
                else:
                    # Make non-callable attributes read-only
                    setattr(module, name, property(lambda self: attr))
