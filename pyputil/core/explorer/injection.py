#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Code injection functionality for pmeX.

Provides methods to inject and revert Python code in module namespaces.
"""

from typing import Dict, Optional


class Injecter:
    """
    Manager for code injection operations in modules.

    This class handles runtime code injection into module namespaces,
    allowing dynamic modification of module attributes, functions, and classes.
    """

    def __init__(self, module):
        """
        Initialize Injecter with target module.

        Parameters
        ----------
        module : ModuleType
            The target module for injection operations
        """
        self.module = module

    def inject(self, code_str: str) -> dict:
        """
        Inject Python code into a module's namespace at runtime.

        Parameters
        ----------
        code_str : str
            Python source code to execute in module namespace

        Returns
        -------
        dict
            Summary of changes with keys:
            - "added": List of newly added attribute names
            - "changed": List of modified attribute names

        Side Effects
        ------------
        - Creates/updates module.__inject_backup__ to track original values
        - Creates/updates module.__inject_added__ to track new attributes

        Examples
        --------
        >>> pme = pmeX("math")
        >>> result = pme.inject("pi = 3.14")
        >>> print(result)
        {'added': [], 'changed': ['pi']}
        """
        module = self.module

        if not hasattr(module, "__inject_backup__"):
            module.__inject_backup__ = {}
        if not hasattr(module, "__inject_added__"):
            module.__inject_added__ = set()

        ns = module.__dict__
        old_keys = set(ns.keys())
        old_values = {k: ns[k] for k in old_keys}
        exec(code_str, ns)
        new_keys = set(ns.keys())
        added = new_keys - old_keys
        changed = {k for k in (new_keys & old_keys) if ns[k] is not old_values[k]}

        module.__inject_added__.update(added)
        for name in changed:
            if name not in module.__inject_backup__:
                module.__inject_backup__[name] = old_values[name]

        return {"added": sorted(added), "changed": sorted(changed)}

    def revert_injection(self, name: str = None, restore_all: bool = False) -> dict:
        """
        Revert injections previously made by inject_code.

        Restores original module state by either reverting specific injections
        or all recorded injections.

        Parameters
        ----------
        name : str, optional
            Specific attribute name to revert
        restore_all : bool, optional
            Whether to revert all injections. Defaults to False.

        Returns
        -------
        dict
            Summary of revert operations with keys:
            - "restored": List of restored attribute names
            - "deleted": List of deleted attribute names

        Examples
        --------
        >>> pme = pmeX("math")
        >>> pme.inject("pi = 3.14")
        >>> result = pme.revert_injection("pi")
        >>> print(result)
        {'restored': ['pi'], 'deleted': []}
        """
        module = self.module

        ns = module.__dict__
        if not hasattr(module, "__inject_backup__") and not hasattr(
            module, "__inject_added__"
        ):
            return {"restored": [], "deleted": []}

        restored = []
        deleted = []

        def _restore(n):
            """Internal helper to restore a single attribute"""
            if hasattr(module, "__inject_backup__") and n in module.__inject_backup__:
                ns[n] = module.__inject_backup__.pop(n)
                restored.append(n)
            elif hasattr(module, "__inject_added__") and n in module.__inject_added__:
                module.__inject_added__.remove(n)
                if n in ns:
                    del ns[n]
                deleted.append(n)

        if restore_all:
            for n in list(getattr(module, "__inject_backup__", {}).keys()):
                _restore(n)
            for n in list(getattr(module, "__inject_added__", set())):
                _restore(n)
        else:
            if name is None:
                return {"restored": [], "deleted": []}
            _restore(name)

        return {"restored": restored, "deleted": deleted}
