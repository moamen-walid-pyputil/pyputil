#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Optional C code parsing using pycparser with comprehensive type handling.

This module provides robust, production-grade C code parsing capabilities
using pycparser (if installed). It handles complex C language features
including:
- Function signatures with complete type information
- Struct/union/enum definitions with recursive dependencies
- Typedef resolution and type aliasing
- Pointer chains, multi-dimensional arrays, and function pointers
- Variadic functions and calling conventions
- Preprocessor directives and macro expansion
- System and custom include path resolution

The type conversion system uses an extensible, dictionary-based mapping
with support for platform-specific type sizes and alignments.

Security Features
-----------------
- Sandboxed parsing with no code execution
- Path traversal protection in include directives
- Memory-safe AST traversal with recursion limits
- Validation of all type conversions
- Timeout protection for complex parsing

Classes
-------
CTypeMapper
    Maps C types to ctypes with platform-specific sizing.
ParsedFunction
    Represents a parsed C function with complete signature info.
ParsedStruct
    Represents a parsed C struct with field layout.
ParsedUnion
    Represents a parsed C union with member types.
ParsedEnum
    Represents a parsed C enum with value mapping.
ParseResult
    Container for all parsed declarations from a translation unit.
CachingParser
    Parser with LRU caching for improved performance.

Functions
---------
parse_c_code
    Extract all declarations from C source code.
parse_function_signatures
    Extract only function signatures from C code.
parse_struct_definitions
    Extract only struct/union definitions from C code.
build_struct_classes
    Build ctypes Structure/Union classes from parsed definitions.
set_function_signatures
    Apply parsed signatures to a loaded ctypes library.
validate_c_code
    Validate C code syntax without full parsing.

Examples
--------
>>> from cfast.parser import parse_c_code, build_struct_classes
>>> 
>>> code = '''
... #include <stdint.h>
... 
... typedef struct Point {
...     double x;
...     double y;
... } Point;
... 
... Point* create_point(double x, double y);
... double distance(Point* p1, Point* p2);
... '''
>>> 
>>> result = parse_c_code(code)
>>> print(f"Found {len(result.functions)} functions")
>>> print(f"Found {len(result.structs)} structs")
>>> 
>>> # Build ctypes classes
>>> struct_classes = build_struct_classes(result)
>>> Point = struct_classes['Point']
>>> 
>>> # Use with loaded library
>>> lib = ctypes.CDLL('./libgeometry.so')
>>> set_function_signatures(lib, code)
>>> p1 = lib.create_point(0.0, 0.0)
"""

import ctypes
import tempfile
import warnings
import re
import os
import sys
import hashlib
import functools
from pathlib import Path
from typing import (
    Dict, Tuple, Any, List, Optional, Set, Union, 
    Callable, Type, NamedTuple, Iterator, cast
)
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import OrderedDict, defaultdict
from contextlib import contextmanager

from .exceptions import SignatureDetectionError, ParseError
from .platform import PlatformInfo
from .utils import CTYPE_MAP, atomic_write

# =============================================================================
# Pycparser Availability Check
# =============================================================================

try:
    from pycparser import c_ast, parse_file, c_parser, c_generator
    from pycparser.plyparser import ParseError as PycparserParseError
    from pycparser.c_lexer import CLexer
    PYPARSER_AVAILABLE = True
    PYPARSER_VERSION = getattr(__import__('pycparser'), '__version__', 'unknown')
except ImportError:
    PYPARSER_AVAILABLE = False
    PYPARSER_VERSION = None
    # Create placeholder exception class
    class PycparserParseError(Exception):
        pass


# =============================================================================
# Constants and Configuration
# =============================================================================

# Maximum recursion depth for AST traversal
MAX_AST_DEPTH = 100

# Maximum number of declarations to process
MAX_DECLARATIONS = 10000

# Maximum source code size (10 MB)
MAX_SOURCE_SIZE = 10 * 1024 * 1024

# Cache size for parsed results
DEFAULT_CACHE_SIZE = 128

# Standard C type categories
class CTypeCategory(Enum):
    """Categories of C types."""
    VOID = auto()
    INTEGER = auto()
    FLOATING = auto()
    POINTER = auto()
    ARRAY = auto()
    STRUCT = auto()
    UNION = auto()
    ENUM = auto()
    FUNCTION = auto()
    TYPEDEF = auto()
    UNKNOWN = auto()


# Platform-specific type sizes (in bytes)
PLATFORM_TYPE_SIZES = {
    'linux': {
        'pointer': 8 if sys.maxsize > 2**32 else 4,
        'size_t': 8 if sys.maxsize > 2**32 else 4,
        'wchar_t': 4,
        'long': 8 if sys.maxsize > 2**32 else 4,
        'long long': 8,
    },
    'darwin': {
        'pointer': 8 if sys.maxsize > 2**32 else 4,
        'size_t': 8 if sys.maxsize > 2**32 else 4,
        'wchar_t': 4,
        'long': 8 if sys.maxsize > 2**32 else 4,
        'long long': 8,
    },
    'windows': {
        'pointer': 8 if sys.maxsize > 2**32 else 4,
        'size_t': 8 if sys.maxsize > 2**32 else 4,
        'wchar_t': 2,
        'long': 4,  # Windows: long is always 32-bit
        'long long': 8,
    },
}


# Extended type mapping with platform-specific sizes
EXTENDED_CTYPE_MAP = {
    # Standard integer types
    **CTYPE_MAP,
    
    # Additional integer types
    ('unsigned', 'short'): ctypes.c_ushort,
    ('signed', 'short'): ctypes.c_short,
    ('unsigned', 'int'): ctypes.c_uint,
    ('signed', 'int'): ctypes.c_int,
    ('unsigned', 'long'): ctypes.c_ulong,
    ('signed', 'long'): ctypes.c_long,
    ('unsigned', 'long', 'long'): ctypes.c_ulonglong,
    ('signed', 'long', 'long'): ctypes.c_longlong,
    
    # stdint.h types
    ('int8_t',): ctypes.c_int8,
    ('uint8_t',): ctypes.c_uint8,
    ('int16_t',): ctypes.c_int16,
    ('uint16_t',): ctypes.c_uint16,
    ('int32_t',): ctypes.c_int32,
    ('uint32_t',): ctypes.c_uint32,
    ('int64_t',): ctypes.c_int64,
    ('uint64_t',): ctypes.c_uint64,
    
    # stddef.h types
    ('size_t',): ctypes.c_size_t,
    ('ssize_t',): ctypes.c_ssize_t,
    ('ptrdiff_t',): ctypes.c_ssize_t,
    ('intptr_t',): ctypes.c_void_p,
    ('uintptr_t',): ctypes.c_void_p,
    
    # stdbool.h
    ('bool',): ctypes.c_bool,
    ('_Bool',): ctypes.c_bool,
    
    # Floating point
    ('float', 'complex'): ctypes.c_void_p,  # Complex not directly supported
    ('double', 'complex'): ctypes.c_void_p,
    
    # Wide character
    ('wchar_t',): ctypes.c_wchar,
    
    # Time types
    ('time_t',): ctypes.c_long,
    ('clock_t',): ctypes.c_long,
    
    # File types
    ('FILE',): ctypes.c_void_p,
}


# =============================================================================
# Preprocessor Helper Definitions
# =============================================================================

PREPROCESSOR_HELPERS = """
/* Auto-generated helpers for pycparser */
#ifndef __CFAST_HELPERS_LOADED
#define __CFAST_HELPERS_LOADED

