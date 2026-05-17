#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
A sophisticated file import module that transforms data files into dynamic Python modules
with caching and live updates.
"""

import os
import json
import csv
import xml.etree.ElementTree as ET
import configparser
import importlib.util
import importlib
import asyncio
import threading
import time
import hashlib
from pathlib import Path
from types import ModuleType, MethodType
from dataclasses import dataclass, field
from typing import Any, Optional, Dict, List, Set, Callable, Union, Tuple
from enum import Enum, auto
from contextlib import contextmanager
from collections import defaultdict, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
import inspect


class ModuleState(Enum):
    """
    Represents different states of module data throughout its lifecycle.

    The state machine governs how data is loaded, accessed, linked, and optimized,
    enabling lazy evaluation and performance tuning based on usage patterns.

    Attributes
    ----------
    UNLOADED : auto
        Data exists in potential form but has not been loaded into memory.
        This state conserves resources until the data is explicitly required.
    LOADED : auto
        Data has been fully loaded into memory and is accessible for direct
        operations. The transition from UNLOADED to LOADED occurs upon first
        access or explicit load request.
    ACTIVE : auto
        Data is being actively used, with watchers registered for change
        notifications. This state indicates high-frequency access patterns
        and may trigger preemptive caching strategies.
    LINKED : auto
        Data is connected to other data sources through linking operations.
        Links can represent mathematical relationships, structural merges,
        or reference dependencies between data fields.
    OPTIMIZED : auto
        Data has been optimized for performance through indexing, compression,
        or other enhancement techniques. This state represents the highest
        level of data readiness for intensive operations.
    """

    UNLOADED = auto()  # Data exists but not loaded
    LOADED = auto()  # Data fully loaded and accessible
    ACTIVE = auto()  # Data being actively used
    LINKED = auto()  # Data connected to other sources
    OPTIMIZED = auto()  # Data optimized for performance


@dataclass
class DataField:
    """
    Data field with comprehensive state management capabilities.

    A DataField represents a single data element that can exist in various states
    of readiness, from unloaded potential to fully optimized active data. It
    manages the lifecycle of data values, supports lazy loading, enables observer
    patterns through watchers, and facilitates inter-field linking operations.

    The field maintains separate storage for potential (lazy) and loaded (active)
    values, allowing for memory-efficient operations until explicit loading is
    required. State transitions are tracked and can trigger notifications to
    registered watchers.

    Attributes
    ----------
    name : str
        Unique identifier for this data field within its context.
    potential_value : Any, optional
        The value that can be loaded when needed, representing the lazy state.
        Default is None.
    loaded_value : Any, optional
        The actively loaded value after transitioning from UNLOADED state.
        Default is None.
    watchers : Set[Callable], optional
        Collection of callback functions to notify upon state changes.
        Default is an empty set.
    state : ModuleState, optional
        Current state in the data lifecycle, initialized to UNLOADED.
    linked_to : DataField, optional
        Reference to another DataField when in LINKED state. This attribute
        is set dynamically during link operations and is not part of the
        formal dataclass fields.

    Examples
    --------
    >>> field = DataField(name="temperature", potential_value=25.5)
    >>> print(field.state)
    ModuleState.UNLOADED
    >>> value = field.load()
    >>> print(field.state)
    ModuleState.LOADED
    >>> print(value)
    25.5

    >>> def temp_watcher():
    ...     print("Temperature field state changed!")
    >>> field.watch(temp_watcher)
    >>> print(field.state)
    ModuleState.ACTIVE
    """

    name: str
    potential_value: Any = None
    loaded_value: Any = None
    watchers: Set[Callable] = field(default_factory=set)
    state: ModuleState = ModuleState.UNLOADED

    def load(self) -> Any:
        """
        Load the data field from potential state into active memory.

        Transitions the field from UNLOADED to LOADED state by promoting
        the potential_value to loaded_value. If the field is already loaded
        or in a higher state, the loaded_value is returned directly without
        state modification.

        Returns
        -------
        Any
            The loaded value of the data field, ready for immediate use.

        Notes
        -----
        This method implements lazy loading semantics. The first call triggers
        the state transition and value promotion; subsequent calls return the
        cached loaded_value without additional processing.

        Examples
        --------
        >>> field = DataField(name="config", potential_value={"debug": True})
        >>> field.state
        <ModuleState.UNLOADED: 1>
        >>> config = field.load()
        >>> field.state
        <ModuleState.LOADED: 2>
        >>> config["debug"]
        True
        """
        if self.state == ModuleState.UNLOADED and self.potential_value:
            self.loaded_value = self.potential_value
            self.state = ModuleState.LOADED
        return self.loaded_value

    def watch(self, watcher: Callable):
        """
        Register a watcher callback for state change notifications.

        Adds the provided callable to the field's watcher collection and
        transitions the field state to ACTIVE, indicating that the data
        is being monitored for changes.

        Parameters
        ----------
        watcher : Callable
            A callable object (function, method, or lambda) that will be
            invoked when the field's state or value changes. The watcher
            should accept no arguments, or should be designed to handle
            the specific notification pattern used.

        Notes
        -----
        The watcher collection uses a set to prevent duplicate registrations.
        State transitions to ACTIVE indicate that the field is under active
        observation and may be subject to additional optimizations.

        Examples
        --------
        >>> field = DataField(name="status", potential_value="idle")
        >>> def on_status_change():
        ...     print(f"Status changed to: {field.load()}")
        >>> field.watch(on_status_change)
        >>> field.state
        <ModuleState.ACTIVE: 3>
        """
        self.watchers.add(watcher)
        self.state = ModuleState.ACTIVE

    def link(self, other: "DataField", operation: str = "add"):
        """
        Link this data field with another field through a specified operation.

        Creates a relationship between two DataField instances, combining their
        values according to the operation type. The result becomes the new
        potential_value of this field, and the state transitions to LINKED.

        Parameters
        ----------
        other : DataField
            The target DataField to link with this instance. The other field
            will be loaded if necessary to access its value.
        operation : str, optional
            The type of linking operation to perform. Valid operations are:
            - 'add': Numeric addition of two values (int or float)
            - 'merge': Dictionary merging (combines key-value pairs)
            - 'reference': Reference linking (stores reference to other field)
            Default is 'add'.

        Raises
        ------
        ValueError
            If the operation cannot be performed due to incompatible value
            types or if an unsupported operation is specified. The error
            message provides details about the type mismatch.

        Notes
        -----
        This method loads both fields if they are in UNLOADED state before
        performing the link operation. After linking, the field's state
        becomes LINKED, and a reference to the other field is stored in
        the `linked_to` attribute for relationship tracking.

        Examples
        --------
        >>> field1 = DataField(name="count", potential_value=10)
        >>> field2 = DataField(name="increment", potential_value=5)
        >>> field1.link(field2, operation="add")
        >>> field1.potential_value
        15
        >>> field1.state
        <ModuleState.LINKED: 4>

        >>> dict1 = DataField(name="base", potential_value={"a": 1})
        >>> dict2 = DataField(name="override", potential_value={"b": 2})
        >>> dict1.link(dict2, operation="merge")
        >>> dict1.potential_value
        {'a': 1, 'b': 2}
        """
        self_value = (
            self.load() if self.state == ModuleState.UNLOADED else self.loaded_value
        )
        other_value = (
            other.load() if other.state == ModuleState.UNLOADED else other.loaded_value
        )

        if (
            operation == "add"
            and isinstance(self_value, (int, float))
            and isinstance(other_value, (int, float))
        ):
            self.potential_value = self_value + other_value
        elif (
            operation == "merge"
            and isinstance(self_value, dict)
            and isinstance(other_value, dict)
        ):
            self.potential_value = {**self_value, **other_value}
        elif operation == "reference":
            self.potential_value = other
        else:
            raise ValueError(
                f"Cannot link values of types {type(self_value)} and {type(other_value)}"
            )

        self.state = ModuleState.LINKED
        self.linked_to = other  # Reference storage


class FileStats:
    """
    Analyzes file structure, context, and relationships for intelligent processing.

    FileStats performs comprehensive analysis of data files to extract structural
    patterns, semantic context, and relationship information. This analysis
    informs caching strategies, linking decisions, and optimization opportunities
    throughout the module system.

    The analyzer examines file metadata, content patterns, naming conventions,
    and directory relationships to build a rich profile of each file's role
    and characteristics within the data ecosystem.

    Attributes
    ----------
    file_path : str
        Absolute path to the analyzed file.
    structure : Dict[str, Any]
        Structural analysis results including complexity, type identification,
        detected patterns, and estimated change rate.
    context : Dict[str, Any]
        Semantic context analysis including domain classification, purpose
        assessment, importance ranking, and update frequency estimation.
    relationships : Dict[str, List[str]]
        Relationship mappings including dependencies, related files, and
        influence connections within the file system.

    Examples
    --------
    >>> stats = FileStats("/path/to/config.json")
    >>> stats.structure["complexity"]
    'simple'
    >>> stats.context["domain"]
    'configuration'
    >>> stats.relationships["related_files"]
    ['/path/to/config_backup.json', '/path/to/config.dev.json']
    """

    def __init__(self, file_path: str):
        """
        Initialize FileStats analyzer for a specific file path.

        Performs immediate analysis of the file upon instantiation, populating
        the structure, context, and relationships attributes with comprehensive
        analysis results.

        Parameters
        ----------
        file_path : str
            Path to the file to analyze. The path is resolved to an absolute
            path and must point to an existing readable file.
        """
        self.file_path = file_path
        self.structure = self._analyze_structure()
        self.context = self._analyze_context()
        self.relationships = self._analyze_relationships()

    def _analyze_structure(self) -> Dict[str, Any]:
        """
        Analyze the structural characteristics of the file.

        Examines file size, format, content patterns, and modification patterns
        to build a structural profile. This analysis informs decisions about
        loading strategies and optimization approaches.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing structural analysis with keys:
            - complexity : str
                Complexity classification ('simple', 'medium', 'complex')
                based on file size thresholds (1KB, 1MB).
            - type : str
                File type classification ('config', 'tabular', 'structured',
                'text', 'unknown') based on extension.
            - patterns : List[str]
                Detected data patterns within the file content.
            - change_rate : str
                Estimated frequency of file modifications.
        """
        path = Path(self.file_path)
        return {
            "complexity": self._calculate_complexity(),
            "type": self._identify_type(),
            "patterns": self._find_patterns(),
            "change_rate": self._estimate_change_rate(),
        }

    def _analyze_context(self) -> Dict[str, Any]:
        """
        Analyze the semantic context and purpose of the file.

        Infers the file's role within the application ecosystem by examining
        naming patterns, directory location, and content characteristics.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing contextual analysis with keys:
            - domain : str
                Functional domain classification ('configuration',
                'data_storage', 'logging', 'general').
            - purpose : str
                Specific purpose assessment within the domain.
            - importance : str
                Relative importance ranking ('low', 'medium', 'high').
            - update_frequency : str
                Estimated update frequency pattern.
        """
        return {
            "domain": self._guess_domain(),
            "purpose": self._guess_purpose(),
            "importance": self._assess_importance(),
            "update_frequency": self._estimate_update_frequency(),
        }

    def _analyze_relationships(self) -> Dict[str, List[str]]:
        """
        Analyze relationships between this file and other files.

        Discovers dependencies, related files, and influence connections through
        directory scanning and naming pattern analysis.

        Returns
        -------
        Dict[str, List[str]]
            Dictionary containing relationship mappings with keys:
            - dependencies : List[str]
                Files that this file depends on.
            - related_files : List[str]
                Files related by naming or location patterns.
            - influences : List[str]
                Files that are influenced by or depend on this file.
        """
        return {
            "dependencies": self._find_dependencies(),
            "related_files": self._find_related_files(),
            "influences": self._find_influences(),
        }

    def _calculate_complexity(self) -> str:
        """
        Calculate the complexity level based on file size.

        Uses size thresholds to categorize files into complexity tiers
        that influence loading and caching strategies.

        Returns
        -------
        str
            Complexity classification:
            - 'simple': Files under 1KB
            - 'medium': Files between 1KB and 1MB
            - 'complex': Files over 1MB
        """
        size = os.path.getsize(self.file_path)
        if size < 1024:
            return "simple"
        elif size < 1024 * 1024:
            return "medium"
        else:
            return "complex"

    def _identify_type(self) -> str:
        """
        Identify the data type based on file extension.

        Maps common file extensions to semantic type categories that guide
        handler selection and processing strategies.

        Returns
        -------
        str
            File type classification:
            - 'config': JSON, YAML, YML files
            - 'tabular': CSV, TSV files
            - 'structured': XML files
            - 'text': TXT files
            - 'unknown': Unrecognized extensions
        """
        ext = Path(self.file_path).suffix.lower()
        if ext in [".json", ".yaml", ".yml"]:
            return "config"
        elif ext in [".csv", ".tsv"]:
            return "tabular"
        elif ext in [".xml"]:
            return "structured"
        elif ext in [".txt"]:
            return "text"
        else:
            return "unknown"

    def _find_patterns(self) -> List[str]:
        """
        Find recurring data patterns within the file content.

        Analyzes file content to identify structural patterns such as
        nested objects, repeating sequences, and data hierarchies.

        Returns
        -------
        List[str]
            List of detected pattern identifiers. Currently returns
            a simplified implementation with basic pattern detection.

        Notes
        -----
        This is a simplified implementation that can be extended with
        more sophisticated pattern recognition algorithms.
        """
        return ["basic_structure"]  # Simplified implementation

    def _estimate_change_rate(self) -> str:
        """
        Estimate how frequently the file is modified.

        Returns
        -------
        str
            Estimated change frequency ('low', 'medium', 'high').
            Currently returns a fixed 'medium' value.

        Notes
        -----
        This simplified implementation can be enhanced with file system
        monitoring and modification history tracking.
        """
        return "medium"

    def _guess_domain(self) -> str:
        """
        Infer the functional domain from file path and name.

        Analyzes the file path string for domain-indicating keywords
        to classify the file's functional area.

        Returns
        -------
        str
            Domain classification:
            - 'configuration': Path contains 'config' or 'setting'
            - 'data_storage': Path contains 'data' or 'db'
            - 'logging': Path contains 'log'
            - 'general': No domain indicators found
        """
        path = self.file_path.lower()
        if "config" in path or "setting" in path:
            return "configuration"
        elif "data" in path or "db" in path:
            return "data_storage"
        elif "log" in path:
            return "logging"
        else:
            return "general"

    def _guess_purpose(self) -> str:
        """
        Infer the specific purpose of the file.

        Returns
        -------
        str
            Purpose classification. Currently returns fixed 'data_storage'
            as a general purpose.

        Notes
        -----
        This simplified implementation can be enhanced with content-based
        purpose detection.
        """
        return "data_storage"

    def _assess_importance(self) -> str:
        """
        Assess the relative importance of the file.

        Returns
        -------
        str
            Importance ranking ('low', 'medium', 'high').
            Currently returns fixed 'medium' importance.

        Notes
        -----
        This simplified implementation can be enhanced with usage pattern
        analysis and dependency graph evaluation.
        """
        return "medium"

    def _estimate_update_frequency(self) -> str:
        """
        Estimate how frequently the file is updated.

        Returns
        -------
        str
            Update frequency estimate. Currently returns fixed 'occasional'
            frequency.

        Notes
        -----
        This simplified implementation can be enhanced with file system
        monitoring and historical modification tracking.
        """
        return "occasional"

    def _find_dependencies(self) -> List[str]:
        """
        Identify files that this file depends on.

        Returns
        -------
        List[str]
            List of dependency file paths. Currently returns an empty list.

        Notes
        -----
        This simplified implementation can be enhanced with import parsing
        and reference detection for various file formats.
        """
        return []

    def _find_related_files(self) -> List[str]:
        """
        Find files related by naming or location patterns.

        Scans the parent directory for files matching a pattern derived
        from this file's stem name (prefix before first underscore).

        Returns
        -------
        List[str]
            List of related file paths matching the derived pattern,
            excluding the current file.
        """
        directory = Path(self.file_path).parent
        pattern = self._get_related_pattern()
        return [str(f) for f in directory.glob(pattern) if f != Path(self.file_path)]

    def _get_related_pattern(self) -> str:
        """
        Generate a glob pattern for finding related files.

        Extracts the prefix before the first underscore from the file stem,
        or uses the full stem if no underscore is present.

        Returns
        -------
        str
            Glob pattern string for matching related files. Format is
            '{prefix}*' where prefix is the extracted file name prefix.
        """
        stem = Path(self.file_path).stem
        return f"{stem.split('_')[0]}*" if "_" in stem else f"{stem}*"

    def _find_influences(self) -> List[str]:
        """
        Identify files that are influenced by or depend on this file.

        Returns
        -------
        List[str]
            List of influenced file paths. Currently returns an empty list.

        Notes
        -----
        This simplified implementation can be enhanced with reverse dependency
        analysis and reference tracking.
        """
        return []


class Cache:
    """
    Intelligent caching system with access prediction and eviction policies.

    Cache implements a least-recently-used (LRU) eviction strategy enhanced with
    access frequency scoring and predictive preloading capabilities. The cache
    maintains access patterns to anticipate future requests and optimize memory
    utilization through intelligent item retention.

    The scoring system balances access frequency against recency, applying a
    time-based decay to prioritize recently accessed items while maintaining
    frequently used items against eviction.

    Attributes
    ----------
    max_size : int
        Maximum number of items the cache can hold before eviction occurs.
    _cache : OrderedDict[str, Any]
        Ordered dictionary maintaining items in access order for LRU eviction.
    _access_count : Dict[str, int]
        Counter tracking total accesses per cache key.
    _last_access : Dict[str, float]
        Timestamp of most recent access per cache key.
    _predictor : AccessPredictor
        Markov chain predictor for anticipating future cache accesses.

    Examples
    --------
    >>> cache = Cache(max_size=100)
    >>> cache.set("user:123", {"name": "Alice", "age": 30})
    >>> data = cache.get("user:123")
    >>> print(data["name"])
    'Alice'
    >>> predictions = cache.predict_next("user:123")
    >>> print(predictions)
    ['user:124', 'user:125', 'user:122']
    """

    def __init__(self, max_size: int = 1000):
        """
        Initialize cache with specified capacity and tracking structures.

        Parameters
        ----------
        max_size : int, optional
            Maximum number of items the cache can store before triggering
            eviction. Default is 1000 items.
        """
        self.max_size = max_size
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._access_count: Dict[str, int] = defaultdict(int)
        self._last_access: Dict[str, float] = {}
        self._predictor = AccessPredictor()

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve an item from the cache by key.

        Updates access metadata including access count, last access timestamp,
        and moves the item to the end of the LRU order. Records the access
        pattern in the predictor for future anticipatory caching.

        Parameters
        ----------
        key : str
            Cache key identifying the item to retrieve.

        Returns
        -------
        Optional[Any]
            The cached value if present, None if the key is not found.

        Notes
        -----
        This method maintains cache statistics and updates the LRU ordering.
        The access is recorded in the predictor regardless of cache hit/miss
        to maintain accurate access pattern models.
        """
        if key in self._cache:
            self._cache.move_to_end(key)
            self._access_count[key] += 1
            self._last_access[key] = time.time()
            self._predictor.record_access(key)
            return self._cache[key]
        return None

    def set(self, key: str, value: Any):
        """
        Store an item in the cache with the specified key.

        If the key already exists, updates the value and moves the item to
        the end of the LRU order. If the cache is at capacity, triggers
        eviction of the least valuable item based on the scoring algorithm.

        Parameters
        ----------
        key : str
            Cache key identifying the item.
        value : Any
            Value to store in the cache. Can be any Python object.

        Notes
        -----
        Setting a value updates all access metadata including counts and
        timestamps. The predictor records this access for pattern analysis.
        """
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self.max_size:
                self._remove_least_used()
            self._cache[key] = value

        self._access_count[key] += 1
        self._last_access[key] = time.time()
        self._predictor.record_access(key)

    def _remove_least_used(self):
        """
        Remove the least valuable item from the cache based on scoring.

        Identifies the cache key with the lowest composite score (balancing
        access frequency against recency) and removes it along with all
        associated metadata. This method is called automatically when the
        cache reaches capacity and a new item needs to be added.

        Notes
        -----
        The removal is atomic - all metadata structures are cleaned up
        to prevent memory leaks. If the cache is empty, this method
        returns without action.
        """
        if not self._cache:
            return

        # Find item with lowest score
        least_key = min(self._cache.keys(), key=lambda k: self._calculate_score(k))
        del self._cache[least_key]
        del self._access_count[least_key]
        del self._last_access[least_key]

    def _calculate_score(self, key: str) -> float:
        """
        Calculate a retention score for cache eviction decisions.

        The score balances access frequency against recency using a formula
        that increases with access count and decreases with time since last
        access. Higher scores indicate items that should be retained.

        Parameters
        ----------
        key : str
            Cache key to calculate score for.

        Returns
        -------
        float
            Retention score where higher values indicate greater value.
            Formula: access_count - (hours_since_last_access)

        Notes
        -----
        The time decay uses hours as the unit, meaning each hour since last
        access reduces the score by 1. This provides a balance between
        preserving frequently accessed items and removing stale ones.
        """
        count = self._access_count[key]
        last_access = self._last_access.get(key, 0)
        time_since_access = time.time() - last_access

        # Higher score = more likely to keep
        return count - (time_since_access / 3600)  # Hours decay

    def predict_next(self, current_key: str) -> List[str]:
        """
        Predict likely future cache accesses based on current key.

        Uses Markov chain analysis of historical access patterns to anticipate
        which keys are most likely to be accessed following the current key.

        Parameters
        ----------
        current_key : str
            The key currently being accessed, used as the starting state
            for prediction.

        Returns
        -------
        List[str]
            List of predicted next keys, ordered by decreasing probability.
            Returns up to 3 predictions with probability > 0.1.

        Examples
        --------
        >>> cache.set("page:1", data1)
        >>> cache.set("page:2", data2)
        >>> cache.set("page:3", data3)
        >>> cache.get("page:1")
        >>> cache.get("page:2")
        >>> cache.get("page:1")
        >>> predictions = cache.predict_next("page:1")
        >>> print(predictions)
        ['page:2', 'page:3']
        """
        return self._predictor.predict(current_key)


