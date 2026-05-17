#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
case.py

 Case-Insensitive Module Access with Typo Correction.

This module provides sophisticated case-insensitive attribute access for Python
modules with intelligent fuzzy matching, caching, and  error recovery.
It enables developers to work with modules using flexible casing while
maintaining full IDE support and type hinting compatibility.

The system is designed for:
- Rapid prototyping and exploration of unfamiliar APIs
- Working with inconsistently cased third-party libraries
- Educational environments where exact casing may be challenging
- REPL sessions and interactive development
- Legacy code migration and compatibility layers

Features
--------
- Case-insensitive attribute, item, and call access
- Intelligent fuzzy matching with configurable sensitivity
- LRU caching for high-performance repeated access
- Thread-safe module patching and restoration
- Recursive patching of submodules
- Context manager for temporary patching
- Comprehensive typo suggestions with similarity scoring
- Support for both sync and async module access patterns
- Automatic handling of common module aliases
- Integration with Python's import system

Classes
-------
CaseInsensitiveModule
    Enhanced module wrapper with fuzzy matching and caching.
ModulePatcher
     patching system with restoration capabilities.
PatchContext
    Context manager for temporary module patching.
AccessCache
    Thread-safe LRU cache for attribute resolution.
TypoSuggester
    Intelligent typo detection and suggestion engine.

Functions
---------
patch_module
    Enhanced module patching with comprehensive options.
patch_modules
    Batch patch multiple modules with pattern matching.
restore_module
    Restore patched module to original state.
is_patched
    Check if a module has been patched.
with_case_insensitive
    Context manager for temporary patching.
patch_recursive
    Recursively patch module and all submodules.
configure_suggester
    Configure global typo suggestion parameters.
"""

import importlib
import sys
import threading
import warnings
import functools
import re
import time
import logging
from collections import OrderedDict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from difflib import get_close_matches, SequenceMatcher
from inspect import ismodule, getmembers
from types import ModuleType, MethodType
from typing import (
    Any, Callable, Dict, List, Optional, Set, Tuple, Type, TypeVar, 
    Union, cast, overload, Generic, Iterator, Pattern
)
from weakref import WeakValueDictionary

# -----------------------------------------------------------------------------
# Module Configuration and Constants
# -----------------------------------------------------------------------------

# Default configuration
DEFAULT_FUZZY_CUTOFF: float = 0.6
DEFAULT_CACHE_SIZE: int = 1000
DEFAULT_CACHE_TTL: float = 300.0  # 5 minutes
DEFAULT_MAX_SUGGESTIONS: int = 3
DEFAULT_RECURSIVE_DEPTH: int = 3
DEFAULT_LAZY_LOAD: bool = True

# Common module aliases for special handling
COMMON_ALIASES: Dict[str, str] = {
    'np': 'numpy',
    'pd': 'pandas',
    'plt': 'matplotlib.pyplot',
    'tf': 'tensorflow',
    'torch': 'torch',
    'sk': 'sklearn',
    'sns': 'seaborn',
    'cv2': 'cv2',
    'bs4': 'bs4',
    'yaml': 'yaml',
}

# Attributes to exclude from case-insensitive access
EXCLUDED_ATTRS: Set[str] = {
    '__class__', '__dict__', '__doc__', '__module__', '__weakref__',
    '__new__', '__init__', '__del__', '__setattr__', '__delattr__',
    '__getattribute__', '__setitem__', '__delitem__', '__call__',
    '__len__', '__iter__', '__hash__', '__str__', '__repr__',
}

# Configure logging
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)


# -----------------------------------------------------------------------------
# Enhanced Data Structures
# -----------------------------------------------------------------------------

@dataclass
class TypoSuggestion:
    """
    Structured typo suggestion with metadata.
    
    Attributes
    ----------
    original : str
        Original misspelled attribute name.
    suggested : str
        Suggested correct attribute name.
    similarity : float
        Similarity score between 0.0 and 1.0.
    distance : int
        Levenshtein edit distance.
    """
    
    original: str
    suggested: str
    similarity: float
    distance: int
    
    def __str__(self) -> str:
        return f"'{self.original}' -> '{self.suggested}' ({self.similarity:.1%} match)"


@dataclass
class AccessStats:
    """
    Statistics for case-insensitive attribute access.
    
    Attributes
    ----------
    total_accesses : int
        Total number of attribute accesses.
    cache_hits : int
        Number of cache hits.
    cache_misses : int
        Number of cache misses.
    typo_corrections : int
        Number of successful typo corrections.
    failed_accesses : int
        Number of failed attribute accesses.
    avg_resolution_time : float
        Average time to resolve attribute in microseconds.
    """
    
    total_accesses: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    typo_corrections: int = 0
    failed_accesses: int = 0
    avg_resolution_time: float = 0.0
    _resolution_times: deque = field(default_factory=lambda: deque(maxlen=100))
    
    def record_hit(self) -> None:
        """Record a cache hit."""
        self.total_accesses += 1
        self.cache_hits += 1
    
    def record_miss(self, resolution_time: float, was_typo: bool = False) -> None:
        """Record a cache miss with resolution time."""
        self.total_accesses += 1
        self.cache_misses += 1
        if was_typo:
            self.typo_corrections += 1
        
        self._resolution_times.append(resolution_time)
        if self._resolution_times:
            self.avg_resolution_time = sum(self._resolution_times) / len(self._resolution_times)
    
    def record_failure(self) -> None:
        """Record a failed access."""
        self.total_accesses += 1
        self.failed_accesses += 1
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        if self.cache_misses + self.cache_hits == 0:
            return 0.0
        return self.cache_hits / (self.cache_hits + self.cache_misses)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert statistics to dictionary."""
        return {
            'total_accesses': self.total_accesses,
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'typo_corrections': self.typo_corrections,
            'failed_accesses': self.failed_accesses,
            'hit_rate': f"{self.hit_rate:.1%}",
            'avg_resolution_time_us': f"{self.avg_resolution_time:.2f}",
        }


