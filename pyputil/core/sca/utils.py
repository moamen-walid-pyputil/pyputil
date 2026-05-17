#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
 Python Object Introspection and Utility Functions.

This module provides a comprehensive set of utilities for deep Python
object inspection, callable manipulation, code extraction, execution
tracing, and attribute management. All functions are designed with
robust error handling and optimized for both performance and reliability.

The utilities support:
- Example extraction from docstrings with multiple parsing strategies
- Universal callable wrapping with recursive processing
- Deep callable unwrapping through decorator chains
- Code object extraction from any callable
- Multi-threaded execution tracing with weak references
- Dynamic dictionary creation for arbitrary objects

Notes
-----
- All functions handle edge cases gracefully with comprehensive error handling
- Thread-safety considerations are documented where applicable
- Caching strategies are employed for performance-critical paths

See Also
--------
inspect : Standard library module for object introspection.
functools : Higher-order functions and callable manipulation.
textwrap : Text formatting utilities.

References
----------
.. [1] Python Documentation: inspect — Inspect live objects.
   https://docs.python.org/3/library/inspect.html
.. [2] Python Documentation: functools — Higher-order functions.
   https://docs.python.org/3/library/functools.html
"""

from collections.abc import Iterable as IterableABC
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from dataclasses import dataclass, field, asdict
from functools import reduce, partial
from pathlib import Path
from typing import (
    Any, List, Dict, Optional, Set, Callable, Union, Iterable,
    Tuple, FrozenSet, Type, TypeVar, overload, Literal,
)
import asyncio
import functools
import importlib
import inspect
import pkgutil
import re
import sys
import textwrap
import threading
import types
import weakref
import warnings


# ============================================================================
# Type Aliases
# ============================================================================

_T = TypeVar('_T')
_MapFunc = Optional[Callable[[Any], Any]]
_FilterFunc = Optional[Callable[[Any], bool]]
_ReduceFunc = Optional[Callable[[Any, Any], Any]]

# ============================================================================
# 1. Example Extraction from Docstrings
# ============================================================================


def _extract_examples_from_docstring(doc: str) -> List[str]:
    """
    Extract example blocks from a docstring based on conventional section titles.

    This function implements a multi-strategy approach to locate and extract
    example sections from docstrings formatted in various popular styles:

    - **Google-style**: ``Example:`` or ``Examples:`` sections.
    - **NumPy-style**: ``Examples`` followed by a dashed underline (``---``).
    - **reStructuredText-style**: ``:Example:`` or ``:Examples:`` directives.
    - **Plain-text**: ``Usage:`` sections.

    The extraction process uses a carefully crafted regular expression that
    identifies section headers and captures all content until the next section
    or the end of the docstring. The captured content is dedented and stripped
    of extraneous whitespace.

    Parameters
    ----------
    doc : str
        The docstring text to parse. May be an empty string. If ``doc`` is
        falsy (empty or None), an empty list is returned immediately without
        processing.

    Returns
    -------
    List[str]
        A list of cleaned example blocks as strings, each representing one
        distinct example section. If no examples are found or the docstring
        is empty, an empty list ``[]`` is returned. Each block has been:

        - Dedented to the left margin using :func:`textwrap.dedent`.
        - Stripped of leading and trailing whitespace.

    Notes
    -----
    **Pattern Details**:

    The extraction regex has the following structure:

    .. code-block:: text

        (?:^|\n)                    # Start of a line
        (?:Example[s]?|Usage|:Example:|:Examples:)
        \s*:?\s*                    # Optional colon and whitespace
        (?:-{3,})?                  # Optional dashed underline (NumPy style)
        \n+
        (                           # Capture group 1: example content
            (?:
                (?!\n\S) .*\n?     # Lines that are not section headers
            )+?
        )
        (?=\n\S|$)                  # Stop before next section or at EOF

    The expression is compiled with ``re.IGNORECASE | re.VERBOSE`` flags
    for case-insensitive matching and extended pattern readability.

    **Edge Cases Handled**:

    - Empty or falsy docstrings return immediately.
    - Multiple example sections are each captured separately.
    - Section headers with trailing colons (``:``) are supported.
    - NumPy-style underlines (``Examples ---``) are properly handled.
    - Blocks containing blank lines are preserved until a new section header
      is detected.

    Examples
    --------
    >>> doc = '''
    ... This is some documentation.
    ...
    ... Examples
    ... --------
    ... >>> result = my_func(1, 2)
    ... >>> print(result)
    ... 3
    ...
    ... Notes
    ... -----
    ... Some additional notes.
    ... '''
    >>> blocks = _extract_examples_from_docstring(doc)
    >>> len(blocks)
    1
    >>> '>>> result = my_func(1, 2)' in blocks[0]
    True

    >>> doc = "No examples here."
    >>> _extract_examples_from_docstring(doc)
    []

    >>> _extract_examples_from_docstring("")
    []
    """
    examples: List[str] = []

    # Early exit for empty docstrings
    if not doc:
        return examples

    # Normalize indentation before processing
    doc = textwrap.dedent(doc)

    # Comprehensive pattern matching multiple docstring styles
    pattern = r"""
        (?:^|\n)                              # Start of line or newline
        (?:
            Example[s]?                        # Example/Examples
            | Usage                            # Usage
            | :Example[s]?:                     # :Example:/:Examples: (RST)
        )
        \s*:?\s*                               # Optional colon and whitespace
        (?:-{3,})?                              # Optional dashed underline (NumPy)
        \n+                                     # One or more newlines
        (                                       # Capture group: example content
            (?:
                (?!\n\S) .*\n?                  # Lines until next section or EOF
            )+?
        )
        (?=\n\S|$)                               # Lookahead: next section or EOF
    """

    # Compile with IGNORECASE and VERBOSE flags for robust matching
    compiled_pattern = re.compile(pattern, re.IGNORECASE | re.VERBOSE)

    matches = compiled_pattern.findall(doc)

    # Process each captured block
    for match in matches:
        block = textwrap.dedent(match).strip()
        if block:
            examples.append(block)

    return examples


def _extract_doctest_examples(doc: str) -> List[str]:
    """
    Extract interactive Python example lines formatted in doctest style.

    This function identifies and extracts code blocks that follow the
    standard Python doctest convention, where interactive examples are
    prefixed with ``>>>`` for primary lines and ``...`` for continuation
    lines. These blocks are commonly used in documentation for usage
    demonstrations and automated testing.

    The extraction handles:

    - Single-line doctest examples: ``>>> func(42)``.
    - Multi-line doctest examples with continuation::

        >>> for i in range(3):
        ...     print(i)

    - Multiple doctest blocks within a single docstring.

    Parameters
    ----------
    doc : str
        The docstring text to scan for doctest examples. May be empty
        or ``None``; in such cases an empty list is returned.

    Returns
    -------
    List[str]
        A list of extracted doctest blocks, each as a single dedented
        string. The blocks are returned in the order they appear in the
        docstring. If no doctest examples are found, an empty list is
        returned.

    Notes
    -----
    **Pattern**:

    .. code-block:: text

        (?m)^\s*>>> .+(?:\n\s*\.\.\. .+)*

    - ``(?m)`` enables multiline mode for ``^`` anchors.
    - ``^\s*>>> .+`` matches lines starting with ``>>>`` (after optional
      whitespace).
    - ``(?:\n\s*\.\.\. .+)*`` matches zero or more continuation lines
      starting with ``...``.

    **Limitations**:

    - Only standard doctest syntax is supported (``>>>`` and ``...``).
    - Custom prompt strings (e.g., from alternative interpreters) are
      not detected.
    - The content after ``>>>``/``...`` is captured as-is without
      parsing or validation.

    Examples
    --------
    >>> doc = '''
    ... Here is how to use the function:
    ...
    ... >>> result = add(2, 3)
    ... >>> print(result)
    ... 5
    ...
    ... Multi-line example:
    ...
    ... >>> for i in range(3):
    ... ...     print(i)
    ... 0
    ... 1
    ... 2
    ... '''
    >>> blocks = _extract_doctest_examples(doc)
    >>> len(blocks)
    2
    >>> '>>> result = add(2, 3)' in blocks[0]
    True
    >>> '>>> for i in range(3):' in blocks[1]
    True

    >>> _extract_doctest_examples("No examples")
    []

    >>> _extract_doctest_examples("")
    []
    """
    examples: List[str] = []

    if not doc:
        return examples

    # Pattern for doctest examples with optional continuation lines
    pattern = r"(?m)^\s*>>> .+(?:\n\s*\.\.\. .+)*"
    matches = re.findall(pattern, doc)

    for match in matches:
        example = textwrap.dedent(match).strip()
        if example:
            examples.append(example)

    return examples


def _extract_codeblock_examples(doc: str) -> List[str]:
    """
    Extract fenced code blocks from docstrings (Markdown-style).

    This function identifies code blocks enclosed in triple backticks
    (`` ``` ``), with optional language specifiers like ``python``.
    These blocks are commonly used in modern documentation formats
    including Markdown and its variants (GitHub Flavored Markdown,
    MyST, etc.).

    The function supports:

    - Fenced blocks with language specifier: `` ```python ``.
    - Fenced blocks without language specifier: `` ``` ``.
    - Multiple code blocks within a single docstring.
    - Content captured between opening and closing fences, excluding
      the fence markers themselves.

    Parameters
    ----------
    doc : str
        The docstring text to scan for fenced code blocks. May be empty
        or ``None``; in such cases an empty list is returned.

    Returns
    -------
    List[str]
        A list of extracted code block contents, each as a dedented
        string. If no fenced code blocks are found, an empty list is
        returned.

    Notes
    -----
    **Pattern**:

    .. code-block:: text

        ```(?:python)?\\s*(.*?)\\s*```

    - `` ``` `` matches the opening fence.
    - ``(?:python)?`` optionally matches the language specifier.
    - ``\\s*`` matches optional whitespace after the opening fence.
    - ``(.*?)`` captures the code content (non-greedy).
    - ``\\s*``` `` matches the closing fence (with optional leading
      whitespace).

    **Flags**: ``re.DOTALL`` for multi-line matching, ``re.IGNORECASE``
    for case-insensitive language specifiers.

    **Limitations**:

    - Only triple-backtick fences are supported (not tildes ``~~~``).
    - Indented code blocks (4 spaces) are not detected.
    - Content is captured as-is; language specifier is not validated.

    Examples
    --------
    >>> doc = '''
    ... Here is an example:
    ...
    ... ```python
    ... def greet(name: str) -> str:
    ...     return f"Hello, {name}"
    ... ```
    ...
    ... And a plain block:
    ...
    ... ```
    ... print("No language specified")
    ... ```
    ... '''
    >>> blocks = _extract_codeblock_examples(doc)
    >>> len(blocks)
    2
    >>> 'def greet(name: str) -> str:' in blocks[0]
    True
    >>> 'print("No language specified")' in blocks[1]
    True

    >>> _extract_codeblock_examples("No code blocks here.")
    []
    """
    examples: List[str] = []

    if not doc:
        return examples

    # Pattern for triple-backtick fenced code blocks with optional language
    pattern = r"```(?:python)?\s*(.*?)\s*```"
    matches = re.findall(pattern, doc, re.DOTALL | re.IGNORECASE)

    for match in matches:
        code = textwrap.dedent(match).strip()
        if code:
            examples.append(code)

    return examples


def _generate_fallback_examples(obj: Any) -> List[str]:
    """
    Generate example calls based on an object's signature.

    When no examples are found in the docstring, this function creates
    synthetic example strings from the object's type and signature.
    The generated examples use placeholder values (``...`` for required
    arguments and the actual default value for optional arguments) to
    illustrate proper usage.

    The generation strategy varies by object type:

    - **Functions and methods**: Uses :func:`inspect.signature` to extract
      parameter names and defaults. Required parameters receive ``...``
      as placeholder; parameters with defaults display the default value.
    - **Classes**: Uses the ``__init__`` method signature (skipping
      ``self``) to generate constructor call examples. Falls back to
      ``ClassName()`` if signature extraction fails.
    - **Other objects**: Generates a generic ``obj_name(...)`` example.

    Parameters
    ----------
    obj : Any
        The Python object for which to generate examples. Can be a
        function, method, class, or any other callable/non-callable
        object.

    Returns
    -------
    List[str]
        A list containing one generated example string. If the object's
        name cannot be determined, the fallback name ``'obj'`` is used.
        The list always contains exactly one element (never empty).

    Notes
    -----
    **Robustness**: All operations are wrapped in try-except blocks to
    ensure that even malformed or unusual objects (e.g., C extensions,
    dynamically created classes) produce a usable example rather than
    raising exceptions.

    **Placeholder Convention**:

    - ``...`` indicates a required argument that the user must provide.
    - ``'default'`` (with quotes) shows the actual default value using
      ``repr()`` to ensure clarity for string defaults.

    **Limitations**:

    - The generated examples are syntactic illustrations and may not
      reflect actual valid usage if the object has complex validation
      or type constraints.
    - ``*args`` and ``**kwargs`` are not explicitly represented in the
      generated examples.

    Examples
    --------
    >>> def compute(x: int, y: int = 10) -> int:
    ...     return x * y
    ...
    >>> _generate_fallback_examples(compute)
    ['compute(x=..., y=10)']

    >>> class Calculator:
    ...     def __init__(self, precision: int = 2):
    ...         pass
    ...
    >>> _generate_fallback_examples(Calculator)
    ['Calculator(precision=2)']

    >>> _generate_fallback_examples(42)
    ['42(...)']
    """
    examples: List[str] = []

    try:
        if inspect.isfunction(obj) or inspect.ismethod(obj):
            name = getattr(obj, "__name__", "func")
            sig = inspect.signature(obj)

            args: List[str] = []
            for param in sig.parameters.values():
                if param.default is not param.empty:
                    # Show the actual default value using repr for clarity
                    args.append(f"{param.name}={param.default!r}")
                else:
                    # Required argument: use placeholder
                    args.append(f"{param.name}=...")

            examples.append(f"{name}({', '.join(args)})")

        elif inspect.isclass(obj):
            name = getattr(obj, "__name__", "ClassName")
            try:
                sig = inspect.signature(obj.__init__)
                args = [
                    f"{param.name}=..."
                    for param in list(sig.parameters.values())[1:]  # skip 'self'
                ]
                examples.append(f"{name}({', '.join(args)})")
            except (ValueError, TypeError, AttributeError):
                # Fallback for classes without __init__ or with broken signatures
                examples.append(f"{name}()")

        else:
            name = getattr(obj, "__name__", repr(obj))
            examples.append(f"{name}(...)")

    except (ValueError, TypeError, AttributeError):
        # Ultimate fallback: use object repr/name
        name = getattr(obj, "__name__", repr(obj))
        examples.append(f"{name}(...)")

    return examples


# ============================================================================
# Main Examples Extraction Function
# ============================================================================


def examples(obj: Any, text: bool = False) -> Union[List[str], str]:
    """
    Extract and deduplicate usage examples from any Python object's docstring.

    This function implements a comprehensive multi-stage extraction pipeline
    that attempts to locate usage examples through four independent strategies,
    applied in order of priority:

    1. **Section-based extraction** (:func:`_extract_examples_from_docstring`):
       Searches for dedicated ``Example``, ``Examples``, or ``Usage``
       sections in the docstring, supporting Google-style, NumPy-style,
       and reStructuredText formatting.

    2. **Doctest extraction** (:func:`_extract_doctest_examples`):
       Locates interactive Python examples prefixed with ``>>>``
       (and continuation lines with ``...``).

    3. **Code block extraction** (:func:`_extract_codeblock_examples`):
       Identifies Markdown-style fenced code blocks enclosed in triple
       backticks (`` ``` ``), with or without language specifiers.

    4. **Fallback generation** (:func:`_generate_fallback_examples`):
       If all extraction strategies return no results, generates synthetic
       example calls based on the object's signature and type.

    After extraction, all examples are deduplicated line-by-line while
    preserving the original order of first appearance.

    Parameters
    ----------
    obj : Any
        The Python object to extract examples from. Must have a
        ``__doc__`` attribute (or an empty string is used). Can be
        a module, class, function, method, or any object with a
        docstring.

    text : bool, optional
        Controls the output format.

        - If ``False`` (default), returns examples as a ``List[str]``
          where each string is one line of example code.
        - If ``True``, returns all example lines joined with newlines
          into a single ``str``.

    Returns
    -------
    Union[List[str], str]
        - ``List[str]``: When ``text=False``, a list of unique example
          lines in order of first appearance.
        - ``str``: When ``text=True``, a single string with all example
          lines joined by newline characters.

        If no examples are found anywhere, the generated fallback
        examples are used. The result is never empty; at minimum,
        one generated example is returned.

    Notes
    -----
    **Deduplication Logic**: The ``clean()`` inner function removes
    duplicate lines while preserving insertion order using a ``set``
    for tracking seen lines. This ensures that repeated examples
    (e.g., the same ``>>>`` block appearing in both section-based
    and doctest extraction) are included only once.

    **Performance**: Each extraction strategy is applied sequentially
    and lazily; if earlier strategies find examples, later strategies
    still execute to catch all possible examples. The fallback
    generation only activates when no examples are found at all.

    **Thread Safety**: This function is purely functional and does not
    modify any shared state, making it safe for concurrent use.

    Raises
    ------
    None
        All internal exceptions are caught and handled gracefully.
        Malformed docstrings, missing attributes, or signature errors
        will not propagate to the caller.

    See Also
    --------
    _extract_examples_from_docstring : Section-based extraction.
    _extract_doctest_examples : Doctest extraction.
    _extract_codeblock_examples : Code block extraction.
    _generate_fallback_examples : Signature-based generation.

    Examples
    --------
    >>> def add(a: int, b: int) -> int:
    ...     '''Add two numbers.
    ...
    ...     Examples
    ...     --------
    ...     >>> add(2, 3)
    ...     5
    ...     >>> add(-1, 1)
    ...     0
    ...     '''
    ...     return a + b
    ...
    >>> examples(add)
    ['>>> add(2, 3)', '5', '>>> add(-1, 1)', '0']

    >>> examples(add, text=True)
    '>>> add(2, 3)\\n5\\n>>> add(-1, 1)\\n0'

    >>> def undocumented(x):
    ...     return x * 2
    ...
    >>> examples(undocumented)
    ['undocumented(x=...)']

    >>> examples("not a function")
    ["'not a function'(...)"]
    """

    def clean(blocks: Iterable[str], text: bool = False) -> Union[List[str], str]:
        """
        Remove duplicate lines from example blocks while preserving order.

        This inner function processes raw example blocks, splits them into
        individual lines, and removes duplicates by tracking seen lines in
        a set. The original order of first appearance is preserved.

        Parameters
        ----------
        blocks : Iterable[str]
            An iterable of example block strings, potentially containing
            multiple lines each.
        text : bool
            If True, join the deduplicated lines with newlines into a
            single string. If False, return them as a list.

        Returns
        -------
        Union[List[str], str]
            Deduplicated example lines in the requested format.
        """
        seen: Set[str] = set()
        result: List[str] = []

        for block in blocks:
            for line in block.splitlines():
                stripped_line = line.strip()
                if stripped_line and stripped_line not in seen:
                    seen.add(stripped_line)
                    result.append(stripped_line)

        if text:
            return "\n".join(result)
        return result

    # Safely retrieve docstring; default to empty string
    doc = getattr(obj, "__doc__", "") or ""
    all_examples: List[str] = []

    # Stage 1: Extract from docstring sections (Example/Examples/Usage)
    all_examples.extend(_extract_examples_from_docstring(doc))

    # Stage 2: Extract doctest-style examples (>>>)
    all_examples.extend(_extract_doctest_examples(doc))

    # Stage 3: Extract ``` code blocks
    all_examples.extend(_extract_codeblock_examples(doc))

    # Stage 4: If no examples found, generate fallback from signature
    if not all_examples:
        all_examples = _generate_fallback_examples(obj)

    return clean(all_examples, text)


# ============================================================================
# 2. Universal Callable Wrapper
# ============================================================================


def to_callable(obj: Any) -> Callable[..., Any]:
    """
    Convert any Python object into a unified callable wrapper.

    This function provides a consistent, polymorphic interface for
    interacting with objects of any type. The returned callable adapts
    its behavior based on the original object's type, enabling:

    - **Dict access**: Retrieve values by key or apply transformations.
    - **Iterable access**: Retrieve elements by index or apply transformations.
    - **Callable execution**: Invoke functions with arguments.
    - **Static values**: Return cached values for non-callable, non-iterable objects.

    The wrapper supports a powerful processing pipeline with:

    - ``map_func``: Transform each element.
    - ``filter_func``: Select elements matching a predicate.
    - ``reduce_func``: Aggregate elements into a single value.
    - ``flatten``: Recursively flatten nested structures into a flat list.

    Parameters
    ----------
    obj : Any
        The Python object to wrap. Can be any type:
        - ``dict``: Returns a dict-like callable with key access.
        - Iterable (excluding ``str``/``bytes``): Returns an indexable callable.
        - Callable: Returns a call executor.
        - Other: Returns a fallback that caches and returns the value.

    Returns
    -------
    Callable[..., Any]
        A callable wrapper that provides a unified interface for the
        given object. The exact signature of the returned callable
        depends on the type of ``obj``:

        - **For dicts**::
            callable(key=None, map_func=None, filter_func=None,
                     reduce_func=None, initial=None, flatten=False)

        - **For iterables**::
            callable(index=None, map_func=None, filter_func=None,
                     reduce_func=None, initial=None, flatten=False)

        - **For callables**::
            callable(*args, **kwargs)

        - **For other**::
            callable(*args, **kwargs)

    Notes
    -----
    **Processing Pipeline Details**:

    The ``_process`` helper implements the core transformation logic:

    1. **For dictionaries**: Processes each key-value pair recursively.
       Keys are preserved; only values may be transformed.
    2. **For iterables**: Processes each element individually.
       The structure (list, tuple, etc.) is preserved.
    3. **For scalar values**: Returns them unchanged.

    **Pipeline Application Order**:

    1. ``filter_func`` is applied first (removes unwanted elements).
    2. ``map_func`` is applied second (transforms remaining elements).
    3. ``reduce_func`` is applied last (aggregates all elements).

    This order ensures that filtering happens before mapping (avoiding
    wasted transformations) and reduction happens after both.

    **Flattening**: The ``_flatten`` helper recursively unpacks nested
    iterables and dictionaries into a single flat list. This is useful
    for normalizing deeply nested data structures.

    **Caching**: The fallback wrapper caches the original value to
    ensure consistent return values across multiple calls.

    **Thread Safety**: The wrapper functions are stateless with respect
    to shared mutable data. The cache in ``_fallback`` is local to
    each wrapper instance, making it thread-safe per wrapper.

    Warnings
    --------
    - The ``_is_iterable`` helper explicitly excludes ``str`` and
      ``bytes`` to prevent treating them as iterables (which would
      cause infinite recursion during flattening).
    - Deep recursion in ``_process`` and ``_flatten`` may hit Python's
      recursion limit for extremely deeply nested structures.

    See Also
    --------
    functools.partial : Partial function application.
    map : Built-in mapping function.
    filter : Built-in filtering function.
    functools.reduce : Built-in reduction function.

    Examples
    --------
    Dict wrapping:

    >>> d = {'a': 1, 'b': 2, 'c': 3}
    >>> wrapper = to_callable(d)
    >>> wrapper(key='b')
    2
    >>> wrapper(map_func=lambda kv: (kv[0], kv[1] * 10))
    {'a': 10, 'b': 20, 'c': 30}

    Iterable wrapping:

    >>> lst = [1, 2, 3, 4, 5]
    >>> wrapper = to_callable(lst)
    >>> wrapper(index=0)
    1
    >>> wrapper(filter_func=lambda x: x > 2)
    [3, 4, 5]
    >>> wrapper(map_func=lambda x: x ** 2, flatten=True)
    [1, 4, 9, 16, 25]

    Nested structure flattening:

    >>> nested = [[1, 2], [3, [4, 5]], 6]
    >>> wrapper = to_callable(nested)
    >>> wrapper(flatten=True)
    [1, 2, 3, 4, 5, 6]

    Function execution:

    >>> def greet(name, greeting="Hello"):
    ...     return f"{greeting}, {name}"
    ...
    >>> wrapper = to_callable(greet)
    >>> wrapper("World")
    'Hello, World'

    Fallback for non-callable values:

    >>> wrapper = to_callable(42)
    >>> wrapper()
    42
    """
    # Cache for storing the original value (used by _fallback)
    cache: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Helper: Check if object is iterable (excluding strings and bytes)
    # ------------------------------------------------------------------
    def _is_iterable(o: Any) -> bool:
        """
        Determine if an object is an iterable collection.

        This function excludes strings (``str``) and bytes (``bytes``)
        from being considered iterable to prevent them from being
        decomposed into individual characters during recursive processing.

        Parameters
        ----------
        o : Any
            The object to test for iterability.

        Returns
        -------
        bool
            ``True`` if the object is an instance of
            ``collections.abc.Iterable`` and is not ``str`` or ``bytes``.
            ``False`` otherwise.
        """
        return isinstance(o, IterableABC) and not isinstance(o, (str, bytes))

    # ------------------------------------------------------------------
    # Helper: Recursive map/filter/reduce processing
    # ------------------------------------------------------------------
    def _process(
        obj: Any,
        map_func: _MapFunc = None,
        filter_func: _FilterFunc = None,
        reduce_func: _ReduceFunc = None,
        initial: Any = None,
    ) -> Any:
        """
        Recursively apply map, filter, and reduce to nested structures.

        This function traverses dictionaries and iterables recursively,
        applying transformation functions at each level. The processing
        order is: filter → map → reduce.

        Parameters
        ----------
        obj : Any
            The object to process. Dictionaries and iterables are
            processed recursively; other types are returned as-is.
        map_func : Callable or None, optional
            Transformation function applied to each element (or key-value
            pair for dicts). If None, no mapping is performed.
        filter_func : Callable or None, optional
            Predicate function that determines which elements to keep.
            If None, all elements are kept.
        reduce_func : Callable or None, optional
            Aggregation function applied to reduce elements to a single
            value. If None, no reduction is performed.
        initial : Any, optional
            Initial value for reduction. Only used when ``reduce_func``
            is provided.

        Returns
        -------
        Any
            The processed object. The return type depends on the input
            type and which transformations are applied:
            - Dict → dict (or reduced value)
            - Iterable → list (or reduced value)
            - Scalar → unchanged value
        """
        # --- Dictionary processing ---
        if isinstance(obj, dict):
            result: Dict[Any, Any] = {}
            for key, value in obj.items():
                # Recursively process nested structures
                val = (
                    _process(value, map_func, filter_func, reduce_func, initial)
                    if (_is_iterable(value) or isinstance(value, dict))
                    else value
                )
                result[key] = val

            # Apply transformations in order: filter → map → reduce
            if filter_func:
                result = {
                    k: v for k, v in result.items()
                    if filter_func((k, v))
                }
            if map_func:
                result = {
                    k: map_func((k, v)) for k, v in result.items()
                }
            if reduce_func:
                items_iter = iter(result.items())
                if initial is not None:
                    result = reduce(
                        lambda acc, item: reduce_func(acc, item),
                        items_iter,
                        initial,
                    )
                else:
                    result = reduce(
                        lambda acc, item: reduce_func(acc, item),
                        items_iter,
                    )
            return result

        # --- Iterable processing ---
        elif _is_iterable(obj):
            result: List[Any] = []
            for item in obj:
                # Recursively process nested structures
                val = (
                    _process(item, map_func, filter_func, reduce_func, initial)
                    if (_is_iterable(item) or isinstance(item, dict))
                    else item
                )
                result.append(val)

            # Apply transformations in order: filter → map → reduce
            if filter_func:
                result = list(filter(filter_func, result))
            if map_func:
                result = list(map(map_func, result))
            if reduce_func:
                if initial is not None:
                    result = reduce(reduce_func, result, initial)
                else:
                    result = reduce(reduce_func, result)
            return result

        # --- Scalar: return unchanged ---
        else:
            return obj

    # ------------------------------------------------------------------
    # Helper: Flatten nested structures into a flat list
    # ------------------------------------------------------------------
    def _flatten(obj: Any) -> List[Any]:
        """
        Flatten arbitrarily nested iterables and dicts into a flat list.

        This function recursively unpacks nested structures, returning
        all leaf values in a single flat list. Dictionaries are processed
        via ``_process`` before inclusion. The original nesting order
        is preserved in a depth-first manner.

        Parameters
        ----------
        obj : Any
            The object to flatten. Nested iterables and dicts are
            recursively unpacked; scalar values are wrapped in a
            single-element list.

        Returns
        -------
        List[Any]
            A flat list containing all leaf elements from the nested
            structure. The order follows depth-first traversal.

        Notes
        -----
        - Dictionary keys are not preserved in the flattened output;
          only the processed dictionary value is included.
        - Infinite recursion is prevented by the ``_is_iterable`` guard
          which excludes strings and bytes.
        """
        if _is_iterable(obj):
            result: List[Any] = []
            for item in obj:
                if _is_iterable(item):
                    # Recursively flatten nested iterables
                    result.extend(_flatten(item))
                elif isinstance(item, dict):
                    # Process dict before appending
                    result.append(_process(item))
                else:
                    # Append scalar value
                    result.append(item)
            return result
        elif isinstance(obj, dict):
            # Wrap processed dictionary in a list
            return [_process(obj)]
        else:
            # Wrap scalar in a single-element list
            return [obj]

    # ------------------------------------------------------------------
    # Fallback wrapper for non-callable, non-iterable objects
    # ------------------------------------------------------------------
    def _fallback(*args: Any, **kwargs: Any) -> Any:
        """
        Handle objects that are not dictionaries, iterables, or callables.

        This wrapper caches the original object on first access and
        returns the cached value on subsequent calls. If the original
        object happens to be callable and arguments are provided, it
        is executed with those arguments.

        Parameters
        ----------
        *args : Any
            Positional arguments (passed to ``obj`` if it is callable).
        **kwargs : Any
            Keyword arguments (passed to ``obj`` if it is callable).

        Returns
        -------
        Any
            The cached object value, or the result of calling it if
            arguments are provided and the object is callable.
        """
        if "__value__" not in cache:
            cache["__value__"] = obj

        # If the object is callable and arguments are provided, execute it
        if callable(obj) and (args or kwargs):
            return obj(*args, **kwargs)

        # Otherwise, return the cached value
        return cache["__value__"]

    # ------------------------------------------------------------------
    # Dict callable: key access + transformation pipeline
    # ------------------------------------------------------------------
    if isinstance(obj, dict):
        def _dict_callable(
            key: Any = None,
            map_func: _MapFunc = None,
            filter_func: _FilterFunc = None,
            reduce_func: _ReduceFunc = None,
            initial: Any = None,
            flatten: bool = False,
        ) -> Any:
            """
            Access dictionary values by key or apply processing pipeline.

            Parameters
            ----------
            key : Any, optional
                If provided, return the value associated with this key
                in the (potentially processed) dictionary.
            map_func : Callable or None, optional
            filter_func : Callable or None, optional
            reduce_func : Callable or None, optional
            initial : Any, optional
            flatten : bool, optional
                If True, flatten the dictionary into a list.

            Returns
            -------
            Any
                The requested value, processed dictionary, or flattened list.
            """
            result = _process(
                obj, map_func, filter_func, reduce_func, initial
            )
            if flatten:
                result = _flatten(result)
            if key is not None:
                return result.get(key)
            return result

        return _dict_callable

    # ------------------------------------------------------------------
    # Iterable callable: index access + transformation pipeline
    # ------------------------------------------------------------------
    if _is_iterable(obj):
        iter_obj = list(obj)  # Materialize for indexed access

        def _iter_callable(
            index: int = None,
            map_func: _MapFunc = None,
            filter_func: _FilterFunc = None,
            reduce_func: _ReduceFunc = None,
            initial: Any = None,
            flatten: bool = False,
        ) -> Any:
            """
            Access iterable elements by index or apply processing pipeline.

            Parameters
            ----------
            index : int, optional
                If provided, return the element at this index in the
                (potentially processed) iterable.
            map_func : Callable or None, optional
            filter_func : Callable or None, optional
            reduce_func : Callable or None, optional
            initial : Any, optional
            flatten : bool, optional
                If True, flatten nested structures into a flat list.

            Returns
            -------
            Any
                The requested element, processed iterable, or flattened list.
            """
            result = _process(
                iter_obj, map_func, filter_func, reduce_func, initial
            )
            if flatten:
                result = _flatten(result)
            if index is not None:
                try:
                    result = result[index]
                except (IndexError, TypeError):
                    # Return None for out-of-bounds or type errors
                    result = None
            return result

        return _iter_callable

    # ------------------------------------------------------------------
    # Callable wrapper: execute with arguments
    # ------------------------------------------------------------------
    if callable(obj):
        def _callable(*args: Any, **kwargs: Any) -> Any:
            """
            Execute the wrapped callable with the given arguments.

            Uses :func:`functools.partial` to bind arguments and then
            immediately calls the resulting partial.

            Parameters
            ----------
            *args : Any
                Positional arguments for the callable.
            **kwargs : Any
                Keyword arguments for the callable.

            Returns
            -------
            Any
                The result of executing the callable with the bound
                arguments.
            """
            return partial(obj, *args, **kwargs)()

        return _callable

    # ------------------------------------------------------------------
    # Default: return fallback wrapper
    # ------------------------------------------------------------------
    return _fallback


# ============================================================================
# 3. Callable Unwrapping
# ============================================================================


def unwrap_callable(obj: Any, max_depth: int = 20) -> Any:
    """
    Recursively unwrap a callable through layers of decorators and wrappers.

    This function peels back multiple layers of wrapping to reveal the
    underlying raw function or callable, handling:

    - **Bound methods** (``types.MethodType``): Unwraps ``__func__``.
    - **Classmethods / staticmethods**: Unwraps ``__func__``.
    - **Functools partials**: Unwraps ``func`` attribute.
    - **Decorator chains**: Follows ``__wrapped__`` attribute.
    - **Callable objects**: If the object has ``__call__`` but no
      ``__code__``, attempts to unwrap ``__call__``.

    The unwrapping continues until no more wrappers are detected or
    the maximum recursion depth is reached.

    Parameters
    ----------
    obj : Any
        The callable to unwrap. Can be any Python object with callable
        characteristics (function, method, partial, decorated function,
        callable instance, etc.).

    max_depth : int, optional
        Maximum number of unwrapping iterations to prevent infinite
        loops in cases of circular wrapping or pathological decorator
        chains. Default is 20.

    Returns
    -------
    Any
        The fully unwrapped callable. If the maximum depth is exceeded
        or the object cannot be further unwrapped, the current object
        at that depth is returned. If unwrapping fails entirely, the
        original object is returned.

    Notes
    -----
    **Cycle Detection**: A ``seen`` set tracks previously encountered
    objects to prevent infinite loops in case of circular references
    (e.g., a decorator that wraps an object in itself).

    **Unwrapping Order**:

    1. Bound method → underlying function
    2. Classmethod/staticmethod → underlying function
    3. Partial → underlying function
    4. Decorated (``__wrapped__``) → next layer
    5. Callable instance (``__call__``) → underlying callable

    **Limitations**:

    - Built-in functions (C extensions) typically have no ``__code__``
      and cannot be further unwrapped.
    - Some decorators may not set ``__wrapped__`` correctly; these
      will stop the unwrapping process.

    See Also
    --------
    inspect.unwrap : Standard library alternative (less aggressive).
    functools.wraps : Decorator for preserving metadata.

    Examples
    --------
    >>> from functools import partial
    >>> def original(x): return x * 2
    >>> wrapped = partial(original, 10)
    >>> unwrap_callable(wrapped) is original
    True

    >>> class MyClass:
    ...     def method(self, x): return x
    ...
    >>> obj = MyClass()
    >>> m = obj.method
    >>> unwrap_callable(m) is MyClass.method
    True
    """
    seen: Set[int] = set()  # Track object identities to prevent cycles
    depth = 0

    while True:
        # Cycle detection: stop if we've seen this object before
        obj_id = id(obj)
        if obj_id in seen:
            return obj
        seen.add(obj_id)

        # Depth limit: prevent infinite loops
        if depth >= max_depth:
            warnings.warn(
                f"Maximum unwrap depth ({max_depth}) reached. "
                f"The callable may be too deeply wrapped or circular.",
                RuntimeWarning,
                stacklevel=2,
            )
            return obj

        depth += 1

        # 1) Unwrap bound method → underlying function
        if isinstance(obj, types.MethodType):
            obj = obj.__func__
            continue

        # 2) Unwrap classmethod / staticmethod
        if isinstance(obj, (classmethod, staticmethod)):
            obj = obj.__func__
            continue

        # 3) Unwrap functools.partial
        if isinstance(obj, functools.partial):
            obj = obj.func
            continue

        # 4) Unwrap decorator chain via __wrapped__
        if hasattr(obj, "__wrapped__"):
            obj = obj.__wrapped__
            continue

        # 5) Unwrap callable objects (no __code__ but have __call__)
        if not hasattr(obj, "__code__") and hasattr(obj, "__call__"):
            call = obj.__call__
            # Only unwrap if __call__ is different from the object itself
            if obj is not call:
                obj = call
                continue

        # Cannot unwrap further
        return obj


# ============================================================================
# 4. Code Object Extraction
# ============================================================================


def get_code(obj: Any) -> Optional[types.CodeType]:
    """
    Extract the underlying code object from any callable.

    This function performs full unwrapping of decorators, wrappers,
    methods, and other callable transformations before attempting to
    retrieve the code object. It is designed to handle any Python
    callable, including:

    - Plain functions (``def``).
    - Lambda functions (``lambda``).
    - Methods (bound and unbound).
    - Static methods and class methods.
    - Partially applied functions (``functools.partial``).
    - Decorated functions (via ``@decorator``).
    - Callable class instances (implementing ``__call__``).
    - Generators, coroutines, and async functions.

    Parameters
    ----------
    obj : Any
        Any Python object that might be callable or wrappable into
        a callable. Non-callable objects are first unwrapped using
        :func:`unwrap_callable`; if the result has a ``__code__``
        attribute, it is returned.

    Returns
    -------
    types.CodeType or None
        The underlying code object (``types.CodeType``) if one exists.
        Returns ``None`` in the following cases:

        - The object is a built-in function implemented in C (e.g.,
          ``len``, ``print``).
        - The unwrapped object does not have a ``__code__`` attribute.
        - An exception occurs during unwrapping (in which case the
          exception is caught, and ``None`` is returned).

    Notes
    -----
    **Built-in Functions**: Functions implemented in C (like
    ``builtins.len``) have no Python code object. These will always
    return ``None``.

    **Lambda Functions**: Lambda functions do have code objects and
    will be handled correctly after unwrapping.

    **Generators and Coroutines**: Generator functions (``def gen(): yield``)
    and coroutine functions (``async def coro():``) return code objects
    with the appropriate flags set (``CO_GENERATOR``, ``CO_COROUTINE``).

    **Silent Failure**: This function never raises exceptions. All
    errors are caught and result in ``None`` being returned, making it
    safe to use on any object.

    See Also
    --------
    unwrap_callable : The unwrapping function used as preprocessing.
    types.CodeType : The type of code objects returned.
    inspect.getsource : Retrieves source code for code objects.

    Examples
    --------
    >>> def func(x): return x + 1
    >>> code = get_code(func)
    >>> code.co_name
    'func'
    >>> code.co_argcount
    1

    >>> get_code(len) is None
    True

    >>> from functools import partial
    >>> p = partial(func, 42)
    >>> code = get_code(p)
    >>> code.co_name
    'func'

    >>> class Callable:
    ...     def __call__(self, x): return x
    ...
    >>> get_code(Callable()) is not None
    True
    """
    try:
        # Unwrap all layers of decoration/wrapping
        target = unwrap_callable(obj)
    except (TypeError, ValueError, AttributeError):
        # If unwrapping fails, use the original object
        target = obj

    # Retrieve the code object if available
    return getattr(target, "__code__", None)


# ============================================================================
# 5. Frame Tracking
# ============================================================================


@dataclass
class FrameRecord:
    """
    Record representing a single frame event for a tracked object.

    This dataclass captures the complete execution context at a specific
    tracing event, including the object identity, event type, code location,
    and local/global variable state. It is designed to be serializable and
    provides a snapshot of execution for debugging, profiling, and analysis.

    Parameters
    ----------
    name : str
        The ``__name__`` of the tracked object, or its ``repr()`` if
        ``__name__`` is unavailable.
    type : str
        The type name of the tracked object (e.g., ``'function'``,
        ``'module'``, ``'MyClass'``).
    event : str
        The trace event type: ``'call'`` (function called), ``'return'``
        (function returned), ``'line'`` (line executed), or ``'exception'``
        (exception raised).
    function : str
        The name of the function or method where the event occurred
        (i.e., ``frame.f_code.co_name``).
    line : int
        The line number where the event occurred (1-indexed).
    file : str
        The absolute or relative file path of the executed frame
        (i.e., ``frame.f_code.co_filename``).
    locals : Dict[str, Any]
        A shallow copy of the local variables in the frame at the time
        of the event. Values are raw Python objects; callers should be
        aware that mutable objects may change after capture.
    globals : Dict[str, str]
        A mapping of global variable names to their type names (e.g.,
        ``{'x': 'int', 'y': 'str'}``). This provides type information
        without capturing potentially large global values.
    stack : List[str]
        A human-readable representation of the call stack at the time
        of the event, formatted as ``"function_name:line_number"``
        strings, ordered from outermost to innermost (reversed from
        ``inspect.stack()``).

    See Also
    --------
    track_objects : The function that generates these records.
    sys.settrace : The underlying tracing mechanism.

    Examples
    --------
    >>> rec = FrameRecord(
    ...     name="my_func",
    ...     type="function",
    ...     event="call",
    ...     function="my_func",
    ...     line=10,
    ...     file="/path/to/file.py",
    ...     locals={"x": 1},
    ...     globals={"x": "int"},
    ...     stack=["module:1", "my_func:10"],
    ... )
    >>> rec.name
    'my_func'
    >>> rec.event
    'call'
    """

    name: str
    type: str
    event: str
    function: str
    line: int
    file: str
    locals: Dict[str, Any]
    globals: Dict[str, str]
    stack: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the FrameRecord to a JSON-serializable dictionary.

        Returns
        -------
        Dict[str, Any]
            A dictionary representation of all fields. The ``locals``
            and ``globals`` fields are included as-is; note that
            ``locals`` values may not be JSON-serializable if they
            contain complex objects.
        """
        return asdict(self)


