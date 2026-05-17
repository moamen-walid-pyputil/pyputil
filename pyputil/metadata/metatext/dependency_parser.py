#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Parser for dependency information.

Classes
-------
DependencyParser
    Parser for extracting and analyzing dependencies.
"""

import re
from typing import Dict, List, Tuple, Optional, DefaultDict, Any
from collections import defaultdict


class DependencyParser:
    """Parser for dependency information with extras support."""

    # Regex patterns for parsing dependencies
    _EXTRA_PATTERN = re.compile(r';\s*extra\s*==\s*[\'"]?(.+?)[\'"]?\s*$')
    _VERSION_PATTERN = re.compile(r"([<>!=~]+)\s*([^,]+)")
    _ENV_MARKER_PATTERN = re.compile(r";\s*(.+)$")

    @staticmethod
    def parse_deps(lines: List[str]) -> Dict[str, List[str]]:
        """
        Parse dependencies from Requires-Dist lines.

        Parameters
        ----------
        lines : List[str]
            List of Requires-Dist lines

        Returns
        -------
        Dict[str, List[str]]
            Dependencies grouped by type and extras
        """
        result = {"required": [], "optional": defaultdict(list), "conditional": []}

        for line in lines:
            if not line.startswith("Requires-Dist:"):
                continue

            dep_line = line.split(":", 1)[1].strip()

            # Check for extra requirements
            extra_match = DependencyParser._EXTRA_PATTERN.search(dep_line)

            if extra_match:
                # Optional dependency with extra
                extra = extra_match.group(1).strip()
                dep = (
                    DependencyParser._EXTRA_PATTERN.sub("", dep_line)
                    .strip()
                    .rstrip(";")
                )
                result["optional"][extra].append(dep)
            elif ";" in dep_line:
                # Conditional dependency
                result["conditional"].append(dep_line)
            else:
                # Required dependency
                result["required"].append(dep_line)

        result["optional"] = dict(result["optional"])
        return result

    @staticmethod
    def parse_dependency_string(dep_string: str) -> Dict[str, str]:
        """
        Parse individual dependency string into components.

        Parameters
        ----------
        dep_string : str
            Dependency specification string

        Returns
        -------
        Dict[str, str]
            Parsed dependency components
        """
        result = {"name": "", "version_spec": "", "markers": "", "extra": ""}

        # Remove whitespace
        dep_string = dep_string.strip()

        # Extract name (everything before first version specifier or marker)
        name_end = len(dep_string)

        # Find version specifiers
        version_match = DependencyParser._VERSION_PATTERN.search(dep_string)
        if version_match:
            name_end = version_match.start()

        # Find environment markers
        marker_match = DependencyParser._ENV_MARKER_PATTERN.search(dep_string)
        if marker_match:
            name_end = min(name_end, marker_match.start())
            result["markers"] = marker_match.group(1).strip()

        result["name"] = dep_string[:name_end].strip()

        # Extract version specification
        if version_match:
            result["version_spec"] = f"{version_match.group(1)}{version_match.group(2)}"

        # Extract extra from markers
        if "extra" in result["markers"].lower():
            extra_match = re.search(
                r'extra\s*==\s*[\'"]?(.+?)[\'"]?', result["markers"]
            )
            if extra_match:
                result["extra"] = extra_match.group(1).strip()

        return result

    @staticmethod
    def analyze_dependencies(deps_info: Dict[str, List[str]]) -> Dict[str, Any]:
        """
        Analyze dependency patterns and statistics.

        Parameters
        ----------
        deps_info : Dict[str, List[str]]
            Dependency information from parse_dependencies

        Returns
        -------
        Dict[str, Any]
            Analysis results
        """
        analysis = {
            "total_required": len(deps_info["required"]),
            "total_optional": sum(len(v) for v in deps_info["optional"].values()),
            "extras_count": len(deps_info["optional"]),
            "conditional_count": len(deps_info["conditional"]),
            "version_specs": defaultdict(int),
            "common_prefixes": defaultdict(int),
        }

        # Analyze all dependencies
        all_deps = (
            deps_info["required"]
            + deps_info["conditional"]
            + [dep for deps in deps_info["optional"].values() for dep in deps]
        )

        for dep in all_deps:
            # Count version specifiers
            if ">=" in dep:
                analysis["version_specs"][">="] += 1
            elif "<=" in dep:
                analysis["version_specs"]["<="] += 1
            elif "==" in dep:
                analysis["version_specs"]["=="] += 1
            elif "~=" in dep:
                analysis["version_specs"]["~="] += 1
            elif "!=" in dep:
                analysis["version_specs"]["!="] += 1
            elif "<" in dep:
                analysis["version_specs"]["<"] += 1
            elif ">" in dep:
                analysis["version_specs"][">"] += 1

            # Check for common prefixes
            if dep.startswith("django-"):
                analysis["common_prefixes"]["django"] += 1
            elif dep.startswith("flask-"):
                analysis["common_prefixes"]["flask"] += 1
            elif dep.startswith("requests"):
                analysis["common_prefixes"]["requests"] += 1
            elif dep.startswith("numpy"):
                analysis["common_prefixes"]["numpy"] += 1
            elif dep.startswith("pandas"):
                analysis["common_prefixes"]["pandas"] += 1

        return analysis

    @staticmethod
    def filter_deps(
        deps_info: Dict[str, List[str]], pattern: str = None, extra: str = None
    ) -> List[str]:
        """
        Filter dependencies by pattern and/or extra.

        Parameters
        ----------
        deps_info : Dict[str, List[str]]
            Dependency information
        pattern : str, optional
            Pattern to search for in dependency names
        extra : str, optional
            Filter by extra requirement

        Returns
        -------
        List[str]
            Filtered dependencies
        """
        if extra:
            deps = deps_info["optional"].get(extra, [])
        else:
            deps = (
                deps_info["required"]
                + deps_info["conditional"]
                + [dep for deps in deps_info["optional"].values() for dep in deps]
            )

        if pattern:
            pattern_lower = pattern.lower()
            return [dep for dep in deps if pattern_lower in dep.lower()]

        return deps