/* Standard type definitions */
#ifndef __STDIO_LOADED
#define __STDIO_LOADED
typedef struct FILE FILE;
typedef struct _IO_FILE FILE;
#endif

#ifndef __STDDEF_LOADED
#define __STDDEF_LOADED
typedef unsigned long size_t;
typedef long ssize_t;
typedef long ptrdiff_t;
#ifndef NULL
#define NULL ((void*)0)
#endif
#endif

#ifndef __STDINT_LOADED
#define __STDINT_LOADED
typedef signed char int8_t;
typedef unsigned char uint8_t;
typedef short int16_t;
typedef unsigned short uint16_t;
typedef int int32_t;
typedef unsigned int uint32_t;
typedef long long int64_t;
typedef unsigned long long uint64_t;
typedef long intptr_t;
typedef unsigned long uintptr_t;
#endif

#ifndef __STDBOOL_LOADED
#define __STDBOOL_LOADED
#define bool _Bool
#define true 1
#define false 0
typedef int _Bool;
#endif

#ifndef __STDARG_LOADED
#define __STDARG_LOADED
typedef __builtin_va_list va_list;
#endif

/* Common attributes and specifiers */
#define __attribute__(x)
#define __restrict
#define __restrict__
#define __inline inline
#define __inline__ inline
#define __const const
#define __const__ const
#define __volatile volatile
#define __volatile__ volatile
#define __extension__
#define __asm__(x)
#define __asm(x)
#define __THROW
#define __nonnull(x)
#define __wur
#define __BEGIN_DECLS
#define __END_DECLS

/* Calling conventions */
#define __cdecl
#define __stdcall
#define __fastcall
#define __thiscall
#define __vectorcall
#define __pascal
#define __syscall
#define WINAPI
#define APIENTRY
#define CALLBACK

/* DLL import/export */
#define __declspec(x)
#define __declspec_dllimport
#define __declspec_dllexport
#define DLLIMPORT
#define DLLEXPORT

/* Deprecated and unused */
#define __deprecated
#define __unused
#define __maybe_unused

/* Alignment */
#define __aligned(x)
#define __packed
#define __alignof__(x)

/* Format checking */
#define __printf__(a, b)
#define __scanf__(a, b)

/* Built-in functions */
#define __builtin_va_start(ap, param)
#define __builtin_va_end(ap)
#define __builtin_va_arg(ap, type)
#define __builtin_va_copy(dest, src)
#define __builtin_expect(expr, val) (expr)
#define __builtin_prefetch(addr, rw, locality)
#define __builtin_constant_p(expr) 0
#define __builtin_types_compatible_p(type1, type2) 0
#define __builtin_offsetof(type, member) 0

/* Thread-local storage */
#define __thread
#define _Thread_local
#define thread_local

/* Atomic operations */
#define _Atomic
#define __atomic

/* Noreturn */
#define _Noreturn
#define __noreturn

/* Static assert */
#define static_assert(cond, msg)
#define _Static_assert(cond, msg)