def _collect_single_module(pkg_name: str) -> Optional[Path]:
    """
    Load a single module and resolve its file path.

    This is a helper function designed for use with
    :class:`concurrent.futures.ThreadPoolExecutor` to enable
    parallel module loading during path collection.

    Parameters
    ----------
    pkg_name : str
        Fully qualified package or module name to import
        (e.g., ``'os.path'``, ``'mypackage.submodule'``).

    Returns
    -------
    Path or None
        The resolved absolute ``Path`` to the module's ``__file__``
        if the module can be imported and has a file location.
        Returns ``None`` if:

        - The module cannot be imported (any exception).
        - The imported module has no ``__file__`` attribute (e.g.,
          built-in modules, namespace packages).

    Notes
    -----
    This function is not intended for direct use; it is designed as
    a target for :meth:`ThreadPoolExecutor.submit`. All exceptions
    are caught to prevent thread crashes from propagating.

    Examples
    --------
    >>> path = _collect_single_module("os")
    >>> path is not None
    True
    >>> path.suffix
    '.py'

    >>> _collect_single_module("nonexistent_module") is None
    True
    """
    try:
        module = importlib.import_module(pkg_name)
        if hasattr(module, "__file__") and module.__file__:
            return Path(module.__file__).resolve()
    except (ImportError, AttributeError, TypeError):
        # Module not found or has no file path
        pass
    return None


