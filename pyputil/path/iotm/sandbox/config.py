#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Configuration System for Python Sandbox Security.

This module provides comprehensive configuration management for sandbox
security settings with support for different security levels, custom
rule sets, and cross-platform compatibility.

The configuration system includes predefined security profiles,
validation mechanisms, and dynamic rule management.

Examples
--------
>>> config = SandboxConfig.from_profile("strict")
>>> config.is_module_allowed("math")
True
>>> config.is_module_allowed("os")
False
>>> custom = SandboxConfig(max_memory_mb=200, allowed_modules=["numpy"])
>>> custom.save("my_config.json")
"""

import json
import re
import sys
import os
from pathlib import Path
from typing import (
    Set, Dict, List, Optional, Any, Union, 
    Pattern, Callable, Tuple, FrozenSet
)
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from functools import lru_cache
import hashlib
import warnings
from datetime import datetime


class SecurityLevel(Enum):
    """
    Predefined security levels for sandbox configuration.
    
    Attributes
    ----------
    MINIMAL : int
        Minimal restrictions, suitable for trusted code
    STANDARD : int
        Standard security, blocks most dangerous operations
    STRICT : int
        Strict security, only essential operations allowed
    CUSTOM : int
        Custom security configuration
    PARANOID : int
        Maximum security, minimal allowed operations
    """
    MINIMAL = auto()
    STANDARD = auto()
    STRICT = auto()
    CUSTOM = auto()
    PARANOID = auto()


class ResourceLimit(Enum):
    """
    Types of resource limits that can be enforced.
    
    Attributes
    ----------
    CPU_TIME : str
        CPU execution time limit
    MEMORY : str
        Memory usage limit
    DISK_IO : str
        Disk I/O operations limit
    NETWORK : str
        Network operations limit
    FILE_HANDLES : str
        Open file handles limit
    PROCESSES : str
        Child process creation limit
    RECURSION : str
        Recursion depth limit
    CODE_SIZE : str
        Code size limit
    """
    CPU_TIME = "cpu_time"
    MEMORY = "memory"
    DISK_IO = "disk_io"
    NETWORK = "network"
    FILE_HANDLES = "file_handles"
    PROCESSES = "processes"
    RECURSION = "recursion"
    CODE_SIZE = "code_size"


@dataclass
class ModuleRule:
    """
    Rule for module import permissions.
    
    Attributes
    ----------
    pattern : Union[str, Pattern]
        Module name pattern (regex or wildcard)
    allowed : bool
        Whether matching modules are allowed
    reason : str
        Reason for this rule
    submodules_inherit : bool
        Whether submodules inherit this rule
    """
    pattern: Union[str, Pattern]
    allowed: bool
    reason: str = ""
    submodules_inherit: bool = True
    
    def __post_init__(self):
        """Compile pattern if it's a string."""
        if isinstance(self.pattern, str):
            # Convert wildcard to regex
            pattern_str = self.pattern.replace(".", "\\.").replace("*", ".*")
            self.pattern = re.compile(f"^{pattern_str}$")
    
    def matches(self, module_name: str) -> bool:
        """
        Check if module name matches this rule.
        
        Parameters
        ----------
        module_name : str
            Module name to check
            
        Returns
        -------
        bool
            True if module matches pattern
        """
        return bool(self.pattern.match(module_name))


@dataclass
class AttributeRule:
    """
    Rule for attribute access permissions.
    
    Attributes
    ----------
    name : str
        Attribute name pattern
    allowed : bool
        Whether attribute access is allowed
    applies_to : Optional[Pattern]
        Pattern for object types this applies to
    reason : str
        Reason for this rule
    """
    name: str
    allowed: bool
    applies_to: Optional[Union[str, Pattern]] = None
    reason: str = ""
    
    def __post_init__(self):
        """Compile applies_to pattern if provided."""
        if isinstance(self.applies_to, str):
            self.applies_to = re.compile(self.applies_to)
    
    def matches(self, attr_name: str, obj_type: Optional[str] = None) -> bool:
        """
        Check if attribute access matches this rule.
        
        Parameters
        ----------
        attr_name : str
            Attribute name
        obj_type : Optional[str]
            Type of object being accessed
            
        Returns
        -------
        bool
            True if rule applies
        """
        name_match = bool(re.match(self.name.replace("*", ".*"), attr_name))
        
        if self.applies_to and obj_type:
            type_match = bool(self.applies_to.match(obj_type))
            return name_match and type_match
        
        return name_match