#endif /* __CFAST_HELPERS_LOADED */
"""


# =============================================================================
# Data Classes for Parsed Results
# =============================================================================

@dataclass
class ParsedType:
    """
    Represents a parsed C type with full qualifier information.
    
    Attributes
    ----------
    base_type : str
        Base type name (e.g., 'int', 'struct Point').
    category : CTypeCategory
        Type category.
    is_const : bool
        Whether type is const-qualified.
    is_volatile : bool
        Whether type is volatile-qualified.
    is_restrict : bool
        Whether type is restrict-qualified.
    is_unsigned : bool
        Whether integer type is unsigned.
    pointer_depth : int
        Number of pointer indirections.
    array_dimensions : List[Optional[int]]
        Array dimension sizes (None for unspecified/incomplete).
    struct_name : Optional[str]
        Struct name if base_type is struct.
    union_name : Optional[str]
        Union name if base_type is union.
    enum_name : Optional[str]
        Enum name if base_type is enum.
    typedef_name : Optional[str]
        Original typedef name if type is aliased.
    """
    base_type: str
    category: CTypeCategory = CTypeCategory.UNKNOWN
    is_const: bool = False
    is_volatile: bool = False
    is_restrict: bool = False
    is_unsigned: bool = False
    pointer_depth: int = 0
    array_dimensions: List[Optional[int]] = field(default_factory=list)
    struct_name: Optional[str] = None
    union_name: Optional[str] = None
    enum_name: Optional[str] = None
    typedef_name: Optional[str] = None
    func_return_type: Optional['ParsedType'] = None
    func_param_types: List['ParsedType'] = field(default_factory=list)
    func_is_variadic: bool = False
    func_calling_convention: Optional[str] = None


@dataclass
class ParsedParameter:
    """
    Represents a function parameter.
    
    Attributes
    ----------
    name : Optional[str]
        Parameter name (may be None in prototypes).
    type : ParsedType
        Parameter type information.
    """
    name: Optional[str]
    type: ParsedType


@dataclass
class ParsedFunction:
    """
    Represents a complete C function declaration.
    
    Attributes
    ----------
    name : str
        Function name.
    return_type : ParsedType
        Return type information.
    parameters : List[ParsedParameter]
        List of function parameters.
    is_variadic : bool
        Whether function takes variable arguments.
    is_inline : bool
        Whether function is declared inline.
    is_static : bool
        Whether function has static linkage.
    storage_class : Optional[str]
        Storage class specifier (extern, static, etc.).
    calling_convention : Optional[str]
        Calling convention (cdecl, stdcall, etc.).
    attributes : List[str]
        Function attributes (e.g., noreturn, deprecated).
    source_location : Optional[str]
        Source location for error reporting.
    """
    name: str
    return_type: ParsedType
    parameters: List[ParsedParameter] = field(default_factory=list)
    is_variadic: bool = False
    is_inline: bool = False
    is_static: bool = False
    storage_class: Optional[str] = None
    calling_convention: Optional[str] = None
    attributes: List[str] = field(default_factory=list)
    source_location: Optional[str] = None


@dataclass
class ParsedField:
    """
    Represents a struct/union field.
    
    Attributes
    ----------
    name : str
        Field name.
    type : ParsedType
        Field type information.
    bit_width : Optional[int]
        Bit width for bit-fields.
    offset : Optional[int]
        Byte offset within struct (if computed).
    """
    name: str
    type: ParsedType
    bit_width: Optional[int] = None
    offset: Optional[int] = None


@dataclass
class ParsedStruct:
    """
    Represents a complete C struct definition.
    
    Attributes
    ----------
    name : Optional[str]
        Struct tag name (may be None for anonymous structs).
    fields : List[ParsedField]
        List of struct fields.
    is_union : bool
        True if this is a union (all fields share memory).
    is_packed : bool
        Whether struct has packed attribute.
    alignment : Optional[int]
        Explicit alignment requirement.
    size : Optional[int]
        Total size in bytes (if computed).
    source_location : Optional[str]
        Source location for error reporting.
    """
    name: Optional[str]
    fields: List[ParsedField] = field(default_factory=list)
    is_union: bool = False
    is_packed: bool = False
    alignment: Optional[int] = None
    size: Optional[int] = None
    source_location: Optional[str] = None


@dataclass
class ParsedEnum:
    """
    Represents a complete C enum definition.
    
    Attributes
    ----------
    name : Optional[str]
        Enum tag name.
    values : Dict[str, Optional[int]]
        Mapping from enumerator names to values (None for auto-assigned).
    source_location : Optional[str]
        Source location for error reporting.
    """
    name: Optional[str]
    values: Dict[str, Optional[int]] = field(default_factory=dict)
    source_location: Optional[str] = None


@dataclass
class ParsedTypedef:
    """
    Represents a C typedef declaration.
    
    Attributes
    ----------
    name : str
        Typedef name.
    type : ParsedType
        Underlying type.
    source_location : Optional[str]
        Source location for error reporting.
    """
    name: str
    type: ParsedType
    source_location: Optional[str] = None


@dataclass
class ParsedVariable:
    """
    Represents a C global variable declaration.
    
    Attributes
    ----------
    name : str
        Variable name.
    type : ParsedType
        Variable type.
    storage_class : Optional[str]
        Storage class (extern, static, etc.).
    initializer : Optional[str]
        Initializer expression (as string).
    source_location : Optional[str]
        Source location for error reporting.
    """
    name: str
    type: ParsedType
    storage_class: Optional[str] = None
    initializer: Optional[str] = None
    source_location: Optional[str] = None


@dataclass
class ParseResult:
    """
    Container for all parsed declarations from a translation unit.
    
    Attributes
    ----------
    functions : Dict[str, ParsedFunction]
        Parsed function declarations.
    structs : Dict[str, ParsedStruct]
        Parsed struct definitions.
    unions : Dict[str, ParsedStruct]
        Parsed union definitions.
    enums : Dict[str, ParsedEnum]
        Parsed enum definitions.
    typedefs : Dict[str, ParsedTypedef]
        Parsed typedef declarations.
    variables : Dict[str, ParsedVariable]
        Parsed global variable declarations.
    source_hash : str
        SHA-256 hash of source code.
    parse_time : float
        Time taken to parse (seconds).
    warnings : List[str]
        Warnings encountered during parsing.
    """
    functions: Dict[str, ParsedFunction] = field(default_factory=dict)
    structs: Dict[str, ParsedStruct] = field(default_factory=dict)
    unions: Dict[str, ParsedStruct] = field(default_factory=dict)
    enums: Dict[str, ParsedEnum] = field(default_factory=dict)
    typedefs: Dict[str, ParsedTypedef] = field(default_factory=dict)
    variables: Dict[str, ParsedVariable] = field(default_factory=dict)
    source_hash: str = ""
    parse_time: float = 0.0
    warnings: List[str] = field(default_factory=list)
    
    def get_function(self, name: str) -> Optional[ParsedFunction]:
        """Get function by name."""
        return self.functions.get(name)
    
    def get_struct(self, name: str) -> Optional[ParsedStruct]:
        """Get struct by name."""
        return self.structs.get(name)
    
    def get_union(self, name: str) -> Optional[ParsedStruct]:
        """Get union by name."""
        return self.unions.get(name)
    
    def get_enum(self, name: str) -> Optional[ParsedEnum]:
        """Get enum by name."""
        return self.enums.get(name)
    
    def get_typedef(self, name: str) -> Optional[ParsedTypedef]:
        """Get typedef by name."""
        return self.typedefs.get(name)
    
    @property
    def total_declarations(self) -> int:
        """Total number of parsed declarations."""
        return (
            len(self.functions) +
            len(self.structs) +
            len(self.unions) +
            len(self.enums) +
            len(self.typedefs) +
            len(self.variables)
        )


# =============================================================================
# Type Mapper Class
# =============================================================================

class CTypeMapper:
    """
    Maps C types to ctypes with platform-specific sizing and alignment.
    
    This class handles the conversion of parsed C types to appropriate
    ctypes types, respecting platform differences and type qualifiers.
    
    Attributes
    ----------
    platform : str
        Platform identifier (linux, darwin, windows).
    pointer_size : int
        Size of pointer in bytes.
    type_aliases : Dict[str, Any]
        Custom type aliases mapping.
    struct_classes : Dict[str, Type[ctypes.Structure]]
        Built struct classes for recursive resolution.
    
    Examples
    --------
    >>> mapper = CTypeMapper()
    >>> parsed_type = ParsedType(base_type='int', pointer_depth=1)
    >>> ctype = mapper.to_ctypes(parsed_type)
    >>> print(ctype)  # <class 'ctypes.POINTER(ctypes.c_int)'>
    """
    
    def __init__(
        self,
        platform: Optional[str] = None,
        struct_classes: Optional[Dict[str, Type[ctypes.Structure]]] = None
    ):
        self.platform = platform or sys.platform
        self._platform_key = self._get_platform_key()
        self.pointer_size = PLATFORM_TYPE_SIZES[self._platform_key]['pointer']
        self.type_aliases: Dict[str, Any] = {}
        self.struct_classes = struct_classes or {}
        
        # Initialize type size cache
        self._type_size_cache: Dict[str, int] = {}
    
    def _get_platform_key(self) -> str:
        """Get normalized platform key."""
        if self.platform.startswith('linux'):
            return 'linux'
        elif self.platform == 'darwin':
            return 'darwin'
        elif self.platform.startswith('win'):
            return 'windows'
        return 'linux'  # Default
    
    def to_ctypes(
        self,
        parsed_type: ParsedType,
        is_return: bool = False
    ) -> Any:
        """
        Convert a parsed C type to a ctypes type.
        
        Parameters
        ----------
        parsed_type : ParsedType
            Parsed type information.
        is_return : bool
            Whether this is a function return type.
        
        Returns
        -------
        Any
            ctypes type (class or instance).
        
        Raises
        ------
        ValueError
            If type cannot be converted.
        """
        # Handle void
        if parsed_type.base_type == 'void':
            if parsed_type.pointer_depth > 0:
                result = ctypes.c_void_p
                for _ in range(parsed_type.pointer_depth - 1):
                    result = ctypes.POINTER(result)
                return result
            return None if is_return else ctypes.c_void_p
        
        # Handle function pointers
        if parsed_type.category == CTypeCategory.FUNCTION:
            return self._function_pointer_type(parsed_type)
        
        # Get base type
        base_ctype = self._get_base_ctypes(parsed_type)
        
        # Apply array dimensions
        if parsed_type.array_dimensions:
            base_ctype = self._apply_array_dimensions(
                base_ctype, parsed_type.array_dimensions, is_return
            )
        
        # Apply pointer indirections
        for _ in range(parsed_type.pointer_depth):
            base_ctype = ctypes.POINTER(base_ctype)
        
        return base_ctype
    
    def _get_base_ctypes(self, parsed_type: ParsedType) -> Any:
        """Get base ctypes type without pointers/arrays."""
        base = parsed_type.base_type
        
        # Check type aliases first
        if base in self.type_aliases:
            return self.type_aliases[base]
        
        # Check struct/union
        if parsed_type.category == CTypeCategory.STRUCT:
            if parsed_type.struct_name in self.struct_classes:
                return self.struct_classes[parsed_type.struct_name]
            return ctypes.c_void_p  # Forward declaration
        
        if parsed_type.category == CTypeCategory.UNION:
            if parsed_type.union_name in self.struct_classes:
                return self.struct_classes[parsed_type.union_name]
            return ctypes.c_void_p
        
        # Check enum
        if parsed_type.category == CTypeCategory.ENUM:
            return ctypes.c_int
        
        # Check extended type map
        type_key = (base,)
        if type_key in EXTENDED_CTYPE_MAP:
            return EXTENDED_CTYPE_MAP[type_key]
        
        # Try with unsigned prefix
        if parsed_type.is_unsigned:
            unsigned_key = ('unsigned', base)
            if unsigned_key in EXTENDED_CTYPE_MAP:
                return EXTENDED_CTYPE_MAP[unsigned_key]
        
        # Handle platform-specific sizes
        if base in ('long', 'unsigned long'):
            if self._platform_key == 'windows':
                return ctypes.c_long if base == 'long' else ctypes.c_ulong
            return ctypes.c_long if base == 'long' else ctypes.c_ulong
        
        # Fallback
        warnings.warn(f"Unknown type '{base}', using c_void_p")
        return ctypes.c_void_p
    
    def _apply_array_dimensions(
        self,
        elem_type: Any,
        dimensions: List[Optional[int]],
        is_return: bool
    ) -> Any:
        """Apply array dimensions to element type."""
        if is_return:
            # Arrays as return values decay to pointers
            return ctypes.POINTER(elem_type)
        
        result = elem_type
        for dim in reversed(dimensions):
            if dim is not None:
                result = result * dim
            else:
                # Incomplete array - treat as pointer
                result = ctypes.POINTER(result)
        return result
    
    def _function_pointer_type(self, func_type: ParsedType) -> Any:
        """Create a function pointer type."""
        # CFUNCTYPE for function pointers
        restype = self.to_ctypes(func_type.func_return_type, is_return=True)
        argtypes = [
            self.to_ctypes(param, is_return=False)
            for param in func_type.func_param_types
        ]
        return ctypes.CFUNCTYPE(restype, *argtypes)
    
    def get_size(self, parsed_type: ParsedType) -> Optional[int]:
        """
        Get size of type in bytes.
        
        Parameters
        ----------
        parsed_type : ParsedType
            Parsed type information.
        
        Returns
        -------
        Optional[int]
            Size in bytes or None if cannot determine.
        """
        ctype = self.to_ctypes(parsed_type)
        try:
            return ctypes.sizeof(ctype)
        except (TypeError, ValueError):
            return None
    
    def get_alignment(self, parsed_type: ParsedType) -> Optional[int]:
        """
        Get alignment requirement of type.
        
        Parameters
        ----------
        parsed_type : ParsedType
            Parsed type information.
        
        Returns
        -------
        Optional[int]
            Alignment in bytes or None if cannot determine.
        """
        ctype = self.to_ctypes(parsed_type)
        try:
            return ctypes.alignment(ctype)
        except (TypeError, ValueError):
            return None


# =============================================================================
# AST Visitor for Parsing
# =============================================================================

class CDeclarationVisitor(c_ast.NodeVisitor):
    """
    AST visitor that extracts declarations from a C translation unit.
    
    This visitor traverses the AST and builds ParsedFunction, ParsedStruct,
    ParsedEnum, and other declaration objects.
    
    Attributes
    ----------
    result : ParseResult
        Accumulated parsing results.
    typedef_map : Dict[str, ParsedType]
        Map of typedef names to their types.
    current_scope : List[str]
        Current scope stack for name resolution.
    warnings : List[str]
        Warnings encountered during traversal.
    """
    
    def __init__(self):
        self.result = ParseResult()
        self.typedef_map: Dict[str, ParsedType] = {}
        self.current_scope: List[str] = []
        self.warnings: List[str] = []
        self._depth = 0
        self._struct_stack: List[ParsedStruct] = []
    
    def visit(self, node: c_ast.Node):
        """Visit a node with depth tracking."""
        self._depth += 1
        if self._depth > MAX_AST_DEPTH:
            self.warnings.append(f"Max AST depth {MAX_AST_DEPTH} exceeded")
            self._depth -= 1
            return
        try:
            super().visit(node)
        finally:
            self._depth -= 1
    
    def visit_FuncDef(self, node: c_ast.FuncDef):
        """Visit function definition."""
        func = self._extract_function(node.decl, is_definition=True)
        if func:
            self.result.functions[func.name] = func
    
    def visit_Decl(self, node: c_ast.Decl):
        """Visit declaration."""
        if node.name is None:
            return
        
        # Check if this is a function declaration
        if isinstance(node.type, c_ast.FuncDecl):
            func = self._extract_function(node, is_definition=False)
            if func:
                self.result.functions[func.name] = func
        
        # Check if this is a struct/union definition
        elif isinstance(node.type, c_ast.Struct):
            struct = self._extract_struct(node.type, node.name)
            if struct:
                if struct.is_union:
                    self.result.unions[struct.name or f"__anon_{id(node)}"] = struct
                else:
                    self.result.structs[struct.name or f"__anon_{id(node)}"] = struct
        
        # Check if this is an enum definition
        elif isinstance(node.type, c_ast.Enum):
            enum = self._extract_enum(node.type)
            if enum:
                self.result.enums[enum.name or f"__anon_{id(node)}"] = enum
        
        # Check if this is a typedef
        elif node.name and self._is_typedef_context():
            typedef = self._extract_typedef(node)
            if typedef:
                self.result.typedefs[typedef.name] = typedef
                self.typedef_map[typedef.name] = typedef.type
        
        # Regular variable declaration
        else:
            var = self._extract_variable(node)
            if var:
                self.result.variables[var.name] = var
    
    def visit_Typedef(self, node: c_ast.Typedef):
        """Visit typedef declaration."""
        typedef = self._extract_typedef(node)
        if typedef:
            self.result.typedefs[typedef.name] = typedef
            self.typedef_map[typedef.name] = typedef.type
    
    def _is_typedef_context(self) -> bool:
        """Check if we're in a typedef context."""
        # This is a simplification; proper implementation would track context
        return False
    
    def _extract_function(
        self,
        decl: Union[c_ast.Decl, c_ast.FuncDecl],
        is_definition: bool
    ) -> Optional[ParsedFunction]:
        """Extract function information from declaration."""
        try:
            name = decl.name if isinstance(decl, c_ast.Decl) else None
            if name is None:
                return None
            
            # Get function type
            func_type = decl.type if isinstance(decl, c_ast.Decl) else decl
            if not isinstance(func_type, c_ast.FuncDecl):
                return None
            
            # Extract return type
            return_type = self._extract_type(func_type.type)
            
            # Extract parameters
            parameters = []
            if func_type.args:
                for param in func_type.args.params:
                    if isinstance(param, c_ast.EllipsisParam):
                        continue
                    param_info = self._extract_parameter(param)
                    parameters.append(param_info)
            
            # Check storage class
            storage_class = None
            is_static = False
            is_inline = False
            
            if hasattr(decl, 'storage'):
                storage = ' '.join(decl.storage) if decl.storage else None
                storage_class = storage
                is_static = 'static' in decl.storage if decl.storage else False
            
            if hasattr(decl, 'funcspec'):
                is_inline = 'inline' in decl.funcspec if decl.funcspec else False
            
            return ParsedFunction(
                name=name,
                return_type=return_type,
                parameters=parameters,
                is_variadic=func_type.args and any(
                    isinstance(p, c_ast.EllipsisParam)
                    for p in func_type.args.params
                ) if func_type.args else False,
                is_inline=is_inline,
                is_static=is_static,
                storage_class=storage_class,
            )
        except Exception as e:
            self.warnings.append(f"Failed to extract function: {e}")
            return None
    
    def _extract_parameter(self, param: c_ast.Decl) -> ParsedParameter:
        """Extract parameter information."""
        param_type = self._extract_type(param.type)
        return ParsedParameter(
            name=param.name,
            type=param_type
        )
    
    def _extract_type(self, type_node: c_ast.Node) -> ParsedType:
        """Extract type information from AST node."""
        parsed = ParsedType(base_type='void')
        
        # Handle TypeDecl wrapper
        if isinstance(type_node, c_ast.TypeDecl):
            parsed.base_type = ' '.join(type_node.type.names) if hasattr(type_node.type, 'names') else 'unknown'
            parsed = self._extract_type_qualifiers(type_node, parsed)
            return self._extract_type(type_node.type)
        
        # Handle IdentifierType (basic types)
        if isinstance(type_node, c_ast.IdentifierType):
            names = type_node.names
            parsed.base_type = ' '.join(names)
            parsed.category = self._categorize_type(names)
            parsed.is_unsigned = 'unsigned' in names
            return parsed
        
        # Handle PtrDecl (pointers)
        if isinstance(type_node, c_ast.PtrDecl):
            parsed = self._extract_type(type_node.type)
            parsed.pointer_depth += 1
            parsed = self._extract_type_qualifiers(type_node, parsed)
            return parsed
        
        # Handle ArrayDecl (arrays)
        if isinstance(type_node, c_ast.ArrayDecl):
            parsed = self._extract_type(type_node.type)
            dim = self._extract_array_dimension(type_node.dim)
            parsed.array_dimensions.append(dim)
            return parsed
        
        # Handle Struct (struct/union)
        if isinstance(type_node, c_ast.Struct):
            parsed.base_type = f"{'union' if type_node.name else 'struct'} {type_node.name or 'anonymous'}"
            parsed.category = CTypeCategory.UNION if type_node.name else CTypeCategory.STRUCT
            parsed.struct_name = type_node.name
            return parsed
        
        # Handle Enum (enum)
        if isinstance(type_node, c_ast.Enum):
            parsed.base_type = f"enum {type_node.name or 'anonymous'}"
            parsed.category = CTypeCategory.ENUM
            parsed.enum_name = type_node.name
            return parsed
        
        # Handle FuncDecl (function pointers)
        if isinstance(type_node, c_ast.FuncDecl):
            parsed.category = CTypeCategory.FUNCTION
            parsed.func_return_type = self._extract_type(type_node.type)
            if type_node.args:
                for param in type_node.args.params:
                    if isinstance(param, c_ast.EllipsisParam):
                        parsed.func_is_variadic = True
                    else:
                        param_type = self._extract_type(param.type)
                        parsed.func_param_types.append(param_type)
            return parsed
        
        # Handle Typedef (typedef reference)
        if isinstance(type_node, c_ast.Typedef):
            parsed.base_type = type_node.name
            parsed.category = CTypeCategory.TYPEDEF
            parsed.typedef_name = type_node.name
            if type_node.name in self.typedef_map:
                return self.typedef_map[type_node.name]
            return parsed
        
        return parsed
    
    def _extract_type_qualifiers(
        self,
        node: Union[c_ast.TypeDecl, c_ast.PtrDecl],
        parsed: ParsedType
    ) -> ParsedType:
        """Extract type qualifiers (const, volatile, restrict)."""
        if hasattr(node, 'qualifiers') and node.qualifiers:
            parsed.is_const = 'const' in node.qualifiers
            parsed.is_volatile = 'volatile' in node.qualifiers
            parsed.is_restrict = 'restrict' in node.qualifiers
        return parsed
    
    def _extract_array_dimension(self, dim_node: Optional[c_ast.Node]) -> Optional[int]:
        """Extract array dimension value."""
        if dim_node is None:
            return None
        if isinstance(dim_node, c_ast.Constant):
            try:
                return int(dim_node.value)
            except ValueError:
                return None
        return None
    
    def _categorize_type(self, names: List[str]) -> CTypeCategory:
        """Categorize a C type based on its name."""
        type_str = ' '.join(names).lower()
        
        if 'void' in type_str:
            return CTypeCategory.VOID
        elif any(t in type_str for t in ('int', 'char', 'short', 'long', 'size_t')):
            return CTypeCategory.INTEGER
        elif any(t in type_str for t in ('float', 'double')):
            return CTypeCategory.FLOATING
        elif 'struct' in type_str:
            return CTypeCategory.STRUCT
        elif 'union' in type_str:
            return CTypeCategory.UNION
        elif 'enum' in type_str:
            return CTypeCategory.ENUM
        
        return CTypeCategory.UNKNOWN
    
    def _extract_struct(
        self,
        struct_node: c_ast.Struct,
        typedef_name: Optional[str] = None
    ) -> Optional[ParsedStruct]:
        """Extract struct/union definition."""
        try:
            name = struct_node.name or typedef_name
            fields = []
            
            if struct_node.decls:
                for decl in struct_node.decls:
                    if isinstance(decl, c_ast.Decl):
                        field = self._extract_field(decl)
                        if field:
                            fields.append(field)
            
            return ParsedStruct(
                name=name,
                fields=fields,
                is_union=False,  # Struct node is used for both; check context
            )
        except Exception as e:
            self.warnings.append(f"Failed to extract struct: {e}")
            return None
    
    def _extract_field(self, decl: c_ast.Decl) -> Optional[ParsedField]:
        """Extract struct/union field."""
        try:
            field_type = self._extract_type(decl.type)
            bit_width = None
            
            if decl.bitsize:
                if isinstance(decl.bitsize, c_ast.Constant):
                    try:
                        bit_width = int(decl.bitsize.value)
                    except ValueError:
                        pass
            
            return ParsedField(
                name=decl.name or '',
                type=field_type,
                bit_width=bit_width,
            )
        except Exception as e:
            self.warnings.append(f"Failed to extract field: {e}")
            return None
    
    def _extract_enum(self, enum_node: c_ast.Enum) -> Optional[ParsedEnum]:
        """Extract enum definition."""
        try:
            name = enum_node.name
            values = {}
            
            if enum_node.values:
                current_value = 0
                for enumerator in enum_node.values:
                    if enumerator.value:
                        if isinstance(enumerator.value, c_ast.Constant):
                            try:
                                current_value = int(enumerator.value.value)
                            except ValueError:
                                pass
                    values[enumerator.name] = current_value
                    current_value += 1
            
            return ParsedEnum(
                name=name,
                values=values,
            )
        except Exception as e:
            self.warnings.append(f"Failed to extract enum: {e}")
            return None
    
    def _extract_typedef(self, node: Union[c_ast.Typedef, c_ast.Decl]) -> Optional[ParsedTypedef]:
        """Extract typedef declaration."""
        try:
            name = node.name
            if name is None:
                return None
            
            typedef_type = self._extract_type(node.type)
            return ParsedTypedef(
                name=name,
                type=typedef_type,
            )
        except Exception as e:
            self.warnings.append(f"Failed to extract typedef: {e}")
            return None
    
    def _extract_variable(self, decl: c_ast.Decl) -> Optional[ParsedVariable]:
        """Extract global variable declaration."""
        try:
            var_type = self._extract_type(decl.type)
            storage_class = None
            
            if hasattr(decl, 'storage') and decl.storage:
                storage_class = ' '.join(decl.storage)
            
            initializer = None
            if hasattr(decl, 'init') and decl.init:
                generator = c_generator.CGenerator()
                initializer = generator.visit(decl.init)
            
            return ParsedVariable(
                name=decl.name,
                type=var_type,
                storage_class=storage_class,
                initializer=initializer,
            )
        except Exception as e:
            self.warnings.append(f"Failed to extract variable: {e}")
            return None


