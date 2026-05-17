#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Decorator interface for cfast.

Provides elegant decorator syntax for defining and using C functions inline
within Python code. Supports multiple patterns including docstring-based,
body-based, and explicit code string decorators.

Decorator Patterns
------------------
@cfunc
    Basic decorator using function name as C function name.

@cfunc(name="custom_name")
    Specify explicit C function name.

@cfunc(libraries=["m"], cflags=["-O3"])
    Pass compilation options.

@cfunc_from_string(code)
    Provide C code as explicit string.

@cstruct
    Define C struct types as Python classes.

@cenum
    Define C enum constants as Python classes.

Examples
--------
>>> from cfast.decorators import cfunc, cstruct

>>> # Basic usage with docstring
>>> @cfunc
... def add(a: int, b: int) -> int:
...     '''
...     int add(int a, int b) {
...         return a + b;
...     }
...     '''
>>> add(5, 3)  # Returns 8

>>> # Multiple functions with explicit name
>>> @cfunc(name="factorial", cflags=["-O3"])
... def fact(n: int) -> int:
...     '''
...     int factorial(int n) {
...         if (n <= 1) return 1;
...         return n * factorial(n - 1);
...     }
...     '''
>>> fact(5)  # Returns 120

>>> # Struct definition
>>> @cstruct
... class Point:
...     '''
...     struct Point {
...         double x;
...         double y;
...     };
...     '''
>>> p = Point(x=10.0, y=20.0)

