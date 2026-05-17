#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Main package detection.

This module provides the primary interface for detecting package origins
by combining metadata analysis, path analysis, and environment detection.
"""

import sys
import warnings
import importlib.util
import importlib.metadata
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Set, Union
from dataclasses import dataclass
from enum import Enum
import time

from .exceptions import (
    PackageDetectorError,
    PackageNotFoundError,
    MetadataReadError,
    PathResolutionError,
    ConfidenceCalculationError,
    CircularImportError,
)
from .utils import (
    error_handler,
    safe_path,
    platform_utils,
    file_utils,
    hash_utils,
    ErrorHandler,
    CacheManager,
)
from .constants import (
    PackageOrigin,
    PackageInfo,
    DetectionConfidence,
    PlatformType,
    EnvironmentType,
)
from .platform_detector import platform_detector, PlatformInfo
from .path_analyzer import path_analyzer, PathAnalysis
from .environment import environment_detector, EnvironmentInfo


class DetectionMethod(str, Enum):
    """Methods used for package detection."""

    BUILTIN_CHECK = "builtin_check"
    FROZEN_CHECK = "frozen_check"
    STDLIB_CHECK = "stdlib_check"
    NAMESPACE_CHECK = "namespace_check"
    METADATA_ANALYSIS = "metadata_analysis"
    PATH_ANALYSIS = "path_analysis"
    ENVIRONMENT_ANALYSIS = "environment_analysis"
    SPEC_ANALYSIS = "spec_analysis"
    DIRECT_IMPORT = "direct_import"
    HEURISTICS = "heuristics"


@dataclass
class DetectionResult:
    """Result of package detection with detailed information."""

    origin: PackageOrigin
    """Detected package origin."""

    confidence: DetectionConfidence
    """Confidence level."""

    confidence_score: float
    """Numerical confidence score (0.0 to 1.0)."""

    package_name: str
    """Name of the detected package."""

    methods_used: List[DetectionMethod]
    """Detection methods used."""

    metadata: Optional["PackageMetadata"] = None
    """Package metadata if available."""

    path_analysis: Optional[PathAnalysis] = None
    """Path analysis results if available."""

    spec: Optional[Any] = None
    """Module specification if available."""

    imported_module: Optional[Any] = None
    """Imported module object if imported."""

    errors: List[str] = None
    """Errors encountered during detection."""

    warnings: List[str] = None
    """Warnings generated during detection."""

    additional_info: Dict[str, Any] = None
    """Additional detection information."""

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
        if self.additional_info is None:
            self.additional_info = {}

    def to_package_info(self) -> PackageInfo:
        """Convert to PackageInfo dictionary."""
        return PackageInfo(
            name=self.package_name,
            origin=self.origin,
            confidence=self.confidence,
            confidence_score=self.confidence_score,
            path=self.path_analysis.path if self.path_analysis else None,
            version=self.metadata.version if self.metadata else None,
            installer=self.metadata.installer if self.metadata else None,
            is_editable=self.metadata.editable if self.metadata else False,
            is_namespace=self.origin == PackageOrigin.NAMESPACE,
            is_development=self._is_development(),
            metadata=self.metadata.raw_metadata if self.metadata else None,
            environment_info=self._get_environment_info(),
            detection_methods=[method.value for method in self.methods_used],
        )

    def _is_development(self) -> bool:
        """Determine if package is in development."""
        if self.origin == PackageOrigin.EDITABLE:
            return True

        if self.path_analysis and self.path_analysis.in_development_dir:
            return True

        if self.metadata and self.metadata.editable:
            return True

        return False

    def _get_environment_info(self) -> Dict[str, Any]:
        """Get environment information."""
        env_info = {}

        try:
            env = environment_detector.environment_info
            env_info.update(
                {
                    "environment_type": env.environment_type.value,
                    "is_isolated": env.is_isolated,
                    "python_version": env.python_version,
                    "python_executable": str(env.python_executable),
                }
            )
        except Exception:
            pass

        return env_info


class PackageDetector:
    """Main package detection engine."""

    def __init__(
        self,
        follow_symlinks: bool = True,
        check_metadata: bool = True,
        import_on_demand: bool = False,
        max_import_depth: int = 2,
        cache_results: bool = True,
    ):
        """
        Initialize the package detector.

        Args:
            follow_symlinks: Whether to follow symbolic links.
            check_metadata: Whether to check package metadata.
            import_on_demand: Whether to import modules for analysis.
            max_import_depth: Maximum depth for recursive imports.
            cache_results: Whether to cache detection results.
        """
        self.follow_symlinks = follow_symlinks
        self.check_metadata = check_metadata
        self.import_on_demand = import_on_demand
        self.max_import_depth = max_import_depth
        self.cache_results = cache_results

        # Initialize components
        self._cache = CacheManager(max_size=1000, ttl_seconds=300)
        self._imported_modules: Set[str] = set()
        self._import_stack: List[str] = []

        # Platform and environment info
        self._platform_info = platform_detector.platform_info
        self._environment_info = environment_detector.environment_info

    def detect(
        self, package_name: str, detailed: bool = True
    ) -> Union[PackageOrigin, DetectionResult]:
        """
        Detect the origin of a package.

        Args:
            package_name: Name of the package to detect.
            detailed: Whether to return detailed DetectionResult.

        Returns:
            PackageOrigin if detailed=False, DetectionResult if detailed=True.

        Raises:
            PackageNotFoundError: If package cannot be found.
            PackageDetectorError: If detection fails.
        """
        from ...metadata._meta_reader import MetadataReader

        cache_key = f"detect:{package_name}:{detailed}"
        if self.cache_results and cache_key in self._cache._cache:
            return self._cache.get(cache_key)

        try:
            # Initialize detection result
            methods_used = []
            errors = []
            warnings = []

            # 1. Quick checks (high priority)
            quick_result = self._quick_checks(package_name, methods_used)
            if quick_result:
                result = self._create_result(
                    package_name, quick_result, methods_used, confidence_score=1.0
                )

                if self.cache_results:
                    self._cache.set(cache_key, result)

                return result if detailed else quick_result

            # 2. Get module specification
            spec = self._get_module_spec(package_name, methods_used)
            if not spec:
                raise PackageNotFoundError(package_name)

            # 3. Handle namespace packages
            if self._is_namespace_package(spec, methods_used):
                result = self._create_result(
                    package_name,
                    PackageOrigin.NAMESPACE,
                    methods_used,
                    spec=spec,
                    confidence_score=0.9,
                )

                if self.cache_results:
                    self._cache.set(cache_key, result)

                return result if detailed else PackageOrigin.NAMESPACE

            # 4. Get path from spec
            package_path = self._get_package_path(spec, methods_used)

            # 5. Analyze path
            path_analysis = None
            if package_path:
                try:
                    path_analysis = path_analyzer.analyze(
                        package_path, resolve_symlinks=self.follow_symlinks
                    )
                    methods_used.append(DetectionMethod.PATH_ANALYSIS)
                except Exception as e:
                    errors.append(f"Path analysis failed: {e}")

            # 6. Read metadata
            metadata = None
            if self.check_metadata and package_path:
                try:
                    metadata = MetadataReader.read_metadata(package_name, package_path)
                    if metadata:
                        methods_used.append(DetectionMethod.METADATA_ANALYSIS)
                except Exception as e:
                    errors.append(f"Metadata reading failed: {e}")

            # 7. Import module if requested
            imported_module = None
            if (
                self.import_on_demand
                and len(self._import_stack) < self.max_import_depth
            ):
                try:
                    imported_module = self._import_module(package_name, methods_used)
                except Exception as e:
                    warnings.append(f"Module import failed: {e}")

            # 8. Determine origin with confidence
            origin, confidence_score = self._determine_origin(
                package_name, spec, path_analysis, metadata, methods_used
            )

            # 9. Create result
            result = self._create_result(
                package_name,
                origin,
                methods_used,
                confidence_score=confidence_score,
                metadata=metadata,
                path_analysis=path_analysis,
                spec=spec,
                imported_module=imported_module,
                errors=errors,
                warnings=warnings,
            )

            if self.cache_results:
                self._cache.set(cache_key, result)

            return result if detailed else origin

        except PackageNotFoundError:
            raise
        except Exception as e:
            raise PackageDetectorError(
                f"Failed to detect package '{package_name}'",
                package_name=package_name,
                error=str(e),
            ) from e

    def _quick_checks(
        self, package_name: str, methods_used: List[DetectionMethod]
    ) -> Optional[PackageOrigin]:
        """Perform quick checks for common cases."""

        # 1. Built-in modules
        if package_name in sys.builtin_module_names:
            methods_used.append(DetectionMethod.BUILTIN_CHECK)
            return PackageOrigin.BUILTIN

        # 2. Frozen modules
        if getattr(sys, "frozen", False):
            methods_used.append(DetectionMethod.FROZEN_CHECK)

            # Check if this specific module is frozen
            try:
                if hasattr(sys, "_MEIPASS"):  # PyInstaller
                    return PackageOrigin.FROZEN
            except:
                pass

        # 3. Standard library
        try:
            from pyputil.modules import is_stdlib

            if is_stdlib(package_name):
                methods_used.append(DetectionMethod.STDLIB_CHECK)
                return PackageOrigin.STDLIB
        except ImportError:
            # Fallback: check common stdlib paths
            stdlib_paths = [Path(p) for p in sys.path if "lib/python" in p]
            for stdlib_path in stdlib_paths:
                if (stdlib_path / package_name).exists() or (
                    stdlib_path / f"{package_name}.py"
                ).exists():
                    methods_used.append(DetectionMethod.STDLIB_CHECK)
                    return PackageOrigin.STDLIB

        return None

    def _get_module_spec(
        self, package_name: str, methods_used: List[DetectionMethod]
    ) -> Optional[Any]:
        """Get module specification."""
        try:
            spec = importlib.util.find_spec(package_name)
            if spec:
                methods_used.append(DetectionMethod.SPEC_ANALYSIS)
            return spec
        except (ModuleNotFoundError, ImportError, ValueError) as e:
            return None
        except Exception as e:
            warnings.warn(f"Failed to get spec for {package_name}: {e}", RuntimeWarning)
            return None

    def _is_namespace_package(
        self, spec: Any, methods_used: List[DetectionMethod]
    ) -> bool:
        """Check if package is a namespace package."""
        if spec.origin is None and spec.submodule_search_locations:
            methods_used.append(DetectionMethod.NAMESPACE_CHECK)
            return True

        if spec.origin == "namespace":
            methods_used.append(DetectionMethod.NAMESPACE_CHECK)
            return True

        return False

    def _get_package_path(
        self, spec: Any, methods_used: List[DetectionMethod]
    ) -> Optional[Path]:
        """Get package path from specification."""
        if not spec.origin:
            return None

        try:
            package_path = Path(spec.origin)

            # Handle __init__.py files
            if package_path.name == "__init__.py":
                package_path = package_path.parent

            return package_path
        except Exception:
            return None

    def _import_module(
        self, package_name: str, methods_used: List[DetectionMethod]
    ) -> Optional[Any]:
        """Import module for analysis."""
        # Check for circular imports
        if package_name in self._import_stack:
            raise CircularImportError(package_name, self._import_stack.copy())

        self._import_stack.append(package_name)

        try:
            module = importlib.import_module(package_name)
            self._imported_modules.add(package_name)
            methods_used.append(DetectionMethod.DIRECT_IMPORT)
            return module
        except ImportError as e:
            return None
        except Exception as e:
            warnings.warn(f"Failed to import {package_name}: {e}", RuntimeWarning)
            return None
        finally:
            if self._import_stack:
                self._import_stack.pop()

    def _determine_origin(
        self,
        package_name: str,
        spec: Any,
        path_analysis: Optional[PathAnalysis],
        metadata: Optional["PackageMetadata"],
        methods_used: List[DetectionMethod],
    ) -> Tuple[PackageOrigin, float]:
        """
        Determine package origin with confidence score.

        Returns:
            Tuple of (origin, confidence_score).
        """
        confidence_factors = {}
        origin_candidates = {}

        # 1. Metadata-based detection (high confidence)
        if metadata:
            if metadata.editable:
                origin_candidates[PackageOrigin.EDITABLE] = 0.8
                confidence_factors["metadata_editable"] = 0.8

            if metadata.installer:
                if metadata.installer.lower() == "pip":
                    origin_candidates[PackageOrigin.SITE_PACKAGES] = 0.7
                    confidence_factors["metadata_installer_pip"] = 0.7
                elif metadata.installer.lower() == "conda":
                    origin_candidates[PackageOrigin.CONDA] = 0.8
                    confidence_factors["metadata_installer_conda"] = 0.8

        # 2. Path-based detection
        if path_analysis:
            if path_analysis.suggested_origin:
                suggested = path_analysis.suggested_origin
                current_score = origin_candidates.get(suggested, 0)
                new_score = max(current_score, path_analysis.confidence_score)
                origin_candidates[suggested] = new_score

            # Add path analysis confidence factors
            confidence_factors.update(path_analysis.confidence_factors)

        # 3. Environment-based heuristics
        methods_used.append(DetectionMethod.ENVIRONMENT_ANALYSIS)

        if self._environment_info.environment_type == EnvironmentType.CONDA:
            confidence_factors["environment_conda"] = 0.3
            origin_candidates[PackageOrigin.CONDA] = max(
                origin_candidates.get(PackageOrigin.CONDA, 0), 0.3
            )
        elif self._environment_info.environment_type == EnvironmentType.VENV:
            confidence_factors["environment_venv"] = 0.2

        # 4. Check for editable install via environment
        if path_analysis and path_analysis.resolved_path:
            if environment_detector.is_editable_install(path_analysis.resolved_path):
                origin_candidates[PackageOrigin.EDITABLE] = max(
                    origin_candidates.get(PackageOrigin.EDITABLE, 0), 0.9
                )
                confidence_factors["environment_editable"] = 0.9

        # 5. Heuristics based on path patterns
        methods_used.append(DetectionMethod.HEURISTICS)

        if spec and spec.origin:
            origin_lower = spec.origin.lower()

            if ".whl" in origin_lower:
                origin_candidates[PackageOrigin.WHEEL] = max(
                    origin_candidates.get(PackageOrigin.WHEEL, 0), 0.7
                )
            elif ".egg" in origin_lower:
                origin_candidates[PackageOrigin.EGG] = max(
                    origin_candidates.get(PackageOrigin.EGG, 0), 0.7
                )
            elif "site-packages" in origin_lower:
                if "users" in origin_lower or "appdata" in origin_lower:
                    origin_candidates[PackageOrigin.USER_SITE] = max(
                        origin_candidates.get(PackageOrigin.USER_SITE, 0), 0.6
                    )
                else:
                    origin_candidates[PackageOrigin.SITE_PACKAGES] = max(
                        origin_candidates.get(PackageOrigin.SITE_PACKAGES, 0), 0.6
                    )
            elif "src" in origin_lower or "lib" in origin_lower:
                origin_candidates[PackageOrigin.EDITABLE] = max(
                    origin_candidates.get(PackageOrigin.EDITABLE, 0), 0.5
                )

        # 6. Determine final origin
        if not origin_candidates:
            return PackageOrigin.UNKNOWN, 0.3

        # Pick origin with highest confidence
        best_origin = max(origin_candidates.items(), key=lambda x: x[1])[0]
        confidence_score = origin_candidates[best_origin]

        # Adjust confidence based on factors
        if confidence_factors:
            average_factor = sum(confidence_factors.values()) / len(confidence_factors)
            confidence_score = (confidence_score + average_factor) / 2

        # Cap confidence
        confidence_score = min(max(confidence_score, 0.0), 1.0)

        return best_origin, confidence_score

    def _create_result(
        self,
        package_name: str,
        origin: PackageOrigin,
        methods_used: List[DetectionMethod],
        confidence_score: float = 0.0,
        **kwargs,
    ) -> DetectionResult:
        """Create a DetectionResult object."""
        # Determine confidence level
        if confidence_score >= 0.9:
            confidence = DetectionConfidence.HIGH
        elif confidence_score >= 0.7:
            confidence = DetectionConfidence.MEDIUM
        elif confidence_score >= 0.5:
            confidence = DetectionConfidence.LOW
        else:
            confidence = DetectionConfidence.WEAK

        # Create additional info
        additional_info = {
            "platform": self._platform_info.platform_type.value,
            "environment": self._environment_info.environment_type.value,
            "detection_time": time.time(),
        }

        # Update with any provided additional info
        if "additional_info" in kwargs and kwargs["additional_info"]:
            additional_info.update(kwargs.pop("additional_info"))

        return DetectionResult(
            origin=origin,
            confidence=confidence,
            confidence_score=confidence_score,
            package_name=package_name,
            methods_used=methods_used,
            additional_info=additional_info,
            **kwargs,
        )

    def detect_multiple(
        self, package_names: List[str], detailed: bool = False
    ) -> Dict[str, Union[PackageOrigin, DetectionResult]]:
        """
        Detect origins for multiple packages.

        Args:
            package_names: List of package names.
            detailed: Whether to return detailed results.

        Returns:
            Dictionary mapping package names to detection results.
        """
        results = {}

        for package_name in package_names:
            try:
                result = self.detect(package_name, detailed=detailed)
                results[package_name] = result
            except Exception as e:
                results[package_name] = (
                    PackageOrigin.NOT_FOUND if not detailed else None
                )

        return results

    def clear_cache(self):
        """Clear all caches."""
        self._cache.clear()
        path_analyzer.clear_cache()
        self._imported_modules.clear()
        self._import_stack.clear()

    def get_statistics(self) -> Dict[str, Any]:
        """Get detector statistics."""
        return {
            "cache_size": len(self._cache._cache),
            "imported_modules": len(self._imported_modules),
            "platform": self._platform_info.platform_type.value,
            "environment": self._environment_info.environment_type.value,
            "settings": {
                "follow_symlinks": self.follow_symlinks,
                "check_metadata": self.check_metadata,
                "import_on_demand": self.import_on_demand,
                "max_import_depth": self.max_import_depth,
                "cache_results": self.cache_results,
            },
        }


# Global detector instance with default settings
default_detector = PackageDetector()


def detect_package_origin(
    package: str,
    follow_symlinks: bool = True,
    check_metadata: bool = True,
    detailed: bool = False,
) -> Union[PackageOrigin, DetectionResult]:
    """
    Function to detect package origin.

    Args:
        package: Package name to detect.
        follow_symlinks: Whether to follow symbolic links.
        check_metadata: Whether to check package metadata.
        detailed: Whether to return detailed information.

    Returns:
        PackageOrigin or detailed DetectionResult.

    Examples:
        >>> detect_package_origin("numpy")
        <PackageOrigin.SITE_PACKAGES: 'site-packages'>

        >>> detect_package_origin("mypackage", detailed=True)
        DetectionResult(origin=PackageOrigin.EDITABLE, ...)
    """
    detector = PackageDetector(
        follow_symlinks=follow_symlinks, check_metadata=check_metadata
    )

    return detector.detect(package, detailed=detailed)


def get_package_info(package: str) -> PackageInfo:
    """
    Get detailed information about a package.

    Args:
        package: Package name.

    Returns:
        PackageInfo dictionary with all details.
    """
    result = detect_package_origin(package, detailed=True)

    if isinstance(result, DetectionResult):
        return result.to_package_info()
    else:
        # Fallback for simple origin
        return PackageInfo(
            name=package,
            origin=result,
            confidence=(
                DetectionConfidence.HIGH
                if result != PackageOrigin.UNKNOWN
                else DetectionConfidence.WEAK
            ),
            confidence_score=1.0 if result != PackageOrigin.UNKNOWN else 0.3,
            is_editable=result == PackageOrigin.EDITABLE,
            is_namespace=result == PackageOrigin.NAMESPACE,
            is_development=result == PackageOrigin.EDITABLE,
        )


def detect_all_installed_packages(
    include_stdlib: bool = False, include_builtin: bool = False
) -> Dict[str, PackageInfo]:
    """
    Detect origins for all installed packages.

    Args:
        include_stdlib: Whether to include standard library packages.
        include_builtin: Whether to include built-in modules.

    Returns:
        Dictionary mapping package names to PackageInfo.
    """
    detector = PackageDetector()
    results = {}

    try:
        # Get all distributions via importlib.metadata
        import importlib.metadata

        for dist in importlib.metadata.distributions():
            package_name = dist.metadata["Name"]

            try:
                info = get_package_info(package_name)
                results[package_name] = info
            except Exception as e:
                # Create basic info for failed detections
                results[package_name] = PackageInfo(
                    name=package_name,
                    origin=PackageOrigin.UNKNOWN,
                    confidence=DetectionConfidence.WEAK,
                    confidence_score=0.1,
                    version=dist.version,
                )

        # Add stdlib packages if requested
        if include_stdlib:
            # This would need a list of stdlib modules
            # For simplicity, we'll add a few common ones
            stdlib_modules = ["os", "sys", "json", "re", "datetime", "pathlib"]
            for module in stdlib_modules:
                if module not in results:
                    results[module] = PackageInfo(
                        name=module,
                        origin=PackageOrigin.STDLIB,
                        confidence=DetectionConfidence.HIGH,
                        confidence_score=1.0,
                        is_stdlib=True,
                    )

        # Add built-in modules if requested
        if include_builtin:
            for module in sys.builtin_module_names:
                if module not in results:
                    results[module] = PackageInfo(
                        name=module,
                        origin=PackageOrigin.BUILTIN,
                        confidence=DetectionConfidence.HIGH,
                        confidence_score=1.0,
                        is_builtin=True,
                    )

    except Exception as e:
        warnings.warn(f"Failed to detect all packages: {e}", RuntimeWarning)

    return results
