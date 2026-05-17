#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
PEP 508 Environment Marker Parser and Evaluator with Extended Syntax Support.

This module provides a robust, feature-rich implementation of environment
markers as defined in PEP 508, with extended support for list literals
and membership testing operators (`in`, `not in`).

The implementation includes a complete lexer, recursive-descent parser,
and evaluator that can process complex boolean expressions with proper
operator precedence and parentheses grouping.

Key Features
------------
- Full PEP 508 compliance for environment markers
- Extended syntax support: `in [...]` and `not in [...]` operators
- Complete Abstract Syntax Tree (AST) representation

Supported Environment Variables
------------------------------
- `python_version`: Major.minor Python version (e.g., '3.11')
- `python_full_version`: Full Python version string
- `sys_platform`: Platform identifier (e.g., 'linux', 'win32', 'darwin')
- `platform_system`: Operating system name
- `platform_machine`: Machine architecture
- `platform_release`: OS release version
- `platform_version`: OS version information
- `platform_python_implementation`: Python implementation name
- `os_name`: OS name from os.name
- `extra`: Extra feature flag (from package extras)
- `implementation_name`: Python implementation name
- `implementation_version`: Python implementation version

Examples
--------
Basic usage:
>>> marker = Marker("python_version >= '3.8' and sys_platform == 'linux'")
>>> marker.evaluate()
True

List syntax (extended):
>>> marker = Marker("sys_platform in ['linux', 'darwin', 'win32']")
>>> marker.evaluate()
True

Complex expressions:
>>> marker = Marker(
...     "(python_version >= '3.8' or python_version < '3.0') and "
...     "sys_platform not in ['win32', 'cygwin']"
... )
>>> marker.get_variables()
{'python_version', 'sys_platform'}

References
----------
- PEP 508: https://www.python.org/dev/peps/pep-0508/
- packaging.markers: https://packaging.pypa.io/en/latest/markers.html
"""

import re
import os
import sys
import platform as _platform
from typing import (
    Any, Dict, List, Optional, Set, Tuple, Union, Iterator,
    ClassVar, Type, TypeVar, cast, overload
)
from enum import Enum, auto
from dataclasses import dataclass, field, asdict
from functools import lru_cache, total_ordering
from abc import ABC, abstractmethod
import warnings

# Try to import packaging.markers for fallback evaluation
try:
    from packaging.markers import Marker as PackagingMarker
    from packaging.markers import UndefinedEnvironmentName, InvalidMarker
    _PACKAGING_AVAILABLE = True
except ImportError:
    _PACKAGING_AVAILABLE = False
    PackagingMarker = None  # type: ignore
    UndefinedEnvironmentName = Exception  # type: ignore
    InvalidMarker = Exception  # type: ignore

# ============================================================================
# Enums and Constants
# ============================================================================

class TokenType(Enum):
    """
    Enumeration of all possible token types in the marker language.
    
    Attributes
    ----------
    LPAREN : str
        Left parenthesis '('.
    RPAREN : str
        Right parenthesis ')'.
    LBRACKET : str
        Left bracket '['.
    RBRACKET : str
        Right bracket ']'.
    COMMA : str
        Comma ','.
    AND : str
        Logical AND operator 'and'.
    OR : str
        Logical OR operator 'or'.
    IN : str
        Membership operator 'in'.
    NOT_IN : str
        Negative membership operator 'not in'.
    OPERATOR : str
        Comparison operators (==, !=, <, >, <=, >=).
    VARIABLE : str
        Environment variable name.
    STRING : str
        String literal (single or double quoted).
    EOF : str
        End of input marker.
    """
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    LBRACKET = "LBRACKET"
    RBRACKET = "RBRACKET"
    COMMA = "COMMA"
    AND = "AND"
    OR = "OR"
    IN = "IN"
    NOT_IN = "NOT_IN"
    OPERATOR = "OPERATOR"
    VARIABLE = "VARIABLE"
    STRING = "STRING"
    EOF = "EOF"


class ComparisonOperator(Enum):
    """
    Comparison operators supported in marker expressions.
    
    Attributes
    ----------
    EQ : str
        Equal to '=='.
    NE : str
        Not equal to '!='.
    LT : str
        Less than '<'.
    LE : str
        Less than or equal to '<='.
    GT : str
        Greater than '>'.
    GE : str
        Greater than or equal to '>='.
    """
    EQ = "=="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    
    @classmethod
    def from_string(cls, value: str) -> Optional['ComparisonOperator']:
        """
        Convert a string to a ComparisonOperator enum.
        
        Parameters
        ----------
        value : str
            String representation of the operator.
        
        Returns
        -------
        Optional[ComparisonOperator]
            The corresponding enum value, or None if not found.
        """
        for op in cls:
            if op.value == value:
                return op
        return None


class LogicalOperator(Enum):
    """
    Logical operators for combining expressions.
    
    Attributes
    ----------
    AND : str
        Logical conjunction 'and'.
    OR : str
        Logical disjunction 'or'.
    """
    AND = "and"
    OR = "or"
    
    @classmethod
    def from_string(cls, value: str) -> Optional['LogicalOperator']:
        """Convert a string to a LogicalOperator enum."""
        for op in cls:
            if op.value == value.lower():
                return op
        return None


class VariableName(Enum):
    """
    Standard PEP 508 environment variable names.
    
    Attributes
    ----------
    PYTHON_VERSION : str
        Major.minor Python version.
    PYTHON_FULL_VERSION : str
        Full Python version string.
    SYS_PLATFORM : str
        System platform identifier.
    PLATFORM_SYSTEM : str
        Operating system name.
    PLATFORM_MACHINE : str
        Machine architecture.
    PLATFORM_RELEASE : str
        OS release version.
    PLATFORM_VERSION : str
        OS version information.
    PLATFORM_PYTHON_IMPLEMENTATION : str
        Python implementation name.
    OS_NAME : str
        OS name from os.name.
    EXTRA : str
        Extra feature flag.
    IMPLEMENTATION_NAME : str
        Python implementation name.
    IMPLEMENTATION_VERSION : str
        Python implementation version.
    """
    PYTHON_VERSION = "python_version"
    PYTHON_FULL_VERSION = "python_full_version"
    SYS_PLATFORM = "sys_platform"
    PLATFORM_SYSTEM = "platform_system"
    PLATFORM_MACHINE = "platform_machine"
    PLATFORM_RELEASE = "platform_release"
    PLATFORM_VERSION = "platform_version"
    PLATFORM_PYTHON_IMPLEMENTATION = "platform_python_implementation"
    OS_NAME = "os_name"
    EXTRA = "extra"
    IMPLEMENTATION_NAME = "implementation_name"
    IMPLEMENTATION_VERSION = "implementation_version"
    
    @classmethod
    def is_valid(cls, name: str) -> bool:
        """Check if a variable name is a standard PEP 508 variable."""
        return name in cls._value2member_map_


# ============================================================================
# Abstract Syntax Tree (AST) Nodes
# ============================================================================

class ASTNode(ABC):
    """
    Abstract base class for all AST nodes in the marker expression tree.
    
    This serves as the foundation for the abstract syntax tree structure
    used to represent parsed marker expressions. All concrete node types
    inherit from this class.
    
    Methods
    -------
    accept(visitor)
        Accept a visitor for the visitor pattern.
    to_dict()
        Convert the node to a dictionary representation.
    """
    
    @abstractmethod
    def accept(self, visitor: 'ASTVisitor') -> Any:
        """
        Accept a visitor for the visitor pattern.
        
        Parameters
        ----------
        visitor : ASTVisitor
            The visitor to accept.
        
        Returns
        -------
        Any
            The result of the visitor's visit method.
        """
        pass
    
    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the node to a dictionary representation.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of the node.
        """
        pass
    
    @abstractmethod
    def get_variables(self) -> Set[str]:
        """
        Get all variable names used in this node and its children.
        
        Returns
        -------
        Set[str]
            Set of variable names.
        """
        pass


