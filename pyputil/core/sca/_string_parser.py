#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
 Python Source Code Static Analysis Module.

This module provides comprehensive static analysis of Python source code
using enhanced regular expression patterns and multi-stage parsing with
validation. It offers deep code inspection without executing the code,
making it safe for analyzing untrusted source files.

The StringParser class serves as the primary interface for all static
analysis operations, providing structural extraction, complexity metrics,
security vulnerability detection, dependency analysis, and code quality
scoring.

Features
--------
- Multi-stage parsing with validation
- Comprehensive complexity metrics (cyclomatic, cognitive, Halstead)
- Security vulnerability detection with CWE/OWASP mapping
- Dependency graph analysis with circular dependency detection
- Code quality scoring with maintainability index
- Smart caching for performance optimization
- Accurate line number tracking with character offset mapping

Notes
-----
This parser uses regex-based analysis rather than AST parsing. While this
approach is faster for simple extractions, it may have limitations with
complex Python syntax. For production-grade analysis, consider using the
built-in ``ast`` module or combining both approaches.

See Also
--------
ast : Abstract Syntax Tree module for precise parsing.
tokenize : Lexical scanner for Python source code.
radon : External library for code complexity metrics.
bandit : Security-focused static analysis tool.

References
----------
.. [1] McCabe, T.J. "A Complexity Measure", IEEE Transactions on Software
       Engineering, 1976.
.. [2] Halstead, M.H. "Elements of Software Science", Elsevier, 1977.
.. [3] "Maintainability Index Technique for Measuring Program
       Maintainability", SEI, 2001.

Examples
--------
>>> source = '''
... def calculate_average(numbers: list) -> float:
...     \"\"\"Calculate the average of a list of numbers.\"\"\"
...     if not numbers:
...         return 0.0
...     total = sum(numbers)
...     return total / len(numbers)
... '''
>>> parser = StringParser(source)
>>> funcs = parser.functions()
>>> len(funcs)
1
>>> funcs[0].name
'calculate_average'
>>> funcs[0].metrics.cyclomatic_complexity
2
"""

import re
from typing import (
    List, Set, Dict, Tuple, Optional, Any, Generator,
    Union, Pattern, Match, FrozenSet, DefaultDict
)
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from collections import defaultdict, Counter, OrderedDict
import math
import hashlib
import json
from functools import lru_cache, cached_property
from ...modules import LIST_OF_STDLIBS


# ============================================================================
# Enumerations
# ============================================================================


class CodeElementType(Enum):
    """
    Types of code elements for classification.

    This enumeration provides standardized categorization of Python
    code structures for consistent analysis and reporting.

    Attributes
    ----------
    FUNCTION : str
        Standalone function definition (``def func():``).
    CLASS : str
        Class definition (``class MyClass:``).
    METHOD : str
        Method defined within a class (``def method(self):``).
    MODULE : str
        Module-level code elements.
    VARIABLE : str
        Variable assignment at module or class level.
    IMPORT : str
        Import statement (``import`` or ``from ... import``).
    DECORATOR : str
        Decorator applied to a function or class (``@decorator``).
    LAMBDA : str
        Lambda expression (``lambda x: x + 1``).
    COMPREHENSION : str
        List, dict, set, or generator comprehension.
    CONSTANT : str
        Named constant (conventionally uppercase).
    """

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    MODULE = "module"
    VARIABLE = "variable"
    IMPORT = "import"
    DECORATOR = "decorator"
    LAMBDA = "lambda"
    COMPREHENSION = "comprehension"
    CONSTANT = "constant"


class ComplexityLevel(Enum):
    """
    Complexity classification levels for code metrics.

    These levels follow standard industry thresholds for code
    complexity assessment.

    Attributes
    ----------
    LOW : str
        Complexity score ≤ 5. Simple, easily testable code.
    MEDIUM : str
        Complexity score 6-10. Moderately complex, still manageable.
    HIGH : str
        Complexity score 11-20. Complex, consider refactoring.
    VERY_HIGH : str
        Complexity score > 20. Highly complex, difficult to test and maintain.
    EXTREME : str
        Complexity score > 50. Extremely complex, requires immediate attention.

    Notes
    -----
    Thresholds are based on McCabe's cyclomatic complexity recommendations:
    - 1-5: Simple, low risk
    - 6-10: Moderate complexity, medium risk
    - 11-20: High complexity, high risk
    - 21-50: Very high complexity, very high risk
    - >50: Extreme complexity, critical risk
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"
    EXTREME = "EXTREME"


class IssueSeverity(Enum):
    """
    Code issue severity levels following standard linting conventions.

    These levels help prioritize code issues during review and
    automated analysis.

    Attributes
    ----------
    INFO : str
        Informational message, no action required.
    LOW : str
        Minor issue, low priority for fixing.
    MEDIUM : str
        Moderate issue, should be addressed in normal development.
    HIGH : str
        Significant issue, should be prioritized.
    CRITICAL : str
        Critical issue requiring immediate attention.
    BLOCKER : str
        Blocker issue preventing code from being production-ready.

    See Also
    --------
    ComplexityLevel : For complexity-specific classifications.
    SecurityLevel : For security risk classifications.
    """

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    BLOCKER = "BLOCKER"


class SecurityLevel(Enum):
    """
    Security risk classification for code patterns.

    Based on OWASP threat modeling and common vulnerability
    classifications.

    Attributes
    ----------
    SAFE : str
        No identified security risks.
    SUSPICIOUS : str
        Potentially unsafe pattern, review recommended.
    RISKY : str
        Known risky pattern, should be refactored.
    DANGEROUS : str
        Dangerous pattern, requires immediate remediation.
    CRITICAL_VULNERABILITY : str
        Confirmed vulnerability with known exploit vectors.

    References
    ----------
    .. [4] OWASP Top Ten Web Application Security Risks.
    .. [5] CWE/SANS Top 25 Most Dangerous Software Errors.
    """

    SAFE = "SAFE"
    SUSPICIOUS = "SUSPICIOUS"
    RISKY = "RISKY"
    DANGEROUS = "DANGEROUS"
    CRITICAL_VULNERABILITY = "CRITICAL_VULNERABILITY"


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class CodeMetrics:
    """
    Comprehensive code metrics for functions and methods.

    This dataclass holds quantitative measurements of code quality,
    complexity, and maintainability for individual code units.

    Parameters
    ----------
    line_count : int
        Number of executable lines (excluding blanks and comments).
    cyclomatic_complexity : int
        McCabe cyclomatic complexity score.
    parameter_count : int
        Number of parameters the function accepts.
    nested_depth : int
        Maximum nesting depth of control structures.
    cognitive_complexity : int
        Cognitive complexity score (considers readability).
    maintainability_index : float
        Maintainability Index (0-100, higher is better).
    halstead_volume : float
        Halstead volume metric.
    code_churn : int, optional
        Number of code changes (requires VCS integration). Default is 0.
    comment_ratio : float, optional
        Ratio of comment lines to code lines. Default is 0.0.
    duplication_score : float, optional
        Code duplication percentage (0.0 to 100.0). Default is 0.0.

    Notes
    -----
    - Cyclomatic complexity: M = E - N + 2P, where E=edges, N=nodes, P=components.
    - Cognitive complexity: Considers nesting and structural complexity.
    - Halstead volume: Based on operator and operand counts.
    - Maintainability Index: 171 - 5.2*ln(V) - 0.23*CC - 16.2*ln(LOC).

    References
    ----------
    .. [1] McCabe, T.J. "A Complexity Measure", IEEE Trans. Software Eng., 1976.
    .. [2] Halstead, M.H. "Elements of Software Science", Elsevier, 1977.
    """

    line_count: int
    cyclomatic_complexity: int
    parameter_count: int
    nested_depth: int
    cognitive_complexity: int
    maintainability_index: float
    halstead_volume: float
    code_churn: int = 0
    comment_ratio: float = 0.0
    duplication_score: float = 0.0


@dataclass
class FunctionInfo:
    """
    Enhanced function information with comprehensive metadata.

    This dataclass captures all relevant information about a function
    definition, including its signature, body, metadata, and quality
    metrics.

    Parameters
    ----------
    name : str
        Function name.
    parameters : str
        Parameter string (e.g., ``"self, x: int, y: str = 'default'"``).
    body : str
        Full function body as a string.
    line_number : int
        Starting line number (1-indexed).
    decorators : List[str]
        List of decorator names applied to the function.
    return_type : Optional[str], optional
        Return type annotation as string. Default is None.
    docstring : Optional[str], optional
        Function docstring if present. Default is None.
    metrics : Optional[CodeMetrics], optional
        Computed code metrics. Default is None.
    complexity_level : ComplexityLevel, optional
        Classified complexity level. Default is ``ComplexityLevel.LOW``.
    security_level : SecurityLevel, optional
        Classified security risk level. Default is ``SecurityLevel.SAFE``.
    is_async : bool, optional
        Whether the function is async. Default is False.
    is_generator : bool, optional
        Whether the function is a generator. Default is False.
    is_nested : bool, optional
        Whether the function is nested inside another function. Default is False.
    is_property : bool, optional
        Whether the function is a property. Default is False.
    is_static : bool, optional
        Whether the function is a static method. Default is False.
    is_class_method : bool, optional
        Whether the function is a class method. Default is False.
    is_abstract : bool, optional
        Whether the function is abstract. Default is False.

    See Also
    --------
    ClassInfo : Class-level analysis information.
    CodeMetrics : Quantitative code measurements.

    Examples
    --------
    >>> info = FunctionInfo(
    ...     name="process",
    ...     parameters="data: list, threshold: float = 0.5",
    ...     body="...",
    ...     line_number=10,
    ...     decorators=["staticmethod"],
    ...     return_type="bool",
    ...     is_async=False,
    ... )
    >>> info.name
    'process'
    """

    name: str
    parameters: str
    body: str
    line_number: int
    decorators: List[str]
    return_type: Optional[str] = None
    docstring: Optional[str] = None
    metrics: Optional[CodeMetrics] = None
    complexity_level: ComplexityLevel = ComplexityLevel.LOW
    security_level: SecurityLevel = SecurityLevel.SAFE
    is_async: bool = False
    is_generator: bool = False
    is_nested: bool = False
    is_property: bool = False
    is_static: bool = False
    is_class_method: bool = False
    is_abstract: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert FunctionInfo to a serializable dictionary.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation with enum values converted to strings.

        Examples
        --------
        >>> info = FunctionInfo(...)
        >>> d = info.to_dict()
        >>> d['complexity_level']
        'LOW'
        """
        result = asdict(self)
        result['complexity_level'] = self.complexity_level.value
        result['security_level'] = self.security_level.value
        return result


@dataclass
class ClassInfo:
    """
    Enhanced class information with comprehensive analysis.

    This dataclass captures class structure, inheritance, methods,
    and attributes for detailed code analysis.

    Parameters
    ----------
    name : str
        Class name.
    bases : List[str]
        List of base class names.
    methods : List[FunctionInfo]
        List of methods defined in the class.
    line_number : int
        Starting line number (1-indexed).
    docstring : Optional[str], optional
        Class docstring if present. Default is None.
    class_variables : List[str], optional
        Class-level variable names. Default is empty list.
    instance_variables : List[str], optional
        Instance variable names (``self.var``). Default is empty list.
    decorators : List[str], optional
        Class decorators. Default is empty list.
    is_abstract : bool, optional
        Whether the class is abstract. Default is False.
    metaclass : Optional[str], optional
        Metaclass name if specified. Default is None.
    inheritance_depth : int, optional
        Depth of inheritance chain. Default is 1.
    method_count : int, optional
        Total number of methods. Default is 0.
    public_methods : List[str], optional
        Names of public methods. Default is empty list.
    private_methods : List[str], optional
        Names of private methods. Default is empty list.

    See Also
    --------
    FunctionInfo : Method-level analysis information.
    ImportInfo : Import dependency information.

    Examples
    --------
    >>> cls = ClassInfo(
    ...     name="MyClass",
    ...     bases=["BaseClass", "Mixin"],
    ...     methods=[],
    ...     line_number=25,
    ...     docstring="A sample class.",
    ...     inheritance_depth=2,
    ... )
    >>> cls.name
    'MyClass'
    >>> len(cls.bases)
    2
    """

    name: str
    bases: List[str]
    methods: List[FunctionInfo]
    line_number: int
    docstring: Optional[str] = None
    class_variables: List[str] = field(default_factory=list)
    instance_variables: List[str] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)
    is_abstract: bool = False
    metaclass: Optional[str] = None
    inheritance_depth: int = 1
    method_count: int = 0
    public_methods: List[str] = field(default_factory=list)
    private_methods: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert ClassInfo to a serializable dictionary.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation with nested conversions.

        Examples
        --------
        >>> cls = ClassInfo(...)
        >>> d = cls.to_dict()
        >>> 'methods' in d
        True
        """
        result = asdict(self)
        result['methods'] = [m.to_dict() for m in self.methods]
        return result


