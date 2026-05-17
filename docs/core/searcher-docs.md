# Searcher Documentation

## Overview

Searcher is a comprehensive, production-ready toolkit for searching and analyzing PyPI (Python Package Index) packages. It provides multi-strategy search capabilities, intelligent caching, package health scoring, performance metrics, and various export formats.

## Architecture

The system consists of the following core modules:

| Module | Purpose |
|--------|---------|
| `enums.py` | Search and cache strategy enumerations |
| `models.py` | Data models for packages, metrics, and statistics |
| `searcher.py` | Main `Searcher` class implementing all search functionality |
| `api.py` | High-level convenience functions for simplified usage |

## Installation

```python
from pyputil.core.searcher import Searcher, search_package, search_sync
from pyputil.core.searcher.enums import SearchStrategy, CacheStrategy
from pyputil.core.searcher.models import PackageInfo, PackageComparison, SearchStatistics
```

Core Classes

Searcher

The primary class for PyPI search operations.

Constructor parameters:

Parameter Type Default Description
cache_ttl int 3600 Time-to-live for cache entries in seconds
max_concurrent int 10 Maximum concurrent requests
timeout int 15 Request timeout in seconds
cache_strategy CacheStrategy HYBRID Cache storage strategy
cache_dir Optional[str] ".pypi_cache" Directory for disk cache
requests_per_second int 5 Rate limit for requests
enable_health_scoring bool True Enable package health scoring
enable_metrics bool True Enable performance metrics collection
enable_validation bool True Enable validation of package names and data

Enumerations

SearchStrategy

Value Description
PRIMARY_JSON_API PyPI's JSON API (fastest, most accurate)
SECONDARY_WEB_SCRAPING Web scraping search (comprehensive)
FALLBACK_SIMPLE_INDEX Simple index scanning
DIRECT_PACKAGE_LOOKUP Direct package lookup as last resort
CACHE Return cached results

CacheStrategy

Value Description
MEMORY Store cache only in memory
DISK Store cache only on disk
HYBRID Store cache in both memory and disk

Data Models

PackageInfo

Comprehensive package information with metadata.

Attribute Type Description
name str Canonical package name
version str Latest stable version
summary str Brief package description
description str Detailed package description
author str Primary author name
license str Software license
requires_python str Python version requirements
downloads DownloadStats Download statistics
dependencies List[str] Required dependencies
health_score float Package health metric (0.0-1.0)
score float Relevance score (0.0-1.0)
development_status str Development status (alpha, beta, stable, etc.)
recent_activity RecentActivity Recent release activity
first_release str Initial release date
last_updated str Last update timestamp

SearchStatistics

Statistics for search performance.

Attribute Type Description
total_searches int Total number of searches performed
successful_searches int Number of successful searches
failed_searches int Number of failed searches
cache_hits int Number of cache hits
cache_hit_rate float Ratio of cache hits to total searches
average_response_time float Average time in seconds for search operations
current_cache_size int Current number of memory cache entries
cache_directory str Path to disk cache directory
cache_strategy str Current cache strategy

PackageComparison

Comparison data for multiple packages.

Attribute Type Description
health_scores Dict[str, float] Package names to health scores
downloads Dict[str, int] Package names to total downloads
latest_versions Dict[str, str] Package names to latest versions
dependencies_count Dict[str, int] Package names to dependency counts
development_status Dict[str, str] Package names to development status
recent_activity Dict[str, int] Package names to recent release counts
days_since_last_release Dict[str, Optional[int]] Days since last release

ExportData

Exported search results.

Attribute Type Description
format str Export format (json, csv, text)
content str Exported content as string
package_count int Number of packages in export

Usage Examples

Basic Search

```python
import asyncio
from pyputil.core.searcher import search_package

async def main():
    # Simple search with defaults
    results = await search_package("web framework", max_results=5)
    
    for package in results:
        print(f"{package.name} v{package.version}")
        print(f"   Health: {package.health_score:.2f}")
        print(f"   Downloads: {package.downloads.total_downloads:,}")
        print(f"   Summary: {package.summary[:100]}...")
        print()

asyncio.run(main())
```

Using the Searcher Class