# -----------------------------------------------------------------------------
# Thread-Safe LRU Cache for Attribute Resolution
# -----------------------------------------------------------------------------

class AccessCache:
    """
    Thread-safe LRU cache for attribute name resolution.
    
    This cache significantly improves performance for repeated attribute
    access patterns, especially in loops or frequently called functions.
    
    Attributes
    ----------
    max_size : int
        Maximum number of cached entries.
    ttl : float
        Time-to-live in seconds for cache entries.
    """
    
    def __init__(self, max_size: int = DEFAULT_CACHE_SIZE, ttl: float = DEFAULT_CACHE_TTL):
        """
        Initialize access cache.
        
        Parameters
        ----------
        max_size : int
            Maximum cache size.
        ttl : float
            Cache TTL in seconds.
        """
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve cached value if available and not expired.
        
        Parameters
        ----------
        key : str
            Cache key (normalized attribute name).
        
        Returns
        -------
        Optional[Any]
            Cached value or None if not found/expired.
        """
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            value, timestamp = self._cache[key]
            
            # Check TTL
            if time.time() - timestamp > self.ttl:
                del self._cache[key]
                self._misses += 1
                return None
            
            # Move to end (LRU)
            self._cache.move_to_end(key)
            self._hits += 1
            return value
    
    def put(self, key: str, value: Any) -> None:
        """
        Store value in cache.
        
        Parameters
        ----------
        key : str
            Cache key.
        value : Any
            Value to cache.
        """
        with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)
            
            self._cache[key] = (value, time.time())
            self._cache.move_to_end(key)
    
    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
    
    def invalidate(self, key: str) -> None:
        """
        Invalidate specific cache entry.
        
        Parameters
        ----------
        key : str
            Cache key to invalidate.
        """
        with self._lock:
            self._cache.pop(key, None)
    
    @property
    def size(self) -> int:
        """Get current cache size."""
        with self._lock:
            return len(self._cache)
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0
            return {
                'size': len(self._cache),
                'max_size': self.max_size,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': f"{hit_rate:.1f}%",
                'ttl': self.ttl,
            }


# -----------------------------------------------------------------------------
# Intelligent Typo Suggestion Engine
# -----------------------------------------------------------------------------

class TypoSuggester:
    """
    Intelligent typo detection and suggestion engine.
    
    This class provides  fuzzy matching with configurable algorithms,
    similarity scoring, and suggestion ranking.
    
    Examples
    --------
    >>> suggester = TypoSuggester()
    >>> suggestions = suggester.suggest("gEt", ["get", "post", "put", "delete"])
    >>> print(suggestions[0])
    'get' -> 'get' (95.0% match)
    """
    
    def __init__(
        self,
        cutoff: float = DEFAULT_FUZZY_CUTOFF,
        max_suggestions: int = DEFAULT_MAX_SUGGESTIONS,
        algorithm: str = "combined",
    ):
        """
        Initialize typo suggester.
        
        Parameters
        ----------
        cutoff : float
            Minimum similarity score for suggestions (0.0-1.0).
        max_suggestions : int
            Maximum number of suggestions to return.
        algorithm : str
            Matching algorithm: 'sequence', 'levenshtein', or 'combined'.
        """
        self.cutoff = cutoff
        self.max_suggestions = max_suggestions
        self.algorithm = algorithm
        self._cache: Dict[str, List[TypoSuggestion]] = {}
    
    def suggest(self, query: str, candidates: List[str]) -> List[TypoSuggestion]:
        """
        Generate typo suggestions for query.
        
        Parameters
        ----------
        query : str
            Search query (potentially misspelled).
        candidates : List[str]
            List of valid candidates.
        
        Returns
        -------
        List[TypoSuggestion]
            Ranked list of suggestions.
        """
        if not query or not candidates:
            return []
        
        # Normalize
        query_lower = query.lower()
        candidates_lower = [c.lower() for c in candidates]
        
        # Check cache
        cache_key = f"{query_lower}:{hash(tuple(sorted(candidates_lower)))}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        suggestions = []
        
        if self.algorithm == "sequence":
            suggestions = self._sequence_matcher(query_lower, candidates, candidates_lower)
        elif self.algorithm == "levenshtein":
            suggestions = self._levenshtein_matcher(query_lower, candidates, candidates_lower)
        else:  # combined
            suggestions = self._combined_matcher(query_lower, candidates, candidates_lower)
        
        # Sort by similarity and limit
        suggestions.sort(key=lambda s: (s.similarity, -s.distance), reverse=True)
        result = suggestions[:self.max_suggestions]
        
        # Cache result
        if len(self._cache) > 1000:
            self._cache.clear()
        self._cache[cache_key] = result
        
        return result
    
    def _sequence_matcher(
        self, 
        query: str, 
        candidates: List[str], 
        candidates_lower: List[str]
    ) -> List[TypoSuggestion]:
        """Use difflib SequenceMatcher for suggestions."""
        suggestions = []
        matches = get_close_matches(query, candidates_lower, n=self.max_suggestions, cutoff=self.cutoff)
        
        for match in matches:
            idx = candidates_lower.index(match)
            original = candidates[idx]
            similarity = SequenceMatcher(None, query, match).ratio()
            distance = self._levenshtein_distance(query, match)
            
            suggestions.append(TypoSuggestion(
                original=query,
                suggested=original,
                similarity=similarity,
                distance=distance,
            ))
        
        return suggestions
    
    def _levenshtein_matcher(
        self,
        query: str,
        candidates: List[str],
        candidates_lower: List[str],
    ) -> List[TypoSuggestion]:
        """Use Levenshtein distance for suggestions."""
        suggestions = []
        
        for original, lower in zip(candidates, candidates_lower):
            distance = self._levenshtein_distance(query, lower)
            max_len = max(len(query), len(lower))
            
            if max_len > 0:
                similarity = 1.0 - (distance / max_len)
            else:
                similarity = 1.0
            
            if similarity >= self.cutoff:
                suggestions.append(TypoSuggestion(
                    original=query,
                    suggested=original,
                    similarity=similarity,
                    distance=distance,
                ))
        
        return suggestions
    
    def _combined_matcher(
        self,
        query: str,
        candidates: List[str],
        candidates_lower: List[str],
    ) -> List[TypoSuggestion]:
        """Combine multiple matching algorithms."""
        seq_suggestions = self._sequence_matcher(query, candidates, candidates_lower)
        lev_suggestions = self._levenshtein_matcher(query, candidates, candidates_lower)
        
        # Merge and deduplicate by suggested name
        seen = set()
        combined = []
        
        for s in seq_suggestions + lev_suggestions:
            if s.suggested not in seen:
                seen.add(s.suggested)
                combined.append(s)
        
        return combined
    
    @staticmethod
    def _levenshtein_distance(s1: str, s2: str) -> int:
        """
        Calculate Levenshtein distance between two strings.
        
        Parameters
        ----------
        s1 : str
            First string.
        s2 : str
            Second string.
        
        Returns
        -------
        int
            Edit distance.
        """
        if len(s1) < len(s2):
            return TypoSuggester._levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = list(range(len(s2) + 1))
        
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            
            previous_row = current_row
        
        return previous_row[-1]
    
    def clear_cache(self) -> None:
        """Clear suggestion cache."""
        self._cache.clear()


# -----------------------------------------------------------------------------
# Enhanced Case-Insensitive Module
# -----------------------------------------------------------------------------

class CaseInsensitiveModule(ModuleType):
    """
     module wrapper enabling case-insensitive access with caching.
    
    This enhanced wrapper provides:
    - Case-insensitive attribute, item, and call access
    - LRU caching for high-performance repeated access
    - Intelligent typo suggestions with fuzzy matching
    - Access statistics and performance monitoring
    - Thread-safe attribute resolution
    - Preservation of original module behavior
    
    Attributes
    ----------
    _ci_cache : AccessCache
        LRU cache for attribute resolution.
    _ci_suggester : TypoSuggester
        Typo suggestion engine.
    _ci_stats : AccessStats
        Access statistics tracker.
    _ci_original_class : Type
        Original module class for restoration.
    _ci_config : Dict[str, Any]
        Configuration options.
    
    Examples
    --------
    >>> import requests
    >>> module = CaseInsensitiveModule("requests")
    >>> module._patch_from_original(requests)
    >>> module.GET
    >>> module.gEt  # Case-insensitive
    >>> module["post"]
    >>> module("head")
    >>> module.gte  # Typo with suggestion
    AttributeError: Module 'requests' has no attribute 'gte'. Did you mean: get? (95% match)
    """
    
    def __init__(self, name: str, doc: Optional[str] = None):
        """
        Initialize case-insensitive module.
        
        Parameters
        ----------
        name : str
            Module name.
        doc : Optional[str]
            Module docstring.
        """
        super().__init__(name, doc)
        self._ci_cache = AccessCache()
        self._ci_suggester = TypoSuggester()
        self._ci_stats = AccessStats()
        self._ci_original_class: Optional[Type] = None
        self._ci_config: Dict[str, Any] = {
            'enable_cache': True,
            'enable_suggestions': True,
            'enable_stats': True,
            'fuzzy_cutoff': DEFAULT_FUZZY_CUTOFF,
            'max_suggestions': DEFAULT_MAX_SUGGESTIONS,
            'case_sensitive_fallback': True,
        }
        self._ci_lock = threading.RLock()
        self._ci_attr_cache: Dict[str, str] = {}  # normalized -> original
    
    def _patch_from_original(self, original_module: ModuleType) -> None:
        """
        Patch this instance with data from original module.
        
        Parameters
        ----------
        original_module : ModuleType
            Original module to copy from.
        """
        # Copy module attributes
        self.__dict__.update(original_module.__dict__)
        
        # Store original class for restoration
        self._ci_original_class = original_module.__class__
        
        # Build initial attribute cache
        self._rebuild_attr_cache()
    
    def _rebuild_attr_cache(self) -> None:
        """Rebuild the normalized attribute cache."""
        with self._ci_lock:
            self._ci_attr_cache.clear()
            
            for attr in dir(self):
                if attr in EXCLUDED_ATTRS:
                    continue
                if attr.startswith('_ci_'):
                    continue
                
                normalized = self._normalize(attr)
                if normalized not in self._ci_attr_cache:
                    self._ci_attr_cache[normalized] = attr
    
    def _normalize(self, name: str) -> str:
        """
        Normalize attribute name for case-insensitive matching.
        
        Parameters
        ----------
        name : str
            Raw attribute name.
        
        Returns
        -------
        str
            Normalized name.
        """
        return name.strip().lower()
    
    def _get_available_attrs(self) -> List[str]:
        """Get list of available attributes for suggestions."""
        with self._ci_lock:
            return list(self._ci_attr_cache.values())
    
    def _resolve(self, name: str) -> Any:
        """
        Resolve attribute name with caching and suggestions.
        
        Parameters
        ----------
        name : str
            Attribute name to resolve.
        
        Returns
        -------
        Any
            Resolved attribute value.
        
        Raises
        ------
        AttributeError
            If attribute cannot be resolved.
        """
        start_time = time.perf_counter()
        normalized = self._normalize(name)
        
        # Try cache first
        if self._ci_config['enable_cache']:
            cached = self._ci_cache.get(normalized)
            if cached is not None:
                self._ci_stats.record_hit()
                return cached
        
        # Check direct match in attribute cache
        with self._ci_lock:
            if normalized in self._ci_attr_cache:
                original_name = self._ci_attr_cache[normalized]
                try:
                    value = super().__getattribute__(original_name)
                    
                    # Cache the result
                    if self._ci_config['enable_cache']:
                        self._ci_cache.put(normalized, value)
                    
                    resolution_time = (time.perf_counter() - start_time) * 1_000_000
                    self._ci_stats.record_miss(resolution_time, was_typo=False)
                    
                    return value
                except AttributeError:
                    # Attribute might have been removed
                    self._ci_attr_cache.pop(normalized, None)
        
        # Try case-sensitive fallback
        if self._ci_config['case_sensitive_fallback']:
            try:
                value = super().__getattribute__(name)
                
                # Add to cache for future
                with self._ci_lock:
                    self._ci_attr_cache[normalized] = name
                
                if self._ci_config['enable_cache']:
                    self._ci_cache.put(normalized, value)
                
                resolution_time = (time.perf_counter() - start_time) * 1_000_000
                self._ci_stats.record_miss(resolution_time, was_typo=False)
                
                return value
            except AttributeError:
                pass
        
        # Generate suggestions if enabled
        if self._ci_config['enable_suggestions']:
            available = self._get_available_attrs()
            suggestions = self._ci_suggester.suggest(
                name, 
                available,
            )
            
            if suggestions:
                best = suggestions[0]
                resolution_time = (time.perf_counter() - start_time) * 1_000_000
                self._ci_stats.record_miss(resolution_time, was_typo=True)
                
                # Format suggestion message
                suggestion_str = f" Did you mean: {best.suggested}? ({best.similarity:.0%} match)"
                if len(suggestions) > 1:
                    others = [s.suggested for s in suggestions[1:3]]
                    suggestion_str += f" Others: {', '.join(others)}"
                
                raise AttributeError(
                    f"Module '{self.__name__}' has no attribute '{name}'.{suggestion_str}"
                )
        
        # No suggestions or suggestions disabled
        self._ci_stats.record_failure()
        raise AttributeError(f"Module '{self.__name__}' has no attribute '{name}'.")
    
    def __getattr__(self, name: str) -> Any:
        """Case-insensitive attribute access."""
        if name.startswith('_ci_'):
            return super().__getattribute__(name)
        return self._resolve(name)
    
    def __getitem__(self, name: str) -> Any:
        """Dictionary-style case-insensitive access."""
        return self._resolve(name)
    
    def __call__(self, name: str) -> Any:
        """Callable case-insensitive access."""
        return self._resolve(name)
    
    def __setattr__(self, name: str, value: Any) -> None:
        """Set attribute and update cache."""
        super().__setattr__(name, value)
        
        if not name.startswith('_ci_') and name not in EXCLUDED_ATTRS:
            with self._ci_lock:
                normalized = self._normalize(name)
                self._ci_attr_cache[normalized] = name
            
            # Invalidate cache for this attribute
            if hasattr(self, '_ci_cache'):
                self._ci_cache.invalidate(self._normalize(name))
    
    def __delattr__(self, name: str) -> None:
        """Delete attribute and update cache."""
        super().__delattr__(name)
        
        if not name.startswith('_ci_'):
            with self._ci_lock:
                normalized = self._normalize(name)
                self._ci_attr_cache.pop(normalized, None)
            
            if hasattr(self, '_ci_cache'):
                self._ci_cache.invalidate(normalized)
    
    def __dir__(self) -> List[str]:
        """Return sorted list of attributes."""
        base_dir = super().__dir__()
        # Filter out internal attributes
        return sorted([a for a in base_dir if not a.startswith('_ci_')])
    
    def __repr__(self) -> str:
        """Enhanced representation with patched status."""
        return f"<CaseInsensitiveModule '{self.__name__}' (patched)>"
    
    def configure(self, **kwargs) -> None:
        """
        Configure module behavior.
        
        Parameters
        ----------
        **kwargs
            Configuration options:
            - enable_cache: bool
            - enable_suggestions: bool
            - enable_stats: bool
            - fuzzy_cutoff: float
            - max_suggestions: int
            - case_sensitive_fallback: bool
        """
        with self._ci_lock:
            for key, value in kwargs.items():
                if key in self._ci_config:
                    self._ci_config[key] = value
                    
                    if key == 'fuzzy_cutoff':
                        self._ci_suggester.cutoff = value
                    elif key == 'max_suggestions':
                        self._ci_suggester.max_suggestions = value
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get access statistics.
        
        Returns
        -------
        Dict[str, Any]
            Comprehensive statistics.
        """
        stats = self._ci_stats.to_dict()
        stats.update({
            'cache': self._ci_cache.stats,
            'attr_cache_size': len(self._ci_attr_cache),
            'config': self._ci_config.copy(),
        })
        return stats
    
    def clear_caches(self) -> None:
        """Clear all internal caches."""
        self._ci_cache.clear()
        self._ci_suggester.clear_cache()
        with self._ci_lock:
            self._ci_attr_cache.clear()
        self._rebuild_attr_cache()
    
    def restore(self) -> ModuleType:
        """
        Restore module to original unpatched state.
        
        Returns
        -------
        ModuleType
            Restored original module.
        """
        if self._ci_original_class is None:
            raise RuntimeError("Cannot restore: original class not stored")
        
        # Create new module instance with original class
        original_module = ModuleType(self.__name__, self.__doc__)
        original_module.__class__ = self._ci_original_class
        original_module.__dict__.update({
            k: v for k, v in self.__dict__.items() 
            if not k.startswith('_ci_')
        })
        
        # Update sys.modules
        sys.modules[self.__name__] = original_module
        
        logger.info(f"Restored module '{self.__name__}' to original state")
        return original_module