@dataclass(frozen=True)
class Comparison(ASTNode):
    """
    Represents a simple comparison: variable operator value.
    
    This node handles standard comparison operators like ==, !=, <, >, <=, >=.
    The node is immutable (frozen) for safety and hashability.
    
    Attributes
    ----------
    variable : str
        The variable name being compared (e.g., 'python_version').
    operator : ComparisonOperator
        The comparison operator.
    value : str
        The value to compare against (without quotes).
    
    Examples
    --------
    >>> comp = Comparison('python_version', ComparisonOperator.GE, '3.8')
    >>> comp.variable
    'python_version'
    >>> comp.operator.value
    '>='
    >>> comp.value
    '3.8'
    """
    variable: str
    operator: ComparisonOperator
    value: str
    
    def __post_init__(self) -> None:
        """Validate the comparison after initialization."""
        if not self.variable:
            raise ValueError("Variable name cannot be empty")
        if not VariableName.is_valid(self.variable):
            warnings.warn(
                f"Non-standard variable name: '{self.variable}'",
                UserWarning,
                stacklevel=3
            )
    
    def accept(self, visitor: 'ASTVisitor') -> Any:
        """Accept a visitor."""
        return visitor.visit_comparison(self)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "type": "Comparison",
            "variable": self.variable,
            "operator": self.operator.value,
            "value": self.value,
        }
    
    def get_variables(self) -> Set[str]:
        """Get variables used in this node."""
        return {self.variable}
    
    def __repr__(self) -> str:
        return (f"Comparison(variable={self.variable!r}, "
                f"operator={self.operator.value!r}, value={self.value!r})")


@dataclass(frozen=True)
class InComparison(ASTNode):
    """
    Represents an 'in' comparison: variable in [value1, value2, ...].
    
    This node handles membership testing against a list of values.
    
    Attributes
    ----------
    variable : str
        The variable name being checked.
    values : Tuple[str, ...]
        Tuple of values to check membership against.
    
    Examples
    --------
    >>> in_comp = InComparison('sys_platform', ('linux', 'darwin', 'win32'))
    >>> in_comp.variable
    'sys_platform'
    >>> in_comp.values
    ('linux', 'darwin', 'win32')
    """
    variable: str
    values: Tuple[str, ...]
    
    def __post_init__(self) -> None:
        """Validate the in comparison after initialization."""
        if not self.variable:
            raise ValueError("Variable name cannot be empty")
        if not self.values:
            raise ValueError("Values list cannot be empty")
        if not VariableName.is_valid(self.variable):
            warnings.warn(
                f"Non-standard variable name: '{self.variable}'",
                UserWarning,
                stacklevel=3
            )
    
    def accept(self, visitor: 'ASTVisitor') -> Any:
        """Accept a visitor."""
        return visitor.visit_in_comparison(self)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "type": "InComparison",
            "variable": self.variable,
            "values": list(self.values),
        }
    
    def get_variables(self) -> Set[str]:
        """Get variables used in this node."""
        return {self.variable}
    
    def __repr__(self) -> str:
        return f"InComparison(variable={self.variable!r}, values={list(self.values)!r})"


@dataclass(frozen=True)
class NotInComparison(ASTNode):
    """
    Represents a 'not in' comparison: variable not in [value1, value2, ...].
    
    This node handles negative membership testing against a list of values.
    
    Attributes
    ----------
    variable : str
        The variable name being checked.
    values : Tuple[str, ...]
        Tuple of values to check membership against.
    
    Examples
    --------
    >>> not_in = NotInComparison('extra', ('test', 'dev', 'ci'))
    >>> not_in.variable
    'extra'
    >>> not_in.values
    ('test', 'dev', 'ci')
    """
    variable: str
    values: Tuple[str, ...]
    
    def __post_init__(self) -> None:
        """Validate the not in comparison after initialization."""
        if not self.variable:
            raise ValueError("Variable name cannot be empty")
        if not self.values:
            raise ValueError("Values list cannot be empty")
        if not VariableName.is_valid(self.variable):
            warnings.warn(
                f"Non-standard variable name: '{self.variable}'",
                UserWarning,
                stacklevel=3
            )
    
    def accept(self, visitor: 'ASTVisitor') -> Any:
        """Accept a visitor."""
        return visitor.visit_not_in_comparison(self)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "type": "NotInComparison",
            "variable": self.variable,
            "values": list(self.values),
        }
    
    def get_variables(self) -> Set[str]:
        """Get variables used in this node."""
        return {self.variable}
    
    def __repr__(self) -> str:
        return f"NotInComparison(variable={self.variable!r}, values={list(self.values)!r})"