class AccessPredictor:
    """
    Predicts access patterns using first-order Markov chain analysis.

    AccessPredictor builds a transition probability model from observed
    access sequences, enabling anticipation of future cache accesses for
    preemptive loading strategies. The model captures sequential patterns
    in key accesses to predict likely next keys.

    Attributes
    ----------
    _transitions : Dict[str, Dict[str, int]]
        Transition count matrix mapping from a key to observed subsequent
        keys with occurrence frequencies.
    _recent : List[str]
        Sliding window of recent accesses (maximum 10 items) used to
        maintain temporal context for transition recording.

    Examples
    --------
    >>> predictor = AccessPredictor()
    >>> predictor.record_access("A")
    >>> predictor.record_access("B")
    >>> predictor.record_access("C")
    >>> predictor.record_access("A")
    >>> predictor.record_access("B")
    >>> predictions = predictor.predict("A")
    >>> print(predictions)
    ['B']
    """

    def __init__(self):
        """
        Initialize predictor with empty transition model and recent history.
        """
        self._transitions: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._recent: List[str] = []

    def record_access(self, key: str):
        """
        Record a cache access for pattern learning.

        Updates the transition model by incrementing the count for the
        transition from the previously accessed key to the current key.
        Maintains a sliding window of recent accesses for context.

        Parameters
        ----------
        key : str
            The cache key being accessed. This becomes the potential source
            state for future transitions.

        Notes
        -----
        The first access only adds to recent history without creating a
        transition (no previous key exists). The recent history is limited
        to 10 items to focus on recent patterns.
        """
        if self._recent:
            last_key = self._recent[-1]
            self._transitions[last_key][key] += 1

        self._recent.append(key)
        if len(self._recent) > 10:
            self._recent.pop(0)

    def predict(self, current_key: str) -> List[str]:
        """
        Predict likely next keys based on current key.

        Analyzes the transition model to find keys that frequently follow
        the current key, filtering by probability threshold and ordering
        by likelihood.

        Parameters
        ----------
        current_key : str
            The current state key from which to predict transitions.

        Returns
        -------
        List[str]
            Predicted next keys with transition probability > 0.1, ordered
            by descending probability. Maximum 3 predictions returned.

        Notes
        -----
        Predictions are filtered to include only statistically significant
        transitions (probability > 0.1) to avoid noise. If no transitions
        exist for the current key, returns an empty list.
        """
        if current_key not in self._transitions:
            return []

        transitions = self._transitions[current_key]
        total = sum(transitions.values())

        predictions = []
        for next_key, count in transitions.items():
            probability = count / total
            if probability > 0.1:  # Only significant probabilities
                predictions.append(next_key)

        return sorted(predictions, key=lambda k: transitions[k], reverse=True)[:3]


