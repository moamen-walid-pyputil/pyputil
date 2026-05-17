#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
PypUtil Core Static Code Analysis - SCA

Unified Parser Interface Module.

This module provides a single, intuitive entry point for accessing multiple
Python code analysis parsers through a unified function interface. It
abstracts away the complexity of selecting and initializing the appropriate
parser for different analysis needs, supporting source code strings,
file paths, and live Python objects.

The module integrates four specialized parsers:

- **StringParser**: Regex-based static analysis of raw source code strings.
- **CodeParser**: Bytecode-level analysis for deep structural inspection.
- **SourceParser**: Source code extraction and file-based analysis.
- **ObjectParser**: Runtime introspection of live Python objects.

By providing a single ``Source()`` function, this module simplifies
meta-programming, dynamic analysis, and code inspection workflows.

Supported Input Types
---------------------
- Raw Python source code strings
- File paths to ``.py`` files
- Live Python objects (modules, classes, functions, instances)

Parser Selection Guide
----------------------
+--------------------+----------------------------------+----------------------+
| Parser             | Best For                         | Input Type           |
+====================+==================================+======================+
| ``string.parser``  | Static text analysis, patterns   | Source code string   |
+--------------------+----------------------------------+----------------------+
| ``code.parser``    | Bytecode inspection, complexity  | Source code string   |
+--------------------+----------------------------------+----------------------+
| ``source.parser``  | File operations, source retrieval| File path or object  |
+--------------------+----------------------------------+----------------------+
| ``object.parser``  | Runtime introspection, metadata  | Live Python object   |
+--------------------+----------------------------------+----------------------+

See Also
--------
StringParser : Regex-based static source analysis.
CodeParser : Bytecode-level code analysis.
SourceParser : Source file and code extraction.
ObjectParser : Runtime object introspection.

Examples
--------
>>> from pyputil.core.sca import Source

>>> # Analyze source code with bytecode parser
>>> code = "def greet(name: str) -> str: return f'Hello, {name}'"
>>> parser = Source(code, parser="code.parser")
>>> result = parser.analyze()
>>> result.functions[0].name
'greet'

>>> # Analyze a Python file with string parser
>>> parser = Source("/path/to/module.py", target="file", parser="string.parser")
>>> funcs = parser.functions()
>>> len(funcs) > 0
True