```python
from pyputil.core.searcher import Searcher
from pyputil.core.searcher.enums import CacheStrategy

async def advanced_search():
    async with Searcher(
        max_concurrent=5,
        cache_ttl=7200,  # 2 hours
        cache_strategy=CacheStrategy.HYBRID,
        enable_health_scoring=True,
        enable_metrics=True
    ) as searcher:
        
        # Single search
        results = await searcher.search(
            "asynchronous http client",
            max_results=10,
            include_details=True
        )
        
        return results

results = asyncio.run(advanced_search())
```

Batch Search

```python
async def batch_search_example():
    async with Searcher() as searcher:
        queries = ["requests", "httpx", "aiohttp", "urllib3"]
        
        batch_results = await searcher.batch_search(
            queries,
            max_results=5,
            include_details=True
        )
        
        for query, packages in batch_results.items():
            print(f"\n'{query}' results:")
            for pkg in packages[:3]:
                print(f"  - {pkg.name} (health: {pkg.health_score:.2f})")
        
        return batch_results
```

Package Comparison

```python
async def compare_packages():
    async with Searcher() as searcher:
        comparison = await searcher.compare_packages(
            ["requests", "httpx", "aiohttp"]
        )
        
        print("Health Score Comparison:")
        for name, score in comparison.health_scores.items():
            print(f"  {name}: {score:.3f}")
        
        print("\nDownload Comparison:")
        for name, downloads in comparison.downloads.items():
            print(f"  {name}: {downloads:,}")
        
        print("\nRecent Activity (last 90 days):")
        for name, activity in comparison.recent_activity.items():
            print(f"  {name}: {activity} releases")
        
        return comparison
```

Getting Package Details

```python
async def get_package_details():
    async with Searcher() as searcher:
        package = await searcher.get_package_details("requests")
        
        if package:
            print(f"Name: {package.name}")
            print(f"Version: {package.version}")
            print(f"Author: {package.author}")
            print(f"License: {package.license}")
            print(f"Python Required: {package.requires_python}")
            print(f"Health Score: {package.health_score:.3f}")
            print(f"Development Status: {package.development_status}")
            print(f"Dependencies: {', '.join(package.dependencies)}")
            
            if package.downloads:
                print(f"Total Downloads: {package.downloads.total_downloads:,}")
                print(f"Releases: {package.downloads.release_count}")
            
            if package.recent_activity:
                print(f"Days Since Last Release: {package.recent_activity.days_since_last_release}")
        
        return package
```

Exporting Results

```python
async def export_results():
    async with Searcher() as searcher:
        results = await searcher.search("data science", max_results=5)
        
        # JSON export (full details)
        json_export = await searcher.export_results(
            results, 
            format="json", 
            include_all_fields=True
        )
        print(f"JSON export: {len(json_export.content)} characters")
        
        # CSV export (for spreadsheet analysis)
        csv_export = await searcher.export_results(results, format="csv")
        print(f"CSV export:\n{csv_export.content[:500]}...")
        
        # Text export (human-readable)
        text_export = await searcher.export_results(results, format="text")
        print(f"Text export:\n{text_export.content}")
        
        return json_export, csv_export, text_export
```

Statistics and Metrics

```python
async def get_statistics():
    async with Searcher(enable_metrics=True) as searcher:
        # Perform some searches
        await searcher.search("requests")
        await searcher.search("numpy")
        await searcher.search("pandas")
        
        # Get statistics
        stats = searcher.get_search_statistics()
        
        print("Search Statistics:")
        print(f"  Total Searches: {stats.total_searches}")
        print(f"  Successful: {stats.successful_searches}")
        print(f"  Failed: {stats.failed_searches}")
        print(f"  Cache Hits: {stats.cache_hits}")
        print(f"  Cache Hit Rate: {stats.cache_hit_rate:.2%}")
        print(f"  Avg Response Time: {stats.average_response_time:.2f}s")
        print(f"  Cache Size: {stats.current_cache_size} entries")
        
        if stats.average_request_time:
            print(f"  Avg Request Time: {stats.average_request_time:.2f}s")
            print(f"  Min Request Time: {stats.min_request_time:.2f}s")
            print(f"  Max Request Time: {stats.max_request_time:.2f}s")
        
        return stats
```