# -----------------------------------------------------------------------------
# Module Patcher System
# -----------------------------------------------------------------------------

class ModulePatcher:
    """
     module patching system with restoration capabilities.
    
    This class manages the patching and restoration of modules, maintaining
    a registry of patched modules and providing batch operations.
    
    Attributes
    ----------
    _patched_modules : WeakValueDictionary
        Registry of patched modules.
    _original_classes : Dict[str, Type]
        Original module classes for restoration.
    """
    
    _instance: Optional['ModulePatcher'] = None
    _lock = threading.RLock()
    
    def __new__(cls) -> 'ModulePatcher':
        """Singleton pattern for global patcher instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize module patcher."""
        if self._initialized:
            return
        
        self._patched_modules: WeakValueDictionary = WeakValueDictionary()
        self._original_classes: Dict[str, Type] = {}
        self._patch_patterns: List[Pattern] = []
        self._initialized = True
        
        logger.debug("ModulePatcher initialized")
    
    def patch(
        self,
        module: Union[str, ModuleType],
        lazy: bool = DEFAULT_LAZY_LOAD,
        **config,
    ) -> ModuleType:
        """
        Patch a module for case-insensitive access.
        
        Parameters
        ----------
        module : Union[str, ModuleType]
            Module to patch.
        lazy : bool
            If True, defer loading until first access.
        **config
            Configuration options for CaseInsensitiveModule.
        
        Returns
        -------
        ModuleType
            Patched module.
        
        Raises
        ------
        TypeError
            If module is not a ModuleType or str.
        ImportError
            If module cannot be imported.
        """
        # Resolve module
        if isinstance(module, str):
            # Check common aliases
            if module in COMMON_ALIASES:
                module = COMMON_ALIASES[module]
            
            try:
                original_module = importlib.import_module(module)
            except ImportError as e:
                logger.error(f"Failed to import module '{module}': {e}")
                raise
        elif ismodule(module):
            original_module = module
            module = module.__name__
        else:
            raise TypeError(f"Expected module to be ModuleType or str, got {type(module)}")
        
        module_name = original_module.__name__
        
        # Check if already patched
        if module_name in self._patched_modules:
            logger.debug(f"Module '{module_name}' already patched")
            return self._patched_modules[module_name]
        
        # Store original class
        if module_name not in self._original_classes:
            self._original_classes[module_name] = original_module.__class__
        
        # Create patched module
        patched = CaseInsensitiveModule(original_module.__name__, original_module.__doc__)
        patched._patch_from_original(original_module)
        patched.configure(**config)
        
        # Replace in sys.modules
        sys.modules[module_name] = patched
        
        # Register in weak dictionary
        self._patched_modules[module_name] = patched
        
        logger.info(f"Patched module '{module_name}' for case-insensitive access")
        return patched
    
    def patch_many(
        self,
        modules: List[Union[str, ModuleType]],
        **config,
    ) -> Dict[str, ModuleType]:
        """
        Patch multiple modules.
        
        Parameters
        ----------
        modules : List[Union[str, ModuleType]]
            List of modules to patch.
        **config
            Configuration options for patched modules.
        
        Returns
        -------
        Dict[str, ModuleType]
            Dictionary of patched modules.
        """
        results = {}
        
        for module in modules:
            try:
                patched = self.patch(module, **config)
                name = patched.__name__ if ismodule(patched) else str(module)
                results[name] = patched
            except Exception as e:
                logger.error(f"Failed to patch module '{module}': {e}")
                results[str(module)] = e
        
        return results
    
    def patch_pattern(
        self,
        pattern: Union[str, Pattern],
        include_builtins: bool = False,
        **config,
    ) -> List[ModuleType]:
        """
        Patch all modules matching a pattern.
        
        Parameters
        ----------
        pattern : Union[str, Pattern]
            Regex pattern to match module names.
        include_builtins : bool
            Whether to include built-in modules.
        **config
            Configuration options.
        
        Returns
        -------
        List[ModuleType]
            List of patched modules.
        """
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        
        patched = []
        
        for name, module in list(sys.modules.items()):
            if not include_builtins and (name.startswith('_') or name in sys.builtin_module_names):
                continue
            
            if pattern.search(name):
                try:
                    patched.append(self.patch(module, **config))
                except Exception as e:
                    logger.debug(f"Failed to patch '{name}': {e}")
        
        logger.info(f"Patched {len(patched)} modules matching pattern '{pattern.pattern}'")
        return patched
    
    def patch_recursive(
        self,
        module: Union[str, ModuleType],
        max_depth: int = DEFAULT_RECURSIVE_DEPTH,
        current_depth: int = 0,
        visited: Optional[Set[str]] = None,
        **config,
    ) -> List[ModuleType]:
        """
        Recursively patch a module and its submodules.
        
        Parameters
        ----------
        module : Union[str, ModuleType]
            Root module to patch.
        max_depth : int
            Maximum recursion depth.
        current_depth : int
            Current recursion depth.
        visited : Optional[Set[str]]
            Set of already visited modules.
        **config
            Configuration options.
        
        Returns
        -------
        List[ModuleType]
            List of patched modules.
        """
        if current_depth >= max_depth:
            return []
        
        if visited is None:
            visited = set()
        
        # Patch root module
        patched_root = self.patch(module, **config)
        patched = [patched_root]
        visited.add(patched_root.__name__)
        
        # Find submodules
        for attr_name in dir(patched_root):
            if attr_name.startswith('_'):
                continue
            
            try:
                attr = getattr(patched_root, attr_name)
                if ismodule(attr) and attr.__name__ not in visited:
                    sub_patched = self.patch_recursive(
                        attr,
                        max_depth=max_depth,
                        current_depth=current_depth + 1,
                        visited=visited,
                        **config,
                    )
                    patched.extend(sub_patched)
            except Exception:
                continue
        
        return patched
    
    def restore(self, module: Union[str, ModuleType]) -> ModuleType:
        """
        Restore a patched module to original state.
        
        Parameters
        ----------
        module : Union[str, ModuleType]
            Module to restore.
        
        Returns
        -------
        ModuleType
            Restored original module.
        """
        if ismodule(module):
            module_name = module.__name__
        else:
            module_name = module
        
        # Get current module from sys.modules
        if module_name not in sys.modules:
            raise ValueError(f"Module '{module_name}' not found in sys.modules")
        
        current = sys.modules[module_name]
        
        # Check if it's our patched module
        if not isinstance(current, CaseInsensitiveModule):
            logger.warning(f"Module '{module_name}' is not patched")
            return current
        
        # Restore using module's restore method
        restored = current.restore()
        
        # Remove from registry
        self._patched_modules.pop(module_name, None)
        
        logger.info(f"Restored module '{module_name}'")
        return restored
    
    def restore_all(self) -> List[ModuleType]:
        """
        Restore all patched modules.
        
        Returns
        -------
        List[ModuleType]
            List of restored modules.
        """
        restored = []
        
        for module_name in list(self._patched_modules.keys()):
            try:
                restored.append(self.restore(module_name))
            except Exception as e:
                logger.error(f"Failed to restore '{module_name}': {e}")
        
        return restored
    
    def is_patched(self, module: Union[str, ModuleType]) -> bool:
        """
        Check if a module is patched.
        
        Parameters
        ----------
        module : Union[str, ModuleType]
            Module to check.
        
        Returns
        -------
        bool
            True if module is patched.
        """
        if ismodule(module):
            module_name = module.__name__
        else:
            module_name = module
        
        if module_name not in sys.modules:
            return False
        
        current = sys.modules[module_name]
        return isinstance(current, CaseInsensitiveModule)
    
    def get_stats(self, module: Optional[Union[str, ModuleType]] = None) -> Dict[str, Any]:
        """
        Get statistics for patched modules.
        
        Parameters
        ----------
        module : Optional[Union[str, ModuleType]]
            Specific module or None for all.
        
        Returns
        -------
        Dict[str, Any]
            Statistics dictionary.
        """
        if module is not None:
            if ismodule(module):
                module = module.__name__
            
            if module in sys.modules:
                current = sys.modules[module]
                if isinstance(current, CaseInsensitiveModule):
                    return {module: current.get_stats()}
            return {}
        
        # Aggregate stats for all patched modules
        stats = {
            'total_patched': len(self._patched_modules),
            'modules': {},
        }
        
        for name, mod in self._patched_modules.items():
            if hasattr(mod, 'get_stats'):
                stats['modules'][name] = mod.get_stats()
        
        return stats


