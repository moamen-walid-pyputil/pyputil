#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Data models for the enhanced PyPI search toolkit.

This module defines the data classes used to represent package information
and search metrics.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional
import re
import statistics

from .enums import SearchStrategy


@dataclass
class SearchMetrics:
    """
    Metrics for search performance analysis.

    Attributes
    ----------
    query : str
        The search query string
    strategy_used : SearchStrategy
        The search strategy that was used
    response_time : float
        Response time in seconds
    results_count : int
        Number of results returned
    cache_hit : bool
        Whether the result came from cache
    timestamp : datetime
        Timestamp when the search was performed
    """

    query: str
    strategy_used: SearchStrategy
    response_time: float
    results_count: int
    cache_hit: bool
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class PackageInfo:
    """
    Comprehensive package information with metadata.

    Attributes
    ----------
    name : str
        Canonical package name
    version : str
        Latest stable version
    summary : str
        Brief package description
    description : str
        Detailed package description
    author : str
        Primary author name
    author_email : str
        Author contact email
    maintainer : str
        Current maintainer
    maintainer_email : str
        Maintainer contact email
    home_page : str
        Project homepage URL
    project_url : str
        Main project URL
    license : str
        Software license
    requires_python : str
        Python version requirements
    download_url : str
        Direct download URL
    project_urls : Dict[str, str]
        Additional project URLs
    releases : Dict[str, List[Dict]]
        Version release history
    classifiers : List[str]
        Trove classifiers
    downloads : Dict[str, int]
        Download statistics
    score : float
        Relevance score (0.0-1.0)
    last_updated : str
        Last update timestamp
    health_score : float
        Package health metric (0.0-1.0)
    popularity_rank : int
        Popularity ranking
    dependencies : List[str]
        Required dependencies
    development_status : str
        Development status from classifiers
    keywords : List[str]
        Package keywords
    first_release : str
        Initial release date
    recent_activity : Dict[str, Any]
        Recent release activity
    """

    name: str
    version: str
    summary: str = ""
    description: str = ""
    author: str = ""
    author_email: str = ""
    maintainer: str = ""
    maintainer_email: str = ""
    home_page: str = ""
    project_url: str = ""
    license: str = ""
    requires_python: str = ""
    download_url: str = ""
    project_urls: Dict[str, str] = field(default_factory=dict)
    releases: Dict[str, List[Dict]] = field(default_factory=dict)
    classifiers: List[str] = field(default_factory=list)
    downloads: Dict[str, int] = field(default_factory=dict)
    score: float = 0.0
    last_updated: str = ""
    health_score: float = 0.0
    popularity_rank: int = 0
    dependencies: List[str] = field(default_factory=list)
    development_status: str = ""
    keywords: List[str] = field(default_factory=list)
    first_release: str = ""
    recent_activity: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """
        Initialize derived attributes and validate data.

        This method is automatically called after the dataclass is initialized.
        It calculates health score, extracts development status, and keywords.
        """
        self._calculate_health_score()
        self._extract_development_status()
        self._extract_keywords()

    def _calculate_health_score(self) -> None:
        """
        Calculate comprehensive package health score.

        The health score is calculated based on multiple factors:
        - Release activity consistency (30%)
        - Download volume (25%)
        - Metadata completeness (20%)
        - Python version compatibility (15%)
        - Classifiers and categorization (10%)

        Returns
        -------
        None
            Updates the health_score attribute in place
        """
        scores = []

        # Release activity (30%)
        if self.releases:
            recent_releases = list(self.releases.keys())[-5:]  # Last 5 releases
            if len(recent_releases) >= 2:
                time_intervals = []
                for i in range(1, len(recent_releases)):
                    time_intervals.append(1)  # Placeholder for actual time calculation
                if time_intervals:
                    consistency = 1.0 - (
                        statistics.stdev(time_intervals) / 30
                        if len(time_intervals) > 1
                        else 0
                    )
                    scores.append(consistency * 0.3)

        # Download volume (25%)
        total_downloads = self.downloads.get("total_downloads", 0)
        download_score = min(
            total_downloads / 1000000, 1.0
        )  # Normalize to 1M downloads
        scores.append(download_score * 0.25)

        # Metadata completeness (20%)
        metadata_items = [
            self.summary,
            self.description,
            self.author,
            self.license,
            self.home_page,
            self.requires_python,
        ]
        completeness = sum(1 for item in metadata_items if item) / len(metadata_items)
        scores.append(completeness * 0.2)

        # Python version compatibility (15%)
        py_compat = 1.0 if self.requires_python else 0.5
        scores.append(py_compat * 0.15)

        # Classifiers and categorization (10%)
        classifier_score = min(len(self.classifiers) / 10, 1.0)
        scores.append(classifier_score * 0.1)

        self.health_score = sum(scores)

    def _extract_development_status(self) -> None:
        """
        Extract development status from classifiers.

        Scans the package classifiers for development status information
        and maps it to a standardized string.

        Returns
        -------
        None
            Updates the development_status attribute in place
        """
        status_map = {
            "Development Status :: 1 - Planning": "planning",
            "Development Status :: 2 - Pre-Alpha": "pre-alpha",
            "Development Status :: 3 - Alpha": "alpha",
            "Development Status :: 4 - Beta": "beta",
            "Development Status :: 5 - Production/Stable": "stable",
            "Development Status :: 6 - Mature": "mature",
            "Development Status :: 7 - Inactive": "inactive",
        }

        for classifier in self.classifiers:
            if classifier in status_map:
                self.development_status = status_map[classifier]
                break
        else:
            self.development_status = "unknown"

    def _extract_keywords(self) -> None:
        """
        Extract keywords from summary and classifiers.

        Extracts meaningful keywords from package summary and classifiers,
        filtering out common stop words.

        Returns
        -------
        None
            Updates the keywords attribute in place
        """
        keyword_blacklist = {"for", "and", "the", "with", "using", "from"}

        # Extract from summary
        if self.summary:
            words = re.findall(r"\b[a-z]{3,}\b", self.summary.lower())
            self.keywords.extend([w for w in words if w not in keyword_blacklist][:10])

        # Extract from classifiers
        for classifier in self.classifiers:
            if "::" in classifier:
                parts = [p.strip().lower() for p in classifier.split("::")]
                self.keywords.extend(parts[-1].split() if parts else [])


