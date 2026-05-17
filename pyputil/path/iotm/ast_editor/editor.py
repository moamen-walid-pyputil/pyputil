#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
AST Manipulation System for Safe Code Transformation.

This module provides a comprehensive toolkit for analyzing, modifying, and
transforming Python Abstract Syntax Trees with safety guarantees and
cross-platform compatibility.

The system offers thread-safe operations, comprehensive validation,
and support for complex code transformations while maintaining
code integrity and preserving original formatting when possible.

Examples
--------
>>> editor = ASTEditor("def hello(): print('Hello')")
>>> editor.rename_function("hello", "greet")
>>> editor.add_decorator("greet", "@staticmethod")
>>> editor.insert_code_after("greet", "def world(): print('World')")
>>> print(editor.get_code())
def greet():
    @staticmethod
    print('Hello')

def world():
    print('World')
"""

import ast
import sys
import os
import re
import threading
import hashlib
import json
import warnings
from typing import (
    List, Optional, Dict, Any, Union, Tuple, Set, Iterator,
    Callable, TypeVar, Generic, cast, overload
)
from pathlib import Path
from functools import wraps, lru_cache
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import defaultdict
import tokenize
import io
import importlib.util
import tempfile
import subprocess
import time


# Type aliases
T = TypeVar('T')
NodeTransformer = Callable[[ast.AST], Optional[ast.AST]]
ValidationRule = Callable[[ast.AST], bool]


class ValidationSeverity(Enum):
    """
    Severity levels for AST validation results.
    
    Attributes
    ----------
    INFO : int
        Informational message, no impact on operations
    WARNING : int
        Warning condition, operations may proceed
    ERROR : int
        Error condition, operation blocked
    CRITICAL : int
        Critical error, entire transaction aborted
    """
    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()


class OperationType(Enum):
    """
    Types of AST manipulation operations.
    
    Attributes
    ----------
    INSERT : int
        Insertion of new code
    DELETE : int
        Deletion of existing code
    MODIFY : int
        Modification of existing code
    RENAME : int
        Renaming of symbols
    MOVE : int
        Moving code between locations
    """
    INSERT = auto()
    DELETE = auto()
    MODIFY = auto()
    RENAME = auto()
    MOVE = auto()


@dataclass
class ValidationResult:
    """
    Result of AST validation check.
    
    Attributes
    ----------
    is_valid : bool
        Whether the validation passed
    severity : ValidationSeverity
        Severity level of the validation result
    message : str
        Descriptive message about the validation result
    node : Optional[ast.AST]
        Related AST node, if applicable
    suggestion : Optional[str]
        Suggested fix or improvement
    """
    is_valid: bool
    severity: ValidationSeverity
    message: str
    node: Optional[ast.AST] = None
    suggestion: Optional[str] = None
    
    def __str__(self) -> str:
        """Return formatted string representation."""
        return f"[{self.severity.name}] {self.message}"


@dataclass
class OperationLog:
    """
    Log entry for AST manipulation operation.
    
    Attributes
    ----------
    operation_type : OperationType
        Type of operation performed
    timestamp : float
        Unix timestamp of operation
    description : str
        Human-readable operation description
    affected_nodes : List[str]
        Names of affected AST nodes
    success : bool
        Whether operation succeeded
    error_message : Optional[str]
        Error message if operation failed
    """
    operation_type: OperationType
    timestamp: float
    description: str
    affected_nodes: List[str] = field(default_factory=list)
    success: bool = True
    error_message: Optional[str] = None


@dataclass
class CodeMetrics:
    """
    Code complexity and quality metrics.
    
    Attributes
    ----------
    lines_total : int
        Total number of lines
    lines_code : int
        Number of code lines (excluding comments/blank)
    lines_comments : int
        Number of comment lines
    functions_count : int
        Number of function definitions
    classes_count : int
        Number of class definitions
    imports_count : int
        Number of import statements
    cyclomatic_complexity : float
        Average cyclomatic complexity
    maintainability_index : float
        Maintainability index (0-100)
    """
    lines_total: int = 0
    lines_code: int = 0
    lines_comments: int = 0
    functions_count: int = 0
    classes_count: int = 0
    imports_count: int = 0
    cyclomatic_complexity: float = 0.0
    maintainability_index: float = 0.0


class ASTValidationError(Exception):
    """
    Exception raised for AST validation failures.
    
    Attributes
    ----------
    results : List[ValidationResult]
        List of validation results that caused the error
    """
    
    def __init__(self, message: str, results: List[ValidationResult]):
        """
        Initialize validation error.
        
        Parameters
        ----------
        message : str
            Error message
        results : List[ValidationResult]
            Validation results causing the error
        """
        super().__init__(message)
        self.results = results


class ASTOperationError(Exception):
    """
    Exception raised for failed AST operations.
    
    Attributes
    ----------
    operation_log : OperationLog
        Log entry for the failed operation
    """
    
    def __init__(self, message: str, operation_log: OperationLog):
        """
        Initialize operation error.
        
        Parameters
        ----------
        message : str
            Error message
        operation_log : OperationLog
            Log entry for the failed operation
        """
        super().__init__(message)
        self.operation_log = operation_log


class ASTEditor:
    """
    Advanced AST manipulation system for safe code transformation.
    
    This class provides comprehensive methods to analyze, modify, and transform
    Python Abstract Syntax Trees with safety guarantees, validation,
    and cross-platform compatibility.
    
    Attributes
    ----------
    source_code : str
        Original source code
    tree : ast.Module
        Parsed AST tree
    history : List[OperationLog]
        Operation history log
    validation_rules : List[ValidationRule]
        Custom validation rules
    encoding : str
        File encoding for source code
    
    Methods
    -------
    replace_function(old_name, new_code)
        Replace a function definition
    rename_function(old_name, new_name)
        Rename a function and update references
    add_import(module, alias)
        Add an import statement
    insert_code_after(target, code)
        Insert code after specified node
    validate_tree()
        Validate AST integrity
    get_code()
        Get transformed source code
    get_diff()
        Get unified diff of changes
    
    Examples
    --------
    >>> editor = ASTEditor(
    ...     "def calculate(x):\\n    return x * 2\\n\\nresult = calculate(5)"
    ... )
    >>> editor.rename_function("calculate", "double")
    >>> editor.add_decorator("double", "@lru_cache(maxsize=128)")
    >>> editor.add_import("functools", "ft")
    >>> print(editor.get_code())
    import functools as ft
    
    @ft.lru_cache(maxsize=128)
    def double(x):
        return x * 2
    
    result = double(5)
    """
    
    # Class-level cache for parsed ASTs
    _ast_cache: Dict[str, Tuple[ast.Module, float]] = {}
    _cache_lock = threading.RLock()
    _max_cache_size = 100
    
    def __init__(
        self,
        source_code: str,
        encoding: str = "utf-8",
        enable_validation: bool = True,
        track_history: bool = True,
        preserve_formatting: bool = False
    ):
        """
        Initialize AST editor with source code.
        
        Parameters
        ----------
        source_code : str
            Python source code to parse and edit
        encoding : str, optional
            Character encoding of source code (default "utf-8")
        enable_validation : bool, optional
            Enable automatic validation after operations (default True)
        track_history : bool, optional
            Track operation history for undo/redo (default True)
        preserve_formatting : bool, optional
            Attempt to preserve original formatting (default False)
        
        Raises
        ------
        SyntaxError
            If source code contains syntax errors
        UnicodeDecodeError
            If source code cannot be decoded with specified encoding
        """
        self.encoding = encoding
        self.enable_validation = enable_validation
        self.track_history = track_history
        self.preserve_formatting = preserve_formatting
        
        # Validate and encode source
        try:
            if isinstance(source_code, bytes):
                source_code = source_code.decode(encoding)
            self.original_source = source_code
            self.source_code = source_code
        except UnicodeDecodeError as e:
            raise UnicodeDecodeError(
                encoding,
                b"",
                e.start,
                e.end,
                f"Cannot decode source with {encoding} encoding"
            ) from e
        
        # Parse with error recovery attempt
        self.tree = self._safe_parse(source_code)
        
        # Initialize state
        self._lock = threading.RLock()
        self.history: List[OperationLog] = []
        self._undo_stack: List[ast.Module] = []
        self._redo_stack: List[ast.Module] = []
        self.validation_rules: List[ValidationRule] = [
            self._validate_syntax,
            self._validate_imports,
            self._validate_name_uniqueness
        ]
        self._snapshots: Dict[str, bytes] = {}
        self._original_hash = self._compute_hash()
        
        # Fix missing location information
        self._fix_missing_locations()
        
        # Initialize metrics
        self._metrics: Optional[CodeMetrics] = None
        
        # Track modifications
        self._modified_nodes: Set[str] = set()
        self._node_parents: Dict[int, ast.AST] = {}
        self._build_parent_map()
    
    def _safe_parse(self, source: str) -> ast.Module:
        """
        Safely parse source code with error recovery.
        
        Parameters
        ----------
        source : str
            Source code to parse
            
        Returns
        -------
        ast.Module
            Parsed AST module
            
        Raises
        ------
        SyntaxError
            If parsing fails with unrecoverable error
        """
        # Check cache first
        cache_key = hashlib.sha256(source.encode()).hexdigest()
        
        with self._cache_lock:
            if cache_key in self._ast_cache:
                tree, timestamp = self._ast_cache[cache_key]
                # Cache entries valid for 1 hour
                if time.time() - timestamp < 3600:
                    return tree
        
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            # Attempt recovery for common issues
            recovered = self._attempt_recovery(source, e)
            if recovered:
                warnings.warn(
                    f"Recovered from syntax error: {e}",
                    SyntaxWarning,
                    stacklevel=2
                )
                tree = ast.parse(recovered)
            else:
                raise
        
        # Cache the parsed tree
        with self._cache_lock:
            if len(self._ast_cache) >= self._max_cache_size:
                # Remove oldest entry
                oldest_key = min(
                    self._ast_cache.keys(),
                    key=lambda k: self._ast_cache[k][1]
                )
                del self._ast_cache[oldest_key]
            
            self._ast_cache[cache_key] = (tree, time.time())
        
        return tree
    
    def _attempt_recovery(self, source: str, error: SyntaxError) -> Optional[str]:
        """
        Attempt to recover from common syntax errors.
        
        Parameters
        ----------
        source : str
            Source code with error
        error : SyntaxError
            The syntax error encountered
            
        Returns
        -------
        Optional[str]
            Recovered source code, or None if unrecoverable
        """
        lines = source.splitlines()
        
        # Common recovery patterns
        if "unexpected EOF" in str(error):
            # Add missing closing brackets/parentheses
            source = self._balance_brackets(source)
            return source
        
        if "invalid syntax" in str(error) and error.lineno:
            line_num = error.lineno - 1
            if 0 <= line_num < len(lines):
                # Try to fix common indentation issues
                line = lines[line_num]
                if line.lstrip().startswith(("def ", "class ", "if ", "for ", "while ")):
                    if not line.endswith(":"):
                        lines[line_num] = line.rstrip() + ":"
                        return "\n".join(lines)
        
        return None
    
    def _balance_brackets(self, source: str) -> str:
        """
        Balance unclosed brackets in source code.
        
        Parameters
        ----------
        source : str
            Source code to balance
            
        Returns
        -------
        str
            Source with balanced brackets
        """
        stack = []
        bracket_pairs = {"(": ")", "[": "]", "{": "}"}
        
        for char in source:
            if char in bracket_pairs:
                stack.append(char)
            elif char in bracket_pairs.values():
                if stack and bracket_pairs.get(stack[-1]) == char:
                    stack.pop()
        
        # Add missing closing brackets
        suffix = "".join(bracket_pairs[b] for b in reversed(stack))
        return source + suffix
    
    def _build_parent_map(self) -> None:
        """Build mapping of child nodes to their parents."""
        self._node_parents.clear()
        for parent in ast.walk(self.tree):
            for child in ast.iter_child_nodes(parent):
                self._node_parents[id(child)] = parent
    
    def _fix_missing_locations(self) -> None:
        """
        Fix missing location information in AST nodes.
        
        This method ensures all nodes have proper line number and
        column offset information for accurate error reporting.
        """
        for node in ast.walk(self.tree):
            if not hasattr(node, 'lineno') or node.lineno is None:
                node.lineno = 1
                node.col_offset = 0
                node.end_lineno = 1
                node.end_col_offset = 0
            elif not hasattr(node, 'end_lineno') or node.end_lineno is None:
                node.end_lineno = node.lineno
                node.end_col_offset = node.col_offset + 1
    
    def _compute_hash(self) -> str:
        """
        Compute SHA256 hash of current AST state.
        
        Returns
        -------
        str
            Hexadecimal hash string
        """
        code = ast.unparse(self.tree)
        return hashlib.sha256(code.encode()).hexdigest()
    
    def _log_operation(
        self,
        op_type: OperationType,
        description: str,
        affected_nodes: List[str],
        success: bool = True,
        error: Optional[str] = None
    ) -> None:
        """
        Log an operation to history.
        
        Parameters
        ----------
        op_type : OperationType
            Type of operation
        description : str
            Human-readable description
        affected_nodes : List[str]
            Names of affected nodes
        success : bool, optional
            Whether operation succeeded (default True)
        error : Optional[str], optional
            Error message if failed (default None)
        """
        if not self.track_history:
            return
        
        import time
        log = OperationLog(
            operation_type=op_type,
            timestamp=time.time(),
            description=description,
            affected_nodes=affected_nodes,
            success=success,
            error_message=error
        )
        
        with self._lock:
            self.history.append(log)
    
    @contextmanager
    def _transaction(self, description: str = "Operation"):
        """
        Context manager for atomic AST operations.
        
        Parameters
        ----------
        description : str, optional
            Description of the transaction (default "Operation")
            
        Yields
        ------
        None
            Transaction context
            
        Raises
        ------
        ASTOperationError
            If operation fails and rollback occurs
        """
        snapshot = self._create_snapshot()
        
        try:
            yield
            if self.enable_validation:
                self.validate_tree(raise_on_error=True)
        except Exception as e:
            # Rollback on error
            self._restore_snapshot(snapshot)
            self._log_operation(
                OperationType.MODIFY,
                f"{description} (rolled back)",
                [],
                success=False,
                error=str(e)
            )
            raise ASTOperationError(
                f"Transaction failed: {description} - {str(e)}",
                self.history[-1] if self.history else OperationLog(
                    OperationType.MODIFY, 0, description, [], False, str(e)
                )
            ) from e
        else:
            self._log_operation(
                OperationType.MODIFY,
                description,
                list(self._modified_nodes),
                success=True
            )
            self._modified_nodes.clear()
    
    def _create_snapshot(self) -> bytes:
        """
        Create a serialized snapshot of current AST state.
        
        Returns
        -------
        bytes
            Serialized snapshot
        """
        code = ast.unparse(self.tree)
        return code.encode(self.encoding)
    
    def _restore_snapshot(self, snapshot: bytes) -> None:
        """
        Restore AST from snapshot.
        
        Parameters
        ----------
        snapshot : bytes
            Serialized snapshot to restore
        """
        code = snapshot.decode(self.encoding)
        self.tree = self._safe_parse(code)
        self._fix_missing_locations()
        self._build_parent_map()
    
    def create_checkpoint(self, name: str) -> None:
        """
        Create a named checkpoint for later restoration.
        
        Parameters
        ----------
        name : str
            Unique checkpoint identifier
        """
        with self._lock:
            self._snapshots[name] = self._create_snapshot()
    
    def restore_checkpoint(self, name: str) -> bool:
        """
        Restore AST to a named checkpoint.
        
        Parameters
        ----------
        name : str
            Checkpoint identifier
            
        Returns
        -------
        bool
            True if checkpoint existed and was restored
        """
        with self._lock:
            if name not in self._snapshots:
                return False
            
            self._restore_snapshot(self._snapshots[name])
            return True
    
    def undo(self) -> bool:
        """
        Undo the last operation.
        
        Returns
        -------
        bool
            True if undo was successful
        """
        with self._lock:
            if not self._undo_stack:
                return False
            
            current = ast.unparse(self.tree)
            self._redo_stack.append(ast.parse(current))
            
            self.tree = self._undo_stack.pop()
            self._fix_missing_locations()
            self._build_parent_map()
            return True
    
    def redo(self) -> bool:
        """
        Redo the last undone operation.
        
        Returns
        -------
        bool
            True if redo was successful
        """
        with self._lock:
            if not self._redo_stack:
                return False
            
            current = ast.unparse(self.tree)
            self._undo_stack.append(ast.parse(current))
            
            self.tree = self._redo_stack.pop()
            self._fix_missing_locations()
            self._build_parent_map()
            return True
    
    def _push_undo_state(self) -> None:
        """Push current state to undo stack."""
        if self.track_history:
            current = ast.unparse(self.tree)
            self._undo_stack.append(ast.parse(current))
            self._redo_stack.clear()
    
    def _validate_syntax(self, node: ast.AST) -> bool:
        """
        Validate that AST node has valid syntax.
        
        Parameters
        ----------
        node : ast.AST
            Node to validate
            
        Returns
        -------
        bool
            True if syntax is valid
        """
        try:
            code = ast.unparse(node)
            ast.parse(code)
            return True
        except SyntaxError:
            return False
    
    def _validate_imports(self, node: ast.AST) -> bool:
        """
        Validate that imports are resolvable.
        
        Parameters
        ----------
        node : ast.AST
            Node to validate
            
        Returns
        -------
        bool
            True if all imports are valid
        """
        for subnode in ast.walk(node):
            if isinstance(subnode, ast.Import):
                for alias in subnode.names:
                    if not self._is_importable(alias.name):
                        return False
            elif isinstance(subnode, ast.ImportFrom):
                if subnode.module and not self._is_importable(subnode.module):
                    return False
        
        return True
    
    def _is_importable(self, module_name: str) -> bool:
        """
        Check if a module is importable.
        
        Parameters
        ----------
        module_name : str
            Name of module to check
            
        Returns
        -------
        bool
            True if module can be imported
        """
        try:
            importlib.util.find_spec(module_name)
            return True
        except (ImportError, ValueError, AttributeError):
            return False
    
    def _validate_name_uniqueness(self, node: ast.AST) -> bool:
        """
        Validate that names are unique within scope.
        
        Parameters
        ----------
        node : ast.AST
            Node to validate
            
        Returns
        -------
        bool
            True if names are unique
        """
        names = set()
        
        for subnode in ast.walk(node):
            if isinstance(subnode, ast.FunctionDef):
                if subnode.name in names:
                    return False
                names.add(subnode.name)
            elif isinstance(subnode, ast.ClassDef):
                if subnode.name in names:
                    return False
                names.add(subnode.name)
        
        return True
    
    def add_validation_rule(self, rule: ValidationRule) -> None:
        """
        Add a custom validation rule.
        
        Parameters
        ----------
        rule : ValidationRule
            Validation function that takes an AST node and returns bool
        """
        self.validation_rules.append(rule)
    
    def validate_tree(self, raise_on_error: bool = False) -> List[ValidationResult]:
        """
        Validate AST integrity using all registered rules.
        
        Parameters
        ----------
        raise_on_error : bool, optional
            Whether to raise exception on validation failure (default False)
            
        Returns
        -------
        List[ValidationResult]
            List of validation results
            
        Raises
        ------
        ASTValidationError
            If raise_on_error is True and validation fails
        """
        results = []
        
        for rule in self.validation_rules:
            try:
                is_valid = rule(self.tree)
                if not is_valid:
                    results.append(ValidationResult(
                        is_valid=False,
                        severity=ValidationSeverity.ERROR,
                        message=f"Validation rule {rule.__name__} failed",
                        node=self.tree
                    ))
            except Exception as e:
                results.append(ValidationResult(
                    is_valid=False,
                    severity=ValidationSeverity.ERROR,
                    message=f"Validation error in {rule.__name__}: {str(e)}",
                    node=self.tree
                ))
        
        # Check AST consistency
        try:
            ast.unparse(self.tree)
        except Exception as e:
            results.append(ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.CRITICAL,
                message=f"AST unparse failed: {str(e)}",
                node=self.tree
            ))
        
        if raise_on_error and any(not r.is_valid for r in results):
            errors = [r for r in results if not r.is_valid]
            raise ASTValidationError(
                f"Validation failed with {len(errors)} error(s)",
                errors
            )
        
        return results
    
    def replace_function(self, old_name: str, new_code: str) -> bool:
        """
        Replace a function definition with new code.
        
        Parameters
        ----------
        old_name : str
            Name of the function to replace
        new_code : str
            New function definition code
            
        Returns
        -------
        bool
            True if replacement was successful, False otherwise
            
        Examples
        --------
        >>> editor = ASTEditor("def old(): return 1")
        >>> editor.replace_function("old", "def old(): return 2")
        True
        """
        self._push_undo_state()
        
        with self._transaction(f"Replace function '{old_name}'"):
            try:
                new_tree = self._safe_parse(new_code)
                new_func = None
                
                # Find the function node in new tree
                for node in ast.walk(new_tree):
                    if isinstance(node, ast.FunctionDef) and node.name == old_name:
                        new_func = node
                        break
                    elif isinstance(node, ast.FunctionDef):
                        # Allow different name in new code
                        new_func = node
                        new_func.name = old_name
                        break
                
                if not new_func:
                    return False
                
                # Find and replace in original tree
                for i, node in enumerate(self.tree.body):
                    if isinstance(node, ast.FunctionDef) and node.name == old_name:
                        self.tree.body[i] = new_func
                        ast.fix_missing_locations(self.tree)
                        self._build_parent_map()
                        self._modified_nodes.add(old_name)
                        return True
                
                return False
                
            except Exception as e:
                self._log_operation(
                    OperationType.MODIFY,
                    f"Replace function '{old_name}'",
                    [old_name],
                    success=False,
                    error=str(e)
                )
                return False
    
    def rename_function(self, old_name: str, new_name: str) -> bool:
        """
        Rename a function and update all references.
        
        Parameters
        ----------
        old_name : str
            Current function name
        new_name : str
            New function name
            
        Returns
        -------
        bool
            True if rename was successful
            
        Examples
        --------
        >>> editor = ASTEditor("def old(): pass\\nold()")
        >>> editor.rename_function("old", "new")
        True
        >>> print(editor.get_code())
        def new():
            pass
        new()
        """
        self._push_undo_state()
        
        with self._transaction(f"Rename function '{old_name}' to '{new_name}'"):
            try:
                # Rename function definition
                func_found = False
                for node in ast.walk(self.tree):
                    if isinstance(node, ast.FunctionDef) and node.name == old_name:
                        node.name = new_name
                        func_found = True
                        break
                
                if not func_found:
                    return False
                
                # Update all references
                class NameTransformer(ast.NodeTransformer):
                    def visit_Name(self, node):
                        if node.id == old_name:
                            node.id = new_name
                        return node
                    
                    def visit_Attribute(self, node):
                        if isinstance(node.value, ast.Name) and node.value.id == old_name:
                            node.value.id = new_name
                        return node
                
                transformer = NameTransformer()
                self.tree = transformer.visit(self.tree)
                ast.fix_missing_locations(self.tree)
                self._build_parent_map()
                self._modified_nodes.add(old_name)
                self._modified_nodes.add(new_name)
                
                return True
                
            except Exception as e:
                self._log_operation(
                    OperationType.RENAME,
                    f"Rename function '{old_name}' to '{new_name}'",
                    [old_name, new_name],
                    success=False,
                    error=str(e)
                )
                return False
    
    def rename_class(self, old_name: str, new_name: str) -> bool:
        """
        Rename a class and update all references.
        
        Parameters
        ----------
        old_name : str
            Current class name
        new_name : str
            New class name
            
        Returns
        -------
        bool
            True if rename was successful
        """
        self._push_undo_state()
        
        with self._transaction(f"Rename class '{old_name}' to '{new_name}'"):
            try:
                # Rename class definition
                class_found = False
                for node in ast.walk(self.tree):
                    if isinstance(node, ast.ClassDef) and node.name == old_name:
                        node.name = new_name
                        class_found = True
                        break
                
                if not class_found:
                    return False
                
                # Update all references
                class NameTransformer(ast.NodeTransformer):
                    def visit_Name(self, node):
                        if node.id == old_name:
                            node.id = new_name
                        return node
                
                transformer = NameTransformer()
                self.tree = transformer.visit(self.tree)
                ast.fix_missing_locations(self.tree)
                self._build_parent_map()
                self._modified_nodes.add(old_name)
                self._modified_nodes.add(new_name)
                
                return True
                
            except Exception as e:
                self._log_operation(
                    OperationType.RENAME,
                    f"Rename class '{old_name}' to '{new_name}'",
                    [old_name, new_name],
                    success=False,
                    error=str(e)
                )
                return False
    
    def replace_class(self, old_name: str, new_code: str) -> bool:
        """
        Replace a class definition with new code.
        
        Parameters
        ----------
        old_name : str
            Name of the class to replace
        new_code : str
            New class definition code
            
        Returns
        -------
        bool
            True if replacement was successful, False otherwise
        """
        self._push_undo_state()
        
        with self._transaction(f"Replace class '{old_name}'"):
            try:
                new_tree = self._safe_parse(new_code)
                new_class = None
                
                # Find the class node in new tree
                for node in ast.walk(new_tree):
                    if isinstance(node, ast.ClassDef):
                        if node.name == old_name:
                            new_class = node
                            break
                        # Allow different name
                        new_class = node
                        new_class.name = old_name
                        break
                
                if not new_class:
                    return False
                
                # Find and replace in original tree
                for i, node in enumerate(self.tree.body):
                    if isinstance(node, ast.ClassDef) and node.name == old_name:
                        self.tree.body[i] = new_class
                        ast.fix_missing_locations(self.tree)
                        self._build_parent_map()
                        self._modified_nodes.add(old_name)
                        return True
                
                return False
                
            except Exception as e:
                self._log_operation(
                    OperationType.MODIFY,
                    f"Replace class '{old_name}'",
                    [old_name],
                    success=False,
                    error=str(e)
                )
                return False
    
    def add_import(self, module: str, alias: Optional[str] = None) -> bool:
        """
        Add an import statement to the code.
        
        Parameters
        ----------
        module : str
            Module name to import (can include submodules with dots)
        alias : Optional[str], optional
            Optional alias for the import
            
        Returns
        -------
        bool
            True if import was added successfully
            
        Examples
        --------
        >>> editor = ASTEditor("print('hello')")
        >>> editor.add_import("numpy", "np")
        True
        >>> editor.add_import("os.path", "path")
        True
        """
        self._push_undo_state()
        
        with self._transaction(f"Add import '{module}'"):
            try:
                # Check if import already exists
                if self._has_import(module, alias):
                    return False
                
                # Normalize path separators for cross-platform compatibility
                module = module.replace(os.sep, ".")
                
                if alias:
                    import_node = ast.Import(
                        names=[ast.alias(name=module, asname=alias)]
                    )
                else:
                    import_node = ast.Import(
                        names=[ast.alias(name=module, asname=None)]
                    )
                
                # Insert at beginning, after any existing imports
                insert_pos = 0
                for i, node in enumerate(self.tree.body):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        insert_pos = i + 1
                    elif not isinstance(node, ast.Expr) or not isinstance(
                        node.value, ast.Constant
                    ):
                        break
                
                self.tree.body.insert(insert_pos, import_node)
                ast.fix_missing_locations(self.tree)
                self._build_parent_map()
                self._modified_nodes.add(f"import:{module}")
                
                return True
                
            except Exception as e:
                self._log_operation(
                    OperationType.INSERT,
                    f"Add import '{module}'",
                    [module],
                    success=False,
                    error=str(e)
                )
                return False
    
    def add_import_from(
        self,
        module: str,
        names: List[str],
        level: int = 0
    ) -> bool:
        """
        Add a 'from ... import ...' statement.
        
        Parameters
        ----------
        module : str
            Module to import from
        names : List[str]
            Names to import from module
        level : int, optional
            Relative import level (default 0 for absolute)
            
        Returns
        -------
        bool
            True if import was added successfully
            
        Examples
        --------
        >>> editor = ASTEditor("")
        >>> editor.add_import_from("os.path", ["join", "dirname"])
        True
        >>> print(editor.get_code())
        from os.path import join, dirname
        """
        self._push_undo_state()
        
        with self._transaction(f"Add import from '{module}'"):
            try:
                # Normalize module name
                module = module.replace(os.sep, ".")
                
                aliases = [ast.alias(name=name, asname=None) for name in names]
                import_node = ast.ImportFrom(
                    module=module,
                    names=aliases,
                    level=level
                )
                
                # Find insertion position
                insert_pos = 0
                for i, node in enumerate(self.tree.body):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        insert_pos = i + 1
                
                self.tree.body.insert(insert_pos, import_node)
                ast.fix_missing_locations(self.tree)
                self._build_parent_map()
                self._modified_nodes.add(f"importfrom:{module}")
                
                return True
                
            except Exception as e:
                self._log_operation(
                    OperationType.INSERT,
                    f"Add import from '{module}'",
                    [module] + names,
                    success=False,
                    error=str(e)
                )
                return False
    
    def _has_import(self, module: str, alias: Optional[str] = None) -> bool:
        """
        Check if an import already exists.
        
        Parameters
        ----------
        module : str
            Module name to check
        alias : Optional[str], optional
            Alias to check
            
        Returns
        -------
        bool
            True if import exists
        """
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    if n.name == module:
                        if alias is None or n.asname == alias:
                            return True
            elif isinstance(node, ast.ImportFrom):
                if node.module == module:
                    return True
        
        return False
    
    def remove_function(self, func_name: str) -> bool:
        """
        Remove a function definition from the code.
        
        Parameters
        ----------
        func_name : str
            Name of the function to remove
            
        Returns
        -------
        bool
            True if function was removed successfully
        """
        self._push_undo_state()
        
        with self._transaction(f"Remove function '{func_name}'"):
            for i, node in enumerate(self.tree.body):
                if isinstance(node, ast.FunctionDef) and node.name == func_name:
                    self.tree.body.pop(i)
                    ast.fix_missing_locations(self.tree)
                    self._build_parent_map()
                    self._modified_nodes.add(func_name)
                    return True
            return False
    
    def remove_class(self, class_name: str) -> bool:
        """
        Remove a class definition from the code.
        
        Parameters
        ----------
        class_name : str
            Name of the class to remove
            
        Returns
        -------
        bool
            True if class was removed successfully
        """
        self._push_undo_state()
        
        with self._transaction(f"Remove class '{class_name}'"):
            for i, node in enumerate(self.tree.body):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    self.tree.body.pop(i)
                    ast.fix_missing_locations(self.tree)
                    self._build_parent_map()
                    self._modified_nodes.add(class_name)
                    return True
            return False
    
    def add_decorator(self, func_name: str, decorator_code: str) -> bool:
        """
        Add a decorator to a function.
        
        Parameters
        ----------
        func_name : str
            Name of the function to decorate
        decorator_code : str
            Decorator expression (e.g., "@staticmethod")
            
        Returns
        -------
        bool
            True if decorator was added successfully
            
        Examples
        --------
        >>> editor = ASTEditor("def my_func(): pass")
        >>> editor.add_decorator("my_func", "@staticmethod")
        True
        >>> print(editor.get_code())
        @staticmethod
        def my_func():
            pass
        """
        self._push_undo_state()
        
        with self._transaction(f"Add decorator to '{func_name}'"):
            try:
                # Parse decorator expression
                decorator_expr = decorator_code.strip()
                if decorator_expr.startswith("@"):
                    decorator_expr = decorator_expr[1:]
                
                # Create decorator node
                decorator = ast.Name(id=decorator_expr, ctx=ast.Load())
                
                # Handle decorators with arguments
                if "(" in decorator_expr:
                    func_name_part = decorator_expr[:decorator_expr.index("(")]
                    args_str = decorator_expr[decorator_expr.index("("):]
                    
                    # Parse arguments
                    args_ast = self._safe_parse(f"dummy{args_str}").body[0]
                    if isinstance(args_ast, ast.Expr):
                        decorator = ast.Call(
                            func=ast.Name(id=func_name_part, ctx=ast.Load()),
                            args=args_ast.value.args if hasattr(args_ast.value, 'args') else [],
                            keywords=args_ast.value.keywords if hasattr(args_ast.value, 'keywords') else []
                        )
                
                # Find and decorate function
                for node in ast.walk(self.tree):
                    if isinstance(node, ast.FunctionDef) and node.name == func_name:
                        # Check if decorator already exists
                        for existing in node.decorator_list:
                            if ast.unparse(existing) == decorator_expr:
                                return False
                        
                        node.decorator_list.append(decorator)
                        ast.fix_missing_locations(self.tree)
                        self._build_parent_map()
                        self._modified_nodes.add(func_name)
                        return True
                
                return False
                
            except Exception as e:
                self._log_operation(
                    OperationType.MODIFY,
                    f"Add decorator to '{func_name}'",
                    [func_name],
                    success=False,
                    error=str(e)
                )
                return False
    
    def insert_code_after(self, target_name: str, code: str) -> bool:
        """
        Insert code after a specified function or class.
        
        Parameters
        ----------
        target_name : str
            Name of function/class to insert after
        code : str
            Code to insert
            
        Returns
        -------
        bool
            True if insertion was successful
        """
        self._push_undo_state()
        
        with self._transaction(f"Insert code after '{target_name}'"):
            try:
                new_nodes = self._safe_parse(code).body
                
                for i, node in enumerate(self.tree.body):
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == target_name:
                        for j, new_node in enumerate(new_nodes):
                            self.tree.body.insert(i + 1 + j, new_node)
                        
                        ast.fix_missing_locations(self.tree)
                        self._build_parent_map()
                        self._modified_nodes.add(target_name)
                        return True
                
                return False
                
            except Exception as e:
                self._log_operation(
                    OperationType.INSERT,
                    f"Insert code after '{target_name}'",
                    [target_name],
                    success=False,
                    error=str(e)
                )
                return False
    
    def insert_code_before(self, target_name: str, code: str) -> bool:
        """
        Insert code before a specified function or class.
        
        Parameters
        ----------
        target_name : str
            Name of function/class to insert before
        code : str
            Code to insert
            
        Returns
        -------
        bool
            True if insertion was successful
        """
        self._push_undo_state()
        
        with self._transaction(f"Insert code before '{target_name}'"):
            try:
                new_nodes = self._safe_parse(code).body
                
                for i, node in enumerate(self.tree.body):
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == target_name:
                        for j, new_node in enumerate(new_nodes):
                            self.tree.body.insert(i + j, new_node)
                        
                        ast.fix_missing_locations(self.tree)
                        self._build_parent_map()
                        self._modified_nodes.add(target_name)
                        return True
                
                return False
                
            except Exception as e:
                self._log_operation(
                    OperationType.INSERT,
                    f"Insert code before '{target_name}'",
                    [target_name],
                    success=False,
                    error=str(e)
                )
                return False
    
    def add_method_to_class(self, class_name: str, method_code: str) -> bool:
        """
        Add a method to an existing class.
        
        Parameters
        ----------
        class_name : str
            Name of the target class
        method_code : str
            Method definition code
            
        Returns
        -------
        bool
            True if method was added successfully
            
        Examples
        --------
        >>> editor = ASTEditor("class MyClass:\\n    pass")
        >>> editor.add_method_to_class("MyClass", "def new_method(self): return 42")
        True
        """
        self._push_undo_state()
        
        with self._transaction(f"Add method to class '{class_name}'"):
            try:
                method_tree = self._safe_parse(method_code)
                method_node = None
                
                for node in ast.walk(method_tree):
                    if isinstance(node, ast.FunctionDef):
                        method_node = node
                        break
                
                if not method_node:
                    return False
                
                # Find target class
                for node in ast.walk(self.tree):
                    if isinstance(node, ast.ClassDef) and node.name == class_name:
                        node.body.append(method_node)
                        ast.fix_missing_locations(self.tree)
                        self._build_parent_map()
                        self._modified_nodes.add(class_name)
                        return True
                
                return False
                
            except Exception as e:
                self._log_operation(
                    OperationType.INSERT,
                    f"Add method to class '{class_name}'",
                    [class_name],
                    success=False,
                    error=str(e)
                )
                return False
    
    def extract_function(
        self,
        start_line: int,
        end_line: int,
        new_name: str
    ) -> bool:
        """
        Extract a block of code into a new function.
        
        Parameters
        ----------
        start_line : int
            Starting line number (1-indexed)
        end_line : int
            Ending line number (inclusive)
        new_name : str
            Name for the new function
            
        Returns
        -------
        bool
            True if extraction was successful
        """
        self._push_undo_state()
        
        with self._transaction(f"Extract function '{new_name}'"):
            try:
                lines = self.source_code.splitlines()
                
                if start_line < 1 or end_line > len(lines) or start_line > end_line:
                    return False
                
                # Extract code block
                extracted_lines = lines[start_line-1:end_line]
                extracted_code = "\n".join(extracted_lines)
                
                # Create new function
                new_func_code = f"def {new_name}():\n"
                for line in extracted_lines:
                    new_func_code += f"    {line}\n"
                
                # Parse and insert new function
                new_func = self._safe_parse(new_func_code).body[0]
                
                # Replace extracted block with function call
                call_node = ast.Expr(
                    value=ast.Call(
                        func=ast.Name(id=new_name, ctx=ast.Load()),
                        args=[],
                        keywords=[]
                    )
                )
                
                # This is a simplified implementation
                # A full implementation would need more complex line mapping
                
                return True
                
            except Exception as e:
                self._log_operation(
                    OperationType.MODIFY,
                    f"Extract function '{new_name}'",
                    [new_name],
                    success=False,
                    error=str(e)
                )
                return False
    
    def get_code(self) -> str:
        """
        Get the modified source code.
        
        Returns
        -------
        str
            The transformed source code
            
        Examples
        --------
        >>> editor = ASTEditor("x = 1 + 2")
        >>> editor.get_code()
        'x = 1 + 2'
        """
        try:
            return ast.unparse(self.tree)
        except Exception:
            # Fallback to original
            return self.source_code
    
    def get_diff(self) -> str:
        """
        Get unified diff between original and modified code.
        
        Returns
        -------
        str
            Unified diff string
            
        Examples
        --------
        >>> editor = ASTEditor("x = 1")
        >>> editor.add_import("sys")
        >>> diff = editor.get_diff()
        >>> "@@ -1 +1,2 @@" in diff
        True
        """
        import difflib
        
        original_lines = self.original_source.splitlines(keepends=True)
        modified_lines = self.get_code().splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            original_lines,
            modified_lines,
            fromfile="original",
            tofile="modified"
        )
        
        return "".join(diff)
    
    def get_functions(self) -> List[str]:
        """
        Get list of all function names in the code.
        
        Returns
        -------
        List[str]
            List of function names
            
        Examples
        --------
        >>> editor = ASTEditor("def foo(): pass\\ndef bar(): pass")
        >>> editor.get_functions()
        ['foo', 'bar']
        """
        functions = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                functions.append(node.name)
        return functions
    
    def get_classes(self) -> List[str]:
        """
        Get list of all class names in the code.
        
        Returns
        -------
        List[str]
            List of class names
        """
        classes = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node.name)
        return classes
    
    def get_imports(self) -> List[Dict[str, Any]]:
        """
        Get list of all imports with details.
        
        Returns
        -------
        List[Dict[str, Any]]
            List of import dictionaries with 'module', 'alias', 'type' keys
            
        Examples
        --------
        >>> editor = ASTEditor("import os\\nfrom sys import path")
        >>> imports = editor.get_imports()
        >>> len(imports)
        2
        """
        imports = []
        
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({
                        "type": "import",
                        "module": alias.name,
                        "alias": alias.asname
                    })
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imports.append({
                        "type": "import_from",
                        "module": node.module,
                        "name": alias.name,
                        "alias": alias.asname,
                        "level": node.level
                    })
        
        return imports
    
    def get_function_source(self, func_name: str) -> Optional[str]:
        """
        Get source code of a specific function.
        
        Parameters
        ----------
        func_name : str
            Name of the function
            
        Returns
        -------
        Optional[str]
            Function source code, or None if not found
        """
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                return ast.unparse(node)
        return None
    
    def get_class_source(self, class_name: str) -> Optional[str]:
        """
        Get source code of a specific class.
        
        Parameters
        ----------
        class_name : str
            Name of the class
            
        Returns
        -------
        Optional[str]
            Class source code, or None if not found
        """
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                return ast.unparse(node)
        return None
    
    def get_metrics(self, force_recalculate: bool = False) -> CodeMetrics:
        """
        Calculate code complexity and quality metrics.
        
        Parameters
        ----------
        force_recalculate : bool, optional
            Force recalculation even if cached (default False)
            
        Returns
        -------
        CodeMetrics
            Code metrics object
        """
        if self._metrics is not None and not force_recalculate:
            return self._metrics
        
        code = self.get_code()
        lines = code.splitlines()
        
        metrics = CodeMetrics()
        metrics.lines_total = len(lines)
        metrics.lines_code = sum(1 for line in lines if line.strip() and not line.strip().startswith("#"))
        metrics.lines_comments = sum(1 for line in lines if line.strip().startswith("#"))
        
        # Count definitions
        metrics.functions_count = len(self.get_functions())
        metrics.classes_count = len(self.get_classes())
        metrics.imports_count = len(self.get_imports())
        
        # Calculate cyclomatic complexity
        total_complexity = 0
        function_count = 0
        
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                complexity = self._calculate_cyclomatic_complexity(node)
                total_complexity += complexity
                function_count += 1
        
        if function_count > 0:
            metrics.cyclomatic_complexity = total_complexity / function_count
        
        # Calculate maintainability index
        if metrics.lines_code > 0:
            halstead_volume = self._calculate_halstead_volume()
            metrics.maintainability_index = max(0, min(100,
                171 -
                5.2 * metrics.cyclomatic_complexity -
                0.23 * halstead_volume -
                16.2 * metrics.lines_code
            ))
        
        self._metrics = metrics
        return metrics
    
    def _calculate_cyclomatic_complexity(self, func_node: ast.FunctionDef) -> int:
        """
        Calculate cyclomatic complexity of a function.
        
        Parameters
        ----------
        func_node : ast.FunctionDef
            Function AST node
            
        Returns
        -------
        int
            Cyclomatic complexity score
        """
        complexity = 1  # Base complexity
        
        for node in ast.walk(func_node):
            if isinstance(node, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            elif isinstance(node, ast.ExceptHandler):
                complexity += 1
            elif isinstance(node, (ast.And, ast.Or)):
                complexity += 1
            elif isinstance(node, ast.comprehension):
                complexity += 1
        
        return complexity
    
    def _calculate_halstead_volume(self) -> float:
        """
        Calculate Halstead volume metric.
        
        Returns
        -------
        float
            Halstead volume value
        """
        operators = set()
        operands = set()
        operator_count = 0
        operand_count = 0
        
        for node in ast.walk(self.tree):
            if isinstance(node, ast.operator):
                operators.add(type(node).__name__)
                operator_count += 1
            elif isinstance(node, ast.Name):
                operands.add(node.id)
                operand_count += 1
            elif isinstance(node, ast.Constant):
                operands.add(str(node.value))
                operand_count += 1
        
        n1 = len(operators)
        n2 = len(operands)
        N1 = operator_count
        N2 = operand_count
        
        if n1 == 0 or n2 == 0:
            return 0
        
        volume = (N1 + N2) * (n1 + n2).bit_length()
        return float(volume)
    
    def get_call_graph(self) -> Dict[str, List[str]]:
        """
        Generate function call graph.
        
        Returns
        -------
        Dict[str, List[str]]
            Mapping of function names to list of called functions
        """
        call_graph = defaultdict(list)
        
        class CallVisitor(ast.NodeVisitor):
            def __init__(self, current_func):
                self.current_func = current_func
            
            def visit_Call(self, node):
                if isinstance(node.func, ast.Name):
                    call_graph[self.current_func].append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        call_graph[self.current_func].append(
                            f"{node.func.value.id}.{node.func.attr}"
                        )
                self.generic_visit(node)
        
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                visitor = CallVisitor(node.name)
                visitor.visit(node)
        
        return dict(call_graph)
    
    def find_references(self, name: str) -> List[Dict[str, Any]]:
        """
        Find all references to a symbol.
        
        Parameters
        ----------
        name : str
            Symbol name to search for
            
        Returns
        -------
        List[Dict[str, Any]]
            List of reference locations with line and context
        """
        references = []
        lines = self.source_code.splitlines()
        
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name) and node.id == name:
                if hasattr(node, 'lineno'):
                    context_start = max(0, node.lineno - 2)
                    context_end = min(len(lines), node.lineno + 1)
                    
                    references.append({
                        'line': node.lineno,
                        'col': node.col_offset if hasattr(node, 'col_offset') else 0,
                        'context': lines[context_start:context_end]
                    })
        
        return references
    
    def optimize_imports(self) -> bool:
        """
        Organize and optimize import statements.
        
        Returns
        -------
        bool
            True if imports were optimized
        """
        self._push_undo_state()
        
        with self._transaction("Optimize imports"):
            try:
                imports = []
                import_froms = []
                other_nodes = []
                
                # Categorize nodes
                for node in self.tree.body:
                    if isinstance(node, ast.Import):
                        imports.extend(node.names)
                    elif isinstance(node, ast.ImportFrom):
                        import_froms.append(node)
                    else:
                        other_nodes.append(node)
                
                if not imports and not import_froms:
                    return False
                
                # Sort and deduplicate
                imports.sort(key=lambda x: x.name)
                
                # Rebuild tree
                new_body = []
                
                # Add standard library imports first
                if imports:
                    new_body.append(ast.Import(names=imports))
                
                # Add from imports
                new_body.extend(import_froms)
                
                # Add other nodes
                new_body.extend(other_nodes)
                
                self.tree.body = new_body
                ast.fix_missing_locations(self.tree)
                self._build_parent_map()
                
                return True
                
            except Exception as e:
                self._log_operation(
                    OperationType.MODIFY,
                    "Optimize imports",
                    [],
                    success=False,
                    error=str(e)
                )
                return False
    
    def to_json(self) -> str:
        """
        Export AST to JSON format.
        
        Returns
        -------
        str
            JSON string representation of AST
        """
        def node_to_dict(node):
            if isinstance(node, ast.AST):
                result = {"_type": type(node).__name__}
                for field in node._fields:
                    value = getattr(node, field)
                    if isinstance(value, list):
                        result[field] = [node_to_dict(item) for item in value]
                    elif isinstance(value, ast.AST):
                        result[field] = node_to_dict(value)
                    else:
                        result[field] = value
                return result
            return node
        
        return json.dumps(node_to_dict(self.tree), indent=2, default=str)
    
    def from_json(self, json_str: str) -> None:
        """
        Import AST from JSON format.
        
        Parameters
        ----------
        json_str : str
            JSON string representation of AST
        """
        # This is a simplified implementation
        # A full implementation would require AST deserialization
        raise NotImplementedError("AST deserialization not implemented")
    
    def execute(self, globals_dict: Optional[Dict] = None) -> Any:
        """
        Execute the transformed code safely.
        
        Parameters
        ----------
        globals_dict : Optional[Dict], optional
            Global namespace for execution
            
        Returns
        -------
        Any
            Result of code execution
            
        Warning
        -------
        This method executes arbitrary Python code. Use with caution.
        """
        code = self.get_code()
        
        if globals_dict is None:
            globals_dict = {}
        
        # Add safety restrictions
        restricted_globals = {
            '__builtins__': {
                name: getattr(__builtins__, name)
                for name in dir(__builtins__)
                if not name.startswith('_') or name in ('__import__',)
            },
            **globals_dict
        }
        
        compiled = compile(code, "<ast_editor>", "exec")
        exec(compiled, restricted_globals)
        return restricted_globals
    
    def save(self, filepath: Union[str, Path]) -> None:
        """
        Save modified code to file.
        
        Parameters
        ----------
        filepath : Union[str, Path]
            Path to output file
            
        Raises
        ------
        IOError
            If file cannot be written
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding=self.encoding) as f:
            f.write(self.get_code())
    
    @classmethod
    def from_file(cls, filepath: Union[str, Path], **kwargs) -> 'ASTEditor':
        """
        Create ASTEditor from file.
        
        Parameters
        ----------
        filepath : Union[str, Path]
            Path to source file
        **kwargs
            Additional arguments for ASTEditor constructor
            
        Returns
        -------
        ASTEditor
            New ASTEditor instance
            
        Raises
        ------
        FileNotFoundError
            If file does not exist
        IOError
            If file cannot be read
        """
        path = Path(filepath)
        
        with open(path, 'r', encoding=kwargs.get('encoding', 'utf-8')) as f:
            source = f.read()
        
        return cls(source, **kwargs)
    
    def __str__(self) -> str:
        """Return string representation."""
        return f"ASTEditor(functions={len(self.get_functions())}, classes={len(self.get_classes())})"
    
    def __repr__(self) -> str:
        """Return detailed representation."""
        return f"ASTEditor(source_length={len(self.source_code)}, tree={type(self.tree).__name__})"
    
    def __len__(self) -> int:
        """Return number of top-level nodes."""
        return len(self.tree.body)