def _collect_module_files(module: types.ModuleType) -> Set[Path]:
    """
    Collect all file paths belonging to a module and its submodules.

    This function recursively discovers all submodules of the given
    module and collects their ``__file__`` paths. Discovery uses
    :func:`pkgutil.walk_packages` for the module tree traversal and
    :class:`ThreadPoolExecutor` for parallel submodule loading.

    Parameters
    ----------
    module : ModuleType
        The root module to collect files from. Must be an imported
        Python module instance with either a ``__file__`` attribute
        (single-file module) or a ``__path__`` attribute (package).

    Returns
    -------
    Set[Path]
        A set of resolved absolute ``Path`` objects representing all
        files belonging to the module and all discoverable submodules.
        Each path is unique (set semantics). If the module has no file
        path and no submodule path, the set may be empty.

    Notes
    -----
    **Threading**: Submodule imports are performed in parallel using
    up to 8 worker threads to accelerate path collection for large
    packages with many submodules.

    **Path Resolution**: All paths are resolved to absolute paths
    using ``Path.resolve()`` to ensure canonical comparison and
    file existence checks.

    **Error Handling**: Submodules that fail to import (e.g., due to
    missing dependencies or syntax errors) are silently skipped;
    only successfully imported modules are included.

    Examples
    --------
    >>> import os
    >>> files = _collect_module_files(os.path)
    >>> len(files) > 0
    True
    >>> all(isinstance(f, Path) for f in files)
    True
    """
    files: Set[Path] = set()

    # Collect the module's main file
    if hasattr(module, "__file__") and module.__file__:
        files.add(Path(module.__file__).resolve())

    # Walk through submodules if the module is a package
    if hasattr(module, "__path__"):
        # Build list of submodule names
        package_prefix = f"{module.__name__}."
        submodule_names = [
            pkg.name
            for pkg in pkgutil.walk_packages(
                module.__path__,
                prefix=package_prefix,
            )
        ]

        # Parallel loading of submodules using thread pool
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_name: Dict[Future, str] = {
                executor.submit(_collect_single_module, name): name
                for name in submodule_names
            }

            for future in as_completed(future_to_name):
                result = future.result()
                if result is not None:
                    files.add(result)

    return files