>>> # Inline C code
>>> @cfunc_inline("int mul(int a, int b) { return a * b; }")
... def multiply(a: int, b: int) -> int: ...
>>> multiply(6, 7)  # Returns 42
"""

import functools
import inspect
import warnings
import textwrap
import ctypes
from typing import (
    Optional, List, Dict, Callable, Any, Union, 
    Type, TypeVar, overload, cast
)
from pathlib import Path

from .core import CFastEngine,  CompileOptions, _get_global_engine
from .exceptions import CompilationError, SignatureDetectionError
from .parser import PYPARSER_AVAILABLE
from .utils import sanitize_identifier, extract_function_names


# Type variable for class decorators
T = TypeVar('T')
C = TypeVar('C', bound=type)


# =============================================================================
# C Function Decorators
# =============================================================================

@overload
def cfunc(func: Callable) -> Callable:
    """Decorator without arguments."""
    ...


@overload
def cfunc(
    *,
    name: Optional[str] = None,
    cflags: Optional[List[str]] = None,
    libraries: Optional[List[str]] = None,
    includes: Optional[List[str]] = None,
    defines: Optional[Dict[str, Optional[str]]] = None,
    link_args: Optional[List[str]] = None,
    extra_includes: Optional[List[str]] = None,
    engine: Optional[CFastEngine] = None,
    options: Optional[CompileOptions] = None,
    cache: bool = True,
    auto_signatures: bool = True,
) -> Callable[[Callable], Callable]:
    """Decorator with keyword arguments."""
    ...


def cfunc(
    func: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    cflags: Optional[List[str]] = None,
    libraries: Optional[List[str]] = None,
    includes: Optional[List[str]] = None,
    defines: Optional[Dict[str, Optional[str]]] = None,
    link_args: Optional[List[str]] = None,
    extra_includes: Optional[List[str]] = None,
    engine: Optional[CFastEngine] = None,
    options: Optional[CompileOptions] = None,
    cache: bool = True,
    auto_signatures: bool = True,
) -> Union[Callable, Callable[[Callable], Callable]]:
    """
    Decorator that compiles a C function from the decorated function's docstring.
    
    This decorator extracts C code from the function's docstring, compiles it,
    and replaces the Python function with a wrapper that calls the compiled
    C function. The Python function signature is preserved for type hints
    and documentation.
    
    Parameters
    ----------
    func : Callable, optional
        The function to decorate (when used without arguments).
    name : str, optional
        Name of the C function to extract. If None, uses the decorated
        Python function's name.
    cflags : list of str, optional
        Compiler flags to pass to the compiler.
    libraries : list of str, optional
        Libraries to link against (e.g., ['m', 'pthread']).
    includes : list of str, optional
        Additional include directories for compilation.
    defines : dict, optional
        Preprocessor macro definitions. Values may be None for definition-only.
    link_args : list of str, optional
        Additional linker arguments.
    extra_includes : list of str, optional
        Additional include directories for signature detection only.
    engine : CFastEngine, optional
        Engine instance to use. If None, uses global singleton.
    options : CompileOptions, optional
        Compilation options object (overrides individual options).
    cache : bool, default True
        Whether to cache the compiled library.
    auto_signatures : bool, default True
        Whether to automatically detect and set function signatures.
    
    Returns
    -------
    callable
        Decorated function that calls the compiled C code.
    
    Raises
    ------
    ValueError
        If no C code is found in the docstring.
    CompilationError
        If compilation fails.
    AttributeError
        If the specified function name is not found in the compiled code.
    
    Examples
    --------
    >>> @cfunc
    ... def add(a: int, b: int) -> int:
    ...     '''
    ...     int add(int a, int b) {
    ...         return a + b;
    ...     }
    ...     '''
    >>> add(3, 5)
    8
    
    >>> @cfunc(name="vector_length", libraries=["m"], cflags=["-O3"])
    ... def length(x: float, y: float) -> float:
    ...     '''
    ...     #include <math.h>
    ...     double vector_length(double x, double y) {
    ...         return sqrt(x*x + y*y);
    ...     }
    ...     '''
    >>> length(3.0, 4.0)
    5.0
    
    >>> # With explicit CompileOptions
    >>> opts = CompileOptions(optimization_level=3, debug=True)
    >>> @cfunc(options=opts)
    ... def fast_add(a: int, b: int) -> int:
    ...     '''int fast_add(int a, int b) { return a + b; }'''
    """
    def decorator(f: Callable) -> Callable:
        return _create_c_function_wrapper(
            func=f,
            name=name or f.__name__,
            cflags=cflags,
            libraries=libraries,
            includes=includes,
            defines=defines,
            link_args=link_args,
            extra_includes=extra_includes,
            engine=engine,
            options=options,
            cache=cache,
            auto_signatures=auto_signatures,
        )
    
    # Handle both @cfunc and @cfunc(...) usage
    if func is not None:
        return decorator(func)
    return decorator


def _create_c_function_wrapper(
    func: Callable,
    name: str,
    cflags: Optional[List[str]] = None,
    libraries: Optional[List[str]] = None,
    includes: Optional[List[str]] = None,
    defines: Optional[Dict[str, Optional[str]]] = None,
    link_args: Optional[List[str]] = None,
    extra_includes: Optional[List[str]] = None,
    engine: Optional[CFastEngine] = None,
    options: Optional[CompileOptions] = None,
    cache: bool = True,
    auto_signatures: bool = True,
) -> Callable:
    """
    Create a wrapper function that calls compiled C code.
    
    Parameters
    ----------
    func : Callable
        The Python function being decorated.
    name : str
        Name of the C function to extract.
    cflags, libraries, includes, defines, link_args : optional
        Compilation options.
    extra_includes : optional
        Include paths for signature detection.
    engine : optional
        CFastEngine instance.
    options : optional
        CompileOptions object.
    cache : bool
        Whether to cache the compiled library.
    auto_signatures : bool
        Whether to auto-detect signatures.
    
    Returns
    -------
    Callable
        Wrapper function that calls the C function.
    """
    # Extract C code from docstring or source
    code = _extract_c_code_from_function(func)
    
    if not code or not code.strip():
        raise ValueError(
            f"Function '{func.__name__}' must have a docstring containing C code, "
            "or use @cfunc_inline with explicit code."
        )
    
    # Get or create engine
    eng = engine or _get_global_engine()
    
    # Build options
    if options is None:
        options = CompileOptions(
            cflags=cflags or [],
            libraries=libraries or [],
            includes=includes or [],
            defines=defines or {},
            link_args=link_args or [],
        )
    
    # Compile and get function
    try:
        c_func = eng.get_function(
            code=code,
            func_name=name,
            options=options,
            extra_includes=extra_includes,
        )
    except CompilationError as e:
        raise CompilationError(
            f"Failed to compile C function '{name}' from decorator '{func.__name__}':\n{e}"
        ) from e
    except AttributeError as e:
        # Try to provide helpful error message
        available = []
        if PYPARSER_AVAILABLE:
            try:
                from .parser import parse_c_code
                result = parse_c_code(code)
                available = list(result.functions.keys())
            except Exception:
                available = extract_function_names(code)
        
        raise AttributeError(
            f"C function '{name}' not found in compiled code.\n"
            f"Available functions: {', '.join(available) if available else 'none detected'}\n"
            f"Make sure the function name matches exactly."
        ) from e
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        """Wrapper that calls the compiled C function."""
        return c_func(*args, **kwargs)
    
    # Attach metadata to wrapper
    wrapper._cfast_code = code
    wrapper._cfast_name = name
    wrapper._cfast_compiled = True
    
    return wrapper


def _extract_c_code_from_function(func: Callable) -> str:
    """
    Extract C code from a function's docstring or body.
    
    Parameters
    ----------
    func : Callable
        The function to extract code from.
    
    Returns
    -------
    str
        Extracted C code.
    """
    # Try docstring first
    if func.__doc__:
        return inspect.cleandoc(func.__doc__)
    
    # Fallback: try to extract from source code (for inline usage)
    try:
        source = inspect.getsource(func)
        
        # Look for string literal in function body
        import ast
        tree = ast.parse(source)
        if isinstance(tree.body[0], ast.FunctionDef):
            func_def = tree.body[0]
            for node in func_def.body:
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Str):
                    return inspect.cleandoc(node.value.s)
    except (OSError, TypeError, SyntaxError):
        pass
    
    return ""


def cfunc_inline(
    code: str,
    name: Optional[str] = None,
    cflags: Optional[List[str]] = None,
    libraries: Optional[List[str]] = None,
    includes: Optional[List[str]] = None,
    defines: Optional[Dict[str, Optional[str]]] = None,
    extra_includes: Optional[List[str]] = None,
    engine: Optional[CFastEngine] = None,
    options: Optional[CompileOptions] = None,
) -> Callable[[Callable], Callable]:
    """
    Decorator that compiles C code provided as an explicit string.
    
    This variant allows you to provide the C code directly as an argument
    to the decorator, without requiring a docstring.
    
    Parameters
    ----------
    code : str
        The C source code to compile.
    name : str, optional
        Name of the C function to extract. If None, uses the decorated
        Python function's name.
    cflags, libraries, includes, defines : optional
        Compilation options.
    extra_includes : optional
        Include paths for signature detection.
    engine : CFastEngine, optional
        Engine instance to use.
    options : CompileOptions, optional
        Compilation options object.
    
    Returns
    -------
    callable
        Decorator that returns the wrapper function.
    
    Examples
    --------
    >>> @cfunc_inline("int add(int a, int b) { return a + b; }")
    ... def add(a: int, b: int) -> int:
    ...     '''This docstring is for Python documentation only.'''
    ...     # The function body is never executed
    ...     pass
    >>> add(3, 5)
    8
    
    >>> @cfunc_inline(
    ...     '''
    ...     #include <math.h>
    ...     double distance(double x1, double y1, double x2, double y2) {
    ...         double dx = x2 - x1;
    ...         double dy = y2 - y1;
    ...         return sqrt(dx*dx + dy*dy);
    ...     }
    ...     ''',
    ...     libraries=["m"]
    ... )
    ... def dist(x1: float, y1: float, x2: float, y2: float) -> float:
    ...     pass
    >>> dist(0, 0, 3, 4)
    5.0
    """
    def decorator(func: Callable) -> Callable:
        return _create_c_function_wrapper(
            func=func,
            name=name or func.__name__,
            cflags=cflags,
            libraries=libraries,
            includes=includes,
            defines=defines,
            extra_includes=extra_includes,
            engine=engine,
            options=options,
        )
    
    return decorator


def cfunc_from_file(
    filepath: Union[str, Path],
    name: Optional[str] = None,
    cflags: Optional[List[str]] = None,
    libraries: Optional[List[str]] = None,
    includes: Optional[List[str]] = None,
    defines: Optional[Dict[str, Optional[str]]] = None,
    encoding: str = 'utf-8',
    engine: Optional[CFastEngine] = None,
) -> Callable[[Callable], Callable]:
    """
    Decorator that compiles C code from a file.
    
    Parameters
    ----------
    filepath : Union[str, Path]
        Path to the C source file.
    name : str, optional
        Name of the C function to extract. If None, uses function name.
    cflags, libraries, includes, defines : optional
        Compilation options.
    encoding : str, default 'utf-8'
        File encoding.
    engine : CFastEngine, optional
        Engine instance to use.
    
    Returns
    -------
    callable
        Decorator that returns the wrapper function.
    
    Examples
    --------
    >>> @cfunc_from_file("math_utils.c", name="add")
    ... def add_numbers(a: int, b: int) -> int:
    ...     '''Python wrapper for C add function from file.'''
    ...     pass
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"C source file not found: {path}")
    
    code = path.read_text(encoding=encoding)
    
    def decorator(func: Callable) -> Callable:
        return _create_c_function_wrapper(
            func=func,
            name=name or func.__name__,
            cflags=cflags,
            libraries=libraries,
            includes=includes,
            defines=defines,
            engine=engine,
        )
    
    return decorator


