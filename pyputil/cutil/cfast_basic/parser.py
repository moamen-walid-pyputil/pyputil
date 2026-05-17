#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Optional C code parsing using pycparser with proper include path handling.

This module provides functionality for parsing C source code and extracting
function signatures and struct definitions. It uses the ``pycparser`` library
when available, and provides graceful fallbacks when it is not installed.

The main functions are:
    - :func:`parse_c_code`: Extract function and struct definitions from C code
    - :func:`set_function_signatures`: Automatically configure ctypes function signatures

If pycparser is not available, all functions will raise :exc:`SignatureDetectionError`
or become no-ops.

Examples
--------
>>> from cfast_basic.parser import parse_c_code, set_function_signatures
>>> code = '''
...     int add(int a, int b) { return a + b; }
...     struct Point { double x; double y; };
... '''
>>> functions, structs = parse_c_code(code)
>>> print(f"Found functions: {list(functions.keys())}")
Found functions: ['add']
>>> print(f"Found structs: {list(structs.keys())}")
Found structs: ['Point']
"""

import tempfile
import warnings
from pathlib import Path
from typing import Dict, Tuple, Any, List, Optional, Union
import ctypes

from .exceptions import SignatureDetectionError
from .platform import PlatformInfo

# Attempt to import pycparser
try:
    from pycparser import c_ast, parse_file, c_parser, c_generator
    from pycparser.plyparser import ParseError
    PYPARSER_AVAILABLE = True
except ImportError:
    PYPARSER_AVAILABLE = False
    # Create dummy classes for type hints when pycparser is not available
    class c_ast:  # type: ignore
        """Dummy module for type hints when pycparser is not installed."""
        pass


# Type mapping from C basic types to ctypes
_C_TYPE_MAP = {
    'int': ctypes.c_int,
    'char': ctypes.c_char,
    'short': ctypes.c_short,
    'long': ctypes.c_long,
    'long long': ctypes.c_longlong,
    'float': ctypes.c_float,
    'double': ctypes.c_double,
    'void': None,
    'size_t': ctypes.c_size_t,
    'ssize_t': ctypes.c_ssize_t,
    'ptrdiff_t': ctypes.c_ssize_t,  # Approximation
    'int8_t': ctypes.c_int8,
    'int16_t': ctypes.c_int16,
    'int32_t': ctypes.c_int32,
    'int64_t': ctypes.c_int64,
    'uint8_t': ctypes.c_uint8,
    'uint16_t': ctypes.c_uint16,
    'uint32_t': ctypes.c_uint32,
    'uint64_t': ctypes.c_uint64,
}

# Unsigned variants
_C_TYPE_MAP.update({
    'unsigned int': ctypes.c_uint,
    'unsigned char': ctypes.c_ubyte,
    'unsigned short': ctypes.c_ushort,
    'unsigned long': ctypes.c_ulong,
    'unsigned long long': ctypes.c_ulonglong,
})


def _get_pycparser_preprocessor_args(
    extra_includes: Optional[List[str]] = None
) -> List[str]:
    """
    Get preprocessor arguments for pycparser, including system and Python paths.

    Parameters
    ----------
    extra_includes : list of str, optional
        Additional include directories to add.

    Returns
    -------
    list of str
        Preprocessor arguments for pycparser (e.g., ``['-E', '-I/path/to/include']``).
    """
    cpp_args = ['-E']

    # Add Python and system include paths
    cpp_args.extend(PlatformInfo.python_include_args())

    # Add any extra includes
    if extra_includes:
        for inc in extra_includes:
            cpp_args.append(f"-I{inc}")

    return cpp_args


def _wrap_code_for_pycparser(code: str) -> str:
    """
    Wrap C code with fake definitions to help pycparser handle standard headers.

    Pycparser does not include standard C library headers. This function
    prepends fake typedefs for common types to allow parsing of code that
    includes standard headers.

    Parameters
    ----------
    code : str
        The original C source code.

    Returns
    -------
    str
        The wrapped C source code.
    """
    fake_definitions = """
/* Pycparser helper: fake definitions for standard headers */
#ifndef __STDIO_LOADED
#define __STDIO_LOADED
typedef struct FILE FILE;
typedef long fpos_t;
#endif

#ifndef __STDDEF_LOADED
#define __STDDEF_LOADED
typedef unsigned long size_t;
typedef long ptrdiff_t;
typedef long ssize_t;
#define NULL ((void*)0)
#endif