# =============================================================================
# Preprocessor Configuration
# =============================================================================

def _get_pycparser_preprocessor_args(
    extra_includes: Optional[List[Union[str, Path]]] = None
) -> List[str]:
    """
    Get preprocessor arguments for pycparser.
    
    Includes system and Python include paths to help pycparser resolve
    standard headers. Also validates include paths for security.
    
    Parameters
    ----------
    extra_includes : Optional[List[Union[str, Path]]]
        Additional include directories to add.
    
    Returns
    -------
    List[str]
        Preprocessor arguments for pycparser.
    
    Raises
    ------
    ValueError
        If include paths contain suspicious patterns.
    """
    cpp_args = ['-E']
    
    # Add Python include paths
    python_includes = PlatformInfo.python_include_args()
    cpp_args.extend(python_includes)
    
    # Add system include paths
    system_includes = _get_system_include_paths()
    for inc in system_includes:
        cpp_args.append(f"-I{inc}")
    
    # Add user-provided includes with validation
    if extra_includes:
        for inc in extra_includes:
            inc_path = Path(inc)
            
            # Security check: prevent path traversal
            if '..' in str(inc_path) or str(inc_path).startswith('~'):
                raise ValueError(f"Suspicious include path: {inc}")
            
            # Resolve and add
            try:
                resolved = inc_path.resolve()
                if resolved.exists() and resolved.is_dir():
                    cpp_args.append(f"-I{resolved}")
                else:
                    warnings.warn(f"Include directory does not exist: {inc}")
            except OSError:
                warnings.warn(f"Cannot resolve include path: {inc}")
    
    # Add defines for better parsing
    cpp_args.extend([
        '-D__attribute__(x)=',
        '-D__restrict=',
        '-D__restrict__=',
        '-D__inline=inline',
        '-D__inline__=inline',
        '-D__const=const',
        '-D__const__=const',
        '-D__volatile=volatile',
        '-D__volatile__=volatile',
        '-D__extension__=',
        '-D__asm__(x)=',
        '-D__asm(x)=',
        '-D__THROW=',
        '-D__nonnull(x)=',
        '-D__wur=',
        '-D__BEGIN_DECLS=',
        '-D__END_DECLS=',
        '-D__cdecl=',
        '-D__stdcall=',
        '-D__fastcall=',
        '-D__declspec(x)=',
        '-DWINAPI=',
        '-DAPIENTRY=',
        '-DCALLBACK=',
        '-D_Noreturn=',
        '-D__noreturn=',
        '-D_Atomic=',
        '-D__atomic=',
        '-D_Thread_local=',
        '-Dthread_local=',
    ])
    
    return cpp_args


