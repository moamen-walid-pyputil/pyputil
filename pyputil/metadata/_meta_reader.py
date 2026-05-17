#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Package metadata reader.

This module reads and parses package metadata from various sources
including PKG-INFO, METADATA, direct_url.json, and other metadata files.
"""

import json
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from ..modules.Detector.exceptions import MetadataReadError
from ..modules.Detector.utils import file_utils, safe_path


@dataclass
class PackageMetadata:
    """Package metadata container."""

    name: str
    "Package name."
    version: Optional[str] = None
    "Package version."
    summary: Optional[str] = None
    "Short package description."
    author: Optional[str] = None
    "Package author."
    author_email: Optional[str] = None
    "Author email."
    license: Optional[str] = None
    "Package license."
    requires_python: Optional[str] = None
    "Python version requirements."
    classifiers: Optional[List[str]] = None
    "PyPI classifiers."
    requires_dist: Optional[List[str]] = None
    "Package dependencies."
    project_urls: Optional[Dict[str, str]] = None
    "Project URLs."
    description: Optional[str] = None
    "Long description."
    description_content_type: Optional[str] = None
    "Description content type."
    installer: Optional[str] = None
    "Installer used (pip, conda, etc.)."
    installed_by: Optional[str] = None
    "Who installed the package."
    installed_time: Optional[str] = None
    "When the package was installed."
    requested: bool = False
    "Whether the package was explicitly requested."
    editable: bool = False
    "Whether it's an editable installation."
    direct_url: Optional[Dict[str, Any]] = None
    "Direct URL information (PEP 610)."
    top_level: Optional[List[str]] = None
    "Top-level modules provided by the package."
    files: Optional[List[str]] = None
    "Files installed by the package."
    raw_metadata: Optional[Dict[str, Any]] = None
    "Raw metadata dictionary."
    metadata_path: Optional[Path] = None
    "Path to metadata file."
    metadata_type: Optional[str] = None
    "Type of metadata (dist-info, egg-info, etc.)."

    def __post_init__(self):
        if self.classifiers is None:
            self.classifiers = []
        if self.requires_dist is None:
            self.requires_dist = []
        if self.project_urls is None:
            self.project_urls = {}
        if self.top_level is None:
            self.top_level = []
        if self.files is None:
            self.files = []
        if self.raw_metadata is None:
            self.raw_metadata = {}


class MetadataReader:
    """Package metadata reader with support for multiple formats."""

    def __init__(self):
        self._cache: Dict[str, PackageMetadata] = {}

    def read_metadata(
        self, package_name: str, package_path: Optional[Path] = None
    ) -> Optional[PackageMetadata]:
        """
        Read package metadata from all possible sources.

        Args:
            package_name: Name of the package.
            package_path: Optional path to the package.

        Returns:
            PackageMetadata object or None if not found.

        Raises:
            MetadataReadError: If metadata reading fails.
        """
        cache_key = f"{package_name}:{package_path}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            metadata = None
            metadata = self._read_from_importlib(package_name)
            if metadata:
                self._cache[cache_key] = metadata
                return metadata
            metadata = self._read_from_pkg_resources(package_name)
            if metadata:
                self._cache[cache_key] = metadata
                return metadata
            if package_path:
                metadata = self._read_from_filesystem(package_name, package_path)
                if metadata:
                    self._cache[cache_key] = metadata
                    return metadata
            metadata = self._search_metadata(package_name)
            if metadata:
                self._cache[cache_key] = metadata
                return metadata
            return None
        except Exception as e:
            raise MetadataReadError(package_name, error=e) from e

    def _read_from_importlib(self, package_name: str) -> Optional[PackageMetadata]:
        """Read metadata using importlib.metadata."""
        try:
            import importlib.metadata as importlib_metadata

            dist = importlib_metadata.distribution(package_name)
            metadata_dict = {}
            if dist.metadata:
                metadata_dict = {
                    "name": dist.metadata.get("Name"),
                    "version": dist.metadata.get("Version"),
                    "summary": dist.metadata.get("Summary"),
                    "author": dist.metadata.get("Author"),
                    "author_email": dist.metadata.get("Author-email"),
                    "license": dist.metadata.get("License"),
                    "requires_python": dist.metadata.get("Requires-Python"),
                    "classifiers": dist.metadata.get_all("Classifier", []),
                    "requires_dist": dist.metadata.get_all("Requires-Dist", []),
                    "description": dist.metadata.get("Description"),
                    "description_content_type": dist.metadata.get(
                        "Description-Content-Type"
                    ),
                }
                project_urls = {}
                for key, value in dist.metadata.items():
                    if key.startswith("Project-URL"):
                        if "," in value:
                            label, url = value.split(",", 1)
                            project_urls[label.strip()] = url.strip()
                metadata_dict["project_urls"] = project_urls
            top_level = []
            files = []
            editable = False
            direct_url = None
            installer = None
            try:
                top_level_content = dist.read_text("top_level.txt")
                if top_level_content:
                    top_level = [
                        line.strip()
                        for line in top_level_content.splitlines()
                        if line.strip()
                    ]
            except FileNotFoundError:
                pass
            try:
                record_content = dist.read_text("RECORD") or dist.read_text(
                    "installed-files.txt"
                )
                if record_content:
                    files = [
                        line.strip()
                        for line in record_content.splitlines()
                        if line.strip()
                    ]
            except FileNotFoundError:
                pass
            try:
                direct_url_content = dist.read_text("direct_url.json")
                if direct_url_content:
                    direct_url = json.loads(direct_url_content)
                    if direct_url and "dir_info" in direct_url:
                        editable = True
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            try:
                installer_content = dist.read_text("INSTALLER")
                if installer_content:
                    installer = installer_content.strip()
            except FileNotFoundError:
                pass
            metadata_path = None
            try:
                if hasattr(dist, "_path"):
                    metadata_path = Path(dist._path)
            except AttributeError:
                pass
            return PackageMetadata(
                name=package_name,
                version=metadata_dict.get("version"),
                summary=metadata_dict.get("summary"),
                author=metadata_dict.get("author"),
                author_email=metadata_dict.get("author_email"),
                license=metadata_dict.get("license"),
                requires_python=metadata_dict.get("requires_python"),
                classifiers=metadata_dict.get("classifiers", []),
                requires_dist=metadata_dict.get("requires_dist", []),
                project_urls=metadata_dict.get("project_urls", {}),
                description=metadata_dict.get("description"),
                description_content_type=metadata_dict.get("description_content_type"),
                installer=installer,
                editable=editable,
                direct_url=direct_url,
                top_level=top_level,
                files=files,
                raw_metadata=metadata_dict,
                metadata_path=metadata_path,
                metadata_type=(
                    "dist-info"
                    if metadata_path and ".dist-info" in str(metadata_path)
                    else "egg-info"
                ),
            )
        except importlib.metadata.PackageNotFoundError:
            return None
        except Exception as e:
            warnings.warn(
                f"Failed to read metadata from importlib for {package_name}: {e}",
                RuntimeWarning,
            )
            return None

    def _read_from_pkg_resources(self, package_name: str) -> Optional[PackageMetadata]:
        """Read metadata using pkg_resources (setuptools)."""
        try:
            import pkg_resources

            dist = pkg_resources.get_distribution(package_name)
            metadata_dict = {
                "name": dist.project_name,
                "version": dist.version,
                "summary": None,
                "author": None,
                "author_email": None,
                "license": None,
                "requires_python": None,
                "classifiers": [],
                "requires_dist": [],
                "project_urls": {},
                "description": None,
                "description_content_type": None,
            }
            if dist.has_metadata("PKG-INFO"):
                pkg_info = dist.get_metadata("PKG-INFO")
                parsed = self._parse_pkg_info(pkg_info)
                metadata_dict.update(parsed)
            editable = dist.location and ".egg-link" in str(dist.location)
            top_level = []
            if hasattr(dist, "_get_metadata"):
                try:
                    top_level_content = dist._get_metadata("top_level.txt")
                    if top_level_content:
                        top_level = [
                            line.strip() for line in top_level_content if line.strip()
                        ]
                except Exception:
                    pass
            files = []
            if hasattr(dist, "get_metadata_lines"):
                try:
                    for line in dist.get_metadata_lines("RECORD"):
                        files.append(line)
                except Exception:
                    pass
            return PackageMetadata(
                name=package_name,
                version=metadata_dict["version"],
                summary=metadata_dict["summary"],
                author=metadata_dict["author"],
                author_email=metadata_dict["author_email"],
                license=metadata_dict["license"],
                requires_python=metadata_dict["requires_python"],
                classifiers=metadata_dict["classifiers"],
                requires_dist=metadata_dict["requires_dist"],
                project_urls=metadata_dict["project_urls"],
                description=metadata_dict["description"],
                description_content_type=metadata_dict["description_content_type"],
                editable=editable,
                top_level=top_level,
                files=files,
                raw_metadata=metadata_dict,
                metadata_path=(
                    Path(dist.location) if hasattr(dist, "location") else None
                ),
                metadata_type="egg" if editable else "dist-info",
            )
        except pkg_resources.DistributionNotFound:
            return None
        except Exception as e:
            warnings.warn(
                f"Failed to read metadata from pkg_resources for {package_name}: {e}",
                RuntimeWarning,
            )
            return None

    def _read_from_filesystem(
        self, package_name: str, package_path: Path
    ) -> Optional[PackageMetadata]:
        """Read metadata from filesystem by searching for metadata files."""
        try:
            metadata_dirs = self._find_metadata_dirs(package_path)
            for metadata_dir in metadata_dirs:
                metadata = self._read_metadata_from_dir(package_name, metadata_dir)
                if metadata:
                    return metadata
            return None
        except Exception as e:
            warnings.warn(
                f"Failed to read metadata from filesystem for {package_name}: {e}",
                RuntimeWarning,
            )
            return None

    def _find_metadata_dirs(self, package_path: Path) -> List[Path]:
        """Find metadata directories near a package path."""
        metadata_dirs = []
        try:
            for parent in [package_path] + list(package_path.parents)[:3]:
                for pattern in ["*.dist-info", "*.egg-info"]:
                    for metadata_dir in parent.glob(pattern):
                        if metadata_dir.is_dir():
                            metadata_dirs.append(metadata_dir)
                if parent.parent.exists():
                    for pattern in ["*.dist-info", "*.egg-info"]:
                        for metadata_dir in parent.parent.glob(pattern):
                            if metadata_dir.is_dir():
                                metadata_dirs.append(metadata_dir)
            unique_dirs = []
            seen = set()
            for dir_path in metadata_dirs:
                resolved = safe_path.resolve(dir_path)
                if resolved and resolved not in seen:
                    seen.add(resolved)
                    unique_dirs.append(resolved)
            return unique_dirs
        except Exception:
            return []

    def _read_metadata_from_dir(
        self, package_name: str, metadata_dir: Path
    ) -> Optional[PackageMetadata]:
        """Read metadata from a metadata directory."""
        try:
            if not self._is_package_metadata(package_name, metadata_dir):
                return None
            metadata_dict = {}
            metadata_file = None
            for filename in ["METADATA", "PKG-INFO"]:
                potential_file = metadata_dir / filename
                if potential_file.exists():
                    metadata_file = potential_file
                    break
            if metadata_file:
                content = file_utils.read_text_safe(metadata_file)
                if content:
                    parsed = self._parse_pkg_info(content)
                    metadata_dict.update(parsed)
            top_level = []
            files = []
            editable = False
            direct_url = None
            installer = None
            top_level_file = metadata_dir / "top_level.txt"
            if top_level_file.exists():
                content = file_utils.read_text_safe(top_level_file)
                if content:
                    top_level = [
                        line.strip() for line in content.splitlines() if line.strip()
                    ]
            for filename in ["RECORD", "installed-files.txt"]:
                record_file = metadata_dir / filename
                if record_file.exists():
                    content = file_utils.read_text_safe(record_file)
                    if content:
                        files = [
                            line.strip()
                            for line in content.splitlines()
                            if line.strip()
                        ]
                    break
            direct_url_file = metadata_dir / "direct_url.json"
            if direct_url_file.exists():
                content = file_utils.read_text_safe(direct_url_file)
                if content:
                    try:
                        direct_url = json.loads(content)
                        if direct_url and "dir_info" in direct_url:
                            editable = True
                    except json.JSONDecodeError:
                        pass
            installer_file = metadata_dir / "INSTALLER"
            if installer_file.exists():
                content = file_utils.read_text_safe(installer_file)
                if content:
                    installer = content.strip()
            metadata_type = "unknown"
            if ".dist-info" in str(metadata_dir):
                metadata_type = "dist-info"
            elif ".egg-info" in str(metadata_dir):
                metadata_type = "egg-info"
            return PackageMetadata(
                name=package_name,
                version=metadata_dict.get("version"),
                summary=metadata_dict.get("summary"),
                author=metadata_dict.get("author"),
                author_email=metadata_dict.get("author_email"),
                license=metadata_dict.get("license"),
                requires_python=metadata_dict.get("requires_python"),
                classifiers=metadata_dict.get("classifiers", []),
                requires_dist=metadata_dict.get("requires_dist", []),
                project_urls=metadata_dict.get("project_urls", {}),
                description=metadata_dict.get("description"),
                description_content_type=metadata_dict.get("description_content_type"),
                installer=installer,
                editable=editable,
                direct_url=direct_url,
                top_level=top_level,
                files=files,
                raw_metadata=metadata_dict,
                metadata_path=metadata_dir,
                metadata_type=metadata_type,
            )
        except Exception:
            return None

    def _is_package_metadata(self, package_name: str, metadata_dir: Path) -> bool:
        """Check if a metadata directory belongs to a package."""
        try:
            dir_name = metadata_dir.name.lower()
            package_name_lower = package_name.lower().replace("-", "_")
            dir_name_no_ext = dir_name.replace(".dist-info", "").replace(
                ".egg-info", ""
            )
            dir_name_no_ext = dir_name_no_ext.replace("-", "_")
            if package_name_lower == dir_name_no_ext:
                return True
            if package_name_lower.replace("_", "-") == dir_name_no_ext.replace(
                "_", "-"
            ):
                return True
            metadata_file = metadata_dir / "METADATA"
            if metadata_file.exists():
                content = file_utils.read_text_safe(metadata_file)
                if content:
                    for line in content.splitlines():
                        if line.lower().startswith("name:"):
                            name_in_metadata = line[5:].strip().lower()
                            if name_in_metadata == package_name_lower:
                                return True
            return False
        except Exception:
            return False

    def _search_metadata(self, package_name: str) -> Optional[PackageMetadata]:
        """Search for metadata in common locations."""
        try:
            import site

            search_paths = []
            try:
                search_paths.extend(site.getsitepackages())
            except AttributeError:
                pass
            try:
                user_site = site.getusersitepackages()
                if user_site:
                    search_paths.append(user_site)
            except AttributeError:
                pass
            for path_str in sys.path:
                if path_str:
                    search_paths.append(path_str)
            unique_paths = []
            seen = set()
            for path_str in search_paths:
                path = Path(path_str)
                resolved = safe_path.resolve(path)
                if resolved and resolved not in seen:
                    seen.add(resolved)
                    unique_paths.append(resolved)
            for search_path in unique_paths:
                if not search_path.exists():
                    continue
                for pattern in ["*.dist-info", "*.egg-info"]:
                    for metadata_dir in search_path.glob(pattern):
                        if metadata_dir.is_dir():
                            metadata = self._read_metadata_from_dir(
                                package_name, metadata_dir
                            )
                            if metadata:
                                return metadata
            return None
        except Exception:
            return None

    def _parse_pkg_info(self, content: str) -> Dict[str, Any]:
        """Parse PKG-INFO/METADATA content."""
        result = {
            "name": None,
            "version": None,
            "summary": None,
            "author": None,
            "author_email": None,
            "license": None,
            "requires_python": None,
            "classifiers": [],
            "requires_dist": [],
            "project_urls": {},
            "description": None,
            "description_content_type": None,
        }
        try:
            msg = BytesParser(policy=policy.default).parsebytes(content.encode("utf-8"))
            result["name"] = msg.get("Name")
            result["version"] = msg.get("Version")
            result["summary"] = msg.get("Summary")
            result["author"] = msg.get("Author")
            result["author_email"] = msg.get("Author-email")
            result["license"] = msg.get("License")
            result["requires_python"] = msg.get("Requires-Python")
            result["description"] = msg.get("Description")
            result["description_content_type"] = msg.get("Description-Content-Type")
            if "Classifier" in msg:
                classifiers = msg.get_all("Classifier")
                if isinstance(classifiers, list):
                    result["classifiers"] = classifiers
                elif classifiers:
                    result["classifiers"] = [classifiers]
            if "Requires-Dist" in msg:
                requires_dist = msg.get_all("Requires-Dist")
                if isinstance(requires_dist, list):
                    result["requires_dist"] = requires_dist
                elif requires_dist:
                    result["requires_dist"] = [requires_dist]
            for key in msg.keys():
                if key.startswith("Project-URL"):
                    value = msg[key]
                    if "," in value:
                        label, url = value.split(",", 1)
                        result["project_urls"][label.strip()] = url.strip()
        except Exception:
            lines = content.splitlines()
            current_key = None
            current_value = []
            for line in lines:
                line = line.rstrip()
                if not line:
                    if current_key and current_value:
                        self._process_pkg_info_line(
                            result, current_key, "\n".join(current_value)
                        )
                    current_key = None
                    current_value = []
                    continue
                if line[0] in " \t" and current_key:
                    current_value.append(line.lstrip())
                else:
                    if current_key and current_value:
                        self._process_pkg_info_line(
                            result, current_key, "\n".join(current_value)
                        )
                    if ": " in line:
                        current_key, value = line.split(": ", 1)
                        current_value = [value]
                    else:
                        current_key = None
                        current_value = []
            if current_key and current_value:
                self._process_pkg_info_line(
                    result, current_key, "\n".join(current_value)
                )
        return result

    def _process_pkg_info_line(self, result: Dict[str, Any], key: str, value: str):
        """Process a single PKG-INFO key-value pair."""
        key_lower = key.lower()
        if key_lower == "name":
            result["name"] = value
        elif key_lower == "version":
            result["version"] = value
        elif key_lower == "summary":
            result["summary"] = value
        elif key_lower == "author":
            result["author"] = value
        elif key_lower == "author-email":
            result["author_email"] = value
        elif key_lower == "license":
            result["license"] = value
        elif key_lower == "requires-python":
            result["requires_python"] = value
        elif key_lower == "classifier":
            if "classifiers" not in result:
                result["classifiers"] = []
            result["classifiers"].append(value)
        elif key_lower == "requires-dist":
            if "requires_dist" not in result:
                result["requires_dist"] = []
            result["requires_dist"].append(value)
        elif key_lower.startswith("project-url"):
            if "project_urls" not in result:
                result["project_urls"] = {}
            if ", " in value:
                label, url = value.split(", ", 1)
                result["project_urls"][label] = url
        elif key_lower == "description":
            result["description"] = value
        elif key_lower == "description-content-type":
            result["description_content_type"] = value

    def clear_cache(self):
        """Clear the metadata cache."""
        self._cache.clear()


metadata_reader = MetadataReader()