# =============================================================================
# Struct and Enum Decorators
# =============================================================================

def cstruct(
    cls: Optional[Type] = None,
    *,
    name: Optional[str] = None,
    cflags: Optional[List[str]] = None,
    libraries: Optional[List[str]] = None,
    includes: Optional[List[str]] = None,
    defines: Optional[Dict[str, Optional[str]]] = None,
    engine: Optional[CFastEngine] = None,
    auto_fields: bool = True,
) -> Union[Type, Callable[[Type], Type]]:
    """
    Decorator that creates a ctypes Structure class from C struct definition.
    
    The C struct definition should be provided in the class docstring.
    The resulting class can be instantiated like a normal Python class
    but uses ctypes.Structure as its base.
    
    Parameters
    ----------
    cls : Type, optional
        The class to decorate.
    name : str, optional
        Name of the C struct to extract. If None, uses class name.
    cflags, libraries, includes, defines : optional
        Compilation options (if struct depends on other code).
    engine : CFastEngine, optional
        Engine instance to use.
    auto_fields : bool, default True
        Whether to automatically create property accessors for fields.
    
    Returns
    -------
    Type
        A class that inherits from ctypes.Structure with the defined fields.
    
    Examples
    --------
    >>> @cstruct
    ... class Point:
    ...     '''
    ...     struct Point {
    ...         double x;
    ...         double y;
    ...     };
    ...     '''
    >>> p = Point(x=10.0, y=20.0)
    >>> p.x, p.y
    (10.0, 20.0)
    
    >>> @cstruct(name="Vector3")
    ... class Vec3:
    ...     '''
    ...     struct Vector3 {
    ...         float x, y, z;
    ...     };
    ...     '''
    ...     def length(self):
    ...         return (self.x**2 + self.y**2 + self.z**2)**0.5
    """
    def decorator(c: Type) -> Type:
        return _create_struct_class(
            cls=c,
            name=name or c.__name__,
            cflags=cflags,
            libraries=libraries,
            includes=includes,
            defines=defines,
            engine=engine,
            auto_fields=auto_fields,
        )
    
    if cls is not None:
        return decorator(cls)
    return decorator