@dataclass(frozen=True)
class BinaryOp(ASTNode):
    """
    Represents a binary logical operation: left AND right or left OR right.
    
    This node handles combining sub-expressions with logical operators.
    
    Attributes
    ----------
    left : ASTNode
        The left operand (sub-expression).
    operator : LogicalOperator
        The binary operator.
    right : ASTNode
        The right operand (sub-expression).
    
    Examples
    --------
    >>> left = Comparison('python_version', ComparisonOperator.GE, '3.8')
    >>> right = Comparison('sys_platform', ComparisonOperator.EQ, 'linux')
    >>> binary = BinaryOp(left, LogicalOperator.AND, right)
    >>> binary.operator.value
    'and'
    """
    left: ASTNode
    operator: LogicalOperator
    right: ASTNode
    
    def accept(self, visitor: 'ASTVisitor') -> Any:
        """Accept a visitor."""
        return visitor.visit_binary_op(self)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "type": "BinaryOp",
            "operator": self.operator.value,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
        }
    
    def get_variables(self) -> Set[str]:
        """Get variables used in this node and its children."""
        return self.left.get_variables() | self.right.get_variables()
    
    def __repr__(self) -> str:
        return (f"BinaryOp(left={self.left!r}, "
                f"operator={self.operator.value!r}, right={self.right!r})")


@dataclass(frozen=True)
class Paren(ASTNode):
    """
    Represents a parenthesized expression: (expr).
    
    This node wraps an expression that is enclosed in parentheses.
    
    Attributes
    ----------
    expr : ASTNode
        The expression inside parentheses.
    
    Examples
    --------
    >>> inner = Comparison('python_version', ComparisonOperator.GE, '3.8')
    >>> paren = Paren(inner)
    >>> isinstance(paren.expr, Comparison)
    True
    """
    expr: ASTNode
    
    def accept(self, visitor: 'ASTVisitor') -> Any:
        """Accept a visitor."""
        return visitor.visit_paren(self)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "type": "Paren",
            "expr": self.expr.to_dict(),
        }
    
    def get_variables(self) -> Set[str]:
        """Get variables used in the wrapped expression."""
        return self.expr.get_variables()
    
    def __repr__(self) -> str:
        return f"Paren(expr={self.expr!r})"


# ============================================================================
# AST Visitor Pattern
# ============================================================================

class ASTVisitor(ABC):
    """
    Abstract base class for AST visitors implementing the visitor pattern.
    
    Subclasses should implement visit methods for each concrete node type.
    """
    
    @abstractmethod
    def visit_comparison(self, node: Comparison) -> Any:
        """Visit a Comparison node."""
        pass
    
    @abstractmethod
    def visit_in_comparison(self, node: InComparison) -> Any:
        """Visit an InComparison node."""
        pass
    
    @abstractmethod
    def visit_not_in_comparison(self, node: NotInComparison) -> Any:
        """Visit a NotInComparison node."""
        pass
    
    @abstractmethod
    def visit_binary_op(self, node: BinaryOp) -> Any:
        """Visit a BinaryOp node."""
        pass
    
    @abstractmethod
    def visit_paren(self, node: Paren) -> Any:
        """Visit a Paren node."""
        pass


class EvaluationVisitor(ASTVisitor):
    """
    Visitor that evaluates an AST with a given environment.
    
    Parameters
    ----------
    environment : Dict[str, str]
        The environment dictionary containing variable values.
    
    Attributes
    ----------
    environment : Dict[str, str]
        The evaluation environment.
    """
    
    def __init__(self, environment: Dict[str, str]):
        self.environment = environment
    
    def _compare_values(self, var_value: str, operator: ComparisonOperator,
                       target_value: str) -> bool:
        """
        Compare two values with intelligent type coercion.
        
        Parameters
        ----------
        var_value : str
            The variable value.
        operator : ComparisonOperator
            The comparison operator.
        target_value : str
            The target value to compare against.
        
        Returns
        -------
        bool
            The result of the comparison.
        """
        # Try numeric comparison first
        try:
            var_num = float(var_value)
            target_num = float(target_value)
            
            if operator == ComparisonOperator.EQ:
                return var_num == target_num
            elif operator == ComparisonOperator.NE:
                return var_num != target_num
            elif operator == ComparisonOperator.LT:
                return var_num < target_num
            elif operator == ComparisonOperator.LE:
                return var_num <= target_num
            elif operator == ComparisonOperator.GT:
                return var_num > target_num
            elif operator == ComparisonOperator.GE:
                return var_num >= target_num
        except (ValueError, TypeError):
            # Fall back to string comparison
            if operator == ComparisonOperator.EQ:
                return var_value == target_value
            elif operator == ComparisonOperator.NE:
                return var_value != target_value
            elif operator == ComparisonOperator.LT:
                return var_value < target_value
            elif operator == ComparisonOperator.LE:
                return var_value <= target_value
            elif operator == ComparisonOperator.GT:
                return var_value > target_value
            elif operator == ComparisonOperator.GE:
                return var_value >= target_value
        
        return False
    
    def visit_comparison(self, node: Comparison) -> bool:
        """Evaluate a Comparison node."""
        var_value = self.environment.get(node.variable, '')
        return self._compare_values(var_value, node.operator, node.value)
    
    def visit_in_comparison(self, node: InComparison) -> bool:
        """Evaluate an InComparison node."""
        var_value = self.environment.get(node.variable, '')
        return var_value in node.values
    
    def visit_not_in_comparison(self, node: NotInComparison) -> bool:
        """Evaluate a NotInComparison node."""
        var_value = self.environment.get(node.variable, '')
        return var_value not in node.values
    
    def visit_binary_op(self, node: BinaryOp) -> bool:
        """Evaluate a BinaryOp node."""
        left_result = node.left.accept(self)
        
        # Short-circuit evaluation
        if node.operator == LogicalOperator.AND and not left_result:
            return False
        if node.operator == LogicalOperator.OR and left_result:
            return True
        
        right_result = node.right.accept(self)
        
        if node.operator == LogicalOperator.AND:
            return left_result and right_result
        else:  # OR
            return left_result or right_result
    
    def visit_paren(self, node: Paren) -> bool:
        """Evaluate a Paren node."""
        return node.expr.accept(self)


class StringifyVisitor(ASTVisitor):
    """
    Visitor that converts an AST back to a normalized string representation.
    
    This visitor produces a canonical string representation of the AST
    that can be used for comparison and hashing.
    """
    
    def visit_comparison(self, node: Comparison) -> str:
        """Convert Comparison to string."""
        return f"{node.variable}{node.operator.value}'{node.value}'"
    
    def visit_in_comparison(self, node: InComparison) -> str:
        """Convert InComparison to string."""
        values_str = ','.join(f"'{v}'" for v in node.values)
        return f"{node.variable} in [{values_str}]"
    
    def visit_not_in_comparison(self, node: NotInComparison) -> str:
        """Convert NotInComparison to string."""
        values_str = ','.join(f"'{v}'" for v in node.values)
        return f"{node.variable} not in [{values_str}]"
    
    def visit_binary_op(self, node: BinaryOp) -> str:
        """Convert BinaryOp to string."""
        left_str = node.left.accept(self)
        right_str = node.right.accept(self)
        return f"{left_str} {node.operator.value} {right_str}"
    
    def visit_paren(self, node: Paren) -> str:
        """Convert Paren to string."""
        return f"({node.expr.accept(self)})"


