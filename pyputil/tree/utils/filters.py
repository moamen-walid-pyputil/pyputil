#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Requirement filtering and evaluation utilities with capabilities.

This module provides comprehensive filtering and evaluation of Python package
requirements with support for environment markers, version constraints,
platform filtering, and custom filter rules. It includes robust fallbacks
when the packaging library is not available and provides detailed logging
and debugging capabilities.
"""

import re
import sys
import os
import platform
import logging
from typing import Dict, List, Optional, Tuple, Set, Any, Callable, Union
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache, wraps
from datetime import datetime
import warnings
from collections import defaultdict
import json

# Configure module logger
logger = logging.getLogger(__name__)

# Try to import packaging libraries with fallbacks
try:
    from packaging.specifiers import SpecifierSet, InvalidSpecifier
    from packaging.markers import Marker, InvalidMarker
    from packaging.version import parse as parse_version, Version
    PACKAGING_AVAILABLE = True
    logger.debug("Using packaging library for requirement evaluation")
except ImportError:
    PACKAGING_AVAILABLE = False
    warnings.warn(
        "packaging library not found. Using built-in fallbacks for "
        "version comparison and marker evaluation. Install packaging "
        "for better accuracy: pip install packaging",
        UserWarning,
        stacklevel=2
    )
    logger.debug("Using built-in fallbacks for requirement evaluation")


class RequirementCategory(Enum):
    """
    Categorization of requirements based on their purpose and context.
    
    This enumeration provides a comprehensive classification system for
    Python package requirements, enabling fine-grained filtering and
    analysis of dependency trees.
    
    Attributes
    ----------
    PRODUCTION : str
        Core runtime dependencies required for normal operation
    DEVELOPMENT : str
        Dependencies used only during development and testing
    OPTIONAL : str
        Optional features that can be enabled via extras
    PEER : str
        Peer dependencies that should be installed alongside
    RECOMMENDED : str
        Recommended but not strictly required dependencies
    CONFLICT : str
        Dependencies that cause conflicts or version issues
    PLATFORM_SPECIFIC : str
        Dependencies that are platform-specific (Windows, Linux, macOS)
    PYTHON_VERSION_SPECIFIC : str
        Dependencies that require specific Python versions
    SECURITY : str
        Security-related dependencies or patches
    DOCUMENTATION : str
        Dependencies needed for building documentation
    BENCHMARK : str
        Dependencies used for performance benchmarking
    PACKAGING : str
        Dependencies used for building and packaging
    
    Examples
    --------
    >>> category = RequirementCategory.PRODUCTION
    >>> category.is_core()
    True
    >>> category.priority()
    10
    """
    
    PRODUCTION = "production"
    DEVELOPMENT = "development"
    OPTIONAL = "optional"
    PEER = "peer"
    RECOMMENDED = "recommended"
    CONFLICT = "conflict"
    PLATFORM_SPECIFIC = "platform_specific"
    PYTHON_VERSION_SPECIFIC = "python_version_specific"
    SECURITY = "security"
    DOCUMENTATION = "documentation"
    BENCHMARK = "benchmark"
    PACKAGING = "packaging"
    
    def is_core(self) -> bool:
        """
        Check if this category represents a core dependency.
        
        Core dependencies are essential for basic functionality and
        should typically be included in most environments.
        
        Returns
        -------
        bool
            True if category is core (PRODUCTION, SECURITY, PEER)
        
        Examples
        --------
        >>> RequirementCategory.PRODUCTION.is_core()
        True
        >>> RequirementCategory.DEVELOPMENT.is_core()
        False
        """
        return self in (RequirementCategory.PRODUCTION, 
                       RequirementCategory.SECURITY,
                       RequirementCategory.PEER)
    
    def priority(self) -> int:
        """
        Get installation priority for this category.
        
        Higher priority categories should be installed first and are
        more critical for application functionality.
        
        Returns
        -------
        int
            Priority value (1-10, with 10 being highest)
        
        Notes
        -----
        Priority order:
        10: PRODUCTION, SECURITY
        9: PEER
        8: RECOMMENDED
        7: OPTIONAL
        6: PLATFORM_SPECIFIC
        5: PYTHON_VERSION_SPECIFIC
        4: PACKAGING
        3: DOCUMENTATION
        2: BENCHMARK
        1: DEVELOPMENT
        0: CONFLICT (should not be installed)
        """
        priorities = {
            RequirementCategory.PRODUCTION: 10,
            RequirementCategory.SECURITY: 10,
            RequirementCategory.PEER: 9,
            RequirementCategory.RECOMMENDED: 8,
            RequirementCategory.OPTIONAL: 7,
            RequirementCategory.PLATFORM_SPECIFIC: 6,
            RequirementCategory.PYTHON_VERSION_SPECIFIC: 5,
            RequirementCategory.PACKAGING: 4,
            RequirementCategory.DOCUMENTATION: 3,
            RequirementCategory.BENCHMARK: 2,
            RequirementCategory.DEVELOPMENT: 1,
            RequirementCategory.CONFLICT: 0
        }
        return priorities.get(self, 5)
    
    def get_color_code(self) -> str:
        """
        Get ANSI color code for visual representation.
        
        Returns
        -------
        str
            ANSI color code string
        """
        colors = {
            RequirementCategory.PRODUCTION: "\033[92m",  # Green
            RequirementCategory.DEVELOPMENT: "\033[94m",  # Blue
            RequirementCategory.OPTIONAL: "\033[93m",    # Yellow
            RequirementCategory.PEER: "\033[95m",        # Magenta
            RequirementCategory.RECOMMENDED: "\033[96m", # Cyan
            RequirementCategory.CONFLICT: "\033[91m",    # Red
            RequirementCategory.SECURITY: "\033[91m",    # Red
        }
        return colors.get(self, "\033[0m")  # Default reset
    
    def __str__(self) -> str:
        """Return string representation."""
        return self.value


class FilterOperator(Enum):
    """
    Comparison operators for custom filter rules.
    
    This enumeration defines all available operators for creating
    sophisticated filtering rules on requirement attributes.
    
    Attributes
    ----------
    EQUALS : str
        Exact equality comparison (==)
    NOT_EQUALS : str
        Inequality comparison (!=)
    GREATER_THAN : str
        Greater than comparison (>)
    LESS_THAN : str
        Less than comparison (<)
    GREATER_EQUALS : str
        Greater than or equal to (>=)
    LESS_EQUALS : str
        Less than or equal to (<=)
    IN : str
        Membership in a collection (in)
    NOT_IN : str
        Non-membership in a collection (not in)
    CONTAINS : str
        Substring containment (contains)
    MATCHES : str
        Regular expression pattern matching (matches)
    EXISTS : str
        Field existence check (exists)
    START_WITH : str
        String prefix matching (starts with)
    END_WITH : str
        String suffix matching (ends with)
    
    Examples
    --------
    >>> op = FilterOperator.EQUALS
    >>> op.value
    '=='
    >>> op.is_comparison()
    True
    """
    
    EQUALS = "=="
    NOT_EQUALS = "!="
    GREATER_THAN = ">"
    LESS_THAN = "<"
    GREATER_EQUALS = ">="
    LESS_EQUALS = "<="
    IN = "in"
    NOT_IN = "not in"
    CONTAINS = "contains"
    MATCHES = "matches"
    EXISTS = "exists"
    START_WITH = "startswith"
    END_WITH = "endswith"
    
    def is_comparison(self) -> bool:
        """
        Check if operator is a value comparison.
        
        Returns
        -------
        bool
            True for equality/inequality operators
        """
        return self in (FilterOperator.EQUALS, FilterOperator.NOT_EQUALS,
                       FilterOperator.GREATER_THAN, FilterOperator.LESS_THAN,
                       FilterOperator.GREATER_EQUALS, FilterOperator.LESS_EQUALS)
    
    def is_membership(self) -> bool:
        """
        Check if operator checks membership.
        
        Returns
        -------
        bool
            True for IN/NOT_IN operators
        """
        return self in (FilterOperator.IN, FilterOperator.NOT_IN)
    
    def is_pattern(self) -> bool:
        """
        Check if operator uses pattern matching.
        
        Returns
        -------
        bool
            True for CONTAINS/MATCHES/START_WITH/END_WITH
        """
        return self in (FilterOperator.CONTAINS, FilterOperator.MATCHES,
                       FilterOperator.START_WITH, FilterOperator.END_WITH)


@dataclass
class FilterRule:
    """
    Custom filter rule for fine-grained requirement evaluation.
    
    A FilterRule represents a single condition that can be evaluated
    against requirement information. Multiple rules can be combined
    to create complex filtering logic.
    
    Parameters
    ----------
    field : str
        Field to filter on (e.g., 'name', 'version', 'marker', 'extra')
    operator : FilterOperator
        Comparison operator to apply
    value : Any
        Value to compare against
    negate : bool, default=False
        Whether to negate the evaluation result
    description : str, optional
        Human-readable description of the rule
    
    Attributes
    ----------
    field : str
        Field name for filtering
    operator : FilterOperator
        Comparison operator
    value : Any
        Comparison value
    negate : bool
        Negation flag
    description : str
        Rule description
    created_at : datetime
        Timestamp when rule was created
    
    Examples
    --------
    >>> # Create rule to include only packages starting with 'django'
    >>> rule = FilterRule(
    ...     field='name',
    ...     operator=FilterOperator.START_WITH,
    ...     value='django',
    ...     description='Django packages only'
    ... )
    >>> rule.evaluate({'name': 'django-rest-framework'})
    True
    >>> rule.evaluate({'name': 'requests'})
    False
    
    >>> # Create rule to exclude test dependencies
    >>> rule = FilterRule(
    ...     field='marker',
    ...     operator=FilterOperator.CONTAINS,
    ...     value='test',
    ...     negate=True,
    ...     description='Exclude test dependencies'
    ... )
    """
    
    field: str
    operator: FilterOperator
    value: Any
    negate: bool = False
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """Initialize default description if not provided."""
        if not self.description:
            negate_str = "NOT " if self.negate else ""
            self.description = f"{negate_str}{self.field} {self.operator.value} {self.value}"
    
    def evaluate(self, requirement_info: Dict[str, Any]) -> bool:
        """
        Evaluate this filter rule against requirement information.
        
        This method performs the actual comparison based on the rule's
        field, operator, and value. It handles various data types and
        provides appropriate error handling.
        
        Parameters
        ----------
        requirement_info : Dict[str, Any]
            Requirement information dictionary containing fields like:
            - 'name': Package name
            - 'version_spec': Version specification string
            - 'marker': Environment marker string
            - 'extras': List of extras
            - 'category': RequirementCategory
            - 'platform': Platform specification
            - 'python_version': Python version requirement
        
        Returns
        -------
        bool
            True if the rule matches the requirement, False otherwise
        
        Raises
        ------
        ValueError
            If field doesn't exist in requirement_info
        
        Examples
        --------
        >>> rule = FilterRule('name', FilterOperator.EQUALS, 'requests')
        >>> rule.evaluate({'name': 'requests', 'version': '2.28.1'})
        True
        
        >>> rule = FilterRule('version', FilterOperator.GREATER_THAN, '2.0')
        >>> rule.evaluate({'name': 'requests', 'version_spec': '>2.0'})
        True
        """
        # Get field value
        field_value = requirement_info.get(self.field)
        
        # Handle missing fields
        if field_value is None:
            if self.operator == FilterOperator.EXISTS:
                result = False
            else:
                result = False
            return not result if self.negate else result
        
        # Special handling for list fields
        if isinstance(field_value, list):
            field_value = ','.join(field_value)
        elif not isinstance(field_value, str):
            field_value = str(field_value)
        
        try:
            # Apply operator
            if self.operator == FilterOperator.EQUALS:
                result = field_value == str(self.value)
            elif self.operator == FilterOperator.NOT_EQUALS:
                result = field_value != str(self.value)
            elif self.operator == FilterOperator.GREATER_THAN:
                result = self._compare_versions(field_value, self.value, '>')
            elif self.operator == FilterOperator.LESS_THAN:
                result = self._compare_versions(field_value, self.value, '<')
            elif self.operator == FilterOperator.GREATER_EQUALS:
                result = self._compare_versions(field_value, self.value, '>=')
            elif self.operator == FilterOperator.LESS_EQUALS:
                result = self._compare_versions(field_value, self.value, '<=')
            elif self.operator == FilterOperator.IN:
                result = field_value in self.value
            elif self.operator == FilterOperator.NOT_IN:
                result = field_value not in self.value
            elif self.operator == FilterOperator.CONTAINS:
                result = str(self.value).lower() in str(field_value).lower()
            elif self.operator == FilterOperator.MATCHES:
                result = bool(re.search(str(self.value), str(field_value), re.IGNORECASE))
            elif self.operator == FilterOperator.START_WITH:
                result = str(field_value).lower().startswith(str(self.value).lower())
            elif self.operator == FilterOperator.END_WITH:
                result = str(field_value).lower().endswith(str(self.value).lower())
            elif self.operator == FilterOperator.EXISTS:
                result = True
            else:
                result = False
            
            # Apply negation if needed
            return not result if self.negate else result
            
        except Exception as e:
            logger.debug(f"Rule evaluation failed: {e}")
            return False
    
    def _compare_versions(self, left: str, right: str, operator: str) -> bool:
        """
        Compare two version strings using specified operator.
        
        Parameters
        ----------
        left : str
            Left version string
        right : str
            Right version string
        operator : str
            Comparison operator (>, <, >=, <=)
        
        Returns
        -------
        bool
            Comparison result
        """
        if PACKAGING_AVAILABLE:
            try:
                left_ver = parse_version(left)
                right_ver = parse_version(right)
                
                if operator == '>':
                    return left_ver > right_ver
                elif operator == '<':
                    return left_ver < right_ver
                elif operator == '>=':
                    return left_ver >= right_ver
                elif operator == '<=':
                    return left_ver <= right_ver
            except Exception:
                pass
        
        # Fallback to simple string comparison
        def normalize(v: str) -> List[Union[int, str]]:
            parts = []
            for part in re.split(r'[.-]', v):
                try:
                    parts.append(int(part))
                except ValueError:
                    parts.append(part)
            return parts
        
        left_norm = normalize(str(left))
        right_norm = normalize(str(right))
        
        if operator == '>':
            return left_norm > right_norm
        elif operator == '<':
            return left_norm < right_norm
        elif operator == '>=':
            return left_norm >= right_norm
        elif operator == '<=':
            return left_norm <= right_norm
        
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert filter rule to dictionary representation.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary with rule data
        """
        return {
            'field': self.field,
            'operator': self.operator.value,
            'value': self.value,
            'negate': self.negate,
            'description': self.description,
            'created_at': self.created_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FilterRule':
        """
        Create filter rule from dictionary.
        
        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary with rule data
        
        Returns
        -------
        FilterRule
            Reconstructed filter rule
        
        Examples
        --------
        >>> data = {'field': 'name', 'operator': '==', 'value': 'requests'}
        >>> rule = FilterRule.from_dict(data)
        """
        operator = FilterOperator(data['operator'])
        return cls(
            field=data['field'],
            operator=operator,
            value=data['value'],
            negate=data.get('negate', False),
            description=data.get('description', '')
        )
    
    def __repr__(self) -> str:
        """String representation of the rule."""
        return f"<FilterRule: {self.description}>"


class EvaluationContext:
    """
    Context manager for requirement evaluation with caching.
    
    This class manages the environment context for evaluating requirements,
    providing caching of marker evaluations and version comparisons to
    improve performance when processing many requirements.
    
    Parameters
    ----------
    environment : Dict[str, str], optional
        Custom environment variables for evaluation
    enable_cache : bool, default=True
        Whether to cache evaluation results
    cache_size : int, default=1000
        Maximum number of cached results
    
    Attributes
    ----------
    environment : Dict[str, str]
        Current evaluation environment
    _cache : Dict[str, bool]
        Cache of evaluation results
    _stats : Dict[str, int]
        Cache statistics
    
    Examples
    --------
    >>> ctx = EvaluationContext()
    >>> with ctx as env:
    ...     marker = "python_version >= '3.8'"
    ...     result = env.evaluate_marker(marker)
    >>> ctx.get_cache_stats()
    {'hits': 0, 'misses': 1, 'size': 1}
    """
    
    def __init__(self, environment: Optional[Dict[str, str]] = None,
                 enable_cache: bool = True, cache_size: int = 1000):
        self.environment = environment or self._get_default_environment()
        self.enable_cache = enable_cache
        self.cache_size = cache_size
        self._cache: Dict[str, bool] = {}
        self._stats = {'hits': 0, 'misses': 0, 'size': 0}
        self._marker_cache: Dict[str, bool] = {}
    
    def _get_default_environment(self) -> Dict[str, str]:
        """
        Get default environment information.
        
        Returns
        -------
        Dict[str, str]
            Dictionary with environment variables
        """
        implementation = platform.python_implementation().lower()
        sys_platform = sys.platform
        platform_system = platform.system().lower()
        platform_machine = platform.machine().lower()
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        python_full_version = (
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )
        
        return {
            "implementation_name": implementation,
            "implementation_version": platform.python_version(),
            "python_version": python_version,
            "python_full_version": python_full_version,
            "sys_platform": sys_platform,
            "platform_system": platform_system,
            "platform_machine": platform_machine,
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "os_name": os.name,
            "extra": "",
        }
    
    def evaluate_marker(self, marker: str) -> bool:
        """
        Evaluate an environment marker string.
        
        Parameters
        ----------
        marker : str
            PEP 508 environment marker string
        
        Returns
        -------
        bool
            True if marker evaluates to True in current environment
        
        Notes
        -----
        Results are cached for performance when enable_cache is True.
        """
        if not marker:
            return True
        
        # Check cache
        cache_key = f"marker:{marker}"
        if self.enable_cache and cache_key in self._marker_cache:
            self._stats['hits'] += 1
            return self._marker_cache[cache_key]
        
        self._stats['misses'] += 1
        
        try:
            if PACKAGING_AVAILABLE:
                marker_obj = Marker(marker)
                result = marker_obj.evaluate(environment=self.environment)
            else:
                result = self._evaluate_marker_fallback(marker)
            
            # Cache result
            if self.enable_cache:
                self._marker_cache[cache_key] = result
                self._stats['size'] = len(self._marker_cache)
                
                # Trim cache if needed
                if len(self._marker_cache) > self.cache_size:
                    # Remove oldest entries (simple FIFO)
                    remove_count = len(self._marker_cache) - self.cache_size
                    for _ in range(remove_count):
                        self._marker_cache.popitem(last=False)
            
            return result
            
        except Exception as e:
            logger.debug(f"Marker evaluation failed for '{marker}': {e}")
            return False
    
    def _evaluate_marker_fallback(self, marker: str) -> bool:
        """
        Fallback marker evaluation when packaging is not available.
        
        Parameters
        ----------
        marker : str
            Marker string to evaluate
        
        Returns
        -------
        bool
            Evaluation result
        """
        marker_lower = marker.lower()
        
        # Simple pattern matching for common markers
        patterns = {
            r"python_version\s*==\s*['\"](\d+\.\d+)['\"]": 
                lambda m: self.environment.get('python_version') == m.group(1),
            r"python_version\s*>=\s*['\"](\d+\.\d+)['\"]": 
                lambda m: self._compare_versions(
                    self.environment.get('python_version', ''), 
                    m.group(1), '>='
                ),
            r"python_version\s*<=\s*['\"](\d+\.\d+)['\"]": 
                lambda m: self._compare_versions(
                    self.environment.get('python_version', ''), 
                    m.group(1), '<='
                ),
            r"sys_platform\s*==\s*['\"]([^'\"]+)['\"]": 
                lambda m: self.environment.get('sys_platform', '') == m.group(1),
            r"platform_system\s*==\s*['\"]([^'\"]+)['\"]": 
                lambda m: self.environment.get('platform_system', '') == m.group(1).lower(),
            r"extra\s*==\s*['\"]([^'\"]+)['\"]": 
                lambda m: self.environment.get('extra', '') == m.group(1),
        }
        
        for pattern, evaluator in patterns.items():
            match = re.search(pattern, marker)
            if match:
                return evaluator(match)
        
        # Default to True for complex markers
        logger.debug(f"Complex marker '{marker}' using fallback, defaulting to True")
        return True
    
    def _compare_versions(self, ver1: str, ver2: str, operator: str) -> bool:
        """
        Compare two version strings.
        
        Parameters
        ----------
        ver1 : str
            First version
        ver2 : str
            Second version
        operator : str
            Comparison operator
        
        Returns
        -------
        bool
            Comparison result
        """
        def normalize(v: str) -> tuple:
            parts = v.split('.')
            return tuple(int(p) if p.isdigit() else p for p in parts)
        
        try:
            v1 = normalize(ver1)
            v2 = normalize(ver2)
            
            if operator == '>=':
                return v1 >= v2
            elif operator == '<=':
                return v1 <= v2
            elif operator == '>':
                return v1 > v2
            elif operator == '<':
                return v1 < v2
            elif operator == '==':
                return v1 == v2
        except Exception:
            pass
        
        return False
    
    def evaluate_version_spec(self, version_spec: str, current_version: Optional[str] = None) -> bool:
        """
        Evaluate a version specification against current or provided version.
        
        Parameters
        ----------
        version_spec : str
            Version specification string (e.g., '>=1.0,<2.0')
        current_version : str, optional
            Version to check (defaults to current Python version)
        
        Returns
        -------
        bool
            True if version meets specification
        """
        if not version_spec:
            return True
        
        if current_version is None:
            current_version = self.environment.get('python_version', '')
        
        cache_key = f"version:{version_spec}:{current_version}"
        if self.enable_cache and cache_key in self._cache:
            self._stats['hits'] += 1
            return self._cache[cache_key]
        
        self._stats['misses'] += 1
        
        try:
            if PACKAGING_AVAILABLE:
                specifier_set = SpecifierSet(version_spec)
                result = current_version in specifier_set
            else:
                result = self._evaluate_version_spec_fallback(version_spec, current_version)
            
            if self.enable_cache:
                self._cache[cache_key] = result
                self._stats['size'] = len(self._cache)
                
                if len(self._cache) > self.cache_size:
                    remove_count = len(self._cache) - self.cache_size
                    for _ in range(remove_count):
                        self._cache.popitem(last=False)
            
            return result
            
        except Exception as e:
            logger.debug(f"Version spec evaluation failed: {e}")
            return False
    
    def _evaluate_version_spec_fallback(self, version_spec: str, current_version: str) -> bool:
        """
        Fallback version spec evaluation when packaging is not available.
        
        Parameters
        ----------
        version_spec : str
            Version specification
        current_version : str
            Current version to check
        
        Returns
        -------
        bool
            True if version matches
        """
        # Parse specifiers
        specifiers = re.findall(r'([<>=!~]=?)\s*([0-9.]+(?:[a-z.]+)?)', version_spec)
        
        for operator, version in specifiers:
            if not self._compare_versions(current_version, version, operator):
                return False
        
        return True
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache performance statistics.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary with cache statistics
        """
        total = self._stats['hits'] + self._stats['misses']
        hit_rate = self._stats['hits'] / total if total > 0 else 0.0
        
        return {
            'hits': self._stats['hits'],
            'misses': self._stats['misses'],
            'hit_rate': hit_rate,
            'cache_size': self._stats['size'],
            'max_cache_size': self.cache_size,
            'marker_cache_size': len(self._marker_cache)
        }
    
    def clear_cache(self) -> None:
        """Clear all cached evaluation results."""
        self._cache.clear()
        self._marker_cache.clear()
        self._stats = {'hits': 0, 'misses': 0, 'size': 0}
        logger.debug("Evaluation cache cleared")
    
    def __enter__(self) -> 'EvaluationContext':
        """Enter context manager."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager - cleanup if needed."""
        pass


class RequirementFilter:
    """
    Advanced filter for requirement evaluation with multiple strategies.
    
    This class provides comprehensive filtering capabilities for Python
    requirements with support for environment markers, version constraints,
    custom rules, and batch evaluation. It's designed for analyzing
    dependency trees and determining which requirements should be included
    in specific environments.
    
    Parameters
    ----------
    skip_optional : bool, default=False
        Whether to skip optional dependencies (dependencies with 'extra' markers)
    skip_development : bool, default=False
        Whether to skip development dependencies (dev, test, docs markers)
    platform_filter : str, optional
        Platform filter ('linux', 'windows', 'darwin', 'unix', 'any')
    python_version_filter : str, optional
        Python version constraint (e.g., '>=3.8', '==3.9.*')
    include_extras : List[str], optional
        List of extras to include (e.g., ['security', 'performance'])
    exclude_extras : List[str], optional
        List of extras to exclude
    include_markers : List[str], optional
        Marker keywords to include (e.g., ['extra', 'platform'])
    exclude_markers : List[str], optional
        Marker keywords to exclude
    include_categories : List[RequirementCategory], optional
        Requirement categories to include
    exclude_categories : List[RequirementCategory], optional
        Requirement categories to exclude
    custom_rules : List[FilterRule], optional
        Custom filter rules for fine-grained control
    strict_mode : bool, default=False
        Whether to fail on invalid markers/specifiers
    cache_results : bool, default=True
        Whether to cache evaluation results for performance
    evaluation_context : EvaluationContext, optional
        Custom evaluation context (creates new if not provided)
    
    Attributes
    ----------
    rules : List[FilterRule]
        List of active filter rules
    evaluation_context : EvaluationContext
        Context for marker and version evaluation
    _stats : Dict[str, int]
        Filtering statistics
    
    Examples
    --------
    >>> # Create filter for production environment
    >>> prod_filter = RequirementFilter(
    ...     skip_development=True,
    ...     skip_optional=True,
    ...     platform_filter='linux',
    ...     python_version_filter='>=3.8'
    ... )
    
    >>> # Filter a requirement
    >>> should_include = prod_filter.should_include(
    ...     version_spec=">=1.0",
    ...     marker="sys_platform == 'linux'"
    ... )
    >>> print(should_include)
    True
    
    >>> # Filter with custom rules
    >>> custom_filter = RequirementFilter(
    ...     custom_rules=[
    ...         FilterRule('name', FilterOperator.START_WITH, 'django'),
    ...         FilterRule('version', FilterOperator.GREATER_THAN, '2.0')
    ...     ]
    ... )
    
    >>> # Batch filtering
    >>> requirements = [
    ...     {'name': 'django', 'version_spec': '>=3.2', 'marker': ''},
    ...     {'name': 'requests', 'version_spec': '>=2.0', 'marker': "extra == 'dev'"}
    ... ]
    >>> results = prod_filter.filter_batch(requirements)
    >>> print(results)
    [{'name': 'django', ...}, ...]
    """
    
    def __init__(self, skip_optional: bool = False,
                 skip_development: bool = False,
                 platform_filter: Optional[str] = None,
                 python_version_filter: Optional[str] = None,
                 include_extras: Optional[List[str]] = None,
                 exclude_extras: Optional[List[str]] = None,
                 include_markers: Optional[List[str]] = None,
                 exclude_markers: Optional[List[str]] = None,
                 include_categories: Optional[List[RequirementCategory]] = None,
                 exclude_categories: Optional[List[RequirementCategory]] = None,
                 custom_rules: Optional[List[FilterRule]] = None,
                 strict_mode: bool = False,
                 cache_results: bool = True,
                 evaluation_context: Optional[EvaluationContext] = None):
        
        self.skip_optional = skip_optional
        self.skip_development = skip_development
        self.platform_filter = platform_filter.lower() if platform_filter else None
        self.python_version_filter = python_version_filter
        self.include_extras = set(include_extras or [])
        self.exclude_extras = set(exclude_extras or [])
        self.include_markers = [m.lower() for m in (include_markers or [])]
        self.exclude_markers = [m.lower() for m in (exclude_markers or [])]
        self.include_categories = set(include_categories or [])
        self.exclude_categories = set(exclude_categories or [])
        self.custom_rules = custom_rules or []
        self.strict_mode = strict_mode
        self.cache_results = cache_results
        self.evaluation_context = evaluation_context or EvaluationContext(enable_cache=cache_results)
        
        # Statistics
        self._stats = {
            'total_evaluations': 0,
            'included': 0,
            'excluded': 0,
            'by_reason': defaultdict(int)
        }
        
        # Build rule list
        self.rules = self._build_rules()
        
        logger.info(f"RequirementFilter initialized with {len(self.rules)} rules")
    
    def _build_rules(self) -> List[FilterRule]:
        """
        Build internal filter rules from configuration.
        
        Returns
        -------
        List[FilterRule]
            List of filter rules to evaluate
        """
        rules = []
        
        # Optional filtering rule
        if self.skip_optional:
            rules.append(FilterRule(
                field='marker',
                operator=FilterOperator.CONTAINS,
                value='extra',
                negate=False,
                description='Exclude optional dependencies'
            ))
        
        # Development filtering rule
        if self.skip_development:
            dev_keywords = ['dev', 'test', 'testing', 'docs', 'doc', 'documentation', 'benchmark']
            for keyword in dev_keywords:
                rules.append(FilterRule(
                    field='marker',
                    operator=FilterOperator.CONTAINS,
                    value=keyword,
                    negate=False,
                    description=f'Exclude development dependencies ({keyword})'
                ))
        
        # Platform filtering
        if self.platform_filter and self.platform_filter != 'any':
            platform_map = {
                'linux': ['linux'],
                'windows': ['win32', 'cygwin'],
                'darwin': ['darwin', 'macos'],
                'unix': ['linux', 'darwin', 'freebsd', 'openbsd']
            }
            
            allowed_platforms = platform_map.get(self.platform_filter, [])
            rules.append(FilterRule(
                field='marker',
                operator=FilterOperator.MATCHES,
                value=f"sys_platform.*(?:{'|'.join(allowed_platforms)})",
                negate=False,
                description=f'Include only {self.platform_filter} platform'
            ))
        
        # Python version filtering
        if self.python_version_filter:
            rules.append(FilterRule(
                field='python_version',
                operator=FilterOperator.MATCHES,
                value=self.python_version_filter,
                negate=False,
                description=f'Python version {self.python_version_filter}'
            ))
        
        # Extras filtering
        if self.include_extras:
            for extra in self.include_extras:
                rules.append(FilterRule(
                    field='extra',
                    operator=FilterOperator.EQUALS,
                    value=extra,
                    negate=False,
                    description=f'Include extra: {extra}'
                ))
        
        if self.exclude_extras:
            for extra in self.exclude_extras:
                rules.append(FilterRule(
                    field='extra',
                    operator=FilterOperator.EQUALS,
                    value=extra,
                    negate=True,
                    description=f'Exclude extra: {extra}'
                ))
        
        # Add custom rules        rules.extend(self.custom_rules)
        
        return rules
    
    def should_include(self, version_spec: str = "", marker: str = "",
                      requirement_info: Optional[Dict[str, Any]] = None,
                      **kwargs) -> bool:
        """
        Determine whether a requirement should be included.
        
        This is the primary evaluation method that applies all configured
        filters to a requirement and returns a boolean decision.
        
        Parameters
        ----------
        version_spec : str, default=""
            Version specification string (e.g., ">=1.0,<2.0")
        marker : str, default=""
            Environment marker string (PEP 508)
        requirement_info : Dict[str, Any], optional
            Additional requirement information (name, extras, category, etc.)
        **kwargs
            Additional keyword arguments that override requirement_info fields
        
        Returns
        -------
        bool
            True if requirement should be included, False otherwise
        
        Raises
        ------
        ValueError
            If in strict mode and evaluation fails
        
        Examples
        --------
        >>> filter = RequirementFilter(skip_optional=True)
        >>> filter.should_include(marker="extra == 'security'")
        False
        
        >>> filter = RequirementFilter(platform_filter='linux')
        >>> filter.should_include(marker="sys_platform == 'linux'")
        True
        
        >>> filter = RequirementFilter(custom_rules=[
        ...     FilterRule('name', FilterOperator.START_WITH, 'django')
        ... ])
        >>> filter.should_include(requirement_info={'name': 'django-rest'})
        True
        """
        self._stats['total_evaluations'] += 1
        
        # Build requirement info
        info = requirement_info or {}
        info.update({
            'version_spec': version_spec,
            'marker': marker,
            **kwargs
        })
        
        # Extract marker and extra for easier access
        if marker and 'extra' not in info:
            extra_match = re.search(r"extra\s*==\s*['\"]([^'\"]+)['\"]", marker.lower())
            if extra_match:
                info['extra'] = extra_match.group(1)
        
        # Extract python_version from marker
        if marker and 'python_version' not in info:
            py_match = re.search(r"python_version\s*([<>=!]+)\s*['\"]([^'\"]+)['\"]", marker)
            if py_match:
                info['python_version_constraint'] = f"{py_match.group(1)}{py_match.group(2)}"
        
        # Set default category if not provided
        if 'category' not in info:
            info['category'] = self._determine_category(info)
        
        # Evaluate each rule
        for rule in self.rules:
            try:
                if not rule.evaluate(info):
                    reason = f"Rule failed: {rule.description}"
                    self._stats['excluded'] += 1
                    self._stats['by_reason'][reason] += 1
                    logger.debug(f"Requirement excluded: {reason}")
                    return False
            except Exception as e:
                if self.strict_mode:
                    raise ValueError(f"Rule evaluation failed: {e}")
                logger.warning(f"Rule evaluation error (skipping): {e}")
        
        # Evaluate environment marker
        if marker:
            try:
                if not self.evaluation_context.evaluate_marker(marker):
                    reason = "Environment marker evaluation failed"
                    self._stats['excluded'] += 1
                    self._stats['by_reason'][reason] += 1
                    logger.debug(f"Requirement excluded: {reason}")
                    return False
            except Exception as e:
                if self.strict_mode:
                    raise ValueError(f"Marker evaluation failed: {e}")
                logger.warning(f"Marker evaluation error (skipping): {e}")
        
        # Evaluate version spec if provided
        if version_spec and version_spec.strip():
            try:
                # Get current version or use provided
                current_version = info.get('current_version')
                if not self.evaluation_context.evaluate_version_spec(version_spec, current_version):
                    reason = f"Version spec not satisfied: {version_spec}"
                    self._stats['excluded'] += 1
                    self._stats['by_reason'][reason] += 1
                    logger.debug(f"Requirement excluded: {reason}")
                    return False
            except Exception as e:
                if self.strict_mode:
                    raise ValueError(f"Version spec evaluation failed: {e}")
                logger.warning(f"Version spec evaluation error (skipping): {e}")
        
        # Category filtering
        if info.get('category'):
            category = info['category']
            if self.include_categories and category not in self.include_categories:
                reason = f"Category not in include list: {category}"
                self._stats['excluded'] += 1
                self._stats['by_reason'][reason] += 1
                return False
            
            if self.exclude_categories and category in self.exclude_categories:
                reason = f"Category in exclude list: {category}"
                self._stats['excluded'] += 1
                self._stats['by_reason'][reason] += 1
                return False
        
        # All filters passed
        self._stats['included'] += 1
        logger.debug(f"Requirement included: {info.get('name', 'unknown')}")
        return True
    
    def _determine_category(self, info: Dict[str, Any]) -> RequirementCategory:
        """
        Determine requirement category based on markers and metadata.
        
        Parameters
        ----------
        info : Dict[str, Any]
            Requirement information
        
        Returns
        -------
        RequirementCategory
            Determined category
        """
        marker = info.get('marker', '').lower()
        
        # Check categories in priority order
        if 'extra' in marker:
            return RequirementCategory.OPTIONAL
        elif any(kw in marker for kw in ['dev', 'test', 'testing']):
            return RequirementCategory.DEVELOPMENT
        elif any(kw in marker for kw in ['docs', 'doc']):
            return RequirementCategory.DOCUMENTATION
        elif 'benchmark' in marker:
            return RequirementCategory.BENCHMARK
        elif any(kw in marker for kw in ['platform', 'sys_platform']):
            return RequirementCategory.PLATFORM_SPECIFIC
        elif 'python_version' in marker:
            return RequirementCategory.PYTHON_VERSION_SPECIFIC
        elif 'packaging' in marker or 'build' in marker:
            return RequirementCategory.PACKAGING
        else:
            return RequirementCategory.PRODUCTION
    
    def filter_batch(self, requirements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter multiple requirements in batch.
        
        Parameters
        ----------
        requirements : List[Dict[str, Any]]
            List of requirement dictionaries, each containing fields like
            'name', 'version_spec', 'marker', 'extras', etc.
        
        Returns
        -------
        List[Dict[str, Any]]
            Filtered list of requirements that passed all filters
        
        Examples
        --------
        >>> filter = RequirementFilter(skip_development=True)
        >>> reqs = [
        ...     {'name': 'django', 'version_spec': '>=3.2', 'marker': ''},
        ...     {'name': 'pytest', 'marker': "extra == 'dev'"},
        ...     {'name': 'requests', 'version_spec': '>=2.0', 'marker': ''}
        ... ]
        >>> filtered = filter.filter_batch(reqs)
        >>> len(filtered)
        2
        """
        results = []
        
        for req in requirements:
            if self.should_include(
                version_spec=req.get('version_spec', ''),
                marker=req.get('marker', ''),
                requirement_info=req
            ):
                results.append(req)
        
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get filtering statistics.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary containing filtering statistics including:
            - total_evaluations: Number of evaluations performed
            - included: Number of requirements included
            - excluded: Number of requirements excluded
            - inclusion_rate: Percentage of requirements included
            - exclusion_reasons: Breakdown of exclusion reasons
            - cache_stats: Cache performance statistics
        """
        total = self._stats['total_evaluations']
        inclusion_rate = self._stats['included'] / total if total > 0 else 0.0
        
        return {
            'total_evaluations': total,
            'included': self._stats['included'],
            'excluded': self._stats['excluded'],
            'inclusion_rate': inclusion_rate,
            'exclusion_reasons': dict(self._stats['by_reason']),
            'cache_stats': self.evaluation_context.get_cache_stats(),
            'active_rules_count': len(self.rules)
        }
    
    def reset_stats(self) -> None:
        """Reset filtering statistics."""
        self._stats = {
            'total_evaluations': 0,
            'included': 0,
            'excluded': 0,
            'by_reason': defaultdict(int)
        }
        logger.debug("Filter statistics reset")
    
    def add_custom_rule(self, rule: FilterRule) -> None:
        """
        Add a custom filter rule.
        
        Parameters
        ----------
        rule : FilterRule
            Custom rule to add
        
        Examples
        --------
        >>> filter = RequirementFilter()
        >>> rule = FilterRule('name', FilterOperator.MATCHES, '^django')
        >>> filter.add_custom_rule(rule)
        """
        self.rules.append(rule)
        logger.debug(f"Added custom rule: {rule.description}")
    
    def remove_custom_rule(self, rule_description: str) -> bool:
        """
        Remove a custom filter rule by description.
        
        Parameters
        ----------
        rule_description : str
            Description of the rule to remove
        
        Returns
        -------
        bool
            True if rule was found and removed
        
        Examples
        --------
        >>> filter = RequirementFilter()
        >>> rule = FilterRule('name', FilterOperator.EQUALS, 'requests')
        >>> filter.add_custom_rule(rule)
        >>> filter.remove_custom_rule("name == requests")
        True
        """
        for i, rule in enumerate(self.rules):
            if rule.description == rule_description:
                self.rules.pop(i)
                logger.debug(f"Removed rule: {rule_description}")
                return True
        return False
    
    def to_config(self) -> Dict[str, Any]:
        """
        Export filter configuration to dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Filter configuration that can be saved and reloaded
        """
        return {
            'skip_optional': self.skip_optional,
            'skip_development': self.skip_development,
            'platform_filter': self.platform_filter,
            'python_version_filter': self.python_version_filter,
            'include_extras': list(self.include_extras),
            'exclude_extras': list(self.exclude_extras),
            'include_markers': self.include_markers,
            'exclude_markers': self.exclude_markers,
            'include_categories': [c.value for c in self.include_categories],
            'exclude_categories': [c.value for c in self.exclude_categories],
            'custom_rules': [rule.to_dict() for rule in self.custom_rules],
            'strict_mode': self.strict_mode
        }
    
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> 'RequirementFilter':
        """
        Create RequirementFilter from configuration dictionary.
        
        Parameters
        ----------
        config : Dict[str, Any]
            Configuration dictionary (usually from to_config())
        
        Returns
        -------
        RequirementFilter
            Configured RequirementFilter instance
        
        Examples
        --------
        >>> config = {'skip_development': True, 'platform_filter': 'linux'}
        >>> filter = RequirementFilter.from_config(config)
        """
        # Convert category strings back to enums
        include_categories = None
        if 'include_categories' in config:
            include_categories = [RequirementCategory(c) for c in config['include_categories']]
        
        exclude_categories = None
        if 'exclude_categories' in config:
            exclude_categories = [RequirementCategory(c) for c in config['exclude_categories']]
        
        # Convert custom rules from dicts
        custom_rules = None
        if 'custom_rules' in config:
            custom_rules = [FilterRule.from_dict(rule) for rule in config['custom_rules']]
        
        return cls(
            skip_optional=config.get('skip_optional', False),
            skip_development=config.get('skip_development', False),
            platform_filter=config.get('platform_filter'),
            python_version_filter=config.get('python_version_filter'),
            include_extras=config.get('include_extras'),
            exclude_extras=config.get('exclude_extras'),
            include_markers=config.get('include_markers'),
            exclude_markers=config.get('exclude_markers'),
            include_categories=include_categories,
            exclude_categories=exclude_categories,
            custom_rules=custom_rules,
            strict_mode=config.get('strict_mode', False)
        )
    
    def __repr__(self) -> str:
        """String representation of the filter."""
        return (f"<RequirementFilter: {len(self.rules)} rules, "
                f"{self._stats['total_evaluations']} evaluations>")


# Convenience functions for backward compatibility

def should_include_requirement(
    version_spec: str = "",
    marker: str = "",
    skip_optional: bool = False,
    skip_development: bool = False,
    platform_filter: Optional[str] = None,
    python_version_filter: Optional[str] = None,
    include_extras: Optional[List[str]] = None,
    exclude_extras: Optional[List[str]] = None,
    include_markers: Optional[List[str]] = None,
    exclude_markers: Optional[List[str]] = None,
    current_environment: Optional[Dict[str, str]] = None,
    **kwargs
) -> bool:
    """
    Legacy function for requirement inclusion checking.
    
    This function maintains backward compatibility with the original API
    while using the enhanced RequirementFilter internally.
    
    Parameters
    ----------
    version_spec : str, default=""
        Version specification string
    marker : str, default=""
        Environment marker string
    skip_optional : bool, default=False
        Skip optional dependencies
    skip_development : bool, default=False
        Skip development dependencies
    platform_filter : str, optional
        Filter by platform
    python_version_filter : str, optional
        Filter by Python version
    include_extras : List[str], optional
        Extras to include
    exclude_extras : List[str], optional
        Extras to exclude
    include_markers : List[str], optional
        Marker keywords to include
    exclude_markers : List[str], optional
        Marker keywords to exclude
    current_environment : Dict[str, str], optional
        Custom environment for evaluation
    **kwargs
        Additional keyword arguments
    
    Returns
    -------
    bool
        True if requirement should be included
    
    Examples
    --------
    >>> should_include_requirement(
    ...     version_spec=">=1.0",
    ...     marker="extra == 'dev'",
    ...     skip_optional=True
    ... )
    False
    
    >>> should_include_requirement(
    ...     marker="sys_platform == 'linux'",
    ...     platform_filter='linux'
    ... )
    True
    """
    # Create evaluation context with custom environment
    eval_context = None
    if current_environment:
        eval_context = EvaluationContext(environment=current_environment)
    
    # Create filter
    requirement_filter = RequirementFilter(
        skip_optional=skip_optional,
        skip_development=skip_development,
        platform_filter=platform_filter,
        python_version_filter=python_version_filter,
        include_extras=include_extras,
        exclude_extras=exclude_extras,
        include_markers=include_markers,
        exclude_markers=exclude_markers,
        evaluation_context=eval_context
    )
    
    # Evaluate
    return requirement_filter.should_include(
        version_spec=version_spec,
        marker=marker,
        **kwargs
    )


def filter_packages_by_pattern(packages: List[str], pattern: Optional[str] = None) -> List[str]:
    """
    Filter a list of package names using a regex pattern.
    
    Parameters
    ----------
    packages : List[str]
        List of package names to filter
    pattern : str, optional
        Regular expression pattern for filtering
    
    Returns
    -------
    List[str]
        Filtered list of package names
    
    Examples
    --------
    >>> packages = ['requests', 'django', 'django-rest-framework', 'pandas']
    >>> filter_packages_by_pattern(packages, '^django')
    ['django', 'django-rest-framework']
    
    >>> filter_packages_by_pattern(packages, 'requests|pandas')
    ['requests', 'pandas']
    """
    if not pattern:
        return packages
    
    try:
        regex = re.compile(pattern, re.IGNORECASE)
        return [pkg for pkg in packages if regex.search(pkg)]
    except re.error as e:
        logger.warning(f"Invalid regex pattern '{pattern}': {e}")
        return packages


def create_environment_filter(environment: str = 'production') -> RequirementFilter:
    """
    Create a pre-configured filter for common environments.
    
    Parameters
    ----------
    environment : str, default='production'
        Environment type: 'production', 'development', 'test', 'ci', 'all'
    
    Returns
    -------
    RequirementFilter
        Pre-configured filter for the specified environment
    
    Examples
    --------
    >>> prod_filter = create_environment_filter('production')
    >>> dev_filter = create_environment_filter('development')
    >>> ci_filter = create_environment_filter('ci')
    """
    configs = {
        'production': {
            'skip_development': True,
            'skip_optional': False,
            'description': 'Production environment - excludes dev dependencies'
        },
        'development': {
            'skip_development': False,
            'skip_optional': False,
            'description': 'Development environment - includes all dependencies'
        },
        'test': {
            'skip_development': False,
            'skip_optional': True,
            'include_markers': ['test', 'testing'],
            'description': 'Testing environment - includes test dependencies'
        },
        'ci': {
            'skip_development': False,
            'skip_optional': False,
            'strict_mode': True,
            'description': 'CI environment - strict evaluation'
        },
        'all': {
            'skip_development': False,
            'skip_optional': False,
            'description': 'All dependencies - no filtering'
        }
    }
    
    config = configs.get(environment.lower(), configs['production'])
    filter_kwargs = {k: v for k, v in config.items() if k != 'description'}
    
    logger.info(f"Created {environment} environment filter: {config['description']}")
    return RequirementFilter(**filter_kwargs)


# Module initialization
def _setup_logging():
    """Configure module logging."""
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)


_setup_logging()
logger.debug("Requirement filtering module initialized")