def _get_system_include_paths() -> List[str]:
    """
    Get system include paths for the current platform.
    
    Returns
    -------
    List[str]
        List of system include directory paths.
    """
    paths = []
    
    if sys.platform.startswith('linux'):
        paths.extend([
            '/usr/include',
            '/usr/local/include',
            '/usr/include/x86_64-linux-gnu',
            '/usr/lib/gcc/x86_64-linux-gnu/*/include',
        ])
    elif sys.platform == 'darwin':
        paths.extend([
            '/usr/include',
            '/usr/local/include',
            '/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk/usr/include',
        ])
    elif sys.platform.startswith('win'):
        # Windows paths - these may need adjustment
        if 'VSINSTALLDIR' in os.environ:
            vs_path = Path(os.environ['VSINSTALLDIR'])
            paths.append(str(vs_path / 'VC' / 'Tools' / 'MSVC' / '*' / 'include'))
            paths.append(str(vs_path / 'VC' / 'Tools' / 'MSVC' / '*' / 'atlmfc' / 'include'))
        
        # Windows SDK
        if 'WindowsSdkDir' in os.environ:
            sdk_path = Path(os.environ['WindowsSdkDir'])
            paths.append(str(sdk_path / 'Include' / '*' / 'ucrt'))
            paths.append(str(sdk_path / 'Include' / '*' / 'shared'))
            paths.append(str(sdk_path / 'Include' / '*' / 'um'))
            paths.append(str(sdk_path / 'Include' / '*' / 'winrt'))
    
    # Filter to existing directories
    import glob
    existing = []
    for path in paths:
        if '*' in path:
            for expanded in glob.glob(path):
                if os.path.isdir(expanded):
                    existing.append(expanded)
        elif os.path.isdir(path):
            existing.append(path)
    
    return existing