def _create_struct_class(
    cls: Type,
    name: str,
    cflags: Optional[List[str]] = None,
    libraries: Optional[List[str]] = None,
    includes: Optional[List[str]] = None,
    defines: Optional[Dict[str, Optional[str]]] = None,
    engine: Optional[CFastEngine] = None,
    auto_fields: bool = True,
) -> Type:
    """
    Create a ctypes.Structure subclass from C struct definition.
    
    Parameters
    ----------
    cls : Type
        The original Python class.
    name : str
        Name of the C struct.
    cflags, libraries, includes, defines : optional
        Compilation options.
    engine : optional
        CFastEngine instance.
    auto_fields : bool
        Whether to create property accessors.
    
    Returns
    -------
    Type
        ctypes.Structure subclass.
    """
    if not PYPARSER_AVAILABLE:
        warnings.warn(
            "pycparser is required for struct parsing. "
            "Install with: pip install pycparser",
            UserWarning,
            stacklevel=2
        )
        return cls
    
    # Extract struct definition
    code = _extract_c_code_from_function(cls)
    if not code:
        # Try to get from docstring
        code = cls.__doc__ or ""
    
    # Parse struct
    from .parser import parse_c_code, build_struct_classes
    
    try:
        result = parse_c_code(code)
        
        if name not in result.structs:
            raise ValueError(
                f"Struct '{name}' not found in code. "
                f"Available: {list(result.structs.keys())}"
            )
        
        # Build struct classes
        struct_classes = build_struct_classes(result.structs, result.unions)
        
        if name not in struct_classes:
            raise ValueError(f"Failed to build struct class for '{name}'")
        
        ctypes_struct = struct_classes[name]
        
        # Create a new class that inherits from ctypes_struct and cls
        class CStructWrapper(ctypes_struct, cls):
            """Wrapper combining ctypes struct with Python class."""
            
            def __init__(self, **kwargs):
                super().__init__()
                for key, value in kwargs.items():
                    if hasattr(self, key):
                        setattr(self, key, value)
            
            def __repr__(self):
                fields = []
                for field_name, _ in self._fields_:
                    fields.append(f"{field_name}={getattr(self, field_name)}")
                return f"{self.__class__.__name__}({', '.join(fields)})"
        
        # Copy metadata
        CStructWrapper.__name__ = cls.__name__
        CStructWrapper.__doc__ = cls.__doc__
        CStructWrapper.__module__ = cls.__module__
        
        return CStructWrapper
        
    except Exception as e:
        warnings.warn(f"Failed to parse struct: {e}", UserWarning, stacklevel=2)
        return cls


