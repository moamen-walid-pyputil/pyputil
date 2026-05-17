#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
cfast_basic_basic: C Foreign function AST - Compile C code at runtime with ctypes.
This basic version from ``cfast_basic`` it might be faster in load than ``cfast_basic``.

cfast_basic is a Python library that compiles C source code into shared libraries
at runtime and loads them using ctypes. It provides automatic caching, 
cross-platform file locking, and optional automatic function signature 
detection using pycparser.

Main Features
-------------
- Compile C code from strings or files at runtime
- Automatic caching based on source and compilation parameters
- Cross-platform file locking to prevent race conditions
- Automatic function signature detection (requires pycparser)
- Support for GCC, Clang, and MSVC compilers
- System include path detection for standard headers

Basic Usage
-----------
>>> import cfast_basic

>>> # Simple function from a string
>>> add = cfast_basic.cfunc('int add(int a, int b) { return a + b; }')
>>> add(3, 5)
8

>>> # Load a complete library
>>> lib = cfast_basic.load_c('''
...     #include <math.h>
...     double square(double x) { return x * x; }
... ''')
>>> lib.square(4.0)
16.0

>>> # Load from a file
>>> lib = cfast_basic.load_c_file('mylib.c', cflags=['-O3'])

For automatic signature detection, also install pycparser:
pip install pycparser

Environment Variables
---------------------
CFAST_CFLAGS : str
    Default compiler flags (e.g., "-O3 -Wall"). Overrides the built-in default.
CFAST_COMPILER : str
    Preferred compiler name ('gcc', 'clang', 'msvc'). Overrides auto-detection.
CFAST_LIBS : str
    Default libraries to link (space-separated). Overrides the built-in default.
"""

from .core import (
    load_c,
    load_c_file,
    cfunc,
    compile_c_code,
    clear_cache,
    get_cache_info,
    ENGINE_VERSION,
    DEFAULT_CFLAGS,
    DEFAULT_LIBS,
)

from .compiler import (
    Compiler,
    GccCompiler,
    ClangCompiler,
    MsvcCompiler,
    detect_compiler,
)

from .platform import PlatformInfo

from .exceptions import (
    CfastError,
    CompilationError,
    SignatureDetectionError,
    CompilerNotFoundError,
    LockError,
)

from .parser import PYPARSER_AVAILABLE

__all__ = [
    # Main API
    'load_c',
    'load_c_file',
    'cfunc',
    'compile_c_code',
    'clear_cache',
    'get_cache_info',

    # Compiler classes
    'Compiler',
    'GccCompiler',
    'ClangCompiler',
    'MsvcCompiler',
    'detect_compiler',

    # Platform utilities
    'PlatformInfo',

    # Exceptions
    'CfastError',
    'CompilationError',
    'SignatureDetectionError',
    'CompilerNotFoundError',
    'LockError',

    # Constants
    'ENGINE_VERSION',
    'DEFAULT_CFLAGS',
    'DEFAULT_LIBS',
    'PYPARSER_AVAILABLE',
]

from typing import List
def __dir__() -> List[str]:
    """Return list of public attributes for tab completion."""
    return __all__