#ifndef __STDINT_LOADED
#define __STDINT_LOADED
typedef signed char int8_t;
typedef short int16_t;
typedef int int32_t;
typedef long long int64_t;
typedef unsigned char uint8_t;
typedef unsigned short uint16_t;
typedef unsigned int uint32_t;
typedef unsigned long long uint64_t;
#endif

#ifndef __STDBOOL_LOADED
#define __STDBOOL_LOADED
#define bool _Bool
#define true 1
#define false 0
#endif

"""
    return fake_definitions + code


if PYPARSER_AVAILABLE:
    def parse_c_code(
        code: str,
        extra_includes: Optional[List[str]] = None
    ) -> Tuple[Dict[str, Tuple[Any, List[Any]]], Dict[str, List[Tuple[str, Any]]]]:
        """
        Parse C source code and extract function signatures and struct definitions.

        This function uses pycparser to analyze the C code and extract:
            - Function definitions (name, return type, parameter types)
            - Function declarations (prototypes)
            - Struct definitions (name, field names and types)

        Parameters
        ----------
        code : str
            The complete C source code to parse.
        extra_includes : list of str, optional
            Additional include directories to search for header files referenced
            by ``#include`` directives.

        Returns
        -------
        functions : dict
            Dictionary mapping function names to tuples of
            ``(return_type_node, list_of_parameter_type_nodes)``.
        structs : dict
            Dictionary mapping struct names to lists of
            ``(field_name, field_type_node)``.

        Raises
        ------
        SignatureDetectionError
            If parsing fails due to syntax errors, missing headers, or
            other pycparser issues.

        Notes
        -----
        This function writes the code to a temporary file because pycparser's
        ``parse_file`` expects a file path. The temporary file is cleaned up
        automatically.

        Examples
        --------
        >>> code = '''
        ...     int add(int a, int b) { return a + b; }
        ...     double multiply(double x, double y);
        ...     struct Point { int x; int y; };
        ... '''
        >>> functions, structs = parse_c_code(code)
        >>> 'add' in functions
        True
        >>> 'multiply' in functions
        True
        >>> 'Point' in structs
        True
        """
        cpp_args = _get_pycparser_preprocessor_args(extra_includes)
        wrapped_code = _wrap_code_for_pycparser(code)

        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.c',
            encoding='utf-8',
            delete=False
        ) as f:
            f.write(wrapped_code)
            temp_file = f.name

        try:
            ast = parse_file(temp_file, use_cpp=True, cpp_args=cpp_args)
            functions: Dict[str, Tuple[Any, List[Any]]] = {}
            structs: Dict[str, List[Tuple[str, Any]]] = {}

            for node in ast.ext:
                # Function definitions
                if isinstance(node, c_ast.FuncDef):
                    decl = node.decl
                    func_name = decl.name
                    restype = decl.type.type
                    params = []
                    if decl.type.args:
                        for param in decl.type.args.params:
                            params.append(param.type)
                    functions[func_name] = (restype, params)

                # Declarations (function prototypes, structs, variables)
                elif isinstance(node, c_ast.Decl):
                    # Struct definitions
                    if isinstance(node.type, c_ast.Struct) and node.type.name:
                        struct_node = node.type
                        struct_name = struct_node.name
                        members: List[Tuple[str, Any]] = []
                        if struct_node.decls:
                            for member in struct_node.decls:
                                if member.name:
                                    members.append((member.name, member.type))
                        structs[struct_name] = members

                    # Function declarations (prototypes without bodies)
                    elif isinstance(node.type, c_ast.FuncDecl):
                        func_name = node.name
                        restype = node.type.type
                        params = []
                        if node.type.args:
                            for param in node.type.args.params:
                                params.append(param.type)
                        functions[func_name] = (restype, params)

            return functions, structs

        except ParseError as e:
            raise SignatureDetectionError(
                f"Failed to parse C code (likely due to missing headers or syntax error): {e}"
            ) from e
        except Exception as e:
            raise SignatureDetectionError(
                f"Unexpected error during C code parsing: {e}"
            ) from e
        finally:
            # Clean up temporary file
            Path(temp_file).unlink(missing_ok=True)

    def _c_type_to_ctypes(
        c_type: Any,
        struct_classes: Dict[str, type],
        is_return: bool = False
    ) -> Any:
        """
        Convert a pycparser type node to a ctypes type.

        This function recursively traverses the pycparser AST type node and
        constructs the equivalent ctypes type. It handles:
            - Basic types (int, char, float, double, etc.)
            - Pointers (``*``)
            - Arrays (``[]``)
            - Structs (``struct name``)
            - Function pointers

        Parameters
        ----------
        c_type : pycparser.c_ast.Node
            The type node from the pycparser AST.
        struct_classes : dict
            Dictionary mapping struct names to ctypes.Structure classes.
            Used for resolving struct types.
        is_return : bool, default False
            If True, arrays are treated as pointers (as they decay to pointers
            when returned from functions).

        Returns
        -------
        ctypes type or None
            The corresponding ctypes type. Returns None for ``void`` return types.
            Returns ``ctypes.c_void_p`` for unrecognized types.

        Notes
        -----
        Unrecognized types are mapped to ``ctypes.c_void_p`` with a warning.
        """
        # Handle TypeDecl (wrapper around the actual type)
        if isinstance(c_type, c_ast.TypeDecl):
            return _c_type_to_ctypes(c_type.type, struct_classes, is_return)

        # Basic types (IdentifierType)
        if isinstance(c_type, c_ast.IdentifierType):
            names = c_type.names
            type_str = ' '.join(names)

            # Check the type map
            if type_str in _C_TYPE_MAP:
                return _C_TYPE_MAP[type_str]

            # Special case: FILE* (opaque type)
            if 'FILE' in names:
                return ctypes.c_void_p

            # Unrecognized type - fall back to void*
            warnings.warn(
                f"Unrecognized C type '{type_str}'. Falling back to c_void_p.",
                UserWarning,
                stacklevel=3
            )
            return ctypes.c_void_p

        # Pointers (PtrDecl)
        if isinstance(c_type, c_ast.PtrDecl):
            pointed = _c_type_to_ctypes(c_type.type, struct_classes, is_return=False)
            if pointed is None:
                return ctypes.c_void_p
            return ctypes.POINTER(pointed)

        # Arrays (ArrayDecl)
        if isinstance(c_type, c_ast.ArrayDecl):
            elem_type = _c_type_to_ctypes(c_type.type, struct_classes, is_return=False)

            # Arrays in return types decay to pointers
            if is_return:
                return ctypes.POINTER(elem_type)

            # Check if we have a constant size
            if c_type.dim and isinstance(c_type.dim, c_ast.Constant):
                try:
                    size = int(c_type.dim.value)
                    return elem_type * size
                except (ValueError, TypeError):
                    pass

            # Variable-length array or unknown size - treat as pointer
            return ctypes.POINTER(elem_type)

        # Structs (Struct)
        if isinstance(c_type, c_ast.Struct):
            struct_name = c_type.name
            if struct_name in struct_classes:
                return struct_classes[struct_name]
            # Forward declaration or opaque struct
            return ctypes.c_void_p

        # Enums (Enum)
        if isinstance(c_type, c_ast.Enum):
            # C enums are compatible with int
            return ctypes.c_int

        # Typedefs (Typedef)
        if isinstance(c_type, c_ast.Typedef):
            return _c_type_to_ctypes(c_type.type, struct_classes, is_return)

        # Function pointers (FuncDecl)
        if isinstance(c_type, c_ast.FuncDecl):
            # Function pointers are represented as c_void_p for simplicity
            # Full function pointer support would require CFUNCTYPE
            return ctypes.c_void_p

        # Fallback for unhandled types
        warnings.warn(
            f"Unhandled C type node: {type(c_type).__name__}. Falling back to c_void_p.",
            UserWarning,
            stacklevel=3
        )
        return ctypes.c_void_p

    def build_struct_classes(structs: Dict[str, List[Tuple[str, Any]]]) -> Dict[str, type]:
        """
        Build ctypes.Structure classes from parsed struct definitions.

        This function performs a two-pass construction to handle self-referential
        and mutually recursive structs (e.g., linked lists, trees).

        Parameters
        ----------
        structs : dict
            Dictionary mapping struct names to lists of (field_name, field_type_node)
            as returned by :func:`parse_c_code`.

        Returns
        -------
        dict
            Dictionary mapping struct names to the constructed
            ``ctypes.Structure`` subclasses.

        Notes
        -----
        Two-pass algorithm:
            1. Create empty Structure classes for all struct names
            2. Populate ``_fields_`` attribute for each class (now all types exist)

        Examples
        --------
        >>> _, structs = parse_c_code('''
        ...     struct Node { int value; struct Node* next; };
        ...     struct Point { double x; double y; };
        ... ''')
        >>> classes = build_struct_classes(structs)
        >>> Node = classes['Node']
        >>> Point = classes['Point']
        >>> issubclass(Node, ctypes.Structure)
        True
        """
        # Phase 1: Create empty classes
        classes: Dict[str, type] = {}
        for name in structs:
            classes[name] = type(name, (ctypes.Structure,), {})

        # Phase 2: Fill _fields_ (now all classes exist for cross-references)
        for name, members in structs.items():
            fields: List[Tuple[str, Any]] = []
            for field_name, field_type in members:
                ctype = _c_type_to_ctypes(field_type, classes, is_return=False)
                fields.append((field_name, ctype))
            classes[name]._fields_ = fields

        return classes

    def set_function_signatures(
        lib: ctypes.CDLL,
        code: str,
        extra_includes: Optional[List[str]] = None
    ) -> None:
        """
        Automatically set argtypes and restype for functions in a ctypes library.

        This function uses pycparser to parse the C source code, extracts function
        signatures and struct definitions, and applies the appropriate ctypes
        type annotations to the loaded library.

        Parameters
        ----------
        lib : ctypes.CDLL
            The loaded shared library object.
        code : str
            The original C source code used to compile the library.
        extra_includes : list of str, optional
            Additional include directories that were used for compilation,
            needed for pycparser to find referenced headers.

        Raises
        ------
        SignatureDetectionError
            If parsing fails or if type conversion encounters an unrecoverable error.

        Notes
        -----
        This function modifies the library object in-place. After calling this
        function, you can call the C functions with Python types, and ctypes
        will automatically convert arguments and return values.

        Examples
        --------
        >>> import ctypes
        >>> from cfast_basic import load_c
        >>> code = '''
        ...     int add(int a, int b) { return a + b; }
        ...     double multiply(double x, double y) { return x * y; }
        ... '''
        >>> lib = load_c(code, auto_signatures=False)  # Disable auto in load_c
        >>> set_function_signatures(lib, code)
        >>> result = lib.add(3, 5)  # Automatic int conversion
        >>> print(result)
        8
        """
        functions, structs = parse_c_code(code, extra_includes)
        struct_classes = build_struct_classes(structs)

        for func_name, (restype_node, param_nodes) in functions.items():
            if hasattr(lib, func_name):
                c_func = getattr(lib, func_name)
                try:
                    # Set return type
                    restype = _c_type_to_ctypes(
                        restype_node, struct_classes, is_return=True
                    )
                    c_func.restype = restype

                    # Set argument types
                    argtypes = []
                    for param_node in param_nodes:
                        argtype = _c_type_to_ctypes(
                            param_node, struct_classes, is_return=False
                        )
                        argtypes.append(argtype)
                    c_func.argtypes = argtypes

                except Exception as e:
                    warnings.warn(
                        f"Failed to set signature for '{func_name}': {e}. "
                        "This function will require manual type configuration.",
                        UserWarning,
                        stacklevel=2
                    )
            else:
                warnings.warn(
                    f"Function '{func_name}' declared in source but not found in library. "
                    "It may be static or not exported.",
                    UserWarning,
                    stacklevel=2
                )

else:
    # Fallback implementations when pycparser is not available

    def parse_c_code(
        code: str,
        extra_includes: Optional[List[str]] = None
    ) -> Tuple[Dict, Dict]:
        """
        Stub implementation when pycparser is not available.

        Raises
        ------
        SignatureDetectionError
            Always raised, indicating pycparser is required.
        """
        raise SignatureDetectionError(
            "pycparser is not installed. "
            "Install it with: pip install pycparser"
        )

    def set_function_signatures(
        lib: ctypes.CDLL,
        code: str,
        extra_includes: Optional[List[str]] = None
    ) -> None:
        """
        No-op implementation when pycparser is not available.

        This function does nothing and logs a debug message.
        """
        import logging
        logging.getLogger(__name__).debug(
            "set_function_signatures called but pycparser is not available. "
            "Skipping automatic signature configuration."
        )

    def build_struct_classes(structs: Dict) -> Dict[str, type]:
        """Stub implementation when pycparser is not available."""
        raise SignatureDetectionError(
            "pycparser is not installed. Cannot build struct classes."
        )