@dataclass
class SearchStatistics:
    """
    Statistics for search performance and usage.

    Attributes
    ----------
    total_searches : int
        Total number of searches performed
    successful_searches : int
        Number of searches that completed successfully
    failed_searches : int
        Number of searches that failed due to errors
    cache_hits : int
        Number of times cache was used instead of API calls
    cache_hit_rate : float
        Ratio of cache hits to total searches (0.0 to 1.0)
    average_response_time : float
        Average time in seconds for search operations
    current_cache_size : int
        Current number of entries in the memory cache
    cache_directory : str
        Path to the disk cache directory
    cache_strategy : str
        Current cache strategy (MEMORY, DISK, HYBRID)
    average_request_time : Optional[float]
        Average time in seconds for HTTP requests
    min_request_time : Optional[float]
        Minimum time in seconds for any HTTP request
    max_request_time : Optional[float]
        Maximum time in seconds for any HTTP request
    total_requests_timed : int
        Total number of HTTP requests that were timed
    """

    total_searches: int = 0
    successful_searches: int = 0
    failed_searches: int = 0
    cache_hits: int = 0
    cache_hit_rate: float = 0.0
    average_response_time: float = 0.0
    current_cache_size: int = 0
    cache_directory: str = ""
    cache_strategy: str = ""
    average_request_time: Optional[float] = None
    min_request_time: Optional[float] = None
    max_request_time: Optional[float] = None
    total_requests_timed: int = 0


@dataclass
class PackageComparison:
    """
    Comparison data for multiple packages across various metrics.

    Attributes
    ----------
    health_scores : Dict[str, float]
        Dictionary mapping package names to their health scores (0.0 to 1.0)
    downloads : Dict[str, int]
        Dictionary mapping package names to total download counts
    latest_versions : Dict[str, str]
        Dictionary mapping package names to their latest version strings
    dependencies_count : Dict[str, int]
        Dictionary mapping package names to number of dependencies
    development_status : Dict[str, str]
        Dictionary mapping package names to their development status
    recent_activity : Dict[str, int]
        Dictionary mapping package names to number of recent releases (last 90 days)
    days_since_last_release : Dict[str, Optional[int]]
        Dictionary mapping package names to days since last release, None if unknown
    """

    health_scores: Dict[str, float] = field(default_factory=dict)
    downloads: Dict[str, int] = field(default_factory=dict)
    latest_versions: Dict[str, str] = field(default_factory=dict)
    dependencies_count: Dict[str, int] = field(default_factory=dict)
    development_status: Dict[str, str] = field(default_factory=dict)
    recent_activity: Dict[str, int] = field(default_factory=dict)
    days_since_last_release: Dict[str, Optional[int]] = field(default_factory=dict)


@dataclass
class DownloadStats:
    """
    Download statistics for a package.

    Attributes
    ----------
    total_downloads : int
        Total number of downloads across all releases and files
    release_count : int
        Number of releases (versions) available for the package
    file_count : int
        Total number of distribution files across all releases
    recent_downloads : int
        Number of downloads from files uploaded in the last 30 days
    average_downloads_per_release : float
        Average number of downloads per release version
    """

    total_downloads: int = 0
    release_count: int = 0
    file_count: int = 0
    recent_downloads: int = 0
    average_downloads_per_release: float = 0.0

    def get(self, key, default: Any = None) -> Any:
        return getattr(self, key, default)


@dataclass
class RecentActivity:
    """
    Recent activity metrics for a package.

    Attributes
    ----------
    recent_releases : int
        Number of releases uploaded in the last 90 days
    latest_upload : Optional[str]
        ISO format timestamp of the most recent upload, None if no uploads
    days_since_last_release : Optional[int]
        Number of days since the last release, None if no releases
    """

    recent_releases: int = 0
    latest_upload: Optional[str] = None
    days_since_last_release: Optional[int] = None


@dataclass
class ExportData:
    """
    Data structure containing exported search results.

    Attributes
    ----------
    format : str
        Export format identifier ('json', 'csv', or 'text')
    content : str
        The actual exported content as a string
    package_count : int
        Number of packages included in the export
    """

    format: str
    content: str
    package_count: int
