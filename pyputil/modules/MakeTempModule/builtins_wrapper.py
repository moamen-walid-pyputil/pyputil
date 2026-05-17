#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Safe wrapper for built-in functions.
"""

import builtins
from typing import Any, Dict, Set
from .dataclasses import ModuleConfig
from .enums import ModulePolicy


class _SafeBuiltins(dict):
    """
    Safe wrapper for built-in functions.

    Provides controlled access to built-in functions based on
    configuration, with overrides for unsafe functions.

    Parameters
    ----------
    allowed : Set[str]
        Set of allowed built-in function names.
    original_builtins : dict
        Original builtins dictionary to wrap.
    config : ModuleConfig
        Module configuration for policy checks.

    Raises
    ------
    KeyError
        When accessing a built-in that is not allowed.

    Examples
    --------
    >>> safe_builtins = _SafeBuiltins({"len", "range"}, builtins.__dict__)
    >>> safe_builtins["len"]
    <built-in function len>
    """

    def __init__(
        self, allowed: Set[str], original_builtins: Dict[str, Any], config: ModuleConfig
    ):
        """
        Initialize safe builtins wrapper.

        Parameters
        ----------
        allowed : Set[str]
            Allowed built-in function names.
        original_builtins : dict
            Original builtins dictionary.
        config : ModuleConfig
            Module configuration.
        """
        super().__init__()
        self._original = original_builtins
        self._allowed = allowed
        self.config = config

        # Copy allowed builtins
        for name in allowed:
            if name in original_builtins:
                self[name] = original_builtins[name]

        # Override unsafe functions
        self["print"] = self._safe_print
        self["input"] = self._safe_input
        self["open"] = self._safe_open
        self["__import__"] = self._deny_import
        self["eval"] = self._deny_eval
        self["exec"] = self._deny_exec
        self["compile"] = self._deny_compile

    def _safe_print(self, *args, **kwargs) -> None:
        """
        Safe version of print function.

        Uses stdout.write if file I/O is not allowed to avoid
        potential issues with file descriptor manipulation.

        Parameters
        ----------
        *args : Any
            Arguments to print.
        **kwargs : Any
            Keyword arguments for print.
        """
        if ModulePolicy.ALLOW_FILE_IO in self.config.policies:
            return builtins.print(*args, **kwargs)

        # Safe alternative without file I/O
        import sys

        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        sys.stdout.write(sep.join(str(arg) for arg in args) + end)

    def _safe_input(self, prompt: str = "") -> str:
        """
        Safe version of input function.

        Parameters
        ----------
        prompt : str, default=""
            Prompt to display.

        Returns
        -------
        str
            User input.

        Raises
        ------
        IOError
            If file I/O operations are not allowed.
        """
        if ModulePolicy.ALLOW_FILE_IO not in self.config.policies:
            raise IOError("Input operations are not allowed")
        return builtins.input(prompt)

    def _safe_open(self, *args, **kwargs):
        """
        Safe version of open function.

        Parameters
        ----------
        *args : Any
            Arguments for open.
        **kwargs : Any
            Keyword arguments for open.

        Returns
        -------
        file object
            Opened file.

        Raises
        ------
        IOError
            If file I/O operations are not allowed.
        """
        if ModulePolicy.ALLOW_FILE_IO not in self.config.policies:
            raise IOError("File operations are not allowed")
        return builtins.open(*args, **kwargs)

    def _deny_import(self, *args, **kwargs) -> None:
        """
        Deny __import__ function.

        Raises
        ------
        ImportError
            Always raised.
        """
        raise ImportError("Import function is disabled")

    def _deny_eval(self, *args, **kwargs) -> None:
        """
        Deny eval function.

        Raises
        ------
        NameError
            Always raised.
        """
        raise NameError("eval function is disabled")

    def _deny_exec(self, *args, **kwargs) -> None:
        """
        Deny exec function.

        Raises
        ------
        NameError
            Always raised.
        """
        raise NameError("exec function is disabled")

    def _deny_compile(self, *args, **kwargs) -> None:
        """
        Deny compile function.

        Raises
        ------
        NameError
            Always raised.
        """
        raise NameError("compile function is disabled")

    def __getitem__(self, key: str) -> Any:
        """
        Get a built-in function if allowed.

        Parameters
        ----------
        key : str
            Built-in function name.

        Returns
        -------
        Any
            Built-in function.

        Raises
        ------
        KeyError
            If the built-in is not in the allowed list.
        """
        if key in self:
            return super().__getitem__(key)
        raise KeyError(f"Builtin '{key}' is not allowed")
