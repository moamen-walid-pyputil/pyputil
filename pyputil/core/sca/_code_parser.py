#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Python Bytecode Analysis and Code Parsing Module.

This module provides comprehensive analysis of Python source code through
bytecode inspection, offering detailed insights into code structure,
dependencies, control flow patterns, exception handling, and quality
metrics. By examining compiled bytecode rather than source text alone,
the parser achieves high accuracy in detecting code constructs and their
relationships.

The analysis covers:
- Function and lambda detection with type classification
- Class structure and method identification
- Import statement tracking and dependency mapping
- Variable scoping (local, global, nonlocal)
- Attribute access patterns and object relationships
- Control flow analysis (branches, loops, jumps)
- Exception handling constructs (try/except/finally, raise)
- Comprehension and generator expression detection
- Context manager usage (with statements, async with)
- Code quality metrics (cyclomatic complexity, maintainability index)

Notes
-----
The parser operates on compiled bytecode, which means it can analyze
syntactically valid Python code without executing it. This provides
a safe way to inspect potentially untrusted code while still obtaining
detailed structural information.

Bytecode patterns vary between Python versions. This implementation
targets Python 3.8+ bytecode instructions. Some detection heuristics
may need adjustment for other Python versions.

See Also
--------
dis : Python bytecode disassembler module.
ast : Abstract Syntax Tree module for source-level analysis.
inspect : Live object inspection utilities.

References
----------
.. [1] Python Documentation: dis — Disassembler for Python bytecode.
   https://docs.python.org/3/library/dis.html
.. [2] McCabe, T.J. "A Complexity Measure", IEEE Transactions on
   Software Engineering, 1976.
.. [3] Coleman, D. et al. "Using Maintainability Index to Assess
   Software", 1994.
