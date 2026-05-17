#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Python package URL resolver with security and reliability.

This module provides a robust solution for discovering and extracting URLs
associated with Python packages, including GitHub repositories, documentation,
homepages, and more. It works with both installed and non-installed packages.

Features
--------
- Supports installed and non-installed packages/modules
- Multiple resolution strategies with fallbacks
- Extracts: GitHub, GitLab, Documentation, Homepage, PyPI, Source repository
- Uses: importlib.metadata, PyPI JSON API, module introspection
- Smart URL ranking and deduplication
- Works with both distribution names and import/module names
- Comprehensive error handling and timeout management
- Rate limiting and caching support
- URL validation and sanitization

Security Features
----------------
- URL validation to prevent injection attacks
- Timeout controls for network requests
- Input sanitization
- Safe URL parsing and normalization
- No execution of arbitrary code

Examples
--------
>>> resolver = PackageURLResolver()
>>> result = resolver.resolve("requests")
>>> print(result["github"])
https://github.com/psf/requests
>>> print(resolver.best_url("rich"))
https://github.com/Textualize/rich

For more examples, see the example() function below.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict, field
from functools import lru_cache
from typing import Dict, List, Optional, Set, Tuple, Union, Any
from urllib.parse import urlparse, urlunparse
import ssl
from collections import defaultdict
import warnings

# Disable SSL certificate verification warnings (optional, for development)
# import urllib3
# urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# =========================================================
# Exceptions
# =========================================================

class PackageResolutionError(Exception):
    """Raised when package resolution completely fails."""
    pass


class PackageTimeoutError(PackageResolutionError):
    """Raised when network operations timeout."""
    pass


class PackageInvalidURLError(PackageResolutionError):
    """Raised when an invalid URL is encountered."""
    pass


# =========================================================
# Data Model
# =========================================================