Cache Management

```python
async def cache_management():
    async with Searcher(
        cache_strategy=CacheStrategy.HYBRID,
        cache_ttl=3600
    ) as searcher:
        
        # Search (caches results)
        await searcher.search("flask")
        
        # Clear cache older than 10 minutes
        searcher.clear_cache(older_than=600, clear_disk=True)
        
        # Clear all cache
        searcher.clear_cache()
        
        print("Cache cleared successfully")
```

Synchronous Usage

```python
from pyputil.core.searcher import search_sync

# For non-async environments
results = search_sync("web framework", max_results=5)

for package in results:
    print(f"{package.name}: {package.health_score:.2f}")
```

Advanced Search with Custom Strategy

```python
from pyputil.core.searcher import Searcher
from pyputil.core.searcher.enums import SearchStrategy

async def custom_strategy_search():
    async with Searcher() as searcher:
        # Try direct lookup first, then JSON API
        custom_priority = [
            SearchStrategy.DIRECT_PACKAGE_LOOKUP,
            SearchStrategy.PRIMARY_JSON_API,
            SearchStrategy.FALLBACK_SIMPLE_INDEX,
        ]
        
        results = await searcher.search(
            "requests",
            max_results=10,
            strategy_priority=custom_priority,
            min_score_threshold=0.4  # Filter low-relevance results
        )
        
        return results
```

Search Strategy Details

The searcher implements a tiered search approach:

1. DIRECT_PACKAGE_LOOKUP - Checks if the query is an exact package name
2. PRIMARY_JSON_API - Uses PyPI's official JSON API (fastest, most accurate)
3. SECONDARY_WEB_SCRAPING - Falls back to web scraping if JSON API fails
4. FALLBACK_SIMPLE_INDEX - Scans the simple index for matching names

Health Score Calculation

The health score (0.0-1.0) is calculated based on:

Factor Weight Description
Release activity 30% Release frequency and consistency
Download volume 25% Total downloads normalized to 1M
Metadata completeness 20% Presence of summary, description, author, license, etc.
Python compatibility 15% Whether requires_python is specified
Classifiers 10% Number of Trove classifiers

Relevance Score Calculation

The relevance score (0.0-1.0) considers:

· Exact name matches (highest priority)
· Name contains query or vice versa
· Name starts with or ends with query
· Word-based matching in name
· Summary-based matching (lower weight)

Performance Features

Feature Description
Connection Pooling Reuses HTTP connections for efficiency
Rate Limiting Prevents IP blocking with configurable limits
Concurrent Requests Controlled parallelism with semaphores
Compression zlib compression for disk cache
Backoff Retries Exponential backoff for failed requests
DNS Caching 5-minute TTL for DNS lookups

Error Handling

```python
import aiohttp
from pyputil.core.searcher import search_package

async def safe_search():
    try:
        results = await search_package("query", timeout=10)
        return results
    except aiohttp.ClientError as e:
        print(f"Network error: {e}")
        return []
    except asyncio.TimeoutError:
        print("Request timed out")
        return []
    except ValueError as e:
        print(f"Invalid query: {e}")
        return []
```

Requirements

· Python 3.7+
· aiohttp - Async HTTP client
· backoff - Retry logic with exponential backoff
· aiolimiter - Async rate limiting

Install dependencies:

```bash
pip install aiohttp backoff aiolimiter
```

Command Line Demo

The module includes a demonstration script:

```python
from pyputil.core.searcher._demo import demo, quick_test

# Run full demo
asyncio.run(demo())

# Run quick functionality test
asyncio.run(quick_test())
```

Key Features Summary

Feature Description
Multi-strategy search Falls back through multiple search methods
Intelligent caching Memory and disk caching with TTL
Health scoring Comprehensive package health metrics
Batch search Concurrent search for multiple queries
Package comparison Compare multiple packages across metrics
Export formats JSON, CSV, and text export
Rate limiting Prevents IP blocking
Async/await Fully asynchronous API
Metrics collection Performance and usage statistics
Validation Package name and data validation
Low-quality filtering Filters spam and test packages