#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Module patching and hooking.

Provides methods to add hooks, patch attributes, and manage modifications
to module attributes with proper locking and backup mechanisms.
"""

from typing import Optional, Any, Callable, List
from functools import wraps


class PatchingManager:
    """
    Manager for module patching and hook operations.

    This class handles function hooks, attribute locking, and patching
    with proper backup and restoration capabilities.
    """

    def __init__(self, module):
        """
        Initialize PatchingManager.

        Parameters
        ----------
        module : ModuleType
            The target module for patching operations
        """
        self.module = module

    def hooks(
        self,
        func_name: str,
        before: Optional[Callable] = None,
        after: Optional[Callable] = None,
    ) -> None:
        """
        Adds before/after hooks around a function in the module.

        Supports multiple hooks per function and stackable behavior.

        Parameters
        ----------
        func_name : str
            Name of the function in the module to hook.
        before : callable, optional
            Function to execute before the original function.
        after : callable, optional
            Function to execute after the original function, receives the result.

        Raises
        ------
        AttributeError
            If the function does not exist in the module.
        TypeError
            If the target is not callable.

        Examples
        --------
        >>> pme = pmeX("math")
        >>> def before_hook():
        ...     print("Before sqrt")
        >>> pme.hooks("sqrt", before=before_hook)
        """
        module = self.module

        # Validate function exists
        if not hasattr(module, func_name):
            raise AttributeError(
                f"Function '{func_name}' not found in module '{module.__name__}'"
            )

        original = getattr(module, func_name)
        if not callable(original):
            raise TypeError(f"'{func_name}' exists but is not callable")

        # Setup hooks store
        if not hasattr(module, "__hooks__"):
            module.__hooks__ = {}

        if func_name not in module.__hooks__:
            module.__hooks__[func_name] = {
                "before": [],
                "after": [],
                "original": original,
            }

            # Wrap function once
            def wrapper(*args, **kwargs):
                info = module.__hooks__[func_name]

                for h in info["before"]:
                    h(*args, **kwargs)

                result = info["original"](*args, **kwargs)

                for h in info["after"]:
                    h(result)

                return result

            setattr(module, func_name, wrapper)

        # Register new hooks
        if before:
            module.__hooks__[func_name]["before"].append(before)
        if after:
            module.__hooks__[func_name]["after"].append(after)

    def lock_attr(self, names: List[str]) -> None:
        """
        Locks specific attributes in the module to prevent modification.

        Works safely with hooks and patches.

        Parameters
        ----------
        names : list of str
            List of attribute names to lock.

        Examples
        --------
        >>> pme = pmeX("math")
        >>> pme.lock_attr(["pi", "e"])
        """
        module = self.module

        if not hasattr(module, "__locked__"):
            module.__locked__ = set()

        module.__locked__.update(names)

        if not hasattr(module, "__lock_backup__"):
            module.__lock_backup__ = module.__setattr__

            def guard(attr: str, value: Any) -> None:
                if hasattr(module, "__locked__") and attr in module.__locked__:
                    raise RuntimeError(f"'{attr}' is locked and cannot be modified")
                module.__lock_backup__(attr, value)

            module.__setattr__ = lambda attr, v: guard(attr, v)

    def patch(self, name: str, new_obj: Any) -> None:
        """
        Patches an attribute in the module.

        Respects locks and creates backups for unpatching.

        Parameters
        ----------
        name : str
            Attribute name to patch.
        new_obj : Any
            New object to assign.

        Raises
        ------
        AttributeError
            If the attribute does not exist in the module.
        RuntimeError
            If the attribute is locked.

        Examples
        --------
        >>> pme = pmeX("math")
        >>> pme.patch("pi", 3.14)
        """
        module = self.module

        if not hasattr(module, name):
            raise AttributeError(
                f"Attribute '{name}' not found in module '{module.__name__}'"
            )
        if hasattr(module, "__locked__") and name in module.__locked__:
            raise RuntimeError(f"Cannot patch locked attribute '{name}'")

        if not hasattr(module, "__patch_backup__"):
            module.__patch_backup__ = {}

        if name not in module.__patch_backup__:
            module.__patch_backup__[name] = getattr(module, name)

        setattr(module, name, new_obj)

    def unpatch(self, name: Optional[str] = None) -> None:
        """
        Restores patched attributes to their original values.

        Parameters
        ----------
        name : str, optional
            Name of the attribute to unpatch. If None, restores all patched attributes.

        Examples
        --------
        >>> pme = pmeX("math")
        >>> pme.patch("pi", 3.14)
        >>> pme.unpatch("pi")
        """
        module = self.module

        if not hasattr(module, "__patch_backup__"):
            return

        if name:
            if name in module.__patch_backup__:
                setattr(module, name, module.__patch_backup__[name])
                del module.__patch_backup__[name]
            return

        for attr, original in module.__patch_backup__.items():
            setattr(module, attr, original)

        module.__patch_backup__.clear()
