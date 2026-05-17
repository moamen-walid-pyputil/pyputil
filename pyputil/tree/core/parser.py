#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
PEP 508 requirement string parser with enhanced metadata extraction and advanced analysis.

This module provides comprehensive parsing and analysis of Python requirement
strings following PEP 508 specification, with built-in version handling and
fallbacks for external libraries.
"""

import re
from typing import Tuple, Optional, List, Dict, Any, Set, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
from urllib.parse import urlparse
from pathlib import Path
import logging
import sys

# Configure module logger
logger = logging.getLogger(__name__)

# Try to import packaging libraries, but provide fallbacks
try:
    from packaging.version import Version, InvalidVersion
    from packaging.specifiers import SpecifierSet, InvalidSpecifier
    PACKAGING_AVAILABLE = True
except ImportError:
    PACKAGING_AVAILABLE = False
    logger.debug("packaging library not available, using built-in fallbacks")


class RequirementType(Enum):
    """
    Enumeration of requirement types based on PEP 508 classification.
    
    Attributes
    ----------
    STANDARD : str
        Standard requirement with name and optional version
    URL : str
        VCS or direct URL requirement
    LOCAL : str
        Local path requirement (file:// or relative path)
    OPTIONAL : str
        Optional requirement with extra marker
    PLATFORM_SPECIFIC : str
        Requirement with platform constraints
    DEVELOPMENT : str
        Development-only requirement
    EXTRAS : str
        Extra dependency requirement
    INVALID : str
        Invalid or unparseable requirement
    """
    STANDARD = "standard"
    URL = "url"
    LOCAL = "local"
    OPTIONAL = "optional"
    PLATFORM_SPECIFIC = "platform_specific"
    DEVELOPMENT = "development"
    EXTRAS = "extras"
    INVALID = "invalid"


class VersionOperator(Enum):
    """
    Version comparison operators for requirement specifications.
    
    Attributes
    ----------
    EQ : str
        Equal to (==)
    GT : str
        Greater than (>)
    LT : str
        Less than (<)
    GE : str
        Greater than or equal to (>=)
    LE : str
        Less than or equal to (<=)
    NE : str
        Not equal to (!=)
    COMPATIBLE : str
        Compatible release (~=)
    ARBITRARY : str
        Arbitrary equality (===)
    """
    EQ = "=="
    GT = ">"
    LT = "<"
    GE = ">="
    LE = "<="
    NE = "!="
    COMPATIBLE = "~="
    ARBITRARY = "==="


@dataclass
class VersionSpecifier:
    """
    Structured representation of a version specifier.
    
    Attributes
    ----------
    operator : VersionOperator
        Comparison operator
    version : str
        Version string
    specifier : str
        Full specifier string
    specifier_type : str
        Type of specifier (release, prerelease, wildcard, postrelease)
    is_wildcard : bool
        Whether the version contains wildcard (*)
    is_prerelease : bool
        Whether the version is a pre-release
    is_postrelease : bool
        Whether the version is a post-release
    """
    operator: VersionOperator
    version: str
    specifier: str
    specifier_type: str = "release"
    is_wildcard: bool = False
    is_prerelease: bool = False
    is_postrelease: bool = False
    
    def __post_init__(self):
        """Auto-detect specifier properties."""
        if ".*" in self.version:
            self.is_wildcard = True
            self.specifier_type = "wildcard"
        elif any(char in self.version.lower() for char in ['a', 'b', 'rc', 'dev', 'pre']):
            self.is_prerelease = True
            self.specifier_type = "prerelease"
        elif 'post' in self.version.lower() or 'rev' in self.version.lower():
            self.is_postrelease = True
            self.specifier_type = "postrelease"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'operator': self.operator.value,
            'version': self.version,
            'specifier': self.specifier,
            'type': self.specifier_type,
            'is_wildcard': self.is_wildcard,
            'is_prerelease': self.is_prerelease,
            'is_postrelease': self.is_postrelease
        }


@dataclass
class EnvironmentMarker:
    """
    Structured representation of an environment marker.
    
    Attributes
    ----------
    expression : str
        Original marker expression
    variables : List[str]
        Variables used in the marker
    conditions : List[Dict[str, str]]
        Parsed conditions
    marker_type : str
        Type of marker (python_version, platform_system, extra, etc.)
    is_complex : bool
        Whether marker contains multiple conditions
    """
    expression: str
    variables: List[str] = field(default_factory=list)
    conditions: List[Dict[str, str]] = field(default_factory=list)
    marker_type: str = "unknown"
    is_complex: bool = False
    
    def evaluate(self, environment: Optional[Dict[str, Any]] = None) -> Optional[bool]:
        """
        Evaluate the marker against the current or provided environment.
        
        Parameters
        ----------
        environment : Dict[str, Any], optional
            Environment variables to evaluate against. If None, uses current
            Python environment.
        
        Returns
        -------
        Optional[bool]
            Evaluation result, or None if evaluation fails
        """
        if environment is None:
            environment = self._get_current_environment()
        
        try:
            # Simple evaluation for basic markers
            if not self.is_complex and self.conditions:
                result = True
                for condition in self.conditions:
                    var = condition.get('variable', '')
                    op = condition.get('operator', '')
                    val = condition.get('value', '')
                    
                    if var in environment:
                        env_val = environment[var]
                        result &= self._evaluate_condition(env_val, op, val)
                return result
            
            # For complex markers, use safer evaluation
            return self._safe_evaluate(environment)
        except Exception as e:
            logger.debug(f"Marker evaluation failed: {e}")
            return None
    
    def _get_current_environment(self) -> Dict[str, Any]:
        """Get current Python environment information."""
        import platform
        import sys
        
        return {
            'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            'python_full_version': sys.version,
            'platform_system': platform.system(),
            'platform_release': platform.release(),
            'platform_version': platform.version(),
            'platform_machine': platform.machine(),
            'os_name': platform.system().lower(),
            'sys_platform': sys.platform,
            'implementation_name': sys.implementation.name,
            'implementation_version': f"{sys.version_info.major}.{sys.version_info.minor}"
        }
    
    def _evaluate_condition(self, left: Any, operator: str, right: str) -> bool:
        """
        Evaluate a single condition.
        
        Parameters
        ----------
        left : Any
            Left-hand side value
        operator : str
            Comparison operator
        right : str
            Right-hand side value
        
        Returns
        -------
        bool
            Evaluation result
        """
        # Convert right side to appropriate type
        if isinstance(left, (int, float)):
            try:
                right = float(right.strip('"\' '))
            except ValueError:
                right = right.strip('"\' ')
        else:
            right = right.strip('"\' ')
        
        # Perform comparison
        if operator == '==':
            return left == right
        elif operator == '!=':
            return left != right
        elif operator == '>':
            return left > right
        elif operator == '>=':
            return left >= right
        elif operator == '<':
            return left < right
        elif operator == '<=':
            return left <= right
        elif operator == 'in':
            return right in left if isinstance(left, str) else left in right
        elif operator == 'not in':
            return right not in left if isinstance(left, str) else left not in right
        
        return False
    
    def _safe_evaluate(self, environment: Dict[str, Any]) -> bool:
        """
        Safely evaluate complex marker expressions.
        
        Parameters
        ----------
        environment : Dict[str, Any]
            Environment variables
        
        Returns
        -------
        bool
            Evaluation result
        """
        # Replace variables with their values
        expr = self.expression.lower()
        for var, value in environment.items():
            if var in expr:
                if isinstance(value, str):
                    expr = expr.replace(var, f"'{value}'")
                else:
                    expr = expr.replace(var, str(value))
        
        # Safely evaluate using restricted globals
        safe_globals = {
            '__builtins__': {
                'True': True,
                'False': False,
                'and': lambda x, y: x and y,
                'or': lambda x, y: x or y,
                'not': lambda x: not x
            }
        }
        
        try:
            return bool(eval(expr, safe_globals, {}))
        except Exception:
            return False


@dataclass
class ParsedRequirement:
    """
    Complete structured representation of a parsed requirement.
    
    Attributes
    ----------
    package_name : Optional[str]
        Normalized package name
    version_spec : str
        Raw version specification string
    extras : List[str]
        List of extras requested
    marker : str
        Raw environment marker string
    requirement_type : RequirementType
        Type of requirement
    version_specifiers : List[VersionSpecifier]
        Parsed version specifiers
    environment_marker : Optional[EnvironmentMarker]
        Parsed environment marker
    original_string : str
        Original requirement string
    url : Optional[str]
        URL if requirement is a URL type
    local_path : Optional[str]
        Local path if requirement is a local type
    normalized_name : str
        PEP 503 normalized package name
    metadata : Dict[str, Any]
        Additional extracted metadata
    errors : List[str]
        List of parsing errors or warnings
    """
    package_name: Optional[str] = None
    version_spec: str = ""
    extras: List[str] = field(default_factory=list)
    marker: str = ""
    requirement_type: RequirementType = RequirementType.STANDARD
    version_specifiers: List[VersionSpecifier] = field(default_factory=list)
    environment_marker: Optional[EnvironmentMarker] = None
    original_string: str = ""
    url: Optional[str] = None
    local_path: Optional[str] = None
    normalized_name: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            'package_name': self.package_name,
            'normalized_name': self.normalized_name,
            'version_spec': self.version_spec,
            'extras': self.extras,
            'marker': self.marker,
            'requirement_type': self.requirement_type.value,
            'version_specifiers': [v.to_dict() for v in self.version_specifiers],
            'environment_marker': asdict(self.environment_marker) if self.environment_marker else None,
            'original_string': self.original_string,
            'url': self.url,
            'local_path': self.local_path,
            'metadata': self.metadata,
            'errors': self.errors,
            'is_valid': self.is_valid()
        }
        return result
    
    def is_valid(self) -> bool:
        """Check if requirement is valid."""
        return self.package_name is not None and len(self.errors) == 0
    
    def matches_version(self, version_str: str) -> bool:
        """
        Check if a given version matches this requirement.
        
        Parameters
        ----------
        version_str : str
            Version string to check
        
        Returns
        -------
        bool
            True if version matches requirements
        """
        if not self.version_specifiers:
            return True
        
        try:
            # Use packaging if available
            if PACKAGING_AVAILABLE:
                specifier_set = SpecifierSet(self.version_spec)
                return version_str in specifier_set
        except Exception:
            pass
        
        # Fallback to built-in version comparison
        return self._matches_version_fallback(version_str)
    
    def _matches_version_fallback(self, version_str: str) -> bool:
        """
        Fallback version matching without external libraries.
        
        Parameters
        ----------
        version_str : str
            Version string to check
        
        Returns
        -------
        bool
            True if version matches requirements
        """
        for spec in self.version_specifiers:
            if not self._compare_version(version_str, spec):
                return False
        return True
    
    def _compare_version(self, version_str: str, spec: VersionSpecifier) -> bool:
        """
        Compare a version against a specifier.
        
        Parameters
        ----------
        version_str : str
            Version to check
        spec : VersionSpecifier
            Specifier to compare against
        
        Returns
        -------
        bool
            True if version matches specifier
        """
        # Simple version comparison (handles basic cases)
        def normalize(v: str) -> List[int]:
            parts = []
            for part in re.split(r'[.-]', v):
                try:
                    parts.append(int(part))
                except ValueError:
                    parts.append(part)
            return parts
        
        try:
            v1 = normalize(version_str)
            v2 = normalize(spec.version.replace('.*', ''))
            
            op = spec.operator
            
            if op == VersionOperator.EQ:
                return v1 == v2
            elif op == VersionOperator.GT:
                return v1 > v2
            elif op == VersionOperator.LT:
                return v1 < v2
            elif op == VersionOperator.GE:
                return v1 >= v2
            elif op == VersionOperator.LE:
                return v1 <= v2
            elif op == VersionOperator.COMPATIBLE:
                # Compatible release: major version must match
                return v1[0] == v2[0] and v1 >= v2
        except Exception:
            pass
        
        return True
    
    def __str__(self) -> str:
        """Return string representation."""
        return self.original_string or f"{self.package_name}{self.version_spec}"


class PEP508Parser:
    """
    Advanced PEP 508 requirement string parser with comprehensive features.
    
    This parser handles all PEP 508 requirement formats including:
    - Standard requirements (package>=1.0)
    - Extras (package[extra]>=1.0)
    - Environment markers (package; python_version>='3.6')
    - URL requirements (package @ https://...)
    - Local path requirements (package @ ./local/path)
    - VCS requirements (package @ git+https://...)
    
    Attributes
    ----------
    normalize_names : bool
        Whether to normalize package names according to PEP 503
    strict_mode : bool
        Whether to raise errors on strict parsing failures
    cache_results : bool
        Whether to cache parsed requirements
    _cache : Dict[str, ParsedRequirement]
        Cache of parsed requirements
    
    Examples
    --------
    >>> parser = PEP508Parser()
    >>> req = parser.parse("requests[security]>=2.25.0; python_version>'3.6'")
    >>> print(req.package_name)
    'requests'
    >>> print(req.extras)
    ['security']
    >>> print(req.environment_marker.expression)
    "python_version>'3.6'"
    """
    
    # PEP 508 compliant patterns
    NAME_PATTERN = r'[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?'
    EXTRAS_PATTERN = r'\[([^\]]+)\]'
    VERSION_PATTERN = r'([<>=!~]=?)\s*([a-zA-Z0-9.*]+(?:\.[a-zA-Z0-9.*]+)*)'
    MARKER_VAR_PATTERN = r'(python_version|python_full_version|os_name|sys_platform|platform_release|platform_system|platform_version|platform_machine|implementation_name|implementation_version|extra)'
    
    def __init__(self, normalize_names: bool = True, 
                 strict_mode: bool = False, 
                 cache_results: bool = True):
        """
        Initialize the PEP 508 parser.
        
        Parameters
        ----------
        normalize_names : bool, default=True
            Whether to normalize package names according to PEP 503
        strict_mode : bool, default=False
            Whether to raise errors on strict parsing failures
        cache_results : bool, default=True
            Whether to cache parsed requirements for performance
        """
        self.normalize_names = normalize_names
        self.strict_mode = strict_mode
        self.cache_results = cache_results
        self._cache: Dict[str, ParsedRequirement] = {}
        
        # Compile regex patterns for performance
        self._name_regex = re.compile(f'^{self.NAME_PATTERN}$', re.IGNORECASE)
        self._url_regex = re.compile(r'^\s*([^@]+)\s*@\s*(.+)$')
        self._extras_regex = re.compile(self.EXTRAS_PATTERN)
        self._version_regex = re.compile(self.VERSION_PATTERN)
        self._marker_regex = re.compile(r';\s*(.+)$')
    
    def parse(self, req_string: str) -> ParsedRequirement:
        """
        Parse a requirement string into a structured ParsedRequirement object.
        
        Parameters
        ----------
        req_string : str
            Requirement string following PEP 508 specification
            
        Returns
        -------
        ParsedRequirement
            Structured representation of the requirement
            
        Examples
        --------
        >>> parser = PEP508Parser()
        >>> req = parser.parse("django>=3.2")
        >>> req.package_name
        'django'
        
        >>> req = parser.parse("package[extra1,extra2] @ git+https://github.com/user/repo.git")
        >>> req.requirement_type
        <RequirementType.URL: 'url'>
        """
        # Check cache
        if self.cache_results and req_string in self._cache:
            return self._cache[req_string]
        
        # Create result object
        result = ParsedRequirement(original_string=req_string)
        
        try:
            # Clean input
            req_string = req_string.strip()
            
            # Check for URL/local requirement (@ syntax)
            url_match = self._url_regex.match(req_string)
            if url_match:
                self._parse_url_requirement(url_match, result)
            else:
                self._parse_standard_requirement(req_string, result)
            
            # Normalize package name if requested
            if result.package_name:
                result.normalized_name = self.normalize_package_name(result.package_name)
            
            # Determine requirement type based on metadata
            self._determine_requirement_type(result)
            
            # Add additional metadata
            self._add_metadata(result)
            
        except Exception as e:
            error_msg = f"Failed to parse requirement: {str(e)}"
            result.errors.append(error_msg)
            result.requirement_type = RequirementType.INVALID
            logger.error(error_msg)
            
            if self.strict_mode:
                raise ValueError(error_msg) from e
        
        # Cache result
        if self.cache_results:
            self._cache[req_string] = result
        
        return result
    
    def _parse_standard_requirement(self, req_string: str, result: ParsedRequirement) -> None:
        """
        Parse a standard requirement (non-URL).
        
        Parameters
        ----------
        req_string : str
            Requirement string
        result : ParsedRequirement
            Result object to populate
        """
        # Extract environment marker if present
        marker_match = self._marker_regex.search(req_string)
        if marker_match:
            result.marker = marker_match.group(1).strip()
            req_string = req_string[:marker_match.start()].strip()
            result.environment_marker = self._parse_marker(result.marker)
        
        # Extract extras
        extras_match = self._extras_regex.search(req_string)
        if extras_match:
            extras_str = extras_match.group(1)
            result.extras = [e.strip() for e in extras_str.split(',') if e.strip()]
            req_string = req_string[:extras_match.start()] + req_string[extras_match.end():]
        
        # Extract package name
        name_match = re.match(f'^\s*({self.NAME_PATTERN})', req_string, re.IGNORECASE)
        if name_match:
            result.package_name = name_match.group(1)
            req_string = req_string[name_match.end():].strip()
        else:
            result.errors.append("No valid package name found")
            return
        
        # Extract version specifiers
        if req_string:
            result.version_spec = req_string
            result.version_specifiers = self._parse_version_specifiers(req_string)
    
    def _parse_url_requirement(self, match: re.Match, result: ParsedRequirement) -> None:
        """
        Parse a URL-based requirement (@ syntax).
        
        Parameters
        ----------
        match : re.Match
            Regex match object
        result : ParsedRequirement
            Result object to populate
        """
        name_part = match.group(1).strip()
        url_part = match.group(2).strip()
        
        # Extract extras from name part
        extras_match = self._extras_regex.search(name_part)
        if extras_match:
            extras_str = extras_match.group(1)
            result.extras = [e.strip() for e in extras_str.split(',') if e.strip()]
            name_part = name_part[:extras_match.start()].strip()
        
        # Extract package name
        name_match = re.match(f'^\s*({self.NAME_PATTERN})$', name_part, re.IGNORECASE)
        if name_match:
            result.package_name = name_match.group(1)
        else:
            result.errors.append("Invalid package name in URL requirement")
        
        # Parse URL
        result.url = url_part
        if url_part.startswith(('git+', 'hg+', 'svn+', 'bzr+')):
            result.requirement_type = RequirementType.URL
            self._parse_vcs_url(url_part, result)
        elif url_part.startswith('file://') or url_part.startswith('./') or url_part.startswith('../'):
            result.requirement_type = RequirementType.LOCAL
            result.local_path = self._parse_local_path(url_part)
        elif urlparse(url_part).scheme in ('http', 'https', 'ftp'):
            result.requirement_type = RequirementType.URL
    
    def _parse_vcs_url(self, url: str, result: ParsedRequirement) -> None:
        """
        Parse VCS URL and extract metadata.
        
        Parameters
        ----------
        url : str
            VCS URL
        result : ParsedRequirement
            Result object to populate
        """
        vcs_patterns = {
            'git+': r'git\+(?:https?://|ssh://|git://)([^@]+)(?:@([^#]+))?(?:#(?:.*))?',
            'hg+': r'hg\+(?:https?://|ssh://)([^@]+)(?:@([^#]+))?',
            'svn+': r'svn\+(?:https?://|svn://)([^@]+)(?:@([^#]+))?',
            'bzr+': r'bzr\+(?:https?://|bzr://)([^@]+)(?:@([^#]+))?'
        }
        
        for vcs, pattern in vcs_patterns.items():
            if url.startswith(vcs):
                result.metadata['vcs_type'] = vcs[:-1]  # Remove trailing '+'
                vcs_match = re.match(pattern, url)
                if vcs_match:
                    result.metadata['repository'] = vcs_match.group(1)
                    if vcs_match.group(2):
                        result.metadata['revision'] = vcs_match.group(2)
                break
    
    def _parse_local_path(self, path: str) -> str:
        """
        Parse local path requirement.
        
        Parameters
        ----------
        path : str
            Path string
        
        Returns
        -------
        str
            Normalized local path
        """
        if path.startswith('file://'):
            path = path[7:]
        
        # Resolve relative paths
        path_obj = Path(path)
        if not path_obj.is_absolute():
            path_obj = Path.cwd() / path_obj
        
        return str(path_obj.resolve())
    
    def _parse_version_specifiers(self, version_spec: str) -> List[VersionSpecifier]:
        """
        Parse version specifiers into structured format.
        
        Parameters
        ----------
        version_spec : str
            Version specification string
            
        Returns
        -------
        List[VersionSpecifier]
            List of parsed version specifiers
        """
        specifiers = []
        
        for match in self._version_regex.finditer(version_spec):
            operator_str = match.group(1)
            version_str = match.group(2)
            
            # Map operator string to enum
            operator_map = {
                '==': VersionOperator.EQ,
                '===': VersionOperator.ARBITRARY,
                '>': VersionOperator.GT,
                '<': VersionOperator.LT,
                '>=': VersionOperator.GE,
                '<=': VersionOperator.LE,
                '!=': VersionOperator.NE,
                '~=': VersionOperator.COMPATIBLE
            }
            
            operator = operator_map.get(operator_str, VersionOperator.EQ)
            
            specifier = VersionSpecifier(
                operator=operator,
                version=version_str,
                specifier=f"{operator_str}{version_str}"
            )
            
            specifiers.append(specifier)
        
        return specifiers
    
    def _parse_marker(self, marker_str: str) -> EnvironmentMarker:
        """
        Parse environment marker expression.
        
        Parameters
        ----------
        marker_str : str
            Marker expression string
            
        Returns
        -------
        EnvironmentMarker
            Structured marker representation
        """
        marker = EnvironmentMarker(expression=marker_str)
        
        # Extract variables used in marker
        marker.variables = list(set(re.findall(self.MARKER_VAR_PATTERN, marker_str, re.IGNORECASE)))
        
        # Parse simple conditions
        condition_pattern = r'({})\s*(==|!=|<=|>=|<|>|in|not in)\s*([\'"][^\'"]+[\'"]|[^\s;]+)'
        
        for match in re.finditer(condition_pattern, marker_str, re.IGNORECASE):
            condition = {
                'variable': match.group(1),
                'operator': match.group(2),
                'value': match.group(3).strip('\'"')
            }
            marker.conditions.append(condition)
        
        # Determine marker type
        marker_lower = marker_str.lower()
        if 'extra' in marker_lower:
            marker.marker_type = 'extra'
        elif any(var in marker_lower for var in ['python_version', 'python_full_version']):
            marker.marker_type = 'python'
        elif any(var in marker_lower for var in ['platform_', 'os_name', 'sys_platform']):
            marker.marker_type = 'platform'
        else:
            marker.marker_type = 'environment'
        
        marker.is_complex = len(marker.conditions) > 1 or 'and' in marker_lower or 'or' in marker_lower
        
        return marker
    
    def _determine_requirement_type(self, result: ParsedRequirement) -> None:
        """
        Determine requirement type based on parsed components.
        
        Parameters
        ----------
        result : ParsedRequirement
            Parsed requirement object
        """
        if result.requirement_type != RequirementType.STANDARD:
            return  # Type already set (URL or local)
        
        if result.marker:
            marker_lower = result.marker.lower()
            if 'extra' in marker_lower:
                result.requirement_type = RequirementType.OPTIONAL
            elif any(keyword in marker_lower for keyword in ['dev', 'test', 'docs', 'doc']):
                result.requirement_type = RequirementType.DEVELOPMENT
            elif any(keyword in marker_lower for keyword in ['platform', 'sys_platform', 'os_name', 'implementation']):
                result.requirement_type = RequirementType.PLATFORM_SPECIFIC
        
        if result.extras:
            result.requirement_type = RequirementType.EXTRAS
    
    def _add_metadata(self, result: ParsedRequirement) -> None:
        """
        Add additional metadata to parsed requirement.
        
        Parameters
        ----------
        result : ParsedRequirement
            Parsed requirement object
        """
        result.metadata.update({
            'has_extras': len(result.extras) > 0,
            'has_marker': bool(result.marker),
            'has_version_spec': bool(result.version_spec),
            'is_url_requirement': result.url is not None,
            'is_local_requirement': result.local_path is not None,
            'specifier_count': len(result.version_specifiers),
            'parsed_at': __import__('time').time()
        })
        
        # Add version constraint details if available
        if result.version_specifiers:
            result.metadata['version_constraints'] = [
                f"{s.operator.value}{s.version}" 
                for s in result.version_specifiers
            ]
    
    def normalize_package_name(self, name: str) -> str:
        """
        Normalize a package name according to PEP 503.
        
        Parameters
        ----------
        name : str
            Package name to normalize
            
        Returns
        -------
        str
            Normalized package name (lowercase with underscores replaced by hyphens)
        
        Examples
        --------
        >>> parser = PEP508Parser()
        >>> parser.normalize_package_name("Django_Package")
        'django-package'
        """
        return name.lower().replace('_', '-')
    
    def validate_package_name(self, name: str) -> bool:
        """
        Validate if a string is a valid package name according to PEP 508.
        
        Parameters
        ----------
        name : str
            Package name to validate
        
        Returns
        -------
        bool
            True if valid, False otherwise
        """
        return bool(self._name_regex.match(name))
    
    def extract_requirements(self, text: str) -> List[ParsedRequirement]:
        """
        Extract all requirement strings from text.
        
        Parameters
        ----------
        text : str
            Text containing requirement strings (e.g., from requirements.txt)
        
        Returns
        -------
        List[ParsedRequirement]
            List of parsed requirements found in text
        """
        requirements = []
        
        # Split by lines and handle line continuations
        lines = text.replace('\\\n', ' ').split('\n')
        
        for line in lines:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            
            # Parse requirement
            req = self.parse(line)
            if req.is_valid():
                requirements.append(req)
            elif not self.strict_mode:
                # In non-strict mode, still try to add with errors
                requirements.append(req)
        
        return requirements
    
    def clear_cache(self) -> None:
        """Clear the parsing cache."""
        self._cache.clear()
        logger.debug("Cache cleared")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns
        -------
        Dict[str, Any]
            Cache statistics
        """
        return {
            'cache_size': len(self._cache),
            'cache_enabled': self.cache_results,
            'cache_keys': list(self._cache.keys()) if self.cache_results else []
        }


# Convenience functions for backward compatibility
_default_parser = PEP508Parser()


def parse_requirement(req: str) -> Tuple[Optional[str], str, List[str], str]:
    """
    Parse a PEP 508 requirement string into basic components.
    
    This is a simplified wrapper around PEP508Parser for backward compatibility.
    
    Parameters
    ----------
    req : str
        Requirement string following PEP 508 specification
        
    Returns
    -------
    tuple
        A tuple containing (package_name, version_spec, extras, marker)
        
    Examples
    --------
    >>> parse_requirement("requests[security]>=2.8.1; python_version>'3.5'")
    ('requests', '>=2.8.1', ['security'], "python_version>'3.5'")
    """
    parsed = _default_parser.parse(req)
    return (parsed.package_name, parsed.version_spec, parsed.extras, parsed.marker)


def parse_requirement_enhanced(req: str) -> Tuple[Optional[str], str, List[str], str, Dict[str, Any]]:
    """
    Enhanced version of parse_requirement that extracts more metadata.
    
    Parameters
    ----------
    req : str
        Requirement string following PEP 508 specification
        
    Returns
    -------
    tuple
        A tuple containing (package_name, version_spec, extras, marker, metadata)
        
    Examples
    --------
    >>> name, spec, extras, marker, meta = parse_requirement_enhanced(
    ...     "requests[security]>=2.8.1; python_version>'3.5'"
    ... )
    >>> meta['has_marker']
    True
    >>> meta['requirement_type']
    'platform_specific'
    """
    parsed = _default_parser.parse(req)
    
    metadata = {
        "original_requirement": req,
        "has_extras": len(parsed.extras) > 0,
        "has_marker": bool(parsed.marker),
        "has_version_spec": bool(parsed.version_spec),
        "requirement_type": parsed.requirement_type.value,
        "version_specifiers": [v.to_dict() for v in parsed.version_specifiers],
        "normalized_name": parsed.normalized_name,
        "is_valid": parsed.is_valid(),
        "errors": parsed.errors
    }
    
    if parsed.environment_marker:
        metadata["marker_variables"] = parsed.environment_marker.variables
        metadata["marker_type"] = parsed.environment_marker.marker_type
    
    return (parsed.package_name, parsed.version_spec, parsed.extras, parsed.marker, metadata)


def parse_version_specifiers(version_spec: str) -> List[Dict[str, str]]:
    """
    Parse version specifiers into structured format.
    
    Parameters
    ----------
    version_spec : str
        Version specification string (e.g., ">=1.0,<2.0")
        
    Returns
    -------
    List[Dict[str, str]]
        List of parsed version specifiers
        
    Examples
    --------
    >>> parse_version_specifiers(">=1.0.0,<2.0.0")
    [
        {'operator': '>=', 'version': '1.0.0', 'specifier': '>=1.0.0', 'type': 'release'},
        {'operator': '<', 'version': '2.0.0', 'specifier': '<2.0.0', 'type': 'release'}
    ]
    """
    specifiers = _default_parser._parse_version_specifiers(version_spec)
    return [s.to_dict() for s in specifiers]


def normalize_package_name(name: str) -> str:
    """
    Normalize a package name according to PEP 503.
    
    Parameters
    ----------
    name : str
        Package name to normalize
        
    Returns
    -------
    str
        Normalized package name (lowercase with underscores replaced by hyphens)
        
    Examples
    --------
    >>> normalize_package_name("Django_Package")
    'django-package'
    """
    return _default_parser.normalize_package_name(name)


def validate_package_name(name: str) -> bool:
    """
    Validate if a string is a valid package name according to PEP 508.
    
    Parameters
    ----------
    name : str
        Package name to validate
        
    Returns
    -------
    bool
        True if valid, False otherwise
        
    Examples
    --------
    >>> validate_package_name("valid-package")
    True
    >>> validate_package_name("invalid@package")
    False
    """
    return _default_parser.validate_package_name(name)


def extract_requirements_from_file(filepath: str) -> List[ParsedRequirement]:
    """
    Extract all requirements from a requirements.txt file.
    
    Parameters
    ----------
    filepath : str
        Path to requirements.txt file
        
    Returns
    -------
    List[ParsedRequirement]
        List of parsed requirements
        
    Examples
    --------
    >>> requirements = extract_requirements_from_file("requirements.txt")
    >>> for req in requirements:
    ...     print(f"{req.package_name}=={req.version_spec}")
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    return _default_parser.extract_requirements(content)


# Module-level logger configuration
def _setup_logging():
    """Configure module logger if not already configured."""
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)


_setup_logging()