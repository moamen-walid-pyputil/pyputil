#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
AST validation for secure module execution.
"""

import ast
from typing import Dict, List, Set
from .dataclasses import ModuleConfig
from .enums import ModulePolicy


class _ASTValidator(ast.NodeVisitor):
    """
    Validate AST nodes against security policies.

    Visits AST nodes and checks for forbidden constructs
    and unsafe operations based on configuration.

    Parameters
    ----------
    config : ModuleConfig
        Configuration defining what is allowed.

    Attributes
    ----------
    FORBIDDEN_NODES : Dict[type, str]
        Mapping of forbidden AST node types to error messages.
    imports_found : List[str]
        List of import statements found during validation.
    unsafe_calls : List[str]
        List of unsafe function calls found during validation.

    Raises
    ------
    SyntaxError
        When forbidden AST nodes are found.
    ImportError
        When unauthorized imports are attempted.

    Examples
    --------
    >>> validator = _ASTValidator(config)
    >>> validator.visit(ast.parse("import os"))
    """

    FORBIDDEN_NODES: Dict[type, str] = {
        ast.Delete: "Deletion operations are not allowed",
        ast.Global: "Global statements are not allowed",
        ast.Nonlocal: "Nonlocal statements are not allowed",
        ast.Lambda: "Lambda expressions are not allowed",
        ast.Yield: "Yield expressions are not allowed",
        ast.YieldFrom: "Yield from expressions are not allowed",
        ast.AsyncFunctionDef: "Async functions are not allowed",
        ast.AsyncFor: "Async for loops are not allowed",
        ast.AsyncWith: "Async with statements are not allowed",
        ast.Await: "Await expressions are not allowed",
        ast.Try: "Try-except blocks are not allowed",
        ast.Assert: "Assert statements are not allowed",
    }

    def __init__(self, config: ModuleConfig):
        """
        Initialize AST validator.

        Parameters
        ----------
        config : ModuleConfig
            Security configuration.
        """
        self.config = config
        self.imports_found: List[str] = []
        self.unsafe_calls: List[str] = []

    def visit(self, node: ast.AST) -> None:
        """
        Visit an AST node and validate it.

        Parameters
        ----------
        node : ast.AST
            AST node to validate.

        Returns
        -------
        None

        Raises
        ------
        SyntaxError
            If node type is in FORBIDDEN_NODES.
        """
        if type(node) in self.FORBIDDEN_NODES:
            raise SyntaxError(f"Security violation: {self.FORBIDDEN_NODES[type(node)]}")

        # Check specific node types
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            self._check_import(node)
        elif isinstance(node, ast.Call):
            self._check_call(node)
        elif isinstance(node, ast.Attribute):
            self._check_attribute(node)

        # Continue visiting child nodes
        return self.generic_visit(node)

    def _check_import(self, node: ast.AST) -> None:
        """
        Check if import statements are allowed.

        Parameters
        ----------
        node : ast.Import or ast.ImportFrom
            Import node to validate.

        Raises
        ------
        SyntaxError
            If imports are disabled.
        ImportError
            If module is not in allowed_modules.
        """
        # Check if imports are allowed
        if ModulePolicy.ALLOW_IMPORTS not in self.config.policies:
            raise SyntaxError("Imports are disabled in this module")

        # Extract import names
        if isinstance(node, ast.Import):
            names = [n.name for n in node.names]
        else:  # ImportFrom
            module_name = node.module or ""
            names = [f"{module_name}.{n.name}" for n in node.names]

        # Track found imports
        self.imports_found.extend(names)

        # Check against allowed modules
        if self.config.allowed_modules:
            for name in names:
                if name not in self.config.allowed_modules:
                    raise ImportError(f"Module '{name}' is not allowed")

    def _check_call(self, node: ast.Call) -> None:
        """
        Check function calls for unsafe functions.

        Parameters
        ----------
        node : ast.Call
            Function call node to validate.

        Raises
        ------
        SyntaxError
            If unsafe function is called and reflection is not allowed.
        """
        if isinstance(node.func, ast.Name):
            func_name = node.func.id

            # Define unsafe functions
            unsafe_functions = {
                "eval",
                "exec",
                "compile",
                "open",
                "input",
                "__import__",
                "exit",
                "quit",
                "globals",
                "locals",
                "getattr",
                "setattr",
                "delattr",
                "hasattr",
                "memoryview",
                "bytearray",
                "bytes",
            }

            # Check if function is unsafe
            if func_name in unsafe_functions:
                self.unsafe_calls.append(func_name)

                # Check if reflection is allowed
                if ModulePolicy.ALLOW_REFLECTION not in self.config.policies:
                    raise SyntaxError(f"Unsafe function call: {func_name}")

    def _check_attribute(self, node: ast.Attribute) -> None:
        """
        Check attribute access for protected attributes.

        Parameters
        ----------
        node : ast.Attribute
            Attribute access node to validate.

        Raises
        ------
        AttributeError
            If accessing protected attributes like __builtins__.
        """
        if isinstance(node.value, ast.Name):
            # Check for protected attributes
            obj_name = node.value.id
            protected_attributes = {"__builtins__", "__dict__", "__code__"}

            if node.attr.startswith("_") and obj_name in protected_attributes:
                raise AttributeError(f"Access to protected attribute: {node.attr}")
