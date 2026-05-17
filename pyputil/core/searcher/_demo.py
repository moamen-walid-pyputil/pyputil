#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Enhanced demonstration and testing module.

This module provides a demonstration of the enhanced PyPI search capabilities.
"""

import asyncio
import logging
import json
from typing import Dict, Any

from .searcher import Searcher
from .models import PackageComparison, SearchStatistics, ExportData
from .enums import CacheStrategy


# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def demo():
    """
    Demo for use Searcher.

    Shows various features including single search, batch search,
    package comparison, statistics, and result export.

    Examples
    --------
    >>> asyncio.run(demo())
    """
    print("Enhanced PyPI Search Toolkit Demo")
    print("=" * 60)

    async with Searcher(
        max_concurrent=10,
        cache_ttl=600,
        enable_health_scoring=True,
        enable_metrics=True,
        cache_strategy=CacheStrategy.HYBRID,
    ) as searcher:
        # Single search with details
        print("1. Single Package Search:")
        print("-" * 30)
        query = "requests"
        results = await searcher.search(query, max_results=3, include_details=True)

        if results:
            for i, package in enumerate(results, 1):
                print(f"{i}. {package.name} v{package.version}")
                print(
                    f"   Score: {package.score:.3f}, Health: {package.health_score:.3f}"
                )
                print(
                    f"   Downloads: {package.downloads.total_downloads:,}"
                    if package.downloads
                    else "   Downloads: 0"
                )
                print(f"   Dependencies: {len(package.dependencies)}")
                print(f"   Status: {package.development_status}")
                summary = (
                    package.summary[:100] + "..."
                    if package.summary and len(package.summary) > 100
                    else (package.summary or "No summary")
                )
                print(f"   Summary: {summary}")
                print()
        else:
            print(f"No results found for query: {query}")
            print()

        # Batch search
        print("\n2. Batch Search:")
        print("-" * 30)
        queries = ["requests", "httpx", "aiohttp"]
        batch_results = await searcher.batch_search(queries, max_results=2)

        for query, packages in batch_results.items():
            print(f"'{query}': {len(packages)} results")
            for pkg in packages:
                version = (
                    pkg.version
                    if pkg.version and pkg.version != "unknown"
                    else "unknown"
                )
                print(f"   - {pkg.name} (v{version})")
                if pkg.summary:
                    summary = (
                        pkg.summary[:50] + "..."
                        if len(pkg.summary) > 50
                        else pkg.summary
                    )
                    print(f"     Summary: {summary}")
            print()

        # Package comparison
        print("\n3. Package Comparison:")
        print("-" * 30)
        try:
            comparison = await searcher.compare_packages(["requests", "httpx"])
            print("Health Scores:")
            for name, score in comparison.health_scores.items():
                print(f"  {name}: {score:.3f}")

            print("\nDownloads:")
            for name, downloads in comparison.downloads.items():
                print(f"  {name}: {downloads:,}")

            print("\nLatest Versions:")
            for name, version in comparison.latest_versions.items():
                print(f"  {name}: {version}")

            print("\nRecent Activity (last 90 days):")
            for name, activity in comparison.recent_activity.items():
                print(f"  {name}: {activity} releases")

            print("\nDays Since Last Release:")
            for name, days in comparison.days_since_last_release.items():
                if days is not None:
                    print(f"  {name}: {days} days")
                else:
                    print(f"  {name}: Unknown")
            print()

        except Exception as e:
            print(f"Package comparison failed: {e}")
            print()

        # Statistics
        print("\n4. Search Statistics:")
        print("-" * 30)
        try:
            stats: SearchStatistics = searcher.get_search_statistics()

            print("Performance Metrics:")
            print(f"  Total Searches: {stats.total_searches}")
            print(f"  Successful Searches: {stats.successful_searches}")
            print(f"  Failed Searches: {stats.failed_searches}")
            print(f"  Cache Hits: {stats.cache_hits}")
            print(f"  Cache Hit Rate: {stats.cache_hit_rate:.2%}")
            print(f"  Avg Response Time: {stats.average_response_time:.2f}s")

            if stats.average_request_time is not None:
                print("\nRequest Timing:")
                print(f"  Avg Request Time: {stats.average_request_time:.2f}s")
                print(f"  Min Request Time: {stats.min_request_time:.2f}s")
                print(f"  Max Request Time: {stats.max_request_time:.2f}s")
                print(f"  Total Requests Timed: {stats.total_requests_timed}")

            print("\nCache Information:")
            print(f"  Current Cache Size: {stats.current_cache_size} entries")
            print(f"  Cache Directory: {stats.cache_directory}")
            print(f"  Cache Strategy: {stats.cache_strategy}")

        except Exception as e:
            print(f"Failed to get statistics: {e}")

        # Export Results
        print("\n5. Export Results:")
        print("-" * 30)
        if results:
            try:
                # JSON Export
                json_export: ExportData = await searcher.export_results(
                    results[:2], "json", include_all_fields=False
                )
                print(f"JSON export (first 2 packages):")
                print(f"  Format: {json_export.format}")
                print(f"  Package Count: {json_export.package_count}")
                print(f"  Content Preview ({len(json_export.content)} chars):")
                try:
                    parsed = json.loads(json_export.content)
                    preview = (
                        json.dumps(parsed, indent=2)[:200] + "..."
                        if len(json_export.content) > 200
                        else json_export.content
                    )
                    print(f"  {preview}")
                except:
                    print(f"  {json_export.content[:200]}...")
                print()

                # Text Export
                text_export: ExportData = await searcher.export_results(
                    results[:1], "text"
                )
                print("Text export (first package):")
                print("-" * 40)
                print(text_export.content)
                print("-" * 40)
                print()

                # CSV Export
                csv_export: ExportData = await searcher.export_results(
                    results[:3], "csv"
                )
                print(f"CSV export (first 3 packages):")
                print(f"  Format: {csv_export.format}")
                print(f"  Package Count: {csv_export.package_count}")
                print(f"  Content Preview:")
                lines = csv_export.content.split("\n")
                for i, line in enumerate(lines[:4]):  # Show header + 3 data rows
                    print(f"  {line}")
                if len(lines) > 4:
                    print(f"  ... and {len(lines) - 4} more lines")
                print()

            except Exception as e:
                print(f"Export failed: {e}")
                print()

        # Additional demonstrations
        print("\n6. Additional Features:")
        print("-" * 30)

        # Get package details directly
        print("Direct Package Details:")
        try:
            package_details = await searcher.get_package_details("requests")
            if package_details:
                print(f"  Package: {package_details.name}")
                print(f"  Version: {package_details.version}")
                print(f"  Author: {package_details.author}")
                print(f"  License: {package_details.license}")
                print(f"  Health Score: {package_details.health_score:.3f}")
                if package_details.recent_activity:
                    print(
                        f"  Days Since Last Release: {package_details.recent_activity.days_since_last_release}"
                    )
            else:
                print("  Package not found")
        except Exception as e:
            print(f"  Failed to get package details: {e}")
        print()

        # Clear cache example
        print("\n7. Cache Management:")
        print("-" * 30)
        print("Clearing cache entries older than 300 seconds...")
        searcher.clear_cache(older_than=300, clear_disk=True)
        print("Cache cleared successfully.")

        # Final statistics
        print("\n8. Final Statistics:")
        print("-" * 30)
        final_stats = searcher.get_search_statistics()
        print(f"Total searches performed: {final_stats.total_searches}")
        print(f"Average response time: {final_stats.average_response_time:.2f}s")
        print(f"Cache efficiency: {final_stats.cache_hit_rate:.2%}")

        print("\n" + "=" * 60)
        print("Demo completed successfully!")
        print("=" * 60)


async def quick_test():
    """
    Quick test function for basic functionality verification.

    Returns
    -------
    bool
        True if all tests pass, False otherwise
    """
    print("Quick Functionality Test")
    print("=" * 60)

    test_results = []

    async with Searcher(
        max_concurrent=5,
        cache_ttl=300,
        enable_health_scoring=True,
        enable_metrics=False,
    ) as searcher:

        # Test 1: Basic search
        print("Test 1: Basic package search...")
        try:
            results = await searcher.search(
                "requests", max_results=2, include_details=False
            )
            if results and len(results) > 0:
                test_results.append(
                    ("Basic Search", True, f"Found {len(results)} results")
                )
            else:
                test_results.append(("Basic Search", False, "No results found"))
        except Exception as e:
            test_results.append(("Basic Search", False, f"Error: {e}"))

        # Test 2: Package details
        print("Test 2: Package details retrieval...")
        try:
            package = await searcher.get_package_details("requests")
            if package and package.name == "requests":
                test_results.append(
                    ("Package Details", True, f"Got details for {package.name}")
                )
            else:
                test_results.append(
                    ("Package Details", False, "Package not found or invalid")
                )
        except Exception as e:
            test_results.append(("Package Details", False, f"Error: {e}"))

        # Test 3: Statistics
        print("Test 3: Statistics collection...")
        try:
            stats = searcher.get_search_statistics()
            if isinstance(stats, SearchStatistics):
                test_results.append(
                    (
                        "Statistics",
                        True,
                        f"Got stats with {stats.total_searches} searches",
                    )
                )
            else:
                test_results.append(("Statistics", False, "Invalid stats format"))
        except Exception as e:
            test_results.append(("Statistics", False, f"Error: {e}"))

    # Print test results
    print("\nTest Results:")
    print("-" * 60)
    all_passed = True
    for test_name, passed, message in test_results:
        status = "✓ PASS" if passed else "✗ FAIL"
        all_passed = all_passed and passed
        print(f"{status} - {test_name}: {message}")

    print("\n" + "=" * 60)
    if all_passed:
        print("All tests passed! ✓")
    else:
        print("Some tests failed. ✗")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    # Run the enhanced demo
    try:
        asyncio.run(demo())

        # Uncomment to run quick test after demo
        # print("\n" + "=" * 60)
        # print("Running quick test...")
        # print("=" * 60)
        # asyncio.run(quick_test())

    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user.")
    except Exception as e:
        print(f"\n\nDemo failed with error: {e}")
        import traceback

        traceback.print_exc()
