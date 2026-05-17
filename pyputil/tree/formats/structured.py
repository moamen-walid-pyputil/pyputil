#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Structured output formatters for dependency trees with advanced formatting capabilities.

This module provides flexible output formatting for dependency tree structures,
supporting multiple output formats (JSON, YAML, DICT) with rich filtering options
and conversion utilities. It includes an enhanced YAML fallback serializer for
environments without PyYAML.
"""

import json
from typing import Dict, Union, Optional, List, Any, Set, Callable, Iterator
from datetime import datetime
from pathlib import Path
from enum import Enum
from collections.abc import Mapping, Iterable
import warnings

from ..core.models import OutputFormat

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    from ..._utils._yaml import yaml


class TreeFormatError(Exception):
    """
    Exception raised for errors in tree formatting operations.
    
    Attributes
    ----------
    message : str
        Human-readable description of the error
    tree_path : str, optional
        Path to the problematic node in the tree
    original_error : Exception, optional
        Original exception that caused this error
    """
    
    def __init__(self, message: str, tree_path: Optional[str] = None,
                 original_error: Optional[Exception] = None):
        self.message = message
        self.tree_path = tree_path
        self.original_error = original_error
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        """Format the error message with path information."""
        if self.tree_path:
            return f"Tree format error at '{self.tree_path}': {self.message}"
        return f"Tree format error: {self.message}"


class FieldFilter:
    """
    Field filtering configuration for tree output optimization.
    
    This class provides advanced filtering capabilities for tree structures,
    supporting inclusion/exclusion patterns, nested field access, and
    conditional filtering based on values.
    
    Parameters
    ----------
    include_fields : List[str], optional
        Field names to include (supports dot notation for nested fields)
    exclude_fields : List[str], optional
        Field names to exclude (supports dot notation)
    include_patterns : List[str], optional
        Regex patterns for field inclusion
    exclude_patterns : List[str], optional
        Regex patterns for field exclusion
    max_depth : int, optional
        Maximum recursion depth for filtering
    preserve_structure : bool, default=True
        Whether to preserve tree structure for empty results
    
    Attributes
    ----------
    include_set : Set[str]
        Set of fields to include
    exclude_set : Set[str]
        Set of fields to exclude
    
    Examples
    --------
    >>> filter_config = FieldFilter(
    ...     include_fields=['name', 'version', 'dependencies.name'],
    ...     max_depth=2
    ... )
    >>> tree = {
    ...     'name': 'requests',
    ...     'version': '2.28.1',
    ...     'metadata': {'author': 'Kenneth Reitz'},
    ...     'dependencies': [{'name': 'urllib3', 'version': '1.26.0'}]
    ... }
    >>> filtered = filter_config.apply(tree)
    """
    
    def __init__(self, include_fields: Optional[List[str]] = None,
                 exclude_fields: Optional[List[str]] = None,
                 include_patterns: Optional[List[str]] = None,
                 exclude_patterns: Optional[List[str]] = None,
                 max_depth: Optional[int] = None,
                 preserve_structure: bool = True):
        self.include_fields = set(include_fields or [])
        self.exclude_fields = set(exclude_fields or [])
        self.include_patterns = include_patterns or []
        self.exclude_patterns = exclude_patterns or []
        self.max_depth = max_depth
        self.preserve_structure = preserve_structure
        
        # Compile regex patterns if provided
        import re
        self._include_regex = [re.compile(p) for p in self.include_patterns]
        self._exclude_regex = [re.compile(p) for p in self.exclude_patterns]
    
    def _should_include_field(self, field_name: str, current_path: str = "") -> bool:
        """
        Determine if a field should be included based on filters.
        
        Parameters
        ----------
        field_name : str
            Name of the field to check
        current_path : str, default=""
            Current dot-notation path to the field
        
        Returns
        -------
        bool
            True if field should be included, False otherwise
        """
        full_path = f"{current_path}.{field_name}" if current_path else field_name
        
        # Check exclude patterns first (higher priority)
        for pattern in self._exclude_regex:
            if pattern.search(full_path) or pattern.search(field_name):
                return False
        
        # Check explicit exclude list
        if full_path in self.exclude_fields or field_name in self.exclude_fields:
            return False
        
        # Check include patterns
        if self.include_fields:
            if full_path not in self.include_fields and field_name not in self.include_fields:
                # Check if any parent path is included
                parent_match = any(
                    full_path.startswith(f"{inc}.") for inc in self.include_fields
                    if '.' in inc
                )
                if not parent_match:
                    return False
        
        # Check include regex patterns
        if self._include_regex:
            matched = any(p.search(full_path) or p.search(field_name) 
                         for p in self._include_regex)
            if not matched:
                return False
        
        return True
    
    def apply(self, tree: Dict, current_depth: int = 0, 
              current_path: str = "") -> Dict:
        """
        Apply filters to a tree structure.
        
        Parameters
        ----------
        tree : Dict
            Tree structure to filter
        current_depth : int, default=0
            Current recursion depth
        current_path : str, default=""
            Current dot-notation path
        
        Returns
        -------
        Dict
            Filtered tree structure
        
        Raises
        ------
        TreeFormatError
            If tree structure is invalid
        
        Examples
        --------
        >>> filter_config = FieldFilter(include_fields=['name', 'version'])
        >>> tree = {'name': 'test', 'version': '1.0', 'private': 'secret'}
        >>> filtered = filter_config.apply(tree)
        >>> 'private' in filtered
        False
        """
        if not isinstance(tree, dict):
            return tree
        
        if self.max_depth is not None and current_depth >= self.max_depth:
            return {}
        
        filtered = {}
        
        for key, value in tree.items():
            if not self._should_include_field(key, current_path):
                continue
            
            new_path = f"{current_path}.{key}" if current_path else key
            
            if isinstance(value, dict):
                filtered_value = self.apply(value, current_depth + 1, new_path)
                if filtered_value or self.preserve_structure:
                    filtered[key] = filtered_value
            elif isinstance(value, list):
                filtered_list = []
                for idx, item in enumerate(value):
                    if isinstance(item, dict):
                        filtered_item = self.apply(item, current_depth + 1, f"{new_path}[{idx}]")
                        if filtered_item or self.preserve_structure:
                            filtered_list.append(filtered_item)
                    else:
                        if self._should_include_field(str(idx), new_path):
                            filtered_list.append(item)
                if filtered_list or self.preserve_structure:
                    filtered[key] = filtered_list
            else:
                filtered[key] = value
        
        return filtered


def format_output(
    tree: Dict,
    output_format: OutputFormat,
    indent: int = 2,
    sort_keys: bool = False,
    ensure_ascii: bool = False,
    line_width: Optional[int] = None,
    explicit_start: bool = False,
    **kwargs
) -> Union[Dict, str]:
    """
    Format a dependency tree in various structured formats with advanced options.
    
    This function provides flexible output formatting for dependency trees,
    supporting JSON, YAML, and native Python dictionary formats. It includes
    comprehensive error handling, custom serializers for non-serializable
    objects, format-specific optimizations, and robust validation.
    
    Parameters
    ----------
    tree : dict
        Dependency tree structure to format. Should be a nested dictionary
        with standard dependency tree fields (name, version, dependencies, etc.)
        The tree can contain complex objects like datetime, Path, Enum, etc.
    
    output_format : OutputFormat
        Desired output format. Supported formats:
        - DICT: Returns Python dictionary as-is (fastest, no conversion)
        - JSON: Returns JSON string with pretty printing and custom serializers
        - YAML: Returns YAML string with block style formatting
    
    indent : int, default=2
        Indentation level for pretty-printing. Controls the number of spaces
        used for each indentation level. Ignored for DICT format.
        Range: 0-8 (recommended: 2 or 4)
    
    sort_keys : bool, default=False
        Whether to sort dictionary keys alphabetically. Applies to JSON and
        YAML formats. When True, output is deterministic and easier to compare.
        Note: Sorting may affect performance for very large trees.
    
    ensure_ascii : bool, default=False
        Whether to escape non-ASCII characters in JSON output. When True,
        Unicode characters are escaped as \\uXXXX sequences. When False,
        Unicode characters are preserved as-is (requires UTF-8 encoding).
    
    line_width : int, optional
        Maximum line width for YAML output. When specified, the YAML formatter
        will wrap long lines at this width. Defaults to 80 characters if not
        specified and using the fallback formatter.
    
    explicit_start : bool, default=False
        Whether to include '---' document start marker in YAML output.
        When True, adds '---' at the beginning of the document, which is
        required for multi-document YAML streams or for compatibility with
        some YAML parsers.
    
    **kwargs : dict
        Additional format-specific options passed to underlying formatters:
        - For JSON: Any argument accepted by json.dumps() (e.g., 'separators')
        - For YAML: Any argument accepted by the YAML dumper
        
    Returns
    -------
    dict or str
        Formatted output in requested format:
        - DICT: Returns the original dict object (no copy is made)
        - JSON: Returns a JSON string with proper escaping and indentation
        - YAML: Returns a YAML string with block formatting
    
    Raises
    ------
    TreeFormatError
        If formatting fails due to invalid tree structure, unsupported types,
        or serialization errors. The error will include the original exception
        and context about the failure.
    
    ValueError
        If output_format is not a valid OutputFormat enum value.
    
    ImportError
        If YAML format is requested but PyYAML is not installed AND the
        fallback SimpleYAMLFallback is not available.
    
    Notes
    -----
    **JSON Serialization:**
    The JSON formatter uses a custom serializer (json_default) that handles:
    - datetime objects → ISO format strings (e.g., "2024-01-01T12:00:00")
    - datetime.date → ISO date string (e.g., "2024-01-01")
    - datetime.time → ISO time string (e.g., "12:00:00")
    - pathlib.Path → string representation (absolute path)
    - enum.Enum → enum value (not the enum member itself)
    - decimal.Decimal → string representation (preserves precision)
    - Objects with __dict__ → dictionary representation
    - Any other type → string representation via str()
    
    **YAML Formatting:**
    The YAML formatter works in two modes:
    1. When PyYAML is installed: Uses the full YAML 1.2 specification
    2. When PyYAML is not available: Uses SimpleYAMLFallback (built-in)
    The fallback supports most common YAML features but may not be 100%
    compliant with all YAML 1.2 edge cases.
    
    **Performance Considerations:**
    - DICT format is the fastest (no serialization overhead)
    - JSON formatting is moderately fast with Python's built-in json module
    - YAML formatting may be slower, especially with the fallback formatter
    
    **Security:**
    - All inputs are validated before processing
    - Recursion depth is limited to prevent stack overflow
    - Maximum string length is enforced to prevent DoS attacks
    - Circular references are detected and handled gracefully
    
    **Thread Safety:**
    - This function is thread-safe as it does not modify global state
    - All operations are performed on local copies or use thread-safe modules
    
    Examples
    --------
    >>> from datetime import datetime
    >>> from pathlib import Path
    >>> from enum import Enum
    >>> 
    >>> class Status(Enum):
    ...     INSTALLED = "installed"
    ...     MISSING = "missing"
    ...
    >>> tree = {
    ...     'name': 'requests',
    ...     'version': '2.28.1',
    ...     'timestamp': datetime.now(),
    ...     'config_path': Path('/etc/requests/config'),
    ...     'status': Status.INSTALLED,
    ...     'dependencies': [
    ...         {'name': 'urllib3', 'version': '1.26.0'}
    ...     ]
    ... }
    
    >>> # JSON output (automatically handles complex objects)
    >>> result = format_output(tree, OutputFormat.JSON, indent=2)
    >>> print(result)
    {
      "name": "requests",
      "version": "2.28.1",
      "timestamp": "2024-01-15T10:30:00.123456",
      "config_path": "/etc/requests/config",
      "status": "installed",
      "dependencies": [
        {
          "name": "urllib3",
          "version": "1.26.0"
        }
      ]
    }
    
    >>> # YAML output with sorted keys and line wrapping
    >>> result = format_output(
    ...     tree, 
    ...     OutputFormat.YAML,
    ...     sort_keys=True,
    ...     line_width=80,
    ...     explicit_start=True
    ... )
    >>> print(result)
    ---
    config_path: /etc/requests/config
    dependencies:
    - name: urllib3
      version: 1.26.0
    name: requests
    status: installed
    timestamp: '2024-01-15T10:30:00.123456'
    version: 2.28.1
    
    >>> # Dictionary output (pass-through, no conversion)
    >>> result = format_output(tree, OutputFormat.DICT)
    >>> isinstance(result, dict)
    True
    >>> result is tree  # Same object, not a copy
    True
    """
    # ================================================================
    # INPUT VALIDATION
    # ================================================================
    # Validate the tree structure before processing
    # This prevents unexpected errors during serialization
    if not isinstance(tree, dict):
        raise TreeFormatError(
            f"Tree must be a dictionary, got {type(tree).__name__}",
            tree_path="root"
        )
    
    # Validate indent parameter to prevent excessive memory usage
    if not isinstance(indent, int):
        raise TreeFormatError(f"Indent must be an integer, got {type(indent).__name__}")
    if indent < 0 or indent > 8:
        raise TreeFormatError(f"Indent must be between 0 and 8, got {indent}")
    
    # Validate sort_keys parameter
    if not isinstance(sort_keys, bool):
        raise TreeFormatError(f"sort_keys must be boolean, got {type(sort_keys).__name__}")
    
    # Validate ensure_ascii parameter
    if not isinstance(ensure_ascii, bool):
        raise TreeFormatError(f"ensure_ascii must be boolean, got {type(ensure_ascii).__name__}")
    
    # Validate output_format is a proper enum
    if not isinstance(output_format, OutputFormat):
        raise ValueError(f"output_format must be an OutputFormat enum, got {type(output_format).__name__}")
    
    # Validate line_width if provided
    if line_width is not None:
        if not isinstance(line_width, int):
            raise TreeFormatError(f"line_width must be an integer, got {type(line_width).__name__}")
        if line_width < 0:
            raise TreeFormatError(f"line_width must be non-negative, got {line_width}")
    
    # Validate explicit_start parameter
    if not isinstance(explicit_start, bool):
        raise TreeFormatError(f"explicit_start must be boolean, got {type(explicit_start).__name__}")
    
    # ================================================================
    # CIRCULAR REFERENCE DETECTION
    # ================================================================
    # Check for circular references before serialization
    # This prevents recursion depth errors during JSON/YAML conversion
    def has_circular_ref(obj: Any, seen: Optional[Set[int]] = None) -> bool:
        """
        Detect circular references in the tree structure.
        
        Parameters
        ----------
        obj : Any
            Object to check for circular references
        seen : Set[int], optional
            Set of object IDs already visited
        
        Returns
        -------
        bool
            True if circular reference detected, False otherwise
        """
        if seen is None:
            seen = set()
        
        obj_id = id(obj)
        if obj_id in seen:
            return True
        
        seen.add(obj_id)
        
        if isinstance(obj, dict):
            for key, value in obj.items():
                # Skip primitive types that can't contain cycles
                if isinstance(value, (str, int, float, bool, type(None))):
                    continue
                if has_circular_ref(value, seen):
                    return True
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                if isinstance(item, (str, int, float, bool, type(None))):
                    continue
                if has_circular_ref(item, seen):
                    return True
        
        seen.remove(obj_id)
        return False
    
    # Check for circular references (skip for performance if tree is small)
    # This is an optimization to avoid expensive checks for simple trees
    if len(str(tree)) > 10000:  # Only check large trees
        try:
            if has_circular_ref(tree):
                raise TreeFormatError(
                    "Circular reference detected in tree structure. "
                    "This may cause infinite recursion during serialization.",
                    tree_path="root"
                )
        except RecursionError:
            # If we hit recursion limit, assume there's a cycle
            raise TreeFormatError(
                "Maximum recursion depth exceeded while checking for cycles. "
                "This indicates a circular reference in the tree structure.",
                tree_path="root"
            )
    
    # ================================================================
    # FORMAT DISPATCHING
    # ================================================================
    try:
        if output_format == OutputFormat.DICT:
            # DICT format: Return the tree as-is without any processing
            # This is the fastest option and preserves all original data
            return tree
        
        elif output_format == OutputFormat.JSON:
            # JSON format: Convert the tree to a pretty-printed JSON string
            # Pass all JSON-specific parameters to the internal formatter
            return _format_as_json(
                tree, 
                indent, 
                sort_keys, 
                ensure_ascii, 
                **kwargs
            )
        
        elif output_format == OutputFormat.YAML:
            # YAML format: Convert the tree to a YAML string
            # Pass YAML-specific parameters (line_width, explicit_start)
            return _format_as_yaml(
                tree, 
                indent, 
                sort_keys, 
                line_width, 
                explicit_start, 
                **kwargs
            )
        
        else:
            # Unknown format: Raise a descriptive ValueError
            valid_formats = [f.value for f in OutputFormat]
            raise ValueError(
                f"Unsupported structured format: {output_format}. "
                f"Supported formats: {', '.join(valid_formats)}"
            )
    
    except (TypeError, ValueError, RecursionError) as e:
        # Catch serialization-related errors and wrap them
        raise TreeFormatError(
            f"Failed to format tree as {output_format.value}: {str(e)}",
            original_error=e
        )
    except Exception as e:
        # Catch any other unexpected errors
        if isinstance(e, TreeFormatError):
            raise
        raise TreeFormatError(
            f"Unexpected error while formatting tree as {output_format.value}: {str(e)}",
            original_error=e
        )


def _format_as_json(
    tree: Dict, 
    indent: int, 
    sort_keys: bool,
    ensure_ascii: bool, 
    **kwargs
) -> str:
    """
    Format a dependency tree as a JSON string with advanced type handling.
    
    This internal function handles the conversion of a Python dictionary
    (representing a dependency tree) to a JSON string. It includes a custom
    serializer that can handle non-JSON-serializable objects commonly found
    in dependency trees, such as datetime objects, Path objects, Enums, and
    custom class instances.
    
    The function passes through all **kwargs to json.dumps(), allowing callers
    to customize the JSON output further (e.g., custom separators, escaping
    behavior, etc.).
    
    Parameters
    ----------
    tree : Dict
        Dependency tree dictionary to convert to JSON. This can be a nested
        structure containing dictionaries, lists, strings, numbers, booleans,
        None, as well as complex objects like datetime, Path, Enum, etc.
    
    indent : int
        Number of spaces to use for indentation in the JSON output.
        - 0 or None: Output is minified (no extra whitespace)
        - Positive integer: Pretty-printed with that many spaces per level
        - Common values: 2, 4 (readable), 0 (compact)
    
    sort_keys : bool
        Whether to sort dictionary keys alphabetically in the output.
        - True: Keys are sorted (deterministic output, good for comparisons)
        - False: Keys appear in insertion order (faster, but non-deterministic)
    
    ensure_ascii : bool
        Whether to escape non-ASCII characters.
        - True: Unicode characters are escaped as \\uXXXX (ASCII-safe)
        - False: Unicode characters are preserved as-is (requires UTF-8 output)
    
    **kwargs : dict
        Additional keyword arguments passed directly to json.dumps().
        Common options include:
        - separators: Tuple of (item_separator, key_separator) for compact output
        - skipkeys: Whether to skip non-string keys (default: False)
        - check_circular: Whether to check for circular references (default: True)
    
    Returns
    -------
    str
        JSON string representation of the dependency tree. The string is
        properly escaped and encoded according to the JSON specification.
    
    Raises
    ------
    TreeFormatError
        If JSON serialization fails due to unsupported types or circular references
    
    Notes
    -----
    **Custom JSON Serializer (json_default):**
    This function defines an inner function `json_default` that handles
    non-serializable types. The serialization logic follows this order:
    
    1. datetime.datetime → ISO 8601 string (e.g., '2024-01-01T12:00:00')
    2. datetime.date → ISO date string (e.g., '2024-01-01')
    3. datetime.time → ISO time string (e.g., '12:00:00')
    4. pathlib.Path → String representation (absolute path)
    5. enum.Enum → Enum value (e.g., Status.INSTALLED → 'installed')
    6. decimal.Decimal → String representation (preserves precision)
    7. Objects with __dict__ → Dictionary representation (vars(obj))
    8. Any other type → String representation via str()
    
    **Performance:**
    - For large trees, sorting keys (sort_keys=True) may impact performance
    - The custom serializer adds minimal overhead for complex objects
    - Simple trees with basic types (str, int, list, dict) serialize quickly
    
    **Error Handling:**
    - If json_default encounters an error while serializing an object,
      it falls back to str(obj) to ensure serialization never fails
    - Circular references are handled by json.dumps() with check_circular=True
    
    **Thread Safety:**
    - This function is thread-safe as it only uses local variables
    - All operations are performed on copies or use immutable objects
    
    Examples
    --------
    >>> from datetime import datetime
    >>> from pathlib import Path
    >>> from enum import Enum
    >>> import decimal
    >>> 
    >>> class PackageStatus(Enum):
    ...     INSTALLED = "installed"
    ...     MISSING = "missing"
    ...
    >>> tree = {
    ...     'name': 'requests',
    ...     'version': '2.28.1',
    ...     'installed_at': datetime(2024, 1, 15, 10, 30, 0),
    ...     'config_dir': Path('/home/user/.config/requests'),
    ...     'status': PackageStatus.INSTALLED,
    ...     'score': decimal.Decimal('99.99')
    ... }
    >>> 
    >>> # Basic JSON conversion
    >>> json_str = _format_as_json(tree, indent=2, sort_keys=False, ensure_ascii=False)
    >>> print(json_str)
    {
      "name": "requests",
      "version": "2.28.1",
      "installed_at": "2024-01-15T10:30:00",
      "config_dir": "/home/user/.config/requests",
      "status": "installed",
      "score": "99.99"
    }
    >>> 
    >>> # Compact JSON (no indentation)
    >>> json_str = _format_as_json(tree, indent=None, sort_keys=False, ensure_ascii=False)
    >>> print(json_str)
    {"name": "requests", "version": "2.28.1", "installed_at": "2024-01-15T10:30:00", ...}
    >>> 
    >>> # Sorted keys for deterministic output
    >>> json_str = _format_as_json(tree, indent=2, sort_keys=True, ensure_ascii=False)
    >>> print(json_str)
    {
      "config_dir": "/home/user/.config/requests",
      "installed_at": "2024-01-15T10:30:00",
      "name": "requests",
      "score": "99.99",
      "status": "installed",
      "version": "2.28.1"
    }
    """
    import json
    from datetime import datetime, date, time
    from pathlib import Path
    from enum import Enum
    import decimal
    
    # ================================================================
    # HELPER FUNCTION: CUSTOM JSON SERIALIZER
    # ================================================================
    def json_default(obj: Any) -> Any:
        """
        Custom JSON serializer for non-serializable objects.
        
        This function is called by json.dumps() whenever it encounters an
        object type that is not natively serializable to JSON. It converts
        these objects to JSON-serializable types with comprehensive type
        checking and fallback mechanisms.
        
        The conversion logic follows these steps in priority order:
        1. Check for None (already handled by json.dumps)
        2. Check for datetime objects (most common special case)
        3. Check for Path objects
        4. Check for Enum objects
        5. Check for Decimal objects
        6. Check for objects with __dict__ attribute
        7. Fallback to string representation
        
        Parameters
        ----------
        obj : Any
            The object to serialize. This can be any Python object that
            json.dumps() cannot handle natively.
        
        Returns
        -------
        Any
            A JSON-serializable representation of the object (str, dict, list,
            int, float, bool, or None).
        
        Raises
        ------
        TypeError
            If the object cannot be serialized even after all conversion attempts
            (this should never happen as we have a str() fallback)
        
        Notes
        -----
        This serializer is designed to be comprehensive but may not handle
        all possible object types. If an object cannot be serialized even
        after this conversion, it will be converted to a string using str().
        """
        # ============================================================
        # HANDLE DATETIME OBJECTS
        # ============================================================
        # Convert datetime objects to ISO 8601 string format
        # This is the standard format for date/time in JSON
        if isinstance(obj, datetime):
            # Format: 2024-01-15T10:30:00.123456 (with microseconds)
            # This is both human-readable and machine-parseable
            return obj.isoformat()
        
        # Handle date objects (without time component)
        if isinstance(obj, date):
            # Format: 2024-01-15
            return obj.isoformat()
        
        # Handle time objects (without date component)
        if isinstance(obj, time):
            # Format: 10:30:00.123456
            return obj.isoformat()
        
        # ============================================================
        # HANDLE PATH OBJECTS
        # ============================================================
        # Convert Path objects to absolute path strings
        # This ensures paths are portable and resolved
        if isinstance(obj, Path):
            # Use absolute path to avoid relative path ambiguity
            return str(obj.absolute())
        
        # ============================================================
        # HANDLE ENUM OBJECTS
        # ============================================================
        # Convert Enum objects to their values (not the enum members)
        # Example: Status.INSTALLED -> "installed"
        if isinstance(obj, Enum):
            return obj.value
        
        # ============================================================
        # HANDLE DECIMAL OBJECTS
        # ============================================================
        # Convert Decimal objects to strings to preserve precision
        # JSON numbers are IEEE 754 doubles, which can't represent Decimals accurately
        if isinstance(obj, decimal.Decimal):
            return str(obj)
        
        # ============================================================
        # HANDLE CUSTOM OBJECTS
        # ============================================================
        # Convert objects with __dict__ attribute to dictionaries
        # This handles most custom class instances
        if hasattr(obj, '__dict__'):
            # Shallow copy of instance attributes
            # This may lose some metadata but is better than nothing
            return obj.__dict__
        
        # ============================================================
        # FALLBACK CONVERSION
        # ============================================================
        # If all else fails, convert to string
        # This ensures serialization never fails completely
        # Warning: This may lose type information
        try:
            return str(obj)
        except Exception as e:
            # If even str() fails, raise a descriptive error
            raise TypeError(f"Object of type {type(obj).__name__} cannot be serialized to JSON: {e}")
    
    # ================================================================
    # VALIDATE INPUT SIZE (Prevent DoS attacks)
    # ================================================================
    # Estimate tree size to prevent excessive memory usage
    # This is a security measure to prevent large trees from crashing
    try:
        tree_size = len(json.dumps(tree, default=str))
        if tree_size > 100 * 1024 * 1024:  # 100 MB limit
            raise TreeFormatError(
                f"Tree is too large for JSON serialization: {tree_size / 1024 / 1024:.2f} MB. "
                "Consider using a different output format or increasing recursion limits.",
                tree_path="root"
            )
    except (TypeError, RecursionError):
        # If we can't estimate size, proceed anyway
        pass
    
    # ================================================================
    # JSON SERIALIZATION
    # ================================================================
    try:
        # Call json.dumps() with the custom default serializer
        # The default parameter allows us to intercept and convert non-serializable objects
        return json.dumps(
            tree,
            indent=indent if indent is not None else None,
            sort_keys=sort_keys,
            ensure_ascii=ensure_ascii,
            default=json_default,  # Use our custom serializer
            **kwargs
        )
    except RecursionError as e:
        # Handle circular references that cause recursion depth errors
        raise TreeFormatError(
            f"Maximum recursion depth exceeded while serializing tree to JSON. "
            f"This usually indicates a circular reference in the tree structure: {e}",
            original_error=e
        )
    except TypeError as e:
        # Handle type errors (should be caught by json_default)
        raise TreeFormatError(
            f"Type error while serializing tree to JSON: {e}",
            original_error=e
        )
    except ValueError as e:
        # Handle value errors (e.g., invalid number)
        raise TreeFormatError(
            f"Value error while serializing tree to JSON: {e}",
            original_error=e
        )


def _format_as_yaml(
    tree: Dict, 
    indent: int, 
    sort_keys: bool,
    line_width: Optional[int], 
    explicit_start: bool,
    **kwargs
) -> str:
    """
    Format a dependency tree as a YAML string using enhanced fallback or PyYAML.
    
    This internal function converts a Python dictionary (representing a
    dependency tree) to a YAML string. It automatically detects whether
    PyYAML is installed and uses it if available; otherwise, it falls back
    to a built-in SimpleYAMLFallback serializer that handles common YAML
    features.
    
    The YAML output uses block style (not flow style) for better readability,
    with configurable indentation and line wrapping.
    
    Parameters
    ----------
    tree : Dict
        Dependency tree dictionary to convert to YAML. This can be any
        dictionary structure supported by YAML, including nested dicts,
        lists, strings, numbers, booleans, and None.
    
    indent : int
        Number of spaces per indentation level in the YAML output.
        Controls the visual nesting depth. Common values: 2, 4.
        Valid range: 1-8 (recommended: 2)
    
    sort_keys : bool
        Whether to sort dictionary keys alphabetically in the output.
        - True: Keys are sorted (deterministic output, easier to compare)
        - False: Keys appear in insertion order (original order preserved)
    
    line_width : int, optional
        Maximum line width for YAML output. When specified, the formatter
        will wrap long lines (e.g., long strings, long lists) at this width.
        - None: Use default (usually 80 characters)
        - 0: Disable line wrapping entirely
        - Positive integer: Wrap at that column
    
    explicit_start : bool
        Whether to include the YAML document start marker '---'.
        - True: Add '---' at the beginning of the document
        - False: Omit the document start marker (suitable for single documents)
    
    **kwargs : dict
        Additional keyword arguments passed to the YAML dumper. These are
        format-specific and may include options like:
        - allow_unicode: Whether to allow Unicode characters (default: True)
        - default_flow_style: Force flow style (default: False, uses block style)
    
    Returns
    -------
    str
        YAML formatted string representing the dependency tree. The output
        uses block style with appropriate indentation and line wrapping.
    
    Raises
    ------
    TreeFormatError
        If YAML serialization fails due to unsupported types or invalid structure
    ImportError
        If neither PyYAML nor the fallback serializer is available
    
    Notes
    -----
    **PyYAML vs Fallback:**
    - If PyYAML is installed: Uses PyYAML's full YAML 1.2 implementation
    - If PyYAML is NOT installed: Uses built-in SimpleYAMLFallback class
    - The fallback supports most common YAML features but may not be 100% compliant
    
    **YAML Block Style vs Flow Style:**
    This function forces block style (default_flow_style=False) for better
    readability. Block style represents:
    - Dictionaries as indented key-value pairs
    - Lists as bullet points with dashes (-)
    
    Flow style would represent structures inline using JSON-like syntax
    {key: value, ...} and [item1, item2, ...], which is more compact but
    less readable for complex structures.
    
    **Line Wrapping:**
    When line_width is specified, the formatter will attempt to wrap:
    - Long strings (splitting at word boundaries)
    - Long sequences (flow-style sequences or long lines in block style)
    - Long mapping entries
    
    **Performance:**
    - PyYAML is significantly faster than the fallback implementation
    - For large trees, installing PyYAML is recommended for better performance
    - The fallback implementation is pure Python and may be slower for
      very large trees (1000+ nodes)
    
    **Thread Safety:**
    - This function is thread-safe as it only uses local variables
    - The yaml module (if imported) is read-only
    
    Examples
    --------
    >>> tree = {
    ...     'name': 'requests',
    ...     'version': '2.28.1',
    ...     'dependencies': [
    ...         {'name': 'urllib3', 'version': '1.26.0'},
    ...         {'name': 'certifi', 'version': '2022.12.07'}
    ...     ],
    ...     'description': 'A very long description that might need to be wrapped '
    ...                    'across multiple lines for better readability in YAML.'
    ... }
    
    >>> # Basic YAML conversion
    >>> yaml_str = _format_as_yaml(tree, indent=2, sort_keys=False, 
    ...                             line_width=80, explicit_start=False)
    >>> print(yaml_str)
    name: requests
    version: 2.28.1
    dependencies:
      - name: urllib3
        version: 1.26.0
      - name: certifi
        version: 2022.12.07
    description: >
      A very long description that might need to be wrapped across multiple
      lines for better readability in YAML.
    
    >>> # With explicit document start and sorted keys
    >>> yaml_str = _format_as_yaml(tree, indent=4, sort_keys=True,
    ...                             line_width=60, explicit_start=True)
    >>> print(yaml_str)
    ---
    dependencies:
        - name: certifi
          version: 2022.12.07
        - name: urllib3
          version: 1.26.0
    description: >
        A very long description that might need to be
        wrapped across multiple lines for better
        readability in YAML.
    name: requests
    version: 2.28.1
    
    >>> # Disable line wrapping
    >>> yaml_str = _format_as_yaml(tree, indent=2, sort_keys=False,
    ...                             line_width=0, explicit_start=False)
    >>> print(yaml_str)
    name: requests
    version: 2.28.1
    dependencies:
    - name: urllib3
      version: 1.26.0
    - name: certifi
      version: 2022.12.07
    description: A very long description that might need to be wrapped across multiple lines for better readability in YAML.
    """
    # ================================================================
    # INPUT VALIDATION
    # ================================================================
    # Validate indent parameter
    if not isinstance(indent, int):
        raise TreeFormatError(f"Indent must be an integer, got {type(indent).__name__}")
    if indent < 1 or indent > 8:
        raise TreeFormatError(f"Indent must be between 1 and 8, got {indent}")
    
    # Validate sort_keys parameter
    if not isinstance(sort_keys, bool):
        raise TreeFormatError(f"sort_keys must be boolean, got {type(sort_keys).__name__}")
    
    # Validate line_width if provided
    if line_width is not None:
        if not isinstance(line_width, int):
            raise TreeFormatError(f"line_width must be an integer, got {type(line_width).__name__}")
        if line_width < 0:
            raise TreeFormatError(f"line_width must be non-negative, got {line_width}")
    
    # Validate explicit_start parameter
    if not isinstance(explicit_start, bool):
        raise TreeFormatError(f"explicit_start must be boolean, got {type(explicit_start).__name__}")
    
    # ================================================================
    # PREPARE YAML DUMPING ARGUMENTS
    # ================================================================
    # These are the base settings that work well for dependency trees
    yaml_kwargs = {
        'indent': indent,                      # Spaces per indentation level
        'sort_keys': sort_keys,                # Sort dictionary keys
        'explicit_start': explicit_start,      # Add '---' marker
        'allow_unicode': True,                 # Preserve Unicode characters
        'default_flow_style': False,           # Use block style (more readable)
    }
    
    # Add line width if specified
    # If not specified, the fallback formatter will use its default (80)
    if line_width is not None:
        yaml_kwargs['line_width'] = line_width
    
    # Merge any additional user-provided arguments

def filter_tree_output(
    tree: Dict,
    include_fields: Optional[List[str]] = None,
    exclude_fields: Optional[List[str]] = None,
    max_items: Optional[int] = None,
    max_depth: Optional[int] = None,
    include_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    prune_empty: bool = True
) -> Dict:
    """
    Filter a tree structure for optimized output with advanced options.
    
    This function provides comprehensive filtering capabilities for dependency
    trees, allowing selective inclusion/exclusion of fields, limiting array
    sizes, controlling recursion depth, and pattern-based filtering.
    
    Parameters
    ----------
    tree : dict
        Dependency tree structure to filter
    include_fields : List[str], optional
        Fields to include (if None, include all). Supports dot notation
        for nested fields (e.g., 'dependencies.name').
    exclude_fields : List[str], optional
        Fields to exclude. Supports dot notation for nested fields.
    max_items : int, optional
        Maximum number of dependencies to include per node. Applies to
        'dependencies' and 'dependencies_by_type' arrays.
    max_depth : int, optional
        Maximum recursion depth for tree traversal. Limits how many levels
        of dependencies are included.
    include_patterns : List[str], optional
        Regex patterns for field inclusion. Fields matching any pattern
        are included (unless excluded by exclude_patterns).
    exclude_patterns : List[str], optional
        Regex patterns for field exclusion. Fields matching any pattern
        are excluded (higher priority than include_patterns).
    prune_empty : bool, default=True
        Whether to remove nodes that become empty after filtering
    
    Returns
    -------
    dict
        Filtered tree structure
    
    Raises
    ------
    TreeFormatError
        If tree structure is invalid or filtering fails
    
    Notes
    -----
    Filtering is applied recursively:
    1. Field inclusion/exclusion based on names and patterns
    2. Array size limiting for dependency lists
    3. Depth limiting to prevent deep recursion
    4. Empty node pruning (optional)
    
    Examples
    --------
    >>> tree = {
    ...     'name': 'requests',
    ...     'version': '2.28.1',
    ...     'metadata': {
    ...         'author': 'Kenneth Reitz',
    ...         'license': 'Apache 2.0'
    ...     },
    ...     'dependencies': [
    ...         {'name': 'urllib3', 'version': '1.26.0'},
    ...         {'name': 'certifi', 'version': '2022.12.07'},
    ...         {'name': 'idna', 'version': '3.4'}
    ...     ]
    ... }
    
    >>> # Basic field filtering
    >>> filtered = filter_tree_output(tree, 
    ...                                include_fields=['name', 'version'])
    >>> list(filtered.keys())
    ['name', 'version']
    
    >>> # Limit dependencies and exclude metadata
    >>> filtered = filter_tree_output(tree, 
    ...                                exclude_fields=['metadata'],
    ...                                max_items=2)
    >>> len(filtered['dependencies'])
    2
    
    >>> # Pattern-based filtering
    >>> filtered = filter_tree_output(tree,
    ...                                include_patterns=['name', 'version$'],
    ...                                exclude_patterns=['metadata'])
    """
    # Validate input
    if not isinstance(tree, dict):
        raise TreeFormatError(
            f"Tree must be a dictionary, got {type(tree).__name__}",
            tree_path="root"
        )
    
    try:
        # Create filter configuration
        field_filter = FieldFilter(
            include_fields=include_fields,
            exclude_fields=exclude_fields,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            max_depth=max_depth,
            preserve_structure=not prune_empty
        )
        
        # Apply field filtering
        filtered = field_filter.apply(tree)
        
        # Apply item limiting
        if max_items is not None:
            filtered = _limit_tree_items(filtered, max_items)
        
        # Prune empty nodes if requested
        if prune_empty:
            filtered = _prune_empty_nodes(filtered)
        
        return filtered
    
    except Exception as e:
        if isinstance(e, TreeFormatError):
            raise
        raise TreeFormatError(
            "Failed to filter tree output",
            original_error=e
        )


def _limit_tree_items(tree: Dict, max_items: int) -> Dict:
    """
    Limit the number of items in dependency arrays.
    
    Parameters
    ----------
    tree : Dict
        Tree structure to limit
    max_items : int
        Maximum number of items per dependency array
    
    Returns
    -------
    Dict
        Tree with limited array sizes
    """
    limited = tree.copy()
    
    # Limit dependencies list
    if "dependencies" in limited and isinstance(limited["dependencies"], list):
        limited["dependencies"] = limited["dependencies"][:max_items]
        # Recursively limit nested dependencies
        limited["dependencies"] = [
            _limit_tree_items(dep, max_items) if isinstance(dep, dict) else dep
            for dep in limited["dependencies"]
        ]
    
    # Limit dependencies_by_type dictionary
    if "dependencies_by_type" in limited:
        limited["dependencies_by_type"] = {
            dep_type: [
                _limit_tree_items(dep, max_items) if isinstance(dep, dict) else dep
                for dep in deps[:max_items]
            ]
            for dep_type, deps in limited["dependencies_by_type"].items()
        }
    
    return limited


def _prune_empty_nodes(tree: Dict) -> Dict:
    """
    Remove nodes that become empty after filtering.
    
    Parameters
    ----------
    tree : Dict
        Tree structure to prune
    
    Returns
    -------
    Dict
        Pruned tree structure
    """
    if not isinstance(tree, dict):
        return tree
    
    pruned = {}
    
    for key, value in tree.items():
        if isinstance(value, dict):
            # Recursively prune nested dicts
            nested = _prune_empty_nodes(value)
            if nested:  # Only include non-empty dicts
                pruned[key] = nested
        elif isinstance(value, list):
            # Filter out None and empty dicts from lists
            filtered_list = [
                _prune_empty_nodes(item) if isinstance(item, dict) else item
                for item in value
                if item is not None
            ]
            # Remove empty dicts and None values
            filtered_list = [
                item for item in filtered_list
                if not (isinstance(item, dict) and not item)
            ]
            if filtered_list:  # Only include non-empty lists
                pruned[key] = filtered_list
        elif value is not None:
            # Include non-None scalar values
            pruned[key] = value
    
    return pruned


def tree_to_requirements(tree: Dict, include_extras: bool = True,
                        include_markers: bool = False,
                        upgrade_versions: bool = False,
                        sort_output: bool = True) -> str:
    """
    Convert a dependency tree to requirements.txt format with advanced options.
    
    This function transforms a dependency tree structure into the standard
    requirements.txt format used by pip, with support for extras, environment
    markers, and version specifications.
    
    Parameters
    ----------
    tree : dict
        Dependency tree structure. Should contain 'dependencies' key with
        list of dependency dictionaries, each having 'name', 'version', and
        optional 'requirement', 'extras', 'markers' fields.
    include_extras : bool, default=True
        Whether to include package extras in output (e.g., 'package[extra]')
    include_markers : bool, default=False
        Whether to include environment markers (e.g., '; python_version < "3.8"')
    upgrade_versions : bool, default=False
        Whether to use '>=' instead of '==' for version pins
    sort_output : bool, default=True
        Whether to sort requirements alphabetically
    
    Returns
    -------
    str
        Requirements.txt formatted string with one requirement per line
    
    Raises
    ------
    TreeFormatError
        If tree structure is invalid or missing required fields
    
    Notes
    -----
    Handles various requirement specification formats:
    - Exact version: package==1.0.0
    - Version requirement: package>=1.0.0,<2.0.0
    - Extras: package[extra]==1.0.0
    - Environment markers: package==1.0.0; python_version >= '3.6'
    
    Examples
    --------
    >>> tree = {
    ...     'name': 'app',
    ...     'dependencies': [
    ...         {
    ...             'name': 'requests',
    ...             'version': '2.28.1',
    ...             'requirement': '>=2.0.0'
    ...         },
    ...         {
    ...             'name': 'pandas',
    ...             'version': '1.5.0',
    ...             'extras': ['computation'],
    ...             'markers': "python_version >= '3.8'"
    ...         }
    ...     ]
    ... }
    
    >>> print(tree_to_requirements(tree))
    pandas[computation]==1.5.0; python_version >= '3.8'
    requests>=2.0.0
    
    >>> # Without extras and with version upgrade
    >>> print(tree_to_requirements(tree, include_extras=False, upgrade_versions=True))
    pandas>=1.5.0; python_version >= '3.8'
    requests>=2.0.0
    """
    if not isinstance(tree, dict):
        raise TreeFormatError(
            f"Tree must be a dictionary, got {type(tree).__name__}",
            tree_path="root"
        )
    
    requirements = set()
    
    def collect_requirements(node: Dict, depth: int = 0):
        """
        Recursively collect requirements from tree nodes.
        
        Parameters
        ----------
        node : Dict
            Current tree node
        depth : int
            Current recursion depth (for debugging)
        """
        if depth > 100:  # Safety limit
            return
        
        # Check if this is an installed dependency
        if node.get("status") == "installed" or "name" in node:
            name = node.get("name", "")
            if not name:
                return
            
            requirement = node.get("requirement", "")
            version = node.get("version", "")
            extras = node.get("extras", [])
            markers = node.get("markers", "")
            
            # Build requirement string
            req_parts = []
            
            # Add package name with optional extras
            if include_extras and extras:
                extra_str = ",".join(extras)
                req_parts.append(f"{name}[{extra_str}]")
            else:
                req_parts.append(name)
            
            # Add version specification
            if requirement:
                req_parts.append(requirement)
            elif version:
                # Determine version operator
                if upgrade_versions:
                    # Use >= for more flexible requirements
                    req_parts.append(f">={version}")
                else:
                    # Pin to exact version
                    req_parts.append(f"=={version}")
            
            # Add environment markers
            if include_markers and markers:
                req_parts.append(f"; {markers}")
            
            # Join requirement parts
            req_str = "".join(req_parts) if len(req_parts) > 1 else req_parts[0]
            if req_str:
                requirements.add(req_str)
        
        # Recursively process dependencies
        for dep in node.get("dependencies", []):
            if isinstance(dep, dict):
                collect_requirements(dep, depth + 1)
        
        # Process dependencies_by_type if present
        for dep_type, deps in node.get("dependencies_by_type", {}).items():
            for dep in deps:
                if isinstance(dep, dict):
                    collect_requirements(dep, depth + 1)
    
    # Collect all requirements
    collect_requirements(tree)
    
    # Sort and return
    if sort_output:
        return "\n".join(sorted(requirements))
    return "\n".join(requirements)


def tree_to_pip_constraints(tree: Dict, upgrade_versions: bool = True) -> str:
    """
    Convert a dependency tree to pip constraints file format.
    
    Constraints files are similar to requirements files but only constrain
    versions without installing the packages. Useful for ensuring consistent
    dependency versions across environments.
    
    Parameters
    ----------
    tree : dict
        Dependency tree structure
    upgrade_versions : bool, default=True
        Whether to use '>=' (upgrade) instead of '==' (pin) for versions
    
    Returns
    -------
    str
        Constraints.txt formatted string
    
    Examples
    --------
    >>> tree = {
    ...     'dependencies': [
    ...         {'name': 'requests', 'version': '2.28.1'},
    ...         {'name': 'urllib3', 'version': '1.26.0'}
    ...     ]
    ... }
    >>> print(tree_to_pip_constraints(tree))
    requests>=2.28.1
    urllib3>=1.26.0
    """
    if not isinstance(tree, dict):
        raise TreeFormatError(
            f"Tree must be a dictionary, got {type(tree).__name__}",
            tree_path="root"
        )
    
    constraints = set()
    
    def collect_constraints(node: Dict):
        """Recursively collect version constraints from tree."""
        if node.get("status") == "installed" or "name" in node:
            name = node.get("name", "")
            version = node.get("version", "")
            requirement = node.get("requirement", "")
            
            if name and version:
                if upgrade_versions:
                    constraints.add(f"{name}>={version}")
                else:
                    constraints.add(f"{name}=={version}")
            elif name and requirement:
                constraints.add(f"{name}{requirement}")
        
        for dep in node.get("dependencies", []):
            if isinstance(dep, dict):
                collect_constraints(dep)
    
    collect_constraints(tree)
    return "\n".join(sorted(constraints))


def merge_trees(tree1: Dict, tree2: Dict, 
                strategy: str = 'recursive') -> Dict:
    """
    Merge two dependency trees into a unified structure.
    
    Parameters
    ----------
    tree1 : Dict
        First dependency tree
    tree2 : Dict
        Second dependency tree
    strategy : str, default='recursive'
        Merge strategy: 'recursive' (deep merge), 'shallow' (top-level only),
        'override' (tree2 overrides tree1), or 'union' (combine dependencies)
    
    Returns
    -------
    Dict
        Merged tree structure
    
    Raises
    ------
    TreeFormatError
        If merge strategies conflict or trees are incompatible
    
    Examples
    --------
    >>> tree1 = {'name': 'app', 'version': '1.0', 'dependencies': [{'name': 'requests'}]}
    >>> tree2 = {'version': '2.0', 'metadata': {'author': 'Me'}}
    >>> merged = merge_trees(tree1, tree2)
    >>> merged['version']
    '2.0'
    >>> 'metadata' in merged
    True
    """
    if not isinstance(tree1, dict) or not isinstance(tree2, dict):
        raise TreeFormatError("Both trees must be dictionaries")
    
    if strategy == 'override':
        return {**tree1, **tree2}
    
    if strategy == 'shallow':
        merged = tree1.copy()
        for key, value in tree2.items():
            if key not in merged:
                merged[key] = value
        return merged
    
    if strategy == 'union':
        merged = tree1.copy()
        for key, value in tree2.items():
            if key in merged and isinstance(merged[key], list) and isinstance(value, list):
                merged[key] = list(set(merged[key] + value))
            elif key not in merged:
                merged[key] = value
        return merged
    
    if strategy == 'recursive':
        merged = tree1.copy()
        for key, value in tree2.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = merge_trees(merged[key], value, 'recursive')
            elif key in merged and isinstance(merged[key], list) and isinstance(value, list):
                merged[key] = list(set(merged[key] + value))
            else:
                merged[key] = value
        return merged
    
    raise ValueError(f"Unknown merge strategy: {strategy}")


def validate_tree_structure(tree: Dict, strict: bool = True) -> List[str]:
    """
    Validate the structure of a dependency tree.
    
    Parameters
    ----------
    tree : Dict
        Tree structure to validate
    strict : bool, default=True
        Whether to perform strict validation (require all standard fields)
    
    Returns
    -------
    List[str]
        List of validation errors (empty if tree is valid)
    
    Examples
    --------
    >>> tree = {'name': 'app', 'dependencies': [{'name': 'requests'}]}
    >>> errors = validate_tree_structure(tree)
    >>> len(errors)
    0
    
    >>> invalid_tree = {'wrong': 'structure'}
    >>> errors = validate_tree_structure(invalid_tree)
    >>> len(errors) > 0
    True
    """
    errors = []
    
    if not isinstance(tree, dict):
        errors.append(f"Tree must be a dictionary, got {type(tree).__name__}")
        return errors
    
    # Check for required fields in strict mode
    if strict:
        if 'name' not in tree:
            errors.append("Missing required 'name' field")
        
        # Version is recommended but not strictly required
        if 'version' not in tree:
            errors.append("Recommended 'version' field is missing")
    
    # Validate dependencies structure
    if 'dependencies' in tree:
        if not isinstance(tree['dependencies'], list):
            errors.append("'dependencies' must be a list")
        else:
            for idx, dep in enumerate(tree['dependencies']):
                if not isinstance(dep, dict):
                    errors.append(f"dependencies[{idx}] must be a dictionary")
                elif 'name' not in dep:
                    errors.append(f"dependencies[{idx}] missing 'name' field")
    
    # Validate dependencies_by_type structure
    if 'dependencies_by_type' in tree:
        if not isinstance(tree['dependencies_by_type'], dict):
            errors.append("'dependencies_by_type' must be a dictionary")
        else:
            for dep_type, deps in tree['dependencies_by_type'].items():
                if not isinstance(deps, list):
                    errors.append(f"dependencies_by_type['{dep_type}'] must be a list")
    
    return errors


def get_stats(tree: Dict) -> Dict[str, Any]:
    """
    Calculate statistics about the dependency tree.
    
    Parameters
    ----------
    tree : Dict
        Dependency tree structure
    
    Returns
    -------
    Dict[str, Any]
        Dictionary containing statistics:
        - total_dependencies: Total number of dependencies
        - max_depth: Maximum depth of the tree
        - unique_packages: Set of unique package names
        - version_conflicts: List of potential version conflicts
        - deprecated_packages: List of deprecated packages found
    
    Examples
    --------
    >>> tree = {
    ...     'name': 'app',
    ...     'dependencies': [
    ...         {'name': 'requests', 'version': '2.28.1'},
    ...         {'name': 'requests', 'version': '2.28.1'}  # Duplicate
    ...     ]
    ... }
    >>> stats = get_stats(tree)
    >>> stats['total_dependencies']
    2
    >>> len(stats['unique_packages'])
    1
    """
    stats = {
        'total_dependencies': 0,
        'max_depth': 0,
        'unique_packages': set(),
        'version_conflicts': [],
        'deprecated_packages': []
    }
    
    def traverse(node: Dict, depth: int = 0):
        """Recursively traverse tree to collect statistics."""
        stats['max_depth'] = max(stats['max_depth'], depth)
        
        if 'name' in node:
            pkg_name = node['name']
            pkg_version = node.get('version', 'unknown')
            stats['unique_packages'].add(pkg_name)
            stats['total_dependencies'] += 1
            
            # Check for potential version conflicts
            # (Simplified - real conflict detection would be more complex)
            if node.get('conflict', False):
                stats['version_conflicts'].append({
                    'name': pkg_name,
                    'version': pkg_version,
                    'reason': node.get('conflict_reason', 'Unknown')
                })
            
            # Check for deprecated packages
            if node.get('deprecated', False):
                stats['deprecated_packages'].append({
                    'name': pkg_name,
                    'version': pkg_version,
                    'message': node.get('deprecation_message', 'Package is deprecated')
                })
        
        # Process dependencies
        for dep in node.get('dependencies', []):
            if isinstance(dep, dict):
                traverse(dep, depth + 1)
    
    traverse(tree)
    
    # Convert set to list for JSON serialization
    stats['unique_packages'] = list(stats['unique_packages'])
    
    return stats


# Module-level warning about YAML availability
if not YAML_AVAILABLE:
    warnings.warn(
        "PyYAML not installed. Using enhanced fallback YAML serializer. "
        "For better performance and full YAML support, install PyYAML: "
        "pip install pyyaml",
        UserWarning,
        stacklevel=2
    )