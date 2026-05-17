#!/usr/bin/env python3

# -*- coding: utf-8 -*-

# =========================
# Core modules
# =========================
from .MakeModule import MakeModule

# =========================
# Temporary modules (mkmod)
# =========================
from .MakeTempModule import (
	mkmod,
	validate_module_source as mkmod_validate_source,
	get_module_stats as mkmod_stats,
	cleanup as mkmod_cleanup,
	is_mkmod,
	to_file as mkmod_to_file,
	from_file as mkmod_from_file,
	get_registered_modules as mkmod_registered,
	remove_module as remove_mkmod,
	update_module_config as update_mkmod_module_config,
	ModuleConfig as MkmodModuleConfig,
	ModuleStat as MkmodModuleStat,
	SafeLevel as MkmodSafeLevel,
	ModulePolicy as MkmodModulePolicy,
)

# =========================
# Package detection
# =========================
from .Detector import (
	detect_package_origin,
	detect_all_installed_packages,
	get_package_info,
	PackageDetector,
	DetectionResult,
	DetectionMethod,
	PackageOrigin,
	PackageInfo,
	DetectionConfidence,
	PlatformType as DetectorPlatformType,
	EnvironmentType as DetectorEnvironmentType,
	PackageDetectorError,
	PackageNotFoundError,
	MetadataReadError,
	PathResolutionError,
	PlatformDetectionError,
	EnvironmentDetectionError,
)

# =========================
# Utilities
# =========================
from .util import (
	current_modules,
	get_module_deps,
	ismodule,
	ispackage,
	isnamespace,
	getmodules,
	getpackages,
	getnamespaces,
	getnamespaces_basic,
	get_deps_from_code,
)

from .util2 import (
	discover_modules,
	get_module_graph,
	circular_deps,
	namespace_packages,
	walk_packages,
	format_dep_graph,
	get_module_importers,
)

# =========================
# Standard library helpers
# =========================
from .stdlib import (
	LIST_OF_STDLIBS,
	is_stdlib,
	isbuiltin,
	stdlib_audit,
)

# =========================
# Locking
# =========================
from .lock import (
	lock_modules,
	unlock_modules,
)

# =========================
# Packages
# =========================
from .packages import (
	list_packages,
	all_packages,
)

# =========================
# Frozen modules
# =========================
from .frozen_module import (
	FrozenModuleCreator,
	FrozenModuleInfo,
	FrozenModuleLoader,
	FrozenModuleFinder,
	FreezeMode,
	FreezeStats,
	frozen_modules_context,
	freeze_module,
	freeze_file,
	freeze_package,
	get_frozen_module_names,
	FrozenModuleError,
	ModuleCompilationError,
	ModuleNotFoundError,
)

# =========================
# Exceptions (grouped)
# =========================
exceptions = (
	# Detector
	PackageDetectorError,
	PackageNotFoundError,
	MetadataReadError,
	PathResolutionError,
	PlatformDetectionError,
	EnvironmentDetectionError,

	# Frozen
	FrozenModuleError,
	ModuleCompilationError,
	ModuleNotFoundError,
)


# =========================
# Public API
# =========================
__all__ = [
	# stdlib
	"LIST_OF_STDLIBS",
	"is_stdlib",
	"isbuiltin",
	"stdlib_audit",

	# core
	"MakeModule",

	# mkmod
	"mkmod",
	"mkmod_validate_source",
	"mkmod_stats",
	"mkmod_cleanup",
	"is_mkmod",
	"mkmod_to_file",
	"mkmod_from_file",
	"mkmod_registered",
	"remove_mkmod",
	"update_mkmod_module_config",
	"MkmodModuleConfig",
	"MkmodModuleStat",
	"MkmodSafeLevel",
	"MkmodModulePolicy",

	# detector
	"detect_package_origin",
	"detect_all_installed_packages",
	"get_package_info",
	"PackageDetector",
	"DetectionResult",
	"DetectionMethod",
	"PackageOrigin",
	"PackageInfo",
	"DetectionConfidence",
	"DetectorPlatformType",
	"DetectorEnvironmentType",

	# utilities
	"current_modules",
	"get_module_deps",
	"ismodule",
	"ispackage",
	"isnamespace",
	"getmodules",
	"getpackages",
	"getnamespaces",
	"getnamespaces_basic",
	"get_deps_from_code",

	# util2
	"discover_modules",
	"get_module_graph",
	"circular_deps",
	"namespace_packages",
	"walk_packages",
	"format_dep_graph",
	"get_module_importers",

	# locking
	"lock_modules",
	"unlock_modules",

	# packages
	"list_packages",
	"all_packages",

	# frozen
	"FrozenModuleCreator",
	"FrozenModuleInfo",
	"FrozenModuleLoader",
	"FrozenModuleFinder",
	"FreezeMode",
	"FreezeStats",
	"frozen_modules_context",
	"freeze_module",
	"freeze_file",
	"freeze_package",
	"get_frozen_module_names",

	# exceptions
	"exceptions",
]

# =========================
# Cleanup namespace
# =========================
from ..api import clean
clean(expose=__all__)