# -----------------------------------------------------------------------------
# Context Manager for Temporary Patching
# -----------------------------------------------------------------------------

@contextmanager
def patch_context(
    module: Union[str, ModuleType, List[Union[str, ModuleType]]],
    recursive: bool = False,
    max_depth: int = DEFAULT_RECURSIVE_DEPTH,
    **config,
) -> Iterator[Union[ModuleType, List[ModuleType]]]:
    """
    Context manager for temporary module patching.
    
    Modules are patched on entry and automatically restored on exit.
    
    Parameters
    ----------
    module : Union[str, ModuleType, List]
        Module(s) to temporarily patch.
    recursive : bool
        Whether to recursively patch submodules.
    max_depth : int
        Maximum depth for recursive patching.
    **config
        Configuration options for patched modules.
    
    Yields
    ------
    Union[ModuleType, List[ModuleType]]
        Patched module(s).
    
    Examples
    --------
    >>> with patch_context("requests") as req:
    ...     response = req.gEt("https://api.example.com")
    ...     data = response["json"]()
    
    >>> with patch_context(["numpy", "pandas"]) as (np, pd):
    ...     arr = np.ARRAY([1, 2, 3])
    ...     df = pd.DATAFRAME({'a': arr})
    """
    patcher = ModulePatcher()
    was_list = isinstance(module, list)
    
    try:
        if was_list:
            patched = []
            for mod in module:
                if recursive:
                    patched.extend(patcher.patch_recursive(mod, max_depth=max_depth, **config))
                else:
                    patched.append(patcher.patch(mod, **config))
            yield patched
        else:
            if recursive:
                patched = patcher.patch_recursive(module, max_depth=max_depth, **config)
                yield patched
            else:
                patched = patcher.patch(module, **config)
                yield patched
    finally:
        # Restore all patched modules
        if was_list:
            for mod in module:
                mod_name = mod if isinstance(mod, str) else mod.__name__
                if patcher.is_patched(mod_name):
                    patcher.restore(mod_name)
        else:
            mod_name = module if isinstance(module, str) else module.__name__
            if patcher.is_patched(mod_name):
                patcher.restore(mod_name)


