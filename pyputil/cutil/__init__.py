#!/usr/bin/env python3

# -*- coding: utf-8 -*-

# =========================
# Standard / Internal Imports
# =========================

from ..api import clean

from . import (
    cimporter,
    cfast,
    cfast_basic,
    liblocator,
)

from .info_extension_module import (
    is_extension_module,
    is_compiled_binary,
    get_module_filename_parts,
    get_module_path,
    clear_spec_cache,
    get_cache_info,
    get_magic_numbers,
    get_current_magic_numbers,
    get_platform_binary_info,
    MAGIC_NUMBERS,
)

from .util import compiled_name


# =========================
# Public API
# =========================

__all__ = [
    # modules
    "cimporter",
    "cfast",
    "cfast_basic",
    "liblocator",

    # functions
    "is_extension_module",
    "is_compiled_binary",
    "get_module_filename_parts",
    "get_module_path",
    "clear_spec_cache",
    "get_cache_info",
    "get_magic_numbers",
    "get_current_magic_numbers",
    "get_platform_binary_info",

    # constants
    "MAGIC_NUMBERS",
]


# =========================
# Cleanup namespace
# =========================

clean(expose=__all__)