class DataProcessor:
    """
    Comprehensive data analysis and quality assessment processor.

    DataProcessor orchestrates multiple analysis components to provide
    holistic insights into data structures. It combines pattern detection,
    issue identification, and performance optimization suggestions with
    an overall quality scoring mechanism.

    The processor examines data recursively to identify structural patterns,
    potential data quality issues, and opportunities for performance
    improvements, synthesizing these into actionable intelligence.

    Attributes
    ----------
    pattern_finder : PatternFinder
        Component that identifies structural and recurring patterns.
    issue_detector : IssueDetector
        Component that detects data quality and consistency issues.
    optimizer : PerformanceOptimizer
        Component that suggests optimizations for large datasets.

    Examples
    --------
    >>> processor = DataProcessor()
    >>> data = {"users": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]}
    >>> analysis = processor.analyze(data)
    >>> print(analysis["quality_score"])
    1.0
    >>> print(analysis["patterns"]["nested_structures"])
    ['root', 'root.users']
    >>> print(len(analysis["issues"]))
    0
    """

    def __init__(self):
        """
        Initialize DataProcessor with its component analyzers.
        """
        self.pattern_finder = PatternFinder()
        self.issue_detector = IssueDetector()
        self.optimizer = PerformanceOptimizer()

    def analyze(self, data: Any) -> Dict[str, Any]:
        """
        Perform comprehensive analysis of the provided data structure.

        Executes all analysis components and compiles their results into
        a unified analysis report including patterns, issues, optimization
        suggestions, and an overall quality assessment.

        Parameters
        ----------
        data : Any
            The data structure to analyze. Can be any Python object,
            though dict and list structures receive the most detailed
            analysis.

        Returns
        -------
        Dict[str, Any]
            Comprehensive analysis dictionary with keys:
            - patterns : Dict[str, Any]
                Pattern detection results from PatternFinder.
            - issues : List[Dict[str, Any]]
                List of detected data quality issues.
            - optimizations : List[Dict[str, Any]]
                Performance optimization suggestions.
            - quality_score : float
                Overall quality score from 0.0 to 1.0, calculated as
                1.0 - (issue_count * 0.1) with a minimum of 0.0.

        Examples
        --------
        >>> processor = DataProcessor()
        >>> data = {"config": None, "items": [1, "two", 3]}
        >>> analysis = processor.analyze(data)
        >>> analysis["quality_score"]
        0.8
        >>> analysis["issues"][0]["type"]
        'missing_value'
        """
        return {
            "patterns": self.pattern_finder.find(data),
            "issues": self.issue_detector.detect(data),
            "optimizations": self.optimizer.suggest(data),
            "quality_score": self._calculate_quality(data),
        }

    def _calculate_quality(self, data: Any) -> float:
        """
        Calculate an overall quality score for the data.

        Derives a score from 0.0 to 1.0 based on the number and severity
        of detected issues. Each issue reduces the score by 0.1, with a
        floor of 0.0.

        Parameters
        ----------
        data : Any
            The data structure to evaluate.

        Returns
        -------
        float
            Quality score between 0.0 (poor) and 1.0 (excellent).

        Notes
        -----
        This is a simplified scoring model. Enhanced implementations could
        weight issues by severity or incorporate pattern-based quality metrics.
        """
        issues = self.issue_detector.detect(data)
        return max(0.0, 1.0 - len(issues) * 0.1)