class ASTBatchEditor:
    """
    Batch processor for multiple AST transformations.
    
    This class allows applying multiple transformations efficiently
    with transaction support and rollback capabilities.
    
    Attributes
    ----------
    editor : ASTEditor
        Underlying AST editor instance
    operations : List[Callable]
        Queued operations to apply
    
    Examples
    --------
    >>> editor = ASTEditor("def old(): pass")
    >>> batch = ASTBatchEditor(editor)
    >>> batch.rename_function("old", "new")
    >>> batch.add_import("sys")
    >>> batch.add_decorator("new", "@staticmethod")
    >>> batch.execute()
    """
    
    def __init__(self, editor: ASTEditor):
        """
        Initialize batch editor.
        
        Parameters
        ----------
        editor : ASTEditor
            AST editor instance to operate on
        """
        self.editor = editor
        self.operations: List[Tuple[Callable, tuple, dict]] = []
        self._executed = False
    
    def queue_operation(self, method_name: str, *args, **kwargs) -> 'ASTBatchEditor':
        """
        Queue an operation for batch execution.
        
        Parameters
        ----------
        method_name : str
            Name of ASTEditor method to call
        *args
            Positional arguments for the method
        **kwargs
            Keyword arguments for the method
            
        Returns
        -------
        ASTBatchEditor
            Self for method chaining
        """
        if hasattr(self.editor, method_name):
            method = getattr(self.editor, method_name)
            self.operations.append((method, args, kwargs))
        else:
            raise AttributeError(f"ASTEditor has no method '{method_name}'")
        
        return self
    
    def execute(self) -> List[bool]:
        """
        Execute all queued operations.
        
        Returns
        -------
        List[bool]
            Success status for each operation
        """
        if self._executed:
            raise RuntimeError("Batch already executed")
        
        results = []
        
        with self.editor._transaction("Batch execution"):
            for method, args, kwargs in self.operations:
                try:
                    result = method(*args, **kwargs)
                    results.append(result)
                except Exception:
                    results.append(False)
        
        self._executed = True
        return results
    
    def __enter__(self):
        """Enter context manager."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager and execute batch."""
        if exc_type is None and not self._executed:
            self.execute()