def track_objects(
    targets: List[Any],
    calls: int = 50,
    live: bool = False,
) -> List[FrameRecord]:
    """
    Track execution of given objects and collect frame-level information.

    This function sets up a global tracing hook using :func:`sys.settrace`
    and :func:`threading.settrace` to monitor the execution of specified
    Python objects. When any of the target objects are encountered in
    an executing frame, a :class:`FrameRecord` is created capturing the
    execution context.

    The function supports tracking:

    - **Modules**: Monitors frames executing in any file belonging to
      the module or its submodules.
    - **Functions and methods**: Monitors frames where ``frame.f_code``
      matches the function's ``__code__``.
    - **Class instances**: Monitors frames where ``self`` references
      the target instance.
    - **Classes**: Monitors frames where ``self`` is an instance of the
      target class.

    Parameters
    ----------
    targets : List[Any]
        List of Python objects to track. Each object can be a module,
        class, class instance, function, or method. Objects are stored
        as weak references internally; if all strong references to an
        object are lost during tracing, that object is silently dropped
        from tracking.

    calls : int, optional
        Maximum number of trace events (frames) to record before
        automatically stopping tracing. This prevents unbounded memory
        growth. Default is 50.

    live : bool, optional
        If ``True``, each trace event is printed to stdout in real-time
        using the format ``"[event] name.function:line"``. Tracing
        continues until manually stopped or until ``calls`` events
        are recorded (the live flag overrides the auto-stop; see Notes).
        If ``False`` (default), tracing stops automatically after
        ``calls`` events are collected.

    Returns
    -------
    List[FrameRecord]
        A list of captured :class:`FrameRecord` instances in the order
        they were encountered. The list length will be at most ``calls``
        (but may be shorter if tracing stopped early or no matching
        frames were encountered).

    Notes
    -----
    **Implementation Details**:

    - **Weak References**: Target objects are stored as ``weakref.ref``
      to prevent the tracing mechanism from keeping objects alive
      artificially. If an object is garbage collected during tracing,
      it is silently removed from tracking.
    - **Module File Scanning**: For module targets, all submodule file
      paths are pre-collected using :func:`_collect_module_files` for
      efficient matching during tracing.
    - **Global Tracing**: The tracer is installed via both
      ``sys.settrace`` and ``threading.settrace`` to support
      multi-threaded applications.

    **Live Mode Behavior**:

    - In live mode, the auto-stop after ``calls`` events is **not**
      applied; tracing continues until the program exits or the
      tracer is manually removed.
    - Live mode is useful for debugging and interactive exploration.

    **Performance Considerations**:

    - Tracing imposes significant performance overhead on all Python
      code execution. Use with ``calls`` limits and targeted objects
      in production environments.
    - The tracer function is called for every frame execution event
      (``call``, ``return``, ``line``, ``exception``), which can
      greatly slow down the program.

    Warnings
    --------
    - This function modifies global state via ``sys.settrace`` and
      ``threading.settrace``. Only one tracer can be active at a time;
      calling this function again will override any previous tracer.
    - Tracing all frames may expose sensitive data in ``frame.f_locals``
      and ``frame.f_globals``, which are captured in :class:`FrameRecord`.

    See Also
    --------
    sys.settrace : Set the global trace function.
    FrameRecord : Dataclass for captured frame events.
    weakref.ref : Weak reference mechanism.

    Examples
    --------
    >>> def test_func(x):
    ...     return x * 2
    ...
    >>> records = track_objects([test_func], calls=10)
    >>> # Execute the function to trigger tracing
    >>> result = test_func(42)
    >>> # Tracing stopped after recording
    >>> len(records) >= 1  # May have captured events
    True
    >>> any(r.function == 'test_func' for r in records)
    True
    """
    history: List[FrameRecord] = []

    # Store weak references to target objects to avoid keeping them alive
    refs: List[weakref.ref] = [weakref.ref(obj) for obj in targets]

    # Pre-scan module file paths for efficient matching
    module_files: Dict[Any, Set[Path]] = {}
    for obj in targets:
        if isinstance(obj, types.ModuleType):
            module_files[obj] = _collect_module_files(obj)

    def tracer(frame: types.FrameType, event: str, arg: Any) -> Any:
        """
        Global trace function called for each frame execution event.

        Parameters
        ----------
        frame : FrameType
            The current execution frame.
        event : str
            The trace event type ('call', 'return', 'line', 'exception').
        arg : Any
            Event-specific argument (e.g., return value for 'return',
            exception for 'exception').

        Returns
        -------
        Callable or None
            Returns itself to continue tracing, or None to stop.
        """
        file_path = Path(frame.f_code.co_filename).resolve()

        # Check each target for match against the current frame
        for ref, target in zip(refs, targets):
            current = ref()
            if current is None:
                # Target has been garbage collected; skip
                continue

            matched = False
            ttype = type(current).__name__

            # --- Match module target ---
            if isinstance(current, types.ModuleType):
                if file_path in module_files.get(current, set()):
                    matched = True

            # --- Match function or method target ---
            elif hasattr(current, "__code__"):
                if frame.f_code is current.__code__:
                    matched = True

            # --- Match class instance target ---
            elif "self" in frame.f_locals and frame.f_locals["self"] is current:
                matched = True

            # --- Match class target (instance of the class) ---
            elif isinstance(current, type) and "self" in frame.f_locals:
                if isinstance(frame.f_locals["self"], current):
                    matched = True

            if matched:
                # Build the call stack representation
                stack_repr = [
                    f"{fi.function}:{fi.lineno}"
                    for fi in inspect.stack()[::-1]
                ]

                # Create the frame record
                rec = FrameRecord(
                    name=getattr(current, "__name__", repr(current)),
                    type=ttype,
                    event=event,
                    function=frame.f_code.co_name,
                    line=frame.f_lineno,
                    file=str(file_path),
                    locals=dict(frame.f_locals),
                    globals={
                        k: type(v).__name__
                        for k, v in frame.f_globals.items()
                    },
                    stack=stack_repr,
                )

                history.append(rec)

                # Live mode: print event to stdout
                if live:
                    print(
                        f"[{event}] {rec.name}.{rec.function}:{rec.line}"
                    )

                # Auto-stop in non-live mode after reaching call limit
                if len(history) >= calls and not live:
                    sys.settrace(None)
                    threading.settrace(None)
                    return None

                return tracer

        return tracer

    # Install tracer globally (main thread + spawned threads)
    sys.settrace(tracer)
    threading.settrace(tracer)

    return history