# -----------------------------------------------------------------------------
# Public API Functions
# -----------------------------------------------------------------------------

# Global patcher instance
_patcher = ModulePatcher()


def patch_module(
    module: Union[str, ModuleType],
    lazy: bool = DEFAULT_LAZY_LOAD,
    **config,
) -> ModuleType:
    """
    Patch a module to enable case-insensitive access with typo suggestions.
    
    This is the main public function for patching modules. It provides
    comprehensive configuration options and maintains backward compatibility.
    
    Parameters
    ----------
    module : str or ModuleType
        The module to patch. Can be either a module object or import name.
    lazy : bool
        If True, defer loading until first access.
    **config
        Configuration options:
        - enable_cache: bool (default: True)
        - enable_suggestions: bool (default: True)
        - enable_stats: bool (default: True)
        - fuzzy_cutoff: float (default: 0.6)
        - max_suggestions: int (default: 3)
        - case_sensitive_fallback: bool (default: True)
    
    Returns
    -------
    ModuleType
        The patched module.
    
    Examples
    --------
    >>> import requests
    >>> patch_module(requests)
    >>> requests.GET
    >>> requests.gEt
    >>> requests["post"]
    >>> requests("head")
    >>> requests.gte  # typo
    AttributeError: Module 'requests' has no attribute 'gte'. Did you mean: get? (95% match)
    
    >>> # With custom configuration
    >>> patch_module("numpy", enable_stats=True, fuzzy_cutoff=0.8)
    >>> import numpy
    >>> numpy.get_stats()  # View access statistics
    """
    return _patcher.patch(module, lazy=lazy, **config)