def cenum(
    cls: Optional[Type] = None,
    *,
    name: Optional[str] = None,
) -> Union[Type, Callable[[Type], Type]]:
    """
    Decorator that creates an IntEnum class from C enum definition.
    
    Parameters
    ----------
    cls : Type, optional
        The class to decorate.
    name : str, optional
        Name of the C enum to extract. If None, uses class name.
    
    Returns
    -------
    Type
        An IntEnum class with the defined constants.
    
    Examples
    --------
    >>> @cenum
    ... class Color:
    ...     '''
    ...     enum Color {
    ...         RED,
    ...         GREEN = 5,
    ...         BLUE
    ...     };
    ...     '''
    >>> Color.RED
    0
    >>> Color.GREEN
    5
    >>> Color.BLUE
    6
    """
    from enum import IntEnum
    
    def decorator(c: Type) -> Type:
        enum_name = name or c.__name__
        code = c.__doc__ or ""
        
        if not PYPARSER_AVAILABLE:
            warnings.warn("pycparser required for enum parsing", UserWarning)
            return c
        
        try:
            from .parser import parse_c_code
            result = parse_c_code(code)
            
            if enum_name in result.enums:
                enum_def = result.enums[enum_name]
                
                # Create IntEnum dynamically
                members = {}
                for member_name, value in enum_def.values.items():
                    members[member_name] = value if value is not None else 0
                
                enum_class = IntEnum(enum_name, members)
                enum_class.__doc__ = c.__doc__
                enum_class.__module__ = c.__module__
                
                return enum_class
        except Exception as e:
            warnings.warn(f"Failed to parse enum: {e}", UserWarning)
        
        return c
    
    if cls is not None:
        return decorator(cls)
    return decorator


