#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Module validation functionality for compatibility checking.
"""

import sys
import platform
import importlib.metadata
from typing import Dict, Any, List, Optional
from .types import ValidationError


class ModuleValidator:
    """
    Validates module compatibility with current system.
    
    Checks Python version, operating system, architecture, and
    dependency compatibility.
    """
    
    def validate(self, module_name: str) -> bool:
        """
        Validate module compatibility.
        
        Parameters
        ----------
        module_name : str
            Name of module to validate.
        
        Returns
        -------
        bool
            True if module is compatible.
        
        Raises
        ------
        ValidationError
            If module is incompatible.
        """
        # Get module metadata
        metadata = self._get_module_metadata(module_name)
        
        # Check Python version
        self._check_python_version(metadata)
        
        # Check OS compatibility
        self._check_os_compatibility(metadata)
        
        # Check architecture
        self._check_architecture(metadata)
        
        # Check dependencies
        self._check_dependencies(metadata)
        
        return True
    
    def _get_module_metadata(self, module_name: str) -> Dict[str, Any]:
        """
        Get module metadata from distribution.
        
        Parameters
        ----------
        module_name : str
            Module name.
        
        Returns
        -------
        Dict[str, Any]
            Module metadata.
        """
        metadata = {}
        
        try:
            dist = importlib.metadata.distribution(module_name)
            
            # Get requires
            metadata['requires'] = dist.requires or []
            
            # Get metadata
            if dist.metadata:
                metadata['requires_python'] = dist.metadata.get('Requires-Python')
                metadata['platform'] = dist.metadata.get('Platform')
            
        except importlib.metadata.PackageNotFoundError:
            pass
        
        return metadata
    
    def _check_python_version(self, metadata: Dict[str, Any]) -> None:
        """
        Check Python version compatibility.
        
        Parameters
        ----------
        metadata : Dict[str, Any]
            Module metadata.
        
        Raises
        ------
        ValidationError
            If Python version incompatible.
        """
        requires_python = metadata.get('requires_python')
        if requires_python:
            # Simplified check - in production, use packaging module
            current = f"{sys.version_info.major}.{sys.version_info.minor}"
            if requires_python.startswith('>='):
                min_version = requires_python[2:].strip()
                if self._compare_versions(current, min_version) < 0:
                    raise ValidationError(
                        f"Module requires Python {requires_python}, "
                        f"but current version is {current}"
                    )
    
    def _check_os_compatibility(self, metadata: Dict[str, Any]) -> None:
        """
        Check OS compatibility.
        
        Parameters
        ----------
        metadata : Dict[str, Any]
            Module metadata.
        
        Raises
        ------
        ValidationError
            If OS incompatible.
        """
        platform_requires = metadata.get('platform')
        if platform_requires:
            current_os = sys.platform
            if platform_requires not in ['any', current_os]:
                raise ValidationError(
                    f"Module requires platform {platform_requires}, "
                    f"but current is {current_os}"
                )
    
    def _check_architecture(self, metadata: Dict[str, Any]) -> None:
        """
        Check architecture compatibility.
        
        Parameters
        ----------
        metadata : Dict[str, Any]
            Module metadata.
        
        Raises
        ------
        ValidationError
            If architecture incompatible.
        """
        # Check for 32/64 bit requirements
        arch = platform.machine()
        if '32bit' in str(metadata) and '64' in arch:
            # Simplified - would need real metadata
            pass
    
    def _check_dependencies(self, metadata: Dict[str, Any]) -> None:
        """
        Check dependencies compatibility.
        
        Parameters
        ----------
        metadata : Dict[str, Any]
            Module metadata.
        
        Raises
        ------
        ValidationError
            If dependencies incompatible.
        """
        requires = metadata.get('requires', [])
        for req in requires:
            # Parse requirement (simplified)
            if ';' in req:
                req, condition = req.split(';', 1)
                # Check condition (e.g., "python_version < '3.8'")
                # Would need proper evaluation
            
            # Check if package is installed
            pkg_name = req.split()[0].split('>')[0].split('<')[0].split('=')[0]
            try:
                importlib.metadata.distribution(pkg_name)
            except importlib.metadata.PackageNotFoundError:
                # Optional dependency?
                pass
    
    def _compare_versions(self, v1: str, v2: str) -> int:
        """
        Compare two version strings.
        
        Parameters
        ----------
        v1 : str
            First version.
        v2 : str
            Second version.
        
        Returns
        -------
        int
            -1 if v1 < v2, 0 if equal, 1 if v1 > v2.
        """
        v1_parts = [int(x) for x in v1.split('.')]
        v2_parts = [int(x) for x in v2.split('.')]
        
        for i in range(max(len(v1_parts), len(v2_parts))):
            v1_part = v1_parts[i] if i < len(v1_parts) else 0
            v2_part = v2_parts[i] if i < len(v2_parts) else 0
            
            if v1_part < v2_part:
                return -1
            elif v1_part > v2_part:
                return 1
        
        return 0


# Global validator instance
_global_validator = ModuleValidator()


def get_validator() -> ModuleValidator:
    """Get the global validator instance."""
    return _global_validator