class PatternFinder:
    """
    Identifies structural patterns and characteristics in data.

    PatternFinder recursively analyzes data structures to detect nested
    hierarchies, repeating patterns, and structural relationships. The
    analysis provides insights into data organization that inform
    optimization and processing strategies.

    Examples
    --------
    >>> finder = PatternFinder()
    >>> data = {"users": [{"id": 1}, {"id": 2}], "config": {"debug": True}}
    >>> patterns = finder.find(data)
    >>> patterns["nested_structures"]
    ['root', 'root.users', 'root.config']
    >>> patterns["repeating_patterns"]
    ['root.users']
    """

    def find(self, data: Any) -> Dict[str, Any]:
        """
        Find and categorize patterns within the data structure.

        Performs recursive traversal of the data to identify structural
        patterns including nested objects, repeating sequences, hierarchies,
        and value ranges.

        Parameters
        ----------
        data : Any
            The data structure to analyze.

        Returns
        -------
        Dict[str, Any]
            Pattern analysis dictionary with keys:
            - nested_structures : List[str]
                Paths to nested dictionary structures.
            - repeating_patterns : List[str]
                Paths to repeating list structures (length > 1).
            - data_hierarchy : List[str]
                Hierarchical relationships in the data.
            - value_ranges : Dict[str, Any]
                Value range information for numeric fields.
        """
        patterns = {
            "nested_structures": [],
            "repeating_patterns": [],
            "data_hierarchy": [],
            "value_ranges": {},
        }
        self._analyze_patterns(data, patterns, [])
        return patterns

    def _analyze_patterns(self, data: Any, patterns: Dict, path: List[str]):
        """
        Recursively analyze data patterns at each level.

        Traverses the data structure, building path information and
        recording pattern observations in the provided patterns dictionary.

        Parameters
        ----------
        data : Any
            Current data node being analyzed.
        patterns : Dict
            Patterns dictionary to update with findings.
        path : List[str]
            Current path components from root to this node.
        """
        current_path = ".".join(path) if path else "root"

        if isinstance(data, dict):
            patterns["nested_structures"].append(current_path)
            for key, value in data.items():
                self._analyze_patterns(value, patterns, path + [str(key)])

        elif isinstance(data, list):
            if len(data) > 1:
                patterns["repeating_patterns"].append(current_path)
            for i, item in enumerate(data):
                self._analyze_patterns(item, patterns, path + [f"[{i}]"])


class IssueDetector:
    """
    Detects potential data quality and consistency issues.

    IssueDetector performs recursive analysis to identify common data
    problems including missing values, empty structures, type inconsistencies,
    and structural anomalies. Each detected issue includes severity
    classification and location information.

    Examples
    --------
    >>> detector = IssueDetector()
    >>> data = {"name": None, "items": [], "mixed": [1, "two", 3]}
    >>> issues = detector.detect(data)
    >>> len(issues)
    3
    >>> issues[0]["type"]
    'missing_value'
    >>> issues[2]["type"]
    'mixed_types'
    >>> issues[2]["severity"]
    'high'
    """

    def detect(self, data: Any) -> List[Dict[str, Any]]:
        """
        Detect data quality issues throughout the structure.

        Performs comprehensive recursive analysis to identify all potential
        data quality problems, returning detailed information about each
        issue including its location, type, and severity.

        Parameters
        ----------
        data : Any
            The data structure to analyze for issues.

        Returns
        -------
        List[Dict[str, Any]]
            List of detected issues, each containing:
            - path : str
                Dot-notation path to the issue location.
            - type : str
                Issue type identifier (e.g., 'missing_value', 'mixed_types').
            - severity : str
                Issue severity ('low', 'medium', 'high').

        Notes
        -----
        Detected issue types include:
        - 'missing_value': None values in the structure
        - 'empty_dictionary': Empty dict objects
        - 'empty_list': Empty list objects
        - 'mixed_types': Lists containing heterogeneous types
        """
        issues = []
        self._find_issues(data, issues, [])
        return issues

    def _find_issues(self, data: Any, issues: List, path: List[str]):
        """
        Recursively find issues at each level of the data structure.

        Parameters
        ----------
        data : Any
            Current data node being examined.
        issues : List
            List to append detected issues to.
        path : List[str]
            Current path components from root to this node.
        """
        current_path = ".".join(path) if path else "root"

        if data is None:
            issues.append(
                {"path": current_path, "type": "missing_value", "severity": "low"}
            )

        elif isinstance(data, dict):
            if not data:
                issues.append(
                    {
                        "path": current_path,
                        "type": "empty_dictionary",
                        "severity": "medium",
                    }
                )

            for key, value in data.items():
                self._find_issues(value, issues, path + [str(key)])

        elif isinstance(data, list):
            if len(data) == 0:
                issues.append(
                    {"path": current_path, "type": "empty_list", "severity": "low"}
                )

            # Check type consistency
            if len(data) > 1:
                first_type = type(data[0])
                if not all(isinstance(x, first_type) for x in data[1:]):
                    issues.append(
                        {
                            "path": current_path,
                            "type": "mixed_types",
                            "severity": "high",
                        }
                    )