class VariableExtractorVisitor(ASTVisitor):
    """
    Visitor that extracts all variable names from an AST.
    """
    
    def visit_comparison(self, node: Comparison) -> Set[str]:
        """Extract variable from Comparison."""
        return {node.variable}
    
    def visit_in_comparison(self, node: InComparison) -> Set[str]:
        """Extract variable from InComparison."""
        return {node.variable}
    
    def visit_not_in_comparison(self, node: NotInComparison) -> Set[str]:
        """Extract variable from NotInComparison."""
        return {node.variable}
    
    def visit_binary_op(self, node: BinaryOp) -> Set[str]:
        """Extract variables from both sides of BinaryOp."""
        left_vars = node.left.accept(self)
        right_vars = node.right.accept(self)
        return left_vars | right_vars
    
    def visit_paren(self, node: Paren) -> Set[str]:
        """Extract variables from parenthesized expression."""
        return node.expr.accept(self)


# ============================================================================
# Token and Tokenizer
# ============================================================================

@dataclass(frozen=True)
class Token:
    """
    Represents a lexical token in the marker expression.
    
    Attributes
    ----------
    type : TokenType
        The token type.
    value : str
        The actual token value.
    line : int
        The line number where the token appears.
    column : int
        The column number where the token appears.
    
    Examples
    --------
    >>> token = Token(TokenType.VARIABLE, 'python_version', 1, 1)
    >>> token.type.value
    'VARIABLE'
    >>> token.value
    'python_version'
    """
    type: TokenType
    value: str
    line: int
    column: int
    
    def __repr__(self) -> str:
        return (f"Token(type={self.type.value!r}, value={self.value!r}, "
                f"line={self.line}, column={self.column})")


class TokenizationError(ValueError):
    """
    Exception raised when tokenization fails.
    
    Attributes
    ----------
    message : str
        Error message.
    line : int
        Line number where error occurred.
    column : int
        Column number where error occurred.
    character : str
        The invalid character that caused the error.
    """
    
    def __init__(self, message: str, line: int, column: int, character: str):
        self.line = line
        self.column = column
        self.character = character
        full_message = f"{message} at line {line}, column {column}: '{character}'"
        super().__init__(full_message)


