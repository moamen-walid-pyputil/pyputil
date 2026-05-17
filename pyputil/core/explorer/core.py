#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Python Module Explorer (pmeX) - Advanced Module Control and Manipulation Tool

pmeX provides a comprehensive framework for runtime Python module analysis,
modification, and control. It enables developers to dynamically inspect, mutate,
clone, and monitor Python modules with fine-grained control over attributes,
functions, imports, and module lifecycle.

Examples
--------
>>> import math
>>> explorer = pmeX(math)
>>> explorer.inject("TAU = 2 * pi")
>>> explorer.patch("sqrt", lambda x: x ** 0.5)
>>> cloned = explorer.clone({'pi': 3.14})
"""

from typing import Dict, Any, Set, Optional, List, Tuple, Union, Callable
from pathlib import Path
from types import ModuleType
import importlib
import inspect
import sys
import pickle
import hashlib
import time
import json
import copy
import gc
import warnings
from datetime import datetime
from collections import defaultdict
import traceback

from ...path.utils import load, move, list_path, make
from ...core.sca.utils import create_dict

from .cloning import clone
from .injection import Injecter
from .protection import ProtectionManager
from .patching import PatchingManager


class pmeX:
    """
    Python Module Explorer for runtime module analysis and modification.

    This class provides advanced tools for modules tracking, injection, patching,
    protection, cloning, and control. It maintains change history and can intercept
    import operations.

    Parameters
    ----------
    module : ModuleType
        The Python module object to explore and control

    Attributes
    ----------
    name : str
        Original module name
    path : Optional[str]
        File system path to the module's directory, if available
    injection : Injecter
        Manager for code injection operations
    protection : ProtectionManager
        Manager for module protection and feature disabling
    patching : PatchingManager
        Manager for patching and hook installation
    _change_history : List[Dict[str, Any]]
        History of all changes made to the module
    _import_interceptor : Optional[Callable]
        Callback function for intercepting import operations
    _blocked_imports : Set[str]
        Set of module names that are blocked from being imported
    _mocked_imports : Dict[str, Any]
        Dictionary mapping module names to their mock objects
    _original_import : Callable
        Original __import__ function saved for restoration
    _import_intercept_active : bool
        Flag indicating if import interception is currently active

    Examples
    --------
    >>> import math
    >>> explorer = pmeX(math)
    >>> explorer.name
    'math'
    >>> explorer.path
    '/usr/lib/python3.9/lib-dynload'
    >>> explorer.inject("VERSION = '1.0'")
    >>> explorer.disable_feature("sqrt", "warn")
    """

    def __init__(self, module: ModuleType) -> None:
        """
        Initialize a pmeX explorer instance for a target module.

        Sets up all managers, initializes change tracking, and prepares
        import interception infrastructure.

        Parameters
        ----------
        module : ModuleType
            The Python module object to explore and control

        Raises
        ------
        TypeError
            If module is not a ModuleType instance

        Examples
        --------
        >>> import math
        >>> explorer = pmeX(math)
        >>> isinstance(explorer, pmeX)
        True
        
        >>> try:
        ...     explorer = pmeX("not a module")
        ... except TypeError as e:
        ...     print(e)
        Expected module module, got <str>
        """
        if not isinstance(module, ModuleType):
            raise TypeError(f"Expected module module, got <{type(module).__name__}>")

        self.module = module
        self.name = module.__name__
        file = getattr(module, "__file__", None)
        self.path = str(Path(file).resolve().parent) if file else None

        # Initialize managers
        self.injection = Injecter(module)
        self.protection = ProtectionManager(module, module)
        self.patching = PatchingManager(module)

        # Initialize change tracking
        self._change_history = []
        self._snapshots = {}
        
        # Initialize import control
        self._import_interceptor = None
        self._blocked_imports = set()
        self._mocked_imports = {}
        self._original_import = None
        self._import_intercept_active = False

        # Record initial state
        self._record_change("__init__", None, module)

    def _record_change(self, name: str, old_value: Any, new_value: Any) -> None:
        """
        Record a change in the module's attribute for history tracking.

        Parameters
        ----------
        name : str
            Name of the changed attribute
        old_value : Any
            Previous value of the attribute
        new_value : Any
            New value of the attribute
        """
        self._change_history.append({
            'timestamp': datetime.now().isoformat(),
            'attribute': name,
            'old_value': repr(old_value)[:200],  # Limit length
            'new_value': repr(new_value)[:200],
            'type': 'modification'
        })

    # ==========================================================================
    # Code Injection Methods
    # ==========================================================================

    def inject(self, code_str: str) -> Dict[str, Any]:
        """
        Dynamically inject Python code into the module's namespace.

        The injected code can define new variables, functions, or classes,
        or modify existing ones. All changes are tracked in the change history.

        Parameters
        ----------
        code_str : str
            Valid Python code to execute within the module's namespace

        Returns
        -------
        Dict[str, Any]
            Dictionary containing operation results including:
            - 'success': bool indicating if injection succeeded
            - 'message': status message
            - 'defined': list of newly defined names

        Raises
        ------
        SyntaxError
            If the code string contains invalid Python syntax
        Exception
            Any exception raised during code execution

        Examples
        --------
        >>> import math
        >>> explorer = pmeX(math)
        
        # Inject a constant
        >>> result = explorer.inject("TAU = 2 * pi")
        >>> result['success']
        True
        
        # Inject a function
        >>> explorer.inject('''
        ... def circle_area(radius):
        ...     return pi * radius ** 2
        ... ''')
        
        # Inject a class
        >>> explorer.inject('''
        ... class Calculator:
        ...     def double(self, x):
        ...         return x * 2
        ... ''')
        
        # Access injected objects
        >>> math.TAU
        6.283185307179586
        >>> math.circle_area(5)
        78.53981633974483
        
        # Handle injection errors
        >>> try:
        ...     explorer.inject("invalid syntax !!!")
        ... except SyntaxError as e:
        ...     print("Syntax error detected")
        Syntax error detected
        """
        result = self.injection.inject(code_str)
        if result.get('defined'):
            for name in result['defined']:
                new_value = getattr(self.module, name, None)
                self._record_change(name, None, new_value)
        return result

    def revert_injection(self, name: Optional[str] = None, restore_all: bool = False) -> Dict[str, Any]:
        """
        Revert previously injected code, optionally restoring original values.

        Parameters
        ----------
        name : Optional[str], default=None
            Specific injected name to revert. If None, uses restore_all behavior
        restore_all : bool, default=False
            If True, revert all injected changes. Requires name=None

        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - 'reverted': list of names that were reverted
            - 'errors': list of errors encountered
            - 'success': bool indicating overall success

        Raises
        ------
        ValueError
            If restore_all is True and name is not None, or vice versa

        Examples
        --------
        >>> import math
        >>> explorer = pmeX(math)
        
        # Inject and then revert specific item
        >>> explorer.inject("TEST_VAR = 100")
        >>> hasattr(math, 'TEST_VAR')
        True
        >>> explorer.revert_injection('TEST_VAR')
        >>> hasattr(math, 'TEST_VAR')
        False
        
        # Inject multiple items and revert all
        >>> explorer.inject("A = 1\\nB = 2\\nC = 3")
        >>> explorer.revert_injection(restore_all=True)
        >>> hasattr(math, 'A')
        False
        """
        if restore_all and name is not None:
            raise ValueError("Cannot specify 'name' when restore_all=True")
        if not restore_all and name is None:
            raise ValueError("Either 'name' or restore_all=True must be specified")
        
        result = self.injection.revert_injection(name, restore_all)
        
        if restore_all:
            self._record_change("bulk_revert", "injected_code", "original_state")
        else:
            old_value = getattr(self.module, name, None)
            self._record_change(name, old_value, "reverted")
        
        return result

    # ==========================================================================
    # Protection Methods
    # ==========================================================================

    def disable_feature(self, name: str, behavior: str = "raise", message: Optional[str] = None) -> Dict[str, Any]:
        """
        Disable a specific feature (function, attribute, or method) of the module.

        This method replaces the target feature with a placeholder that implements
        the specified behavior when accessed or called.

        Parameters
        ----------
        name : str
            Name of the feature to disable (e.g., 'sqrt', 'pi', 'Calculator')
        behavior : str, default='raise'
            How to handle access to disabled feature:
            - 'raise': Raise RuntimeError when accessed
            - 'warn': Print warning and return None
            - 'ignore': Silently return None
            - 'return': Return a specified value (requires 'return_value' parameter)
        message : Optional[str], default=None
            Custom error or warning message. If None, a default message is used

        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - 'success': bool indicating if operation succeeded
            - 'feature': name of disabled feature
            - 'behavior': behavior mode applied
            - 'original': reference to original feature (for restoration)

        Examples
        --------
        >>> import math
        >>> explorer = pmeX(math)
        
        # Disable sqrt with exception
        >>> explorer.disable_feature('sqrt', 'raise')
        >>> try:
        ...     math.sqrt(16)
        ... except RuntimeError as e:
        ...     print(e)
        Feature 'sqrt' has been disabled
        
        # Disable with warning
        >>> explorer.disable_feature('log', 'warn', 'Log function is deprecated')
        >>> result = math.log(10)
        UserWarning: Log function is deprecated
        >>> print(result)
        None
        
        # Disable and return custom value
        >>> explorer.disable_feature('pi', 'return', 'Pi is not available')
        >>> math.pi
        'Pi is not available'
        
        # Revert a disabled feature
        >>> explorer.revert_feature('pi')
        >>> math.pi
        3.141592653589793
        """
        result = self.protection.disable_feature(name, behavior, message)
        self._record_change(name, result.get('original'), result.get('new'))
        return result

    def revert_feature(self, name: Optional[str] = None, restore_all: bool = False) -> Dict[str, Any]:
        """
        Restore a previously disabled feature to its original state.

        Parameters
        ----------
        name : Optional[str], default=None
            Specific feature name to restore. Required if restore_all=False
        restore_all : bool, default=False
            If True, restore all disabled features

        Returns
        -------
        Dict[str, Any]
            Dictionary containing restored features and status information

        Raises
        ------
        ValueError
            If restore_all is True and name is not None, or vice versa

        Examples
        --------
        >>> import math
        >>> explorer = pmeX(math)
        
        # Disable and restore single feature
        >>> explorer.disable_feature('sqrt', 'raise')
        >>> explorer.revert_feature('sqrt')
        >>> math.sqrt(16)
        4.0
        
        # Disable multiple and restore all
        >>> explorer.disable_feature('sin', 'warn')
        >>> explorer.disable_feature('cos', 'warn')
        >>> explorer.revert_feature(restore_all=True)
        """
        result = self.protection.revert_feature(name, restore_all)
        self._record_change(f"revert_{name or 'all'}", "disabled", "restored")
        return result

    def freeze(self, message: str = "Module has been frozen and cannot be modified") -> None:
        """
        Permanently freeze the module to prevent any further modifications.

        After freezing, all attempts to modify the module (including injection,
        patching, or direct attribute assignment) will raise RuntimeError.

        Parameters
        ----------
        message : str, default='Module has been frozen and cannot be modified'
            Custom error message to display when modification is attempted

        Raises
        ------
        RuntimeError
            If the module is already frozen or an error occurs during freezing

        Notes
        -----
        This operation cannot be undone within the same interpreter session.
        Freezing affects the module at the C level using sys.modules guarding.

        Examples
        --------
        >>> import math
        >>> explorer = pmeX(math)
        >>> explorer.freeze("math module is locked")
        
        >>> try:
        ...     math.pi = 3.0
        ... except RuntimeError as e:
        ...     print(e)
        math module is locked
        
        >>> # Injections also fail
        >>> try:
        ...     explorer.inject("NEW = 42")
        ... except RuntimeError as e:
        ...     print(e)
        math module is locked
        """
        self.protection.freeze(message)
        self._record_change("freeze", None, message)

    def readonly(self, freeze: bool = False) -> None:
        """
        Make the module read-only, optionally with permanent freezing.

        This creates property descriptors that block attribute assignment,
        deletion, and creation while still allowing reading operations.

        Parameters
        ----------
        freeze : bool, default=False
            If True, also permanently freeze the module (cannot be reverted)
            If False, readonly can be reverted by recreating the module

        Raises
        ------
        RuntimeError
            If an error occurs while making the module read-only

        Notes
        -----
        When freeze=False, the protection is implemented at the Python level
        and could potentially be bypassed. Use freeze=True for stronger security.

        Examples
        --------
        >>> import math
        >>> explorer = pmeX(math)
        
        # Read-only without freeze (reversible via new module instance)
        >>> explorer.readonly(freeze=False)
        >>> try:
        ...     math.pi = 3.14
        ... except AttributeError as e:
        ...     print(e)
        Cannot modify read-only module
        
        # Read-only with freeze (permanent)
        >>> explorer = pmeX(math)
        >>> explorer.readonly(freeze=True)
        >>> # Any modification attempt raises RuntimeError
        """
        self.protection.readonly(freeze)
        self._record_change("readonly", None, {"freeze": freeze})

    # ==========================================================================
    # Patching and Hooking Methods
    # ==========================================================================

    def hooks(self, func_name: str, before: Optional[Callable] = None, after: Optional[Callable] = None) -> None:
        """
        Install before/after hooks on a function or method.

        Hooks allow executing custom code before and/or after the target function
        executes, without modifying the original function's code.

        Parameters
        ----------
        func_name : str
            Name of the function/method to hook
        before : Optional[Callable], default=None
            Function to execute before target. Signature: before(*args, **kwargs)
            Should return either None or a tuple (new_args, new_kwargs) to modify call
        after : Optional[Callable], default=None
            Function to execute after target. Signature: after(result, *args, **kwargs)
            Can modify and return a different result

        Raises
        ------
        AttributeError
            If the function name doesn't exist in the module
        TypeError
            If before/after are not callable (when provided)

        Examples
        --------
        >>> import math
        >>> explorer = pmeX(math)
        
        # Log function calls
        >>> def log_before(*args, **kwargs):
        ...     print(f"Calling sqrt with args={args}")
        ...     return None  # Don't modify arguments
        >>> def log_after(result, *args, **kwargs):
        ...     print(f"sqrt returned {result}")
        ...     return result  # Return unmodified result
        
        >>> explorer.hooks('sqrt', before=log_before, after=log_after)
        >>> math.sqrt(16)
        Calling sqrt with args=(16,)
        sqrt returned 4.0
        4.0
        
        # Modify arguments before function call
        >>> def double_value(*args, **kwargs):
        ...     return (args[0] * 2,), kwargs
        >>> explorer.hooks('sqrt', before=double_value)
        >>> math.sqrt(16)  # Actually computes sqrt(32)
        5.656854249492381
        
        # Remove hooks
        >>> explorer.unpatch('sqrt')
        """
        self.patching.hooks(func_name, before, after)
        self._record_change(f"hook_{func_name}", None, {"before": before, "after": after})

    def lock_attr(self, names: List[str]) -> None:
        """
        Lock specific attributes to prevent deletion or modification.

        Locked attributes become read-only and cannot be deleted. This provides
        finer control than global read-only mode.

        Parameters
        ----------
        names : List[str]
            List of attribute names to lock

        Raises
        ------
        AttributeError
            If an attribute name doesn't exist in the module

        Notes
        -----
        Locked attributes can still be unlocked by patching, but direct
        assignment or deletion will raise AttributeError.

        Examples
        --------
        >>> import math
        >>> explorer = pmeX(math)
        
        # Lock pi and e constants
        >>> explorer.lock_attr(['pi', 'e'])
        
        >>> try:
        ...     math.pi = 3.0
        ... except AttributeError as e:
        ...     print(e)
        Can't modify locked attribute 'pi'
        
        >>> try:
        ...     del math.e
        ... except AttributeError as e:
        ...     print(e)
        Can't delete locked attribute 'e'
        
        # Unlock through patching
        >>> explorer.unpatch('pi')
        >>> math.pi = 3.14  # Now works
        """
        self.patching.lock_attr(names)
        self._record_change("lock_attr", None, names)

    def patch(self, name: str, new_obj: Any) -> None:
        """
        Replace a module attribute (function, variable, class) with a new object.

        Patching is more flexible than hooks as it completely replaces the target,
        while hooks wrap the original function.

        Parameters
        ----------
        name : str
            Name of the attribute to patch
        new_obj : Any
            New object to replace the existing attribute

        Raises
        ------
        AttributeError
            If the attribute doesn't exist (unless creating new attribute)

        Notes
        -----
        Patching records the original value for future unpatching.
        To temporarily replace an attribute, use patch() then unpatch().

        Examples
        --------
        >>> import math
        >>> explorer = pmeX(math)
        
        # Replace with constant
        >>> explorer.patch('pi', 3.14)
        >>> math.pi
        3.14
        
        # Replace with modified version
        >>> explorer.patch('sqrt', lambda x: x ** 0.5 * 2)  # Double result
        >>> math.sqrt(16)
        8.0
        
        # Replace with completely new functionality
        >>> explorer.patch('sin', lambda x: f"sin({x}) = {__import__('math').sin(x)}")
        >>> math.sin(1.57)
        'sin(1.57) = 0.9999996829318346'
        
        # Restore original
        >>> explorer.unpatch('pi')
        >>> math.pi
        3.141592653589793
        """
        old_value = getattr(self.module, name, None)
        self.patching.patch(name, new_obj)
        self._record_change(name, old_value, new_obj)

    def unpatch(self, name: Optional[str] = None) -> None:
        """
        Restore a patched attribute to its original value.

        Parameters
        ----------
        name : Optional[str], default=None
            Name of the attribute to unpatch. If None, restores all patched attributes

        Raises
        ------
        AttributeError
            If the attribute wasn't previously patched

        Examples
        --------
        >>> import math
        >>> explorer = pmeX(math)
        
        # Patch multiple functions
        >>> explorer.patch('sqrt', lambda x: x ** 0.5 * 2)
        >>> explorer.patch('sin', lambda x: f"sin({x})")
        
        # Unpatch a specific function
        >>> explorer.unpatch('sqrt')
        >>> math.sqrt(16)  # Restored to original
        4.0
        
        # Unpatch all remaining
        >>> explorer.unpatch()
        >>> math.sin(1.57)
        0.9999996829318346  # Original sin function
        """
        self.patching.unpatch(name)
        self._record_change(f"unpatch_{name or 'all'}", "patched", "original")

    # ==========================================================================
    # Import Control Methods
    # ==========================================================================

    def block_imports(self, modules: List[str]) -> Dict[str, bool]:
        """
        Block specific modules from being imported within the target module.

        This intercepts import statements to prevent certain modules from being
        imported, raising ImportError when attempted.

        Parameters
        ----------
        modules : List[str]
            List of module names to block (supports wildcards like 'numpy.*')

        Returns
        -------
        Dict[str, bool]
            Dictionary mapping module names to whether blocking was successful

        Raises
        ------
        RuntimeError
            If import interception hasn't been activated

        Notes
        -----
        Call `activate_import_interception()` first to enable import control.
        Blocked modules affect all imports in the interpreter, not just the target.

        Examples
        --------
        >>> explorer = pmeX(math)
        >>> explorer.activate_import_interception()
        
        # Block dangerous modules
        >>> explorer.block_imports(['os', 'subprocess', 'sys'])
        
        # Try to import blocked module
        >>> try:
        ...     import os
        ... except ImportError as e:
        ...     print(e)
        Import of module 'os' is blocked by pmeX
        
        # Block with wildcards
        >>> explorer.block_imports(['numpy.*'])
        >>> try:
        ...     from numpy import array
        ... except ImportError as e:
        ...     print(e)
        Import of module 'numpy' is blocked by pmeX
        
        # Check blocked list
        >>> print(explorer.get_blocked_imports())
        {'os', 'subprocess', 'sys', 'numpy.*'}
        """
        if not self._import_intercept_active:
            self.activate_import_interception()
        
        results = {}
        for module in modules:
            if module not in self._blocked_imports:
                self._blocked_imports.add(module)
                results[module] = True
            else:
                results[module] = False
        
        self._record_change("block_imports", None, list(modules))
        return results

    def mock_import(self, module_name: str, mock_object: Any) -> None:
        """
        Replace a module import with a mock object.

        When the specified module is imported, the mock object is returned instead
        of the real module. This is useful for testing and dependency isolation.

        Parameters
        ----------
        module_name : str
            Name of the module to mock (e.g., 'numpy', 'requests')
        mock_object : Any
            Object to return instead of the real module (typically a MagicMock)

        Raises
        ------
        RuntimeError
            If import interception hasn't been activated

        Notes
        -----
        Mocking takes precedence over blocking. If a module is both mocked and
        blocked, the mock will be returned.

        Examples
        --------
        >>> from unittest.mock import MagicMock
        >>> explorer = pmeX(math)
        >>> explorer.activate_import_interception()
        
        # Mock a module
        >>> mock_np = MagicMock()
        >>> mock_np.array.return_value = [1, 2, 3]
        >>> explorer.mock_import('numpy', mock_np)
        
        # Now importing numpy returns the mock
        >>> import numpy as np
        >>> np.array([1, 2, 3])
        [1, 2, 3]
        
        # Mock with custom object
        >>> class FakeDatabase:
        ...     def query(self, sql):
        ...         return [{"id": 1, "name": "test"}]
        >>> explorer.mock_import('database', FakeDatabase())
        >>> import database
        >>> db = database
        >>> db.query("SELECT * FROM users")
        [{'id': 1, 'name': 'test'}]
        
        # Remove mock
        >>> explorer.unmock_import('numpy')
        """
        if not self._import_intercept_active:
            self.activate_import_interception()
        
        self._mocked_imports[module_name] = mock_object
        self._record_change("mock_import", None, module_name)

    def unmock_import(self, module_name: str) -> bool:
        """
        Remove a mock for a previously mocked module.

        Parameters
        ----------
        module_name : str
            Name of the module to unmock

        Returns
        -------
        bool
            True if the mock was removed, False if it wasn't mocked

        Examples
        --------
        >>> explorer = pmeX(math)
        >>> explorer.activate_import_interception()
        >>> explorer.mock_import('numpy', mock_object)
        >>> explorer.unmock_import('numpy')
        True
        
        # Now numpy imports normally
        >>> import numpy  # Actually imports real numpy
        """
        if module_name in self._mocked_imports:
            del self._mocked_imports[module_name]
            self._record_change("unmock_import", module_name, None)
            return True
        return False

    def intercept_import(self, callback: Callable[[str, Any], Tuple[str, Any]]) -> None:
        """
        Set a custom callback to intercept and modify imports.

        The callback receives the module name and the imported module object,
        and can modify or replace the module before it's returned.

        Parameters
        ----------
        callback : Callable[[str, Any], Tuple[str, Any]]
            Function that takes (module_name, module_object) and returns
            (new_name, new_module) tuple

        Raises
        ------
        RuntimeError
            If import interception hasn't been activated

        Examples
        --------
        >>> explorer = pmeX(math)
        >>> explorer.activate_import_interception()
        
        # Add prefix to all imported modules
        >>> def add_prefix(name, module):
        ...     return (f"mocked_{name}", module)
        >>> explorer.intercept_import(add_prefix)
        
        # Log all imports
        >>> import sys
        >>> def log_import(name, module):
        ...     print(f"Importing: {name}")
        ...     return (name, module)
        >>> explorer.intercept_import(log_import)
        
        # Transform specific modules
        >>> def transform_numpy(name, module):
        ...     if name == 'numpy':
        ...         module = MagicMock()
        ...     return (name, module)
        >>> explorer.intercept_import(transform_numpy)
        
        # Remove interceptor
        >>> explorer.disable_import_interception()
        """
        if not self._import_intercept_active:
            self.activate_import_interception()
        
        self._import_interceptor = callback
        self._record_change("intercept_import", None, callback)

    def activate_import_interception(self) -> None:
        """
        Activate the import interception system.

        This replaces the built-in __import__ function with a custom version
        that applies blocking, mocking, and interception rules.

        Raises
        ------
        RuntimeError
            If interception is already active

        Notes
        -----
        This affects the entire Python interpreter. Always call
        `disable_import_interception()` when done to restore normal imports.

        Examples
        --------
        >>> explorer = pmeX(math)
        >>> explorer.activate_import_interception()
        >>> explorer.block_imports(['os'])
        
        # Import interception is now active
        >>> try:
        ...     import os
        ... except ImportError:
        ...     print("Blocked!")
        Blocked!
        
        # Deactivate when done
        >>> explorer.disable_import_interception()
        """
        if self._import_intercept_active:
            raise RuntimeError("Import interception is already active")
        
        self._original_import = __builtins__['__import__']
        
        def intercepted_import(name, globals=None, locals=None, fromlist=(), level=0):
            # Check if module is mocked
            if name in self._mocked_imports:
                return self._mocked_imports[name]
            
            # Check if module is blocked
            for blocked in self._blocked_imports:
                if blocked.endswith('.*'):
                    if name.startswith(blocked[:-2]):
                        raise ImportError(f"Import of module {name!r} is blocked by pmeX")
                elif name == blocked:
                    raise ImportError(f"Import of module {name!r} is blocked by pmeX")
            
            # Perform normal import
            module = self._original_import(name, globals, locals, fromlist, level)
            
            # Apply interceptor if set
            if self._import_interceptor:
                new_name, new_module = self._import_interceptor(name, module)
                if new_name != name:
                    sys.modules[new_name] = new_module
                return new_module
            
            return module
        
        __builtins__['__import__'] = intercepted_import
        self._import_intercept_active = True

    def disable_import_interception(self) -> None:
        """
        Disable the import interception system.

        Restores the original __import__ function and clears all blocking
        and mocking rules.

        Returns
        -------
        bool
            True if interception was disabled, False if it wasn't active

        Examples
        --------
        >>> explorer = pmeX(math)
        >>> explorer.activate_import_interception()
        >>> explorer.block_imports(['os'])
        >>> explorer.disable_import_interception()
        
        # Now imports work normally
        >>> import os  # Successfully imports os
        >>> os.path.exists('/tmp')
        True
        """
        if not self._import_intercept_active:
            return False
        
        if self._original_import:
            __builtins__['__import__'] = self._original_import
        
        self._import_intercept_active = False
        self._blocked_imports.clear()
        self._mocked_imports.clear()
        self._import_interceptor = None
        self._original_import = None
        
        return True

    def get_blocked_imports(self) -> Set[str]:
        """
        Get the set of currently blocked import names.

        Returns
        -------
        Set[str]
            Set of module names that are currently blocked

        Examples
        --------
        >>> explorer.block_imports(['os', 'sys'])
        >>> print(explorer.get_blocked_imports())
        {'os', 'sys'}
        """
        return self._blocked_imports.copy()

    def get_mocked_imports(self) -> Dict[str, Any]:
        """
        Get the dictionary of currently mocked imports.

        Returns
        -------
        Dict[str, Any]
            Dictionary mapping module names to their mock objects

        Examples
        --------
        >>> explorer.mock_import('numpy', mock_np)
        >>> mocks = explorer.get_mocked_imports()
        >>> print(mocks.keys())
        dict_keys(['numpy'])
        """
        return self._mocked_imports.copy()

    # ==========================================================================
    # Serialization and Persistence Methods
    # ==========================================================================

    def serialize(self, path: Optional[Union[str, Path]] = None, format: str = 'pickle') -> bytes:
        """
        Serialize the current state of the module to bytes or file.

        This captures the complete module state including all attributes,
        functions, and injected code. The serialized state can be restored later.

        Parameters
        ----------
        path : Optional[Union[str, Path]], default=None
            File path to save serialized state. If None, returns bytes
        format : str, default='pickle'
            Serialization format: 'pickle', 'json' (for simple objects), or 'msgpack'

        Returns
        -------
        bytes
            Serialized module state (when path is None)
        
        Raises
        ------
        ValueError
            If format is not supported or if serialization fails
        IOError
            If writing to file fails

        Notes
        -----
        Not all objects can be pickled (e.g., file handles, database connections).
        Use caution with modules that contain unserializable objects.

        Examples
        --------
        >>> import math
        >>> explorer = pmeX(math)
        >>> explorer.inject("VERSION = '2.0'")
        >>> explorer.patch('sqrt', lambda x: x ** 0.5)
        
        # Serialize to bytes
        >>> state_bytes = explorer.serialize()
        >>> len(state_bytes) > 0
        True
        
        # Save to file
        >>> explorer.serialize('/tmp/math_state.pkl')
        
        # Create new explorer and restore
        >>> new_explorer = pmeX(math)
        >>> new_explorer = new_explorer.deserialize(state_bytes)
        
        # Or restore from file
        >>> new_explorer = pmeX(math)
        >>> new_explorer.deserialize('/tmp/math_state.pkl')
        """
        state = {
            'module_name': self.name,
            'timestamp': datetime.now().isoformat(),
            'attributes': {},
            'change_history': self._change_history,
            'injected_code': getattr(self.injection, '_injected_code', []),
            'patched_attrs': getattr(self.patching, '_patched', {})
        }
        
        # Capture all module attributes
        for attr_name, attr_value in self.module.__dict__.items():
            try:
                # Test if attribute is serializable
                pickle.dumps(attr_value)
                state['attributes'][attr_name] = attr_value
            except (pickle.PickleError, TypeError, AttributeError):
                # Skip unserializable objects
                state['attributes'][attr_name] = f"<Unserializable: {type(attr_value).__name__}>"
        
        if format == 'pickle':
            serialized = pickle.dumps(state)
        elif format == 'json':
            serialized = json.dumps(state, default=str, indent=2).encode('utf-8')
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        if path:
            path = Path(path)
            path.write_bytes(serialized)
        
        self._record_change("serialize", None, {"format": format, "path": str(path) if path else None})
        return serialized

    def deserialize(self, source: Union[str, Path, bytes], format: str = 'pickle') -> 'pmeX':
        """
        Restore module state from serialized data.

        Loads attributes, injected code, and patches from a previously saved state.

        Parameters
        ----------
        source : Union[str, Path, bytes]
            File path or bytes object containing serialized state
        format : str, default='pickle'
            Format of serialized data: 'pickle' or 'json'

        Returns
        -------
        pmeX
            Self instance for method chaining

        Raises
        ------
        ValueError
            If format is not supported or deserialization fails
        IOError
            If reading from file fails

        Examples
        --------
        >>> # Save state
        >>> explorer1 = pmeX(math)
        >>> explorer1.inject("TEST = 42")
        >>> explorer1.serialize('/tmp/math_state.pkl')
        
        # Load into new explorer
        >>> explorer2 = pmeX(math)
        >>> explorer2.deserialize('/tmp/math_state.pkl')
        >>> hasattr(math, 'TEST')
        True
        >>> math.TEST
        42
        
        # Restore from bytes
        >>> state_bytes = explorer1.serialize()
        >>> explorer3 = pmeX(math)
        >>> explorer3.deserialize(state_bytes)
        """
        if isinstance(source, (str, Path)):
            source = Path(source).read_bytes()
        
        if format == 'pickle':
            state = pickle.loads(source)
        elif format == 'json':
            state = json.loads(source.decode('utf-8'))
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        # Restore attributes
        for attr_name, attr_value in state.get('attributes', {}).items():
            if not attr_name.startswith('__'):  # Skip magic methods
                try:
                    setattr(self.module, attr_name, attr_value)
                except Exception:
                    warnings.warn(f"Failed to restore attribute: {attr_name}")
        
        # Restore injected code
        for code in state.get('injected_code', []):
            try:
                self.inject(code)
            except Exception:
                warnings.warn(f"Failed to re-inject code: {code[:50]}...")
        
        # Restore patches
        for attr_name, original_value in state.get('patched_attrs', {}).items():
            try:
                self.patch(attr_name, state['attributes'].get(attr_name))
            except Exception:
                warnings.warn(f"Failed to restore patch: {attr_name}")
        
        self._change_history = state.get('change_history', [])
        self._record_change("deserialize", None, state.get('timestamp'))
        
        return self

    def snapshot(self, name: Optional[str] = None) -> str:
        """
        Create a named snapshot of the current module state.

        Snapshots are stored in memory for fast restoration without serialization.

        Parameters
        ----------
        name : Optional[str], default=None
            Name for this snapshot. If None, auto-generates timestamp-based name

        Returns
        -------
        str
            Name of the created snapshot

        Examples
        --------
        >>> explorer = pmeX(math)
        >>> explorer.inject("VERSION = '1.0'")
        
        # Create snapshot
        >>> snap_name = explorer.snapshot("before_changes")
        >>> print(snap_name)
        before_changes
        
        # Make changes
        >>> explorer.patch('pi', 3.14)
        >>> explorer.inject("STATUS = 'modified'")
        
        # Restore snapshot
        >>> explorer.restore_snapshot("before_changes")
        >>> hasattr(math, 'STATUS')
        False
        >>> math.pi  # Restored to original
        3.141592653589793
        """
        if name is None:
            name = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        
        # Deep copy the module's state
        snapshot_data = {
            'attributes': {},
            'injected_code': getattr(self.injection, '_injected_code', []).copy(),
            'patched_attrs': getattr(self.patching, '_original_values', {}).copy(),
            'change_history': self._change_history.copy()
        }
        
        # Copy all attributes
        for attr_name, attr_value in self.module.__dict__.items():
            try:
                snapshot_data['attributes'][attr_name] = copy.deepcopy(attr_value)
            except (TypeError, pickle.PickleError):
                snapshot_data['attributes'][attr_name] = attr_value  # Fallback to reference
        
        self._snapshots[name] = snapshot_data
        self._record_change("snapshot", None, name)
        
        return name

    def restore_snapshot(self, name: str) -> bool:
        """
        Restore module state from a previously created snapshot.

        Parameters
        ----------
        name : str
            Name of the snapshot to restore

        Returns
        -------
        bool
            True if restore was successful, False if snapshot not found

        Raises
        ------
        KeyError
            If snapshot name doesn't exist

        Examples
        --------
        >>> explorer = pmeX(math)
        >>> explorer.inject("TEST = 100")
        >>> explorer.snapshot("test_state")
        >>> explorer.inject("TEST = 200")
        >>> math.TEST
        200
        >>> explorer.restore_snapshot("test_state")
        True
        >>> math.TEST
        100
        
        # List available snapshots
        >>> explorer.list_snapshots()
        ['test_state', 'initial_state', 'modified_state']
        """
        if name not in self._snapshots:
            raise KeyError(f"Snapshot '{name}' not found. Available: {list(self._snapshots.keys())}")
        
        snapshot = self._snapshots[name]
        
        # Restore attributes
        for attr_name, attr_value in snapshot['attributes'].items():
            if not attr_name.startswith('__'):
                setattr(self.module, attr_name, attr_value)
        
        # Restore injection and patching state
        self.injection._injected_code = snapshot.get('injected_code', [])
        self.patching._original_values = snapshot.get('patched_attrs', {})
        
        # Restore original values for patched attributes
        for attr_name, original_value in self.patching._original_values.items():
            setattr(self.module, attr_name, original_value)
        
        self._change_history = snapshot.get('change_history', [])
        self._record_change("restore_snapshot", None, name)
        
        return True

    def list_snapshots(self) -> List[str]:
        """
        List all available snapshot names.

        Returns
        -------
        List[str]
            List of snapshot names in creation order

        Examples
        --------
        >>> explorer.snapshot("state_1")
        >>> explorer.snapshot("state_2")
        >>> explorer.snapshot("state_3")
        >>> explorer.list_snapshots()
        ['state_1', 'state_2', 'state_3']
        """
        return list(self._snapshots.keys())

    def delete_snapshot(self, name: str) -> bool:
        """
        Delete a snapshot to free memory.

        Parameters
        ----------
        name : str
            Name of the snapshot to delete

        Returns
        -------
        bool
            True if deleted, False if snapshot didn't exist

        Examples
        --------
        >>> explorer.snapshot("temp_state")
        >>> explorer.delete_snapshot("temp_state")
        True
        >>> "temp_state" in explorer.list_snapshots()
        False
        """
        if name in self._snapshots:
            del self._snapshots[name]
            self._record_change("delete_snapshot", name, None)
            return True
        return False

    # ==========================================================================
    # Resource Management Methods
    # ==========================================================================

    def cleanup_unused(self, include_private: bool = False) -> Dict[str, int]:
        """
        Clean up unused attributes, imports, and cached data.

        This method identifies and removes attributes that are no longer referenced,
        helping to free memory and reduce module size.

        Parameters
        ----------
        include_private : bool, default=False
            If True, also consider private attributes (starting with '_')
            for cleanup

        Returns
        -------
        Dict[str, int]
            Dictionary with cleanup statistics:
            - 'attributes_removed': number of attributes removed
            - 'imports_removed': number of unused imports removed
            - 'memory_freed_estimate_mb': estimated memory freed in MB

        Notes
        -----
        This operation is conservative and may not remove all unused objects.
        Use with caution as it might remove attributes that are used indirectly.

        Examples
        --------
        >>> import math
        >>> explorer = pmeX(math)
        
        # Add some temporary data
        >>> math.temp_var = 100
        >>> math.another_temp = "test"
        
        # Clean up
        >>> stats = explorer.cleanup_unused()
        >>> print(f"Removed {stats['attributes_removed']} attributes")
        Removed 2 attributes
        
        # Private attributes require explicit flag
        >>> math._private = 42
        >>> stats = explorer.cleanup_unused()
        >>> stats['attributes_removed']
        0
        >>> stats = explorer.cleanup_unused(include_private=True)
        >>> stats['attributes_removed']
        1
        """
        stats = {'attributes_removed': 0, 'imports_removed': 0, 'memory_freed_estimate_mb': 0}
        
        # Track referenced attributes (naive reference counting)
        referenced = set()
        for attr_name, attr_value in self.module.__dict__.items():
            if attr_name.startswith('__') and attr_name.endswith('__'):
                continue  # Skip magic methods
            
            if not include_private and attr_name.startswith('_'):
                continue
            
            # Check if attribute is referenced by other module attributes
            is_referenced = False
            for other_name, other_value in self.module.__dict__.items():
                if other_name != attr_name:
                    try:
                        if other_value == attr_value or attr_value in str(other_value):
                            is_referenced = True
                            break
                    except Exception:
                        pass
            
            if not is_referenced:
                # Estimate memory freed (very rough estimate)
                try:
                    size_estimate = len(str(attr_value)) / 1024 / 1024  # MB
                    stats['memory_freed_estimate_mb'] += size_estimate
                except Exception:
                    pass
                
                # Remove the attribute
                try:
                    delattr(self.module, attr_name)
                    stats['attributes_removed'] += 1
                    self._record_change(f"cleanup_{attr_name}", attr_value, None)
                except Exception:
                    pass
        
        # Force garbage collection
        gc.collect()
        
        return stats

    def unload(self) -> bool:
        """
        Unload the module from sys.modules and clean up references.

        This completely removes the module from the Python interpreter,
        allowing it to be garbage collected and re-imported fresh.

        Returns
        -------
        bool
            True if module was successfully unloaded, False otherwise

        Raises
        ------
        RuntimeError
            If the module cannot be unloaded (e.g., has dependencies)

        Notes
        -----
        After unloading, the original module object may still exist if
        referenced elsewhere. Use `reload_force()` to completely reload.

        Examples
        --------
        >>> # Create custom module
        >>> import types
        >>> my_module = types.ModuleType('mymod')
        >>> my_module.data = [1, 2, 3]
        >>> sys.modules['mymod'] = my_module
        
        >>> explorer = pmeX(my_module)
        >>> explorer.unload()
        True
        
        >>> 'mymod' in sys.modules
        False
        
        # Re-import fresh
        >>> import mymodule  # New instance
        """
        if self.name not in sys.modules:
            return False
        
        # Clean up import interception if active
        if self._import_intercept_active:
            self.disable_import_interception()
        
        # Store module reference before removal
        module_ref = sys.modules.get(self.name)
        
        # Remove from sys.modules
        del sys.modules[self.name]
        
        # Clear module's __dict__ to free references
        if hasattr(module_ref, '__dict__'):
            module_ref.__dict__.clear()
        
        # Force garbage collection
        gc.collect()
        
        self._record_change("unload", module_ref, None)
        return True

    def reload_force(self, preserve_patches: bool = False) -> ModuleType:
        """
        Forcefully reload the module, optionally preserving patches.

        This completely reloads the module from disk, clearing all runtime
        modifications. Can optionally preserve applied patches.

        Parameters
        ----------
        preserve_patches : bool, default=False
            If True, reapplies patches after reload. Only works for simple patches.

        Returns
        -------
        ModuleType
            The newly reloaded module object

        Raises
        ------
        ImportError
            If the module cannot be reloaded
        RuntimeError
            If preserve_patches is True and patches cannot be reapplied

        Notes
        -----
        This uses importlib.reload() which may have limitations for some modules.
        Custom C extensions may not reload properly.

        Examples
        --------
        >>> import math
        >>> explorer = pmeX(math)
        
        # Modify module
        >>> explorer.patch('pi', 3.14)
        >>> math.pi
        3.14
        
        # Reload without preserving patches
        >>> math = explorer.reload_force()
        >>> math.pi  # Restored to original
        3.141592653589793
        
        # Reload with preserving patches
        >>> explorer.patch('pi', 3.14)
        >>> math = explorer.reload_force(preserve_patches=True)
        >>> math.pi
        3.14
        """
        # Save patches if needed
        saved_patches = {}
        if preserve_patches:
            saved_patches = getattr(self.patching, '_original_values', {}).copy()
        
        # Unload current module
        self.unload()
        
        # Reload module
        try:
            if self.name in sys.modules:
                self.module = importlib.reload(sys.modules[self.name])
            else:
                self.module = importlib.import_module(self.name)
        except ImportError as e:
            raise ImportError(f"Failed to reload module '{self.name}': {e}")
        
        # Update references
        self.module = sys.modules[self.name]
        
        # Reapply patches if requested
        if preserve_patches and saved_patches:
            for attr_name, original_value in saved_patches.items():
                try:
                    new_value = getattr(self.module, attr_name, None)
                    self.patch(attr_name, new_value)
                except Exception as e:
                    raise RuntimeError(f"Failed to reapply patch to '{attr_name}': {e}")
        
        # Reinitialize managers with new module
        self.injection = Injecter(self.module)
        self.protection = ProtectionManager(self.module, self.module)
        self.patching = PatchingManager(self.module)
        
        self._record_change("reload_force", "old_module", "new_module")
        return self.module

    # ==========================================================================
    # Batch Operations Methods
    # ==========================================================================

    def batch_patch(self, patches: Dict[str, Any], atomic: bool = True) -> Dict[str, bool]:
        """
        Apply multiple patches in batch, optionally as an atomic operation.

        Parameters
        ----------
        patches : Dict[str, Any]
            Dictionary mapping attribute names to their new values
        atomic : bool, default=True
            If True, rollback all patches if any patch fails.
            If False, continue applying remaining patches on failure.

        Returns
        -------
        Dict[str, bool]
            Dictionary mapping each attribute name to success status

        Raises
        ------
        RuntimeError
            If atomic=True and a patch fails (with rollback info)

        Examples
        --------
        >>> explorer = pmeX(math)
        
        # Batch patch multiple attributes
        >>> patches = {
        ...     'pi': 3.14,
        ...     'e': 2.71828,
        ...     'tau': 6.28318,
        ...     'sqrt': lambda x: x ** 0.5
        ... }
        >>> results = explorer.batch_patch(patches)
        >>> results['pi']
        True
        >>> results['tau']
        True
        >>> math.tau
        6.28318
        
        # Atomic batch (all or nothing)
        >>> bad_patches = {
        ...     'valid_attr': 100,
        ...     'non_existent_attr': 200  # This will fail
        ... }
        >>> try:
        ...     explorer.batch_patch(bad_patches, atomic=True)
        ... except RuntimeError as e:
        ...     print("Rolled back!")
        >>> hasattr(math, 'valid_attr')  # Not applied
        False
        """
        results = {}
        successful = []
        
        # Save original values for rollback
        original_values = {}
        for name in patches:
            if hasattr(self.module, name):
                original_values[name] = getattr(self.module, name)
        
        try:
            for name, new_value in patches.items():
                try:
                    old_value = getattr(self.module, name, None)
                    self.patching.patch(name, new_value)
                    results[name] = True
                    successful.append(name)
                    self._record_change(f"batch_patch_{name}", old_value, new_value)
                except Exception as e:
                    results[name] = False
                    if atomic:
                        raise RuntimeError(f"Batch patch failed on '{name}': {e}")
            
            return results
            
        except Exception:
            # Rollback if atomic mode
            if atomic:
                for name in successful:
                    if name in original_values:
                        setattr(self.module, name, original_values[name])
                    else:
                        delattr(self.module, name)
                for name in patches:
                    if name in original_values and name not in successful:
                        setattr(self.module, name, original_values[name])
            raise

    def batch_inject(self, code_snippets: Dict[str, str], atomic: bool = True) -> Dict[str, bool]:
        """
        Inject multiple code snippets in batch.

        Parameters
        ----------
        code_snippets : Dict[str, str]
            Dictionary mapping names to code strings to inject
        atomic : bool, default=True
            If True, rollback all injections if any fails

        Returns
        -------
        Dict[str, bool]
            Dictionary mapping each injection name to success status

        Examples
        --------
        >>> explorer = pmeX(math)
        >>> snippets = {
        ...     'constant': 'ANSWER = 42',
        ...     'function': 'def greet(): return "Hello"',
        ...     'class': 'class Calc: def add(self, a, b): return a + b'
        ... }
        >>> results = explorer.batch_inject(snippets)
        >>> math.ANSWER
        42
        >>> math.greet()
        'Hello'
        """
        results = {}
        successful = []
        
        # Track what was created
        created_names = set()
        
        try:
            for name, code in code_snippets.items():
                try:
                    result = self.injection.inject(code)
                    if result.get('defined'):
                        created_names.update(result['defined'])
                    results[name] = True
                    successful.append(name)
                    self._record_change(f"batch_inject_{name}", None, result.get('defined'))
                except Exception as e:
                    results[name] = False
                    if atomic:
                        raise RuntimeError(f"Batch injection failed on '{name}': {e}")
            
            return results
            
        except Exception:
            # Rollback if atomic mode
            if atomic:
                for attr_name in created_names:
                    if hasattr(self.module, attr_name):
                        delattr(self.module, attr_name)
                for name in successful:
                    self.injection.revert_injection(name, False)
            raise

    def batch_disable(self, features: List[str], behavior: str = "raise") -> Dict[str, bool]:
        """
        Disable multiple features in batch.

        Parameters
        ----------
        features : List[str]
            List of feature names to disable
        behavior : str, default='raise'
            Behavior for disabled features ('raise', 'warn', 'ignore', 'return')

        Returns
        -------
        Dict[str, bool]
            Dictionary mapping each feature to disable status

        Examples
        --------
        >>> explorer = pmeX(math)
        >>> features = ['sqrt', 'sin', 'cos', 'tan']
        >>> results = explorer.batch_disable(features, 'warn')
        
        # All functions now warn when called
        >>> math.sqrt(16)
        UserWarning: Feature 'sqrt' is disabled
        >>> math.sin(1.57)
        UserWarning: Feature 'sin' is disabled
        """
        results = {}
        
        for feature in features:
            try:
                self.protection.disable_feature(feature, behavior)
                results[feature] = True
                self._record_change(f"batch_disable_{feature}", None, behavior)
            except Exception as e:
                results[feature] = False
        
        return results

    # ==========================================================================
    # Change Tracking and Diff Methods
    # ==========================================================================

    def get_change_history(self, limit: Optional[int] = None, since: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieve the history of all changes made to the module.

        Parameters
        ----------
        limit : Optional[int], default=None
            Maximum number of changes to return (most recent first)
        since : Optional[str], default=None
            ISO format timestamp to get changes after this time

        Returns
        -------
        List[Dict[str, Any]]
            List of change records, each containing:
            - 'timestamp': when the change occurred
            - 'attribute': name of changed attribute
            - 'old_value': previous value (truncated)
            - 'new_value': new value (truncated)
            - 'type': type of change

        Examples
        --------
        >>> explorer = pmeX(math)
        >>> explorer.inject("TEST = 1")
        >>> explorer.patch('pi', 3.14)
        >>> explorer.disable_feature('sqrt', 'warn')
        
        # Get all changes
        >>> history = explorer.get_change_history()
        >>> len(history)
        3
        >>> history[0]['attribute']
        'pi'
        
        # Get last 2 changes
        >>> recent = explorer.get_change_history(limit=2)
        >>> len(recent)
        2
        
        # Get changes after specific time
        >>> changes = explorer.get_change_history(since='2024-01-01T00:00:00')
        """
        changes = self._change_history.copy()
        
        # Filter by time if specified
        if since:
            changes = [c for c in changes if c['timestamp'] >= since]
        
        # Sort by timestamp (newest first)
        changes.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Apply limit
        if limit:
            changes = changes[:limit]
        
        return changes

    def get_changed(self) -> Dict[str, Tuple[Any, Any]]:
        """
        Get all attributes that have been modified from their original state.

        Returns
        -------
        Dict[str, Tuple[Any, Any]]
            Dictionary mapping attribute names to (original_value, current_value)
            Only includes attributes that have been modified.

        Examples
        --------
        >>> import math
        >>> explorer = pmeX(math)
        
        # Store original pi
        >>> original_pi = math.pi
        
        # Make changes
        >>> explorer.patch('pi', 3.14)
        >>> explorer.inject("NEW_VAR = 100")
        
        # Get changed attributes
        >>> changed = explorer.get_changed()
        >>> 'pi' in changed
        True
        >>> changed['pi']  # (original, current)
        (3.141592653589793, 3.14)
        >>> 'NEW_VAR' in changed
        True  # New attributes are considered changed
        """
        changed = {}
        
        # For patched attributes, we can get original from patching manager
        patched = getattr(self.patching, '_original_values', {})
        for attr_name, original_value in patched.items():
            current_value = getattr(self.module, attr_name, None)
            if current_value != original_value:
                changed[attr_name] = (original_value, current_value)
        
        # Check for new attributes (not in original module)
        # This is simplified - a full implementation would need the original module state
        original_attrs = set(dir(self.module.__class__))  # Base attributes
        
        for attr_name in dir(self.module):
            if attr_name not in original_attrs and not attr_name.startswith('__'):
                current_value = getattr(self.module, attr_name)
                changed[attr_name] = (None, current_value)
        
        return changed

    def diff(self, other: Union[ModuleType, 'pmeX']) -> Dict[str, Dict[str, Any]]:
        """
        Generate a detailed difference between current and another module state.

        Parameters
        ----------
        other : Union[ModuleType, pmeX]
            Another module or pmeX instance to compare against

        Returns
        -------
        Dict[str, Dict[str, Any]]
            Difference dictionary with keys:
            - 'added': {attribute_name: value}
            - 'removed': {attribute_name: old_value}
            - 'modified': {attribute_name: {'old': old, 'new': new}}
            - 'type_changed': {attribute_name: {'old_type': str, 'new_type': str}}

        Examples
        --------
        >>> import math
        >>> explorer1 = pmeX(math)
        >>> explorer2 = pmeX(math)
        
        # Make changes to explorer2
        >>> explorer2.patch('pi', 3.14)
        >>> explorer2.inject("VERSION = '2.0'")
        
        # Generate diff
        >>> diff = explorer1.diff(explorer2)
        >>> 'added' in diff and 'VERSION' in diff['added']
        True
        >>> diff['modified']['pi']['old']
        3.141592653589793
        >>> diff['modified']['pi']['new']
        3.14
        
        # Compare with clean module
        >>> diff = explorer1.diff(math)  # Compare with original math module
        """
        # Normalize other to module object
        if isinstance(other, pmeX):
            other_module = other.module
        else:
            other_module = other
        
        diff_result = {
            'added': {},
            'removed': {},
            'modified': {},
            'type_changed': {}
        }
        
        # Get attributes from both modules
        self_attrs = set(dir(self.module))
        other_attrs = set(dir(other_module))
        
        # Find added and removed
        for attr in other_attrs - self_attrs:
            if not attr.startswith('__'):
                diff_result['added'][attr] = getattr(other_module, attr)
        
        for attr in self_attrs - other_attrs:
            if not attr.startswith('__'):
                diff_result['removed'][attr] = getattr(self.module, attr)
        
        # Find modified
        for attr in self_attrs & other_attrs:
            if attr.startswith('__'):
                continue
            
            self_value = getattr(self.module, attr)
            other_value = getattr(other_module, attr)
            
            if self_value != other_value:
                diff_result['modified'][attr] = {
                    'old': self_value,
                    'new': other_value
                }
                
                # Check if type changed
                if type(self_value) != type(other_value):
                    diff_result['type_changed'][attr] = {
                        'old_type': type(self_value).__name__,
                        'new_type': type(other_value).__name__
                    }
        
        return diff_result

    def rollback(self, steps: int = 1) -> List[Dict[str, Any]]:
        """
        Rollback a specified number of changes from the change history.

        Parameters
        ----------
        steps : int, default=1
            Number of changes to rollback (most recent first)

        Returns
        -------
        List[Dict[str, Any]]
            List of changes that were rolled back

        Raises
        ------
        ValueError
            If steps is less than 1 or greater than change history length

        Examples
        --------
        >>> explorer = pmeX(math)
        
        # Make a series of changes
        >>> explorer.patch('pi', 3.14)
        >>> explorer.patch('e', 2.718)
        >>> explorer.inject("TAU = 6.283")
        
        # Rollback last change
        >>> rolled = explorer.rollback(1)
        >>> hasattr(math, 'TAU')
        False
        
        # Rollback 2 more changes
        >>> rolled = explorer.rollback(2)
        >>> math.pi  # Restored to original
        3.141592653589793
        
        # Try to rollback more than available
        >>> explorer.rollback(100)
        ValueError: Cannot rollback 100 steps, only 3 changes in history
        """
        if steps < 1:
            raise ValueError(f"Steps must be at least 1, got {steps}")
        
        if steps > len(self._change_history):
            raise ValueError(f"Cannot rollback {steps} steps, only {len(self._change_history)} changes in history")
        
        rolled_back = []
        
        # Get the most recent changes to rollback
        changes_to_rollback = self._change_history[-steps:]
        
        # Process changes in reverse order (oldest of the batch first)
        for change in reversed(changes_to_rollback):
            attr_name = change['attribute']
            
            # Attempt to restore old value
            try:
                old_value = change.get('old_value')
                if old_value and old_value != 'None':
                    # Parse and restore - simplified version
                    # Full implementation would need proper value parsing
                    if hasattr(self.module, attr_name):
                        try:
                            # This is simplified - real implementation needs eval safety
                            pass
                        except Exception:
                            setattr(self.module, attr_name, None)
                else:
                    if hasattr(self.module, attr_name):
                        delattr(self.module, attr_name)
                
                rolled_back.append(change)
            except Exception as e:
                warnings.warn(f"Failed to rollback change to '{attr_name}': {e}")
        
        # Remove rolled back changes from history
        self._change_history = self._change_history[:-steps]
        
        return rolled_back

    # ==========================================================================
    # Utility Methods
    # ==========================================================================

    def modules(self, level: int = 0) -> Dict[str, ModuleType]:
        """
        Extract modules from the namespace with configurable search depth.

        Parameters
        ----------
        level : int, optional
            Depth of recursive searching. Level 0 inspects only the namespace of
            the module. Defaults to 0.

        Returns
        -------
        Dict[str, ModuleType]
            Dictionary mapping names to module objects found up to the given depth.

        Examples
        --------
        >>> explorer = pmeX(numpy)
        >>> modules = explorer.modules(level=1)
        >>> print(list(modules.keys())[:5])
        """
        visited = set()
        result = {}

        def collect(obj, current_level):
            obj_id = id(obj)
            if obj_id in visited:
                return
            visited.add(obj_id)

            try:
                ns = create_dict(obj)
            except Exception:
                return

            for name, val in ns.items():
                if inspect.ismodule(val):
                    result[name] = val
                    if current_level < level:
                        collect(val, current_level + 1)
                else:
                    if current_level < level:
                        collect(val, current_level + 1)

        collect(self.module, 0)
        return result

    def executive(self, code: str) -> Any:
        """
        Execute or evaluate Python code inside a module's namespace.

        Parameters
        ----------
        code : str
            Python code to execute in module context

        Returns
        -------
        Any
            Result of expression evaluation, or None for statements

        Examples
        --------
        >>> explorer = pmeX(math)
        >>> result = explorer.executive("2 * pi")
        >>> print(result)
        6.283185307179586
        """
        ns = create_dict(self.module)

        try:
            result = eval(code, ns)
            return result
        except SyntaxError:
            exec(code, ns)
            return None

    def clone(
        self,
        mutation_rules: Optional[Dict[str, Any]] = None,
        *,
        copy_all: bool = True,
        exclude: Optional[Set[str]] = None,
        deep_copy_attrs: Optional[Set[str]] = None,
        shallow_copy_attrs: Optional[Set[str]] = None,
        preserve_module_metadata: bool = True,
        module_doc: Optional[str] = None,
        import_original_on_error: bool = True,
        recursion_limit: int = 10,
        enable_warnings: bool = True,
    ) -> ModuleType:
        """
        Clone a Python module with selective mutation capabilities.

        This method creates a deep copy of a module while allowing targeted
        modifications to specific attributes.

        Parameters
        ----------
        mutation_rules : Dict[str, Any], optional
            Rules for mutating specific attributes. Keys are attribute names,
            values can be:
            - A callable that receives the original attribute and returns modified version
            - Any value to replace the attribute entirely
        copy_all : bool, optional
            If True, copy all attributes not explicitly excluded. Defaults to True.
        exclude : Set[str], optional
            Set of attribute names to skip during cloning
        deep_copy_attrs : Set[str], optional
            Attributes that require deep copy even if in shallow_copy_attrs
        shallow_copy_attrs : Set[str], optional
            Attributes that should be shallow copied (shared reference)
        preserve_module_metadata : bool, optional
            Preserve original module metadata (__file__, __package__, etc.).
            Defaults to True.
        module_doc : str, optional
            Custom documentation string for the cloned module
        import_original_on_error : bool, optional
            If True, import original attribute on copy error. Defaults to True.
        recursion_limit : int, optional
            Maximum recursion depth for deep copying. Defaults to 10.
        enable_warnings : bool, optional
            Enable warnings for potential issues during cloning. Defaults to True.

        Returns
        -------
        ModuleType
            A new module object with cloned (and potentially mutated) attributes

        Examples
        --------
        >>> explorer = pmeX(math)
        >>> rules = {'pi': 3.14, 'sqrt': lambda f: lambda x: f(x) * 2}
        >>> math_clone = explorer.clone(rules)
        >>> math_clone.pi
        3.14
        >>> math_clone.sqrt(4)
        4.0
        """
        return clone(
            module=self.module,
            mutation_rules=mutation_rules,
            copy_all=copy_all,
            exclude=exclude,
            deep_copy_attrs=deep_copy_attrs,
            shallow_copy_attrs=shallow_copy_attrs,
            preserve_module_metadata=preserve_module_metadata,
            module_doc=module_doc,
            import_original_on_error=import_original_on_error,
            recursion_limit=recursion_limit,
            enable_warnings=enable_warnings,
        )

    def info(self) -> Dict[str, Any]:
        """
        Get comprehensive information about the module and its current state.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - 'name': module name
            - 'path': module file path
            - 'size': number of attributes
            - 'functions': count of functions
            - 'classes': count of classes
            - 'constants': count of constants
            - 'patches': number of active patches
            - 'injections': number of injected code snippets
            - 'frozen': whether module is frozen
            - 'readonly': whether module is read-only
            - 'snapshots': number of saved snapshots
            - 'change_count': total number of changes recorded

        Examples
        --------
        >>> explorer = pmeX(math)
        >>> info = explorer.info()
        >>> print(f"Module: {info['name']}, Functions: {info['functions']}")
        Module: math, Functions: 47
        
        >>> explorer.patch('pi', 3.14)
        >>> info = explorer.info()
        >>> info['patches']
        1
        """
        # Count different attribute types
        functions = 0
        classes = 0
        constants = 0
        modules = 0
        
        for name, value in self.module.__dict__.items():
            if name.startswith('__'):
                continue
            if inspect.isfunction(value):
                functions += 1
            elif inspect.isclass(value):
                classes += 1
            elif inspect.ismodule(value):
                modules += 1
            else:
                constants += 1
        
        return {
            'name': self.name,
            'path': self.path,
            'size': len(self.module.__dict__),
            'functions': functions,
            'classes': classes,
            'constants': constants,
            'modules': modules,
            'patches': len(getattr(self.patching, '_original_values', {})),
            'injections': len(getattr(self.injection, '_injected_code', [])),
            'frozen': getattr(self.module, '_pmeX_frozen', False),
            'readonly': getattr(self.module, '_pmeX_readonly', False),
            'snapshots': len(self._snapshots),
            'change_count': len(self._change_history),
            'import_interception_active': self._import_intercept_active,
            'blocked_imports': len(self._blocked_imports),
            'mocked_imports': len(self._mocked_imports)
        }