class PerformanceOptimizer:
    """
    Suggests performance optimizations for data structures.

    PerformanceOptimizer analyzes data characteristics to identify
    opportunities for optimization, particularly for large datasets
    that may benefit from alternative storage strategies or access
    patterns.

    Examples
    --------
    >>> optimizer = PerformanceOptimizer()
    >>> large_dict = {f"key_{i}": i for i in range(200)}
    >>> suggestions = optimizer.suggest(large_dict)
    >>> suggestions[0]["suggestion"]
    'Large dictionary - consider database'
    >>> suggestions[0]["benefit"]
    'high'
    """

    def suggest(self, data: Any) -> List[Dict[str, Any]]:
        """
        Suggest performance optimizations for the data structure.

        Analyzes data size and characteristics to recommend optimization
        strategies that could improve performance for large or complex
        data structures.

        Parameters
        ----------
        data : Any
            The data structure to analyze for optimization opportunities.

        Returns
        -------
        List[Dict[str, Any]]
            List of optimization suggestions, each containing:
            - path : str
                Path to the optimization target.
            - suggestion : str
                Description of the recommended optimization.
            - benefit : str
                Estimated benefit level ('low', 'medium', 'high').

        Notes
        -----
        Current optimization triggers:
        - Dictionaries with > 100 keys: Consider database storage
        - Lists with > 1000 items: Consider pagination
        """
        suggestions = []
        self._find_optimizations(data, suggestions, [])
        return suggestions

    def _find_optimizations(self, data: Any, suggestions: List, path: List[str]):
        """
        Recursively find optimization opportunities.

        Parameters
        ----------
        data : Any
            Current data node being examined.
        suggestions : List
            List to append optimization suggestions to.
        path : List[str]
            Current path components from root to this node.
        """
        current_path = ".".join(path) if path else "root"

        if isinstance(data, dict):
            if len(data) > 100:
                suggestions.append(
                    {
                        "path": current_path,
                        "suggestion": "Large dictionary - consider database",
                        "benefit": "high",
                    }
                )

            for key, value in data.items():
                self._find_optimizations(value, suggestions, path + [str(key)])

        elif isinstance(data, list):
            if len(data) > 1000:
                suggestions.append(
                    {
                        "path": current_path,
                        "suggestion": "Large list - consider pagination",
                        "benefit": "medium",
                    }
                )


