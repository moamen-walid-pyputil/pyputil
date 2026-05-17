#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import ast
from typing import Any, Optional, Union, List, Dict


class Signature:
    """
    Attributes:
        body (str): The original source code string
        _tree (ast.AST): The parsed AST tree
        _nodes (list): Flattened list of all AST nodes

    Example:
        >>> # Function example
        >>> func_code = 'def greet(name: str, age: int = 20) -> str: pass'
        >>> sig = Signature(func_code)
        >>> print(sig.signature())
        {
            'name': 'greet',
            'type': 'function',
            'parameters': ['name', 'age'],
            'annotations': {'name': 'str', 'age': 'int', 'return': 'str'},
            'defaults': {'age': 20}
        }

        >>> # Class example
        >>> class_code = '''
        ... class Person:
        ...     def __init__(self, name: str, age: int = 20):
        ...         self.name = name
        ...         self.age = age
        ... '''
        >>> sig = Signature(class_code)
        >>> print(sig.signature())
        {
            'name': 'Person',
            'type': 'class',
            'parameters': ['self', 'name', 'age'],
            'annotations': {'name': 'str', 'age': 'int'},
            'defaults': {'age': 20}
        }
    """

    def __init__(self, defbody: str) -> None:
        """
        Initialize the Signature analyzer with source code.

        Args:
            defbody (str): Python source code containing a function, async function, or class definition

        Raises:
            TypeError: If defbody is not a string
            SyntaxError: If the source code contains syntax errors
            ValueError: If no valid function or class definition is found
        """
        if not isinstance(defbody, str):
            raise TypeError(
                f"Expected 'defbody' to be a string, got {type(defbody).__name__}"
            )

        self.body = defbody.strip()

        try:
            self._tree = ast.parse(self.body)
        except SyntaxError as e:
            raise SyntaxError(f"Invalid Python syntax in provided code: {e}") from e

        self._nodes = list(ast.walk(self._tree))

        # Validate that we have a function or class definition
        if not self._find_main_node():
            raise ValueError(
                "No function or class definition found in the provided code"
            )

    # ------------------------------------------------------

    def _find_main_node(self) -> Optional[ast.AST]:
        """
        Find the main definition node in the AST.

        Returns:
            Optional[ast.AST]: The main AST node (FunctionDef, AsyncFunctionDef, or ClassDef)
            Returns None if no definition is found.
        """
        for node in self._nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                return node
        return None

    # ------------------------------------------------------

    def _find_init_node(self, class_node: ast.ClassDef) -> Optional[ast.FunctionDef]:
        """
        Find the __init__ method in a class definition.

        Args:
            class_node (ast.ClassDef): The class definition node to search

        Returns:
            Optional[ast.FunctionDef]: The __init__ method node if found, None otherwise
        """
        for node in class_node.body:
            if isinstance(node, ast.FunctionDef) and node.name == "__init__":
                return node
        return None

    # ------------------------------------------------------

    def _extract_params(
        self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]
    ) -> List[str]:
        """
        Extract all parameter names from a function definition.

        This method handles:
        - Regular parameters (args)
        - Variable arguments (*args)
        - Keyword arguments (**kwargs)
        - Positional-only parameters (Python 3.8+)
        - Keyword-only parameters (Python 3.0+)

        Args:
            node: Function definition AST node

        Returns:
            List[str]: List of parameter names in order of declaration
        """
        params = []

        # Regular positional parameters
        if node.args.args:
            params.extend(arg.arg for arg in node.args.args)

        # *args parameter
        if node.args.vararg:
            params.append(node.args.vararg.arg)

        # **kwargs parameter
        if node.args.kwarg:
            params.append(node.args.kwarg.arg)

        # Positional-only parameters (Python 3.8+)
        if hasattr(node.args, "posonlyargs") and node.args.posonlyargs:
            params.extend(arg.arg for arg in node.args.posonlyargs)

        # Keyword-only parameters
        if node.args.kwonlyargs:
            params.extend(arg.arg for arg in node.args.kwonlyargs)

        return params

    # ------------------------------------------------------

    def _extract_annotations(
        self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]
    ) -> Dict[str, str]:
        """
        Extract type annotations for parameters and return value.

        This method handles various forms of type annotations including:
        - Simple types (str, int, etc.)
        - Compound types (List[str], Dict[str, int], etc.)
        - Imported types (from typing import List)

        Args:
            node: Function definition AST node

        Returns:
            Dict[str, str]: Dictionary mapping parameter names to their type annotations
                           and 'return' for return type annotation
        """
        annotations = {}

        def _get_annotation_string(annotation_node: ast.AST) -> str:
            """
            Convert an annotation AST node to a string representation.

            Args:
                annotation_node: AST node representing the type annotation

            Returns:
                str: String representation of the type annotation
            """
            if isinstance(annotation_node, ast.Name):
                return annotation_node.id
            elif isinstance(annotation_node, ast.Attribute):
                return f"{annotation_node.value.id}.{annotation_node.attr}"
            elif isinstance(annotation_node, ast.Subscript):
                # Handle generic types like List[str], Dict[str, int]
                base = _get_annotation_string(annotation_node.value)
                if isinstance(annotation_node.slice, ast.Index):
                    # Python 3.8 and earlier
                    slice_str = _get_annotation_string(annotation_node.slice.value)
                else:
                    # Python 3.9 and later
                    slice_str = _get_annotation_string(annotation_node.slice)
                return f"{base}[{slice_str}]"
            elif isinstance(annotation_node, ast.Constant):
                return str(annotation_node.value)
            else:
                # For complex annotations, return a simplified representation
                return (
                    ast.unparse(annotation_node)
                    if hasattr(ast, "unparse")
                    else "complex_type"
                )

        # Extract parameter annotations
        all_args = []

        # Collect all possible argument types
        if hasattr(node.args, "posonlyargs"):
            all_args.extend(node.args.posonlyargs)
        all_args.extend(node.args.args)
        if node.args.vararg:
            all_args.append(node.args.vararg)
        if node.args.kwonlyargs:
            all_args.extend(node.args.kwonlyargs)
        if node.args.kwarg:
            all_args.append(node.args.kwarg)

        for arg in all_args:
            if hasattr(arg, "annotation") and arg.annotation:
                try:
                    annotations[arg.arg] = _get_annotation_string(arg.annotation)
                except (AttributeError, KeyError):
                    # If we can't parse the annotation, skip it
                    continue

        # Extract return type annotation
        if node.returns:
            try:
                annotations["return"] = _get_annotation_string(node.returns)
            except (AttributeError, KeyError):
                pass

        return annotations

    # ------------------------------------------------------

    def _extract_defaults(
        self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]
    ) -> Dict[str, Any]:
        """
        Extract default values for function parameters.

        Args:
            node: Function definition AST node

        Returns:
            Dict[str, Any]: Dictionary mapping parameter names to their default values
        """
        defaults = {}

        # Helper function to extract value from AST node
        def _get_default_value(default_node: ast.AST) -> Any:
            if isinstance(default_node, ast.Constant):
                return default_node.value
            elif isinstance(default_node, ast.Name):
                return default_node.id
            elif isinstance(default_node, ast.Attribute):
                return f"{default_node.value.id}.{default_node.attr}"
            elif hasattr(ast, "unparse"):
                return ast.unparse(default_node)
            else:
                return "default_value"

        # Regular parameters with defaults
        if node.args.defaults:
            # The last n parameters have defaults, where n is len(defaults)
            args_with_defaults = node.args.args[-len(node.args.defaults) :]
            for arg, default in zip(args_with_defaults, node.args.defaults):
                defaults[arg.arg] = _get_default_value(default)

        # Keyword-only parameters with defaults
        if node.args.kw_defaults:
            for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
                if default is not None:  # None means no default
                    defaults[arg.arg] = _get_default_value(default)

        return defaults

    # ------------------------------------------------------

    def signature(self) -> Dict[str, Any]:
        """
        Generate a complete structured signature of the analyzed code.

        The signature includes:
        - name: The name of the function/class
        - type: The type of definition ('function', 'async_function', or 'class')
        - parameters: List of parameter names in order
        - annotations: Dictionary of type annotations for parameters and return type
        - defaults: Dictionary of default parameter values

        Returns:
            Dict[str, Any]: Structured signature information

        Raises:
            ValueError: If no valid signature can be extracted
        """
        main_node = self._find_main_node()
        if not main_node:
            raise ValueError("No function or class definition found to analyze")

        result = {
            "name": main_node.name,
            "parameters": [],
            "annotations": {},
            "defaults": {},
        }

        # Determine the type of definition
        if isinstance(main_node, ast.FunctionDef):
            result["type"] = "function"
            result["parameters"] = self._extract_params(main_node)
            result["annotations"] = self._extract_annotations(main_node)
            result["defaults"] = self._extract_defaults(main_node)

        elif isinstance(main_node, ast.AsyncFunctionDef):
            result["type"] = "async_function"
            result["parameters"] = self._extract_params(main_node)
            result["annotations"] = self._extract_annotations(main_node)
            result["defaults"] = self._extract_defaults(main_node)

        elif isinstance(main_node, ast.ClassDef):
            result["type"] = "class"
            init_node = self._find_init_node(main_node)
            if init_node:
                result["parameters"] = self._extract_params(init_node)
                result["annotations"] = self._extract_annotations(init_node)
                result["defaults"] = self._extract_defaults(init_node)

        return result

    # ------------------------------------------------------

    def get_parameter_info(self) -> List[Dict[str, Any]]:
        """
        Get detailed information about each parameter.

        Returns:
            List[Dict[str, Any]]: List of dictionaries with parameter details including
                                 name, type, default value, and whether it's required
        """
        signature = self.signature()
        parameters = []

        for param_name in signature["parameters"]:
            param_info = {
                "name": param_name,
                "type": signature["annotations"].get(param_name, "any"),
                "default": signature["defaults"].get(param_name),
                "required": param_name not in signature["defaults"],
            }
            parameters.append(param_info)

        return parameters

    # ------------------------------------------------------

    def __repr__(self) -> str:
        """Return a string representation of the Signature object."""
        try:
            sig = self.signature()
            return f"Signature(name='{sig['name']}', type='{sig['type']}', parameters={len(sig['parameters'])})"
        except (ValueError, KeyError):
            return "Signature(invalid)"

    # ------------------------------------------------------

    def __str__(self) -> str:
        """Return a human-readable string representation of the signature."""
        try:
            sig = self.signature()
            params = []
            for param in self.get_parameter_info():
                param_str = param["name"]
                if param["type"] != "any":
                    param_str += f": {param['type']}"
                if param["default"] is not None:
                    param_str += f" = {param['default']}"
                params.append(param_str)

            return f"{sig['name']}({', '.join(params)})"
        except (ValueError, KeyError):
            raise ValueError("invalid signature") from None