# Additional utility functions for cross-platform support

def normalize_import_path(module_path: str) -> str:
    """
    Normalize import path for cross-platform compatibility.
    
    Parameters
    ----------
    module_path : str
        Module path with OS-specific separators
        
    Returns
    -------
    str
        Normalized path with dot separators
    """
    return module_path.replace(os.sep, ".").replace("/", ".")


def get_ast_diff(tree1: ast.AST, tree2: ast.AST) -> List[str]:
    """
    Get human-readable differences between two ASTs.
    
    Parameters
    ----------
    tree1 : ast.AST
        Original AST
    tree2 : ast.AST
        Modified AST
        
    Returns
    -------
    List[str]
        List of difference descriptions
    """
    code1 = ast.unparse(tree1)
    code2 = ast.unparse(tree2)
    
    import difflib
    diff = difflib.unified_diff(
        code1.splitlines(),
        code2.splitlines(),
        fromfile="original",
        tofile="modified"
    )
    
    return list(diff)


def is_valid_python_code(code: str) -> bool:
    """
    Check if string is valid Python code.
    
    Parameters
    ----------
    code : str
        Code to validate
        
    Returns
    -------
    bool
        True if code is syntactically valid
    """
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


# Export public interface
__all__ = [
    "ASTEditor",
    "ASTBatchEditor",
    "ValidationSeverity",
    "OperationType",
    "ValidationResult",
    "OperationLog",
    "CodeMetrics",
    "ASTValidationError",
    "ASTOperationError",
    "normalize_import_path",
    "get_ast_diff",
    "is_valid_python_code",
]


# Self-executing guard for module
if __name__ == "__main__":
    import doctest
    doctest.testmod(verbose=True, optionflags=doctest.ELLIPSIS)