class FileModule:
    """
    Main module for converting files to Python modules with advanced features.

    FileModule serves as the primary interface for transforming data files
    into dynamic Python modules with state management, caching, analysis,
    and intelligent linking capabilities. It orchestrates the entire workflow
    from file reading through module creation and ongoing management.

    The class maintains a registry of file format handlers, a global cache
    system, file statistics analyzers, and data field registries. It supports
    both synchronous and asynchronous module creation, file watching for live
    updates, and automatic linking of related files.

    Attributes
    ----------
    _handlers : Dict[str, Callable]
        Class-level registry mapping file extensions to handler functions.
    _cache : Cache
        Class-level cache instance for module storage.
    _analyzers : Dict[str, FileStats]
        Class-level registry of file statistics analyzers.
    _data_fields : Dict[str, DataField]
        Class-level registry of data fields.
    use_states : bool
        Instance flag controlling state-based lazy loading.
    auto_link : bool
        Instance flag controlling automatic linking of related files.
    cache : Cache
        Instance-level cache for this FileModule.
    live_monitors : Dict[str, threading.Thread]
        Active file monitoring threads.
    processor : DataProcessor
        Data analysis and processing component.
    linker : FileLinker
        Module linking and relationship management component.

    Examples
    --------
    >>> fm = FileModule(use_states=True, cache_size=2000, auto_link=True)
    >>> module = fm.create_module("config.json")
    >>> print(module.get_state())
    ModuleState.LOADED
    >>> data = module.load_data()
    >>> print(data["version"])
    '1.0.0'

    >>> modules = await fm.create_many(["file1.json", "file2.yaml"])
    >>> for mod in modules:
    ...     print(mod.__file__)
    """

    _handlers: Dict[str, Callable] = {}
    _cache = Cache()
    _analyzers: Dict[str, FileStats] = {}
    _data_fields: Dict[str, DataField] = {}

    def __init__(
        self, use_states: bool = True, cache_size: int = 2000, auto_link: bool = True
    ):
        """
        Initialize FileModule with configuration options.

        Parameters
        ----------
        use_states : bool, optional
            Enable state-based lazy loading of data. When True, data is
            initially in UNLOADED state and only loaded on first access.
            When False, data is immediately loaded. Default is True.
        cache_size : int, optional
            Maximum number of modules to cache in memory. When exceeded,
            least recently used modules are evicted. Default is 2000.
        auto_link : bool, optional
            Enable automatic linking of related files during module creation.
            When True, the linker component connects modules with related
            files. Default is True.
        """
        self.use_states = use_states
        self.auto_link = auto_link
        self.cache = Cache(cache_size)
        self.live_monitors: Dict[str, threading.Thread] = {}
        self.processor = DataProcessor()
        self.linker = FileLinker()

    @classmethod
    def register_handler(
        cls, extensions: Union[str, List[str]], states: List[ModuleState] = None
    ):
        """
        Register a file handler function for specified extensions.

        Decorator factory that registers handler functions for processing
        specific file formats. Handlers are wrapped to create DataField
        instances with state management capabilities.

        Parameters
        ----------
        extensions : Union[str, List[str]]
            File extension(s) to associate with this handler. Can be a single
            extension string (e.g., '.json') or a list of extensions. The
            leading dot is optional and will be normalized.
        states : List[ModuleState], optional
            List of ModuleState values this handler supports. If None,
            defaults to [ModuleState.LOADED, ModuleState.UNLOADED].

        Returns
        -------
        Callable
            Decorator function that wraps and registers the handler.

        Examples
        --------
        >>> @FileModule.register_handler(['json', 'jsonl'])
        ... def load_json(file_path: str, module: FileModule) -> Any:
        ...     with open(file_path, 'r') as f:
        ...         return json.load(f)
        """
        if isinstance(extensions, str):
            extensions = [extensions]

        if states is None:
            states = [ModuleState.LOADED, ModuleState.UNLOADED]

        def decorator(handler: Callable) -> Callable:
            def wrapped_handler(file_path: str, module: "FileModule") -> Any:
                # Create data field for this file
                field = DataField(
                    name=f"file_{hash(file_path)}",
                    potential_value=handler(file_path, module),
                    state=ModuleState.UNLOADED,
                )

                # Store in registry
                field_key = f"{file_path}:{id(handler)}"
                cls._data_fields[field_key] = field

                return field

            for ext in extensions:
                cls._handlers[ext.lower()] = wrapped_handler

            return wrapped_handler

        return decorator

    def create_module(self, file_path: str, force_load: bool = False) -> ModuleType:
        """
        Create a Python module from a data file.

        Processes the specified file using the appropriate registered handler,
        analyzes its structure and context, and builds a dynamic Python module
        with the file's data accessible as attributes.

        Parameters
        ----------
        file_path : str
            Path to the source file to convert. Must point to an existing
            file with a supported extension.
        force_load : bool, optional
            Force immediate data loading regardless of state configuration.
            When True and use_states is enabled, loads data immediately.
            Default is False.

        Returns
        -------
        ModuleType
            Dynamic Python module with file data as attributes. The module
            includes metadata attributes and methods for state management.

        Raises
        ------
        ImportError
            If the file format is not supported or if processing fails.
            The error message includes the file path and failure reason.

        Examples
        --------
        >>> fm = FileModule()
        >>> config = fm.create_module("settings.json")
        >>> print(config.__file__)
        '/absolute/path/to/settings.json'
        >>> data = config.load_data()
        >>> print(data["database"]["host"])
        'localhost'
        """
        file_path = os.path.abspath(file_path)

        # Check cache first
        cache_key = f"module_{hash(file_path)}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        # Analyze file
        if file_path not in self._analyzers:
            self._analyzers[file_path] = FileStats(file_path)

        analyzer = self._analyzers[file_path]

        # Get handler
        ext = Path(file_path).suffix.lower().lstrip(".")
        if ext not in self._handlers:
            raise ImportError(f"Unsupported file format: {ext}")

        handler = self._handlers[ext]

        try:
            # Execute handler
            data_field = handler(file_path, self)

            # Load data if requested
            if force_load or not self.use_states:
                data = data_field.load()
            else:
                data = data_field

            # Create module
            module = self._build_module(
                name=Path(file_path).stem,
                data=data,
                file_path=file_path,
                analyzer=analyzer,
            )

            # Cache module
            self.cache.set(cache_key, module)

            # Auto-link if enabled
            if self.auto_link:
                self.linker.link_module(module, file_path)

            return module

        except Exception as e:
            raise ImportError(f"Failed to create module from {file_path}: {e}")

    def _build_module(
        self, name: str, data: Any, file_path: str, analyzer: FileStats
    ) -> ModuleType:
        """
        Build a Python module from processed data.

        Constructs a dynamic module with the data injected as attributes
        and enhanced with metadata, state management methods, and analysis
        information.

        Parameters
        ----------
        name : str
            Name for the module, typically derived from the filename.
        data : Any
            Processed data to inject into the module. May be a DataField
            instance if state management is enabled.
        file_path : str
            Original source file path for metadata.
        analyzer : FileStats
            File analysis results containing structure and context information.

        Returns
        -------
        ModuleType
            Configured Python module with data attributes and metadata.
        """
        module = ModuleType(name)

        # Core attributes
        module.__file__ = file_path
        module.__data__ = data
        module.__stats__ = analyzer

        # Module methods
        module.load_data = MethodType(
            lambda self: data.load() if isinstance(data, DataField) else data, module
        )
        module.add_watcher = MethodType(
            lambda self, watcher: (
                data.watch(watcher) if isinstance(data, DataField) else None
            ),
            module,
        )
        module.get_state = MethodType(
            lambda self: (
                data.state if isinstance(data, DataField) else ModuleState.LOADED
            ),
            module,
        )

        module.get_patterns = MethodType(lambda self: self.__stats__.structure, module)

        module.get_relationships = MethodType(
            lambda self: self.__stats__.relationships, module
        )

        # Inject data as attributes
        actual_data = data.load() if isinstance(data, DataField) else data
        self._inject_data(module, actual_data, analyzer)

        return module

    def _inject_data(self, module: ModuleType, data: Any, analyzer: FileStats):
        """
        Inject data as module attributes with proper naming.

        Recursively processes data structures and adds them as attributes
        to the module. Nested dictionaries become sub-modules, and values
        become DataField instances when state management is enabled.

        Parameters
        ----------
        module : ModuleType
            Target module to inject data into.
        data : Any
            Data to inject. Dict values create sub-modules or DataFields.
        analyzer : FileStats
            File analysis context for metadata enhancement.
        """
        if isinstance(data, dict):
            for key, value in data.items():
                clean_key = self._clean_key(key)

                if isinstance(value, dict):
                    # Create sub-module for nested data
                    sub_module = ModuleType(clean_key)
                    self._inject_data(sub_module, value, analyzer)
                    setattr(module, clean_key, sub_module)
                else:
                    # Create data field for values
                    field = DataField(
                        name=clean_key, potential_value=value, state=ModuleState.LOADED
                    )
                    setattr(module, clean_key, field)

    def _clean_key(self, key: str) -> str:
        """
        Clean a key string for use as a Python attribute name.

        Replaces invalid characters and ensures the resulting string is
        a valid Python identifier. If cleaning fails to produce a valid
        identifier, generates a fallback name using MD5 hash.

        Parameters
        ----------
        key : str
            Original key name from the data source.

        Returns
        -------
        str
            Cleaned string suitable for use as a Python attribute.
            Invalid characters are replaced with underscores.

        Examples
        --------
        >>> fm = FileModule()
        >>> fm._clean_key("user-name")
        'user_name'
        >>> fm._clean_key("123invalid")
        'field_a1b2c3d4'
        """
        cleaned = (
            str(key)
            .replace(" ", "_")
            .replace("-", "_")
            .replace(".", "_")
            .replace("/", "_")
            .lower()
        )

        # Ensure valid identifier
        if not cleaned.isidentifier():
            cleaned = "field_" + hashlib.md5(cleaned.encode()).hexdigest()[:8]

        return cleaned

    async def create_many(
        self, file_paths: List[str], max_concurrent: int = 5
    ) -> List[ModuleType]:
        """
        Create modules from multiple files concurrently.

        Processes multiple files in parallel with concurrency control,
        significantly improving throughput for batch operations.

        Parameters
        ----------
        file_paths : List[str]
            List of file paths to process into modules.
        max_concurrent : int, optional
            Maximum number of concurrent file processing operations.
            Default is 5.

        Returns
        -------
        List[ModuleType]
            List of created modules in the same order as input paths.
            Failed operations result in exception objects in the list
            rather than modules.

        Examples
        --------
        >>> fm = FileModule()
        >>> files = ["config1.json", "config2.yaml", "data.csv"]
        >>> modules = await fm.create_many(files, max_concurrent=3)
        >>> for mod in modules:
        ...     if isinstance(mod, Exception):
        ...         print(f"Failed: {mod}")
        ...     else:
        ...         print(f"Loaded: {mod.__file__}")
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def create_single(path: str) -> ModuleType:
            async with semaphore:
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, self.create_module, path)

        tasks = [create_single(path) for path in file_paths]
        return await asyncio.gather(*tasks, return_exceptions=True)

    def watch_file(self, file_path: str, on_change: Callable = None) -> "FileWatcher":
        """
        Create a file watcher for live updates on file changes.

        Establishes a monitoring thread that detects file modifications
        and automatically reloads the module when changes occur.

        Parameters
        ----------
        file_path : str
            Path to the file to monitor for changes.
        on_change : Callable, optional
            Optional callback function invoked when file changes are
            detected. Receives the reloaded module as an argument.

        Returns
        -------
        FileWatcher
            Active file watcher instance that manages the monitoring thread.

        Examples
        --------
        >>> fm = FileModule()
        >>> def on_config_change(new_module):
        ...     print(f"Config updated: {new_module.__file__}")
        >>> watcher = fm.watch_file("config.json", on_config_change)
        >>> # File changes will trigger callback
        >>> watcher.stop()  # Clean up when done
        """
        return FileWatcher(file_path, self, on_change)


class FileLinker:
    """
    Manages relationships and links between file modules.

    FileLinker establishes and tracks connections between related files,
    enabling cross-module references and dependency management. It analyzes
    file naming patterns and directory structures to discover implicit
    relationships between data sources.

    Attributes
    ----------
    links : Dict[str, List[str]]
        Mapping from source files to lists of linked target files.
    link_strength : Dict[Tuple[str, str], float]
        Mapping from (source, target) pairs to link strength values (0.0-1.0).

    Examples
    --------
    >>> linker = FileLinker()
    >>> module = create_module("users_2024.json")
    >>> linker.link_module(module, "/data/users_2024.json")
    >>> linker.links["/data/users_2024.json"]
    ['/data/users_2023.json', '/data/users_2024_backup.json']
    """

    def __init__(self):
        """
        Initialize FileLinker with empty link registries.
        """
        self.links: Dict[str, List[str]] = defaultdict(list)
        self.link_strength: Dict[Tuple[str, str], float] = {}

    def link_module(self, module: ModuleType, file_path: str):
        """
        Link a module with its related files.

        Discovers files related to the specified file through naming
        patterns and establishes link relationships in the module.

        Parameters
        ----------
        module : ModuleType
            The module to enhance with link information.
        file_path : str
            Path to the source file for relationship discovery.
        """
        related = self._find_related(file_path)

        for related_file in related:
            self._create_link(module, file_path, related_file)

    def _find_related(self, file_path: str) -> List[str]:
        """
        Find files related to the target file.

        Scans the parent directory for files matching a pattern derived
        from the file's stem name.

        Parameters
        ----------
        file_path : str
            Path to the base file for relationship discovery.

        Returns
        -------
        List[str]
            List of related file paths matching the derived pattern,
            excluding the base file itself.
        """
        directory = Path(file_path).parent
        pattern = self._get_link_pattern(file_path)

        return [str(f) for f in directory.glob(pattern) if f != Path(file_path)]

    def _get_link_pattern(self, file_path: str) -> str:
        """
        Generate a glob pattern for finding related files.

        Extracts the prefix before the first underscore or uses the
        full stem as the pattern base.

        Parameters
        ----------
        file_path : str
            Path to generate pattern from.

        Returns
        -------
        str
            Glob pattern string for matching related files.
        """
        stem = Path(file_path).stem
        return f"{stem.split('_')[0]}*" if "_" in stem else f"{stem}*"

    def _create_link(self, module: ModuleType, source: str, target: str):
        """
        Create a link relationship between files.

        Records the link in internal registries and enhances the module
        with link metadata.

        Parameters
        ----------
        module : ModuleType
            Module to enhance with link information.
        source : str
            Source file path.
        target : str
            Target file path being linked.
        """
        link_key = (source, target)
        self.link_strength[link_key] = 0.7

        # Add link info to module
        if not hasattr(module, "__links__"):
            module.__links__ = []

        module.__links__.append(
            {"target": target, "strength": 0.7, "created": time.time()}
        )


class FileWatcher:
    """
    Monitors files for changes and triggers module updates.

    FileWatcher establishes a background monitoring thread that periodically
    checks file content hashes to detect modifications. When changes are
    detected, it automatically reloads the module and invokes optional
    callback handlers.

    Attributes
    ----------
    file_path : str
        Absolute path to the monitored file.
    module : FileModule
        Reference to the FileModule instance for module recreation.
    on_change : Callable
        Optional callback invoked when file changes are detected.
    is_watching : bool
        Flag indicating whether monitoring is active.
    watcher_thread : threading.Thread
        Background thread performing the monitoring.
    last_hash : str
        MD5 hash of the file's last known content state.

    Examples
    --------
    >>> fm = FileModule()
    >>> def handle_update(new_module):
    ...     print("Configuration updated!")
    >>> watcher = FileWatcher("config.json", fm, handle_update)
    >>> # File changes will trigger handle_update
    >>> watcher.stop()  # Clean shutdown
    """

    def __init__(self, file_path: str, module: FileModule, on_change: Callable = None):
        """
        Initialize and start a file watcher.

        Parameters
        ----------
        file_path : str
            Path to the file to monitor. The file must exist and be readable.
        module : FileModule
            FileModule instance used to recreate the module on changes.
        on_change : Callable, optional
            Callback function invoked when file changes are detected.
            Receives the newly created module as its sole argument.
        """
        self.file_path = file_path
        self.module = module
        self.on_change = on_change
        self.is_watching = False
        self.watcher_thread = None
        self.last_hash = None

        self.start()

    def start(self):
        """
        Start the file monitoring thread.

        Initializes and launches a daemon thread that periodically checks
        for file modifications. The thread runs until stop() is called.
        """
        self.is_watching = True
        self.watcher_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self.watcher_thread.start()

    def stop(self):
        """
        Stop the file monitoring thread.

        Signals the monitoring loop to exit and waits up to 1 second for
        the thread to terminate cleanly.
        """
        self.is_watching = False
        if self.watcher_thread:
            self.watcher_thread.join(timeout=1.0)

    def _watch_loop(self):
        """
        Main monitoring loop that runs in the background thread.

        Periodically checks the file's content hash and triggers module
        reload when changes are detected. Sleeps for 1 second between
        checks, with a 5-second backoff on errors.
        """
        while self.is_watching:
            try:
                current_hash = self._get_file_hash()

                if self.last_hash is None:
                    self.last_hash = current_hash
                elif current_hash != self.last_hash:
                    # File changed - handle update
                    self._handle_change()
                    self.last_hash = current_hash

                time.sleep(1)
            except Exception as e:
                time.sleep(5)

    def _get_file_hash(self) -> str:
        """
        Calculate the MD5 hash of the current file content.

        Returns
        -------
        str
            Hexadecimal MD5 hash string of the file's binary content.
        """
        with open(self.file_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def _handle_change(self):
        """
        Handle a detected file change event.

        Attempts to recreate the module from the updated file and invokes
        the on_change callback if provided. Errors during recreation are
        silently ignored to maintain watcher stability.
        """
        try:
            # Recreate module
            new_module = self.module.create_module(self.file_path)

            # Call change callback
            if self.on_change:
                self.on_change(new_module)

        except Exception as e:
            pass


# =============================================================================
# FILE HANDLERS - Registered format processors
# =============================================================================

# Create main module instance
main_module = FileModule(use_states=True, cache_size=3000, auto_link=True)


@main_module.register_handler(
    ["json", "jsonl"],
    states=[ModuleState.UNLOADED, ModuleState.LOADED, ModuleState.LINKED],
)
def load_json(file_path: str, module: FileModule) -> Any:
    """
    JSON file handler with intelligent processing and analysis.

    Loads and parses JSON format files, performing structural analysis
    and enhancing the result with statistics metadata. Supports both
    standard JSON and JSON Lines (JSONL) formats.

    Parameters
    ----------
    file_path : str
        Path to the JSON file to load. Must be a valid JSON or JSONL file.
    module : FileModule
        The FileModule instance managing this load operation, providing
        access to data processing and analysis capabilities.

    Returns
    -------
    Any
        Parsed JSON data as a Python dictionary, enhanced with a '__stats__'
        key containing analysis results including patterns, issues, and
        optimization suggestions.

    Raises
    ------
    TypeError
        If the loaded JSON data is not a dictionary object. This handler
        expects the root element to be a dict for metadata enhancement.

    Examples
    --------
    >>> data = load_json("config.json", file_module)
    >>> print(data["__stats__"]["quality_score"])
    1.0
    >>> print(data["database"]["host"])
    'localhost'
    """
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Process data
    analysis = module.processor.analyze(data)
    if isinstance(data, dict):
        data["__stats__"] = analysis
    else:
        raise TypeError(
            f"Expected load file JSON to be dict, got '<{type(data).__name__}>'"
        )

    return data


@main_module.register_handler(
    ["csv", "tsv"], states=[ModuleState.LOADED, ModuleState.ACTIVE]
)
def load_csv(file_path: str, module: FileModule) -> Any:
    """
    CSV/TSV file handler with intelligent structure detection.

    Analyzes CSV files to detect delimiters, header presence, and structural
    characteristics. Adapts the parsing strategy based on detected format
    to produce either dictionary-based or list-based results.

    Parameters
    ----------
    file_path : str
        Path to the CSV or TSV file to load.
    module : FileModule
        The FileModule instance managing this load operation.

    Returns
    -------
    Dict[str, Any]
        Dictionary containing:
        - headers : List[str] or None
            Column headers if detected, None otherwise.
        - rows : List[Union[Dict, List]]
            Data rows. If headers exist, each row is a dict mapping header
            to value. Without headers, each row is a list of values.
        - stats : Dict[str, int]
            Statistics including 'row_count' and 'column_count'.
        - structure : str
            Either 'dictionary' (with headers) or 'list' (without headers).

    Examples
    --------
    >>> result = load_csv("users.csv", file_module)
    >>> print(result["headers"])
    ['id', 'name', 'email']
    >>> print(result["stats"]["row_count"])
    42
    >>> first_user = result["rows"][0]
    >>> print(first_user["name"])
    'Alice Smith'
    """
    with open(file_path, "r", encoding="utf-8") as f:
        # Analyze CSV structure
        sample = f.read(4096)
        f.seek(0)

        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(sample)
        has_header = sniffer.has_header(sample)

        if has_header:
            reader = csv.DictReader(f, dialect=dialect)
            rows = list(reader)

            result = {
                "headers": reader.fieldnames,
                "rows": rows,
                "stats": {
                    "row_count": len(rows),
                    "column_count": len(reader.fieldnames) if reader.fieldnames else 0,
                },
                "structure": "dictionary",
            }
        else:
            reader = csv.reader(f, dialect=dialect)
            rows = list(reader)

            result = {
                "headers": None,
                "rows": rows,
                "stats": {
                    "row_count": len(rows),
                    "column_count": len(rows[0]) if rows else 0,
                },
                "structure": "list",
            }

    return result


@main_module.register_handler(
    ["yaml", "yml"], states=[ModuleState.UNLOADED, ModuleState.LINKED]
)
def load_yaml(file_path: str, module: FileModule) -> Any:
    """
    YAML file handler with safe loading.

    Loads YAML format files using PyYAML's safe loader to prevent code
    execution vulnerabilities. Requires PyYAML to be installed.

    Parameters
    ----------
    file_path : str
        Path to the YAML file to load.
    module : FileModule
        The FileModule instance managing this load operation.

    Returns
    -------
    Any
        Parsed YAML data structure, typically a dictionary or list.

    Raises
    ------
    ImportError
        If PyYAML is not installed. The error message includes installation
        instructions.

    Examples
    --------
    >>> data = load_yaml("config.yml", file_module)
    >>> print(data["application"]["name"])
    'MyApp'
    """
    try:
        import yaml
    except ImportError:
        raise ImportError("PyYAML required: pip install PyYAML")

    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data


@main_module.register_handler(
    ["xml"], states=[ModuleState.LOADED, ModuleState.OPTIMIZED]
)
def load_xml(file_path: str, module: FileModule) -> Any:
    """
    XML file handler with namespace support and hierarchical parsing.

    Parses XML documents into nested dictionary structures that preserve
    element hierarchy, attributes, and text content. Handles repeated
    child elements by grouping them into lists automatically.

    Parameters
    ----------
    file_path : str
        Path to the XML file to load.
    module : FileModule
        The FileModule instance managing this load operation.

    Returns
    -------
    Dict[str, Any]
        Dictionary representation of the XML document with structure:
        - _tag : str
            Element tag name.
        - _attrs : Dict[str, str]
            Element attributes.
        - _text : str, optional
            Text content if present.
        - [child_tags] : Union[Dict, List[Dict]]
            Child elements, single or list based on count.
        - _metadata : Dict[str, str]
            Additional metadata including root element name and structure type.

    Examples
    --------
    >>> data = load_xml("users.xml", file_module)
    >>> print(data["_tag"])
    'users'
    >>> print(data["_metadata"]["structure"])
    'hierarchical'
    >>> first_user = data["user"][0]
    >>> print(first_user["name"]["_text"])
    'Alice'
    """
    tree = ET.parse(file_path)
    root = tree.getroot()

    def parse_element(element, depth=0):
        """
        Recursively parse an XML element to a dictionary representation.

        Parameters
        ----------
        element : xml.etree.ElementTree.Element
            The XML element to parse.
        depth : int, optional
            Current recursion depth to prevent infinite loops. Default is 0.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation of the element and its descendants.
        """
        if depth > 20:
            return {"_text": element.text.strip() if element.text else None}

        result = {
            "_tag": element.tag,
            "_attrs": dict(element.attrib),
        }

        # Process children
        children_by_tag = defaultdict(list)
        for child in element:
            child_data = parse_element(child, depth + 1)
            children_by_tag[child.tag].append(child_data)

        # Add children
        for tag, children in children_by_tag.items():
            if len(children) == 1:
                result[tag] = children[0]
            else:
                result[tag] = children

        # Add text
        if element.text and element.text.strip():
            result["_text"] = element.text.strip()

        return result

    data = parse_element(root)
    data["_metadata"] = {"root": root.tag, "structure": "hierarchical"}

    return data


@main_module.register_handler(["ini", "cfg"], states=[ModuleState.LOADED])
def load_ini(file_path: str, module: FileModule) -> Any:
    """
    INI configuration file handler.

    Parses INI format configuration files using Python's configparser,
    producing a nested dictionary structure organized by sections.

    Parameters
    ----------
    file_path : str
        Path to the INI or CFG file to load.
    module : FileModule
        The FileModule instance managing this load operation.

    Returns
    -------
    Dict[str, Dict[str, str]]
        Nested dictionary where top-level keys are section names and values
        are dictionaries mapping option names to their string values.

    Examples
    --------
    >>> config = load_ini("app.ini", file_module)
    >>> print(config["database"]["host"])
    'localhost'
    >>> print(config["database"]["port"])
    '5432'
    """
    parser = configparser.ConfigParser()
    parser.read(file_path, encoding="utf-8")

    config = {}
    for section in parser.sections():
        config[section] = dict(parser[section])

    return config


@main_module.register_handler(["txt"], states=[ModuleState.LOADED])
def load_text(file_path: str, module: FileModule) -> Any:
    """
    Plain text file handler with line-aware processing.

    Loads text files and provides both full content and line-by-line
    access with basic statistics.

    Parameters
    ----------
    file_path : str
        Path to the text file to load.
    module : FileModule
        The FileModule instance managing this load operation.

    Returns
    -------
    Dict[str, Any]
        Dictionary containing:
        - content : str
            Complete file contents as a single string.
        - lines : List[str]
            List of individual lines (without newline characters).
        - line_count : int
            Total number of lines in the file.

    Examples
    --------
    >>> text_data = load_text("readme.txt", file_module)
    >>> print(text_data["line_count"])
    15
    >>> first_line = text_data["lines"][0]
    >>> print(first_line)
    'Project Documentation'
    """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    return {
        "content": content,
        "lines": content.splitlines(),
        "line_count": len(content.splitlines()),
    }


def to_module(file_path: str, **kwargs) -> ModuleType:
    """
    Create a Python module from a data file with advanced features.

    Convenience function that creates a FileModule instance and generates
    a module from the specified file in a single call.

    Parameters
    ----------
    file_path : str
        Path to the source file to convert into a module.
    **kwargs : dict
        Additional keyword arguments passed to FileModule constructor.
        See FileModule.__init__ for available options including:
        - use_states : bool
            Enable state-based lazy loading.
        - cache_size : int
            Maximum cached modules.
        - auto_link : bool
            Enable automatic file linking.

    Returns
    -------
    ModuleType
        Dynamic Python module with file data as attributes and methods.

    Examples
    --------
    >>> config = to_module('settings.json', use_states=True)
    >>> print(config.database.host.load())
    'localhost'
    """
    module = FileModule(**kwargs)
    return module.create_module(file_path)


async def to_modules(file_paths: List[str], **kwargs) -> List[ModuleType]:
    """
    Create modules from multiple files concurrently.

    Convenience async function for batch processing multiple files into
    modules with concurrency control.

    Parameters
    ----------
    file_paths : List[str]
        List of file paths to convert into modules.
    **kwargs : dict
        Additional keyword arguments passed to FileModule constructor.
        See FileModule.__init__ for available options.

    Returns
    -------
    List[ModuleType]
        List of created modules in the same order as input paths.

    Examples
    --------
    >>> modules = await to_modules(['file1.json', 'file2.yaml'])
    >>> for module in modules:
    ...     print(module.get_state())
    """
    module = FileModule(**kwargs)
    return await module.create_many(file_paths)


@contextmanager
def watch_module(file_path: str, **kwargs):
    """
    Context manager for watching a file with automatic module updates.

    Creates a monitored environment where the module automatically reloads
    when the source file changes. The context yields the current module
    and handles cleanup of the watcher on exit.

    Parameters
    ----------
    file_path : str
        Path to the file to watch and convert to a module.
    **kwargs : dict
        Additional keyword arguments passed to FileModule constructor.

    Yields
    ------
    ModuleType
        The created module with live update capability. The module will
        automatically refresh when the source file changes.

    Examples
    --------
    >>> with watch_module('data.json') as data:
    ...     print(data.load_data())
    ...     # Module auto-updates on file changes
    ...     time.sleep(10)
    ...     print(data.load_data())  # Reflects any changes
    """
    module = FileModule(**kwargs)
    watcher = module.watch_file(file_path)

    try:
        module = module.create_module(file_path)
        yield module
    finally:
        watcher.stop()


def _check_level(level: str) -> str:
    """
    Validate and normalize the directory scan level parameter.

    Ensures the provided level string matches one of the supported
    scanning modes.

    Parameters
    ----------
    level : str
        Scan level to validate. Expected values are 'local' or 'global'.

    Returns
    -------
    str
        Normalized lowercase level string if valid.

    Raises
    ------
    ValueError
        If the level string is not 'local' or 'global'. The error message
        includes the invalid value received.
    """
    levels = ["local", "global"]
    level = level.strip().lower()
    msg = f"Expected level is 'local' or 'global' but '{level}' was obtained"

    if not level in levels:
        raise ValueError(msg)
    return level


def scan_dir(
    directory: str,
    pattern: str = "*",
    stderr: bool = False,
    level: str = "local",
    max_workers: int = 8,
    **kwargs,
) -> Union[Dict[str, object], Tuple[Dict[str, object], List[str]]]:
    """
    Scan a directory and load all supported data files as modules.

    Recursively or locally scans a directory for files matching the given
    pattern, processing each supported file format into a Python module.
    Uses concurrent processing for efficiency with large directories.

    Parameters
    ----------
    directory : str
        Path to the directory to scan.
    pattern : str, optional
        File glob pattern to filter files. Default is "*" (all files).
    stderr : bool, optional
        If True, returns a tuple containing both valid modules and a list
        of invalid file stems. If False, returns only valid modules.
        Default is False.
    level : str, optional
        Scan depth: 'local' uses glob (non-recursive), 'global' uses rglob
        (recursive). Default is 'local'.
    max_workers : int, optional
        Maximum number of concurrent threads for processing files.
        Default is 8.
    **kwargs : dict
        Additional keyword arguments passed to FileModule constructor.

    Returns
    -------
    Union[Dict[str, object], Tuple[Dict[str, object], List[str]]]
        If stderr is False:
            Dict[str, ModuleType] mapping filenames to module objects.
        If stderr is True:
            Tuple containing (valid_modules_dict, invalid_stems_list).

    Examples
    --------
    >>> modules = scan_dir('/data/configs', pattern='*.json')
    >>> for name, module in modules.items():
    ...     print(f"Loaded {name}")

    >>> valid, invalid = scan_dir('/data', '*.csv', stderr=True, level='global')
    >>> print(f"Successfully loaded: {len(valid)}")
    >>> print(f"Failed to load: {invalid}")
    """
    module = FileModule(**kwargs)
    valid_modules: Dict[str, object] = {}
    invalid_modules: List[str] = []

    level = _check_level(level)
    dirpath = Path(directory)

    # --- Determine scan mode ---
    if level == "local":
        files = list(dirpath.glob(pattern))
    else:
        files = list(dirpath.rglob(pattern))

    # --- Worker function ---
    def process_file(file_path: Path):
        """
        Process a single file into a module.

        Parameters
        ----------
        file_path : Path
            Path object pointing to the file to process.

        Returns
        -------
        Optional[Tuple[str, object]]
            If successful, tuple of (filename, module). If file is not
            supported, returns None. If processing fails, returns
            ('__invalid__', file_stem).
        """
        if not file_path.is_file():
            return None

        ext = file_path.suffix.lower().lstrip(".")
        if ext not in FileModule._handlers:
            return None

        try:
            mod = module.create_module(str(file_path))
            return (file_path.name, mod)
        except ImportError:
            return ("__invalid__", file_path.stem)

    # --- Thread Pool Executor ---
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_file, fp): fp for fp in files}

        for future in as_completed(futures):
            result = future.result()
            if not result:
                continue

            key, value = result

            if key == "__invalid__":
                invalid_modules.append(value)
            else:
                valid_modules[key] = value

    # --- Return mode ---
    if stderr:
        return (valid_modules, invalid_modules)

    return valid_modules