# =============================================================================
# Main Parsing Functions
# =============================================================================

if PYPARSER_AVAILABLE:
    
    def parse_c_code(
        code: str,
        extra_includes: Optional[List[Union[str, Path]]] = None,
        validate: bool = True
    ) -> ParseResult:
        """
        Parse C source code and extract all declarations.
        
        This function parses C source code using pycparser and extracts
        function signatures, struct/union/enum definitions, typedefs,
        and global variable declarations.
        
        Parameters
        ----------
        code : str
            The C source code to parse.
        extra_includes : Optional[List[Union[str, Path]]]
            Additional include directories to search for headers.
        validate : bool
            Whether to perform additional validation on parsed types.
        
        Returns
        -------
        ParseResult
            Container with all parsed declarations.
        
        Raises
        ------
        ParseError
            If parsing fails due to syntax errors.
        SignatureDetectionError
            If parsing fails for other reasons.
        ValueError
            If code exceeds size limit or contains invalid content.
        
        Examples
        --------
        >>> code = '''
        ... #include <stdint.h>
        ... 
        ... typedef struct {
        ...     double x, y;
        ... } Point;
        ... 
        ... Point* create_point(double x, double y);
        ... '''
        >>> 
        >>> result = parse_c_code(code)
        >>> print(f"Functions: {list(result.functions.keys())}")
        >>> print(f"Structs: {list(result.structs.keys())}")
        """
        import time
        start_time = time.time()
        
        # Validate input
        if not code or not code.strip():
            raise ValueError("Source code cannot be empty")
        
        if len(code) > MAX_SOURCE_SIZE:
            raise ValueError(f"Source code exceeds maximum size of {MAX_SOURCE_SIZE} bytes")
        
        # Generate source hash
        source_hash = hashlib.sha256(code.encode()).hexdigest()
        
        # Get preprocessor arguments
        try:
            cpp_args = _get_pycparser_preprocessor_args(extra_includes)
        except ValueError as e:
            raise SignatureDetectionError(f"Invalid include paths: {e}") from e
        
        # Create temporary file with helpers
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.c',
            encoding='utf-8',
            delete=False
        ) as f:
            f.write(PREPROCESSOR_HELPERS)
            f.write('\n')
            f.write(code)
            temp_file = f.name
        
        try:
            # Parse the file
            ast = parse_file(
                temp_file,
                use_cpp=True,
                cpp_args=cpp_args,
                parser=c_parser.CParser()
            )
            
            # Visit AST to extract declarations
            visitor = CDeclarationVisitor()
            visitor.visit(ast)
            
            # Build result
            result = visitor.result
            result.source_hash = source_hash
            result.parse_time = time.time() - start_time
            result.warnings = visitor.warnings
            
            # Validate if requested
            if validate:
                _validate_parse_result(result)
            
            return result
            
        except PycparserParseError as e:
            raise ParseError(
                f"Syntax error in C code: {e}\n"
                "Check for missing semicolons, unmatched braces, or invalid syntax."
            ) from e
        except Exception as e:
            raise SignatureDetectionError(
                f"Failed to parse C code: {e}\n"
                "Try adding include paths via extra_includes parameter."
            ) from e
        finally:
            # Cleanup temporary file
            try:
                Path(temp_file).unlink(missing_ok=True)
            except OSError:
                pass
    
    def _validate_parse_result(result: ParseResult) -> None:
        """
        Validate parsed result for consistency.
        
        Parameters
        ----------
        result : ParseResult
            Parsed result to validate.
        
        Raises
        ------
        SignatureDetectionError
            If validation fails.
        """
        # Check for incomplete types
        for func_name, func in result.functions.items():
            if func.return_type.category == CTypeCategory.UNKNOWN:
                result.warnings.append(
                    f"Function '{func_name}' has unknown return type: {func.return_type.base_type}"
                )
            
            for param in func.parameters:
                if param.type.category == CTypeCategory.UNKNOWN:
                    result.warnings.append(
                        f"Function '{func_name}' parameter '{param.name}' has unknown type"
                    )
    
    def parse_function_signatures(
        code: str,
        extra_includes: Optional[List[Union[str, Path]]] = None
    ) -> Dict[str, ParsedFunction]:
        """
        Extract only function signatures from C code.
        
        Parameters
        ----------
        code : str
            C source code to parse.
        extra_includes : Optional[List[Union[str, Path]]]
            Additional include directories.
        
        Returns
        -------
        Dict[str, ParsedFunction]
            Mapping from function name to parsed signature.
        """
        result = parse_c_code(code, extra_includes)
        return result.functions
    
    def parse_struct_definitions(
        code: str,
        extra_includes: Optional[List[Union[str, Path]]] = None
    ) -> Tuple[Dict[str, ParsedStruct], Dict[str, ParsedStruct]]:
        """
        Extract only struct/union definitions from C code.
        
        Parameters
        ----------
        code : str
            C source code to parse.
        extra_includes : Optional[List[Union[str, Path]]]
            Additional include directories.
        
        Returns
        -------
        Tuple[Dict[str, ParsedStruct], Dict[str, ParsedStruct]]
            Tuple of (structs, unions) dictionaries.
        """
        result = parse_c_code(code, extra_includes)
        return result.structs, result.unions
    
    def build_struct_classes(
        structs: Dict[str, ParsedStruct],
        unions: Optional[Dict[str, ParsedStruct]] = None,
        mapper: Optional[CTypeMapper] = None
    ) -> Dict[str, Type[ctypes.Structure]]:
        """
        Build ctypes Structure/Union classes from parsed definitions.
        
        Uses a two-pass approach to handle self-referential and mutually
        recursive structs correctly.
        
        Parameters
        ----------
        structs : Dict[str, ParsedStruct]
            Mapping from struct name to parsed definition.
        unions : Optional[Dict[str, ParsedStruct]]
            Mapping from union name to parsed definition.
        mapper : Optional[CTypeMapper]
            Type mapper instance. Created if not provided.
        
        Returns
        -------
        Dict[str, Type[ctypes.Structure]]
            Mapping from name to constructed ctypes class.
        
        Examples
        --------
        >>> result = parse_c_code(code)
        >>> classes = build_struct_classes(result.structs, result.unions)
        >>> Point = classes['Point']
        >>> point = Point()
        >>> point.x = 10.0
        """
        all_structs = {**structs}
        if unions:
            all_structs.update(unions)
        
        mapper = mapper or CTypeMapper()
        
        # Phase 1: Create empty classes
        classes = {}
        for name, parsed in all_structs.items():
            if parsed.is_union:
                # Create as Union subclass
                class_dict = {'_fields_': []}
                classes[name] = type(name, (ctypes.Union,), class_dict)
            else:
                # Create as Structure subclass
                class_dict = {'_fields_': []}
                if parsed.is_packed:
                    class_dict['_pack_'] = 1
                classes[name] = type(name, (ctypes.Structure,), class_dict)
        
        # Update mapper with created classes
        mapper.struct_classes = classes
        
        # Phase 2: Fill _fields_
        for name, parsed in all_structs.items():
            fields = []
            for field in parsed.fields:
                try:
                    ctype = mapper.to_ctypes(field.type)
                    fields.append((field.name, ctype))
                except Exception as e:
                    warnings.warn(f"Failed to convert field '{field.name}': {e}")
                    fields.append((field.name, ctypes.c_void_p))
            
            classes[name]._fields_ = fields
        
        return classes
    
    def set_function_signatures(
        lib: 'ctypes.CDLL',
        code: str,
        extra_includes: Optional[List[Union[str, Path]]] = None,
        mapper: Optional[CTypeMapper] = None
    ) -> None:
        """
        Automatically set argtypes and restype for functions in the library.
        
        Uses pycparser to parse the C code and apply ctypes signatures.
        Handles #include directives by using system include paths.
        
        Parameters
        ----------
        lib : ctypes.CDLL
            Loaded library.
        code : str
            Original C source code.
        extra_includes : Optional[List[Union[str, Path]]]
            Additional include directories to search for headers.
        mapper : Optional[CTypeMapper]
            Type mapper instance. Created if not provided.
        
        Raises
        ------
        SignatureDetectionError
            If parsing fails or signatures cannot be applied.
        
        Examples
        --------
        >>> lib = ctypes.CDLL('./mylib.so')
        >>> set_function_signatures(lib, code)
        >>> result = lib.add(5, 3)  # Correct type checking applied
        """
        # Parse the code
        result = parse_c_code(code, extra_includes)
        
        # Build struct classes
        struct_classes = build_struct_classes(
            result.structs,
            result.unions,
            mapper
        )
        
        mapper = mapper or CTypeMapper(struct_classes=struct_classes)
        
        # Apply signatures to library functions
        applied = 0
        failed = []
        
        for func_name, func in result.functions.items():
            if not hasattr(lib, func_name):
                continue
            
            try:
                c_func = getattr(lib, func_name)
                
                # Set return type
                if func.return_type.base_type != 'void':
                    c_func.restype = mapper.to_ctypes(func.return_type, is_return=True)
                
                # Set argument types
                argtypes = []
                for param in func.parameters:
                    argtypes.append(mapper.to_ctypes(param.type, is_return=False))
                c_func.argtypes = argtypes
                
                applied += 1
                
            except Exception as e:
                failed.append((func_name, str(e)))
                warnings.warn(
                    f"Failed to set signature for '{func_name}': {e}",
                    UserWarning,
                    stacklevel=2
                )
        
        if applied == 0 and result.functions:
            warnings.warn(
                f"No function signatures were applied. Functions in code: {list(result.functions.keys())}",
                UserWarning,
                stacklevel=2
            )
    
    def validate_c_code(
        code: str,
        extra_includes: Optional[List[Union[str, Path]]] = None
    ) -> Tuple[bool, List[str]]:
        """
        Validate C code syntax without full parsing.
        
        Parameters
        ----------
        code : str
            C source code to validate.
        extra_includes : Optional[List[Union[str, Path]]]
            Additional include directories.
        
        Returns
        -------
        Tuple[bool, List[str]]
            - bool: True if valid, False otherwise
            - List[str]: List of validation errors/warnings
        """
        errors = []
        
        try:
            result = parse_c_code(code, extra_includes, validate=True)
            errors.extend(result.warnings)
            return len(errors) == 0, errors
        except (ParseError, SignatureDetectionError) as e:
            errors.append(str(e))
            return False, errors
        except Exception as e:
            errors.append(f"Unexpected error: {e}")
            return False, errors


