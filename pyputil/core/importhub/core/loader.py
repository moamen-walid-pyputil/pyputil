#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Module loading functionality for different import types.
"""

import importlib
import importlib.util
import sys
import os
import types
from typing import Optional, Any, Dict
from .types import LazyModule, ValidationError
from .parser import normalize_module_path


class ModuleLoader:
    """
    Handles loading of modules from various sources.
    
    This class manages the actual module loading process, including
    standard imports, file-based imports, and lazy loading.
    """
    
    def load_module(
        self,
        module_name: str,
        reload: bool = False,
        lazy: bool = False,
        inject_globals: Optional[Dict] = None,
        search_paths: Optional[list] = None,
    ) -> Optional[types.ModuleType]:
        """
        Load a module by name.
        
        Parameters
        ----------
        module_name : str
            Name of module to load.
        reload : bool
            Force reload if already imported.
        lazy : bool
            Return lazy proxy instead of loading immediately.
        inject_globals : dict, optional
            Globals to inject into module.
        search_paths : list, optional
            Additional search paths.
        
        Returns
        -------
        Optional[types.ModuleType]
            Loaded module or None if not found.
        """
        # Find module spec
        spec = self._find_spec(module_name, search_paths)
        if spec is None:
            return None
        
        # Handle lazy loading
        if lazy:
            return LazyModule(spec)
        
        # Create and execute module
        module = importlib.util.module_from_spec(spec)
        
        if inject_globals:
            module.__dict__.update(inject_globals)
        
        # Check if we need to reload
        if reload and module_name in sys.modules:
            module = importlib.reload(sys.modules[module_name])
        else:
            spec.loader.exec_module(module)
        
        return module
    
    def load_from_file(
        self,
        file_path: str,
        reload: bool = False,
        inject_globals: Optional[Dict] = None,
    ) -> Optional[types.ModuleType]:
        """
        Load a module from a file path.
        
        Parameters
        ----------
        file_path : str
            Path to Python file.
        reload : bool
            Force reload if already loaded.
        inject_globals : dict, optional
            Globals to inject.
        
        Returns
        -------
        Optional[types.ModuleType]
            Loaded module or None if file not found.
        """
        # Normalize path
        abs_path = normalize_module_path(file_path)
        
        if not os.path.exists(abs_path):
            return None
        
        # Create module name from path
        module_name = self._path_to_module_name(abs_path)
        
        # Create spec
        spec = importlib.util.spec_from_file_location(module_name, abs_path)
        if spec is None:
            return None
        
        # Load module
        module = importlib.util.module_from_spec(spec)
        
        if inject_globals:
            module.__dict__.update(inject_globals)
        
        # Check if we need to reload
        if reload and module_name in sys.modules:
            module = importlib.reload(sys.modules[module_name])
        else:
            spec.loader.exec_module(module)
            sys.modules[module_name] = module
        
        return module
    
    def _find_spec(
        self,
        module_name: str,
        search_paths: Optional[list] = None
    ) -> Optional[importlib.machinery.ModuleSpec]:
        """
        Find module specification.
        
        Parameters
        ----------
        module_name : str
            Module name.
        search_paths : list, optional
            Additional search paths.
        
        Returns
        -------
        Optional[importlib.machinery.ModuleSpec]
            Module spec or None if not found.
        """
        # Save original path
        original_path = sys.path[:]
        
        try:
            # Add search paths temporarily
            if search_paths:
                sys.path = search_paths + sys.path
            
            # Try to find spec
            return importlib.util.find_spec(module_name)
            
        finally:
            # Restore original path
            sys.path = original_path
    
    def _path_to_module_name(self, file_path: str) -> str:
        """
        Convert file path to module name.
        
        Parameters
        ----------
        file_path : str
            Path to Python file.
        
        Returns
        -------
        str
            Module name.
        """
        # Remove extension and convert path separators to dots
        rel_path = os.path.relpath(file_path)
        name = rel_path.replace(os.path.sep, '.')
        if name.endswith('.py'):
            name = name[:-3]
        if name.endswith('.__init__'):
            name = name[:-9]
        return name


# Global loader instance
_global_loader = ModuleLoader()


def get_loader() -> ModuleLoader:
    """Get the global module loader instance."""
    return _global_loader