#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
File operations for exporting and importing modules.
"""

import os
from typing import Optional, Dict, Any
from types import ModuleType
from .dataclasses import ModuleConfig


def to_file(module: ModuleType, filename: str, include_metadata: bool = True) -> None:
    """
    Convert a mkmod module object to a Python file.

    Saves the module source code, attributes, and variables to a Python file.

    Parameters
    ----------
    module : ModuleType
        mkmod module object to export.
    filename : str
        Output filename (should end with .py).
    include_metadata : bool, default=True
        Whether to include mkmod metadata as comments.

    Returns
    -------
    None

    Raises
    ------
    TypeError
        If module is not a mkmod module.
    ValueError
        If filename doesn't end with .py.
    PermissionError
        If unable to write to the file.

    Examples
    --------
    >>> mod = mkmod("calculator", source="def add(a, b): return a + b")
    >>> to_file(mod, "calculator.py")
    >>> # Creates calculator.py with the add function
    """
    from .core import is_mkmod

    # Validate inputs
    if not isinstance(module, ModuleType):
        raise TypeError(f"Expected module object, got {type(module).__name__}")

    if not is_mkmod(module):
        raise TypeError("Module was not created with mkmod")

    if not filename.endswith(".py"):
        raise ValueError(f"Filename must end with .py, got: {filename}")

    # Gather module information
    module_name = module.__name__
    source_code = getattr(module, "__source__", None)

    # Collect all module attributes that are not private/internal
    attrs_to_export: Dict[str, Any] = {}
    for attr_name in dir(module):
        # Skip private/internal attributes unless include_metadata is True
        if attr_name.startswith("__") and attr_name.endswith("__"):
            if not include_metadata or attr_name in ("__name__", "__doc__"):
                continue
        elif attr_name.startswith("_"):
            continue

        try:
            attr_value = getattr(module, attr_name)

            # Skip modules, builtins, and mkmod internal attributes
            if isinstance(attr_value, ModuleType):
                continue
            if attr_name in ("__builtins__", "__loader__", "__spec__", "__package__"):
                continue
            if attr_name.startswith("__mkmod_"):
                continue

            attrs_to_export[attr_name] = attr_value
        except Exception:
            # Skip attributes that can't be accessed
            continue

    # Build the Python file content
    lines = []

    # Add module docstring if available
    module_doc = getattr(module, "__doc__", None)
    if module_doc:
        lines.append(f'"""{module_doc}"""')
        lines.append("")

    # Add source code if available
    if source_code:
        lines.append("# === Source Code ===")
        lines.append(source_code)
        if source_code and not source_code.endswith("\n"):
            lines.append("")  # Add newline if source doesn't end with one

    # Add exported attributes
    if attrs_to_export:
        if source_code:  # Add separator only if we have source code
            lines.append("\n# === Module Attributes ===")
        else:
            lines.append("# === Module Attributes ===")

    # Helper function to safely represent values
    def safe_repr(
        value: Any, indent: int = 0, max_depth: int = 3, current_depth: int = 0
    ) -> str:
        """
        Safely represent a value as Python code.

        Parameters
        ----------
        value : Any
            Value to represent.
        indent : int, default=0
            Current indentation level.
        max_depth : int, default=3
            Maximum recursion depth.
        current_depth : int, default=0
            Current recursion depth.

        Returns
        -------
        str
            Python representation of value.
        """
        if current_depth >= max_depth:
            return "..."

        indent_str = " " * indent

        if isinstance(value, (int, float, bool, type(None))):
            return repr(value)

        elif isinstance(value, str):
            # For multi-line strings, use triple quotes
            if "\n" in value:
                return f'"""{value}"""'
            return repr(value)

        elif isinstance(value, (list, tuple)):
            if not value:  # Empty
                return repr(value)

            items = []
            for item in value:
                item_repr = safe_repr(item, indent + 4, max_depth, current_depth + 1)
                items.append(f"{indent_str}    {item_repr}")

            if isinstance(value, tuple):
                if len(value) == 1:
                    return f"({items[0].strip()},)"
                return f'(\n{"".join(items)}\n{indent_str})'
            else:  # list
                return f'[\n{"".join(items)}\n{indent_str}]'

        elif isinstance(value, dict):
            if not value:  # Empty
                return "{}"

            items = []
            for k, v in value.items():
                if not isinstance(k, (str, int, float, bool, type(None))):
                    continue  # Skip non-serializable keys
                key_repr = repr(k)
                val_repr = safe_repr(v, indent + 4, max_depth, current_depth + 1)
                items.append(f"{indent_str}    {key_repr}: {val_repr},")

            return f'{{\n{"".join(items)}\n{indent_str}}}'

        elif isinstance(value, set):
            if not value:  # Empty
                return "set()"

            items = []
            for item in value:
                item_repr = safe_repr(item, indent + 4, max_depth, current_depth + 1)
                items.append(f"{indent_str}    {item_repr},")

            return f'{{\n{"".join(items)}\n{indent_str}}}'

        elif isinstance(value, type):
            return f"<class '{value.__name__}'>"

        elif callable(value):
            # Try to get source for functions defined in this module
            try:
                if hasattr(value, "__module__") and value.__module__ == module_name:
                    if hasattr(value, "__code__"):
                        return f"'<function {value.__name__}>'"
            except Exception:
                pass
            return f"'<callable {type(value).__name__}>'"

        else:
            return f"'<{type(value).__name__}>'"

    # Export each attribute
    for attr_name, attr_value in sorted(attrs_to_export.items()):
        # Skip if already defined in source code (unless it's a redefinition)
        if source_code and attr_name in source_code and callable(attr_value):
            lines.append(
                f"# {attr_name} = {safe_repr(attr_value)}  # Already defined above"
            )
        else:
            value_repr = safe_repr(attr_value)
            lines.append(f"{attr_name} = {value_repr}")

    # Add metadata as comments if requested
    if include_metadata:
        lines.append("\n# === Mkmod Metadata ===")

        metadata_attrs = [
            ("__name__", "Module name"),
            ("__created__", "Creation timestamp"),
            ("__modified__", "Last modification timestamp"),
            ("__Safe_level__", "Security level"),
            ("__policies__", "Security policies"),
            ("__fingerprint__", "Source fingerprint"),
            ("__factory__", "Created by"),
        ]

        for attr, description in metadata_attrs:
            value = getattr(module, attr, None)
            if value is not None:
                if attr in ("__created__", "__modified__"):
                    from datetime import datetime

                    try:
                        dt = datetime.fromtimestamp(value)
                        value_str = f"{value} ({dt.isoformat()})"
                    except Exception:
                        value_str = str(value)
                else:
                    value_str = str(value)

                lines.append(f"# {description}: {value_str}")

    # Write to file
    try:
        content = "\n".join(lines)

        # Ensure the content ends with a newline
        if not content.endswith("\n"):
            content += "\n"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)

    except IOError as e:
        raise PermissionError(f"Cannot write to file '{filename}': {e}")
    except Exception as e:
        raise RuntimeError(f"Error exporting module to file: {e}")


def from_file(
    filename: str, module_name: Optional[str] = None, **mkmod_kwargs
) -> ModuleType:
    """
    Create a mkmod module from a Python file.

    Parameters
    ----------
    filename : str
        Python file to import.
    module_name : str, optional
        Name for the module. Defaults to filename without extension.
    **mkmod_kwargs
        Additional arguments to pass to mkmod.

    Returns
    -------
    ModuleType
        mkmod module object.

    Raises
    ------
    FileNotFoundError
        If file does not exist.

    Examples
    --------
    >>> module = from_file("calculator.py")
    >>> module.add(1, 2)
    3
    """
    from .core import mkmod

    # Check if file exists
    if not os.path.exists(filename):
        raise FileNotFoundError(f"File not found: {filename}")

    # Determine module name
    if module_name is None:
        module_name = os.path.splitext(os.path.basename(filename))[0]

    # Read file content
    try:
        with open(filename, "r", encoding="utf-8") as f:
            source = f.read()
    except UnicodeDecodeError:
        # Try with different encoding
        with open(filename, "r", encoding="latin-1") as f:
            source = f.read()

    # Create module using mkmod
    return mkmod(module_name, source=source, **mkmod_kwargs)


def export_module(
    module: ModuleType, output_dir: str = ".", include_metadata: bool = False
) -> str:
    """
    Export a mkmod module to a file.

    Parameters
    ----------
    module : ModuleType
        mkmod module to export.
    output_dir : str, default="."
        Output directory.
    include_metadata : bool, default=False
        Whether to include metadata as comments.

    Returns
    -------
    str
        Path to the created file.

    Raises
    ------
    ValueError
        If module doesn't have __name__ attribute.

    Examples
    --------
    >>> path = export_module(module, "exports")
    >>> print(path)
    "exports/my_module.py"
    """
    if not hasattr(module, "__name__"):
        raise ValueError("Module must have a __name__ attribute")

    filename = os.path.join(output_dir, f"{module.__name__}.py")

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Handle filename conflicts
    counter = 1
    original_filename = filename
    while os.path.exists(filename):
        name_without_ext = os.path.splitext(original_filename)[0]
        filename = f"{name_without_ext}_{counter}.py"
        counter += 1

    # Export to file
    to_file(module, filename, include_metadata=include_metadata)
    return filename