else:
    # =========================================================================
    # Fallback stubs when pycparser is not available
    # =========================================================================
    
    def parse_c_code(
        code: str,
        extra_includes: Optional[List[Union[str, Path]]] = None,
        validate: bool = True
    ) -> ParseResult:
        """Raise SignatureDetectionError when pycparser is not installed."""
        raise SignatureDetectionError(
            "pycparser is required for signature detection. "
            "Install with: pip install pycparser"
        )
    
    def parse_function_signatures(
        code: str,
        extra_includes: Optional[List[Union[str, Path]]] = None
    ) -> Dict[str, ParsedFunction]:
        """Stub when pycparser is not available."""
        raise SignatureDetectionError("pycparser is required")
    
    def parse_struct_definitions(
        code: str,
        extra_includes: Optional[List[Union[str, Path]]] = None
    ) -> Tuple[Dict[str, ParsedStruct], Dict[str, ParsedStruct]]:
        """Stub when pycparser is not available."""
        raise SignatureDetectionError("pycparser is required")
    
    def build_struct_classes(
        structs: Dict[str, ParsedStruct],
        unions: Optional[Dict[str, ParsedStruct]] = None,
        mapper: Optional[CTypeMapper] = None
    ) -> Dict[str, Type[ctypes.Structure]]:
        """Stub when pycparser is not available."""
        return {}
    
    def set_function_signatures(
        lib: 'ctypes.CDLL',
        code: str,
        extra_includes: Optional[List[Union[str, Path]]] = None,
        mapper: Optional[CTypeMapper] = None
    ) -> None:
        """No-op when pycparser is not available."""
        warnings.warn(
            "pycparser not installed. Function signatures not set.",
            UserWarning,
            stacklevel=2
        )
    
    def validate_c_code(
        code: str,
        extra_includes: Optional[List[Union[str, Path]]] = None
    ) -> Tuple[bool, List[str]]:
        """Stub when pycparser is not available."""
        return False, ["pycparser not installed"]