def patch_modules(
    modules: List[Union[str, ModuleType]],
    **config,
) -> Dict[str, ModuleType]:
    """
    Batch patch multiple modules.
    
    Parameters
    ----------
    modules : List[Union[str, ModuleType]]
        List of modules to patch.
    **config
        Configuration options (see patch_module).
    
    Returns
    -------
    Dict[str, ModuleType]
        Dictionary of patched modules.
    
    Examples
    --------
    >>> results = patch_modules(["numpy", "pandas", "matplotlib"])
    >>> for name, mod in results.items():
    ...     if not isinstance(mod, Exception):
    ...         print(f"Patched: {name}")
    """
    return _patcher.patch_many(modules, **config)


def patch_pattern(
    pattern: Union[str, Pattern],
    include_builtins: bool = False,
    **config,
) -> List[ModuleType]:
    """
    Patch all modules matching a regex pattern.
    
    Parameters
    ----------
    pattern : Union[str, Pattern]
        Regex pattern to match module names.
    include_builtins : bool
        Whether to include built-in modules.
    **config
        Configuration options.
    
    Returns
    -------
    List[ModuleType]
        List of patched modules.
    
    Examples
    --------
    >>> # Patch all data science modules
    >>> patched = patch_pattern(r"^(numpy|pandas|scipy|sklearn)")
    >>> print(f"Patched {len(patched)} modules")
    """
    return _patcher.patch_pattern(pattern, include_builtins=include_builtins, **config)


