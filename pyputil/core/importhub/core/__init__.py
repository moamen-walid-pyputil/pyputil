#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Core module for import system.

This package provides the core functionality for the import module,
including caching, installation, validation, and async support.
"""

from .types import LazyModule, LazyAttributeProxy, ValidationError, ImportConfig
from .parser import parse_target, is_file_path, extract_module_name
from .cache import ImportCache, get_cache, cached_import
from .installer import PackageInstaller, get_installer, install_package
from .loader import ModuleLoader, get_loader
from .validator import ModuleValidator, get_validator
from .async_import import AsyncImporter, get_async_importer

__all__ = [
    'LazyModule',
    'LazyAttributeProxy',
    'ValidationError',
    'ImportConfig',
    'parse_target',
    'is_file_path',
    'extract_module_name',
    'ImportCache',
    'get_cache',
    'cached_import',
    'PackageInstaller',
    'get_installer',
    'install_package',
    'ModuleLoader',
    'get_loader',
    'ModuleValidator',
    'get_validator',
    'AsyncImporter',
    'get_async_importer',
]