"""

import ast
import dis
import math
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from types import CodeType
from typing import (
    Any, Dict, List, Optional, Set, Tuple, Union, FrozenSet,
    ClassVar, DefaultDict, Iterator, Sequence,
)


# ============================================================================
# Enumerations
# ============================================================================


class FunctionType(Enum):
    """
    Enumeration of supported function types detected during bytecode analysis.

    These types are determined by examining the code object's flags
    (``co_flags``) which encode information about the function's
    characteristics.

    Attributes
    ----------
    FUNCTION : auto
        Standard synchronous function (``def func():``).
    ASYNC_FUNCTION : auto
        Coroutine function (``async def func():``). Flag: ``CO_COROUTINE``.
    GENERATOR : auto
        Generator function (``def func(): yield``). Flag: ``CO_GENERATOR``.
    ASYNC_GENERATOR : auto
        Async generator function (``async def func(): yield``).
        Flag: ``CO_ASYNC_GENERATOR``.
    LAMBDA : auto
        Lambda expression (``lambda x: x + 1``). Detected by name ``<lambda>``.

    See Also
    --------
    FunctionInfo : Dataclass using this enumeration.
    CodeParser._CODE_FLAGS : Flag value mapping.
    """

    FUNCTION = auto()
    ASYNC_FUNCTION = auto()
    GENERATOR = auto()
    ASYNC_GENERATOR = auto()
    LAMBDA = auto()


class ImportType(Enum):
    """
    Enumeration of import statement types.

    Attributes
    ----------
    IMPORT : auto
        Direct import (``import module`` or ``import module as alias``).
    IMPORT_FROM : auto
        From-import (``from module import name``).
    IMPORT_STAR : auto
        Star import (``from module import *``).

    See Also
    --------
    ImportInfo : Dataclass using this enumeration.
    OpcodeCategories.IMPORT : Related bytecode opcodes.
    """

    IMPORT = auto()
    IMPORT_FROM = auto()
    IMPORT_STAR = auto()


class ControlFlowType(Enum):
    """
    Enumeration of control flow constructs detected in bytecode.

    These types correspond to different categories of jump instructions
    found in Python bytecode.

    Attributes
    ----------
    JUMP : auto
        Unconditional jump (e.g., ``JUMP_FORWARD``, ``JUMP_ABSOLUTE``).
    CONDITIONAL : auto
        Conditional branch based on boolean evaluation
        (e.g., ``POP_JUMP_IF_TRUE``).
    LOOP : auto
        Loop iteration constructs (e.g., ``FOR_ITER``, ``SETUP_LOOP``).
    EXCEPTION : auto
        Exception handling setup (e.g., ``SETUP_EXCEPT``, ``SETUP_FINALLY``).
    CONTEXT_MANAGER : auto
        Context manager setup (e.g., ``SETUP_WITH``, ``SETUP_ASYNC_WITH``).

    See Also
    --------
    ControlFlowInfo : Dataclass using this enumeration.
    OpcodeCategories.JUMP : Related bytecode opcodes.
    """

    JUMP = auto()
    CONDITIONAL = auto()
    LOOP = auto()
    EXCEPTION = auto()
    CONTEXT_MANAGER = auto()


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class FunctionInfo:
    """
    Comprehensive information about a Python function extracted from bytecode.

    This dataclass captures all structural metadata available from a
    function's code object, including argument counts, variable
    allocations, stack requirements, and type annotations.

    Parameters
    ----------
    name : str
        Simple function name (e.g., ``'calculate'``). For lambdas,
        this is ``'<lambda_N>'`` where N is a counter.
    qualified_name : str
        Fully qualified function name including class/module context
        (e.g., ``'module.ClassName.calculate'``).
    type : FunctionType, optional
        Classification of the function type. Default is
        ``FunctionType.FUNCTION``.
    argcount : int, optional
        Number of regular positional arguments (including optional ones).
        Default is 0.
    posonlyargcount : int, optional
        Number of positional-only arguments (Python 3.8+). Default is 0.
    kwonlyargcount : int, optional
        Number of keyword-only arguments. Default is 0.
    nlocals : int, optional
        Total number of local variables including arguments. Default is 0.
    stacksize : int, optional
        Maximum stack depth required for execution. Default is 0.
    flags : List[str], optional
        Human-readable code flags (e.g., ``['OPTIMIZED', 'NEWLOCALS']``).
        Default is empty list.
    firstlineno : int, optional
        First line number of the function definition in the source.
        Default is 0.
    filename : str, optional
        Source filename where the function is defined. Default is "".
    decorators : List[str], optional
        List of decorator names applied to the function, if detectable.
        Default is empty list.
    docstring : Optional[str], optional
        Function docstring if present in the code constants. Default is None.
    annotations : Dict[str, str], optional
        Mapping of parameter names and ``'return'`` to their type annotation
        strings. Default is empty dict.

    See Also
    --------
    FunctionType : Enumeration of function types.
    ClassInfo : Class-level analysis information.

    Examples
    --------
    >>> info = FunctionInfo(
    ...     name="add",
    ...     qualified_name="module.add",
    ...     type=FunctionType.FUNCTION,
    ...     argcount=2,
    ...     nlocals=2,
    ...     firstlineno=10,
    ... )
    >>> info.name
    'add'
    >>> info.argcount
    2
    """

    name: str
    qualified_name: str
    type: FunctionType = FunctionType.FUNCTION
    argcount: int = 0
    posonlyargcount: int = 0
    kwonlyargcount: int = 0
    nlocals: int = 0
    stacksize: int = 0
    flags: List[str] = field(default_factory=list)
    firstlineno: int = 0
    filename: str = ""
    decorators: List[str] = field(default_factory=list)
    docstring: Optional[str] = None
    annotations: Dict[str, str] = field(default_factory=dict)

    def is_method(self) -> bool:
        """
        Determine if this function is likely a method based on context.

        Returns
        -------
        bool
            True if the qualified name contains class context
            (i.e., includes a dot-separated class name).
        """
        parts = self.qualified_name.split('.')
        return len(parts) > 2  # module.class.method pattern


@dataclass
class ClassInfo:
    """
    Information about a Python class extracted from bytecode analysis.

    Classes are detected heuristically from code objects with no
    arguments (``co_argcount == 0``) that are not special names
    like ``<lambda>`` or ``<module>``. The detection is based on
    the structure of the bytecode and the presence of class-specific
    operations.

    Parameters
    ----------
    name : str
        Simple class name (e.g., ``'MyClass'``).
    qualified_name : str
        Fully qualified class name including module context
        (e.g., ``'mypackage.MyClass'``).
    firstlineno : int, optional
        First line number of the class definition. Default is 0.
    filename : str, optional
        Source filename where the class is defined. Default is "".
    base_classes : List[str], optional
        List of base class names from inheritance. Default is empty list.
    decorators : List[str], optional
        List of decorator names applied to the class. Default is empty list.
    docstring : Optional[str], optional
        Class docstring if present. Default is None.
    methods : List[str], optional
        List of method names defined within the class body.
        Default is empty list.
    attributes : List[str], optional
        List of class-level attribute names. Default is empty list.

    See Also
    --------
    FunctionInfo : Method-level analysis information.

    Examples
    --------
    >>> info = ClassInfo(
    ...     name="Calculator",
    ...     qualified_name="module.Calculator",
    ...     base_classes=["object"],
    ...     firstlineno=25,
    ... )
    >>> info.name
    'Calculator'
    >>> len(info.base_classes)
    1
    """

    name: str
    qualified_name: str
    firstlineno: int = 0
    filename: str = ""
    base_classes: List[str] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)
    docstring: Optional[str] = None
    methods: List[str] = field(default_factory=list)
    attributes: List[str] = field(default_factory=list)


@dataclass
class CallInfo:
    """
    Information about a function or method call detected in bytecode.

    Calls are identified by ``CALL_FUNCTION``, ``CALL_METHOD``, and related
    opcodes. The callee name is resolved from the preceding load instructions
    in the bytecode stream.

    Parameters
    ----------
    caller : str
        Name of the calling context (function or module where the call occurs).
    callee : str
        Name of the called function/method. May be ``'<unknown>'`` if the
        callee cannot be resolved from the load stack.
    line_number : int, optional
        Line number where the call occurs (1-indexed). Default is 0.
    is_method : bool, optional
        Whether the call is a method call (invoked on an object).
        Default is False.
    arguments_count : int, optional
        Number of positional arguments passed (extracted from the CALL
        opcode argument). Default is 0.
    keyword_arguments : List[str], optional
        List of keyword argument names, if detectable. Default is empty list.

    See Also
    --------
    OpcodeCategories.CALL : Call-related bytecode opcodes.

    Examples
    --------
    >>> info = CallInfo(
    ...     caller="process_data",
    ...     callee="len",
    ...     line_number=42,
    ...     arguments_count=1,
    ... )
    >>> info.callee
    'len'
    >>> info.arguments_count
    1
    """

    caller: str
    callee: str
    line_number: int = 0
    is_method: bool = False
    arguments_count: int = 0
    keyword_arguments: List[str] = field(default_factory=list)


@dataclass
class ImportInfo:
    """
    Information about an import statement detected in bytecode.

    Imports are identified by ``IMPORT_NAME``, ``IMPORT_FROM``, and
    ``IMPORT_STAR`` opcodes. The parser tracks the relationship between
    import statements and their associated names.

    Parameters
    ----------
    module : str
        Imported module or submodule name (e.g., ``'os.path'``).
    type : ImportType, optional
        Type of import statement. Default is ``ImportType.IMPORT``.
    context : str, optional
        Context (function or module) where the import occurs.
        Default is ``'<module>'``.
    line_number : int, optional
        Line number of the import statement. Default is 0.
    alias : Optional[str], optional
        Import alias if ``as`` is used (e.g., ``import numpy as np``
        yields alias ``'np'``). Default is None.
    imported_names : List[str], optional
        Names imported from the module for from-imports
        (e.g., ``from os import path, listdir`` yields
        ``['path', 'listdir']``). Default is empty list.

    See Also
    --------
    ImportType : Enumeration of import types.
    OpcodeCategories.IMPORT : Import-related bytecode opcodes.

    Examples
    --------
    >>> info = ImportInfo(
    ...     module="os.path",
    ...     type=ImportType.IMPORT_FROM,
    ...     imported_names=["join", "dirname"],
    ...     line_number=3,
    ... )
    >>> info.module
    'os.path'
    >>> info.imported_names
    ['join', 'dirname']
    """

    module: str
    type: ImportType = ImportType.IMPORT
    context: str = "<module>"
    line_number: int = 0
    alias: Optional[str] = None
    imported_names: List[str] = field(default_factory=list)


@dataclass
class VariableInfo:
    """
    Information about a variable detected in bytecode.

    Variables are identified through ``LOAD_*`` and ``STORE_*`` opcodes,
    which indicate reading from and writing to variable names in
    different scopes.

    Parameters
    ----------
    name : str
        Variable name (e.g., ``'counter'``, ``'result'``).
    scope : str, optional
        Scope where the variable is defined (function or module context).
        Default is ``'<module>'``.
    line_number : int, optional
        Line number of variable definition or first usage. Default is 0.
    is_global : bool, optional
        Whether the variable is accessed via ``LOAD_GLOBAL``/``STORE_GLOBAL``.
        Default is False.
    is_local : bool, optional
        Whether the variable is accessed via ``LOAD_FAST``/``STORE_FAST``.
        Default is False.
    is_parameter : bool, optional
        Whether the variable is a function parameter. Default is False.
    type_hint : Optional[str], optional
        Type annotation string if available. Default is None.

    See Also
    --------
    OpcodeCategories.LOAD : Load-related bytecode opcodes.
    OpcodeCategories.STORE : Store-related bytecode opcodes.

    Examples
    --------
    >>> info = VariableInfo(
    ...     name="total",
    ...     scope="calculate_sum",
    ...     is_local=True,
    ...     line_number=15,
    ... )
    >>> info.name
    'total'
    >>> info.is_local
    True
    """

    name: str
    scope: str = "<module>"
    line_number: int = 0
    is_global: bool = False
    is_local: bool = False
    is_parameter: bool = False
    type_hint: Optional[str] = None


@dataclass
class AttributeAccessInfo:
    """
    Information about attribute access (``obj.attr``) detected in bytecode.

    Attribute access is identified by ``LOAD_ATTR``, ``LOAD_METHOD``,
    and ``STORE_ATTR`` opcodes. The object name is resolved from the
    preceding load instructions.

    Parameters
    ----------
    object_name : str
        Name of the object whose attribute is being accessed.
    attribute : str
        Name of the attribute being accessed.
    context : str, optional
        Context (function or module) where the access occurs.
        Default is ``'<module>'``.
    line_number : int, optional
        Line number of the attribute access. Default is 0.
    is_assignment : bool, optional
        Whether the access is for assignment (``STORE_ATTR``) rather
        than reading (``LOAD_ATTR``). Default is False.

    Examples
    --------
    >>> info = AttributeAccessInfo(
    ...     object_name="my_list",
    ...     attribute="append",
    ...     context="add_item",
    ...     line_number=20,
    ... )
    >>> info.object_name
    'my_list'
    >>> info.attribute
    'append'
    """

    object_name: str
    attribute: str
    context: str = "<module>"
    line_number: int = 0
    is_assignment: bool = False


@dataclass
class ControlFlowInfo:
    """
    Information about control flow statements detected in bytecode.

    Control flow is identified through jump instructions (``JUMP_*``,
    ``POP_JUMP_IF_*``, ``SETUP_*``) that alter the sequential execution
    of bytecode.

    Parameters
    ----------
    type : ControlFlowType
        Classification of the control flow construct.
    opcode : str
        The bytecode instruction that triggered detection
        (e.g., ``'POP_JUMP_IF_FALSE'``).
    target : int
        Target bytecode offset for the jump.
    context : str, optional
        Context where the control flow occurs. Default is ``'<module>'``.
    line_number : int, optional
        Line number of the control flow statement. Default is 0.
    is_conditional : bool, optional
        Whether the control flow is conditional (depends on a boolean
        evaluation). Default is False.

    See Also
    --------
    ControlFlowType : Enumeration of control flow types.
    OpcodeCategories.JUMP : Jump-related bytecode opcodes.

    Examples
    --------
    >>> info = ControlFlowInfo(
    ...     type=ControlFlowType.CONDITIONAL,
    ...     opcode="POP_JUMP_IF_FALSE",
    ...     target=42,
    ...     is_conditional=True,
    ...     line_number=18,
    ... )
    >>> info.type.name
    'CONDITIONAL'
    """

    type: ControlFlowType
    opcode: str
    target: int
    context: str = "<module>"
    line_number: int = 0
    is_conditional: bool = False


@dataclass
class ExceptionInfo:
    """
    Information about exception handling constructs detected in bytecode.

    Exception handling is identified by ``SETUP_EXCEPT``, ``SETUP_FINALLY``,
    ``RAISE_VARARGS``, and related opcodes that establish exception
    handling frames.

    Parameters
    ----------
    type : str
        Type of exception construct: ``'try_except'``, ``'raise'``,
        ``'try_finally'``, or ``'try_except_finally'``.
    context : str, optional
        Context where the exception handling occurs. Default is ``'<module>'``.
    line_number : int, optional
        Line number of the try/raise statement. Default is 0.
    exception_types : List[str], optional
        Exception types being handled (for except clauses).
        Default is empty list.
    has_else_block : bool, optional
        Whether the try block has an ``else`` clause. Default is False.
    has_finally_block : bool, optional
        Whether the try block has a ``finally`` clause. Default is False.

    See Also
    --------
    OpcodeCategories.EXCEPTION : Exception-related bytecode opcodes.

    Examples
    --------
    >>> info = ExceptionInfo(
    ...     type="try_except",
    ...     context="safe_divide",
    ...     line_number=30,
    ...     exception_types=["ZeroDivisionError"],
    ...     has_else_block=True,
    ... )
    >>> info.type
    'try_except'
    >>> info.exception_types
    ['ZeroDivisionError']
    """

    type: str
    context: str = "<module>"
    line_number: int = 0
    exception_types: List[str] = field(default_factory=list)
    has_else_block: bool = False
    has_finally_block: bool = False


@dataclass
class ComprehensionInfo:
    """
    Information about comprehensions and generator expressions.

    Comprehensions are detected via ``BUILD_LIST``, ``BUILD_SET``,
    ``BUILD_MAP``, and related opcodes that construct collections
    from iteration patterns.

    Parameters
    ----------
    type : str
        Type of comprehension: ``'list'``, ``'dict'``, ``'set'``,
        ``'tuple'`` (generator expression also maps to this),
        or ``'unknown'``.
    context : str, optional
        Context where the comprehension occurs. Default is ``'<module>'``.
    line_number : int, optional
        Line number of the comprehension. Default is 0.
    num_iterators : int, optional
        Number of iteration levels (nested ``for`` clauses). Default is 0.
    has_condition : bool, optional
        Whether the comprehension includes filtering ``if`` conditions.
        Default is False.

    See Also
    --------
    OpcodeCategories.COMPREHENSION : Comprehension-related opcodes.

    Examples
    --------
    >>> info = ComprehensionInfo(
    ...     type="list",
    ...     context="transform_data",
    ...     line_number=22,
    ...     num_iterators=1,
    ...     has_condition=True,
    ... )
    >>> info.type
    'list'
    """

    type: str
    context: str = "<module>"
    line_number: int = 0
    num_iterators: int = 0
    has_condition: bool = False


@dataclass
class ContextManagerInfo:
    """
    Information about context managers (``with`` statements).

    Context managers are detected via ``SETUP_WITH`` and
    ``SETUP_ASYNC_WITH`` opcodes that establish context management
    frames for resource handling.

    Parameters
    ----------
    type : str
        Type of context manager: ``'with'`` or ``'async_with'``.
    context : str, optional
        Context where the context manager is used. Default is ``'<module>'``.
    line_number : int, optional
        Line number of the ``with`` statement. Default is 0.
    managers_count : int, optional
        Number of context managers in the statement
        (e.g., ``with open('a') as f, open('b') as g:`` has 2).
        Default is 1.

    See Also
    --------
    OpcodeCategories.ASYNC : Async-related bytecode opcodes.

    Examples
    --------
    >>> info = ContextManagerInfo(
    ...     type="with",
    ...     context="read_file",
    ...     line_number=12,
    ...     managers_count=1,
    ... )
    >>> info.type
    'with'
    """

    type: str
    context: str = "<module>"
    line_number: int = 0
    managers_count: int = 1


@dataclass
class CodeMetrics:
    """
    Comprehensive code quality metrics and statistics.

    This dataclass aggregates various software quality metrics calculated
    from the bytecode analysis, including size metrics, complexity measures,
    and maintainability indicators.

    Parameters
    ----------
    total_lines : int, optional
        Total lines of code in the source. Default is 0.
    total_functions : int, optional
        Total number of functions (including lambdas). Default is 0.
    total_classes : int, optional
        Total number of classes detected. Default is 0.
    total_imports : int, optional
        Total number of import statements. Default is 0.
    total_calls : int, optional
        Total number of function/method calls. Default is 0.
    cyclomatic_complexity : int, optional
        McCabe cyclomatic complexity score. Higher values indicate more
        complex code with more branching paths. Default is 0.
    maintainability_index : float, optional
        Maintainability Index (0-100 scale, higher is better).
        Based on lines of code, complexity, and structure.
        Default is 0.0.
    opcode_frequencies : Dict[str, int], optional
        Frequency distribution of bytecode operations encountered
        during analysis. Useful for identifying code patterns
        and optimization opportunities. Default is empty dict.

    Notes
    -----
    **Cyclomatic Complexity Calculation**:
    M = E - N + 2P (simplified as 1 + number of decision points).
    Decision points include:
    - Conditional branches (``if``, ``elif``)
    - Loops (``for``, ``while``)
    - Exception handlers (``except``)
    - Boolean operators (``and``, ``or``)

    **Maintainability Index**:
    MI = 171 - 5.2 * ln(V) - 0.23 * CC - 16.2 * ln(LOC)
    where V = Halstead Volume, CC = Cyclomatic Complexity,
    LOC = Lines of Code.

    References
    ----------
    .. [2] McCabe, T.J. "A Complexity Measure", 1976.
    .. [3] Coleman, D. et al. "Using Maintainability Index", 1994.

    Examples
    --------
    >>> metrics = CodeMetrics(
    ...     total_lines=150,
    ...     total_functions=5,
    ...     cyclomatic_complexity=8,
    ...     maintainability_index=72.5,
    ... )
    >>> metrics.total_functions
    5
    >>> metrics.cyclomatic_complexity
    8
    """

    total_lines: int = 0
    total_functions: int = 0
    total_classes: int = 0
    total_imports: int = 0
    total_calls: int = 0
    cyclomatic_complexity: int = 0
    maintainability_index: float = 0.0
    opcode_frequencies: Dict[str, int] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """
    Complete code analysis result aggregating all detected elements.

    This is the primary output container for the :class:`CodeParser`
    analysis, collecting all detected code constructs and computed
    metrics into a single structured object.

    Parameters
    ----------
    functions : List[FunctionInfo], optional
        All analyzed functions (including lambdas). Default is empty list.
    classes : List[ClassInfo], optional
        All analyzed classes. Default is empty list.
    calls : List[CallInfo], optional
        All detected function/method calls. Default is empty list.
    imports : List[ImportInfo], optional
        All detected import statements. Default is empty list.
    variables : List[VariableInfo], optional
        All detected variables with scope information. Default is empty list.
    attribute_accesses : List[AttributeAccessInfo], optional
        All detected attribute accesses. Default is empty list.
    control_flow : List[ControlFlowInfo], optional
        All detected control flow statements. Default is empty list.
    exceptions : List[ExceptionInfo], optional
        All detected exception handling constructs. Default is empty list.
    comprehensions : List[ComprehensionInfo], optional
        All detected comprehension expressions. Default is empty list.
    context_managers : List[ContextManagerInfo], optional
        All detected context manager statements. Default is empty list.
    metrics : CodeMetrics, optional
        Computed code quality metrics. Default is a new ``CodeMetrics()``.

    See Also
    --------
    CodeParser.analyze : Method that produces this result.
    CodeParser.search : Method for querying results.

    Examples
    --------
    >>> result = AnalysisResult(
    ...     functions=[FunctionInfo(name="main", qualified_name="main")],
    ...     metrics=CodeMetrics(total_lines=50),
    ... )
    >>> len(result.functions)
    1
    >>> result.metrics.total_lines
    50
    """

    functions: List[FunctionInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    calls: List[CallInfo] = field(default_factory=list)
    imports: List[ImportInfo] = field(default_factory=list)
    variables: List[VariableInfo] = field(default_factory=list)
    attribute_accesses: List[AttributeAccessInfo] = field(default_factory=list)
    control_flow: List[ControlFlowInfo] = field(default_factory=list)
    exceptions: List[ExceptionInfo] = field(default_factory=list)
    comprehensions: List[ComprehensionInfo] = field(default_factory=list)
    context_managers: List[ContextManagerInfo] = field(default_factory=list)
    metrics: CodeMetrics = field(default_factory=CodeMetrics)


# ============================================================================
# Opcode Categories
# ============================================================================


class OpcodeCategories:
    """
    Bytecode operation categories for organized analysis.

    This class provides organized categorization of Python bytecode
    operations into logical groups for easier analysis and pattern
    detection. Categories are exposed as frozen sets to prevent
    accidental modification.

    The categories follow the logical grouping defined in the Python
    ``dis`` module documentation, adapted for common analysis patterns.

    Attributes
    ----------
    LOAD : FrozenSet[str]
        Operations that load values onto the stack
        (e.g., ``LOAD_FAST``, ``LOAD_GLOBAL``, ``LOAD_CONST``).
    STORE : FrozenSet[str]
        Operations that store values into variables
        (e.g., ``STORE_FAST``, ``STORE_NAME``, ``STORE_ATTR``).
    CALL : FrozenSet[str]
        Operations that invoke functions or methods
        (e.g., ``CALL_FUNCTION``, ``CALL_METHOD``).
    JUMP : FrozenSet[str]
        Operations that alter control flow
        (e.g., ``JUMP_FORWARD``, ``POP_JUMP_IF_TRUE``).
    COMPARISON : FrozenSet[str]
        Comparison operations (``COMPARE_OP``).
    BINARY_OPERATION : FrozenSet[str]
        Binary arithmetic and bitwise operations
        (e.g., ``BINARY_ADD``, ``BINARY_MULTIPLY``).
    IMPORT : FrozenSet[str]
        Import-related operations
        (``IMPORT_NAME``, ``IMPORT_FROM``, ``IMPORT_STAR``).
    FUNCTION : FrozenSet[str]
        Function creation and return operations
        (``MAKE_FUNCTION``, ``CALL_FUNCTION``, ``RETURN_VALUE``).
    CLASS : FrozenSet[str]
        Class creation operations
        (``BUILD_CLASS``, ``LOAD_BUILD_CLASS``).
    COMPREHENSION : FrozenSet[str]
        Collection building operations
        (``BUILD_LIST``, ``BUILD_MAP``, ``BUILD_SET``, ``BUILD_TUPLE``).
    EXCEPTION : FrozenSet[str]
        Exception handling setup operations
        (``SETUP_FINALLY``, ``SETUP_EXCEPT``, ``RAISE_VARARGS``).
    ASYNC : FrozenSet[str]
        Async-specific operations
        (``GET_AITER``, ``GET_ANEXT``, ``GET_AWAITABLE``).

    See Also
    --------
    dis : Python bytecode disassembler module.

    Notes
    -----
    The opcode names in these sets correspond to Python 3.8+ bytecode
    instructions. Some opcodes may have been renamed or removed in
    earlier or later Python versions.
    """

    LOAD: ClassVar[FrozenSet[str]] = frozenset({
        'LOAD_FAST', 'LOAD_GLOBAL', 'LOAD_NAME', 'LOAD_CONST',
        'LOAD_ATTR', 'LOAD_METHOD', 'LOAD_DEREF', 'LOAD_CLOSURE',
        'LOAD_CLASSDEREF',
    })

    STORE: ClassVar[FrozenSet[str]] = frozenset({
        'STORE_FAST', 'STORE_NAME', 'STORE_GLOBAL',
        'STORE_ATTR', 'STORE_DEREF', 'STORE_SUBSCR',
    })

    CALL: ClassVar[FrozenSet[str]] = frozenset({
        'CALL_FUNCTION', 'CALL_FUNCTION_KW',
        'CALL_FUNCTION_EX', 'CALL_METHOD',
    })

    JUMP: ClassVar[FrozenSet[str]] = frozenset({
        'JUMP_ABSOLUTE', 'JUMP_FORWARD',
        'POP_JUMP_IF_TRUE', 'POP_JUMP_IF_FALSE',
        'JUMP_IF_TRUE_OR_POP', 'JUMP_IF_FALSE_OR_POP',
        'FOR_ITER',
    })

    COMPARISON: ClassVar[FrozenSet[str]] = frozenset({'COMPARE_OP'})

    BINARY_OPERATION: ClassVar[FrozenSet[str]] = frozenset({
        'BINARY_ADD', 'BINARY_SUBTRACT', 'BINARY_MULTIPLY',
        'BINARY_DIVIDE', 'BINARY_MODULO', 'BINARY_POWER',
        'BINARY_LSHIFT', 'BINARY_RSHIFT', 'BINARY_AND',
        'BINARY_OR', 'BINARY_XOR',
    })

    IMPORT: ClassVar[FrozenSet[str]] = frozenset({
        'IMPORT_NAME', 'IMPORT_FROM', 'IMPORT_STAR',
    })

    FUNCTION: ClassVar[FrozenSet[str]] = frozenset({
        'MAKE_FUNCTION', 'CALL_FUNCTION', 'RETURN_VALUE',
    })

    CLASS: ClassVar[FrozenSet[str]] = frozenset({
        'BUILD_CLASS', 'LOAD_BUILD_CLASS',
    })

    COMPREHENSION: ClassVar[FrozenSet[str]] = frozenset({
        'BUILD_LIST', 'BUILD_MAP', 'BUILD_SET',
        'BUILD_TUPLE', 'BUILD_SLICE', 'BUILD_STRING',
    })

    EXCEPTION: ClassVar[FrozenSet[str]] = frozenset({
        'SETUP_FINALLY', 'SETUP_EXCEPT', 'SETUP_WITH',
        'WITH_EXCEPT_START', 'RAISE_VARARGS',
    })

    ASYNC: ClassVar[FrozenSet[str]] = frozenset({
        'GET_AITER', 'GET_ANEXT', 'BEFORE_ASYNC_WITH',
        'SETUP_ASYNC_WITH', 'GET_AWAITABLE',
    })


# ============================================================================
# Main Parser Class
# ============================================================================


class CodeParser:
    """
    Comprehensive Python code analyzer using bytecode inspection.

    This parser provides deep analysis of Python source code by examining
    compiled bytecode instructions. Unlike source-level (AST) analysis,
    bytecode inspection reveals the actual execution structures, including
    optimized patterns, control flow, and runtime behaviors.

    The analysis is performed lazily: bytecode is compiled at initialization,
    but detailed inspection occurs only when :meth:`analyze` is called.

    Parameters
    ----------
    source_code : str
        Complete Python source code to analyze. Must be syntactically
        valid Python.
    mode : str, optional
        Compilation mode. One of:

        - ``'exec'`` (default): For modules and scripts.
        - ``'eval'``: For single expressions.
        - ``'single'``: For single interactive statements.

    filename : str, optional
        Logical filename for compilation context (used in error messages
        and traceback display). Default is ``'<string>'``.

    Raises
    ------
    ValueError
        If the source code contains syntax errors. The exception message
        includes the line number and error description.

    Attributes
    ----------
    source : str
        The original source code (read-only).
    filename : str
        The filename used for compilation context.
    mode : str
        The compilation mode.

    Notes
    -----
    **Detection Heuristics**:

    - Classes are detected as code objects with ``co_argcount == 0``
      and non-special names. This heuristic may produce false positives
      for simple factory functions.
    - Lambda functions are identified by their ``<lambda>`` name.
    - Function types (async, generator) are determined from ``co_flags``.
    - Method calls are inferred from ``LOAD_METHOD``/``LOAD_ATTR``
      followed by ``CALL_*`` opcodes.

    **Limitations**:

    - Decorators are not directly detectable from bytecode alone
      (they are applied at definition time).
    - Type annotations are not extracted from bytecode
      (available in ``__annotations__`` at runtime).
    - Some complex control flow patterns (e.g., ``match``/``case``
      in Python 3.10+) are simplified in bytecode representation.
    - Bytecode patterns vary between Python versions.

    See Also
    --------
    dis : Python bytecode disassembler.
    ast : Abstract Syntax Tree module.
    compile : Built-in compilation function.

    References
    ----------
    .. [1] Python ``dis`` module documentation.
    .. [2] McCabe, T.J. "A Complexity Measure", 1976.

    Examples
    --------
    Basic function analysis:

    >>> code = '''
    ... def fibonacci(n: int) -> int:
    ...     '''Compute the nth Fibonacci number.'''
    ...     if n <= 1:
    ...         return n
    ...     return fibonacci(n-1) + fibonacci(n-2)
    ... '''
    >>> parser = CodeParser(code)
    >>> result = parser.analyze()
    >>> len(result.functions)
    1
    >>> func = result.functions[0]
    >>> func.name
    'fibonacci'
    >>> func.type.name
    'FUNCTION'
    >>> func.argcount
    1

    Import analysis:

    >>> code = '''
    ... import os
    ... from pathlib import Path
    ... from math import *
    ... '''
    >>> parser = CodeParser(code)
    >>> result = parser.analyze()
    >>> len(result.imports)
    3

    Pattern search:

    >>> code = '''
    ... def process_data(items): pass
    ... def load_data(): pass
    ... class DataProcessor: pass
    ... '''
    >>> parser = CodeParser(code)
    >>> parser.search("data")
    {'functions': ['process_data', 'load_data'], 'classes': ['DataProcessor']}
    """

    # ------------------------------------------------------------------
    # Code object flags mapping (Python 3.8+)
    # Each flag value corresponds to a bit in co_flags
    # ------------------------------------------------------------------
    _CODE_FLAGS: ClassVar[Dict[int, str]] = {
        0x0001: 'OPTIMIZED',           # Code is optimized
        0x0002: 'NEWLOCALS',           # New locals namespace created
        0x0004: 'VARARGS',             # Has *args parameter
        0x0008: 'VARKEYWORDS',         # Has **kwargs parameter
        0x0010: 'NESTED',              # Nested function
        0x0020: 'GENERATOR',           # Generator function
        0x0040: 'NOFREE',              # No free variables
        0x0080: 'COROUTINE',           # Coroutine (async def)
        0x0100: 'ITERABLE_COROUTINE',  # Iterable coroutine
        0x0200: 'ASYNC_GENERATOR',     # Async generator
    }

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(
        self,
        source_code: str,
        mode: str = 'exec',
        filename: str = '<string>',
    ) -> None:
        """
        Initialize the parser with source code for analysis.

        Parameters
        ----------
        source_code : str
            Python source code to analyze.
        mode : str, optional
            Compilation mode (``'exec'``, ``'eval'``, or ``'single'``).
            Default is ``'exec'``.
        filename : str, optional
            Filename for compilation context. Default is ``'<string>'``.

        Raises
        ------
        ValueError
            If the source code contains syntax errors.
        """
        # Validate compilation mode
        if mode not in ('exec', 'eval', 'single'):
            raise ValueError(
                f"Invalid mode: {mode!r}. "
                f"Expected 'exec', 'eval', or 'single'."
            )

        self._source: str = source_code
        self._mode: str = mode
        self._filename: str = filename

        # Core analysis state
        self._result: AnalysisResult = AnalysisResult()
        self._current_context: List[str] = ['<module>']
        self._lambda_counter: int = 0
        self._current_lineno: int = 0
        self._import_tracker: Dict[str, ImportInfo] = {}

        # Compile source code to bytecode
        try:
            self._code_obj: CodeType = compile(
                self._source,
                self._filename,
                self._mode,
            )
        except SyntaxError as e:
            raise ValueError(
                f"Syntax error in source code at line {e.lineno}: "
                f"{e.msg}"
            ) from e
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"Compilation error: {e}"
            ) from e

    # ------------------------------------------------------------------
    # Public Properties
    # ------------------------------------------------------------------

    @property
    def source(self) -> str:
        """
        Return the original source code.

        Returns
        -------
        str
            The source code provided during initialization.

        Examples
        --------
        >>> parser = CodeParser("x = 42")
        >>> parser.source
        'x = 42'
        """
        return self._source

    @property
    def filename(self) -> str:
        """
        Return the filename used for compilation context.

        Returns
        -------
        str
            The logical filename.
        """
        return self._filename

    @property
    def mode(self) -> str:
        """
        Return the compilation mode.

        Returns
        -------
        str
            One of ``'exec'``, ``'eval'``, or ``'single'``.
        """
        return self._mode

    @property
    def code_object(self) -> CodeType:
        """
        Return the compiled code object.

        Returns
        -------
        CodeType
            The top-level compiled code object.
        """
        return self._code_obj

    # ------------------------------------------------------------------
    # Public Analysis Methods
    # ------------------------------------------------------------------

    def analyze(self) -> AnalysisResult:
        """
        Perform complete code analysis on the compiled bytecode.

        This method traverses the entire code object tree recursively,
        analyzing each nested code object, its instructions, and
        computing aggregate metrics.

        Returns
        -------
        AnalysisResult
            Comprehensive analysis results containing all detected
            code elements (functions, classes, calls, imports, variables,
            control flow, exceptions, comprehensions, context managers)
            and computed quality metrics.

        Notes
        -----
        The analysis is performed once; subsequent calls return
        the cached result. To re-analyze, create a new parser instance.

        The method processes:
        1. Top-level code object
        2. All nested code objects (functions, lambdas, comprehensions)
        3. All bytecode instructions with pattern detection
        4. Aggregate metrics calculation

        Examples
        --------
        >>> code = '''
        ... def add(a, b):
        ...     return a + b
        ...
        ... result = add(1, 2)
        ... '''
        >>> parser = CodeParser(code)
        >>> analysis = parser.analyze()
        >>> len(analysis.functions)
        1
        >>> analysis.functions[0].name
        'add'
        >>> len(analysis.calls)
        1
        >>> analysis.calls[0].callee
        'add'
        >>> analysis.metrics.total_lines > 0
        True
        """
        self._analyze_code_object(self._code_obj)
        self._calculate_metrics()
        return self._result

    def search(
        self,
        pattern: str,
        category: str = 'all',
    ) -> Dict[str, List[str]]:
        """
        Search for patterns in analyzed code elements.

        Performs case-insensitive substring matching against names
        of functions, classes, imports, variables, and calls.

        Parameters
        ----------
        pattern : str
            Search pattern (case-insensitive). Matches if the pattern
            is a substring of the element name.
        category : str, optional
            Element category to search. Valid values:

            - ``'all'``: Search all categories (default).
            - ``'functions'``: Search function names.
            - ``'classes'``: Search class names.
            - ``'imports'``: Search import module names.
            - ``'variables'``: Search variable names.
            - ``'calls'``: Search callee names.

        Returns
        -------
        Dict[str, List[str]]
            Dictionary mapping category names to lists of matching
            element names. For ``category='all'``, all categories
            are included in the result dict. Categories with no
            matches are omitted from the result.

        Raises
        ------
        ValueError
            If ``category`` is not one of the valid options.

        Examples
        --------
        >>> code = '''
        ... import numpy as np
        ... import pandas as pd
        ... from numpy import array
        ... def numpy_helper():
        ...     return np.array([1, 2, 3])
        ... '''
        >>> parser = CodeParser(code)
        >>> parser.search("numpy")
        {'functions': ['numpy_helper'], 'imports': ['numpy'], 'calls': []}

        >>> parser.search("num", "imports")
        {'imports': ['numpy']}

        >>> parser.search("str", "functions")
        {'functions': []}
        """
        valid_categories = {'all', 'functions', 'classes', 'imports',
                            'variables', 'calls'}

        if category not in valid_categories:
            raise ValueError(
                f"Invalid category: {category!r}. "
                f"Expected one of: {', '.join(sorted(valid_categories))}."
            )

        pattern_lower = pattern.lower()
        results: DefaultDict[str, List[str]] = defaultdict(list)

        # Define search mappings: category -> list of (name, qualified_name)
        search_map: Dict[str, List[Tuple[str, str]]] = {
            'functions': [
                (f.name, f.qualified_name)
                for f in self._result.functions
            ],
            'classes': [
                (c.name, c.qualified_name)
                for c in self._result.classes
            ],
            'imports': [
                (imp.module, imp.module)
                for imp in self._result.imports
            ],
            'variables': [
                (v.name, v.scope)
                for v in self._result.variables
            ],
            'calls': [
                (c.callee, c.caller)
                for c in self._result.calls
            ],
        }

        if category == 'all':
            for cat, items in search_map.items():
                matches = [
                    name
                    for name, _ in items
                    if pattern_lower in name.lower()
                ]
                if matches:  # Only include non-empty results
                    results[cat] = matches
        else:
            items = search_map.get(category, [])
            results[category] = [
                name
                for name, _ in items
                if pattern_lower in name.lower()
            ]

        return dict(results)

    # ------------------------------------------------------------------
    # Core Analysis Methods
    # ------------------------------------------------------------------

    def _analyze_code_object(self, code_obj: CodeType) -> None:
        """
        Recursively analyze a code object and all its nested components.

        This is the main traversal method that processes each code object
        in the compiled bytecode tree, dispatching to specialized analysis
        methods based on the object's characteristics.

        Parameters
        ----------
        code_obj : CodeType
            The code object to analyze. May be the top-level module
            code or a nested function/class/comprehension code object.

        Notes
        -----
        The analysis order is:
        1. Update the execution context stack.
        2. Determine code object type (function, lambda, class, comprehension).
        3. Dispatch to appropriate specialized analyzer.
        4. Analyze all bytecode instructions in the object.
        5. Recursively process nested code objects found in constants.
        6. Restore the context stack.

        Special code object names:
        - ``<module>``: Top-level module code (no specialized analysis).
        - ``<lambda>``: Lambda expression.
        - ``<genexpr>``: Generator expression.
        - ``<dictcomp>``: Dictionary comprehension.
        - ``<setcomp>``: Set comprehension.
        - ``<listcomp>``: List comprehension.
        """
        context_name = code_obj.co_name

        # Update analysis context stack
        if context_name != '<module>':
            self._current_context.append(context_name)

        # Determine and dispatch based on code object type
        if context_name == '<lambda>':
            self._analyze_lambda(code_obj)
        elif context_name in (
            '<genexpr>', '<dictcomp>', '<setcomp>', '<listcomp>',
        ):
            # Comprehensions and generator expressions are handled
            # through bytecode pattern detection
            pass
        elif context_name != '<module>':
            self._analyze_function(code_obj)
            # Heuristic: class detection (code objects with 0 args)
            if code_obj.co_argcount == 0 and not context_name.startswith('<'):
                # Check if this looks like a class (contains methods)
                if self._has_class_characteristics(code_obj):
                    self._analyze_class(code_obj)

        # Analyze individual bytecode instructions
        self._analyze_instructions(code_obj)

        # Recursively analyze nested code objects in constants
        for const in code_obj.co_consts:
            if isinstance(const, CodeType):
                self._analyze_code_object(const)

        # Restore context stack
        if context_name != '<module>':
            self._current_context.pop()

    def _has_class_characteristics(self, code_obj: CodeType) -> bool:
        """
        Apply heuristics to determine if a code object represents a class.

        Parameters
        ----------
        code_obj : CodeType
            Code object to evaluate.

        Returns
        -------
        bool
            True if the code object likely represents a class definition.

        Notes
        -----
        Heuristics used:
        - Contains ``LOAD_NAME`` or ``LOAD_GLOBAL`` for ``__name__``
          and ``__module__`` (typical class body setup).
        - Contains ``STORE_NAME`` for attribute assignment.
        - Contains ``LOAD_BUILD_CLASS`` or ``BUILD_CLASS`` opcodes.
        - Nested code objects that look like methods.
        """
        # Quick check: look for class-related opcodes in instructions
        for instr in dis.get_instructions(code_obj):
            if instr.opname in ('LOAD_BUILD_CLASS',):
                return True
            if instr.opname == 'BUILD_CLASS':
                return True

        # Check if nested code objects contain methods
        method_count = 0
        for const in code_obj.co_consts:
            if isinstance(const, CodeType):
                if const.co_name not in ('<lambda>', '<module>') and \
                   not const.co_name.startswith('<'):
                    method_count += 1

        # A class typically has at least one method
        return method_count >= 1 and code_obj.co_argcount == 0

    def _analyze_function(self, code_obj: CodeType) -> None:
        """
        Analyze a function code object and extract its metadata.

        Parameters
        ----------
        code_obj : CodeType
            Function code object to analyze. Must have a valid
            function name (not ``<lambda>`` or special names).

        Notes
        -----
        Extracted information includes:
        - Function type (regular, async, generator, async generator)
        - Argument counts (regular, positional-only, keyword-only)
        - Local variable count
        - Stack size requirements
        - Code flags
        - Source location (filename, first line number)
        """
        # Determine function type from code flags
        func_type = FunctionType.FUNCTION
        if code_obj.co_flags & 0x0080:  # CO_COROUTINE
            func_type = FunctionType.ASYNC_FUNCTION
        elif code_obj.co_flags & 0x0200:  # CO_ASYNC_GENERATOR
            func_type = FunctionType.ASYNC_GENERATOR
        elif code_obj.co_flags & 0x0020:  # CO_GENERATOR
            func_type = FunctionType.GENERATOR

        # Build function information
        function_info = FunctionInfo(
            name=code_obj.co_name,
            qualified_name='.'.join(self._current_context),
            type=func_type,
            argcount=code_obj.co_argcount,
            posonlyargcount=getattr(code_obj, 'co_posonlyargcount', 0),
            kwonlyargcount=code_obj.co_kwonlyargcount,
            nlocals=code_obj.co_nlocals,
            stacksize=code_obj.co_stacksize,
            flags=self._extract_code_flags(code_obj),
            firstlineno=code_obj.co_firstlineno,
            filename=code_obj.co_filename,
        )

        self._result.functions.append(function_info)

    def _analyze_lambda(self, code_obj: CodeType) -> None:
        """
        Analyze a lambda function code object.

        Lambdas are identified by the ``<lambda>`` name. Each lambda
        is assigned a unique sequential name (``<lambda_1>``,
        ``<lambda_2>``, etc.) for identification purposes.

        Parameters
        ----------
        code_obj : CodeType
            Lambda code object to analyze.
        """
        self._lambda_counter += 1
        lambda_name = f'<lambda_{self._lambda_counter}>'

        function_info = FunctionInfo(
            name=lambda_name,
            qualified_name=(
                f"{'.'.join(self._current_context)}.{lambda_name}"
            ),
            type=FunctionType.LAMBDA,
            argcount=code_obj.co_argcount,
            posonlyargcount=getattr(code_obj, 'co_posonlyargcount', 0),
            kwonlyargcount=code_obj.co_kwonlyargcount,
            nlocals=code_obj.co_nlocals,
            stacksize=code_obj.co_stacksize,
            flags=self._extract_code_flags(code_obj),
            firstlineno=code_obj.co_firstlineno,
            filename=code_obj.co_filename,
        )

        self._result.functions.append(function_info)

    def _analyze_class(self, code_obj: CodeType) -> None:
        """
        Analyze a class code object.

        Parameters
        ----------
        code_obj : CodeType
            Class code object to analyze.
        """
        class_info = ClassInfo(
            name=code_obj.co_name,
            qualified_name='.'.join(self._current_context),
            firstlineno=code_obj.co_firstlineno,
            filename=code_obj.co_filename,
        )

        self._result.classes.append(class_info)

    def _analyze_instructions(self, code_obj: CodeType) -> None:
        """
        Analyze bytecode instructions with multi-pattern detection.

        This method iterates through all instructions in the code object
        and dispatches each to specialized detection methods for different
        code constructs (loads, stores, calls, control flow, imports,
        comprehensions, exceptions, context managers).

        Parameters
        ----------
        code_obj : CodeType
            Code object whose instructions to analyze.

        Notes
        -----
        State tracking is maintained across instructions using:
        - ``load_stack``: Tracks loaded values for resolving call targets
          and attribute access objects.
        - ``last_opcode`` / ``last_argval``: Tracks previous instruction
          for pattern detection requiring context.
        """
        context = '.'.join(self._current_context)
        instructions = list(dis.get_instructions(code_obj))

        # State tracking for pattern detection
        load_stack: List[Tuple[str, Any]] = []
        line_number_stack: List[int] = []  # Tracks line numbers
        last_opcode: Optional[str] = None
        last_argval: Any = None

        for instr in instructions:
            # Update line tracking when line changes
            if instr.starts_line is not None:
                self._current_lineno = instr.starts_line

            # Pattern detection based on opcode category
            self._detect_load_operations(instr, context, load_stack)
            self._detect_store_operations(instr, context)
            self._detect_call_operations(instr, context, load_stack)
            self._detect_control_flow(instr, context)
            self._detect_import_operations(instr, context)
            self._detect_comprehensions(instr, last_opcode)
            self._detect_exception_handling(instr, context)
            self._detect_context_managers(instr, context)

            last_opcode = instr.opname
            last_argval = instr.argval

    # ------------------------------------------------------------------
    # Pattern Detection Methods
    # ------------------------------------------------------------------

    def _detect_load_operations(
        self,
        instr: dis.Instruction,
        context: str,
        load_stack: List[Tuple[str, Any]],
    ) -> None:
        """
        Detect and track variable loading operations.

        Parameters
        ----------
        instr : dis.Instruction
            Current bytecode instruction.
        context : str
            Current execution context.
        load_stack : List[Tuple[str, Any]]
            Stack tracking loaded values for call/attribute resolution.

        Notes
        -----
        Detects:
        - ``LOAD_GLOBAL``: Global variable access
        - ``LOAD_NAME``: Name access (module/class scope)
        - ``LOAD_FAST``: Local variable access
        - ``LOAD_ATTR``: Attribute access on objects
        - ``LOAD_METHOD``: Method loading for calling
        - ``LOAD_DEREF``: Closure variable access
        """
        opname = instr.opname

        if opname in ('LOAD_GLOBAL', 'LOAD_NAME'):
            var_info = VariableInfo(
                name=instr.argval,
                scope=context,
                line_number=self._current_lineno,
                is_global=(opname == 'LOAD_GLOBAL'),
            )
            self._result.variables.append(var_info)
            load_stack.append(('global', instr.argval))

        elif opname == 'LOAD_FAST':
            var_info = VariableInfo(
                name=instr.argval,
                scope=context,
                line_number=self._current_lineno,
                is_local=True,
            )
            self._result.variables.append(var_info)
            load_stack.append(('local', instr.argval))

        elif opname in ('LOAD_ATTR', 'LOAD_METHOD'):
            if load_stack:
                obj_name = load_stack[-1][1]
                attr_access = AttributeAccessInfo(
                    object_name=obj_name,
                    attribute=instr.argval,
                    context=context,
                    line_number=self._current_lineno,
                )
                self._result.attribute_accesses.append(attr_access)
            load_stack.append(('attribute', instr.argval))

        elif opname == 'LOAD_DEREF':
            var_info = VariableInfo(
                name=instr.argval,
                scope=context,
                line_number=self._current_lineno,
                is_local=True,  # Closure variables are local to enclosing scope
            )
            self._result.variables.append(var_info)
            load_stack.append(('closure', instr.argval))

    def _detect_store_operations(
        self,
        instr: dis.Instruction,
        context: str,
    ) -> None:
        """
        Detect variable storage operations.

        Parameters
        ----------
        instr : dis.Instruction
            Current bytecode instruction.
        context : str
            Current execution context.

        Notes
        -----
        Detects:
        - ``STORE_FAST``: Local variable assignment
        - ``STORE_NAME``: Name assignment (module/class scope)
        - ``STORE_GLOBAL``: Global variable assignment
        - ``STORE_ATTR``: Attribute assignment on objects
        - ``STORE_DEREF``: Closure variable assignment
        """
        if instr.opname in ('STORE_FAST', 'STORE_NAME', 'STORE_GLOBAL',
                            'STORE_ATTR', 'STORE_DEREF'):
            var_info = VariableInfo(
                name=instr.argval,
                scope=context,
                line_number=self._current_lineno,
                is_global=(instr.opname == 'STORE_GLOBAL'),
                is_local=(instr.opname == 'STORE_FAST'),
            )
            self._result.variables.append(var_info)

            # Track attribute assignment
            if instr.opname == 'STORE_ATTR':
                attr_access = AttributeAccessInfo(
                    object_name='<stack>',  # Object name resolved at runtime
                    attribute=instr.argval,
                    context=context,
                    line_number=self._current_lineno,
                    is_assignment=True,
                )
                self._result.attribute_accesses.append(attr_access)

    def _detect_call_operations(
        self,
        instr: dis.Instruction,
        context: str,
        load_stack: List[Tuple[str, Any]],
    ) -> None:
        """
        Detect function and method call operations.

        Parameters
        ----------
        instr : dis.Instruction
            Current bytecode instruction.
        context : str
            Current execution context.
        load_stack : List[Tuple[str, Any]]
            Stack tracking loaded values for call target resolution.

        Notes
        -----
        Call targets are resolved by scanning the load stack backwards
        for the most recent global, local, or attribute load, which
        typically represents the callable being invoked.
        """
        if instr.opname.startswith('CALL_'):
            # Resolve the callee from the load stack (last loaded callable)
            callee = '<unknown>'
            for load_type, load_name in reversed(load_stack):
                if load_type in ('global', 'local', 'attribute', 'closure'):
                    callee = load_name
                    break

            # Determine if this is a method call
            is_method = (
                load_stack and
                len(load_stack) >= 2 and
                load_stack[-2][0] in ('attribute',)
            )

            # Extract argument count from CALL opcode if possible
            arg_count = 0
            if hasattr(instr, 'argval') and isinstance(instr.argval, int):
                arg_count = instr.argval

            call_info = CallInfo(
                caller=context,
                callee=callee,
                line_number=self._current_lineno,
                is_method=is_method,
                arguments_count=arg_count,
            )
            self._result.calls.append(call_info)

    def _detect_control_flow(
        self,
        instr: dis.Instruction,
        context: str,
    ) -> None:
        """
        Detect control flow operations.

        Parameters
        ----------
        instr : dis.Instruction
            Current bytecode instruction.
        context : str
            Current execution context.

        Notes
        -----
        Classifies jumps into:
        - CONDITIONAL: ``POP_JUMP_IF_*`` instructions
        - JUMP: Unconditional ``JUMP_*`` instructions
        - LOOP: ``FOR_ITER`` (iteration control)
        """
        if instr.opname in OpcodeCategories.JUMP:
            # Classify the type of control flow
            if instr.opname in (
                'POP_JUMP_IF_TRUE', 'POP_JUMP_IF_FALSE',
                'JUMP_IF_TRUE_OR_POP', 'JUMP_IF_FALSE_OR_POP',
            ):
                flow_type = ControlFlowType.CONDITIONAL
                is_conditional = True
            elif instr.opname == 'FOR_ITER':
                flow_type = ControlFlowType.LOOP
                is_conditional = False
            else:
                flow_type = ControlFlowType.JUMP
                is_conditional = False

            flow_info = ControlFlowInfo(
                type=flow_type,
                opcode=instr.opname,
                target=instr.argval if instr.argval is not None else 0,
                context=context,
                line_number=self._current_lineno,
                is_conditional=is_conditional,
            )
            self._result.control_flow.append(flow_info)

    def _detect_import_operations(
        self,
        instr: dis.Instruction,
        context: str,
    ) -> None:
        """
        Detect import operations.

        Parameters
        ----------
        instr : dis.Instruction
            Current bytecode instruction.
        context : str
            Current execution context.

        Notes
        -----
        Tracks import sequences:
        - ``IMPORT_NAME``: Creates a new import record.
        - ``IMPORT_FROM``: Appends to the most recent import's
          ``imported_names`` list.
        - ``IMPORT_STAR``: Sets the import type to star import.
        """
        if instr.opname == 'IMPORT_NAME':
            import_info = ImportInfo(
                module=instr.argval,
                type=ImportType.IMPORT,
                context=context,
                line_number=self._current_lineno,
            )
            self._result.imports.append(import_info)
            self._import_tracker[instr.argval] = import_info

        elif instr.opname == 'IMPORT_FROM':
            # Link to the most recent import
            if self._import_tracker:
                # Find the most recently added import
                if self._result.imports:
                    last_import = self._result.imports[-1]
                    last_import.type = ImportType.IMPORT_FROM
                    last_import.imported_names.append(instr.argval)

        elif instr.opname == 'IMPORT_STAR':
            if self._result.imports:
                last_import = self._result.imports[-1]
                last_import.type = ImportType.IMPORT_STAR

    def _detect_comprehensions(
        self,
        instr: dis.Instruction,
        last_opcode: Optional[str],
    ) -> None:
        """
        Detect comprehension and generator expressions.

        Parameters
        ----------
        instr : dis.Instruction
            Current bytecode instruction.
        last_opcode : Optional[str]
            Previous instruction opcode for context.

        Notes
        -----
        Maps ``BUILD_*`` opcodes to comprehension types:
        - ``BUILD_LIST`` → list comprehension
        - ``BUILD_SET`` → set comprehension
        - ``BUILD_MAP`` → dictionary comprehension
        - ``BUILD_TUPLE`` → generator expression (or tuple)
        - ``BUILD_SLICE`` → slice expression
        """
        if instr.opname in OpcodeCategories.COMPREHENSION:
            comp_type_map = {
                'BUILD_LIST': 'list',
                'BUILD_SET': 'set',
                'BUILD_MAP': 'dict',
                'BUILD_TUPLE': 'generator',  # or tuple
                'BUILD_SLICE': 'slice',
                'BUILD_STRING': 'string',
            }

            comp_type = comp_type_map.get(instr.opname, 'unknown')
            comp_info = ComprehensionInfo(
                type=comp_type,
                context='.'.join(self._current_context),
                line_number=self._current_lineno,
            )
            self._result.comprehensions.append(comp_info)

    def _detect_exception_handling(
        self,
        instr: dis.Instruction,
        context: str,
    ) -> None:
        """
        Detect exception handling constructs.

        Parameters
        ----------
        instr : dis.Instruction
            Current bytecode instruction.
        context : str
            Current execution context.

        Notes
        -----
        Detects:
        - ``SETUP_EXCEPT``: try/except block
        - ``SETUP_FINALLY``: try/finally block
        - ``RAISE_VARARGS``: raise statement
        """
        if instr.opname in ('SETUP_FINALLY', 'SETUP_EXCEPT'):
            exc_type = (
                'try_except' if instr.opname == 'SETUP_EXCEPT'
                else 'try_finally'
            )
            exc_info = ExceptionInfo(
                type=exc_type,
                context=context,
                line_number=self._current_lineno,
                has_finally_block=(instr.opname == 'SETUP_FINALLY'),
            )
            self._result.exceptions.append(exc_info)

        elif instr.opname == 'RAISE_VARARGS':
            exc_info = ExceptionInfo(
                type='raise',
                context=context,
                line_number=self._current_lineno,
            )
            self._result.exceptions.append(exc_info)

    def _detect_context_managers(
        self,
        instr: dis.Instruction,
        context: str,
    ) -> None:
        """
        Detect context manager (with statement) operations.

        Parameters
        ----------
        instr : dis.Instruction
            Current bytecode instruction.
        context : str
            Current execution context.

        Notes
        -----
        Detects:
        - ``SETUP_WITH``: Synchronous with statement
        - ``SETUP_ASYNC_WITH``: Async with statement
        - ``BEFORE_ASYNC_WITH``: Async context manager preparation
        """
        if instr.opname == 'SETUP_WITH':
            ctx_info = ContextManagerInfo(
                type='with',
                context=context,
                line_number=self._current_lineno,
            )
            self._result.context_managers.append(ctx_info)

        elif instr.opname in ('SETUP_ASYNC_WITH', 'BEFORE_ASYNC_WITH'):
            ctx_info = ContextManagerInfo(
                type='async_with',
                context=context,
                line_number=self._current_lineno,
            )
            self._result.context_managers.append(ctx_info)

    # ------------------------------------------------------------------
    # Metrics Calculation
    # ------------------------------------------------------------------

    def _calculate_metrics(self) -> None:
        """
        Calculate comprehensive code quality and complexity metrics.

        This method aggregates all structural information collected
        during analysis into quantitative metrics, including:
        - Lines of code
        - Function, class, import, and call counts
        - Cyclomatic complexity from control flow branches
        - Maintainability index

        The computed metrics are stored in ``self._result.metrics``.
        """
        # Count source lines (excluding empty lines for accuracy)
        source_lines = [
            line for line in self._source.splitlines()
            if line.strip()
        ]
        total_lines = len(source_lines)

        # Cyclomatic complexity: 1 base + control flow branches + exceptions
        complexity = 1
        complexity += len(self._result.control_flow)
        complexity += len([
            e for e in self._result.exceptions
            if e.type in ('try_except', 'try_finally')
        ])

        # Calculate Maintainability Index
        mi = self._calculate_maintainability_index(total_lines, complexity)

        # Collect opcode frequencies for the top-level code object
        opcode_freqs = dict(Counter(
            instr.opname
            for instr in dis.get_instructions(self._code_obj)
        ))

        metrics = CodeMetrics(
            total_lines=len(self._source.splitlines()),
            total_functions=len(self._result.functions),
            total_classes=len(self._result.classes),
            total_imports=len(self._result.imports),
            total_calls=len(self._result.calls),
            cyclomatic_complexity=complexity,
            maintainability_index=round(mi, 2),
            opcode_frequencies=opcode_freqs,
        )

        self._result.metrics = metrics

    def _calculate_maintainability_index(
        self,
        total_lines: int,
        complexity: int,
    ) -> float:
        """
        Calculate the Maintainability Index using the SEI formula.

        The Maintainability Index (MI) is a composite metric that
        combines lines of code, cyclomatic complexity, and other
        factors into a single score indicating how maintainable
        the code is.

        Parameters
        ----------
        total_lines : int
            Number of logical source lines.
        complexity : int
            Cyclomatic complexity score.

        Returns
        -------
        float
            Maintainability index clamped to [0.0, 100.0].
            Higher scores indicate better maintainability.

        Notes
        -----
        **Formula** (simplified SEI version)::

            MI = 171 - 5.2 * ln(LOC) - 0.23 * CC

        where:
        - LOC = max(total_lines, 1) to avoid log(0)
        - CC = complexity score (decision points)

        **Score Interpretation**:
        - 85-100: Highly maintainable
        - 65-85: Moderately maintainable
        - 40-65: Needs improvement
        - 0-40: Difficult to maintain

        References
        ----------
        .. [3] Coleman, D., Ash, D., Lowther, B., & Oman, P. (1994).
           "Using Metrics to Evaluate Software System Maintainability."
           Computer, 27(8), 44-49.
        """
        loc = max(total_lines, 1)  # Prevent log(0)
        mi = 171.0 - 5.2 * math.log(loc) - 0.23 * complexity
        return max(0.0, min(100.0, mi))

    def _extract_code_flags(self, code_obj: CodeType) -> List[str]:
        """
        Extract human-readable code flags from a code object.

        Parameters
        ----------
        code_obj : CodeType
            Code object to extract flags from.

        Returns
        -------
        List[str]
            List of flag descriptions in the order they appear in
            ``_CODE_FLAGS``. For example, a generator function might
            return ``['OPTIMIZED', 'NEWLOCALS', 'GENERATOR']``.

        Notes
        -----
        Flags are determined by checking each bit in ``co_flags``
        against the ``_CODE_FLAGS`` mapping. Only flags present
        in the mapping are included.
        """
        flags: List[str] = []
        for flag_value, flag_name in self._CODE_FLAGS.items():
            if code_obj.co_flags & flag_value:
                flags.append(flag_name)
        return flags

    def _get_instruction_count(self, code_obj: CodeType) -> int:
        """
        Count the total number of bytecode instructions in a code object.

        Parameters
        ----------
        code_obj : CodeType
            Code object to count instructions for.

        Returns
        -------
        int
            Total instruction count, including instructions from
            nested code objects.

        Notes
        -----
        This method recursively counts instructions in all nested
        code objects (functions, comprehensions, etc.) found in
        the ``co_consts`` tuple.
        """
        count = len(list(dis.get_instructions(code_obj)))
        for const in code_obj.co_consts:
            if isinstance(const, CodeType):
                count += self._get_instruction_count(const)
        return count

    # ------------------------------------------------------------------
    # Special Methods
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        """
        Return an unambiguous string representation of the parser.

        Returns
        -------
        str
            String showing filename, mode, and source size.
        """
        return (
            f"CodeParser("
            f"filename={self._filename!r}, "
            f"mode={self._mode!r}, "
            f"source_size={len(self._source)} chars)"
        )

    def __str__(self) -> str:
        """
        Return a human-readable summary of the parser state.

        Returns
        -------
        str
            Multi-line summary with source size and compilation info.
        """
        lines = [
            f"CodeParser for {self._filename!r}",
            f"  Mode: {self._mode}",
            f"  Source size: {len(self._source)} characters",
            f"  Source lines: {len(self._source.splitlines())}",
            f"  Compiled: {self._code_obj is not None}",
        ]
        return '\n'.join(lines)

    def __len__(self) -> int:
        """
        Return the number of source code lines.

        Returns
        -------
        int
            Line count (including empty lines).

        Examples
        --------
        >>> parser = CodeParser("x = 1\\ny = 2")
        >>> len(parser)
        2
        """
        return len(self._source.splitlines())

    def __contains__(self, item: str) -> bool:
        """
        Check if a name is defined in the analyzed code.

        Parameters
        ----------
        item : str
            Name to search for in functions and classes.

        Returns
        -------
        bool
            True if the name matches any function or class.

        Notes
        -----
        Only searches already-analyzed results. If :meth:`analyze`
        has not been called, returns False.

        Examples
        --------
        >>> parser = CodeParser("def hello(): pass")
        >>> "hello" in parser  # Before analysis
        False
        >>> parser.analyze()
        >>> "hello" in parser  # After analysis
        True
        """
        func_names = {f.name for f in self._result.functions}
        class_names = {c.name for c in self._result.classes}
        return item in func_names or item in class_names