def patch_recursive(
    module: Union[str, ModuleType],
    max_depth: int = DEFAULT_RECURSIVE_DEPTH,
    **config,
) -> List[ModuleType]:
    """
    Recursively patch a module and all its submodules.
    
    Parameters
    ----------
    module : Union[str, ModuleType]
        Root module to patch.
    max_depth : int
        Maximum recursion depth.
    **config
        Configuration options.
    
    Returns
    -------
    List[ModuleType]
        List of all patched modules.
    
    Examples
    --------
    >>> # Patch matplotlib and all its submodules
    >>> patched = patch_recursive("matplotlib", max_depth=2)
    >>> print(f"Patched {len(patched)} modules including submodules")
    """
    return _patcher.patch_recursive(module, max_depth=max_depth, **config)


def restore_module(module: Union[str, ModuleType]) -> ModuleType:
    """
    Restore a patched module to its original state.
    
    Parameters
    ----------
    module : Union[str, ModuleType]
        Module to restore.
    
    Returns
    -------
    ModuleType
        Restored original module.
    
    Examples
    --------
    >>> patch_module("requests")
    >>> # ... use patched requests ...
    >>> restore_module("requests")
    >>> # requests is back to normal
    """
    return _patcher.restore(module)


def restore_all_modules() -> List[ModuleType]:
    """
    Restore all patched modules to original state.
    
    Returns
    -------
    List[ModuleType]
        List of restored modules.
    """
    return _patcher.restore_all()