@dataclass
class ImportInfo:
    """
    Enhanced import information with dependency analysis.

    This dataclass provides detailed information about import
    statements, including module classification and aliases.

    Parameters
    ----------
    module : str
        Module name being imported.
    imports : List[str]
        Specific names imported from the module.
    aliases : Dict[str, str]
        Mapping of original names to their aliases.
    line_number : int
        Line number of the import statement (1-indexed).
    import_type : str
        Type of import: ``'from_import'`` or ``'direct_import'``.
    is_stdlib : bool, optional
        Whether the module is from the Python standard library. Default is False.
    is_third_party : bool, optional
        Whether the module is from a third-party package. Default is False.
    is_local : bool, optional
        Whether the module is a local project module. Default is False.
    version_constraint : Optional[str], optional
        Version constraint if specified. Default is None.
    is_conditional : bool, optional
        Whether the import is inside a try-except block. Default is False.

    See Also
    --------
    DependencyInfo : Dependency relationship analysis.

    Examples
    --------
    >>> imp = ImportInfo(
    ...     module="os.path",
    ...     imports=["join", "dirname"],
    ...     aliases={"join": "join", "dirname": "dirname"},
    ...     line_number=3,
    ...     import_type="from_import",
    ...     is_stdlib=True,
    ... )
    >>> imp.is_stdlib
    True
    """

    module: str
    imports: List[str]
    aliases: Dict[str, str]
    line_number: int
    import_type: str
    is_stdlib: bool = False
    is_third_party: bool = False
    is_local: bool = False
    version_constraint: Optional[str] = None
    is_conditional: bool = False


@dataclass
class VariableInfo:
    """
    Enhanced variable information with type analysis.

    This dataclass captures variable definitions, their types,
    usage patterns, and visibility characteristics.

    Parameters
    ----------
    name : str
        Variable name.
    value : str
        Assigned value as a string.
    line_number : int
        Line number of the assignment (1-indexed).
    is_constant : bool
        Whether the variable follows constant naming convention.
    type_hint : Optional[str], optional
        Type annotation as string. Default is None.
    is_public : bool, optional
        Whether the variable is public. Default is True.
    is_class_var : bool, optional
        Whether it's a class-level variable. Default is False.
    is_instance_var : bool, optional
        Whether it's an instance variable. Default is False.
    usage_count : int, optional
        Number of times the variable is referenced. Default is 0.
    is_global : bool, optional
        Whether the variable is declared global. Default is False.
    is_nonlocal : bool, optional
        Whether the variable is declared nonlocal. Default is False.
    """
    name: str
    value: str
    line_number: int
    is_constant: bool
    type_hint: Optional[str] = None
    is_public: bool = True
    is_class_var: bool = False
    is_instance_var: bool = False
    usage_count: int = 0
    is_global: bool = False
    is_nonlocal: bool = False


@dataclass
class CallInfo:
    """
    Enhanced call information with context analysis.

    Parameters
    ----------
    name : str
        Name of the called function or method.
    line_number : int
        Line number of the call (1-indexed).
    call_type : str
        Type of call: ``'function'``, ``'method'``, ``'builtin'``, etc.
    context : str, optional
        Surrounding code context. Default is "".
    arguments : str, optional
        Argument string. Default is "".
    is_dynamic : bool, optional
        Whether the call uses dynamic dispatch. Default is False.
    is_nested_call : bool, optional
        Whether the call is nested inside another call. Default is False.
    recursion_depth : int, optional
        Depth of recursive calls. Default is 0.
    is_conditional : bool, optional
        Whether the call is inside a conditional. Default is False.
    """
    name: str
    line_number: int
    call_type: str
    context: str = ""
    arguments: str = ""
    is_dynamic: bool = False
    is_nested_call: bool = False
    recursion_depth: int = 0
    is_conditional: bool = False


@dataclass
class CodeIssue:
    """
    Enhanced code issue information with fix suggestions.

    Parameters
    ----------
    issue_type : str
        Type identifier for the issue (e.g., ``'LONG_FUNCTION'``).
    description : str
        Human-readable description of the issue.
    line_number : int
        Line number where the issue occurs (1-indexed).
    severity : IssueSeverity
        Severity level of the issue.
    element_name : str, optional
        Name of the affected code element. Default is "".
    category : str, optional
        Issue category (e.g., ``'maintainability'``). Default is "".
    confidence : float, optional
        Detection confidence (0.0 to 1.0). Default is 1.0.
    suggestion : str, optional
        Human-readable fix suggestion. Default is "".
    quick_fix : str, optional
        Automated fix code if available. Default is "".
    rule_id : Optional[str], optional
        Linting rule identifier. Default is None.

    Examples
    --------
    >>> issue = CodeIssue(
    ...     issue_type="LONG_FUNCTION",
    ...     description="Function is too long (75 lines)",
    ...     line_number=42,
    ...     severity=IssueSeverity.MEDIUM,
    ...     element_name="process_data",
    ...     category="maintainability",
    ...     suggestion="Break into smaller functions",
    ... )
    >>> issue.issue_type
    'LONG_FUNCTION'
    """

    issue_type: str
    description: str
    line_number: int
    severity: IssueSeverity
    element_name: str = ""
    category: str = ""
    confidence: float = 1.0
    suggestion: str = ""
    quick_fix: str = ""
    rule_id: Optional[str] = None


@dataclass
class DependencyInfo:
    """
    Enhanced dependency information with relationship analysis.

    Parameters
    ----------
    source : str
        Source element name (the dependent).
    target : str
        Target element name (the dependency).
    dependency_type : str
        Type of dependency relationship.
    line_number : int
        Line number where the dependency is established.
    strength : float, optional
        Dependency strength (0.0 to 1.0). Default is 1.0.
    is_direct : bool, optional
        Whether this is a direct dependency. Default is True.
    is_circular : bool, optional
        Whether this creates a circular dependency. Default is False.
    is_optional : bool, optional
        Whether the dependency is optional. Default is False.
    """
    source: str
    target: str
    dependency_type: str
    line_number: int
    strength: float = 1.0
    is_direct: bool = True
    is_circular: bool = False
    is_optional: bool = False


@dataclass
class SecurityVulnerability:
    """
    Security vulnerability information with CWE/OWASP mapping.

    Parameters
    ----------
    vulnerability_type : str
        Type of vulnerability (e.g., ``'injection'``).
    description : str
        Detailed description of the vulnerability.
    line_number : int
        Line number where the vulnerability exists.
    severity : IssueSeverity
        Severity level of the vulnerability.
    cwe_id : Optional[str], optional
        Common Weakness Enumeration ID. Default is None.
    owasp_category : Optional[str], optional
        OWASP Top 10 category. Default is None.
    attack_vector : str, optional
        Description of the attack vector. Default is "".
    impact : str, optional
        Description of the potential impact. Default is "".
    mitigation : str, optional
        Recommended mitigation steps. Default is "".
    cvss_score : float, optional
        CVSS severity score (0.0 to 10.0). Default is 0.0.

    References
    ----------
    .. [6] CWE - Common Weakness Enumeration, https://cwe.mitre.org/
    .. [7] OWASP Top Ten, https://owasp.org/www-project-top-ten/

    Examples
    --------
    >>> vuln = SecurityVulnerability(
    ...     vulnerability_type="command_injection",
    ...     description="User input passed to os.system()",
    ...     line_number=55,
    ...     severity=IssueSeverity.CRITICAL,
    ...     cwe_id="CWE-78",
    ...     owasp_category="A03:2021-Injection",
    ...     mitigation="Use subprocess.run() with shell=False",
    ... )
    >>> vuln.cwe_id
    'CWE-78'
    """

    vulnerability_type: str
    description: str
    line_number: int
    severity: IssueSeverity
    cwe_id: Optional[str] = None
    owasp_category: Optional[str] = None
    attack_vector: str = ""
    impact: str = ""
    mitigation: str = ""
    cvss_score: float = 0.0


@dataclass
class CodeSummary:
    """
    Comprehensive code analysis summary.

    Parameters
    ----------
    total_lines : int
        Total number of lines in the source.
    total_functions : int
        Total number of functions.
    total_classes : int
        Total number of classes.
    total_imports : int
        Total number of import statements.
    total_variables : int
        Total number of variables.
    average_complexity : float
        Average cyclomatic complexity across functions.
    maintainability_index : float
        Overall maintainability index.
    security_level : SecurityLevel
        Overall security risk level.
    issue_count : int
        Total number of detected issues.
    critical_issues : int
        Number of critical issues.
    """
    total_lines: int
    total_functions: int
    total_classes: int
    total_imports: int
    total_variables: int
    average_complexity: float
    maintainability_index: float
    security_level: SecurityLevel
    issue_count: int
    critical_issues: int