@dataclass(slots=True)
class PackageURLs:
    """
    Container for all discovered package URLs.

    This dataclass stores all URLs found for a package, organized by type.
    All fields are optional as not all packages will have every URL type.

    Attributes
    ----------
    name : Optional[str]
        Package name as discovered from metadata
    version : Optional[str]
        Package version if available
    github : Optional[str]
        GitHub repository URL
    gitlab : Optional[str]
        GitLab repository URL
    repository : Optional[str]
        Primary repository URL (GitHub, GitLab, or other)
    homepage : Optional[str]
        Package homepage URL
    documentation : Optional[str]
        Documentation URL (often ReadTheDocs or similar)
    pypi : Optional[str]
        PyPI project page URL
    source : Optional[str]
        Source code repository URL
    bug_tracker : Optional[str]
        Issue tracker URL
    download_url : Optional[str]
        Direct download URL if available
    all_urls : Optional[List[str]]
        List of all discovered URLs (deduplicated)
    confidence : Optional[float]
        Confidence score for the resolution (0.0 to 1.0)
    resolution_time : Optional[float]
        Time taken to resolve in seconds

    Examples
    --------
    >>> urls = PackageURLs(
    ...     name="requests",
    ...     github="https://github.com/psf/requests",
    ...     pypi="https://pypi.org/project/requests/"
    ... )
    >>> print(urls.github)
    https://github.com/psf/requests
    """

    name: Optional[str] = None
    version: Optional[str] = None

    github: Optional[str] = None
    gitlab: Optional[str] = None

    repository: Optional[str] = None
    homepage: Optional[str] = None
    documentation: Optional[str] = None

    pypi: Optional[str] = None

    source: Optional[str] = None
    bug_tracker: Optional[str] = None
    download_url: Optional[str] = None

    all_urls: Optional[List[str]] = field(default_factory=list)
    confidence: Optional[float] = None
    resolution_time: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert PackageURLs to dictionary, excluding None values.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation with None values filtered out

        Examples
        --------
        >>> urls = PackageURLs(github="https://github.com/psf/requests")
        >>> urls.to_dict()
        {'github': 'https://github.com/psf/requests', 'all_urls': []}
        """
        return {k: v for k, v in asdict(self).items() if v is not None}

    def has_any_url(self) -> bool:
        """
        Check if any URLs have been discovered.

        Returns
        -------
        bool
            True if at least one URL is present, False otherwise

        Examples
        --------
        >>> urls = PackageURLs()
        >>> urls.has_any_url()
        False
        >>> urls.github = "https://github.com/psf/requests"
        >>> urls.has_any_url()
        True
        """
        url_fields = ['github', 'gitlab', 'repository', 'homepage', 
                     'documentation', 'pypi', 'source', 'bug_tracker', 
                     'download_url']
        return any(getattr(self, field) for field in url_fields)


# =========================================================
# Main Resolver
# =========================================================

class PackageURLResolver:
    """
    Advanced package URL resolver with multiple resolution strategies.

    This class implements a comprehensive strategy to discover URLs associated
    with Python packages. It attempts multiple resolution methods in a
    prioritized order, falling back to alternatives when necessary.

    Resolution Strategy
    -------------------
    1. Try installed package metadata (fastest, most reliable for installed packages)
    2. Try import/module inspection (for packages that can be imported)
    3. Query PyPI JSON API (most comprehensive, works for any PyPI package)
    4. Normalize and rank URLs based on confidence

    Parameters
    ----------
    timeout : int, optional
        Timeout in seconds for network requests (default: 10)
    user_agent : str, optional
        Custom User-Agent string for HTTP requests
    enable_cache : bool, optional
        Enable caching of resolution results (default: True)
    cache_ttl : int, optional
        Cache time-to-live in seconds (default: 300)
    verify_ssl : bool, optional
        Verify SSL certificates (default: True)
    respect_rate_limits : bool, optional
        Respect PyPI API rate limits (default: True)

    Attributes
    ----------
    cache : Dict[str, Tuple[float, PackageURLs]]
        Internal cache storing (timestamp, result) tuples
    request_count : int
        Number of API requests made in current session

    Examples
    --------
    Create resolver with custom settings:
    
    >>> resolver = PackageURLResolver(timeout=5, enable_cache=True)
    
    Resolve single package:
    
    >>> result = resolver.resolve("requests")
    >>> print(result["github"])
    https://github.com/psf/requests
    
    Get best URL:
    
    >>> best = resolver.best_url("rich")
    >>> print(best)
    https://github.com/Textualize/rich
    
    Batch resolve packages:
    
    >>> packages = ["requests", "numpy", "pandas"]
    >>> results = resolver.resolve_batch(packages)
    >>> for pkg, urls in results.items():
    ...     print(f"{pkg}: {urls.get('github', 'No GitHub')}")
    """

    PYPI_API = "https://pypi.org/pypi/{package}/json"
    PYPI_SIMPLE = "https://pypi.org/simple/{package}/"
    
    URL_PATTERN = re.compile(
        r"https?://[^\s,<>\"'()]+",
        re.IGNORECASE,
    )
    
    # Known URL patterns for classification
    GITHUB_PATTERN = re.compile(r"github\.com/([^/]+)/([^/]+)")
    GITLAB_PATTERN = re.compile(r"gitlab\.com/([^/]+)/([^/]+)")
    READTHEDOCS_PATTERN = re.compile(r"([\w-]+)\.readthedocs\.io")

    def __init__(
        self,
        timeout: int = 10,
        user_agent: Optional[str] = None,
        enable_cache: bool = True,
        cache_ttl: int = 300,
        verify_ssl: bool = True,
        respect_rate_limits: bool = True,
    ):
        """
        Initialize the PackageURLResolver with configuration options.
        """
        self.timeout = timeout
        self.user_agent = user_agent or "PackageURLResolver/2.0 (+https://github.com/example)"
        self.enable_cache = enable_cache
        self.cache_ttl = cache_ttl
        self.verify_ssl = verify_ssl
        self.respect_rate_limits = respect_rate_limits
        
        self.cache: Dict[str, Tuple[float, PackageURLs]] = {}
        self.request_count = 0
        self._last_request_time = 0.0
        self._rate_limit_delay = 0.1  # Minimum 100ms between requests
        
        # Setup SSL context if needed
        if not verify_ssl:
            self._ssl_context = ssl.create_default_context()
            self._ssl_context.check_hostname = False
            self._ssl_context.verify_mode = ssl.CERT_NONE
        else:
            self._ssl_context = None

    def resolve(self, package_name: str, use_cache: bool = True) -> Dict[str, Optional[str]]:
        """
        Resolve package URLs using multiple strategies.

        This method attempts to find URLs for a package using installed metadata,
        module inspection, and PyPI API queries in that order. Results are merged
        with later sources providing additional URLs but not overwriting existing ones.

        Parameters
        ----------
        package_name : str
            Package name OR import/module name (e.g., "requests" or "PIL")
        use_cache : bool, optional
            Whether to use cached results (default: True)

        Returns
        -------
        Dict[str, Optional[str]]
            Dictionary containing discovered URLs with keys: name, version,
            github, gitlab, repository, homepage, documentation, pypi,
            source, bug_tracker, download_url

        Raises
        ------
        PackageResolutionError
            If no URLs could be resolved for the package
        PackageTimeoutError
            If network operations timeout
        ValueError
            If package_name is invalid or empty

        Examples
        --------
        >>> resolver = PackageURLResolver()
        >>> result = resolver.resolve("requests")
        >>> result["name"]
        'requests'
        >>> result["github"]
        'https://github.com/psf/requests'
        
        Resolve with custom timeout:
        
        >>> resolver.timeout = 5
        >>> result = resolver.resolve("fastapi")
        
        Handle resolution failure:
        
        >>> try:
        ...     result = resolver.resolve("nonexistent-package-xyz")
        ... except PackageResolutionError as e:
        ...     print(f"Failed: {e}")
        """
        if not package_name or not isinstance(package_name, str):
            raise ValueError("Package name must be a non-empty string")
        
        package_name = package_name.strip()
        
        # Check cache
        if use_cache and self.enable_cache:
            cached_result = self._get_from_cache(package_name)
            if cached_result:
                return cached_result.to_dict()
        
        start_time = time.time()
        result = PackageURLs()
        
        # Step 1: Try installed package metadata
        metadata_result = self._resolve_from_installed(package_name)
        if metadata_result:
            result = self._merge(result, metadata_result)
            result.confidence = 0.9
        
        # Step 2: Try module inspection
        inspection_result = self._resolve_from_module(package_name)
        if inspection_result:
            result = self._merge(result, inspection_result)
            if result.confidence is None:
                result.confidence = 0.7
        
        # Step 3: Query PyPI API
        try:
            pypi_result = self._resolve_from_pypi(package_name)
            if pypi_result:
                result = self._merge(result, pypi_result)
                if result.confidence is None:
                    result.confidence = 0.95
        except (urllib.error.URLError, TimeoutError) as e:
            warnings.warn(f"PyPI API query failed for {package_name}: {e}", UserWarning)
        
        # Step 4: Try alternative name normalization
        if not result.has_any_url():
            normalized_name = self._normalize_package_name(package_name)
            if normalized_name != package_name:
                try:
                    alt_result = self._resolve_from_pypi(normalized_name)
                    if alt_result and alt_result.has_any_url():
                        result = self._merge(result, alt_result)
                        result.confidence = 0.85
                except Exception:
                    pass
        
        # Final normalization
        self._normalize_urls(result)
        result.resolution_time = time.time() - start_time
        
        # Validate URLs
        result = self._validate_urls(result)
        
        # Check if we found anything
        if not result.has_any_url():
            raise PackageResolutionError(
                f"Could not resolve any URLs for package: {package_name}"
            )
        
        # Cache result
        if self.enable_cache:
            self._add_to_cache(package_name, result)
        
        return result.to_dict()

    def resolve_batch(
        self, 
        package_names: List[str], 
        use_cache: bool = True,
        raise_on_error: bool = False
    ) -> Dict[str, Dict[str, Optional[str]]]:
        """
        Resolve multiple packages in batch.

        Parameters
        ----------
        package_names : List[str]
            List of package names to resolve
        use_cache : bool, optional
            Whether to use cached results (default: True)
        raise_on_error : bool, optional
            If True, raise exception on first error; if False, skip failed packages (default: False)

        Returns
        -------
        Dict[str, Dict[str, Optional[str]]]
            Dictionary mapping package names to their URL dictionaries

        Raises
        ------
        PackageResolutionError
            If raise_on_error is True and a package fails to resolve

        Examples
        --------
        >>> resolver = PackageURLResolver()
        >>> packages = ["requests", "rich", "numpy"]
        >>> results = resolver.resolve_batch(packages)
        >>> for pkg, urls in results.items():
        ...     print(f"{pkg}: {urls.get('github', 'N/A')}")
        
        Skip failed packages:
        
        >>> results = resolver.resolve_batch(["requests", "invalid-pkg"], raise_on_error=False)
        >>> "invalid-pkg" in results
        False
        """
        results = {}
        
        for package_name in package_names:
            try:
                results[package_name] = self.resolve(package_name, use_cache=use_cache)
            except PackageResolutionError as e:
                if raise_on_error:
                    raise
                warnings.warn(f"Skipping {package_name}: {e}", UserWarning)
            except Exception as e:
                if raise_on_error:
                    raise PackageResolutionError(f"Unexpected error for {package_name}: {e}")
                warnings.warn(f"Skipping {package_name}: {e}", UserWarning)
        
        return results

    def best_url(self, package_name: str, prefer_https: bool = True) -> Optional[str]:
        """
        Return the best available URL based on priority ranking.

        Priority order:
        1. GitHub
        2. GitLab
        3. Repository
        4. Homepage
        5. Documentation
        6. PyPI
        7. Source
        8. Download URL

        Parameters
        ----------
        package_name : str
            Package name or import/module name
        prefer_https : bool, optional
            Prefer HTTPS URLs over HTTP (default: True)

        Returns
        -------
        Optional[str]
            Best URL found, or None if no URLs available

        Examples
        --------
        >>> resolver = PackageURLResolver()
        >>> resolver.best_url("requests")
        'https://github.com/psf/requests'
        >>> resolver.best_url("nonexistent-package")
        None
        
        Get best URL with HTTP fallback:
        
        >>> resolver.best_url("some-package", prefer_https=False)
        """
        data = self.resolve(package_name)
        
        priorities = [
            "github", "gitlab", "repository", "homepage",
            "documentation", "pypi", "source", "download_url"
        ]
        
        for key in priorities:
            value = data.get(key)
            if value:
                if prefer_https and value.startswith("http://"):
                    https_version = value.replace("http://", "https://", 1)
                    if self._is_url_reachable(https_version):
                        return https_version
                return value
        
        return None

    def github_url(self, package_name: str) -> Optional[str]:
        """
        Return GitHub repository URL if available.

        Parameters
        ----------
        package_name : str
            Package name or import/module name

        Returns
        -------
        Optional[str]
            GitHub URL or None if not found

        Examples
        --------
        >>> resolver = PackageURLResolver()
        >>> resolver.github_url("requests")
        'https://github.com/psf/requests'
        >>> resolver.github_url("numpy")
        'https://github.com/numpy/numpy'
        """
        return self.resolve(package_name).get("github")

    def pypi_url(self, package_name: str) -> Optional[str]:
        """
        Return PyPI project URL.

        Parameters
        ----------
        package_name : str
            Package name or import/module name

        Returns
        -------
        Optional[str]
            PyPI URL or None if not found

        Examples
        --------
        >>> resolver = PackageURLResolver()
        >>> resolver.pypi_url("requests")
        'https://pypi.org/project/requests/'
        """
        return self.resolve(package_name).get("pypi")

    def get_repo_info(self, package_name: str) -> Optional[Tuple[str, str]]:
        """
        Extract owner and repository name from GitHub/GitLab URL.

        Parameters
        ----------
        package_name : str
            Package name or import/module name

        Returns
        -------
        Optional[Tuple[str, str]]
            Tuple of (owner, repo) or None if not a GitHub/GitLab URL

        Examples
        --------
        >>> resolver = PackageURLResolver()
        >>> owner, repo = resolver.get_repo_info("requests")
        >>> print(f"{owner}/{repo}")
        psf/requests
        """
        github_url = self.github_url(package_name)
        if github_url:
            match = self.GITHUB_PATTERN.search(github_url)
            if match:
                return (match.group(1), match.group(2))
        
        gitlab_url = self.resolve(package_name).get("gitlab")
        if gitlab_url:
            match = self.GITLAB_PATTERN.search(gitlab_url)
            if match:
                return (match.group(1), match.group(2))
        
        return None

    def clear_cache(self) -> None:
        """
        Clear the internal resolution cache.

        Examples
        --------
        >>> resolver = PackageURLResolver()
        >>> resolver.resolve("requests")  # Cached
        >>> resolver.clear_cache()
        >>> resolver.resolve("requests")  # Will query again
        """
        self.cache.clear()
        self.request_count = 0

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the cache.

        Returns
        -------
        Dict[str, Any]
            Dictionary with cache statistics (size, hits, misses)

        Examples
        --------
        >>> resolver = PackageURLResolver()
        >>> resolver.resolve("requests")
        >>> stats = resolver.get_cache_stats()
        >>> print(f"Cache size: {stats['size']}")
        """
        return {
            "size": len(self.cache),
            "enabled": self.enable_cache,
            "ttl": self.cache_ttl,
            "requests_made": self.request_count
        }

    # =====================================================
    # Private Resolution Methods
    # =====================================================

    def _resolve_from_installed(
        self, 
        package_name: str
    ) -> Optional[PackageURLs]:
        """
        Resolve URLs from installed package metadata.

        Parameters
        ----------
        package_name : str
            Package distribution name

        Returns
        -------
        Optional[PackageURLs]
            PackageURLs object with URLs from metadata or None
        """
        try:
            dist = importlib.metadata.distribution(package_name)
        except importlib.metadata.PackageNotFoundError:
            return None

        metadata = dist.metadata
        
        result = PackageURLs(
            name=metadata.get("Name"),
            version=dist.version,
        )
        
        # Extract URLs from metadata
        urls = []
        
        # Home page
        home_page = metadata.get("Home-page") or metadata.get("Homepage")
        if home_page and self._is_valid_url(home_page):
            urls.append(("homepage", home_page))
        
        # Project-URLs
        project_urls = metadata.get_all("Project-URL", [])
        for item in project_urls:
            extracted = self._extract_url(item)
            if extracted and self._is_valid_url(extracted):
                label = item.split(",")[0].strip().lower() if "," in item else "project"
                urls.append((label, extracted))
        
        self._classify_urls(result, urls)
        
        # Always generate PyPI URL if we have a name
        if result.name:
            result.pypi = f"https://pypi.org/project/{result.name}/"
        
        return result

    def _resolve_from_module(
        self, 
        package_name: str
    ) -> Optional[PackageURLs]:
        """
        Resolve URLs by inspecting the imported module.

        Parameters
        ----------
        package_name : str
            Module import name

        Returns
        -------
        Optional[PackageURLs]
            PackageURLs object with URLs from module attributes
        """
        try:
            module = importlib.import_module(package_name)
        except Exception:
            return None
        
        result = PackageURLs()
        
        # Common URL attributes in modules
        url_attributes = [
            ("__url__", "homepage"),
            ("__homepage__", "homepage"),
            ("__github__", "github"),
            ("__docs__", "documentation"),
            ("__documentation__", "documentation"),
            ("__source__", "source"),
        ]
        
        for attr, url_type in url_attributes:
            value = getattr(module, attr, None)
            if isinstance(value, str) and self._is_valid_url(value):
                self._classify_urls(result, [(url_type, value)])
        
        return result

    def _resolve_from_pypi(
        self, 
        package_name: str
    ) -> Optional[PackageURLs]:
        """
        Resolve URLs from PyPI JSON API.

        Parameters
        ----------
        package_name : str
            Package name on PyPI

        Returns
        -------
        Optional[PackageURLs]
            PackageURLs object with URLs from PyPI

        Raises
        ------
        PackageTimeoutError
            If the request times out
        """
        # Rate limiting
        if self.respect_rate_limits:
            time_since_last = time.time() - self._last_request_time
            if time_since_last < self._rate_limit_delay:
                time.sleep(self._rate_limit_delay - time_since_last)
        
        url = self.PYPI_API.format(package=urllib.parse.quote(package_name))
        
        try:
            request = urllib.request.Request(
                url, 
                headers={"User-Agent": self.user_agent}
            )
            
            if self._ssl_context:
                with urllib.request.urlopen(
                    request, 
                    timeout=self.timeout, 
                    context=self._ssl_context
                ) as response:
                    data = json.loads(response.read().decode())
            else:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode())
            
            self.request_count += 1
            self._last_request_time = time.time()
            
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        except urllib.error.URLError as e:
            raise PackageTimeoutError(f"Network error for {package_name}: {e}")
        except TimeoutError as e:
            raise PackageTimeoutError(f"Timeout for {package_name}: {e}")
        except json.JSONDecodeError as e:
            warnings.warn(f"Invalid JSON from PyPI for {package_name}: {e}", UserWarning)
            return None
        
        info = data.get("info", {})
        
        result = PackageURLs(
            name=info.get("name"),
            version=info.get("version"),
            pypi=f"https://pypi.org/project/{package_name}/"
        )
        
        urls = []
        
        # project_urls
        project_urls = info.get("project_urls") or {}
        for key, value in project_urls.items():
            if value and self._is_valid_url(value):
                urls.append((key.lower(), value))
        
        # home_page
        home_page = info.get("home_page")
        if home_page and self._is_valid_url(home_page):
            urls.append(("homepage", home_page))
        
        # download_url
        download_url = info.get("download_url")
        if download_url and self._is_valid_url(download_url):
            result.download_url = download_url
        
        self._classify_urls(result, urls)
        
        return result

    # =====================================================
    # URL Classification and Processing
    # =====================================================

    def _classify_urls(
        self, 
        result: PackageURLs, 
        urls: List[Tuple[str, str]]
    ) -> None:
        """
        Classify URLs into specific categories based on patterns and labels.

        Parameters
        ----------
        result : PackageURLs
            PackageURLs object to update
        urls : List[Tuple[str, str]]
            List of (label, url) tuples to classify
        """
        for label, url in urls:
            if not url:
                continue
            
            result.all_urls.append(url)
            
            lower_url = url.lower()
            lower_label = label.lower()
            
            # GitHub detection
            if "github.com" in lower_url:
                if not result.github:
                    result.github = url
                if not result.repository:
                    result.repository = url
            
            # GitLab detection
            elif "gitlab.com" in lower_url:
                if not result.gitlab:
                    result.gitlab = url
                if not result.repository:
                    result.repository = url
            
            # Documentation detection
            doc_keywords = {"doc", "documentation", "readthedocs", "docs"}
            if any(keyword in lower_label for keyword in doc_keywords):
                if not result.documentation:
                    result.documentation = url
            
            # Bug tracker detection
            bug_keywords = {"bug", "issue", "tracker", "issues"}
            if any(keyword in lower_label for keyword in bug_keywords):
                if not result.bug_tracker:
                    result.bug_tracker = url
            
            # Source code detection
            source_keywords = {"source", "code", "repository", "repo"}
            if any(keyword in lower_label for keyword in source_keywords):
                if not result.source:
                    result.source = url
            
            # Homepage fallback
            if "homepage" in lower_label and not result.homepage:
                result.homepage = url
            elif not result.homepage and any(keyword in lower_label for keyword in {"home", "website"}):
                result.homepage = url

    @staticmethod
    def _extract_url(text: str) -> Optional[str]:
        """
        Extract first URL from arbitrary text.

        Parameters
        ----------
        text : str
            Text potentially containing a URL

        Returns
        -------
        Optional[str]
            Extracted URL or None if not found

        Examples
        --------
        >>> PackageURLResolver._extract_url("Homepage: https://example.com")
        'https://example.com'
        """
        match = re.search(r"https?://[^\s,<>\"'()]+", text, re.IGNORECASE)
        return match.group(0) if match else None

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        """
        Validate URL format.

        Parameters
        ----------
        url : str
            URL to validate

        Returns
        -------
        bool
            True if URL has valid scheme and netloc

        Examples
        --------
        >>> PackageURLResolver._is_valid_url("https://github.com")
        True
        >>> PackageURLResolver._is_valid_url("not-a-url")
        False
        """
        try:
            parsed = urlparse(url)
            return bool(parsed.scheme in {'http', 'https'} and parsed.netloc)
        except Exception:
            return False

    def _is_url_reachable(self, url: str, timeout: float = 3.0) -> bool:
        """
        Check if a URL is reachable (optional, used for HTTPS preference).

        Parameters
        ----------
        url : str
            URL to check
        timeout : float
            Timeout in seconds

        Returns
        -------
        bool
            True if URL is reachable

        Note
        ----
        This is a lightweight check - not used by default to avoid performance impact.
        """
        try:
            request = urllib.request.Request(
                url, 
                method='HEAD',
                headers={"User-Agent": self.user_agent}
            )
            if self._ssl_context:
                with urllib.request.urlopen(request, timeout=timeout, context=self._ssl_context):
                    return True
            else:
                with urllib.request.urlopen(request, timeout=timeout):
                    return True
        except Exception:
            return False

    @staticmethod
    def _normalize_urls(result: PackageURLs) -> None:
        """
        Normalize and deduplicate URLs.

        Parameters
        ----------
        result : PackageURLs
            PackageURLs object to normalize
        """
        if result.all_urls:
            unique = []
            seen = set()
            
            for url in result.all_urls:
                # Normalize URL
                url = url.strip().rstrip('/')
                # Remove trailing slash from path
                if url.endswith('/') and not url.endswith('//'):
                    url = url[:-1]
                
                if url not in seen:
                    seen.add(url)
                    unique.append(url)
            
            result.all_urls = unique

    def _validate_urls(self, result: PackageURLs) -> PackageURLs:
        """
        Validate and sanitize all URLs in the result.

        Parameters
        ----------
        result : PackageURLs
            PackageURLs object to validate

        Returns
        -------
        PackageURLs
            Validated PackageURLs object
        """
        for field_name in ['github', 'gitlab', 'repository', 'homepage', 
                          'documentation', 'pypi', 'source', 'bug_tracker', 
                          'download_url']:
            url = getattr(result, field_name)
            if url and not self._is_valid_url(url):
                setattr(result, field_name, None)
        
        return result

    @staticmethod
    def _normalize_package_name(name: str) -> str:
        """
        Normalize package name for PyPI queries.

        Parameters
        ----------
        name : str
            Package name to normalize

        Returns
        -------
        str
            Normalized package name
        """
        # Convert to lowercase and replace underscores/dots with hyphens
        normalized = name.lower().replace('_', '-').replace('.', '-')
        return normalized

    @staticmethod
    def _merge(original: PackageURLs, new: PackageURLs) -> PackageURLs:
        """
        Merge two PackageURLs objects, preferring non-None values.

        Parameters
        ----------
        original : PackageURLs
            Original PackageURLs object
        new : PackageURLs
            New PackageURLs object to merge in

        Returns
        -------
        PackageURLs
            Merged PackageURLs object
        """
        # List of fields to merge
        field_names = ['name', 'version', 'github', 'gitlab', 'repository', 
                      'homepage', 'documentation', 'pypi', 'source', 
                      'bug_tracker', 'download_url']
        
        for field_name in field_names:
            current = getattr(original, field_name)
            incoming = getattr(new, field_name)
            
            if not current and incoming:
                setattr(original, field_name, incoming)
        
        # Merge all_urls lists
        if new.all_urls:
            if original.all_urls is None:
                original.all_urls = []
            original.all_urls.extend(new.all_urls)
        
        # Merge confidence (take higher confidence)
        if new.confidence:
            if original.confidence is None or new.confidence > original.confidence:
                original.confidence = new.confidence
        
        return original

    # =====================================================
    # Cache Management
    # =====================================================

    def _get_from_cache(self, package_name: str) -> Optional[PackageURLs]:
        """
        Retrieve cached resolution result.

        Parameters
        ----------
        package_name : str
            Package name for cache lookup

        Returns
        -------
        Optional[PackageURLs]
            Cached result or None if expired/not found
        """
        if package_name in self.cache:
            timestamp, result = self.cache[package_name]
            if time.time() - timestamp < self.cache_ttl:
                return result
            else:
                del self.cache[package_name]
        return None

    def _add_to_cache(self, package_name: str, result: PackageURLs) -> None:
        """
        Add resolution result to cache.

        Parameters
        ----------
        package_name : str
            Package name for cache key
        result : PackageURLs
            Result to cache
        """
        self.cache[package_name] = (time.time(), result)

    # =====================================================
    # Utility Methods
    # =====================================================

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get resolver statistics.

        Returns
        -------
        Dict[str, Any]
            Dictionary with resolver statistics

        Examples
        --------
        >>> resolver = PackageURLResolver()
        >>> resolver.resolve("requests")
        >>> stats = resolver.get_statistics()
        >>> print(f"Requests made: {stats['total_requests']}")
        """
        return {
            "total_requests": self.request_count,
            "cache_size": len(self.cache),
            "cache_enabled": self.enable_cache,
            "timeout": self.timeout,
            "verify_ssl": self.verify_ssl
        }


# =========================================================
# Convenience Functions
# =========================================================

def quick_resolve(package_name: str, timeout: int = 5) -> Optional[str]:
    """
    Quick resolution returning the best URL.

    This is a convenience function for simple use cases.

    Parameters
    ----------
    package_name : str
        Package name to resolve
    timeout : int, optional
        Timeout in seconds (default: 5)

    Returns
    -------
    Optional[str]
        Best URL found or None

    Examples
    --------
    >>> url = quick_resolve("requests")
    >>> print(url)
    https://github.com/psf/requests
    >>> url = quick_resolve("nonexistent-package")
    >>> print(url)
    None
    """
    try:
        resolver = PackageURLResolver(timeout=timeout)
        return resolver.best_url(package_name)
    except PackageResolutionError:
        return None


def get_multiple_urls(package_names: List[str], **resolver_kwargs) -> Dict[str, Optional[str]]:
    """
    Get best URLs for multiple packages.

    Parameters
    ----------
    package_names : List[str]
        List of package names
    **resolver_kwargs
        Additional arguments passed to PackageURLResolver

    Returns
    -------
    Dict[str, Optional[str]]
        Dictionary mapping package names to their best URL

    Examples
    --------
    >>> urls = get_multiple_urls(["requests", "numpy", "pandas"])
    >>> for pkg, url in urls.items():
    ...     print(f"{pkg}: {url}")
    """
    resolver = PackageURLResolver(**resolver_kwargs)
    results = resolver.resolve_batch(package_names, raise_on_error=False)
    return {pkg: data.get('github') or data.get('repository') for pkg, data in results.items()}


def example() -> None:
    """
    Demonstrate the usage of PackageURLResolver with various examples.

    This function shows common usage patterns and edge cases.

    Examples
    --------
    >>> example()  # Run demonstration
    """
    print("=" * 70)
    print("Package URL Resolver Examples")
    print("=" * 70)
    
    resolver = PackageURLResolver(timeout=5, enable_cache=True)
    
    # Example 1: Basic resolution
    print("\n1. Basic Resolution")
    print("-" * 40)
    packages = ["requests", "rich", "fastapi"]
    
    for package in packages:
        try:
            urls = resolver.resolve(package)
            print(f"\n{package}:")
            print(f"  GitHub: {urls.get('github', 'N/A')}")
            print(f"  Docs: {urls.get('documentation', 'N/A')}")
        except PackageResolutionError as e:
            print(f"  Error: {e}")
    
    # Example 2: Best URL selection
    print("\n2. Best URL Selection")
    print("-" * 40)
    for package in ["numpy", "pandas", "flask"]:
        best = resolver.best_url(package)
        print(f"{package:10} -> {best}")
    
    # Example 3: Batch resolution
    print("\n3. Batch Resolution")
    print("-" * 40)
    batch = ["click", "colorama", "tqdm"]
    results = resolver.resolve_batch(batch)
    for pkg, urls in results.items():
        print(f"{pkg:10} GitHub: {urls.get('github', 'N/A')}")
    
    # Example 4: Cache statistics
    print("\n4. Cache Statistics")
    print("-" * 40)
    stats = resolver.get_cache_stats()
    print(f"Cache enabled: {stats['enabled']}")
    print(f"Cache size: {stats['size']}")
    print(f"Requests made: {stats['requests_made']}")
    
    # Example 5: Repository info extraction
    print("\n5. Repository Info Extraction")
    print("-" * 40)
    for package in ["requests", "pytest"]:
        repo_info = resolver.get_repo_info(package)
        if repo_info:
            owner, repo = repo_info
            print(f"{package:10} -> {owner}/{repo}")
    
    print("\n" + "=" * 70)


__all__ = [
    # Main resolver class
    'PackageURLResolver',
    
    # Data model class
    'PackageURLs',
    
    # Exception classes
    'PackageResolutionError',
    'PackageTimeoutError',
    'PackageInvalidURLError',
    
    # Convenience functions
    'quick_resolve',
    'get_multiple_urls',
    'example',
]

# =========================================================
# Command-line Interface
# =========================================================

def main() -> None:
    """
    Command-line interface for the package URL resolver.
    
    Usage:
        pyputil-pypiutil <package_name> [--best] [--github] [--pypi]
        pyputil-pypiutil --example
        pyputil-pypiutil --batch package1 package2 package3
    
    Examples:
        pyputil-pypiutil requests
        pyputil-pypiutil rich --best
        pyputil-pypiutil numpy --github
        pyputil-pypiutil --batch requests numpy pandas
        python pyputil-pypiutil --example-resolver
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Python Package URL Resolver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        "packages",
        nargs="*",
        help="Package names to resolve"
    )
    parser.add_argument(
        "--best",
        action="store_true",
        help="Return only the best URL"
    )
    parser.add_argument(
        "--github",
        action="store_true",
        help="Return only the GitHub URL"
    )
    parser.add_argument(
        "--pypi",
        action="store_true",
        help="Return only the PyPI URL"
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Treat remaining arguments as batch of packages"
    )
    parser.add_argument(
        "--example-resolver",
        action="store_true",
        help="Run example demonstrations"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Timeout in seconds (default: 10)"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable caching"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output"
    )
    
    args = parser.parse_args()
    
    if args.example_resolver:
        example()
        sys.exit(0)
    
    if not args.packages:
        parser.print_help()
        sys.exit(1)
    
    resolver = PackageURLResolver(
        timeout=args.timeout,
        enable_cache=not args.no_cache
    )
    
    if args.batch:
        results = resolver.resolve_batch(args.packages)
        for pkg, urls in results.items():
            if args.best:
                best = resolver.best_url(pkg)
                print(f"{pkg}: {best}")
            elif args.github:
                print(f"{pkg}: {urls.get('github', 'N/A')}")
            elif args.pypi:
                print(f"{pkg}: {urls.get('pypi', 'N/A')}")
            else:
                print(f"\n{pkg}:")
                for key, value in urls.items():
                    if value and not key.startswith('_'):  # Skip private attributes
                        print(f"  {key:12}: {value}")
    else:
        for package in args.packages:
            if args.best:
                result = resolver.best_url(package)
                print(result if result else "Not found")
            elif args.github:
                result = resolver.github_url(package)
                print(result if result else "Not found")
            elif args.pypi:
                result = resolver.pypi_url(package)
                print(result if result else "Not found")
            else:
                try:
                    result = resolver.resolve(package)
                    print(f"\n{package}:")
                    for key, value in result.items():
                        if value:
                            print(f"  {key:12}: {value}")
                    if args.verbose and resolver.get_cache_stats()['size'] > 0:
                        stats = resolver.get_cache_stats()
                        print(f"\n  Cache size: {stats['size']}")
                        print(f"  Requests: {stats['requests_made']}")
                except PackageResolutionError as e:
                    print(f"{package}: Error - {e}")

if __name__ == "__main__":
	main()