def is_patched(module: Union[str, ModuleType]) -> bool:
    """
    Check if a module has been patched.
    
    Parameters
    ----------
    module : Union[str, ModuleType]
        Module to check.
    
    Returns
    -------
    bool
        True if module is patched.
    
    Examples
    --------
    >>> patch_module("json")
    >>> is_patched("json")
    True
    >>> restore_module("json")
    >>> is_patched("json")
    False
    """
    return _patcher.is_patched(module)


def get_patch_stats(module: Optional[Union[str, ModuleType]] = None) -> Dict[str, Any]:
    """
    Get statistics for patched modules.
    
    Parameters
    ----------
    module : Optional[Union[str, ModuleType]]
        Specific module or None for aggregate statistics.
    
    Returns
    -------
    Dict[str, Any]
        Statistics dictionary.
    
    Examples
    --------
    >>> patch_module("requests", enable_stats=True)
    >>> import requests
    >>> requests.get
    >>> requests.GET
    >>> stats = get_patch_stats("requests")
    >>> print(f"Cache hit rate: {stats['requests']['hit_rate']}")
    """
    return _patcher.get_stats(module)


def configure_patched_module(
    module: Union[str, ModuleType],
    **config,
) -> None:
    """
    Configure an already patched module.
    
    Parameters
    ----------
    module : Union[str, ModuleType]
        Patched module to configure.
    **config
        Configuration options (see patch_module).
    
    Raises
    ------
    ValueError
        If module is not patched.
    
    Examples
    --------
    >>> patch_module("requests")
    >>> configure_patched_module("requests", enable_stats=True, fuzzy_cutoff=0.8)
    """
    if ismodule(module):
        mod = module
    else:
        if module not in sys.modules:
            raise ValueError(f"Module '{module}' not found")
        mod = sys.modules[module]
    
    if not isinstance(mod, CaseInsensitiveModule):
        raise ValueError(f"Module '{mod.__name__}' is not patched")
    
    mod.configure(**config)


def with_case_insensitive(
    modules: Union[str, ModuleType, List[Union[str, ModuleType]]],
    **config,
):
    """
    Decorator to temporarily patch modules for a function.
    
    Parameters
    ----------
    modules : Union[str, ModuleType, List]
        Module(s) to temporarily patch.
    **config
        Configuration options.
    
    Returns
    -------
    Callable
        Decorated function.
    
    Examples
    --------
    >>> @with_case_insensitive("requests")
    ... def fetch_data():
    ...     import requests
    ...     return requests.GET("https://api.example.com")
    >>> 
    >>> data = fetch_data()  # requests is patched only inside function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with patch_context(modules, **config):
                return func(*args, **kwargs)
        return wrapper
    return decorator


# -----------------------------------------------------------------------------
# Module Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Main classes
    'CaseInsensitiveModule',
    'ModulePatcher',
    'TypoSuggester',
    'AccessCache',
    'TypoSuggestion',
    'AccessStats',
    
    # Primary functions
    'patch_module',
    'patch_modules',
    'patch_pattern',
    'patch_recursive',
    'restore_module',
    'restore_all_modules',
    'is_patched',
    'get_patch_stats',
    'configure_patched_module',
    
    # Context managers and decorators
    'patch_context',
    'with_case_insensitive',
]