# ============================================================================
# Main Parser Class
# ============================================================================


class StringParser:
    """
     Python source code analyzer with enhanced regex patterns
    and comprehensive code analysis capabilities.

    This parser performs static analysis of Python source code using
    optimized regular expressions, providing structural extraction,
    complexity metrics, security vulnerability detection, dependency
    graph analysis, and code quality scoring.

    Features
    --------
    - **Multi-stage parsing with cache validation**
    - **Comprehensive complexity metrics** (cyclomatic, cognitive, Halstead)
    - **Security vulnerability detection** with CWE/OWASP mapping
    - **Performance optimization** with smart caching and lazy evaluation
    - **Dependency graph analysis** with circular dependency detection
    - **Code quality scoring** with maintainability index
    - **Accurate line tracking** with character offset mapping
    - **Privacy-aware logging** for debugging

    Parameters
    ----------
    source_code : str
        Complete Python source code as a string.

    Raises
    ------
    ValueError
        If ``source_code`` is empty or not a string.
    TypeError
        If ``source_code`` is not a string.

    Attributes
    ----------
    original_code : str
        The original, unmodified source code.
    code : str
        Source code with string literals removed (for accurate parsing).
    lines : List[str]
        Source code split into individual lines.
    source_hash : str
        SHA-256 hash of the original source code.
    source_size : int
        Size of the source code in characters.

    Warnings
    --------
    - This parser uses regex-based analysis, which may not handle
      all Python syntax perfectly (e.g., f-strings with complex
      expressions, type hints with generics).
    - For production-grade analysis, consider combining with
      ``ast``-based parsing.

    Notes
    -----
    The parser uses pre-compiled regular expressions for performance.
    These patterns are optimized for common Python code patterns but
    may have edge cases with extremely complex or unusual syntax.

    Performance Considerations
    --------------------------
    - First access to each analysis property triggers computation
      and caching.
    - Subsequent accesses return cached results.
    - Use ``clear_cache()`` to release memory after analysis.

    See Also
    --------
    ast.parse : Standard library AST parsing.
    tokenize : Lexical scanner for Python source.
    bandit : Security-focused static analysis.

    References
    ----------
    .. [1] McCabe, T.J. "A Complexity Measure", IEEE Trans., 1976.
    .. [2] Halstead, M.H. "Elements of Software Science", 1977.
    .. [3] "Maintainability Index", SEI, 2001.

    Examples
    --------
    Basic usage:

    >>> source = '''
    ... def add(a: int, b: int) -> int:
    ...     \"\"\"Add two numbers.\"\"\"
    ...     return a + b
    ...
    ... def calculate_sum(numbers: list) -> int:
    ...     \"\"\"Calculate sum of list.\"\"\"
    ...     total = 0
    ...     for num in numbers:
    ...         total += num
    ...     return total
    ...
    ... class Calculator:
    ...     \"\"\"A simple calculator class.\"\"\"
    ...     def __init__(self, initial: int = 0):
    ...         self.value = initial
    ...
    ...     def add(self, x: int) -> int:
    ...         self.value += x
    ...         return self.value
    ... '''
    >>> parser = StringParser(source)
    >>> funcs = parser.functions()
    >>> len(funcs)
    2
    >>> funcs[0].name
    'add'
    >>> funcs[0].return_type
    'int'
    >>> funcs[0].metrics.cyclomatic_complexity
    1

    Class analysis:

    >>> classes = parser.classes()
    >>> len(classes)
    1
    >>> classes[0].name
    'Calculator'
    >>> len(classes[0].methods)
    2

    Complexity analysis:

    >>> funcs[1].metrics.cyclomatic_complexity
    2
    >>> funcs[1].complexity_level.name
    'LOW'

    Security analysis:

    >>> risky_source = '''
    ... def execute_command(cmd: str) -> str:
    ...     import os
    ...     return os.system(cmd)
    ... '''
    >>> risky_parser = StringParser(risky_source)
    >>> risky_funcs = risky_parser.functions()
    >>> risky_funcs[0].security_level.name
    'DANGEROUS'

    Code issues detection:

    >>> issues = parser.code_issues()
    >>> any(i.issue_type == "LONG_FUNCTION" for i in issues)
    False
    """

    # ------------------------------------------------------------------------
    # Pre-compiled Regex Patterns (Class-level constants)
    # ------------------------------------------------------------------------

    _FUNC_PATTERN: Pattern[str] = re.compile(
        r"^([ \t]*)(?:async[ \t]+)?def[ \t]+([a-zA-Z_]\w*)[ \t]*"
        r"\(([^)#]*?(?:\([^)]*\)[^)#]*?)*)\)[ \t]*"
        r'(?:->[ \t]*([\w\[\], \.\'"]*))?[ \t]*:[ \t]*\n'
        r"((?:(?:\1[ \t]+.*\n|\s*\n))*)",
        re.MULTILINE,
    )

    _CLASS_PATTERN: Pattern[str] = re.compile(
        r"^([ \t]*)class[ \t]+([a-zA-Z_]\w*)[ \t]*"
        r"(?:\(([^)#]*?(?:\([^)]*\)[^)#]*?)*)\))?[ \t]*:[ \t]*\n"
        r"((?:(?:\1[ \t]+.*\n|\s*\n))*)",
        re.MULTILINE,
    )

    _IMPORT_PATTERN: Pattern[str] = re.compile(
        r"^[ \t]*(?:from[ \t]+([\w\.]+)[ \t]+import[ \t]+"
        r"((?:\w+|\*)(?:[ \t]*,[ \t]*(?:\w+|\*))*)(?:[ \t]+as[ \t]+(\w+))?"
        r"|import[ \t]+((?:\w+)(?:[ \t]*,[ \t]*(?:\w+))*)(?:[ \t]+as[ \t]+(\w+))?)"
        r"[ \t]*(?:#.*)?$",
        re.MULTILINE,
    )

    _VARIABLE_PATTERN: Pattern[str] = re.compile(
        r"^(?![ \t]*(?:def|class|import|from|if|elif|else|for|while|with|try|except|finally|async))"
        r'[ \t]*([A-Za-z_][\w\.]*)[ \t]*(?::[ \t]*([\w\[\], \.\'"]+))?[ \t]*=[ \t]*'
        r"([^=\n]+(?:\n[ \t]+[^=\n]+)*)",
        re.MULTILINE,
    )

    _FUNC_CALL_PATTERN: Pattern[str] = re.compile(
        r"\b([a-zA-Z_][\w\.]*)[ \t]*\(([^);]*(?:\([^)]*\)[^);]*)*)\)",
        re.MULTILINE,
    )

    _METHOD_CALL_PATTERN: Pattern[str] = re.compile(
        r"\.([a-zA-Z_]\w*)[ \t]*\(([^)]*(?:\([^)]*\)[^)]*)*)\)",
        re.MULTILINE,
    )

    _DECORATOR_PATTERN: Pattern[str] = re.compile(
        r"^[ \t]*@([a-zA-Z_][\w\.]*(?:\([^)]*\))?)", re.MULTILINE
    )

    _DOCSTRING_PATTERN: Pattern[str] = re.compile(
        r'(\'\'\'(.*?)\'\'\'|"""(.*?)""")', re.MULTILINE | re.DOTALL
    )

    _STRING_LITERAL_PATTERN: Pattern[str] = re.compile(
        r'(\'\'\'(?:[^\']|\'{1,2}(?!\'))*\'\'\'|"""(?:[^"]|"{1,2}(?!"))*"""'
        r"|\'[^\']*\'|\"[^\"]*\")",
        re.MULTILINE | re.DOTALL,
    )

    _COMMENT_PATTERN: Pattern[str] = re.compile(r"^\s*#")

    # ------------------------------------------------------------------------
    # Class-level Constants
    # ------------------------------------------------------------------------

    _COMPLEXITY_KEYWORDS: FrozenSet[str] = frozenset({
        "if", "elif", "else", "for", "while",
        "try", "except", "finally", "with",
        "and", "or", "not", "assert",
        "return", "yield", "await",
        "match", "case", "raise", "break", "continue",
    })

    _SECURITY_RISKY_FUNCTIONS: FrozenSet[str] = frozenset({
        "eval", "exec", "compile",
        "input",
        "os.system", "os.popen",
        "subprocess.call", "subprocess.Popen",
        "pickle.loads", "pickle.load",
        "marshal.loads",
        "yaml.load",
        "json.loads",  # Risky with untrusted input
        "ctypes.CDLL",
        "__import__",
    })

    _PYTHON_STDLIB_MODULES: FrozenSet[str] = frozenset(LIST_OF_STDLIBS)

    _SECURITY_VULNERABILITY_PATTERNS: Dict[str, Pattern[str]] = {
        "command_injection": re.compile(
            r"(?:os\.(?:system|popen|exec[lvpe]*)|subprocess\.(?:call|Popen|run|check_output))\s*\("
        ),
        "code_injection": re.compile(
            r"(?:eval|exec|compile|__import__)\s*\("
        ),
        "pickle_injection": re.compile(
            r"(?:pickle\.(?:load|loads)|marshal\.load[s]?|yaml\.load)\s*\("
        ),
        "path_traversal": re.compile(
            r"(?:open|os\.path\.join)\s*\(\s*.*request\.|user_input"
        ),
        "sql_injection": re.compile(
            r"(?:execute|executemany)\s*\(\s*.*%.*%"
        ),
        "hardcoded_password": re.compile(
            r'(?:password|passwd|secret|api_key|token)\s*=\s*["\'][^"\']+["\']'
        ),
        "unsafe_deserialization": re.compile(
            r"(?:json\.loads|pickle\.loads|yaml\.load)\s*\(\s*request\.|user_input"
        ),
    }

    _INJECTION_PATTERNS: List[Pattern[str]] = [
        re.compile(r"os\.system\s*\("),
        re.compile(r"subprocess\.call\s*\("),
        re.compile(r"eval\s*\("),
        re.compile(r"exec\s*\("),
        re.compile(r"__import__\s*\("),
    ]

    # ------------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------------

    def __init__(self, source_code: str) -> None:
        """
        Initialize the analyzer with Python source code.

        Parameters
        ----------
        source_code : str
            Complete Python source code as a single string.

        Raises
        ------
        TypeError
            If ``source_code`` is not a string.
        ValueError
            If ``source_code`` is empty or contains only whitespace.

        Notes
        -----
        - String literals are removed from the working copy to prevent
          false positives during regex matching.
        - Character offset mapping is computed for accurate line numbers.
        - Internal cache is initialized for lazy evaluation.

        Examples
        --------
        >>> parser = StringParser("x = 42\\ny = x + 1")
        >>> parser.original_code
        'x = 42\\ny = x + 1'
        >>> parser.source_size
        13
        """
        if not isinstance(source_code, str):
            raise TypeError(
                f"source_code must be a string, got {type(source_code).__name__}"
            )
        if not source_code.strip():
            raise ValueError(
                "source_code cannot be empty or contain only whitespace"
            )

        self._original_code: str = source_code
        self._code: str = self._remove_string_literals(source_code)
        self._lines: List[str] = source_code.splitlines()
        self._cache: Dict[str, Any] = {}
        self._line_offsets: List[int] = self._calculate_line_offsets()
        self._source_hash: Optional[str] = None
        self._issues: Optional[List[CodeIssue]] = None
        self._security_vulnerabilities: Optional[List[SecurityVulnerability]] = None

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def original_code(self) -> str:
        """
        Return the original, unmodified source code.

        Returns
        -------
        str
            The original source code as provided during initialization.

        Examples
        --------
        >>> parser = StringParser("x = 42")
        >>> parser.original_code
        'x = 42'
        """
        return self._original_code

    @property
    def code(self) -> str:
        """
        Return source code with string literals removed.

        This is the working copy used for regex matching to avoid
        false positives within string literals.

        Returns
        -------
        str
            Source code with string literals replaced by empty strings.

        See Also
        --------
        original_code : The unmodified source code.
        """
        return self._code

    @property
    def lines(self) -> List[str]:
        """
        Return source code split into individual lines.

        Returns
        -------
        List[str]
            List of source code lines without trailing newline characters.

        Examples
        --------
        >>> parser = StringParser("line1\\nline2\\nline3")
        >>> len(parser.lines)
        3
        >>> parser.lines[0]
        'line1'
        """
        return self._lines

    @property
    def source_hash(self) -> str:
        """
        Compute and return the SHA-256 hash of the original source code.

        Returns
        -------
        str
            Hexadecimal string of the SHA-256 hash (64 characters).

        Examples
        --------
        >>> parser = StringParser("print('hello')")
        >>> len(parser.source_hash)
        64
        """
        if self._source_hash is None:
            self._source_hash = hashlib.sha256(
                self._original_code.encode('utf-8')
            ).hexdigest()
        return self._source_hash

    @property
    def source_size(self) -> int:
        """
        Return the size of the source code in characters.

        Returns
        -------
        int
            Total number of characters in the source code.

        Examples
        --------
        >>> parser = StringParser("x = 42")
        >>> parser.source_size
        6
        """
        return len(self._original_code)

    @property
    def line_count(self) -> int:
        """
        Return the number of lines in the source code.

        Returns
        -------
        int
            Total number of lines.

        Examples
        --------
        >>> parser = StringParser("line1\\nline2\\nline3")
        >>> parser.line_count
        3
        """
        return len(self._lines)

    # ------------------------------------------------------------------------
    # Internal Helper Methods
    # ------------------------------------------------------------------------

    def _calculate_line_offsets(self) -> List[int]:
        """
        Calculate character offsets for the start of each line.

        This builds a lookup table for efficient line number
        resolution from character positions.

        Returns
        -------
        List[int]
            List of character offsets, one per line. The first
            element is always 0.

        Notes
        -----
        Offsets account for the newline character (``\\n``) that
        separates lines.

        Examples
        --------
        >>> parser = StringParser("abc\\ndef\\nghi")
        >>> parser._line_offsets
        [0, 4, 8]
        """
        offsets = [0]
        offset = 0
        for line in self._original_code.split("\n"):
            offset += len(line) + 1  # +1 for newline
            offsets.append(offset)
        return offsets

    def _remove_string_literals(self, code: str) -> str:
        """
        Remove string literals to avoid false positives in regex parsing.

        This preprocessing step replaces all string literals with
        empty strings to prevent keywords and patterns within strings
        from affecting analysis.

        Parameters
        ----------
        code : str
            Source code potentially containing string literals.

        Returns
        -------
        str
            Source code with all string literals replaced by ``""``.

        Notes
        -----
        Handles:
        - Single-quoted strings: ``'text'``
        - Double-quoted strings: ``"text"``
        - Triple-quoted strings (both ``'''`` and ``\"\"\"``)

        Examples
        --------
        >>> parser = StringParser("x = 'def func():'")
        >>> 'def func' in parser.code
        False
        """
        return self._STRING_LITERAL_PATTERN.sub('""', code)

    def _get_line_number(self, char_index: int) -> int:
        """
        Calculate the 1-indexed line number from a character position.

        Uses the pre-computed line offset table for efficient lookup.

        Parameters
        ----------
        char_index : int
            Character position in the source code (0-indexed).

        Returns
        -------
        int
            Line number (1-indexed). Returns the last line number
            if ``char_index`` is beyond the source length.

        Examples
        --------
        >>> parser = StringParser("abc\\ndef\\nghi")
        >>> parser._get_line_number(0)
        1
        >>> parser._get_line_number(5)
        2
        """
        for i, offset in enumerate(self._line_offsets):
            if char_index < offset:
                return i
        return len(self._line_offsets)

    def _extract_docstring(self, text: str) -> Optional[str]:
        """
        Extract docstring from function or class body text.

        Searches for the first triple-quoted string in the body,
        which conventionally serves as the docstring.

        Parameters
        ----------
        text : str
            Code body text (function or class body).

        Returns
        -------
        str or None
            The extracted docstring content without quotes, or None
            if no docstring is found.

        Notes
        -----
        - Only triple-quoted strings (``'''`` or ``\"\"\"``) are
          recognized as docstrings.
        - The content is stripped of leading/trailing whitespace.

        Examples
        --------
        >>> parser = StringParser("")
        >>> result = parser._extract_docstring('''\"\"\"Hello World\"\"\"\\nx = 1''')
        >>> result
        'Hello World'
        """
        match = self._DOCSTRING_PATTERN.search(text)
        if match:
            return match.group(2) or match.group(3)
        return None

    def _calculate_comprehensive_metrics(
        self, body: str, param_count: int
    ) -> CodeMetrics:
        """
        Calculate comprehensive code metrics for a function or method body.

        Computes multiple standard software metrics in a single pass
        through the body text.

        Parameters
        ----------
        body : str
            Function or method body text including indentation.
        param_count : int
            Number of parameters the function accepts.

        Returns
        -------
        CodeMetrics
            Dataclass containing all computed metrics:
            - ``line_count``: Executable lines (excluding blanks and comments).
            - ``cyclomatic_complexity``: McCabe complexity score.
            - ``parameter_count``: Number of parameters.
            - ``nested_depth``: Maximum nesting level.
            - ``cognitive_complexity``: Cognitive complexity score.
            - ``maintainability_index``: SEI maintainability index (0-100).
            - ``halstead_volume``: Halstead volume metric.

        Notes
        -----
        **Cyclomatic Complexity** (M = E - N + 2P, simplified):
        Counts decision points: ``if``, ``elif``, ``for``, ``while``,
        ``and``, ``or``, ``except``.

        **Cognitive Complexity**:
        Considers nesting depth and structural complexity.

        **Halstead Volume**:
        V = N * log2(n), where n = distinct operators/operands,
        N = total operators/operands.

        **Maintainability Index**:
        MI = 171 - 5.2*ln(V) - 0.23*CC - 16.2*ln(LOC)

        References
        ----------
        .. [1] McCabe, T.J. "A Complexity Measure", 1976.
        .. [2] Halstead, M.H. "Elements of Software Science", 1977.

        Examples
        --------
        >>> parser = StringParser("")
        >>> metrics = parser._calculate_comprehensive_metrics(
        ...     "if x > 0:\\n    return x\\nreturn 0", 1
        ... )
        >>> metrics.cyclomatic_complexity
        2
        >>> metrics.line_count
        3
        """
        lines = body.split("\n")
        line_count = len([
            line for line in lines
            if line.strip() and not line.strip().startswith("#")
        ])

        # Cyclomatic complexity
        complexity = 1  # Base complexity
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            for keyword in self._COMPLEXITY_KEYWORDS:
                if keyword in stripped.split():
                    complexity += 1
                    break

        # Nested depth
        nested_depth = 0
        current_depth = 0
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                indent = len(line) - len(line.lstrip())
                current_depth = indent // 4  # Assume 4-space indentation
                nested_depth = max(nested_depth, current_depth)

        # Cognitive complexity (simplified SonarQube approach)
        cognitive_complexity = complexity
        cognitive_complexity += nested_depth * 2  # Nesting penalty
        if "recursion" in body.lower():
            cognitive_complexity += 5  # Recursion penalty

        # Halstead volume
        operators = set(re.findall(r"[+\-*/%=<>!&|^~@]", body))
        operands = set(re.findall(r"\b[a-zA-Z_]\w*\b", body))
        n1 = len(operators)
        n2 = len(operands)
        N = n1 + n2
        V = N * math.log2(n1 + n2) if (n1 + n2) > 0 else 0

        # Maintainability index
        maintainability_index = max(
            0.0,
            171.0
            - 5.2 * math.log(V + 1)
            - 0.23 * complexity
            - 16.2 * math.log(line_count + 1),
        )

        # Comment ratio
        comment_lines = sum(1 for line in lines if line.strip().startswith("#"))
        comment_ratio = comment_lines / max(line_count, 1)

        return CodeMetrics(
            line_count=line_count,
            cyclomatic_complexity=complexity,
            parameter_count=param_count,
            nested_depth=nested_depth,
            cognitive_complexity=cognitive_complexity,
            maintainability_index=round(maintainability_index, 2),
            halstead_volume=round(V, 2),
            comment_ratio=round(comment_ratio, 3),
        )

    def _find_decorators(self, function_line: int) -> List[str]:
        """
        Find decorators applied to a function or class definition.

        Scans lines immediately preceding the definition line for
        decorator patterns (lines starting with ``@``).

        Parameters
        ----------
        function_line : int
            Line number of the function or class definition (1-indexed).

        Returns
        -------
        List[str]
            List of decorator names in order of application (top to bottom).
            Empty list if no decorators are found.

        Notes
        -----
        - Handles both simple decorators (``@staticmethod``) and
          parameterized decorators (``@decorator(args)``).
        - Stops scanning when a non-decorator, non-blank line is encountered.

        Examples
        --------
        >>> source = '''
        ... @staticmethod
        ... @validate(value=True)
        ... def process():
        ...     pass
        ... '''
        >>> parser = StringParser(source)
        >>> parser._find_decorators(4)  # Line of 'def process():'
        ['staticmethod', 'validate(value=True)']
        """
        decorators: List[str] = []
        current_line = function_line - 1

        while current_line > 0:
            line_content = self._lines[current_line - 1].strip()
            if not line_content:
                current_line -= 1
                continue
            if not line_content.startswith("@"):
                break

            decorator_match = self._DECORATOR_PATTERN.match(line_content)
            if decorator_match:
                decorators.append(decorator_match.group(1))
            current_line -= 1

        return list(reversed(decorators))

    # ------------------------------------------------------------------------
    # Public Analysis Methods
    # ------------------------------------------------------------------------

    def functions(self) -> List[FunctionInfo]:
        """
        Extract all functions with enhanced analysis and metrics.

        Parses function definitions including async functions,
        extracts parameters, return types, decorators, docstrings,
        and computes comprehensive code quality metrics.

        Returns
        -------
        List[FunctionInfo]
            List of ``FunctionInfo`` dataclass instances, each containing
            complete function analysis including:
            - Name, parameters, body
            - Return type annotation
            - Docstring
            - Decorators
            - Code metrics (complexity, maintainability, etc.)
            - Complexity and security classifications
            - Async, generator, and nesting flags
            - Property, static method, class method detection

        Notes
        -----
        Results are cached after first access for performance.
        Use ``clear_cache()`` to force re-analysis.

        The function handles:
        - Regular functions
        - Async functions (``async def``)
        - Nested functions
        - Methods (``self`` parameter detection)
        - Decorated functions

        See Also
        --------
        classes : Extract class definitions with methods.
        code_issues : Detect issues in extracted functions.

        Examples
        --------
        >>> source = '''
        ... @staticmethod
        ... def add(a: int, b: int) -> int:
        ...     '''Add two numbers.'''
        ...     return a + b
        ... '''
        >>> parser = StringParser(source)
        >>> funcs = parser.functions()
        >>> len(funcs)
        1
        >>> funcs[0].name
        'add'
        >>> funcs[0].return_type
        'int'
        >>> funcs[0].decorators
        ['staticmethod']
        >>> funcs[0].docstring
        'Add two numbers.'
        """
        cache_key = "functions"
        if cache_key in self._cache:
            return self._cache[cache_key]

        functions_list: List[FunctionInfo] = []

        for match in self._FUNC_PATTERN.finditer(self._original_code):
            indent, name, params, return_type, body = match.groups()
            start_line = self._get_line_number(match.start())

            # Extract metadata
            decorators = self._find_decorators(start_line)
            docstring = self._extract_docstring(body)
            param_count = len([
                p for p in params.split(",")
                if p.strip() and p.strip() not in ("self", "cls")
            ])
            metrics = self._calculate_comprehensive_metrics(body, param_count)

            # Determine complexity level
            complexity_level = self._classify_complexity(
                metrics.cyclomatic_complexity
            )

            # Security analysis
            security_level = self._analyze_function_security(
                name, body, params
            )

            # Detect function characteristics
            is_async = "async" in self._lines[start_line - 1]
            is_generator = "yield" in body
            is_nested = len(indent) > 0
            is_property = "property" in [d.lower() for d in decorators]
            is_static = "staticmethod" in decorators
            is_class_method = "classmethod" in decorators
            is_abstract = "abstractmethod" in decorators or (
                is_class_method and "@abstractmethod" in str(decorators)
            )

            functions_list.append(
                FunctionInfo(
                    name=name,
                    parameters=params.strip(),
                    body=body,
                    line_number=start_line,
                    decorators=decorators,
                    return_type=return_type.strip() if return_type else None,
                    docstring=docstring,
                    metrics=metrics,
                    complexity_level=complexity_level,
                    security_level=security_level,
                    is_async=is_async,
                    is_generator=is_generator,
                    is_nested=is_nested,
                    is_property=is_property,
                    is_static=is_static,
                    is_class_method=is_class_method,
                    is_abstract=is_abstract,
                )
            )

        self._cache[cache_key] = functions_list
        return functions_list

    def _classify_complexity(self, score: int) -> ComplexityLevel:
        """
        Classify cyclomatic complexity score into a complexity level.

        Parameters
        ----------
        score : int
            Cyclomatic complexity score.

        Returns
        -------
        ComplexityLevel
            The corresponding complexity classification.

        Notes
        -----
        Thresholds based on industry standards:
        - 1-5: LOW (simple, low risk)
        - 6-10: MEDIUM (moderate, manageable)
        - 11-20: HIGH (complex, consider refactoring)
        - 21-50: VERY_HIGH (highly complex, difficult to test)
        - 51+: EXTREME (critical, requires immediate action)

        Examples
        --------
        >>> parser = StringParser("x = 1")
        >>> parser._classify_complexity(3).name
        'LOW'
        >>> parser._classify_complexity(25).name
        'VERY_HIGH'
        """
        if score <= 5:
            return ComplexityLevel.LOW
        elif score <= 10:
            return ComplexityLevel.MEDIUM
        elif score <= 20:
            return ComplexityLevel.HIGH
        elif score <= 50:
            return ComplexityLevel.VERY_HIGH
        else:
            return ComplexityLevel.EXTREME

    def _analyze_function_security(
        self, name: str, body: str, params: str
    ) -> SecurityLevel:
        """
        Analyze function body for security risks and vulnerabilities.

        Checks for injection points, dangerous function calls, unsafe
        string formatting, and hardcoded credentials.

        Parameters
        ----------
        name : str
            Function name (for context).
        body : str
            Function body to analyze.
        params : str
            Function parameters string.

        Returns
        -------
        SecurityLevel
            Classified security risk level:
            - ``SAFE``: No risks detected.
            - ``SUSPICIOUS``: Potential issues found.
            - ``RISKY``: Known risky patterns.
            - ``DANGEROUS``: Critical vulnerabilities detected.
            - ``CRITICAL_VULNERABILITY``: Confirmed vulnerability.

        Notes
        -----
        Detection includes:
        - Dangerous function calls (``eval``, ``exec``, ``os.system``)
        - Code injection patterns
        - Unsafe deserialization
        - Hardcoded credentials
        - Path traversal vulnerabilities

        See Also
        --------
        security_vulnerabilities : Detailed vulnerability reports.

        Examples
        --------
        >>> parser = StringParser("")
        >>> level = parser._analyze_function_security(
        ...     "exec_cmd", "os.system(user_input)", "user_input"
        ... )
        >>> level.name
        'DANGEROUS'
        """
        # Check for high-risk function calls
        for risky_func in self._SECURITY_RISKY_FUNCTIONS:
            if risky_func in body:
                return SecurityLevel.DANGEROUS

        # Check injection patterns
        for pattern in self._INJECTION_PATTERNS:
            if pattern.search(body):
                return SecurityLevel.RISKY

        # Check unsafe string formatting with user inputs
        unsafe_formatting = False
        if "%." in body or ".format(" in body:
            risky_params = {"user_input", "request", "query", "params", "data"}
            if any(p.strip() in risky_params for p in params.split(",")):
                unsafe_formatting = True

        if unsafe_formatting:
            return SecurityLevel.SUSPICIOUS

        # Check hardcoded secrets
        secret_pattern = re.compile(
            r'(?:password|passwd|secret|api_key|token|key)\s*=\s*["\'][^"\']+["\']',
            re.IGNORECASE,
        )
        if secret_pattern.search(body):
            return SecurityLevel.RISKY

        return SecurityLevel.SAFE

    def classes(self) -> List[ClassInfo]:
        """
        Extract all classes with enhanced analysis and inheritance tracking.

        Parses class definitions including their bases, methods,
        variables, decorators, and computes inheritance depth.

        Returns
        -------
        List[ClassInfo]
            List of ``ClassInfo`` dataclass instances containing:
            - Class name and base classes
            - Methods list (as ``FunctionInfo``)
            - Class and instance variables
            - Decorators
            - Docstring
            - Inheritance depth
            - Abstract and metaclass detection

        Notes
        -----
        Results are cached after first access.

        Methods are extracted from the class body using regex patterns
        adapted for the class indentation level.

        See Also
        --------
        functions : Extract standalone functions.
        imports : Extract import statements.

        Examples
        --------
        >>> source = '''
        ... class Calculator(BaseCalc):
        ...     \"\"\"A calculator class.\"\"\"
        ...     default_precision: int = 2
        ...
        ...     def __init__(self, initial: int = 0):
        ...         self.value = initial
        ...
        ...     def add(self, x: int) -> int:
        ...         self.value += x
        ...         return self.value
        ... '''
        >>> parser = StringParser(source)
        >>> classes = parser.classes()
        >>> len(classes)
        1
        >>> classes[0].name
        'Calculator'
        >>> classes[0].bases
        ['BaseCalc']
        >>> len(classes[0].methods)
        2
        >>> classes[0].docstring
        'A calculator class.'
        """
        cache_key = "classes"
        if cache_key in self._cache:
            return self._cache[cache_key]

        classes_list: List[ClassInfo] = []

        for match in self._CLASS_PATTERN.finditer(self._original_code):
            indent, name, bases, body = match.groups()
            start_line = self._get_line_number(match.start())

            # Parse base classes and metaclass
            base_list: List[str] = []
            metaclass: Optional[str] = None
            if bases:
                for base in bases.split(","):
                    base = base.strip()
                    if "=" in base and "metaclass" in base:
                        metaclass = base.split("=")[1].strip()
                        continue
                    if base:
                        base_list.append(base)

            # Extract methods
            methods = self._extract_class_methods(body, indent)
            decorators = self._find_decorators(start_line)
            docstring = self._extract_docstring(body)
            class_vars, instance_vars = self._extract_class_variables(body)

            # Inheritance depth
            inheritance_depth = self._calculate_inheritance_depth(
                base_list, classes_list
            )

            # Abstract detection
            is_abstract = any(
                "abstract" in d.lower() or "ABCMeta" in (metaclass or "")
                for d in decorators
            )
            if methods:
                is_abstract = is_abstract or any(
                    m.is_abstract for m in methods
                )

            # Method categorization
            public_methods = [
                m.name for m in methods
                if not m.name.startswith("_")
            ]
            private_methods = [
                m.name for m in methods
                if m.name.startswith("_") and not m.name.startswith("__")
            ]

            classes_list.append(
                ClassInfo(
                    name=name,
                    bases=base_list,
                    methods=methods,
                    line_number=start_line,
                    docstring=docstring,
                    class_variables=class_vars,
                    instance_variables=instance_vars,
                    decorators=decorators,
                    is_abstract=is_abstract,
                    metaclass=metaclass,
                    inheritance_depth=inheritance_depth,
                    method_count=len(methods),
                    public_methods=public_methods,
                    private_methods=private_methods,
                )
            )

        self._cache[cache_key] = classes_list
        return classes_list

    def _calculate_inheritance_depth(
        self, bases: List[str], all_classes: List[ClassInfo]
    ) -> int:
        """
        Calculate inheritance depth for a class.

        Recursively determines the maximum depth of the inheritance
        chain by searching through already-parsed classes.

        Parameters
        ----------
        bases : List[str]
            List of base class names.
        all_classes : List[ClassInfo]
            All classes already parsed from the source.

        Returns
        -------
        int
            Inheritance depth (minimum 1 for classes without bases).

        Notes
        -----
        - External base classes (not in the parsed source) contribute
          depth 2 (assumed to inherit from ``object``).
        - Circular inheritance is not detected here; use
          :meth:`deps` for circular dependency analysis.

        Examples
        --------
        >>> parser = StringParser("")
        >>> existing = []
        >>> parser._calculate_inheritance_depth([], existing)
        1
        >>> parser._calculate_inheritance_depth(["object"], existing)
        2
        """
        if not bases:
            return 1

        max_depth = 1
        for base in bases:
            base_class = next(
                (cls for cls in all_classes if cls.name == base), None
            )
            if base_class:
                max_depth = max(max_depth, base_class.inheritance_depth + 1)
            else:
                max_depth = max(max_depth, 2)  # External base class

        return max_depth

    def _extract_class_methods(
        self, class_body: str, class_indent: str
    ) -> List[FunctionInfo]:
        """
        Extract methods from a class body with enhanced analysis.

        Parameters
        ----------
        class_body : str
            Class body text.
        class_indent : str
            The indentation string of the class definition.

        Returns
        -------
        List[FunctionInfo]
            List of method ``FunctionInfo`` instances.
        """
        methods: List[FunctionInfo] = []
        indent_level = len(class_indent) + 4  # Methods are indented more

        method_pattern = re.compile(
            r"^[ \t]{" + str(indent_level) + r",}(?:async[ \t]+)?"
            r"def[ \t]+([a-zA-Z_]\w*)[ \t]*"
            r"\(([^)#]*?(?:\([^)]*\)[^)#]*?)*)\)[ \t]*"
            r'(?:->[ \t]*([\w\[\], \.\'"]*))?[ \t]*:[ \t]*\n'
            r"((?:(?:[ \t]{" + str(indent_level + 4) + r",}.*\n|\s*\n))*)",
            re.MULTILINE,
        )

        for match in method_pattern.finditer(class_body):
            name, params, return_type, body = match.groups()
            param_count = len([
                p for p in params.split(",")
                if p.strip() and p.strip() not in ("self", "cls")
            ])
            metrics = self._calculate_comprehensive_metrics(body, param_count)
            docstring = self._extract_docstring(body)
            security_level = self._analyze_function_security(name, body, params)
            is_async = "async" in match.group(0)

            methods.append(
                FunctionInfo(
                    name=name,
                    parameters=params.strip(),
                    body=body,
                    line_number=0,  # Relative, can be adjusted if needed
                    decorators=[],
                    return_type=return_type.strip() if return_type else None,
                    docstring=docstring,
                    metrics=metrics,
                    security_level=security_level,
                    is_async=is_async,
                )
            )

        return methods

    def _extract_class_variables(
        self, class_body: str
    ) -> Tuple[List[str], List[str]]:
        """
        Extract class and instance variables from class body.

        Parameters
        ----------
        class_body : str
            Class body text.

        Returns
        -------
        Tuple[List[str], List[str]]
            Tuple of (class_variables, instance_variables).

        Notes
        -----
        - Class variables: defined directly in class scope (uppercase = constant).
        - Instance variables: assigned via ``self.var_name``.
        """
        class_vars: List[str] = []
        instance_vars: List[str] = []

        # Class variables
        class_var_pattern = re.compile(r"^\s+([A-Za-z_][\w]*)\s*[:=]")
        for line in class_body.split("\n"):
            match = class_var_pattern.match(line)
            if match and not line.strip().startswith("def "):
                var_name = match.group(1)
                if var_name.isupper():
                    class_vars.append(var_name)

        # Instance variables
        instance_var_pattern = re.compile(r"self\.([A-Za-z_][\w]*)\s*=")
        for match in instance_var_pattern.finditer(class_body):
            instance_vars.append(match.group(1))

        return class_vars, instance_vars

    def imports(self) -> List[ImportInfo]:
        """
        Extract all imports with enhanced dependency analysis.

        Returns
        -------
        List[ImportInfo]
            List of ``ImportInfo`` instances with module classification.

        See Also
        --------
        functions, classes, variables
        """
        cache_key = "imports"
        if cache_key in self._cache:
            return self._cache[cache_key]

        imports_list: List[ImportInfo] = []

        for match in self._IMPORT_PATTERN.finditer(self._original_code):
            from_module, from_imports, from_alias, direct_import, direct_alias = (
                match.groups()
            )
            line_number = self._get_line_number(match.start())

            if from_module:
                import_items = [item.strip() for item in from_imports.split(",")]
                aliases = self._parse_aliases(import_items)
                is_stdlib = from_module.split(".")[0] in self._PYTHON_STDLIB_MODULES

                imports_list.append(
                    ImportInfo(
                        module=from_module,
                        imports=import_items,
                        aliases=aliases,
                        line_number=line_number,
                        import_type="from_import",
                        is_stdlib=is_stdlib,
                        is_third_party=not is_stdlib and "." in from_module,
                        is_local=not is_stdlib and "." not in from_module,
                    )
                )
            else:
                module_items = [item.strip() for item in direct_import.split(",")]
                aliases = self._parse_aliases(module_items)
                is_stdlib = any(
                    module.split(".")[0] in self._PYTHON_STDLIB_MODULES
                    for module in module_items
                )

                imports_list.append(
                    ImportInfo(
                        module=direct_import,
                        imports=module_items,
                        aliases=aliases,
                        line_number=line_number,
                        import_type="direct_import",
                        is_stdlib=is_stdlib,
                        is_third_party=not is_stdlib,
                        is_local=False,
                    )
                )

        self._cache[cache_key] = imports_list
        return imports_list

    def _parse_aliases(self, items: List[str]) -> Dict[str, str]:
        """
        Parse aliases from import items.

        Parameters
        ----------
        items : List[str]
            List of import items potentially with ``as`` clauses.

        Returns
        -------
        Dict[str, str]
            Mapping of original names to their aliases.
        """
        aliases: Dict[str, str] = {}
        for item in items:
            item = item.strip()
            if " as " in item:
                parts = item.split(" as ")
                original = parts[0].strip()
                alias = parts[1].strip()
                aliases[original] = alias
            else:
                aliases[item] = item
        return aliases

    def variables(self) -> List[VariableInfo]:
        """
        Extract all global variables with enhanced type analysis.

        Returns
        -------
        List[VariableInfo]
            List of ``VariableInfo`` instances.
        """
        cache_key = "variables"
        if cache_key in self._cache:
            return self._cache[cache_key]

        variables_list: List[VariableInfo] = []
        function_names = {func.name for func in self.functions()}
        class_names = {cls.name for cls in self.classes()}

        for match in self._VARIABLE_PATTERN.finditer(self._code):
            var_name, type_hint, var_value = match.groups()
            line_number = self._get_line_number(match.start())

            if (
                var_name not in function_names
                and var_name not in class_names
                and not var_name.startswith("__")
            ):
                # Usage analysis
                usage_count = len(
                    re.findall(rf"\b{re.escape(var_name)}\b", self._code)
                )

                variables_list.append(
                    VariableInfo(
                        name=var_name,
                        value=var_value.strip() if var_value else "",
                        line_number=line_number,
                        is_constant=var_name.isupper(),
                        type_hint=type_hint.strip() if type_hint else None,
                        is_public=not var_name.startswith("_"),
                        usage_count=usage_count,
                    )
                )

        self._cache[cache_key] = variables_list
        return variables_list

    def function_calls(self) -> List[CallInfo]:
        """
        Extract all function calls with enhanced context analysis.

        Returns
        -------
        List[CallInfo]
            List of ``CallInfo`` instances.
        """
        cache_key = "function_calls"
        if cache_key in self._cache:
            return self._cache[cache_key]

        calls_list: List[CallInfo] = []
        user_functions = {func.name for func in self.functions()}

        for match in self._FUNC_CALL_PATTERN.finditer(self._code):
            call_text = match.group(0)
            func_name_match = re.match(r"([a-zA-Z_][\w\.]*)", call_text)

            if func_name_match:
                func_name = func_name_match.group(1)
                arguments = match.group(2) if len(match.groups()) > 1 else ""

                if self._is_valid_call(func_name):
                    call_type = (
                        "builtin"
                        if func_name in self._get_builtins()
                        else "function"
                    )
                    if func_name in user_functions:
                        call_type = "user_function"

                    calls_list.append(
                        CallInfo(
                            name=func_name,
                            line_number=self._get_line_number(match.start()),
                            call_type=call_type,
                            context=call_text[:100],
                            arguments=arguments,
                            is_dynamic=(
                                "getattr" in call_text
                                or "setattr" in call_text
                            ),
                            is_nested_call=call_text.count("(") > 1,
                        )
                    )

        for match in self._METHOD_CALL_PATTERN.finditer(self._code):
            method_name = match.group(1)
            arguments = match.group(2) if len(match.groups()) > 1 else ""

            if self._is_valid_call(method_name):
                calls_list.append(
                    CallInfo(
                        name=method_name,
                        line_number=self._get_line_number(match.start()),
                        call_type="method",
                        context=match.group(0)[:100],
                        arguments=arguments,
                        is_nested_call=match.group(0).count("(") > 1,
                    )
                )

        self._cache[cache_key] = calls_list
        return calls_list

    def _is_valid_call(self, name: str) -> bool:
        """
        Validate if a name represents a valid function/method call.

        Parameters
        ----------
        name : str
            Name to validate.

        Returns
        -------
        bool
            True if the name is a valid call target.
        """
        keywords = {
            "if", "else", "for", "while", "def", "class",
            "return", "import", "from", "try", "except",
            "with", "async", "await", "lambda", "yield",
            "raise", "assert", "del", "global", "nonlocal",
            "pass", "break", "continue",
        }
        return (
            name not in keywords
            and not name.startswith("__")
            and name not in {"self", "cls", "super", "True", "False", "None"}
        )

    def _get_builtins(self) -> FrozenSet[str]:
        """
        Return comprehensive set of Python built-in functions.

        Returns
        -------
        FrozenSet[str]
            Frozen set of built-in function names.
        """
        return frozenset({
            "abs", "all", "any", "ascii", "bin", "bool",
            "breakpoint", "bytearray", "bytes", "callable", "chr",
            "classmethod", "compile", "complex", "delattr", "dict",
            "dir", "divmod", "enumerate", "eval", "exec",
            "filter", "float", "format", "frozenset", "getattr",
            "globals", "hasattr", "hash", "help", "hex", "id",
            "input", "int", "isinstance", "issubclass", "iter",
            "len", "list", "locals", "map", "max", "memoryview",
            "min", "next", "object", "oct", "open", "ord",
            "pow", "print", "property", "range", "repr",
            "reversed", "round", "set", "setattr", "slice",
            "sorted", "staticmethod", "str", "sum", "super",
            "tuple", "type", "vars", "zip", "__import__",
        })

    def code_issues(self) -> List[CodeIssue]:
        """
        Find comprehensive code issues with enhanced detection.

        Returns
        -------
        List[CodeIssue]
            List of detected code issues with severity and suggestions.
        """
        if self._issues is not None:
            return self._issues

        issues: List[CodeIssue] = []

        # Analyze functions
        for func in self.functions():
            issues.extend(self._analyze_function_issues(func))

        # Analyze classes
        for cls in self.classes():
            issues.extend(self._analyze_class_issues(cls))

        # Analyze imports
        for imp in self.imports():
            issues.extend(self._analyze_import_issues(imp))

        # Analyze variables
        for var in self.variables():
            issues.extend(self._analyze_variable_issues(var))

        self._issues = issues
        return issues

    def _analyze_function_issues(self, func: FunctionInfo) -> List[CodeIssue]:
        """Analyze function-specific issues."""
        issues: List[CodeIssue] = []
        metrics = func.metrics

        if metrics is None:
            return issues

        if metrics.line_count > 50:
            issues.append(
                CodeIssue(
                    issue_type="LONG_FUNCTION",
                    description=(
                        f"Function '{func.name}' is too long "
                        f"({metrics.line_count} lines)"
                    ),
                    line_number=func.line_number,
                    severity=IssueSeverity.MEDIUM,
                    element_name=func.name,
                    category="maintainability",
                    suggestion=(
                        "Consider breaking down into smaller, "
                        "more focused functions"
                    ),
                    rule_id="CC001",
                )
            )

        if metrics.cyclomatic_complexity > 10:
            issues.append(
                CodeIssue(
                    issue_type="HIGH_COMPLEXITY",
                    description=(
                        f"Function '{func.name}' has high cyclomatic "
                        f"complexity ({metrics.cyclomatic_complexity})"
                    ),
                    line_number=func.line_number,
                    severity=IssueSeverity.HIGH,
                    element_name=func.name,
                    category="complexity",
                    suggestion=(
                        "Simplify logic by extracting methods or "
                        "using early returns"
                    ),
                    rule_id="CC002",
                )
            )

        if metrics.parameter_count > 5:
            issues.append(
                CodeIssue(
                    issue_type="TOO_MANY_PARAMETERS",
                    description=(
                        f"Function '{func.name}' has too many "
                        f"parameters ({metrics.parameter_count})"
                    ),
                    line_number=func.line_number,
                    severity=IssueSeverity.MEDIUM,
                    element_name=func.name,
                    category="design",
                    suggestion=(
                        "Consider using a parameter object, "
                        "dataclass, or configuration dictionary"
                    ),
                    rule_id="CC003",
                )
            )

        if metrics.nested_depth > 4:
            issues.append(
                CodeIssue(
                    issue_type="DEEP_NESTING",
                    description=(
                        f"Function '{func.name}' has deep nesting "
                        f"(level {metrics.nested_depth})"
                    ),
                    line_number=func.line_number,
                    severity=IssueSeverity.MEDIUM,
                    element_name=func.name,
                    category="readability",
                    suggestion=(
                        "Flatten nested structures using early "
                        "returns or extracted methods"
                    ),
                    rule_id="CC004",
                )
            )

        if metrics.maintainability_index < 40:
            issues.append(
                CodeIssue(
                    issue_type="LOW_MAINTAINABILITY",
                    description=(
                        f"Function '{func.name}' has low "
                        f"maintainability index "
                        f"({metrics.maintainability_index:.1f})"
                    ),
                    line_number=func.line_number,
                    severity=IssueSeverity.HIGH,
                    element_name=func.name,
                    category="maintainability",
                    suggestion="Refactor to improve readability and reduce complexity",
                    rule_id="CC005",
                )
            )

        return issues

    def _analyze_class_issues(self, cls: ClassInfo) -> List[CodeIssue]:
        """Analyze class-specific issues."""
        issues: List[CodeIssue] = []

        if len(cls.methods) > 20:
            issues.append(
                CodeIssue(
                    issue_type="LARGE_CLASS",
                    description=(
                        f"Class '{cls.name}' has too many methods "
                        f"({len(cls.methods)})"
                    ),
                    line_number=cls.line_number,
                    severity=IssueSeverity.MEDIUM,
                    element_name=cls.name,
                    category="design",
                    suggestion=(
                        "Consider breaking down into smaller, "
                        "more focused classes"
                    ),
                    rule_id="CC006",
                )
            )

        if cls.inheritance_depth > 3:
            issues.append(
                CodeIssue(
                    issue_type="DEEP_INHERITANCE",
                    description=(
                        f"Class '{cls.name}' has deep inheritance "
                        f"hierarchy ({cls.inheritance_depth} levels)"
                    ),
                    line_number=cls.line_number,
                    severity=IssueSeverity.MEDIUM,
                    element_name=cls.name,
                    category="design",
                    suggestion=(
                        "Consider composition over inheritance "
                        "to reduce coupling"
                    ),
                    rule_id="CC007",
                )
            )

        if len(cls.bases) > 3:
            issues.append(
                CodeIssue(
                    issue_type="TOO_MANY_BASES",
                    description=(
                        f"Class '{cls.name}' inherits from too many "
                        f"base classes ({len(cls.bases)})"
                    ),
                    line_number=cls.line_number,
                    severity=IssueSeverity.LOW,
                    element_name=cls.name,
                    category="design",
                    suggestion=(
                        "Consider using composition or mixins "
                        "to reduce inheritance complexity"
                    ),
                    rule_id="CC008",
                )
            )

        return issues

    def _analyze_import_issues(self, imp: ImportInfo) -> List[CodeIssue]:
        """Analyze import-specific issues."""
        issues: List[CodeIssue] = []

        if "*" in imp.imports:
            issues.append(
                CodeIssue(
                    issue_type="WILDCARD_IMPORT",
                    description=f"Wildcard import from module '{imp.module}'",
                    line_number=imp.line_number,
                    severity=IssueSeverity.LOW,
                    element_name=imp.module,
                    category="style",
                    suggestion="Import specific names instead of using wildcard (*)",
                    quick_fix=f"# Replace with specific imports from {imp.module}",
                    rule_id="CC009",
                )
            )

        return issues

    def _analyze_variable_issues(self, var: VariableInfo) -> List[CodeIssue]:
        """Analyze variable-specific issues."""
        issues: List[CodeIssue] = []

        if var.usage_count <= 1 and not var.is_constant:
            issues.append(
                CodeIssue(
                    issue_type="UNUSED_VARIABLE",
                    description=(
                        f"Variable '{var.name}' is defined but "
                        f"not used (usage count: {var.usage_count})"
                    ),
                    line_number=var.line_number,
                    severity=IssueSeverity.LOW,
                    element_name=var.name,
                    category="unused_code",
                    suggestion="Remove unused variable or use it in the code",
                    rule_id="CC010",
                )
            )

        return issues

    def security_vulnerabilities(self) -> List[SecurityVulnerability]:
        """
        Perform comprehensive security vulnerability scanning.

        Returns
        -------
        List[SecurityVulnerability]
            List of detected security vulnerabilities with CWE/OWASP mapping.
        """
        if self._security_vulnerabilities is not None:
            return self._security_vulnerabilities

        vulnerabilities: List[SecurityVulnerability] = []

        for vuln_type, pattern in self._SECURITY_VULNERABILITY_PATTERNS.items():
            for match in pattern.finditer(self._original_code):
                line_number = self._get_line_number(match.start())
                description = self._get_vulnerability_description(
                    vuln_type, match.group(0)
                )
                cwe_id = self._get_cwe_id(vuln_type)
                owasp_cat = self._get_owasp_category(vuln_type)
                mitigation = self._get_mitigation(vuln_type)

                vulnerabilities.append(
                    SecurityVulnerability(
                        vulnerability_type=vuln_type,
                        description=description,
                        line_number=line_number,
                        severity=self._get_vulnerability_severity(vuln_type),
                        cwe_id=cwe_id,
                        owasp_category=owasp_cat,
                        mitigation=mitigation,
                    )
                )

        self._security_vulnerabilities = vulnerabilities
        return vulnerabilities

    def _get_vulnerability_description(
        self, vuln_type: str, code: str
    ) -> str:
        """Get human-readable description for a vulnerability."""
        descriptions = {
            "command_injection": f"Potential command injection: {code[:80]}",
            "code_injection": f"Potential code injection: {code[:80]}",
            "pickle_injection": f"Unsafe deserialization: {code[:80]}",
            "path_traversal": f"Potential path traversal: {code[:80]}",
            "sql_injection": f"Potential SQL injection: {code[:80]}",
            "hardcoded_password": f"Hardcoded credential detected: {code[:80]}",
            "unsafe_deserialization": f"Unsafe deserialization: {code[:80]}",
        }
        return descriptions.get(vuln_type, f"Security issue: {code[:80]}")

    def _get_cwe_id(self, vuln_type: str) -> Optional[str]:
        """Map vulnerability type to CWE ID."""
        cwe_mapping = {
            "command_injection": "CWE-78",
            "code_injection": "CWE-94",
            "pickle_injection": "CWE-502",
            "path_traversal": "CWE-22",
            "sql_injection": "CWE-89",
            "hardcoded_password": "CWE-798",
            "unsafe_deserialization": "CWE-502",
        }
        return cwe_mapping.get(vuln_type)

    def _get_owasp_category(self, vuln_type: str) -> Optional[str]:
        """Map vulnerability type to OWASP Top 10 category."""
        owasp_mapping = {
            "command_injection": "A03:2021-Injection",
            "code_injection": "A03:2021-Injection",
            "pickle_injection": "A08:2021-Software and Data Integrity Failures",
            "path_traversal": "A01:2021-Broken Access Control",
            "sql_injection": "A03:2021-Injection",
            "hardcoded_password": "A07:2021-Identification and Authentication Failures",
            "unsafe_deserialization": "A08:2021-Software and Data Integrity Failures",
        }
        return owasp_mapping.get(vuln_type)

    def _get_mitigation(self, vuln_type: str) -> str:
        """Get mitigation advice for a vulnerability type."""
        mitigations = {
            "command_injection": (
                "Use subprocess.run() with shell=False and "
                "a list of arguments instead of a command string"
            ),
            "code_injection": (
                "Avoid eval()/exec() with user input. "
                "Use ast.literal_eval() for safe evaluation"
            ),
            "pickle_injection": (
                "Never unpickle data from untrusted sources. "
                "Use JSON or other safe serialization formats"
            ),
            "path_traversal": (
                "Validate and sanitize file paths. "
                "Use os.path.realpath() to resolve paths"
            ),
            "sql_injection": (
                "Use parameterized queries or ORM instead "
                "of string formatting"
            ),
            "hardcoded_password": (
                "Store secrets in environment variables or "
                "a secure vault (e.g., HashiCorp Vault)"
            ),
            "unsafe_deserialization": (
                "Avoid deserializing data from untrusted sources. "
                "Use safe parsers with type validation"
            ),
        }
        return mitigations.get(vuln_type, "Review and fix the security issue")

    def _get_vulnerability_severity(self, vuln_type: str) -> IssueSeverity:
        """Get severity level for a vulnerability type."""
        severity_mapping = {
            "command_injection": IssueSeverity.CRITICAL,
            "code_injection": IssueSeverity.CRITICAL,
            "pickle_injection": IssueSeverity.HIGH,
            "path_traversal": IssueSeverity.HIGH,
            "sql_injection": IssueSeverity.CRITICAL,
            "hardcoded_password": IssueSeverity.HIGH,
            "unsafe_deserialization": IssueSeverity.HIGH,
        }
        return severity_mapping.get(vuln_type, IssueSeverity.MEDIUM)

    def deps(self) -> List[DependencyInfo]:
        """
        Analyze comprehensive dependencies between code elements.

        Returns
        -------
        List[DependencyInfo]
            List of dependency relationships.
        """
        dependencies: List[DependencyInfo] = []
        functions = self.functions()
        classes = self.classes()
        calls = self.function_calls()

        # Function call dependencies
        for call in calls:
            source_func = self._find_containing_function(call.line_number)
            if source_func and call.call_type in ("function", "user_function"):
                dependencies.append(
                    DependencyInfo(
                        source=source_func.name,
                        target=call.name,
                        dependency_type="function_call",
                        line_number=call.line_number,
                        strength=self._calculate_dependency_strength(
                            call, source_func
                        ),
                    )
                )

        # Class inheritance dependencies
        for cls in classes:
            for base in cls.bases:
                dependencies.append(
                    DependencyInfo(
                        source=cls.name,
                        target=base,
                        dependency_type="class_inheritance",
                        line_number=cls.line_number,
                        strength=1.0,
                        is_direct=True,
                    )
                )

        # Method call dependencies
        for call in calls:
            if call.call_type == "method":
                source_func = self._find_containing_function(call.line_number)
                if source_func:
                    dependencies.append(
                        DependencyInfo(
                            source=source_func.name,
                            target=call.name,
                            dependency_type="method_call",
                            line_number=call.line_number,
                            strength=0.8,
                        )
                    )

        return dependencies

    def _calculate_dependency_strength(
        self, call: CallInfo, source_func: FunctionInfo
    ) -> float:
        """
        Calculate dependency strength based on call context.

        Parameters
        ----------
        call : CallInfo
            Call information.
        source_func : FunctionInfo
            Source function information.

        Returns
        -------
        float
            Dependency strength between 0.0 and 1.0.
        """
        strength = 1.0

        # Reduce for conditional calls
        if any(
            kw in call.context
            for kw in ("if", "else", "try", "except")
        ):
            strength *= 0.7

        # Reduce for rare calls
        call_count = len([
            c for c in self.function_calls() if c.name == call.name
        ])
        if call_count == 1:
            strength *= 0.8

        return round(strength, 2)

    def _find_containing_function(
        self, line_number: int
    ) -> Optional[FunctionInfo]:
        """
        Find which function contains the given line number.

        Parameters
        ----------
        line_number : int
            Line number to check.

        Returns
        -------
        FunctionInfo or None
            The containing function, or None if line is not in any function.
        """
        for func in self.functions():
            func_end_line = func.line_number + func.body.count("\n")
            if func.line_number <= line_number <= func_end_line:
                return func

        for cls in self.classes():
            for method in cls.methods:
                if cls.line_number <= line_number <= cls.line_number + 500:
                    return method

        return None

    def summary(self) -> CodeSummary:
        """
        Generate a comprehensive code analysis summary.

        Returns
        -------
        CodeSummary
            Summary dataclass with aggregate metrics.
        """
        functions = self.functions()
        classes = self.classes()
        imports = self.imports()
        variables = self.variables()
        issues = self.code_issues()
        vulnerabilities = self.security_vulnerabilities()

        avg_complexity = (
            sum(
                f.metrics.cyclomatic_complexity
                for f in functions
                if f.metrics
            ) / max(len(functions), 1)
        )

        avg_maintainability = (
            sum(
                f.metrics.maintainability_index
                for f in functions
                if f.metrics
            ) / max(len(functions), 1)
        )

        # Overall security level
        if any(
            v.severity == IssueSeverity.CRITICAL
            for v in vulnerabilities
        ):
            overall_security = SecurityLevel.CRITICAL_VULNERABILITY
        elif any(
            v.severity == IssueSeverity.HIGH
            for v in vulnerabilities
        ):
            overall_security = SecurityLevel.DANGEROUS
        elif vulnerabilities:
            overall_security = SecurityLevel.RISKY
        else:
            overall_security = SecurityLevel.SAFE

        critical_count = sum(
            1 for i in issues
            if i.severity in (IssueSeverity.CRITICAL, IssueSeverity.BLOCKER)
        )

        return CodeSummary(
            total_lines=self.line_count,
            total_functions=len(functions),
            total_classes=len(classes),
            total_imports=len(imports),
            total_variables=len(variables),
            average_complexity=round(avg_complexity, 2),
            maintainability_index=round(avg_maintainability, 2),
            security_level=overall_security,
            issue_count=len(issues),
            critical_issues=critical_count,
        )

    def clear_cache(self) -> None:
        """
        Clear all internal caches to free memory.

        This forces re-computation of all lazy properties on next
        access. Useful when the source code has been modified or
        when memory needs to be freed after analysis.

        Examples
        --------
        >>> parser = StringParser("def func(): pass")
        >>> funcs = parser.functions()  # Triggers parsing and caching
        >>> parser.clear_cache()  # Frees cached data
        """
        self._cache.clear()
        self._issues = None
        self._security_vulnerabilities = None
        self._source_hash = None

    def to_json(self, indent: int = 2) -> str:
        """
        Export complete analysis results as JSON string.

        Parameters
        ----------
        indent : int, optional
            Number of spaces for JSON indentation. Default is 2.

        Returns
        -------
        str
            JSON-formatted string of analysis results.

        Examples
        --------
        >>> parser = StringParser("def func(): pass")
        >>> json_str = parser.to_json()
        >>> 'functions' in json_str
        True
        """
        summary = self.summary()

        output = {
            "source_hash": self.source_hash,
            "source_size": self.source_size,
            "summary": {
                "total_lines": summary.total_lines,
                "total_functions": summary.total_functions,
                "total_classes": summary.total_classes,
                "total_imports": summary.total_imports,
                "total_variables": summary.total_variables,
                "average_complexity": summary.average_complexity,
                "maintainability_index": summary.maintainability_index,
                "security_level": summary.security_level.value,
                "issue_count": summary.issue_count,
                "critical_issues": summary.critical_issues,
            },
            "functions": [
                f.to_dict() for f in self.functions()
            ],
            "classes": [
                c.to_dict() for c in self.classes()
            ],
            "imports": [
                asdict(imp) for imp in self.imports()
            ],
            "variables": [
                asdict(var) for var in self.variables()
            ],
            "issues": [
                {
                    **asdict(issue),
                    "severity": issue.severity.value,
                }
                for issue in self.code_issues()
            ],
            "security_vulnerabilities": [
                {
                    **asdict(vuln),
                    "severity": vuln.severity.value,
                }
                for vuln in self.security_vulnerabilities()
            ],
        }

        return json.dumps(output, indent=indent, ensure_ascii=False)

    def __repr__(self) -> str:
        """
        Return unambiguous string representation.

        Returns
        -------
        str
            Representation showing class name and source hash.
        """
        return (
            f"StringParser("
            f"lines={self.line_count}, "
            f"hash={self.source_hash[:8]}...)"
        )

    def __str__(self) -> str:
        """
        Return human-readable analysis summary.

        Returns
        -------
        str
            Multi-line summary of key analysis results.
        """
        summary = self.summary()
        lines = [
            "StringParser Analysis Summary",
            f"  Lines: {summary.total_lines}",
            f"  Functions: {summary.total_functions}",
            f"  Classes: {summary.total_classes}",
            f"  Imports: {summary.total_imports}",
            f"  Variables: {summary.total_variables}",
            f"  Avg Complexity: {summary.average_complexity}",
            f"  Maintainability: {summary.maintainability_index:.1f}",
            f"  Security: {summary.security_level.value}",
            f"  Issues: {summary.issue_count} ({summary.critical_issues} critical)",
        ]
        return "\n".join(lines)

    def __len__(self) -> int:
        """
        Return the number of source code lines.

        Returns
        -------
        int
            Line count.

        Examples
        --------
        >>> parser = StringParser("x = 1\\ny = 2")
        >>> len(parser)
        2
        """
        return self.line_count

    def __contains__(self, item: str) -> bool:
        """
        Check if a name is defined in the source code.

        Parameters
        ----------
        item : str
            Name to search for in functions and classes.

        Returns
        -------
        bool
            True if the name is found.

        Examples
        --------
        >>> parser = StringParser("def hello(): pass")
        >>> "hello" in parser
        True
        """
        func_names = {f.name for f in self.functions()}
        class_names = {c.name for c in self.classes()}
        return item in func_names or item in class_names

    def __eq__(self, other: object) -> bool:
        """
        Check equality by comparing source code hashes.

        Parameters
        ----------
        other : object
            Another StringParser instance.

        Returns
        -------
        bool
            True if source codes are identical.

        Examples
        --------
        >>> p1 = StringParser("x = 1")
        >>> p2 = StringParser("x = 1")
        >>> p1 == p2
        True
        """
        if not isinstance(other, StringParser):
            return NotImplemented
        return self.source_hash == other.source_hash

    def __hash__(self) -> int:
        """
        Return hash based on source code.

        Returns
        -------
        int
            Hash value for use in sets and dicts.
        """
        return hash(self.source_hash)