@dataclass
class ResourceLimits:
    """
    Resource limits configuration.
    
    Attributes
    ----------
    cpu_time_seconds : float
        Maximum CPU execution time
    memory_mb : int
        Maximum memory usage in megabytes
    max_open_files : int
        Maximum number of open file handles
    max_processes : int
        Maximum number of child processes
    max_recursion_depth : int
        Maximum recursion depth
    max_code_size_bytes : int
        Maximum code size in bytes
    max_string_length : int
        Maximum string length
    max_iterations : int
        Maximum loop iterations
    """
    cpu_time_seconds: float = 5.0
    memory_mb: int = 100
    max_open_files: int = 10
    max_processes: int = 0
    max_recursion_depth: int = 100
    max_code_size_bytes: int = 100 * 1024  # 100KB
    max_string_length: int = 1024 * 1024  # 1MB
    max_iterations: int = 1000000
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ResourceLimits':
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SandboxConfig:
    """
    Comprehensive configuration for sandbox security settings.
    
    This class manages all security-related configurations including
    allowed modules, blocked operations, resource limits, and
    custom security rules.
    
    Attributes
    ----------
    security_level : SecurityLevel
        Current security level
    allowed_modules : Set[str]
        Explicitly allowed modules
    blocked_modules : Set[str]
        Explicitly blocked modules
    module_rules : List[ModuleRule]
        Pattern-based module rules
    safe_builtins : Set[str]
        Allowed built-in functions
    blocked_attributes : Set[str]
        Blocked attribute names
    attribute_rules : List[AttributeRule]
        Pattern-based attribute rules
    resource_limits : ResourceLimits
        Resource usage limits
    allow_imports : bool
        Whether imports are allowed at all
    allow_file_io : bool
        Whether file I/O operations are allowed
    allow_network : bool
        Whether network operations are allowed
    allow_subprocesses : bool
        Whether subprocess creation is allowed
    
    Methods
    -------
    from_profile(level)
        Create configuration from security profile
    from_file(path)
        Load configuration from file
    save(path)
        Save configuration to file
    is_module_allowed(module_name)
        Check if module import is allowed
    is_attribute_allowed(attr_name, obj_type)
        Check if attribute access is allowed
    add_module_rule(pattern, allowed, reason)
        Add a module permission rule
    validate()
        Validate configuration consistency
    
    Examples
    --------
    >>> config = SandboxConfig.from_profile("standard")
    >>> config.is_module_allowed("math")
    True
    >>> config.is_module_allowed("os.system")
    False
    >>> config.add_module_rule("myapp.*", True, "Allow internal modules")
    >>> config.save("sandbox_config.json")
    """
    
    # Predefined security profiles
    _PROFILES: Dict[SecurityLevel, Dict[str, Any]] = {
        SecurityLevel.MINIMAL: {
            "allowed_modules": {"*"},
            "blocked_modules": {"os.system", "subprocess.call"},
            "safe_builtins": {"*"},
            "allow_imports": True,
            "allow_file_io": True,
            "allow_network": True,
            "allow_subprocesses": False,
            "resource_limits": ResourceLimits(
                cpu_time_seconds=30.0,
                memory_mb=500,
                max_code_size_bytes=1024 * 1024  # 1MB
            )
        },
        SecurityLevel.STANDARD: {
            "allowed_modules": {
                "math", "random", "datetime", "json", "re",
                "collections", "itertools", "functools", "typing",
                "string", "textwrap", "hashlib", "base64",
                "csv", "xml.etree.ElementTree", "html", "urllib.parse"
            },
            "blocked_modules": {
                "os", "subprocess", "sys", "shutil", "socket", "pickle",
                "marshal", "ctypes", "importlib", "inspect",
                "pty", "fcntl", "resource", "signal", "multiprocessing",
                "threading", "_thread", "asyncio", "concurrent.futures"
            },
            "safe_builtins": {
                'abs', 'all', 'any', 'bool', 'dict', 'enumerate', 'float',
                'int', 'len', 'list', 'max', 'min', 'print', 'range', 'round',
                'set', 'sorted', 'str', 'sum', 'tuple', 'zip', 'type',
                'isinstance', 'issubclass', 'chr', 'ord', 'hex', 'oct',
                'map', 'filter', 'reversed', 'slice', 'complex', 'bytes',
                'bytearray', 'memoryview', 'property', 'staticmethod', 'classmethod',
                'bin', 'divmod', 'pow', 'format', 'hasattr', 'getattr',
                'callable', 'dir', 'vars', 'id', 'hash'
            },
            "blocked_attributes": {
                '__builtins__', '__import__', '__loader__', '__spec__',
                '__subclasses__', '__globals__', '__code__', '__closure__',
                '__getattribute__', '__setattr__', '__delattr__', '__reduce__',
                '__reduce_ex__', '__class__', '__bases__', '__mro__',
                '__dict__', '__module__', '__weakref__', '__doc__',
                '__func__', '__self__', '__annotations__', '__kwdefaults__',
                '__defaults__', '__qualname__', '__name__'
            },
            "allow_imports": True,
            "allow_file_io": False,
            "allow_network": False,
            "allow_subprocesses": False,
            "resource_limits": ResourceLimits()
        },
        SecurityLevel.STRICT: {
            "allowed_modules": {
                "math", "random", "datetime", "json",
                "collections", "itertools", "functools"
            },
            "blocked_modules": {"*"},
            "safe_builtins": {
                'abs', 'all', 'any', 'bool', 'dict', 'enumerate', 'float',
                'int', 'len', 'list', 'max', 'min', 'print', 'range', 'round',
                'set', 'sorted', 'str', 'sum', 'tuple', 'zip',
                'isinstance', 'issubclass', 'len', 'type'
            },
            "blocked_attributes": {"*"},
            "allow_imports": True,
            "allow_file_io": False,
            "allow_network": False,
            "allow_subprocesses": False,
            "resource_limits": ResourceLimits(
                cpu_time_seconds=2.0,
                memory_mb=50,
                max_code_size_bytes=50 * 1024  # 50KB
            )
        },
        SecurityLevel.PARANOID: {
            "allowed_modules": set(),
            "blocked_modules": {"*"},
            "safe_builtins": {
                'abs', 'bool', 'dict', 'float', 'int', 'len', 'list',
                'max', 'min', 'range', 'round', 'set', 'str', 'sum', 'tuple'
            },
            "blocked_attributes": {"*"},
            "allow_imports": False,
            "allow_file_io": False,
            "allow_network": False,
            "allow_subprocesses": False,
            "resource_limits": ResourceLimits(
                cpu_time_seconds=1.0,
                memory_mb=10,
                max_code_size_bytes=10 * 1024  # 10KB
            )
        }
    }
    
    # System modules that are always blocked (critical security)
    _CRITICAL_MODULES: FrozenSet[str] = frozenset({
        'os', 'subprocess', 'sys', 'shutil', 'socket', 'pickle',
        'marshal', 'ctypes', 'cffi', 'importlib', '__main__',
        'builtins', 'inspect', 'eval', 'exec', 'compile',
        'pty', 'fcntl', 'resource', 'signal', 'multiprocessing',
        'threading', '_thread', 'asyncio', 'concurrent.futures',
        'code', 'codeop', 'traceback', 'linecache', 'pdb',
        'bdb', 'runpy', 'py_compile', 'compileall'
    })
    
    # Safe standard library modules
    _SAFE_STDLIB: FrozenSet[str] = frozenset({
        'math', 'cmath', 'random', 'statistics', 'datetime', 'time',
        'calendar', 'collections', 'itertools', 'functools', 'operator',
        'typing', 'enum', 'dataclasses', 're', 'string', 'textwrap',
        'json', 'csv', 'hashlib', 'base64', 'binascii', 'uuid',
        'html', 'xml.etree.ElementTree', 'urllib.parse', 'argparse',
        'logging', 'warnings', 'trace', 'copy', 'pprint', 'reprlib',
        'decimal', 'fractions', 'array', 'struct', 'weakref',
        'types', 'contextlib', 'pathlib', 'tempfile'
    })
    
    def __init__(
        self,
        security_level: SecurityLevel = SecurityLevel.CUSTOM,
        allowed_modules: Optional[Set[str]] = None,
        blocked_modules: Optional[Set[str]] = None,
        safe_builtins: Optional[Set[str]] = None,
        blocked_attributes: Optional[Set[str]] = None,
        module_rules: Optional[List[ModuleRule]] = None,
        attribute_rules: Optional[List[AttributeRule]] = None,
        resource_limits: Optional[ResourceLimits] = None,
        allow_imports: bool = True,
        allow_file_io: bool = False,
        allow_network: bool = False,
        allow_subprocesses: bool = False,
        custom_allowed_paths: Optional[List[Union[str, Path]]] = None,
        allowed_network_hosts: Optional[List[str]] = None,
        enable_logging: bool = False,
        log_file: Optional[Union[str, Path]] = None,
        audit_events: bool = True
    ):
        """
        Initialize sandbox configuration.
        
        Parameters
        ----------
        security_level : SecurityLevel, optional
            Base security level (default CUSTOM)
        allowed_modules : Optional[Set[str]], optional
            Explicitly allowed module names
        blocked_modules : Optional[Set[str]], optional
            Explicitly blocked module names
        safe_builtins : Optional[Set[str]], optional
            Allowed built-in function names
        blocked_attributes : Optional[Set[str]], optional
            Blocked attribute names
        module_rules : Optional[List[ModuleRule]], optional
            Pattern-based module rules
        attribute_rules : Optional[List[AttributeRule]], optional
            Pattern-based attribute rules
        resource_limits : Optional[ResourceLimits], optional
            Resource usage limits
        allow_imports : bool, optional
            Whether imports are allowed (default True)
        allow_file_io : bool, optional
            Whether file I/O is allowed (default False)
        allow_network : bool, optional
            Whether network operations are allowed (default False)
        allow_subprocesses : bool, optional
            Whether subprocesses are allowed (default False)
        custom_allowed_paths : Optional[List[Union[str, Path]]], optional
            Specific paths allowed for file I/O
        allowed_network_hosts : Optional[List[str]], optional
            Specific hosts allowed for network operations
        enable_logging : bool, optional
            Enable security event logging (default False)
        log_file : Optional[Union[str, Path]], optional
            Path to log file
        audit_events : bool, optional
            Enable security event auditing (default True)
        """
        self.security_level = security_level
        self.allow_imports = allow_imports
        self.allow_file_io = allow_file_io
        self.allow_network = allow_network
        self.allow_subprocesses = allow_subprocesses
        
        # Initialize sets
        self.allowed_modules: Set[str] = allowed_modules or set()
        self.blocked_modules: Set[str] = blocked_modules or set()
        self.safe_builtins: Set[str] = safe_builtins or set()
        self.blocked_attributes: Set[str] = blocked_attributes or set()
        
        # Rules
        self.module_rules: List[ModuleRule] = module_rules or []
        self.attribute_rules: List[AttributeRule] = attribute_rules or []
        
        # Resource limits
        self.resource_limits = resource_limits or ResourceLimits()
        
        # Advanced settings
        self.custom_allowed_paths: List[Path] = [
            Path(p) for p in (custom_allowed_paths or [])
        ]
        self.allowed_network_hosts: List[str] = allowed_network_hosts or []
        
        # Logging and auditing
        self.enable_logging = enable_logging
        self.log_file = Path(log_file) if log_file else None
        self.audit_events = audit_events
        
        # Internal state
        self._config_hash: Optional[str] = None
        self._created_at = datetime.now()
        self._modified_at = self._created_at
        self._validation_errors: List[str] = []
        
        # Apply security level if not custom
        if security_level != SecurityLevel.CUSTOM:
            self._apply_profile(security_level)
        
        # Always block critical modules
        self.blocked_modules.update(self._CRITICAL_MODULES)
        
        # Validate configuration
        self.validate()
    
    def _apply_profile(self, level: SecurityLevel) -> None:
        """
        Apply a predefined security profile.
        
        Parameters
        ----------
        level : SecurityLevel
            Security level to apply
        """
        if level not in self._PROFILES:
            raise ValueError(f"Unknown security level: {level}")
        
        profile = self._PROFILES[level]
        
        # Apply profile settings
        self.allowed_modules = set(profile.get("allowed_modules", set()))
        self.blocked_modules = set(profile.get("blocked_modules", set()))
        self.safe_builtins = set(profile.get("safe_builtins", set()))
        self.blocked_attributes = set(profile.get("blocked_attributes", set()))
        self.allow_imports = profile.get("allow_imports", True)
        self.allow_file_io = profile.get("allow_file_io", False)
        self.allow_network = profile.get("allow_network", False)
        self.allow_subprocesses = profile.get("allow_subprocesses", False)
        
        if "resource_limits" in profile:
            self.resource_limits = profile["resource_limits"]
    
    @classmethod
    def from_profile(cls, level: Union[str, SecurityLevel]) -> 'SandboxConfig':
        """
        Create configuration from a security profile.
        
        Parameters
        ----------
        level : Union[str, SecurityLevel]
            Security level name or enum value
            
        Returns
        -------
        SandboxConfig
            Configured sandbox configuration
            
        Examples
        --------
        >>> config = SandboxConfig.from_profile("strict")
        >>> config = SandboxConfig.from_profile(SecurityLevel.STANDARD)
        """
        if isinstance(level, str):
            level = SecurityLevel[level.upper()]
        
        return cls(security_level=level)
    
    @classmethod
    def from_file(cls, path: Union[str, Path]) -> 'SandboxConfig':
        """
        Load configuration from JSON file.
        
        Parameters
        ----------
        path : Union[str, Path]
            Path to configuration file
            
        Returns
        -------
        SandboxConfig
            Loaded configuration
            
        Raises
        ------
        FileNotFoundError
            If file does not exist
        json.JSONDecodeError
            If file contains invalid JSON
        """
        path = Path(path)
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Convert lists back to sets
        data['allowed_modules'] = set(data.get('allowed_modules', []))
        data['blocked_modules'] = set(data.get('blocked_modules', []))
        data['safe_builtins'] = set(data.get('safe_builtins', []))
        data['blocked_attributes'] = set(data.get('blocked_attributes', []))
        
        # Convert resource limits
        if 'resource_limits' in data:
            data['resource_limits'] = ResourceLimits.from_dict(data['resource_limits'])
        
        # Convert module rules
        if 'module_rules' in data:
            data['module_rules'] = [
                ModuleRule(**rule) for rule in data['module_rules']
            ]
        
        # Convert attribute rules
        if 'attribute_rules' in data:
            data['attribute_rules'] = [
                AttributeRule(**rule) for rule in data['attribute_rules']
            ]
        
        # Convert paths
        if 'custom_allowed_paths' in data:
            data['custom_allowed_paths'] = [
                Path(p) for p in data['custom_allowed_paths']
            ]
        
        return cls(**data)
    
    def save(self, path: Union[str, Path]) -> None:
        """
        Save configuration to JSON file.
        
        Parameters
        ----------
        path : Union[str, Path]
            Path to save configuration
            
        Raises
        ------
        IOError
            If file cannot be written
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        data = self.to_dict()
        
        # Convert sets to lists for JSON serialization
        data['allowed_modules'] = list(data['allowed_modules'])
        data['blocked_modules'] = list(data['blocked_modules'])
        data['safe_builtins'] = list(data['safe_builtins'])
        data['blocked_attributes'] = list(data['blocked_attributes'])
        
        # Convert paths to strings
        data['custom_allowed_paths'] = [str(p) for p in data['custom_allowed_paths']]
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert configuration to dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of configuration
        """
        return {
            'security_level': self.security_level.name,
            'allowed_modules': self.allowed_modules,
            'blocked_modules': self.blocked_modules,
            'safe_builtins': self.safe_builtins,
            'blocked_attributes': self.blocked_attributes,
            'module_rules': [
                {
                    'pattern': rule.pattern.pattern,
                    'allowed': rule.allowed,
                    'reason': rule.reason,
                    'submodules_inherit': rule.submodules_inherit
                }
                for rule in self.module_rules
            ],
            'attribute_rules': [
                {
                    'name': rule.name,
                    'allowed': rule.allowed,
                    'applies_to': rule.applies_to.pattern if rule.applies_to else None,
                    'reason': rule.reason
                }
                for rule in self.attribute_rules
            ],
            'resource_limits': self.resource_limits.to_dict(),
            'allow_imports': self.allow_imports,
            'allow_file_io': self.allow_file_io,
            'allow_network': self.allow_network,
            'allow_subprocesses': self.allow_subprocesses,
            'custom_allowed_paths': self.custom_allowed_paths,
            'allowed_network_hosts': self.allowed_network_hosts,
            'enable_logging': self.enable_logging,
            'log_file': str(self.log_file) if self.log_file else None,
            'audit_events': self.audit_events
        }
    
    @lru_cache(maxsize=1000)
    def is_module_allowed(self, module_name: str) -> bool:
        """
        Check if a module import is allowed.
        
        Parameters
        ----------
        module_name : str
            Full module name to check
            
        Returns
        -------
        bool
            True if module import is allowed
            
        Examples
        --------
        >>> config = SandboxConfig.from_profile("standard")
        >>> config.is_module_allowed("math")
        True
        >>> config.is_module_allowed("os.system")
        False
        """
        if not self.allow_imports:
            return False
        
        # Check base module name
        base_module = module_name.split('.')[0]
        
        # Critical modules are never allowed
        if base_module in self._CRITICAL_MODULES:
            return False
        
        # Check explicit blocked list
        if module_name in self.blocked_modules:
            return False
        
        if base_module in self.blocked_modules:
            return False
        
        # Check wildcard blocked
        if "*" in self.blocked_modules:
            return False
        
        # Check explicit allowed list
        if module_name in self.allowed_modules:
            return True
        
        if base_module in self.allowed_modules:
            return True
        
        # Check wildcard allowed
        if "*" in self.allowed_modules:
            return True
        
        # Check pattern rules
        for rule in self.module_rules:
            if rule.matches(module_name):
                return rule.allowed
            
            # Check base module if submodules inherit
            if rule.submodules_inherit and rule.matches(base_module):
                return rule.allowed
        
        # Safe stdlib modules are allowed by default in non-strict modes
        if self.security_level in (SecurityLevel.MINIMAL, SecurityLevel.STANDARD):
            if base_module in self._SAFE_STDLIB:
                return True
        
        return False
    
    @lru_cache(maxsize=1000)
    def is_attribute_allowed(
        self,
        attr_name: str,
        obj_type: Optional[str] = None
    ) -> bool:
        """
        Check if attribute access is allowed.
        
        Parameters
        ----------
        attr_name : str
            Attribute name
        obj_type : Optional[str], optional
            Type of object being accessed
            
        Returns
        -------
        bool
            True if attribute access is allowed
        """
        # Check explicit blocked list
        if attr_name in self.blocked_attributes:
            return False
        
        # Check wildcard blocked
        if "*" in self.blocked_attributes:
            return False
        
        # Check pattern rules
        for rule in self.attribute_rules:
            if rule.matches(attr_name, obj_type):
                return rule.allowed
        
        return True
    
    def add_module_rule(
        self,
        pattern: str,
        allowed: bool,
        reason: str = "",
        submodules_inherit: bool = True
    ) -> None:
        """
        Add a pattern-based module permission rule.
        
        Parameters
        ----------
        pattern : str
            Module name pattern (supports * wildcard)
        allowed : bool
            Whether matching modules are allowed
        reason : str, optional
            Reason for this rule
        submodules_inherit : bool, optional
            Whether submodules inherit this rule
            
        Examples
        --------
        >>> config = SandboxConfig()
        >>> config.add_module_rule("myapp.*", True, "Allow internal modules")
        """
        rule = ModuleRule(pattern, allowed, reason, submodules_inherit)
        self.module_rules.append(rule)
        self._invalidate_cache()
        self._modified_at = datetime.now()
    
    def add_attribute_rule(
        self,
        name: str,
        allowed: bool,
        applies_to: Optional[str] = None,
        reason: str = ""
    ) -> None:
        """
        Add a pattern-based attribute permission rule.
        
        Parameters
        ----------
        name : str
            Attribute name pattern
        allowed : bool
            Whether attribute access is allowed
        applies_to : Optional[str], optional
            Object type pattern this applies to
        reason : str, optional
            Reason for this rule
        """
        rule = AttributeRule(name, allowed, applies_to, reason)
        self.attribute_rules.append(rule)
        self._invalidate_cache()
        self._modified_at = datetime.now()
    
    def allow_module(self, module_name: str) -> None:
        """
        Explicitly allow a module.
        
        Parameters
        ----------
        module_name : str
            Module name to allow
        """
        self.allowed_modules.add(module_name)
        self.blocked_modules.discard(module_name)
        self._invalidate_cache()
    
    def block_module(self, module_name: str) -> None:
        """
        Explicitly block a module.
        
        Parameters
        ----------
        module_name : str
            Module name to block
        """
        self.blocked_modules.add(module_name)
        self.allowed_modules.discard(module_name)
        self._invalidate_cache()
    
    def allow_builtin(self, builtin_name: str) -> None:
        """
        Allow a built-in function.
        
        Parameters
        ----------
        builtin_name : str
            Built-in function name
        """
        self.safe_builtins.add(builtin_name)
    
    def block_builtin(self, builtin_name: str) -> None:
        """
        Block a built-in function.
        
        Parameters
        ----------
        builtin_name : str
            Built-in function name
        """
        self.safe_builtins.discard(builtin_name)
    
    def allow_path(self, path: Union[str, Path]) -> None:
        """
        Allow file I/O for a specific path.
        
        Parameters
        ----------
        path : Union[str, Path]
            Path to allow
        """
        self.custom_allowed_paths.append(Path(path))
    
    def allow_host(self, host: str) -> None:
        """
        Allow network connections to a specific host.
        
        Parameters
        ----------
        host : str
            Hostname or IP address
        """
        self.allowed_network_hosts.append(host)
    
    def _invalidate_cache(self) -> None:
        """Invalidate cached permission checks."""
        self.is_module_allowed.cache_clear()
        self.is_attribute_allowed.cache_clear()
        self._config_hash = None
    
    def validate(self, raise_on_error: bool = False) -> List[str]:
        """
        Validate configuration consistency.
        
        Parameters
        ----------
        raise_on_error : bool, optional
            Raise exception on validation error (default False)
            
        Returns
        -------
        List[str]
            List of validation errors
            
        Raises
        ------
        ValueError
            If raise_on_error is True and validation fails
        """
        errors = []
        
        # Check for conflicting rules
        if "*" in self.allowed_modules and "*" in self.blocked_modules:
            errors.append("Conflicting wildcard rules for modules")
        
        # Validate resource limits
        if self.resource_limits.memory_mb < 1:
            errors.append("Memory limit must be at least 1 MB")
        
        if self.resource_limits.cpu_time_seconds < 0.1:
            errors.append("CPU time limit must be at least 0.1 seconds")
        
        # Validate file paths
        for path in self.custom_allowed_paths:
            if not path.is_absolute():
                errors.append(f"Path must be absolute: {path}")
        
        # Validate network hosts
        for host in self.allowed_network_hosts:
            if not self._is_valid_host(host):
                errors.append(f"Invalid host format: {host}")
        
        # Check logging configuration
        if self.enable_logging and self.log_file:
            try:
                self.log_file.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                errors.append(f"Cannot create log directory: {e}")
        
        self._validation_errors = errors
        
        if errors and raise_on_error:
            raise ValueError(f"Configuration validation failed: {'; '.join(errors)}")
        
        return errors
    
    def _is_valid_host(self, host: str) -> bool:
        """
        Validate hostname or IP address format.
        
        Parameters
        ----------
        host : str
            Host to validate
            
        Returns
        -------
        bool
            True if valid format
        """
        # Simple validation
        if not host:
            return False
        
        # Check for IP address format
        ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if re.match(ip_pattern, host):
            parts = host.split('.')
            return all(0 <= int(p) <= 255 for p in parts)
        
        # Check for hostname format
        hostname_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?$'
        return bool(re.match(hostname_pattern, host))
    
    def get_hash(self) -> str:
        """
        Get unique hash of current configuration.
        
        Returns
        -------
        str
            SHA256 hash of configuration
        """
        if self._config_hash is None:
            data = json.dumps(self.to_dict(), sort_keys=True, default=str)
            self._config_hash = hashlib.sha256(data.encode()).hexdigest()
        return self._config_hash
    
    def clone(self) -> 'SandboxConfig':
        """
        Create a deep copy of the configuration.
        
        Returns
        -------
        SandboxConfig
            Cloned configuration
        """
        return SandboxConfig(
            security_level=self.security_level,
            allowed_modules=self.allowed_modules.copy(),
            blocked_modules=self.blocked_modules.copy(),
            safe_builtins=self.safe_builtins.copy(),
            blocked_attributes=self.blocked_attributes.copy(),
            module_rules=[ModuleRule(
                rule.pattern.pattern,
                rule.allowed,
                rule.reason,
                rule.submodules_inherit
            ) for rule in self.module_rules],
            attribute_rules=[AttributeRule(
                rule.name,
                rule.allowed,
                rule.applies_to.pattern if rule.applies_to else None,
                rule.reason
            ) for rule in self.attribute_rules],
            resource_limits=ResourceLimits(**self.resource_limits.to_dict()),
            allow_imports=self.allow_imports,
            allow_file_io=self.allow_file_io,
            allow_network=self.allow_network,
            allow_subprocesses=self.allow_subprocesses,
            custom_allowed_paths=self.custom_allowed_paths.copy(),
            allowed_network_hosts=self.allowed_network_hosts.copy(),
            enable_logging=self.enable_logging,
            log_file=self.log_file,
            audit_events=self.audit_events
        )
    
    def merge(self, other: 'SandboxConfig') -> 'SandboxConfig':
        """
        Merge with another configuration (other takes precedence).
        
        Parameters
        ----------
        other : SandboxConfig
            Configuration to merge with
            
        Returns
        -------
        SandboxConfig
            Merged configuration
        """
        merged = self.clone()
        
        # Merge sets (union)
        merged.allowed_modules.update(other.allowed_modules)
        merged.blocked_modules.update(other.blocked_modules)
        merged.safe_builtins.update(other.safe_builtins)
        merged.blocked_attributes.update(other.blocked_attributes)
        
        # Merge rules
        merged.module_rules.extend(other.module_rules)
        merged.attribute_rules.extend(other.attribute_rules)
        
        # Merge paths and hosts
        merged.custom_allowed_paths.extend(other.custom_allowed_paths)
        merged.allowed_network_hosts.extend(other.allowed_network_hosts)
        
        # Override resource limits (other takes precedence if set)
        if other.resource_limits != ResourceLimits():
            merged.resource_limits = other.resource_limits
        
        # Override boolean flags
        merged.allow_imports = other.allow_imports
        merged.allow_file_io = other.allow_file_io
        merged.allow_network = other.allow_network
        merged.allow_subprocesses = other.allow_subprocesses
        merged.enable_logging = other.enable_logging
        merged.audit_events = other.audit_events
        
        if other.log_file:
            merged.log_file = other.log_file
        
        merged._invalidate_cache()
        return merged
    
    def __repr__(self) -> str:
        """Return string representation."""
        return f"SandboxConfig(level={self.security_level.name}, modules={len(self.allowed_modules)})"
    
    def __eq__(self, other: Any) -> bool:
        """Check equality with another configuration."""
        if not isinstance(other, SandboxConfig):
            return False
        return self.get_hash() == other.get_hash()
    
    def __str__(self) -> str:
        """Return user-friendly string."""
        return f"Sandbox Configuration ({self.security_level.name} level)"


# Pre-configured instances for common use cases
DEFAULT_CONFIG = SandboxConfig.from_profile(SecurityLevel.STANDARD)
STRICT_CONFIG = SandboxConfig.from_profile(SecurityLevel.STRICT)
PARANOID_CONFIG = SandboxConfig.from_profile(SecurityLevel.PARANOID)
MINIMAL_CONFIG = SandboxConfig.from_profile(SecurityLevel.MINIMAL)


# Export public interface
__all__ = [
    'SandboxConfig',
    'SecurityLevel',
    'ResourceLimit',
    'ResourceLimits',
    'ModuleRule',
    'AttributeRule',
    'DEFAULT_CONFIG',
    'STRICT_CONFIG',
    'PARANOID_CONFIG',
    'MINIMAL_CONFIG',
]