>>> # Inspect a live object
>>> import math
>>> parser = Source(math, parser="object.parser")
>>> 'sqrt' in dir(parser.obj)
True
"""

from typing import Any, Union, Optional, Type, overload, Literal, get_type_hints
from pathlib import Path
import inspect
import warnings

# Import parsers from their respective modules
from ._string_parser import StringParser
from ._code_parser import CodeParser
from ._source_parser import SourceParser
from ._object_parser import ObjectParser


# ============================================================================
# Type Aliases
# ============================================================================

# Supported parser identifiers
_ParserType = Literal[
    "string.parser",
    "code.parser",
    "source.parser",
    "object.parser",
]

# Supported target modes
_TargetType = Literal[
    "source",
    "file",
    "object",
]

# Union of all supported parser instances
_ParserInstance = Union[
    StringParser,
    CodeParser,
    SourceParser,
    ObjectParser,
]

# Mapping from parser identifier to parser class
_PARSER_CLASS_MAP = {
    "string.parser": StringParser,
    "code.parser": CodeParser,
    "source.parser": SourceParser,
    "object.parser": ObjectParser,
}

# Set of valid parser names for validation
_VALID_PARSERS = frozenset(_PARSER_CLASS_MAP.keys())

# Set of valid target modes for validation
_VALID_TARGETS = frozenset({"source", "file", "object"})


# ============================================================================
# Validation Helpers
# ============================================================================


def _validate_parser_name(parser: str) -> str:
    """
    Validate and normalize a parser identifier string.

    Performs case-insensitive matching and whitespace stripping to
    ensure robust parser selection even with inconsistent input
    formatting.

    Parameters
    ----------
    parser : str
        Raw parser identifier string. Can be mixed case and may
        contain leading/trailing whitespace.

    Returns
    -------
    str
        Normalized (lowercase, stripped) parser identifier.

    Raises
    ------
    ValueError
        If the parser identifier is not one of the supported values:
        ``'string.parser'``, ``'code.parser'``, ``'source.parser'``,
        or ``'object.parser'``. The error message lists all valid
        options.

    Examples
    --------
    >>> _validate_parser_name("  Code.Parser  ")
    'code.parser'

    >>> _validate_parser_name("invalid.parser")
    Traceback (most recent call last):
        ...
    ValueError: Invalid parser: 'invalid.parser'. ...
    """
    normalized = parser.lower().strip()

    if normalized not in _VALID_PARSERS:
        valid_list = "', '".join(sorted(_VALID_PARSERS))
        raise ValueError(
            f"Invalid parser: {parser!r}. "
            f"Expected one of: '{valid_list}'."
        )

    return normalized


def _validate_target_name(target: str) -> str:
    """
    Validate and normalize a target mode string.

    Performs case-insensitive matching and whitespace stripping for
    robust target mode selection.

    Parameters
    ----------
    target : str
        Raw target mode string. Can be mixed case and may contain
        leading/trailing whitespace.

    Returns
    -------
    str
        Normalized (lowercase, stripped) target mode.

    Raises
    ------
    ValueError
        If the target mode is not one of the supported values:
        ``'source'``, ``'file'``, or ``'object'``. The error message
        lists all valid options.

    Examples
    --------
    >>> _validate_target_name("  File  ")
    'file'

    >>> _validate_target_name("invalid")
    Traceback (most recent call last):
        ...
    ValueError: Invalid target: 'invalid'. ...
    """
    normalized = target.lower().strip()

    if normalized not in _VALID_TARGETS:
        valid_list = "', '".join(sorted(_VALID_TARGETS))
        raise ValueError(
            f"Invalid target: {target!r}. "
            f"Expected one of: '{valid_list}'."
        )

    return normalized


def _is_file_path(obj: Any) -> bool:
    """
    Determine if an object likely represents a file path.

    This heuristic checks whether the input is a string (or Path)
    that could refer to an existing ``.py`` file.

    Parameters
    ----------
    obj : Any
        Object to evaluate as a potential file path.

    Returns
    -------
    bool
        True if ``obj`` is a string or ``Path`` instance that points
        to an existing ``.py`` file. False for all other types and
        for strings that do not exist as files.

    Notes
    -----
    - Only checks for existence on the filesystem for strings and
      Path objects.
    - Does not verify that the file contains valid Python code.
    - Returns False for non-string, non-Path objects without raising.

    Examples
    --------
    >>> _is_file_path("/path/to/existing.py")  # doctest: +SKIP
    True

    >>> _is_file_path("def func(): pass")
    False

    >>> _is_file_path(42)
    False
    """
    if isinstance(obj, (str, Path)):
        path = Path(obj)
        return path.exists() and path.suffix == '.py'
    return False


# ============================================================================
# Main Unified Parser Function
# ============================================================================


def Source(
    obj: Any,
    parser: str = "source.parser",
    target: Optional[str] = None,
) -> _ParserInstance:
    """
    Create and return an appropriate parser instance based on input type.

    This function serves as the unified entry point for all code analysis
    needs, automatically selecting and configuring the correct parser based
    on the desired analysis type and input characteristics. It abstracts
    away the complexity of parser selection, input normalization, and
    initialization.

    The function supports three input modes (controlled by ``target``):

    1. **Source mode** (``target="source"``):
       Treats ``obj`` as raw Python source code. The source is passed
       directly to the selected parser.

    2. **File mode** (``target="file"``):
       Treats ``obj`` as a file path. The file contents are read and
       passed to the selected parser.

    3. **Object mode** (``target="object"``):
       Passes ``obj`` directly to the selected parser without any
       preprocessing. Required for ``object.parser``.

    When ``target`` is ``None`` (default), the function applies
    automatic detection:

    - If ``parser`` is ``"object.parser"``, ``target`` defaults to
      ``"object"``.
    - Otherwise, if ``obj`` appears to be a file path, ``target``
      defaults to ``"file"``.
    - Otherwise, ``target`` defaults to ``"source"``.

    Parameters
    ----------
    obj : Any
        The input data to be parsed. The interpretation depends on the
        ``target`` parameter:

        - When ``target="source"``: A string of Python source code.
        - When ``target="file"``: A file path (``str`` or ``Path``)
          pointing to a ``.py`` file.
        - When ``target="object"``: Any live Python object (module,
          class, function, instance, etc.).

    parser : str, optional
        Specifies which parser class to instantiate. Accepted values
        (case-insensitive):

        - ``"string.parser"``: :class:`StringParser` for regex-based
          static analysis of source code strings.
        - ``"code.parser"``: :class:`CodeParser` for bytecode-level
          structural analysis.
        - ``"source.parser"``: :class:`SourceParser` for source code
          extraction, file management, and code manipulation.
        - ``"object.parser"``: :class:`ObjectParser` for runtime
          introspection of live Python objects.

        Default is ``"source.parser"``.

    target : str or None, optional
        Specifies how ``obj`` should be interpreted before passing to
        the parser. Accepted values (case-insensitive):

        - ``"source"``: Treat ``obj`` as raw source code text.
        - ``"file"``: Treat ``obj`` as a file path and read its contents.
        - ``"object"``: Pass ``obj`` directly (no preprocessing).

        If ``None`` (default), automatic detection is applied based on
        the parser type and object characteristics. See Notes for details.

    Returns
    -------
    Union[StringParser, CodeParser, SourceParser, ObjectParser]
        A fully initialized parser instance of the requested type,
        ready for analysis. The specific return type depends on the
        ``parser`` parameter:

        - ``"string.parser"`` → :class:`StringParser`
        - ``"code.parser"`` → :class:`CodeParser`
        - ``"source.parser"`` → :class:`SourceParser`
        - ``"object.parser"`` → :class:`ObjectParser`

    Raises
    ------
    ValueError
        If ``parser`` or ``target`` contain unsupported values.
        The error message lists all valid options.
    FileNotFoundError
        If ``target="file"`` and the specified file does not exist
        or cannot be read.
    TypeError
        If ``target="source"`` and ``obj`` is not a string, or if
        ``target="object"`` but ``parser`` does not support object
        input.
    SyntaxError
        If ``parser="code.parser"`` and the source code contains
        syntax errors (propagated from :class:`CodeParser`).

    Warnings
    --------
    UserWarning
        If automatic target detection is ambiguous (e.g., when a
        string looks like both source code and a file path).

    Notes
    -----
    **Automatic Target Detection** (when ``target=None``):

    The detection follows this priority:

    1. If ``parser`` is ``"object.parser"``, ``target`` is set to
       ``"object"`` (object parsers always receive objects directly).
    2. If ``obj`` appears to be a file path (exists on disk with
       ``.py`` extension), ``target`` is set to ``"file"``.
    3. Otherwise, ``target`` is set to ``"source"``.

    **Parser Initialization Details**:

    - ``StringParser(source_code)``: Initialized with a source string.
    - ``CodeParser(source_code)``: Initialized with a source string,
      compiled to bytecode.
    - ``SourceParser(object)``: Initialized with any Python object,
      supports source extraction and file operations.
    - ``ObjectParser(object)``: Initialized with any Python object,
      performs runtime introspection.

    **Best Practices**:

    - Use ``parser="string.parser"`` for quick static analysis of
      source code patterns, imports, and structure.
    - Use ``parser="code.parser"`` for deep analysis requiring
      bytecode inspection, complexity metrics, and control flow.
    - Use ``parser="source.parser"`` when you need file operations,
      source extraction, or code transformation.
    - Use ``parser="object.parser"`` for runtime introspection of
      live objects, attributes, and metadata.

    See Also
    --------
    StringParser : Regex-based static source analysis.
    CodeParser : Bytecode-level code analysis.
    SourceParser : Source file and code extraction.
    ObjectParser : Runtime object introspection.

    Examples
    --------
    **Basic usage with explicit parameters:**

    >>> code = '''
    ... def add(a: int, b: int) -> int:
    ...     return a + b
    ... '''
    >>> parser = Source(code, parser="code.parser", target="source")
    >>> result = parser.analyze()
    >>> result.functions[0].name
    'add'

    **Automatic target detection from file path:**

    >>> # Assuming '/path/to/module.py' exists
    >>> parser = Source("/path/to/module.py", parser="string.parser")  # doctest: +SKIP
    >>> funcs = parser.functions()  # doctest: +SKIP

    **Object introspection:**

    >>> import math
    >>> parser = Source(math, parser="object.parser")
    >>> parser.type_name
    'module'
    >>> 'sqrt' in parser.attrs
    True

    **Source parser for code extraction:**

    >>> def greet(name: str) -> str:
    ...     '''Return a greeting.'''
    ...     return f"Hello, {name}!"
    ...
    >>> parser = Source(greet, parser="source.parser", target="object")
    >>> parser.name
    'greet'
    >>> parser.source.startswith('def greet')
    True

    **Using defaults (source.parser with auto-detection):**

    >>> parser = Source("x = 42")
    >>> type(parser).__name__
    'SourceParser'
    """
    # ------------------------------------------------------------------
    # Step 1: Normalize and validate parameters
    # ------------------------------------------------------------------
    parser = _validate_parser_name(parser)

    if target is not None:
        target = _validate_target_name(target)

    # ------------------------------------------------------------------
    # Step 2: Auto-detect target mode if not explicitly specified
    # ------------------------------------------------------------------
    if target is None:
        if parser == "object.parser":
            # Object parser always operates on objects directly
            target = "object"
        elif _is_file_path(obj):
            # Input looks like a file path
            target = "file"
            warnings.warn(
                f"Auto-detected target='file' for input: {obj!r}. "
                f"If this is source code, specify target='source' explicitly.",
                UserWarning,
                stacklevel=2,
            )
        else:
            # Default: treat as source code
            target = "source"

    # ------------------------------------------------------------------
    # Step 3: Resolve the actual data to pass to the parser
    # ------------------------------------------------------------------
    if target == "source":
        # Validate that obj is suitable as source code
        if not isinstance(obj, (str, bytes)):
            raise TypeError(
                f"target='source' requires a string or bytes input, "
                f"got {type(obj).__name__}. "
                f"Use target='file' for file paths or target='object' for objects."
            )
        source_data = obj

    elif target == "file":
        # Read the file contents
        file_path = Path(obj)
        if not file_path.exists():
            raise FileNotFoundError(
                f"File not found: {file_path}. "
                f"Please verify the file path and try again."
            )
        if not file_path.is_file():
            raise FileNotFoundError(
                f"Path exists but is not a file: {file_path}. "
                f"Please provide a path to a regular file."
            )
        try:
            source_data = file_path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            # Fall back to reading as bytes if UTF-8 fails
            source_data = file_path.read_bytes()
            warnings.warn(
                f"File {file_path} could not be read as UTF-8. "
                f"Read as bytes instead.",
                UserWarning,
                stacklevel=2,
            )

    elif target == "object":
        # Pass the object directly
        source_data = obj

    else:
        # Should never reach here due to validation above
        raise ValueError(f"Unexpected target value: {target!r}")

    # ------------------------------------------------------------------
    # Step 4: Create and return the appropriate parser instance
    # ------------------------------------------------------------------
    if parser == "string.parser":
        return StringParser(source_data)

    elif parser == "code.parser":
        return CodeParser(source_data)

    elif parser == "object.parser":
        return ObjectParser(source_data)

    elif parser == "source.parser":
        return SourceParser(source_data)

    else:
        # Should never reach here due to validation above
        raise ValueError(f"Unexpected parser value: {parser!r}")


# ============================================================================
# Convenience Functions
# ============================================================================


def parse_string(source_code: str) -> StringParser:
    """
    Convenience function to create a StringParser for static analysis.

    This is equivalent to calling ``Source(source_code, parser="string.parser")``.

    Parameters
    ----------
    source_code : str
        Python source code as a string.

    Returns
    -------
    StringParser
        Initialized StringParser instance ready for analysis.

    Examples
    --------
    >>> parser = parse_string("def hello(): return 'world'")
    >>> funcs = parser.functions()
    >>> funcs[0].name
    'hello'
    """
    return StringParser(source_code)


def parse_code(source_code: str) -> CodeParser:
    """
    Convenience function to create a CodeParser for bytecode analysis.

    This is equivalent to calling ``Source(source_code, parser="code.parser")``.

    Parameters
    ----------
    source_code : str
        Python source code as a string.

    Returns
    -------
    CodeParser
        Initialized CodeParser instance ready for analysis.

    Raises
    ------
    ValueError
        If the source code contains syntax errors.

    Examples
    --------
    >>> parser = parse_code("def add(a, b): return a + b")
    >>> result = parser.analyze()
    >>> result.functions[0].name
    'add'
    """
    return CodeParser(source_code)


def parse_file(file_path: Union[str, Path]) -> SourceParser:
    """
    Convenience function to create a SourceParser for file-based analysis.

    This is equivalent to calling
    ``Source(file_path, parser="source.parser", target="file")``.

    Parameters
    ----------
    file_path : str or Path
        Path to a Python source file.

    Returns
    -------
    SourceParser
        Initialized SourceParser instance ready for analysis.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.

    Examples
    --------
    >>> parser = parse_file("/path/to/module.py")  # doctest: +SKIP
    >>> parser.line_count > 0  # doctest: +SKIP
    True
    """
    return Source(file_path, parser="source.parser", target="file")


def parse_object(obj: Any) -> ObjectParser:
    """
    Convenience function to create an ObjectParser for runtime introspection.

    This is equivalent to calling ``Source(obj, parser="object.parser")``.

    Parameters
    ----------
    obj : Any
        Any Python object to introspect.

    Returns
    -------
    ObjectParser
        Initialized ObjectParser instance ready for analysis.

    Examples
    --------
    >>> import math
    >>> parser = parse_object(math)
    >>> 'pi' in parser.attrs
    True
    """
    return ObjectParser(obj)


# ============================================================================
# Module-Level Information
# ============================================================================

__all__ = [
    "Source",
    "parse_string",
    "parse_code",
    "parse_file",
    "parse_object",
    "StringParser",
    "CodeParser",
    "SourceParser",
    "ObjectParser",
]


from ...api import clean
clean(expose=__all__)