# ============================================================================
# 6. Dynamic Dictionary Creation
# ============================================================================


def create_dict(obj: Any) -> Dict[str, Any]:
    """
    Create a dictionary-like attribute mapping for any Python object.

    This function provides a unified way to access an object's readable
    attributes as a dictionary, even for objects that do not natively
    support ``__dict__`` (e.g., built-in types, C extensions, classes
    using ``__slots__``). It employs a multi-strategy approach:

    1. **Native ``__dict__``**: If the object already has a ``__dict__``
       mapping, it is returned directly.
    2. **Attribute injection**: If the object supports dynamic attribute
       assignment, a new ``__dict__`` is created and populated with all
       readable attributes from ``dir(obj)``.
    3. **Wrapper fallback**: If neither approach works (e.g., for integers,
       strings, or other immutable built-in types), a ``DictWrapper``
       proxy is created that provides dictionary-like access while
       preserving access to the original object's attributes.

    Parameters
    ----------
    obj : Any
        The object for which to create an attribute dictionary. Can be
        any Python object, including:

        - User-defined class instances.
        - Built-in types (``int``, ``str``, ``list``, etc.).
        - Modules.
        - Classes themselves.
        - C extension objects.

    Returns
    -------
    Dict[str, Any]
        A dictionary containing the object's readable attributes,
        where keys are attribute names (as returned by ``dir(obj)``)
        and values are the corresponding attribute values obtained
        via ``getattr``.

        - If the object has a native ``__dict__``, returns it directly.
        - If injection succeeds, returns the newly created ``__dict__``.
        - If a wrapper is needed, returns the wrapper's ``__dict__``,
          which proxies attribute access to the original object.

    Notes
    -----
    **Attribute Extraction**: The internal ``extract_attributes()``
    function iterates over all names returned by ``dir(obj)`` and
    attempts to retrieve each attribute via ``getattr``. Attributes
    that raise exceptions during access are silently skipped. This
    provides a best-effort snapshot of readable attributes.

    **DictWrapper**: When the original object does not support
    ``__dict__`` assignment, a ``DictWrapper`` instance is created.
    The wrapper:

    - Stores extracted attributes in its own ``__dict__``.
    - Proxies attribute access to the original object via
      ``__getattr__`` for any attributes not in ``__dict__``.
    - Provides a useful ``__repr__`` for debugging.

    **Limitations**:

    - The snapshot represents attribute values at the moment of
      extraction; subsequent changes to the original object are
      not reflected in the dictionary (except for native
      ``__dict__`` returns, which remain live).
    - Some objects may have a ``__dict__`` that is not a proper
      dictionary (e.g., ``mappingproxy``); the function returns
      what is available without conversion.

    **Thread Safety**: This function reads object attributes without
    modification (except for the optional ``__dict__`` injection).
    It is safe for concurrent calls on different objects.

    See Also
    --------
    dir : Built-in function listing attribute names.
    getattr : Built-in function retrieving attribute values.
    vars : Built-in function returning ``__dict__``.

    Examples
    --------
    >>> class Example:
    ...     def __init__(self):
    ...         self.name = "Alice"
    ...         self.age = 30
    ...
    >>> obj = Example()
    >>> d = create_dict(obj)
    >>> d['name']
    'Alice'
    >>> d['age']
    30

    >>> create_dict(42)  # Built-in int has no __dict__
    {'__class__': <class 'int'>, ...}

    >>> import math
    >>> d = create_dict(math)
    >>> 'pi' in d
    True
    >>> d['pi']
    3.141592653589793
    """

    def extract_attributes(o: Any) -> Dict[str, Any]:
        """
        Extract all readable attributes from an object.

        Iterates through ``dir(o)`` and safely retrieves each
        attribute via ``getattr``. Attributes that raise exceptions
        (e.g., descriptors requiring specific contexts) are silently
        excluded from the result.

        Parameters
        ----------
        o : Any
            The object to extract attributes from.

        Returns
        -------
        Dict[str, Any]
            Mapping of attribute names to their values.
        """
        attrs: Dict[str, Any] = {}
        for name in dir(o):
            # Skip Python's internal slot wrappers and unreadable attrs
            try:
                attrs[name] = getattr(o, name)
            except (AttributeError, TypeError, RuntimeError):
                # Silently skip attributes that cannot be read
                pass
        return attrs

    # Strategy 1: Return native __dict__ if it exists
    if hasattr(obj, "__dict__"):
        return obj.__dict__

    # Strategy 2: Try to inject __dict__ for objects that support it
    try:
        attrs = extract_attributes(obj)
        setattr(obj, "__dict__", attrs)
        return obj.__dict__
    except (AttributeError, TypeError, ValueError):
        # Object does not support attribute assignment
        pass

    # Strategy 3: Create a DictWrapper proxy
    class DictWrapper:
        """
        Proxy object providing dictionary-like access to an object's attributes.

        This wrapper stores extracted attributes in its own ``__dict__``
        and falls back to the original object for attribute access when
        the attribute is not found in ``__dict__``.

        Parameters
        ----------
        original : Any
            The original object being wrapped.

        Attributes
        ----------
        original : Any
            Reference to the original object.
        __dict__ : dict
            Dictionary of extracted attributes.

        Notes
        -----
        The wrapper is designed to be transparent: accessing an attribute
        that exists in ``__dict__`` returns the stored value; accessing
        any other attribute falls back to the original object.
        """

        __slots__ = ('original', '__dict__')

        def __init__(self, original: Any) -> None:
            self.original = original
            self.__dict__ = extract_attributes(original)

        def __getattr__(self, item: str) -> Any:
            """
            Fall back to the original object for missing attributes.

            Parameters
            ----------
            item : str
                The attribute name to retrieve.

            Returns
            -------
            Any
                The attribute value from the original object.

            Raises
            ------
            AttributeError
                Propagated from the original object if the attribute
                does not exist.
            """
            return getattr(self.original, item)

        def __repr__(self) -> str:
            """
            Return a string representation showing the wrapped object.

            Returns
            -------
            str
                String in the format ``<DictWrapper for original_repr>``.
            """
            return f"<DictWrapper for {self.original!r}>"

    # Create wrapper and return its __dict__
    wrapper = DictWrapper(obj)
    return getattr(wrapper, "__dict__", {})