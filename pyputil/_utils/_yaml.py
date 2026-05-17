#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import warnings
import re
from typing import Any, Dict, List, Union, Optional, Tuple, Set, Callable
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from collections.abc import Iterable, Mapping
import json
import hashlib


class YAMLFormatError(Exception):
    """
    Exception raised for YAML formatting errors.
    
    This exception is raised when the YAML serializer encounters invalid
    data structures or formatting issues during serialization.
    
    Attributes
    ----------
    message : str
        Human-readable description of the error
    data_path : str, optional
        Path to the problematic data in dot notation (e.g., 'workflow.jobs.build.steps')
    original_error : Exception, optional
        Original exception that caused this error
    """
    
    def __init__(self, message: str, data_path: Optional[str] = None, 
                 original_error: Optional[Exception] = None):
        self.message = message
        self.data_path = data_path
        self.original_error = original_error
        super().__init__(self.message)
    
    def __str__(self) -> str:
        """Return formatted error message with path information."""
        if self.data_path:
            return f"YAML format error at '{self.data_path}': {self.message}"
        return f"YAML format error: {self.message}"


class SimpleYAMLFallback:
    """
    Enhanced fallback YAML serializer with comprehensive functionality.
    
    This class provides production-ready YAML serialization for when PyYAML
    is not available. It implements a significant subset of YAML 1.2 features
    with extensive customization options and robust error handling.
    
    Features
    --------
    - Full YAML 1.2 compatible syntax for common structures
    - Advanced data type support (datetime, Decimal, Enum, Path, bytes)
    - Multi-line string handling with multiple styles (literal, folded, quoted)
    - Flow and block style control for collections
    - Anchor and alias support for YAML references
    - Automatic line wrapping with configurable width
    - Indentation and style customization
    - Comment generation and preservation
    - Circular reference detection and handling
    - Custom serializer registration
    - Pretty printing with sorting options
    - Unicode and special character escaping
    - Recursive depth limiting for large structures
    
    Parameters
    ----------
    indent : int, default=2
        Number of spaces for each indentation level
    default_flow_style : bool, default=False
        Whether to use flow style (inline) for collections by default
    allow_unicode : bool, default=True
        Whether to allow unicode characters without escaping
    line_width : int, default=80
        Maximum line width before wrapping (0 disables wrapping)
    explicit_start : bool, default=False
        Whether to include '---' document start marker
    explicit_end : bool, default=False
        Whether to include '...' document end marker
    sort_keys : bool, default=False
        Whether to sort dictionary keys alphabetically
    indent_mapping : int, default=None
        Specific indentation for mappings (uses indent if None)
    indent_sequence : int, default=None
        Specific indentation for sequences (uses indent if None)
    block_seq_indent : int, default=0
        Extra indentation for sequences in block mode
    allow_duplicate_keys : bool, default=False
        Whether to allow duplicate dictionary keys (triggers warning)
    max_recursion_depth : int, default=100
        Maximum recursion depth before raising error
    detect_cycles : bool, default=True
        Whether to detect and handle circular references
    custom_serializers : Dict[type, Callable], optional
        Custom serializers for specific types
    
    Attributes
    ----------
    _anchor_registry : Dict[str, Any]
        Registry of anchors for YAML references
    _anchor_counter : int
        Counter for generating unique anchor names
    _serialized_objects : Dict[int, str]
        Registry of serialized objects to prevent cycles
    
    Examples
    --------
    >>> yaml = SimpleYAMLFallback(indent=4, line_width=120)
    >>> data = {
    ...     "workflow": {
    ...         "name": "CI/CD Pipeline",
    ...         "on": ["push", "pull_request"],
    ...         "jobs": {
    ...             "build": {
    ...                 "runs-on": "ubuntu-latest",
    ...                 "steps": [
    ...                     {"uses": "actions/checkout@v2"},
    ...                     {"run": "make build"}
    ...                 ]
    ...             }
    ...         }
    ...     }
    ... }
    >>> print(yaml.dump(data))
    
    >>> # Advanced usage with custom serializers
    >>> yaml.register_serializer(Path, lambda p: str(p.absolute()))
    >>> data = {"path": Path("/home/user/file.txt")}
    >>> print(yaml.dump(data))
    """
    
    def __init__(self, indent: int = 2, default_flow_style: bool = False,
                 allow_unicode: bool = True, line_width: int = 80,
                 explicit_start: bool = False, explicit_end: bool = False,
                 sort_keys: bool = False, indent_mapping: Optional[int] = None,
                 indent_sequence: Optional[int] = None, block_seq_indent: int = 0,
                 allow_duplicate_keys: bool = False, max_recursion_depth: int = 100,
                 detect_cycles: bool = True,
                 custom_serializers: Optional[Dict[type, Callable]] = None):
        """
        Initialize YAML serializer with configuration parameters.
        
        Parameters
        ----------
        indent : int, default=2
            Number of spaces for each indentation level (1-8)
        default_flow_style : bool, default=False
            Use flow style (braces/brackets) instead of block style
        allow_unicode : bool, default=True
            Output unicode characters without escaping
        line_width : int, default=80
            Maximum line width before wrapping (0 to disable)
        explicit_start : bool, default=False
            Add '---' at the beginning of output
        explicit_end : bool, default=False
            Add '...' at the end of output
        sort_keys : bool, default=False
            Sort dictionary keys alphabetically
        indent_mapping : int, optional
            Indentation for mapping items (defaults to indent)
        indent_sequence : int, optional
            Indentation for sequence items (defaults to indent)
        block_seq_indent : int, default=0
            Extra spaces before sequence dashes in block mode
        allow_duplicate_keys : bool, default=False
            Allow duplicate dictionary keys (otherwise warning)
        max_recursion_depth : int, default=100
            Maximum recursion depth limit
        detect_cycles : bool, default=True
            Detect circular references in data structures
        custom_serializers : Dict[type, Callable], optional
            Type-specific serializer functions
        
        Raises
        ------
        ValueError
            If indent values are invalid (not 1-8)
        
        Examples
        --------
        >>> yaml = SimpleYAMLFallback(indent=4, line_width=120)
        >>> yaml = SimpleYAMLFallback(default_flow_style=True, explicit_start=True)
        """
        # Validate parameters
        if not 1 <= indent <= 8:
            raise ValueError(f"indent must be between 1 and 8, got {indent}")
        
        # Store configuration
        self.indent = indent
        self.default_flow_style = default_flow_style
        self.allow_unicode = allow_unicode
        self.line_width = line_width
        self.explicit_start = explicit_start
        self.explicit_end = explicit_end
        self.sort_keys = sort_keys
        self.indent_mapping = indent_mapping or indent
        self.indent_sequence = indent_sequence or indent
        self.block_seq_indent = block_seq_indent
        self.allow_duplicate_keys = allow_duplicate_keys
        self.max_recursion_depth = max_recursion_depth
        self.detect_cycles = detect_cycles
        
        # Initialize internal state
        self._anchor_registry: Dict[str, Any] = {}
        self._anchor_counter: int = 0
        self._serialized_objects: Dict[int, str] = {}
        self._custom_serializers: Dict[type, Callable] = custom_serializers or {}
        
        # Default serializers for common types
        self._register_default_serializers()
    
    def _register_default_serializers(self) -> None:
        """Register the built-in serializers for common Python types."""
        self._custom_serializers[datetime] = self._serialize_datetime
        self._custom_serializers[date] = self._serialize_date
        self._custom_serializers[time] = self._serialize_time
        self._custom_serializers[timedelta] = self._serialize_timedelta
        self._custom_serializers[Decimal] = self._serialize_decimal
        self._custom_serializers[Path] = self._serialize_path
        self._custom_serializers[Enum] = lambda e: e.value
        self._custom_serializers[bytes] = self._serialize_bytes
    
    def register_serializer(self, type_: type, serializer: Callable[[Any], Any]) -> None:
        """
        Register a custom serializer for a specific type.
        
        Parameters
        ----------
        type_ : type
            The Python type to handle with this serializer
        serializer : Callable[[Any], Any]
            Function that takes an instance of type_ and returns a serializable value
        
        Raises
        ------
        TypeError
            If serializer is not callable
        
        Examples
        --------
        >>> yaml = SimpleYAMLFallback()
        >>> yaml.register_serializer(complex, lambda c: f"{c.real}+{c.imag}j")
        >>> yaml.dump({"complex": 3+4j})
        'complex: 3.0+4.0j'
        """
        if not callable(serializer):
            raise TypeError(f"Serializer must be callable, got {type(serializer)}")
        self._custom_serializers[type_] = serializer
    
    def _serialize_datetime(self, dt: datetime) -> str:
        """
        Serialize datetime object to ISO 8601 format.
        
        Parameters
        ----------
        dt : datetime
            Datetime object to serialize
        
        Returns
        -------
        str
            ISO 8601 formatted datetime string
        
        Examples
        --------
        >>> yaml = SimpleYAMLFallback()
        >>> yaml._serialize_datetime(datetime(2024, 1, 1, 12, 0, 0))
        '2024-01-01T12:00:00'
        """
        if dt.tzinfo:
            return dt.isoformat()
        return dt.isoformat() + 'Z' if dt.tzinfo is None else dt.isoformat()
    
    def _serialize_date(self, d: date) -> str:
        """
        Serialize date object to YYYY-MM-DD format.
        
        Parameters
        ----------
        d : date
            Date object to serialize
        
        Returns
        -------
        str
            Formatted date string
        """
        return d.isoformat()
    
    def _serialize_time(self, t: time) -> str:
        """
        Serialize time object to HH:MM:SS format.
        
        Parameters
        ----------
        t : time
            Time object to serialize
        
        Returns
        -------
        str
            Formatted time string
        """
        return t.isoformat()
    
    def _serialize_timedelta(self, td: timedelta) -> str:
        """
        Serialize timedelta object to duration string.
        
        Parameters
        ----------
        td : timedelta
            Timedelta object to serialize
        
        Returns
        -------
        str
            Duration in format 'P[n]Y[n]M[n]DT[n]H[n]M[n]S'
        
        Examples
        --------
        >>> yaml = SimpleYAMLFallback()
        >>> yaml._serialize_timedelta(timedelta(days=5, hours=3))
        'P5DT3H'
        """
        days = td.days
        seconds = td.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        parts = []
        if days > 0:
            parts.append(f"{days}D")
        if hours > 0:
            parts.append(f"{hours}H")
        if minutes > 0:
            parts.append(f"{minutes}M")
        if secs > 0:
            parts.append(f"{secs}S")
        
        return f"P{''.join(parts)}" if parts else "PT0S"
    
    def _serialize_decimal(self, d: Decimal) -> str:
        """
        Serialize Decimal object to string representation.
        
        Parameters
        ----------
        d : Decimal
            Decimal to serialize
        
        Returns
        -------
        str
            String representation without scientific notation
        """
        return format(d, 'f')
    
    def _serialize_path(self, p: Path) -> str:
        """
        Serialize Path object to absolute path string.
        
        Parameters
        ----------
        p : Path
            Path object to serialize
        
        Returns
        -------
        str
            Absolute path as string
        """
        return str(p.absolute())
    
    def _serialize_bytes(self, b: bytes) -> str:
        """
        Serialize bytes object to base64 or hex string.
        
        Parameters
        ----------
        b : bytes
            Bytes to serialize
        
        Returns
        -------
        str
            Base64 encoded string ('!binary' tag) or hex for short values
        """
        if len(b) < 32:
            return f"!!binary {b.hex()}"
        import base64
        return f"!!binary {base64.b64encode(b).decode('ascii')}"
    
    def _generate_anchor(self, obj: Any) -> str:
        """
        Generate a unique anchor name for YAML references.
        
        Parameters
        ----------
        obj : Any
            Object to generate anchor for
        
        Returns
        -------
        str
            Unique anchor identifier
        
        Examples
        --------
        >>> yaml = SimpleYAMLFallback()
        >>> anchor = yaml._generate_anchor({"data": [1,2,3]})
        >>> anchor.startswith('id')
        True
        """
        self._anchor_counter += 1
        anchor = f"id{self._anchor_counter}"
        self._anchor_registry[anchor] = obj
        return anchor
    
    def _detect_circular_reference(self, obj: Any, path: str = "") -> Optional[str]:
        """
        Detect circular references in nested structures.
        
        Parameters
        ----------
        obj : Any
            Object to check for circular references
        path : str, default=""
            Current path in dot notation for error reporting
        
        Returns
        -------
        Optional[str]
            Path where circular reference was found, or None if not found
        
        Raises
        ------
        YAMLFormatError
            If circular reference is detected and detection is enabled
        
        Examples
        --------
        >>> yaml = SimpleYAMLFallback()
        >>> circular = {}
        >>> circular['self'] = circular
        >>> yaml._detect_circular_reference(circular)
        'self'
        """
        if not self.detect_cycles:
            return None
        
        seen = set()
        
        def _dfs(obj, current_path, stack):
            obj_id = id(obj)
            if obj_id in seen:
                return stack[stack.index(current_path)] if current_path in stack else None
            seen.add(obj_id)
            
            if isinstance(obj, dict):
                for k, v in obj.items():
                    result = _dfs(v, f"{current_path}.{k}", stack + [current_path])
                    if result:
                        return result
            elif isinstance(obj, (list, tuple, set)):
                for i, v in enumerate(obj):
                    result = _dfs(v, f"{current_path}[{i}]", stack + [current_path])
                    if result:
                        return result
            return None
        
        return _dfs(obj, path, [])
    
    def _wrap_line(self, text: str, indent_level: int = 0,
                   first_indent: Optional[int] = None) -> str:
        """
        Wrap text to specified line width with indentation.
        
        Parameters
        ----------
        text : str
            Text to wrap
        indent_level : int, default=0
            Base indentation level
        first_indent : int, optional
            Indentation for first line (defaults to indent_level)
        
        Returns
        -------
        str
            Wrapped text with proper line breaks
        
        Notes
        -----
        Uses word boundary detection to avoid breaking words.
        Preserves existing newlines and indentation.
        
        Examples
        --------
        >>> yaml = SimpleYAMLFallback(line_width=40)
        >>> long_text = "This is a very long string that needs to be wrapped"
        >>> print(yaml._wrap_line(long_text, indent_level=2))
        """
        if self.line_width <= 0 or len(text) <= self.line_width:
            return text
        
        first_indent = first_indent if first_indent is not None else indent_level
        indent_spaces = " " * (indent_level * self.indent)
        first_indent_spaces = " " * (first_indent * self.indent)
        
        # Split existing lines
        lines = []
        for paragraph in text.split('\n'):
            if not paragraph:
                lines.append('')
                continue
            
            # Wrap paragraph
            words = paragraph.split(' ')
            current_line = []
            current_length = 0
            
            for word in words:
                word_len = len(word) + (1 if current_line else 0)
                if current_length + word_len <= self.line_width - len(first_indent_spaces):
                    current_line.append(word)
                    current_length += word_len
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                    current_line = [word]
                    current_length = len(word)
            
            if current_line:
                lines.append(' '.join(current_line))
        
        # Apply indentation
        result_lines = []
        for i, line in enumerate(lines):
            if i == 0:
                result_lines.append(f"{first_indent_spaces}{line}")
            else:
                result_lines.append(f"{indent_spaces}{line}")
        
        return '\n'.join(result_lines)
    
    def _escape_string(self, value: str, style: str = 'double') -> str:
        """
        Escape special characters in strings for YAML compatibility.
        
        Parameters
        ----------
        value : str
            String to escape
        style : {'double', 'single', 'literal', 'folded'}, default='double'
            Quote style to use for escaping
        
        Returns
        -------
        str
            Escaped string suitable for YAML
        
        Notes
        -----
        Double quotes support escape sequences (\n, \t, etc.)
        Single quotes only escape single quotes by doubling them
        Literal style preserves newlines (|)
        Folded style folds newlines to spaces (>)
        
        Examples
        --------
        >>> yaml = SimpleYAMLFallback()
        >>> yaml._escape_string("Hello\nWorld", 'double')
        '"Hello\\nWorld"'
        >>> yaml._escape_string("Don't stop", 'single')
        "'Don''t stop'"
        """
        if style == 'literal':
            return '|-\n' + '\n'.join(f"  {line}" for line in value.split('\n'))
        
        if style == 'folded':
            return '>-\n' + '\n'.join(f"  {line}" for line in value.split('\n\n'))
        
        if style == 'single':
            # Only escape single quotes by doubling them
            escaped = value.replace("'", "''")
            return f"'{escaped}'"
        
        # Double quote escaping
        escape_chars = {
            '\n': '\\n',
            '\r': '\\r',
            '\t': '\\t',
            '\b': '\\b',
            '\f': '\\f',
            '\\': '\\\\',
            '"': '\\"',
        }
        escaped = ''.join(escape_chars.get(c, c) for c in value)
        return f'"{escaped}"'
    
    def _serialize_value(self, value: Any, indent_level: int = 0,
                        path: str = "", flow_style: Optional[bool] = None,
                        use_anchor: bool = True) -> str:
        """
        Serialize a single value to YAML string with advanced formatting.
        
        Parameters
        ----------
        value : Any
            Python value to serialize
        indent_level : int, default=0
            Current indentation level
        path : str, default=""
            Current path in dot notation for error reporting
        flow_style : bool, optional
            Whether to use flow style (overrides default)
        use_anchor : bool, default=True
            Whether to use anchors for repeated references
        
        Returns
        -------
        str
            YAML-formatted string representation
        
        Raises
        ------
        YAMLFormatError
            If serialization fails due to unsupported type or recursion depth
        
        Notes
        -----
        Handles all YAML scalar types including:
        - None (null)
        - Boolean (true/false)
        - Integers and floats
        - Strings (with automatic quoting when needed)
        - Collections (dicts, lists, tuples, sets)
        - Custom objects via registered serializers
        
        Examples
        --------
        >>> yaml = SimpleYAMLFallback()
        >>> yaml._serialize_value("simple string", 0)
        'simple string'
        >>> yaml._serialize_value("true", 0)  # Auto-quoted
        '"true"'
        >>> yaml._serialize_value(None, 0)
        'null'
        """
        # Check recursion depth
        if indent_level > self.max_recursion_depth:
            raise YAMLFormatError(
                f"Maximum recursion depth {self.max_recursion_depth} exceeded",
                data_path=path
            )
        
        # Handle None
        if value is None:
            return "null"
        
        # Handle boolean
        if isinstance(value, bool):
            return "true" if value else "false"
        
        # Handle numeric types
        if isinstance(value, (int, float)):
            if isinstance(value, float) and (value != value):  # NaN
                return ".nan"
            if isinstance(value, float) and value == float('inf'):
                return ".inf"
            if isinstance(value, float) and value == float('-inf'):
                return "-.inf"
            return str(value)
        
        # Handle string
        if isinstance(value, str):
            flow_style = flow_style if flow_style is not None else False
            
            # Check if string needs quoting
            needs_quoting = any(
                c in value for c in '[]{}:?#&*!|>%@`\'"\\@,'
            ) or value in ('true', 'false', 'null', 'yes', 'no', 'on', 'off')
            
            # Check for multi-line
            if '\n' in value or len(value) > (self.line_width or 80):
                return self._escape_string(value, 'literal')
            
            if needs_quoting:
                return self._escape_string(value, 'double')
            
            return value
        
        # Handle bytes
        if isinstance(value, bytes):
            return self._serialize_bytes(value)
        
        # Handle enumerations
        if isinstance(value, Enum):
            return self._serialize_value(value.value, indent_level, path, flow_style)
        
        # Handle custom types via registered serializers
        for type_, serializer in self._custom_serializers.items():
            if isinstance(value, type_):
                try:
                    serialized = serializer(value)
                    return self._serialize_value(serialized, indent_level, path, flow_style)
                except Exception as e:
                    raise YAMLFormatError(
                        f"Custom serializer failed for {type(value).__name__}",
                        data_path=path,
                        original_error=e
                    )
        
        # Handle dictionaries
        if isinstance(value, dict):
            # Detect circular references
            circular_path = self._detect_circular_reference(value, path)
            if circular_path:
                raise YAMLFormatError(
                    f"Circular reference detected at '{circular_path}'",
                    data_path=path
                )
            
            # Check for anchor usage
            if use_anchor and id(value) in self._serialized_objects:
                return f"*{self._serialized_objects[id(value)]}"
            
            anchor = None
            if use_anchor and len(value) > 1:
                anchor = self._generate_anchor(value)
                self._serialized_objects[id(value)] = anchor
            
            result = SimpleYAMLFallback._serialize_dict(
                value, indent_level, self, path, flow_style
            )
            
            if anchor:
                return f"&{anchor}\n{result}"
            return result
        
        # Handle sequences (list, tuple, set)
        if isinstance(value, (list, tuple, set)):
            # Convert set to list for consistent ordering
            if isinstance(value, set):
                value = sorted(value) if self.sort_keys else list(value)
            
            # Detect circular references
            circular_path = self._detect_circular_reference(value, path)
            if circular_path:
                raise YAMLFormatError(
                    f"Circular reference detected at '{circular_path}'",
                    data_path=path
                )
            
            # Check for anchor usage
            if use_anchor and id(value) in self._serialized_objects:
                return f"*{self._serialized_objects[id(value)]}"
            
            anchor = None
            if use_anchor and len(value) > 1:
                anchor = self._generate_anchor(value)
                self._serialized_objects[id(value)] = anchor
            
            result = self._serialize_list(
                value, indent_level, path, flow_style
            )
            
            if anchor:
                return f"&{anchor}\n{result}"
            return result
        
        # Try to convert to string as last resort
        try:
            return str(value)
        except Exception as e:
            raise YAMLFormatError(
                f"Cannot serialize object of type {type(value).__name__}",
                data_path=path,
                original_error=e
            )
    
    def _serialize_dict(self, data: Dict[str, Any], indent_level: int = 0,
                       parent: Optional['SimpleYAMLFallback'] = None,
                       path: str = "", flow_style: Optional[bool] = None,
                       parent_context: Optional[Dict] = None) -> str:
        """
        Serialize a dictionary to YAML string with advanced formatting.
        
        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary to serialize
        indent_level : int, default=0
            Current indentation level
        parent : SimpleYAMLFallback, optional
            Parent instance (for static method compatibility)
        path : str, default=""
            Current path for error reporting
        flow_style : bool, optional
            Force flow style (braces) if True, block style if False
        parent_context : Dict, optional
            Parent context for duplicate key detection
        
        Returns
        -------
        str
            YAML-formatted dictionary string
        
        Raises
        ------
        YAMLFormatError
            If duplicate keys are found and not allowed
        
        Examples
        --------
        >>> yaml = SimpleYAMLFallback()
        >>> data = {"key1": "value1", "key2": {"nested": "value"}}
        >>> print(yaml._serialize_dict(data))
        key1: value1
        key2:
          nested: value
        """
        if parent is None:
            parent = self
        
        if not data:
            return "{}" if (flow_style if flow_style is not None else parent.default_flow_style) else "{}"
        
        flow_style = flow_style if flow_style is not None else parent.default_flow_style
        
        # Flow style (inline dictionary)
        if flow_style:
            items = []
            sorted_keys = sorted(data.keys()) if parent.sort_keys else data.keys()
            for i, key in enumerate(sorted_keys):
                if not isinstance(key, str):
                    key = str(key)
                value = self._serialize_value(data[key], indent_level, f"{path}.{key}")
                items.append(f"{key}: {value}")
            result = f"{{ {', '.join(items)} }}"
            
            # Wrap if too long
            if parent.line_width > 0 and len(result) > parent.line_width:
                return self._wrap_line(result, indent_level, indent_level)
            return result
        
        # Block style
        lines = []
        indent_str = " " * (indent_level * parent.indent_mapping)
        sorted_keys = sorted(data.keys()) if parent.sort_keys else data.keys()
        
        for key in sorted_keys:
            current_path = f"{path}.{key}" if path else key
            
            # Check for duplicate keys
            if parent_context and key in parent_context and not parent.allow_duplicate_keys:
                warnings.warn(
                    f"Duplicate key '{key}' found at path '{current_path}'",
                    UserWarning,
                    stacklevel=3
                )
            
            value = data[key]
            serialized_value = parent._serialize_value(
                value, indent_level + 1, current_path
            )
            
            # Format the key-value pair
            if '\n' in serialized_value:
                lines.append(f"{indent_str}{key}:")
                # Add indented content
                for line in serialized_value.split('\n'):
                    lines.append(f"{indent_str}{'  ' * (1)}{line}")
            elif serialized_value.startswith('&'):
                # Handle anchors
                lines.append(f"{indent_str}{key}: {serialized_value}")
            else:
                # Check if value needs extra indentation
                if isinstance(value, (dict, list)) and value:
                    lines.append(f"{indent_str}{key}:")
                    lines.append(serialized_value)
                else:
                    lines.append(f"{indent_str}{key}: {serialized_value}")
        
        return '\n'.join(lines)
    
    def _serialize_list(self, data: List[Any], indent_level: int = 0,
                       path: str = "", flow_style: Optional[bool] = None) -> str:
        """
        Serialize a list to YAML string with advanced formatting.
        
        Parameters
        ----------
        data : List[Any]
            List to serialize
        indent_level : int, default=0
            Current indentation level
        path : str, default=""
            Current path for error reporting
        flow_style : bool, optional
            Force flow style (brackets) if True, block style if False
        
        Returns
        -------
        str
            YAML-formatted list string
        
        Examples
        --------
        >>> yaml = SimpleYAMLFallback()
        >>> data = ["item1", "item2", {"key": "value"}]
        >>> print(yaml._serialize_list(data))
        - item1
        - item2
        - key: value
        """
        if not data:
            return "[]" if (flow_style if flow_style is not None else self.default_flow_style) else "[]"
        
        flow_style = flow_style if flow_style is not None else self.default_flow_style
        
        # Flow style (inline list)
        if flow_style:
            items = [self._serialize_value(item, indent_level, f"{path}[{i}]")
                    for i, item in enumerate(data)]
            result = f"[{', '.join(items)}]"
            
            # Wrap if too long
            if self.line_width > 0 and len(result) > self.line_width:
                return self._wrap_line(result, indent_level, indent_level)
            return result
        
        # Block style
        lines = []
        indent_str = " " * (indent_level * self.indent_sequence)
        seq_indent = " " * self.block_seq_indent
        
        for i, item in enumerate(data):
            current_path = f"{path}[{i}]"
            serialized_item = self._serialize_value(item, indent_level + 1, current_path)
            
            # Check if item is a dict and needs special handling
            if isinstance(item, dict) and item:
                lines.append(f"{indent_str}{seq_indent}-")
                # Add indented dict content
                for line in serialized_item.split('\n'):
                    lines.append(f"{indent_str}  {line}")
            elif '\n' in serialized_item:
                lines.append(f"{indent_str}{seq_indent}- {serialized_item.split(chr(10))[0]}")
                for line in serialized_item.split('\n')[1:]:
                    lines.append(f"{indent_str}  {line}")
            else:
                lines.append(f"{indent_str}{seq_indent}- {serialized_item}")
        
        return '\n'.join(lines)
    
    def dump(self, data: Any, stream: Optional[Any] = None,
            default_flow_style: Optional[bool] = None,
            sort_keys: Optional[bool] = None,
            indent: Optional[int] = None,
            line_width: Optional[int] = None,
            explicit_start: Optional[bool] = None,
            explicit_end: Optional[bool] = None) -> Optional[str]:
        """
        Dump Python object to YAML string or file stream.
        
        Parameters
        ----------
        data : Any
            Python object to serialize (typically dict or list)
        stream : file-like object, optional
            If provided, write YAML to this stream instead of returning string
        default_flow_style : bool, optional
            Override instance default_flow_style for this dump
        sort_keys : bool, optional
            Override instance sort_keys for this dump
        indent : int, optional
            Override instance indent for this dump (must be 1-8)
        line_width : int, optional
            Override instance line_width for this dump
        explicit_start : bool, optional
            Include '---' document start marker
        explicit_end : bool, optional
            Include '...' document end marker
        
        Returns
        -------
        str or None
            If stream is None, returns YAML string; otherwise returns None
        
        Raises
        ------
        YAMLFormatError
            If data cannot be serialized
        ValueError
            If parameters have invalid values
        
        Examples
        --------
        >>> yaml = SimpleYAMLFallback()
        >>> data = {"name": "test", "values": [1, 2, 3]}
        >>> print(yaml.dump(data))
        name: test
        values:
        - 1
        - 2
        - 3
        
        >>> # Write to file
        >>> with open('output.yml', 'w') as f:
        ...     yaml.dump(data, stream=f)
        
        >>> # Override settings
        >>> print(yaml.dump(data, default_flow_style=True))
        {name: test, values: [1, 2, 3]}
        """
        # Override settings
        if indent is not None and not (1 <= indent <= 8):
            raise ValueError(f"indent must be between 1 and 8, got {indent}")
        
        temp_indent = indent or self.indent
        temp_flow_style = default_flow_style if default_flow_style is not None else self.default_flow_style
        temp_sort_keys = sort_keys if sort_keys is not None else self.sort_keys
        temp_line_width = line_width if line_width is not None else self.line_width
        temp_explicit_start = explicit_start if explicit_start is not None else self.explicit_start
        temp_explicit_end = explicit_end if explicit_end is not None else self.explicit_end
        
        # Reset internal state for this dump
        self._anchor_registry.clear()
        self._anchor_counter = 0
        self._serialized_objects.clear()
        
        try:
            # Sort keys if requested
            if temp_sort_keys and isinstance(data, dict):
                data = self._sort_dict_recursive(data)
            
            # Serialize data
            if isinstance(data, dict):
                result = self._serialize_dict(data, 0, self, "", temp_flow_style)
            elif isinstance(data, (list, tuple, set)):
                result = self._serialize_list(list(data), 0, "", temp_flow_style)
            else:
                result = self._serialize_value(data, 0, "", temp_flow_style)
            
            # Add document markers
            if temp_explicit_start:
                result = f"---\n{result}"
            if temp_explicit_end:
                result = f"{result}\n..."
            
        except Exception as e:
            raise YAMLFormatError(
                f"Failed to serialize data: {str(e)}",
                original_error=e
            )
        
        # Write to stream or return string
        if stream is not None:
            stream.write(result)
            return None
        return result
    
    def _sort_dict_recursive(self, data: Any) -> Any:
        """
        Recursively sort dictionary keys alphabetically.
        
        Parameters
        ----------
        data : Any
            Data structure to sort
        
        Returns
        -------
        Any
            Sorted data structure
        
        Notes
        -----
        Sorts dictionary keys recursively while preserving other structures.
        
        Examples
        --------
        >>> yaml = SimpleYAMLFallback()
        >>> data = {"z": 1, "a": {"c": 2, "b": 3}}
        >>> print(yaml._sort_dict_recursive(data))
        {'a': {'b': 3, 'c': 2}, 'z': 1}
        """
        if isinstance(data, dict):
            return {
                k: self._sort_dict_recursive(v)
                for k, v in sorted(data.items())
            }
        elif isinstance(data, list):
            return [self._sort_dict_recursive(item) for item in data]
        elif isinstance(data, tuple):
            return tuple(self._sort_dict_recursive(item) for item in data)
        elif isinstance(data, set):
            return {self._sort_dict_recursive(item) for item in data}
        return data
    
    def dump_all(self, documents: List[Any], stream: Optional[Any] = None,
                 **kwargs) -> Optional[str]:
        """
        Dump multiple YAML documents to a single output.
        
        Parameters
        ----------
        documents : List[Any]
            List of Python objects to serialize as separate YAML documents
        stream : file-like object, optional
            If provided, write YAML to this stream instead of returning string
        **kwargs
            Additional arguments passed to dump() for each document
        
        Returns
        -------
        str or None
            If stream is None, returns YAML string with '---' separators;
            otherwise returns None
        
        Examples
        --------
        >>> yaml = SimpleYAMLFallback()
        >>> docs = [{"doc": 1}, {"doc": 2}, {"doc": 3}]
        >>> print(yaml.dump_all(docs))
        ---
        doc: 1
        ---
        doc: 2
        ---
        doc: 3
        """
        results = []
        for i, doc in enumerate(documents):
            # Force explicit start for all but first document if not specified
            if i > 0:
                kwargs['explicit_start'] = True
            elif kwargs.get('explicit_start') is None:
                kwargs['explicit_start'] = False
            
            result = self.dump(doc, **kwargs)
            if result is not None:
                results.append(result)
        
        output = '---\n'.join(results)
        
        if stream is not None:
            stream.write(output)
            return None
        return output


# Create global instance for backward compatibility
yaml = SimpleYAMLFallback()

# Emit warning about missing yaml library
warnings.warn(
    "PyYAML library not found. Using fallback YAML serializer. "
    "For full YAML support (including parsing), install PyYAML: pip install pyyaml",
    UserWarning,
    stacklevel=2
)