# =============================================================================
# Module-Level C Code Decorator
# =============================================================================

def cmodule(
    code: Optional[str] = None,
    *,
    filepath: Optional[Union[str, Path]] = None,
    cflags: Optional[List[str]] = None,
    libraries: Optional[List[str]] = None,
    includes: Optional[List[str]] = None,
    defines: Optional[Dict[str, Optional[str]]] = None,
    engine: Optional[CFastEngine] = None,
    prefix: str = "",
) -> Callable[[Type], Type]:
    """
    Class decorator that compiles C code and attaches functions as methods.
    
    This decorator compiles the provided C code and attaches all exported
    functions as static methods to the decorated class.
    
    Parameters
    ----------
    code : str, optional
        C source code to compile.
    filepath : Union[str, Path], optional
        Path to C source file (alternative to code).
    cflags, libraries, includes, defines : optional
        Compilation options.
    engine : CFastEngine, optional
        Engine instance to use.
    prefix : str, default ""
        Prefix to add to all method names.
    
    Returns
    -------
    callable
        Class decorator.
    
    Examples
    --------
    >>> @cmodule('''
    ...     int add(int a, int b) { return a + b; }
    ...     int mul(int a, int b) { return a * b; }
    ... ''')
    ... class Math:
    ...     '''Math operations from C.'''
    ...     pass
    >>> Math.add(3, 5)
    8
    >>> Math.mul(4, 7)
    28
    """
    def decorator(cls: Type) -> Type:
        eng = engine or _get_global_engine()
        
        # Get code
        if filepath:
            path = Path(filepath)
            if not path.exists():
                raise FileNotFoundError(f"C source file not found: {path}")
            source_code = path.read_text()
        elif code:
            source_code = code
        else:
            source_code = cls.__doc__ or ""
        
        if not source_code:
            raise ValueError("No C code provided")
        
        # Compile and load
        lib = eng.load(
            code=source_code,
            cflags=cflags,
            libraries=libraries,
            includes=includes,
            defines=defines,
        )
        
        # Attach functions as static methods
        for func_name in lib.list_functions():
            if not func_name.startswith('_'):
                method_name = f"{prefix}{func_name}"
                c_func = getattr(lib, func_name)
                setattr(cls, method_name, staticmethod(c_func))
        
        # Store library reference
        cls._cfast_lib = lib
        
        return cls
    
    return decorator


# =============================================================================
# Utility Functions
# =============================================================================

def is_cfunc(obj: Any) -> bool:
    """
    Check if an object is a cfast-compiled function.
    
    Parameters
    ----------
    obj : Any
        Object to check.
    
    Returns
    -------
    bool
        True if obj is a cfast-compiled function.
    """
    return hasattr(obj, '_cfast_compiled') and obj._cfast_compiled


def get_c_code(obj: Any) -> Optional[str]:
    """
    Get the original C code from a cfast-decorated object.
    
    Parameters
    ----------
    obj : Any
        cfast-decorated function or class.
    
    Returns
    -------
    Optional[str]
        The original C code, or None if not available.
    """
    if hasattr(obj, '_cfast_code'):
        return obj._cfast_code
    elif hasattr(obj, '__doc__'):
        return obj.__doc__
    return None


def get_c_name(obj: Any) -> Optional[str]:
    """
    Get the C function name from a cfast-decorated function.
    
    Parameters
    ----------
    obj : Any
        cfast-decorated function.
    
    Returns
    -------
    Optional[str]
        The C function name, or None if not available.
    """
    return getattr(obj, '_cfast_name', None)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Function decorators
    'cfunc',
    'cfunc_inline',
    'cfunc_from_file',
    
    # Struct/Enum decorators
    'cstruct',
    'cenum',
    
    # Module decorator
    'cmodule',
    
    # Utility functions
    'is_cfunc',
    'get_c_code',
    'get_c_name',
]