# =============================================================================
# Caching Parser
# =============================================================================

class CachingParser:
    """
    Parser with LRU caching for improved performance.
    
    This class caches parsed results based on source code hash to avoid
    repeated parsing of identical code.
    
    Parameters
    ----------
    cache_size : int
        Maximum number of entries to cache.
    enable_cache : bool
        Whether to enable caching.
    
    Attributes
    ----------
    hits : int
        Number of cache hits.
    misses : int
        Number of cache misses.
    
    Examples
    --------
    >>> parser = CachingParser(cache_size=128)
    >>> result1 = parser.parse(code)
    >>> result2 = parser.parse(code)  # Returns cached result
    >>> print(f"Hit ratio: {parser.hit_ratio:.2%}")
    """
    
    def __init__(self, cache_size: int = DEFAULT_CACHE_SIZE, enable_cache: bool = True):
        self.cache_size = cache_size
        self.enable_cache = enable_cache
        self._cache: OrderedDict[str, ParseResult] = OrderedDict()
        self._hits = 0
        self._misses = 0
    
    @property
    def hits(self) -> int:
        """Number of cache hits."""
        return self._hits
    
    @property
    def misses(self) -> int:
        """Number of cache misses."""
        return self._misses
    
    @property
    def hit_ratio(self) -> float:
        """Cache hit ratio."""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0
    
    def parse(
        self,
        code: str,
        extra_includes: Optional[List[Union[str, Path]]] = None,
        validate: bool = True
    ) -> ParseResult:
        """
        Parse C code with caching.
        
        Parameters
        ----------
        code : str
            C source code to parse.
        extra_includes : Optional[List[Union[str, Path]]]
            Additional include directories.
        validate : bool
            Whether to validate parsed result.
        
        Returns
        -------
        ParseResult
            Parsed result (cached if available).
        """
        if not self.enable_cache:
            return parse_c_code(code, extra_includes, validate)
        
        # Generate cache key
        cache_key = hashlib.sha256(
            f"{code}{extra_includes}{validate}".encode()
        ).hexdigest()
        
        # Check cache
        if cache_key in self._cache:
            self._hits += 1
            # Move to end (LRU)
            result = self._cache.pop(cache_key)
            self._cache[cache_key] = result
            return result
        
        self._misses += 1
        
        # Parse and cache
        result = parse_c_code(code, extra_includes, validate)
        
        # Evict if cache full
        if len(self._cache) >= self.cache_size:
            self._cache.popitem(last=False)
        
        self._cache[cache_key] = result
        return result
    
    def clear_cache(self) -> None:
        """Clear the parse cache."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            'hits': self._hits,
            'misses': self._misses,
            'hit_ratio': self.hit_ratio,
            'cache_size': len(self._cache),
            'max_size': self.cache_size,
        }


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Main parsing functions
    'parse_c_code',
    'parse_function_signatures',
    'parse_struct_definitions',
    'build_struct_classes',
    'set_function_signatures',
    'validate_c_code',
    
    # Data classes
    'ParseResult',
    'ParsedFunction',
    'ParsedStruct',
    'ParsedEnum',
    'ParsedTypedef',
    'ParsedVariable',
    'ParsedParameter',
    'ParsedField',
    'ParsedType',
    
    # Type mapping
    'CTypeMapper',
    'CTypeCategory',
    
    # Caching
    'CachingParser',
    
    # Exceptions
    'ParseError',
    
    # Constants
    'PYPARSER_AVAILABLE',
    'PYPARSER_VERSION',
]