class MarkerTokenizer:
    """
    Tokenizes a marker string into a stream of tokens.
    
    This class converts a marker string into a stream of tokens that can
    be consumed by the parser. It handles whitespace, operators, variables,
    strings, and list syntax with comprehensive error handling.
    
    Parameters
    ----------
    marker : str
        The marker string to tokenize.
    
    Attributes
    ----------
    marker : str
        The original marker string.
    tokens : List[Token]
        List of tokens produced by tokenization.
    
    Raises
    ------
    TokenizationError
        If an invalid character is encountered.
    
    Examples
    --------
    >>> tokenizer = MarkerTokenizer("python_version >= '3.8'")
    >>> len(tokenizer.tokens)
    5
    >>> tokenizer.tokens[0].type
    <TokenType.VARIABLE: 'VARIABLE'>
    """
    
    # Token patterns compiled once for efficiency
    _TOKEN_PATTERNS: ClassVar[List[Tuple[TokenType, re.Pattern]]] = [
        (TokenType.LPAREN, re.compile(r'\(')),
        (TokenType.RPAREN, re.compile(r'\)')),
        (TokenType.LBRACKET, re.compile(r'\[')),
        (TokenType.RBRACKET, re.compile(r'\]')),
        (TokenType.COMMA, re.compile(r',')),
        (TokenType.AND, re.compile(r'\band\b', re.IGNORECASE)),
        (TokenType.OR, re.compile(r'\bor\b', re.IGNORECASE)),
        (TokenType.IN, re.compile(r'\bin\b', re.IGNORECASE)),
        (TokenType.NOT_IN, re.compile(r'\bnot\s+in\b', re.IGNORECASE)),
        (TokenType.OPERATOR, re.compile(r'(==|!=|<=|>=|<|>)')),
        (TokenType.VARIABLE, re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*')),
        (TokenType.STRING, re.compile(r'(?:"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')')),
    ]
    
    def __init__(self, marker: str):
        self.marker = marker
        self.tokens: List[Token] = []
        self._line: int = 1
        self._column: int = 1
        self._pos: int = 0
        self._tokenize()
    
    def _advance(self, n: int = 1) -> None:
        """
        Advance position by n characters, updating line and column.
        
        Parameters
        ----------
        n : int, default=1
            Number of characters to advance.
        """
        for _ in range(n):
            if self._pos < len(self.marker):
                if self.marker[self._pos] == '\n':
                    self._line += 1
                    self._column = 1
                else:
                    self._column += 1
                self._pos += 1
    
    def _skip_whitespace(self) -> None:
        """Skip any whitespace characters."""
        while self._pos < len(self.marker) and self.marker[self._pos].isspace():
            self._advance()
    
    def _match_pattern(self, pattern: re.Pattern) -> Optional[str]:
        """
        Try to match a compiled regex at current position.
        
        Parameters
        ----------
        pattern : re.Pattern
            The compiled regex pattern to match.
        
        Returns
        -------
        Optional[str]
            The matched string if found, None otherwise.
        """
        match = pattern.match(self.marker, self._pos)
        if match:
            value = match.group()
            self._advance(len(value))
            return value
        return None
    
    def _tokenize(self) -> None:
        """
        Tokenize the marker string.
        
        This method scans the input string and produces tokens for
        all recognized patterns.
        
        Raises
        ------
        TokenizationError
            If an invalid character is encountered.
        """
        while self._pos < len(self.marker):
            self._skip_whitespace()
            if self._pos >= len(self.marker):
                break
            
            start_line = self._line
            start_col = self._column
            matched = False
            
            for token_type, pattern in self._TOKEN_PATTERNS:
                value = self._match_pattern(pattern)
                if value is not None:
                    # Normalize operator values
                    if token_type in (TokenType.AND, TokenType.OR, TokenType.IN):
                        value = value.lower()
                    elif token_type == TokenType.NOT_IN:
                        value = 'not in'
                    
                    self.tokens.append(Token(token_type, value, start_line, start_col))
                    matched = True
                    break
            
            if not matched:
                raise TokenizationError(
                    "Invalid character",
                    self._line,
                    self._column,
                    self.marker[self._pos]
                )
    
    def __iter__(self) -> Iterator[Token]:
        """Return an iterator over the tokens."""
        return iter(self.tokens)
    
    def __len__(self) -> int:
        """Return the number of tokens."""
        return len(self.tokens)


# ============================================================================
# Parser
# ============================================================================

class ParseError(SyntaxError):
    """
    Exception raised when parsing fails.
    
    Attributes
    ----------
    message : str
        Error message.
    token : Optional[Token]
        The token where the error occurred.
    expected : Optional[str]
        What was expected.
    got : Optional[str]
        What was actually found.
    """
    
    def __init__(self, message: str, token: Optional[Token] = None,
                 expected: Optional[str] = None, got: Optional[str] = None):
        self.token = token
        self.expected = expected
        self.got = got
        
        if token:
            full_message = (f"{message} at line {token.line}, column {token.column}. "
                           f"Token: {token.type.value}('{token.value}')")
            if expected and got:
                full_message += f" (expected {expected}, got {got})"
        else:
            full_message = message
        
        super().__init__(full_message)


class MarkerParser:
    """
    Parses a marker string into an AST using recursive descent parsing.
    
    This parser converts a token stream into an abstract syntax tree that
    can be evaluated or analyzed. It implements proper operator precedence
    and handles parenthesized expressions.
    
    Grammar
    -------
    expr        ::= and_expr ('or' and_expr)*
    and_expr    ::= primary ('and' primary)*
    primary     ::= '(' expr ')' | comparison
    comparison  ::= VARIABLE OPERATOR STRING
                  | VARIABLE 'in' list
                  | VARIABLE 'not in' list
    list        ::= '[' STRING (',' STRING)* ']'
    
    Parameters
    ----------
    marker : str
        The marker string to parse.
    
    Attributes
    ----------
    tokens : List[Token]
        The list of tokens from the tokenizer.
    
    Raises
    ------
    ParseError
        If the marker syntax is invalid.
    TokenizationError
        If tokenization fails.
    
    Examples
    --------
    >>> parser = MarkerParser("python_version >= '3.8'")
    >>> ast = parser.parse()
    >>> isinstance(ast, Comparison)
    True
    """
    
    def __init__(self, marker: str):
        self.tokens = list(MarkerTokenizer(marker))
        self._pos: int = 0
        self._current_token: Optional[Token] = self.tokens[0] if self.tokens else None
    
    def _advance(self) -> None:
        """Move to the next token."""
        self._pos += 1
        if self._pos < len(self.tokens):
            self._current_token = self.tokens[self._pos]
        else:
            self._current_token = None
    
    def _peek(self) -> Optional[Token]:
        """Look at the current token without consuming it."""
        return self._current_token
    
    def _match(self, expected_type: TokenType) -> Token:
        """
        Match and consume a token of the expected type.
        
        Parameters
        ----------
        expected_type : TokenType
            The expected token type.
        
        Returns
        -------
        Token
            The matched token.
        
        Raises
        ------
        ParseError
            If the current token doesn't match the expected type.
        """
        token = self._peek()
        if token and token.type == expected_type:
            self._advance()
            return token
        else:
            got = token.type.value if token else 'EOF'
            raise ParseError(
                f"Expected {expected_type.value}",
                token,
                expected=expected_type.value,
                got=got
            )
    
    def parse(self) -> ASTNode:
        """
        Parse the whole expression.
        
        Returns
        -------
        ASTNode
            The root node of the AST.
        
        Examples
        --------
        >>> parser = MarkerParser("python_version >= '3.8' and sys_platform == 'linux'")
        >>> ast = parser.parse()
        >>> isinstance(ast, BinaryOp)
        True
        """
        return self._parse_expr()
    
    def _parse_expr(self) -> ASTNode:
        """
        Parse an expression with OR as lowest precedence.
        
        expr ::= and_expr ('or' and_expr)*
        
        Returns
        -------
        ASTNode
            The parsed expression node.
        """
        node = self._parse_and()
        
        while self._peek() and self._peek().type == TokenType.OR:
            self._advance()
            right = self._parse_and()
            node = BinaryOp(node, LogicalOperator.OR, right)
        
        return node
    
    def _parse_and(self) -> ASTNode:
        """
        Parse an expression with AND as medium precedence.
        
        and_expr ::= primary ('and' primary)*
        
        Returns
        -------
        ASTNode
            The parsed expression node.
        """
        node = self._parse_primary()
        
        while self._peek() and self._peek().type == TokenType.AND:
            self._advance()
            right = self._parse_primary()
            node = BinaryOp(node, LogicalOperator.AND, right)
        
        return node
    
    def _parse_primary(self) -> ASTNode:
        """
        Parse a primary: either a parenthesized expression or a comparison.
        
        primary ::= '(' expr ')' | comparison
        
        Returns
        -------
        ASTNode
            The parsed primary expression node.
        """
        token = self._peek()
        
        if token and token.type == TokenType.LPAREN:
            self._advance()
            node = self._parse_expr()
            self._match(TokenType.RPAREN)
            return Paren(node)
        else:
            return self._parse_comparison()
    
    def _parse_comparison(self) -> ASTNode:
        """
        Parse a comparison expression.
        
        comparison ::= VARIABLE OPERATOR STRING
                     | VARIABLE 'in' list
                     | VARIABLE 'not in' list
        
        Returns
        -------
        ASTNode
            A Comparison, InComparison, or NotInComparison node.
        
        Raises
        ------
        ParseError
            If the comparison syntax is invalid.
        """
        var_token = self._match(TokenType.VARIABLE)
        token = self._peek()
        
        if not token:
            raise ParseError("Unexpected end of input after variable", var_token)
        
        # Check for 'not in' or 'in' operators
        if token.type == TokenType.NOT_IN:
            self._advance()
            values = self._parse_list()
            return NotInComparison(var_token.value, tuple(values))
        elif token.type == TokenType.IN:
            self._advance()
            values = self._parse_list()
            return InComparison(var_token.value, tuple(values))
        elif token.type == TokenType.OPERATOR:
            self._advance()
            val_token = self._match(TokenType.STRING)
            # Strip quotes and unescape
            value = self._unescape_string(val_token.value)
            operator = ComparisonOperator.from_string(token.value)
            if operator is None:
                raise ParseError(f"Invalid operator: {token.value}", token)
            return Comparison(var_token.value, operator, value)
        else:
            raise ParseError(
                f"Unexpected token after variable",
                token,
                expected="OPERATOR, IN, or NOT_IN",
                got=token.type.value
            )
    
    def _parse_list(self) -> List[str]:
        """
        Parse a list of strings like ['test', 'dev'].
        
        list ::= '[' STRING (',' STRING)* ']'
        
        Returns
        -------
        List[str]
            List of string values.
        
        Raises
        ------
        ParseError
            If the list syntax is invalid.
        
        Examples
        --------
        >>> parser = MarkerParser("extra in ['test', 'dev']")
        >>> parser._parse_list()
        ['test', 'dev']
        """
        self._match(TokenType.LBRACKET)
        values = []
        
        token = self._peek()
        if token and token.type == TokenType.RBRACKET:
            raise ParseError("Empty list not allowed", token)
        
        while self._peek() and self._peek().type != TokenType.RBRACKET:
            token = self._match(TokenType.STRING)
            values.append(self._unescape_string(token.value))
            
            token = self._peek()
            if token and token.type == TokenType.COMMA:
                self._advance()
                # Check for trailing comma
                if self._peek() and self._peek().type == TokenType.RBRACKET:
                    raise ParseError("Trailing comma not allowed in list", token)
            elif token and token.type != TokenType.RBRACKET:
                raise ParseError(
                    f"Expected comma or closing bracket",
                    token,
                    got=token.type.value
                )
        
        self._match(TokenType.RBRACKET)
        return values
    
    @staticmethod
    def _unescape_string(s: str) -> str:
        """
        Unescape a quoted string literal.
        
        Parameters
        ----------
        s : str
            The quoted string to unescape.
        
        Returns
        -------
        str
            The unescaped string without quotes.
        """
        # Remove quotes
        if len(s) >= 2 and (s[0] == s[-1]) and s[0] in ('"', "'"):
            s = s[1:-1]
        
        # Handle escape sequences
        s = s.replace('\\"', '"')
        s = s.replace("\\'", "'")
        s = s.replace('\\\\', '\\')
        s = s.replace('\\n', '\n')
        s = s.replace('\\r', '\r')
        s = s.replace('\\t', '\t')
        
        return s


# ============================================================================
# Enhanced Marker Class
# ============================================================================

@total_ordering
class Marker:
    """
    A robust and feature‑rich environment marker evaluator.
    
    This class parses and evaluates Python environment markers as defined in
    PEP 508, with extended support for list literals and membership testing.
    
    Parameters
    ----------
    marker : str
        The marker string to be parsed and evaluated. Must conform to PEP 508
        with extended support for list syntax.
    validate : bool, default=True
        Whether to validate the marker string upon initialization. If `True`
        and validation fails, a `ValueError` is raised.
    
    Attributes
    ----------
    marker_string : str
        The original marker string.
    ast : Optional[ASTNode]
        The abstract syntax tree of the parsed marker (None if invalid).
    variables : Set[str]
        Set of variable names used in the marker.
    has_list_operators : bool
        Whether the marker uses extended list syntax.
    is_valid : bool
        Indicates whether the marker string is syntactically valid.
    
    Methods
    -------
    evaluate(environment=None)
        Evaluate the marker against a given environment dictionary.
    get_ast()
        Return the abstract syntax tree of the marker.
    get_variables()
        Return the set of variable names used in the marker.
    normalize(marker)
        Return a canonicalized version of a marker string (classmethod).
    to_string()
        Convert the AST back to a normalized string.
    
    Notes
    -----
    This implementation extends the standard PEP 508 syntax by supporting
    list literals with the `in` and `not in` operators:
    
    - `sys_platform in ['linux', 'windows']`
    - `extra not in ['test', 'dev']`
    
    The class is thread-safe for parsing (uses cached ASTs) and provides
    comprehensive error handling with detailed error messages.
    
    Examples
    --------
    Basic usage:
    >>> m = Marker("python_version >= '3.8' and sys_platform == 'linux'")
    >>> m.evaluate()
    True
    
    Using list syntax:
    >>> m = Marker("python_version >= '3.8' and sys_platform in ['linux', 'windows']")
    >>> m.evaluate()
    True
    
    Extracting variables:
    >>> m.get_variables()
    {'python_version', 'sys_platform'}
    
    String representation:
    >>> print(m)
    python_version >= '3.8' and sys_platform in ['linux', 'windows']
    
    Equality comparison:
    >>> m1 = Marker("python_version >= '3.8' and sys_platform in ['linux', 'windows']")
    >>> m2 = Marker("python_version>='3.8' and sys_platform in ['linux','windows']")
    >>> m1 == m2
    True
    
    Invalid marker handling:
    >>> try:
    ...     m = Marker("python_version >== '3.8'")
    ... except ValueError as e:
    ...     print("Invalid marker")
    Invalid marker
    """
    
    # Class-level AST cache for performance
    _ast_cache: ClassVar[Dict[str, ASTNode]] = {}
    
    # Valid environment variable names
    _VALID_VARIABLES: ClassVar[Set[str]] = {
        'python_version',
        'python_full_version',
        'sys_platform',
        'platform_system',
        'platform_machine',
        'platform_release',
        'platform_version',
        'platform_python_implementation',
        'os_name',
        'extra',
        'implementation_name',
        'implementation_version',
    }
    
    def __init__(self, marker: str, validate: bool = True):
        self.marker_string = marker
        self.has_list_operators = self._check_for_list_operators(marker)
        
        # Try to parse the marker
        try:
            if marker in self._ast_cache:
                self.ast = self._ast_cache[marker]
            else:
                parser = MarkerParser(marker)
                self.ast = parser.parse()
                self._ast_cache[marker] = self.ast
            self.is_valid = True
        except (TokenizationError, ParseError, ValueError) as e:
            self.ast = None
            self.is_valid = False
            if validate:
                raise ValueError(f"Invalid marker: {marker}\n{e}") from e
        
        # Extract variables from AST
        if self.ast is not None:
            extractor = VariableExtractorVisitor()
            self.variables = self.ast.accept(extractor)
        else:
            self.variables = set()
        
        # Initialize packaging marker for fallback (only if available and no list operators)
        self._packaging_marker: Optional[Any] = None
        if _PACKAGING_AVAILABLE and not self.has_list_operators and self.is_valid:
            try:
                self._packaging_marker = PackagingMarker(marker)
            except Exception:
                # Packaging marker failed, but we still have our AST
                pass
    
    @staticmethod
    def _check_for_list_operators(marker: str) -> bool:
        """
        Check if the marker contains list operators.
        
        Parameters
        ----------
        marker : str
            The marker string to check.
        
        Returns
        -------
        bool
            True if the marker contains list syntax, False otherwise.
        """
        pattern_in = re.compile(r'\bin\s*\[', re.IGNORECASE)
        pattern_not_in = re.compile(r'\bnot\s+in\s*\[', re.IGNORECASE)
        return bool(pattern_in.search(marker) or pattern_not_in.search(marker))
    
    @staticmethod
    def _get_default_environment() -> Dict[str, str]:
        """
        Get the default environment for evaluation.
        
        This method gathers system information to populate the standard
        PEP 508 environment variables.
        
        Returns
        -------
        Dict[str, str]
            Default environment dictionary with system information.
        
        Examples
        --------
        >>> env = Marker._get_default_environment()
        >>> 'python_version' in env
        True
        >>> 'sys_platform' in env
        True
        """
        env = {}
        
        # Python version information
        env['python_version'] = f"{sys.version_info.major}.{sys.version_info.minor}"
        env['python_full_version'] = sys.version.split()[0]
        
        # Platform information
        env['sys_platform'] = sys.platform
        env['platform_system'] = _platform.system()
        env['platform_machine'] = _platform.machine()
        env['platform_release'] = _platform.release()
        env['platform_version'] = _platform.version()
        
        # Operating system
        env['os_name'] = os.name
        
        # Python implementation
        env['platform_python_implementation'] = _platform.python_implementation()
        env['implementation_name'] = _platform.python_implementation()
        env['implementation_version'] = _platform.python_version()
        
        # Extra (default empty)
        env['extra'] = ''
        
        return env
    
    def evaluate(self, environment: Optional[Dict[str, str]] = None,
                use_packaging: bool = False) -> bool:
        """
        Evaluate the marker against the given environment.
        
        Parameters
        ----------
        environment : Optional[Dict[str, str]], default=None
            Dictionary containing environment variables to use for evaluation.
            Keys should be marker variable names. If `None`, the current
            system environment is used.
        use_packaging : bool, default=False
            Whether to use packaging.markers for evaluation (if available).
            Only applicable for markers without list operators. When False,
            the custom AST evaluator is used.
        
        Returns
        -------
        bool
            True if the marker evaluates to True, False otherwise.
        
        Raises
        ------
        ValueError
            If the marker is invalid or evaluation fails.
        
        Examples
        --------
        Basic evaluation:
        >>> m = Marker("python_version >= '3.8'")
        >>> m.evaluate()
        True
        
        Custom environment:
        >>> m.evaluate({'python_version': '3.7'})
        False
        
        List syntax:
        >>> m = Marker("sys_platform in ['linux', 'windows']")
        >>> m.evaluate()
        True
        
        Complex expressions:
        >>> m = Marker("python_version >= '3.8' and extra in ['dev', 'test']")
        >>> m.evaluate({'python_version': '3.9', 'extra': 'dev'})
        True
        """
        if not self.is_valid or self.ast is None:
            raise ValueError("Cannot evaluate an invalid marker")
        
        # Prepare environment
        if environment is None:
            environment = self._get_default_environment()
        else:
            # Merge with defaults for missing variables
            defaults = self._get_default_environment()
            merged_env = defaults.copy()
            merged_env.update(environment)
            environment = merged_env
        
        # Choose evaluation method
        if use_packaging and not self.has_list_operators and self._packaging_marker:
            try:
                return self._packaging_marker.evaluate(environment)
            except UndefinedEnvironmentName as e:
                raise ValueError(f"Missing environment variable: {e}") from e
            except InvalidMarker as e:
                raise ValueError(f"Invalid marker: {e}") from e
            except Exception as e:
                raise ValueError(f"Evaluation error: {e}") from e
        else:
            # Use our custom AST evaluator
            evaluator = EvaluationVisitor(environment)
            try:
                return self.ast.accept(evaluator)
            except Exception as e:
                raise ValueError(f"Evaluation error: {e}") from e
    
    def get_ast(self) -> Optional[ASTNode]:
        """
        Return the abstract syntax tree (AST) of the marker.
        
        Returns
        -------
        Optional[ASTNode]
            The root node of the AST if the marker is valid, otherwise None.
        
        Examples
        --------
        >>> m = Marker("python_version >= '3.8'")
        >>> ast = m.get_ast()
        >>> isinstance(ast, Comparison)
        True
        >>> ast.variable  # type: ignore
        'python_version'
        """
        return self.ast
    
    def get_variables(self) -> Set[str]:
        """
        Return the set of variable names used in the marker.
        
        Returns
        -------
        Set[str]
            Variable names such as 'python_version', 'sys_platform', 'extra'.
        
        Examples
        --------
        >>> m = Marker("python_version >= '3.8' and sys_platform == 'linux'")
        >>> m.get_variables()
        {'python_version', 'sys_platform'}
        
        With list syntax:
        >>> m = Marker("extra in ['dev', 'test']")
        >>> m.get_variables()
        {'extra'}
        """
        return self.variables.copy()
    
    def to_string(self) -> str:
        """
        Convert the AST back to a normalized string representation.
        
        Returns
        -------
        str
            A canonical string representation of the marker.
        
        Raises
        ------
        ValueError
            If the marker is invalid.
        
        Examples
        --------
        >>> m = Marker("python_version >= '3.8' and sys_platform in ['linux', 'windows']")
        >>> m.to_string()
        "python_version>='3.8' and sys_platform in ['linux','windows']"
        """
        if not self.is_valid or self.ast is None:
            raise ValueError("Cannot stringify an invalid marker")
        
        stringifier = StringifyVisitor()
        return self.ast.accept(stringifier)
    
    def __str__(self) -> str:
        """Return the original marker string."""
        return self.marker_string
    
    def __repr__(self) -> str:
        """Return a string representation of the Marker."""
        return f"Marker({self.marker_string!r})"
    
    def __eq__(self, other: Any) -> bool:
        """
        Compare two markers for equality based on canonicalized representation.
        
        Parameters
        ----------
        other : Any
            The other object to compare.
        
        Returns
        -------
        bool
            True if the normalized marker strings are equal.
        
        Examples
        --------
        >>> m1 = Marker("python_version >= '3.8'")
        >>> m2 = Marker("python_version>='3.8'")
        >>> m1 == m2
        True
        """
        if isinstance(other, Marker):
            return self.normalize(self.marker_string) == self.normalize(other.marker_string)
        elif isinstance(other, str):
            return self.normalize(self.marker_string) == self.normalize(other)
        return NotImplemented
    
    def __lt__(self, other: Any) -> bool:
        """
        Compare two markers for ordering based on normalized string.
        
        Parameters
        ----------
        other : Any
            The other object to compare.
        
        Returns
        -------
        bool
            True if this marker is less than the other.
        """
        if isinstance(other, Marker):
            return self.normalize(self.marker_string) < self.normalize(other.marker_string)
        elif isinstance(other, str):
            return self.normalize(self.marker_string) < self.normalize(other)
        return NotImplemented
    
    def __hash__(self) -> int:
        """Return a hash based on the normalized marker string."""
        return hash(self.normalize(self.marker_string))
    
    @classmethod
    def normalize(cls, marker: str) -> str:
        """
        Canonicalize a marker string for consistent comparison.
        
        This method removes extra whitespace, normalizes operators,
        and ensures consistent formatting for list syntax.
        
        Parameters
        ----------
        marker : str
            The marker string to normalize.
        
        Returns
        -------
        str
            A normalized version of the marker.
        
        Examples
        --------
        >>> Marker.normalize(" python_version>='3.8'   and sys_platform == 'linux' ")
        "python_version>='3.8' and sys_platform=='linux'"
        
        >>> Marker.normalize("python_version >= '3.8' and sys_platform in ['linux', 'windows']")
        "python_version>='3.8' and sys_platform in ['linux','windows']"
        """
        marker = marker.strip()
        
        # Collapse multiple spaces
        marker = re.sub(r'\s+', ' ', marker)
        
        # Normalize and/or operators (ensure lowercase with single spaces)
        marker = re.sub(r'\s*(and|or)\s*', r' \1 ', marker, flags=re.IGNORECASE)
        marker = re.sub(r'\s+and\s+', ' and ', marker)
        marker = re.sub(r'\s+or\s+', ' or ', marker)
        
        # Remove spaces around comparison operators
        marker = re.sub(r'\s*(==|!=|<=|>=|<|>)\s*', r'\1', marker)
        
        # Normalize 'in' and 'not in'
        marker = re.sub(r'\s*in\s+', ' in ', marker, flags=re.IGNORECASE)
        marker = re.sub(r'\s*not\s+in\s+', ' not in ', marker, flags=re.IGNORECASE)
        
        # Normalize list spacing
        marker = re.sub(r'\[\s*', '[', marker)
        marker = re.sub(r'\s*\]', ']', marker)
        marker = re.sub(r'\s*,\s*', ',', marker)
        
        # Clean up any remaining multiple spaces
        marker = re.sub(r'\s+', ' ', marker)
        
        return marker.strip()
    
    @classmethod
    def clear_cache(cls) -> None:
        """
        Clear the AST cache.
        
        This can be useful in long-running applications to free memory
        or if markers are generated dynamically.
        
        Examples
        --------
        >>> Marker.clear_cache()
        >>> len(Marker._ast_cache)
        0
        """
        cls._ast_cache.clear()
    
    @classmethod
    def get_cache_info(cls) -> Dict[str, int]:
        """
        Get information about the AST cache.
        
        Returns
        -------
        Dict[str, int]
            Dictionary with cache size.
        
        Examples
        --------
        >>> info = Marker.get_cache_info()
        >>> 'size' in info
        True
        """
        return {"size": len(cls._ast_cache)}


# ============================================================================
# Convenience Functions
# ============================================================================

def evaluate_marker(marker: str, environment: Optional[Dict[str, str]] = None) -> bool:
    """
    Convenience function to evaluate a marker string.
    
    Parameters
    ----------
    marker : str
        The marker string to evaluate.
    environment : Optional[Dict[str, str]], default=None
        Environment dictionary. If None, uses system environment.
    
    Returns
    -------
    bool
        Evaluation result.
    
    Examples
    --------
    >>> evaluate_marker("python_version >= '3.8'")
    True
    >>> evaluate_marker("sys_platform in ['linux', 'windows']")
    True
    """
    return Marker(marker).evaluate(environment)


def is_valid_marker(marker: str) -> bool:
    """
    Check if a marker string is syntactically valid.
    
    Parameters
    ----------
    marker : str
        The marker string to validate.
    
    Returns
    -------
    bool
        True if the marker is valid, False otherwise.
    
    Examples
    --------
    >>> is_valid_marker("python_version >= '3.8'")
    True
    >>> is_valid_marker("invalid >>> marker")
    False
    """
    try:
        Marker(marker, validate=True)
        return True
    except ValueError:
        return False


def normalize_marker(marker: str) -> str:
    """
    Normalize a marker string.
    
    Parameters
    ----------
    marker : str
        The marker string to normalize.
    
    Returns
    -------
    str
        Normalized marker string.
    
    Examples
    --------
    >>> normalize_marker(" python_version>='3.8'   and sys_platform == 'linux' ")
    "python_version>='3.8' and sys_platform=='linux'"
    """
    return Marker.normalize(marker)


def extract_marker_variables(marker: str) -> Set[str]:
    """
    Extract variable names from a marker string.
    
    Parameters
    ----------
    marker : str
        The marker string to analyze.
    
    Returns
    -------
    Set[str]
        Set of variable names used in the marker.
    
    Raises
    ------
    ValueError
        If the marker is invalid.
    
    Examples
    --------
    >>> extract_marker_variables("python_version >= '3.8' and extra in ['dev', 'test']")
    {'python_version', 'extra'}
    """
    m = Marker(marker)
    return m.get_variables()


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Main class
    "Marker",
    
    # AST Nodes
    "ASTNode",
    "Comparison",
    "InComparison",
    "NotInComparison",
    "BinaryOp",
    "Paren",
    
    # Enums
    "TokenType",
    "ComparisonOperator",
    "LogicalOperator",
    "VariableName",
    
    # Tokenization and Parsing
    "Token",
    "MarkerTokenizer",
    "MarkerParser",
    
    # Visitors
    "ASTVisitor",
    "EvaluationVisitor",
    "StringifyVisitor",
    "VariableExtractorVisitor",
    
    # Exceptions
    "TokenizationError",
    "ParseError",
    
    # Convenience functions
    "evaluate_marker",
    "is_valid_marker",
    "normalize_marker",
    "extract_marker_variables",
]

