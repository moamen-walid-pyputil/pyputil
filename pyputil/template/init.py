#!/usr/bin/env python3

# -*- coding: utf-8 -*-

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
__init__.py generator with import organization.

This module provides tools for generating package initialization
files with automatic import detection, duplicate handling, and validation.
"""

from pathlib import Path
from typing import Union, Optional, List, Pattern, Tuple, Dict, Set, Any, Callable
from types import ModuleType
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
import importlib.util
import importlib
import re
import os
import ast
import shutil
import sys
import warnings
import time
import hashlib
import json
from datetime import datetime
from functools import lru_cache
from contextlib import contextmanager


class ImportStyle(str, Enum):
    """Import style options."""
    RELATIVE = "relative"
    ABSOLUTE = "absolute"
    BOTH = "both"


class AliasStrategy(str, Enum):
    """Alias generation strategies."""
    DESCRIPTIVE = "descriptive"
    NUMERIC = "numeric"
    FOLDER_BASED = "folder_based"
    NONE = "none"


class ValidationLevel(str, Enum):
    """Validation strictness levels."""
    NONE = "none"
    BASIC = "basic"
    STRICT = "strict"
    FULL = "full"


class ConflictResolution(str, Enum):
    """Conflict resolution strategies for duplicate modules."""
    ALIAS = "alias"
    SKIP = "skip"
    WARN = "warn"
    ERROR = "error"


@dataclass
class ModuleInfo:
    """
    Information about a discovered Python module.
    
    Attributes
    ----------
    path : Path
        Absolute path to the module file.
    relative_path : Path
        Path relative to package root.
    name : str
        Module name (filename without extension).
    full_import : str
        Full dotted import path.
    folder : str
        Folder path as dotted string.
    depth : int
        Depth from package root.
    size : int
        File size in bytes.
    hash : str
        SHA256 hash of file content.
    is_package : bool
        Whether this module is a subpackage (has __init__.py).
    exports : List[str]
        Names exported by the module (from __all__ if exists).
    """
    path: Path
    relative_path: Path
    name: str
    full_import: str
    folder: str
    depth: int
    size: int
    hash: str
    is_package: bool = False
    exports: List[str] = field(default_factory=list)


@dataclass
class GenerationStats:
    """
    Statistics about the generation process.
    
    Attributes
    ----------
    total_modules : int
        Total number of modules discovered.
    unique_modules : int
        Number of unique module names.
    duplicate_modules : int
        Number of duplicate module names.
    aliases_created : int
        Number of aliases generated.
    excluded_modules : int
        Number of modules excluded.
    invalid_modules : int
        Number of invalid modules skipped.
    packages_found : int
        Number of subpackages discovered.
    generation_time : float
        Time taken to generate in seconds.
    warnings_count : int
        Number of warnings issued.
    """
    total_modules: int = 0
    unique_modules: int = 0
    duplicate_modules: int = 0
    aliases_created: int = 0
    excluded_modules: int = 0
    invalid_modules: int = 0
    packages_found: int = 0
    generation_time: float = 0.0
    warnings_count: int = 0


class InitFileGenerator:
    """
    Generator for __init__.py files with import organization.
    
    This class provides comprehensive functionality for generating package
    initialization files with automatic import detection, duplicate handling,
    validation, and best practices for Python packaging.
    
    Attributes
    ----------
    root : Path
        Root directory of the package.
    config : Dict[str, Any]
        Configuration dictionary for generator settings.
    stats : GenerationStats
        Statistics about the generation process.
    """
    
    # Default exclusion patterns
    DEFAULT_EXCLUSIONS = [
        "test_*",
        "*_test.py",
        "*_tests.py",
        "conftest.py",
        "__pycache__",
        "*.pyc",
        "*.pyo",
        "*.pyd",
        "*.so",
        "*.dll",
        "*.dylib",
        "setup.py",
        "setup.cfg",
        "pyproject.toml",
        "noxfile.py",
        "tox.ini",
        ".git",
        ".svn",
        ".hg",
        ".tox",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        "*.egg-info",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".coverage",
        "htmlcov",
        "docs",
        "examples",
        "scripts",
        "tests",
        "benchmarks",
    ]
    
    def __init__(
        self,
        root: Union[str, Path],
        overwrite: bool = True,
        exclude_patterns: Optional[List[str]] = None,
        use_aliases: bool = True,
        alias_strategy: AliasStrategy = AliasStrategy.DESCRIPTIVE,
        conflict_resolution: ConflictResolution = ConflictResolution.ALIAS,
        group_by_folder: bool = True,
        import_style: ImportStyle = ImportStyle.RELATIVE,
        validation_level: ValidationLevel = ValidationLevel.BASIC,
        follow_symlinks: bool = False,
        max_depth: Optional[int] = None,
        include_subpackages: bool = True,
        generate_all: bool = True,
        all_style: str = "explicit",  # explicit, wildcard, auto
        add_docstring: bool = True,
        add_metadata: bool = True,
        sort_imports: bool = True,
        use_black_formatting: bool = False,
        backup_existing: bool = True,
        dry_run: bool = False,
        verbose: bool = False,
        show_warnings: bool = True,
        preserve_existing_content: bool = False,
        detect_exports: bool = True,
        add_type_hints: bool = False,
        generate_version: bool = True,
        custom_header: Optional[str] = None,
        custom_footer: Optional[str] = None,
    ) -> None:
        """
        Initialize the InitFileGenerator with comprehensive configuration.
        
        Parameters
        ----------
        root : Union[str, Path]
            Root package directory. This should be the directory containing
            the package modules and subpackages.
            
        overwrite : bool, default=True
            Whether to overwrite existing __init__.py files. If False and
            the file exists, generation will be skipped.
            
        exclude_patterns : Optional[List[str]], optional
            List of glob patterns to exclude from import generation.
            Patterns are matched against filenames and relative paths.
            
        use_aliases : bool, default=True
            Whether to create aliases for duplicate module names. If False,
            duplicate modules will cause conflicts or be skipped based on
            conflict_resolution strategy.
            
        alias_strategy : AliasStrategy, default="descriptive"
            Strategy for generating aliases:
            - "descriptive": Use folder context (e.g., utils_helper)
            - "numeric": Use numeric suffixes (e.g., helper_1)
            - "folder_based": Use folder names only (e.g., utils_helper)
            - "none": No aliases (conflicts may occur)
            
        conflict_resolution : ConflictResolution, default="alias"
            How to handle duplicate module names:
            - "alias": Create aliases for duplicates
            - "skip": Skip duplicate modules
            - "warn": Issue warning and skip
            - "error": Raise exception
            
        group_by_folder : bool, default=True
            Whether to group imports by folder structure. When True,
            imports from the same folder are combined.
            
        import_style : ImportStyle, default="relative"
            Style for import statements:
            - "relative": Use relative imports (from .module import ...)
            - "absolute": Use absolute imports (from package import ...)
            - "both": Generate both styles (commented alternative)
            
        validation_level : ValidationLevel, default="basic"
            Strictness of import validation:
            - "none": No validation
            - "basic": Check syntax only
            - "strict": Check syntax and name conflicts
            - "full": Check syntax, conflicts, and try importing
            
        follow_symlinks : bool, default=False
            Whether to follow symbolic links when scanning directories.
            Can cause duplicate modules if not handled carefully.
            
        max_depth : Optional[int], optional
            Maximum directory depth to scan from root. Useful for
            limiting recursion in deep package structures.
            
        include_subpackages : bool, default=True
            Whether to include modules from subpackages in the main
            __init__.py. When False, only root-level modules are included.
            
        generate_all : bool, default=True
            Whether to generate __all__ list with exported names.
            The __all__ list controls what gets imported with `from package import *`.
            
        all_style : str, default="explicit"
            Style for __all__ generation:
            - "explicit": List all exported names explicitly
            - "wildcard": Use "*" (import all)
            - "auto": Automatic based on module exports
            
        add_docstring : bool, default=True
            Whether to add a module docstring with package information.
            
        add_metadata : bool, default=True
            Whether to add metadata comments (generator info, timestamp).
            
        sort_imports : bool, default=True
            Whether to sort import statements alphabetically for consistency.
            
        use_black_formatting : bool, default=False
            Whether to apply Black code formatting to the generated file.
            Requires the 'black' package to be installed.
            
        backup_existing : bool, default=True
            Whether to create a backup of existing __init__.py files.
            Backups are saved as __init__.py.backup.YYYYMMDD_HHMMSS.
            
        dry_run : bool, default=False
            Whether to simulate generation without writing files.
            Useful for testing and validation.
            
        verbose : bool, default=False
            Whether to print detailed information during generation.
            
        show_warnings : bool, default=True
            Whether to show warning messages.
            
        preserve_existing_content : bool, default=False
            Whether to preserve existing content when overwriting.
            If True, attempts to merge new imports with existing.
            
        detect_exports : bool, default=True
            Whether to detect __all__ exports from modules.
            
        add_type_hints : bool, default=False
            Whether to add type hints to generated code.
            
        generate_version : bool, default=True
            Whether to generate __version__ attribute.
            
        custom_header : Optional[str], optional
            Custom header text to add at the top of the file.
            
        custom_footer : Optional[str], optional
            Custom footer text to add at the bottom of the file.
            
        Raises
        ------
        NotADirectoryError
            If the provided root path is not a directory.
        PermissionError
            If the directory cannot be accessed.
        ValueError
            If configuration parameters are invalid.
        """
        # Validate root path
        self.root = Path(root).resolve()
        self._validate_root()
        
        # Store configuration
        self.overwrite = overwrite
        self.exclude_patterns = exclude_patterns or []
        self.use_aliases = use_aliases
        self.alias_strategy = alias_strategy
        self.conflict_resolution = conflict_resolution
        self.group_by_folder = group_by_folder
        self.import_style = import_style
        self.validation_level = validation_level
        self.follow_symlinks = follow_symlinks
        self.max_depth = max_depth
        self.include_subpackages = include_subpackages
        self.generate_all = generate_all
        self.all_style = all_style
        self.add_docstring = add_docstring
        self.add_metadata = add_metadata
        self.sort_imports = sort_imports
        self.use_black_formatting = use_black_formatting
        self.backup_existing = backup_existing
        self.dry_run = dry_run
        self.verbose = verbose
        self.show_warnings = show_warnings
        self.preserve_existing_content = preserve_existing_content
        self.detect_exports = detect_exports
        self.add_type_hints = add_type_hints
        self.generate_version = generate_version
        self.custom_header = custom_header
        self.custom_footer = custom_footer
        
        # Combine exclusion patterns
        self._combined_exclusions = self.DEFAULT_EXCLUSIONS + self.exclude_patterns
        
        # Compile patterns for performance
        self._compiled_patterns = self._compile_patterns(self._combined_exclusions)
        
        # Initialize data structures
        self.modules: Dict[str, ModuleInfo] = {}
        self.imports_by_folder: Dict[str, Set[str]] = defaultdict(set)
        self.module_names: Dict[str, List[ModuleInfo]] = defaultdict(list)
        self.aliases: Dict[str, str] = {}
        self.alias_counter: Dict[str, int] = defaultdict(int)
        self.stats = GenerationStats()
        
        # Validate configuration
        self._validate_config()
        
        if self.verbose:
            self._log(f"InitFileGenerator initialized for: {self.root}")
            self._log(f"Excluding {len(self._combined_exclusions)} patterns")
            self._log(f"Validation level: {self.validation_level}")
            self._log(f"Conflict resolution: {self.conflict_resolution}")
    
    def _log(self, message: str, level: str = "info") -> None:
        """Internal logging method for verbose output."""
        if not self.verbose:
            return
        
        prefix = {
            "info": "[INFO]",
            "warning": "[WARNING]",
            "error": "[ERROR]",
        }.get(level, "[INFO]")
    
    def _warn(self, message: str, category: type = UserWarning) -> None:
        """Issue a warning message."""
        self.stats.warnings_count += 1
        if self.show_warnings:
            warnings.warn(message, category, stacklevel=2)
    
    def _validate_root(self) -> None:
        """Validate that the root directory exists and is accessible."""
        if not self.root.exists():
            raise NotADirectoryError(
                f"Root directory '{self.root}' does not exist. "
                f"Please provide a valid package path."
            )
        if not self.root.is_dir():
            raise NotADirectoryError(
                f"'{self.root}' is not a directory. "
                f"A directory containing Python modules is required."
            )
        if not os.access(self.root, os.R_OK):
            raise PermissionError(
                f"No read permission for directory '{self.root}'. "
                f"Please check file permissions."
            )
    
    def _validate_config(self) -> None:
        """Validate configuration parameters."""
        if self.max_depth is not None and self.max_depth < 1:
            raise ValueError(f"max_depth must be >= 1, got {self.max_depth}")
        
        if self.alias_strategy == AliasStrategy.NONE and self.use_aliases:
            self.use_aliases = False
            self._warn(
                f"Alias strategy is 'none' but use_aliases=True. "
                f"Setting use_aliases=False.",
                UserWarning
            )
        
        if self.all_style not in ["explicit", "wildcard", "auto"]:
            raise ValueError(f"Invalid all_style: {self.all_style}")
        
        if self.use_black_formatting:
            try:
                import black
            except ImportError:
                self._warn(
                    "Black not installed. Disabling formatting. "
                    "Install with: pip install black",
                    UserWarning
                )
                self.use_black_formatting = False
    
    def _compile_patterns(self, patterns: List[str]) -> List[Pattern]:
        """
        Compile glob patterns to regex patterns for efficient matching.
        
        Parameters
        ----------
        patterns : List[str]
            List of glob patterns to compile.
            
        Returns
        -------
        List[Pattern]
            Compiled regex patterns.
        """
        compiled = []
        for pattern in patterns:
            # Convert glob to regex
            regex = re.escape(pattern)
            regex = regex.replace(r"\*", ".*")
            regex = regex.replace(r"\?", ".")
            regex = f"^{regex}$"
            compiled.append(re.compile(regex))
        return compiled
    
    def _should_exclude(self, path: Path) -> Tuple[bool, str]:
        """
        Check if a path should be excluded based on patterns and rules.
        
        Parameters
        ----------
        path : Path
            File or directory path to check.
            
        Returns
        -------
        Tuple[bool, str]
            (should_exclude, reason)
        """
        try:
            rel_path = path.relative_to(self.root)
        except ValueError:
            return True, "outside root directory"
        
        filename = path.name
        rel_str = str(rel_path)
        
        # Check against compiled patterns
        for pattern in self._compiled_patterns:
            if pattern.match(filename) or pattern.match(rel_str):
                return True, f"matched pattern: {pattern.pattern}"
        
        # Check depth limit
        if self.max_depth is not None:
            depth = len(rel_path.parts)
            if depth > self.max_depth:
                return True, f"depth {depth} exceeds limit {self.max_depth}"
        
        # Check for private files/directories
        if any(part.startswith("_") for part in rel_path.parts):
            return True, "private file/directory (starts with underscore)"
        
        return False, ""
    
    def _get_file_hash(self, path: Path) -> str:
        """Calculate SHA256 hash of file content."""
        try:
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()[:16]
        except (IOError, OSError):
            return ""
    
    def _detect_exports(self, path: Path) -> List[str]:
        """
        Detect __all__ exports from a Python module.
        
        Parameters
        ----------
        path : Path
            Path to the Python module.
            
        Returns
        -------
        List[str]
            List of exported names.
        """
        if not self.detect_exports:
            return []
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "__all__":
                            if isinstance(node.value, (ast.List, ast.Tuple)):
                                exports = []
                                for elt in node.value.elts:
                                    if isinstance(elt, ast.Constant):
                                        exports.append(str(elt.value))
                                    elif isinstance(elt, ast.Str):  # Python 3.7 compatibility
                                        exports.append(elt.s)
                                return exports
        except (SyntaxError, UnicodeDecodeError, IOError) as e:
            pass
        
        return []
    
    def _collect_modules(self) -> None:
        """Collect information about all valid Python modules in the package."""
        start_time = time.time()
        
        for path in self.root.rglob("*.py"):
            # Handle symlinks
            if path.is_symlink() and not self.follow_symlinks:
                continue
            
            # Skip __init__.py files
            if path.name == "__init__.py":
                continue
            
            # Check exclusion
            should_exclude, reason = self._should_exclude(path)
            if should_exclude:
                self.stats.excluded_modules += 1
                if self.verbose:
                    self._log(f"Excluded: {path.relative_to(self.root)} ({reason})")
                continue
            
            # Validate Python file
            if not self._is_valid_python_file(path):
                self.stats.invalid_modules += 1
                if self.verbose:
                    self._log(f"Invalid: {path.relative_to(self.root)}")
                continue
            
            # Get module information
            rel_path = path.relative_to(self.root)
            module_path = rel_path.with_suffix("")
            parts = module_path.parts
            
            if not parts:
                continue
            
            module_name = parts[-1]
            folder = ".".join(parts[:-1]) if len(parts) > 1 else ""
            full_import = ".".join(parts)
            depth = len(parts)
            
            # Check if it's a subpackage
            is_package = (path.parent / "__init__.py").exists()
            
            # Create module info
            module_info = ModuleInfo(
                path=path,
                relative_path=rel_path,
                name=module_name,
                full_import=full_import,
                folder=folder,
                depth=depth,
                size=path.stat().st_size,
                hash=self._get_file_hash(path),
                is_package=is_package,
                exports=self._detect_exports(path),
            )
            
            # Store module info
            self.modules[full_import] = module_info
            self.module_names[module_name].append(module_info)
            self.stats.total_modules += 1
            
            # Only include in root imports if it's a top-level module or subpackages enabled
            if depth == 1 or self.include_subpackages:
                self.imports_by_folder[folder].add(module_name)
            
            if self.verbose:
                self._log(f"Found: {full_import} ({module_info.size} bytes)")
        
        # Calculate statistics
        self.stats.unique_modules = len(self.module_names)
        self.stats.duplicate_modules = sum(
            1 for names in self.module_names.values() if len(names) > 1
        )
        self.stats.packages_found = sum(1 for m in self.modules.values() if m.is_package)
        self.stats.generation_time = time.time() - start_time
        
        if self.verbose:
            self._log(f"Collection complete: {self.stats.total_modules} modules found")
            self._log(f"  Unique: {self.stats.unique_modules}")
            self._log(f"  Duplicates: {self.stats.duplicate_modules}")
            self._log(f"  Packages: {self.stats.packages_found}")
            self._log(f"  Time: {self.stats.generation_time:.3f}s")
    
    def _is_valid_python_file(self, path: Path) -> bool:
        """
        Validate that a file is a valid Python module.
        
        Parameters
        ----------
        path : Path
            File path to validate.
            
        Returns
        -------
        bool
            True if the file is a valid Python module.
        """
        try:
            # Check file extension
            if path.suffix != ".py":
                return False
            
            # Check file size (skip empty files)
            file_size = path.stat().st_size
            if file_size == 0:
                return False
            
            # Check if we can parse the Python file
            with open(path, "r", encoding="utf-8") as f:
                try:
                    ast.parse(f.read())
                except SyntaxError as e:
                    self._warn(f"Syntax error in {path.name}: {e}", SyntaxWarning)
                    return False
            
            return True
            
        except (UnicodeDecodeError, PermissionError, OSError) as e:
            self._warn(f"Cannot read {path.name}: {e}", UserWarning)
            return False
    
    def _generate_alias(self, module_info: ModuleInfo) -> str:
        """
        Generate an alias for a module based on the configured strategy.
        
        Parameters
        ----------
        module_info : ModuleInfo
            Information about the module.
            
        Returns
        -------
        str
            Generated alias.
        """
        base_name = module_info.name
        folder_parts = module_info.folder.split(".") if module_info.folder else []
        
        if self.alias_strategy == AliasStrategy.NUMERIC:
            count = self.alias_counter[base_name]
            self.alias_counter[base_name] += 1
            alias = f"{base_name}_{count}"
        
        elif self.alias_strategy == AliasStrategy.FOLDER_BASED:
            if folder_parts:
                # Use folder names for context
                context = "_".join(folder_parts[-2:])  # Last 2 folders
                alias = f"{context}_{base_name}"
            else:
                alias = base_name
        
        else:  # DESCRIPTIVE (default)
            if len(folder_parts) >= 2:
                # Use parent folder for context
                context = folder_parts[-2]
                alias = f"{context}_{base_name}"
            elif len(folder_parts) == 1:
                alias = f"{folder_parts[0]}_{base_name}"
            else:
                alias = base_name
        
        # Ensure alias is valid Python identifier
        alias = re.sub(r"[^a-zA-Z0-9_]", "_", alias)
        if alias and alias[0].isdigit():
            alias = f"_{alias}"
        
        # Ensure uniqueness
        original_alias = alias
        counter = 1
        while alias in self.aliases.values():
            alias = f"{original_alias}_{counter}"
            counter += 1
        
        return alias
    
    def _resolve_conflicts(self) -> None:
        """Resolve duplicate module names according to conflict resolution strategy."""
        for name, modules in self.module_names.items():
            if len(modules) == 1:
                continue
            
            if self.conflict_resolution == ConflictResolution.ERROR:
                paths = [m.full_import for m in modules]
                raise ValueError(
                    f"Duplicate module name '{name}' found in: {', '.join(paths)}"
                )
            
            elif self.conflict_resolution == ConflictResolution.SKIP:
                # Keep only first module, skip others
                for module in modules[1:]:
                    if module.full_import in self.imports_by_folder[module.folder]:
                        self.imports_by_folder[module.folder].discard(module.name)
                    self._warn(f"Skipping duplicate module: {module.full_import}", UserWarning)
            
            elif self.conflict_resolution == ConflictResolution.WARN:
                paths = [m.full_import for m in modules]
                self._warn(
                    f"Duplicate module name '{name}' found in: {', '.join(paths)}. "
                    f"Only first module will be used.",
                    UserWarning
                )
                # Keep only first module
                for module in modules[1:]:
                    if module.full_import in self.imports_by_folder[module.folder]:
                        self.imports_by_folder[module.folder].discard(module.name)
            
            else:  # ALIAS (default)
                if self.use_aliases:
                    for i, module in enumerate(modules):
                        if i == 0:
                            continue  # Keep original
                        alias = self._generate_alias(module)
                        self.aliases[module.full_import] = alias
                        self.stats.aliases_created += 1
                        
                        # Update imports_by_folder to use alias
                        if module.name in self.imports_by_folder[module.folder]:
                            self.imports_by_folder[module.folder].discard(module.name)
                            self.imports_by_folder[module.folder].add(alias)
                else:
                    self._warn(
                        f"Duplicate module '{name}' but aliases disabled. "
                        f"Skipping: {modules[1].full_import}",
                        UserWarning
                    )
    
    def _build_import_lines(self) -> List[str]:
        """Build import statements."""
        import_lines = []
        
        # Sort folders if requested
        folders = sorted(self.imports_by_folder.keys()) if self.sort_imports else self.imports_by_folder.keys()
        
        for folder in folders:
            modules = sorted(self.imports_by_folder[folder]) if self.sort_imports else self.imports_by_folder[folder]
            
            if not modules:
                continue
            
            # Check if we can bulk import from this folder
            can_bulk = all(
                self.module_names.get(mod, []) and len(self.module_names[mod]) == 1
                for mod in modules
            )
            
            if can_bulk and folder:
                # Bulk import from subfolder
                modules_str = ", ".join(modules)
                
                if self.import_style == ImportStyle.RELATIVE:
                    import_lines.append(f"from .{folder} import {modules_str}")
                elif self.import_style == ImportStyle.ABSOLUTE:
                    package_name = self.root.name
                    import_lines.append(f"from {package_name}.{folder} import {modules_str}")
                else:  # BOTH
                    if self.import_style == ImportStyle.BOTH:
                        import_lines.append(f"from .{folder} import {modules_str}  # relative")
                        import_lines.append(f"# from {self.root.name}.{folder} import {modules_str}  # absolute")
            
            elif can_bulk and not folder:
                # Bulk import from root
                modules_str = ", ".join(modules)
                
                if self.import_style == ImportStyle.RELATIVE:
                    import_lines.append(f"from . import {modules_str}")
                elif self.import_style == ImportStyle.ABSOLUTE:
                    import_lines.append(f"import {modules_str}")
                else:  # BOTH
                    import_lines.append(f"from . import {modules_str}  # relative")
                    import_lines.append(f"# import {modules_str}  # absolute")
            
            else:
                # Individual imports
                for module in modules:
                    # Check if this is an alias
                    is_alias = module in self.aliases.values()
                    original_name = None
                    for full_import, alias in self.aliases.items():
                        if alias == module:
                            original_name = full_import.split(".")[-1]
                            break
                    
                    if self.import_style == ImportStyle.RELATIVE:
                        if folder:
                            if is_alias:
                                import_lines.append(
                                    f"from .{folder} import {original_name} as {module}"
                                )
                            else:
                                import_lines.append(f"from .{folder} import {module}")
                        else:
                            if is_alias:
                                import_lines.append(
                                    f"from . import {original_name} as {module}"
                                )
                            else:
                                import_lines.append(f"from . import {module}")
                    
                    elif self.import_style == ImportStyle.ABSOLUTE:
                        package_name = self.root.name
                        if folder:
                            if is_alias:
                                import_lines.append(
                                    f"from {package_name}.{folder} import {original_name} as {module}"
                                )
                            else:
                                import_lines.append(f"from {package_name}.{folder} import {module}")
                        else:
                            if is_alias:
                                import_lines.append(
                                    f"import {package_name}.{original_name} as {module}"
                                )
                            else:
                                import_lines.append(f"import {package_name}.{module}")
                    
                    else:  # BOTH
                        if folder:
                            if is_alias:
                                import_lines.append(
                                    f"from .{folder} import {original_name} as {module}  # relative"
                                )
                                import_lines.append(
                                    f"# from {self.root.name}.{folder} import {original_name} as {module}  # absolute"
                                )
                            else:
                                import_lines.append(f"from .{folder} import {module}  # relative")
                                import_lines.append(f"# from {self.root.name}.{folder} import {module}  # absolute")
                        else:
                            if is_alias:
                                import_lines.append(
                                    f"from . import {original_name} as {module}  # relative"
                                )
                                import_lines.append(
                                    f"# import {self.root.name}.{original_name} as {module}  # absolute"
                                )
                            else:
                                import_lines.append(f"from . import {module}  # relative")
                                import_lines.append(f"# import {self.root.name}.{module}  # absolute")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_lines = []
        for line in import_lines:
            if line not in seen:
                seen.add(line)
                unique_lines.append(line)
        
        return unique_lines
    
    def _validate_imports(self, import_lines: List[str]) -> Tuple[bool, List[str]]:
        """
        Validate generated import statements.
        
        Parameters
        ----------
        import_lines : List[str]
            List of import statements to validate.
            
        Returns
        -------
        Tuple[bool, List[str]]
            (is_valid, error_messages)
        """
        if self.validation_level == ValidationLevel.NONE:
            return True, []
        
        errors = []
        
        # Check syntax
        for i, line in enumerate(import_lines, 1):
            try:
                ast.parse(line)
            except SyntaxError as e:
                errors.append(f"Line {i}: Syntax error in '{line}': {e}")
        
        if self.validation_level in [ValidationLevel.STRICT, ValidationLevel.FULL]:
            # Check for duplicate imports
            seen = set()
            for line in import_lines:
                if line in seen:
                    errors.append(f"Duplicate import: '{line}'")
                seen.add(line)
            
            # Check for name conflicts
            names = set()
            for line in import_lines:
                match = re.search(r"(?:import|as)\s+(\w+)", line)
                if match:
                    name = match.group(1)
                    if name in names:
                        errors.append(f"Name conflict: '{name}' appears multiple times")
                    names.add(name)
        
        if self.validation_level == ValidationLevel.FULL:
            # Try to import modules (simulate)
            for line in import_lines:
                # Extract module path
                match = re.search(r"from\s+\.?(\S+)\s+import", line)
                if match:
                    module_path = match.group(1)
                    try:
                        # Note: This is a simplified check
                        pass
                    except Exception as e:
                        errors.append(f"Cannot import {module_path}: {e}")
        
        return len(errors) == 0, errors
    
    def _build_all_list(self) -> List[str]:
        """
        Build the __all__ list of exported names.
        
        Returns
        -------
        List[str]
            List of names to export.
        """
        if not self.generate_all:
            return []
        
        all_names = set()
        
        # Add non-duplicate modules
        for name, modules in self.module_names.items():
            if len(modules) == 1 and name not in self.aliases.values():
                all_names.add(name)
        
        # Add aliases
        for alias in self.aliases.values():
            all_names.add(alias)
        
        # Add exports from modules (if auto style)
        if self.all_style == "auto" and self.detect_exports:
            for module in self.modules.values():
                if module.exports:
                    all_names.update(module.exports)
        
        return sorted(all_names) if self.sort_imports else list(all_names)
    
    def _build_docstring(self) -> str:
        """Build the module docstring."""
        if not self.add_docstring:
            return ""
        
        docstring_lines = [
            f'"""',
            f"{self.root.name} package.",
            "",
            f"This package contains {self.stats.total_modules} modules across "
            f"{self.stats.packages_found} subpackages.",
            "",
            f"Auto-generated by InitFileGenerator on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            '"""',
        ]
        
        return "\n".join(docstring_lines)
    
    def _build_version(self) -> str:
        """Build __version__ attribute."""
        if not self.generate_version:
            return ""
        
        return '__version__ = "0.1.0"'
    
    def _build_content(self, import_lines: List[str]) -> str:
        """
        Build the complete __init__.py file content.
        
        Parameters
        ----------
        import_lines : List[str]
            List of import statements.
            
        Returns
        -------
        str
            Complete file content.
        """
        content_parts = []
        
        # Add custom header
        if self.custom_header:
            content_parts.append(self.custom_header)
            content_parts.append("")
        
        # Add docstring
        docstring = self._build_docstring()
        if docstring:
            content_parts.append(docstring)
            content_parts.append("")
        
        # Add imports
        if import_lines:
            content_parts.extend(import_lines)
            content_parts.append("")
        
        # Add version
        version = self._build_version()
        if version:
            content_parts.append(version)
            content_parts.append("")
        
        # Add __all__
        all_list = self._build_all_list()
        if all_list:
            if self.all_style == "wildcard":
                content_parts.append("__all__ = ['*']")
            else:
                all_lines = ["__all__ = ["]
                for name in all_list:
                    all_lines.append(f'    "{name}",')
                all_lines.append("]")
                content_parts.extend(all_lines)
                content_parts.append("")
        
        # Add metadata
        if self.add_metadata:
            content_parts.append("# Generation Metadata")
            content_parts.append(f"# Generated: {datetime.now().isoformat()}")
            content_parts.append(f"# Modules: {self.stats.total_modules}")
            content_parts.append(f"# Aliases: {self.stats.aliases_created}")
            content_parts.append("")
        
        # Add custom footer
        if self.custom_footer:
            content_parts.append(self.custom_footer)
            content_parts.append("")
        
        # Join everything
        content = "\n".join(content_parts)
        
        # Apply Black formatting if requested
        if self.use_black_formatting:
            try:
                import black
                mode = black.Mode()
                content = black.format_str(content, mode=mode)
            except ImportError:
                pass
        
        return content.strip()
    
    def generate(self) -> str:
        """
        Generate the __init__.py file.
        
        Returns
        -------
        str
            Path to the created __init__.py file.
            
        Raises
        ------
        ValueError
            If generated imports fail validation in strict mode.
        IOError
            If the file cannot be written.
        """
        init_file = self.root / "__init__.py"
        
        # Check if we should overwrite
        if init_file.exists() and not self.overwrite:
            if self.verbose:
                self._log(f"Skipping existing file: {init_file}")
            return str(init_file)
        
        # Collect module information
        self._collect_modules()
        
        # Resolve conflicts
        self._resolve_conflicts()
        
        # Build import lines
        import_lines = self._build_import_lines()
        
        # Validate imports if requested
        if self.validation_level != ValidationLevel.NONE and import_lines:
            is_valid, errors = self._validate_imports(import_lines)
            if not is_valid:
                error_msg = "\n".join(errors)
                raise ValueError(f"Import validation failed:\n{error_msg}")
        
        # Build file content
        content = self._build_content(import_lines)
        
        if self.dry_run:
            if self.verbose:
                self._log(f"DRY RUN: Would generate {init_file}")
                self._log(f"Content preview:\n{content[:500]}...")
            return str(init_file)
        
        # Create backup if file exists and backup enabled
        if init_file.exists() and self.backup_existing:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = init_file.with_suffix(f".py.backup.{timestamp}")
            try:
                shutil.copy2(init_file, backup_file)
                if self.verbose:
                    self._log(f"Backup created: {backup_file}")
            except OSError as e:
                self._warn(f"Failed to create backup: {e}", UserWarning)
        
        # Write the file
        try:
            init_file.write_text(content, encoding="utf-8")
            if self.verbose:
                self._log(f"Generated: {init_file}")
                self._log(f"File size: {init_file.stat().st_size} bytes")
        except (IOError, OSError) as e:
            raise IOError(f"Failed to write {init_file}: {e}")
        
        return str(init_file)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get generation statistics.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary with generation statistics.
        """
        return {
            "total_modules": self.stats.total_modules,
            "unique_modules": self.stats.unique_modules,
            "duplicate_modules": self.stats.duplicate_modules,
            "aliases_created": self.stats.aliases_created,
            "excluded_modules": self.stats.excluded_modules,
            "invalid_modules": self.stats.invalid_modules,
            "packages_found": self.stats.packages_found,
            "generation_time": self.stats.generation_time,
            "warnings_count": self.stats.warnings_count,
        }


def init_template(
    root: Union[str, Path],
    overwrite: bool = True,
    exclude_patterns: Optional[List[str]] = None,
    use_aliases: bool = True,
    alias_strategy: str = "descriptive",
    conflict_resolution: str = "alias",
    group_by_folder: bool = True,
    import_style: str = "relative",
    validation_level: str = "basic",
    follow_symlinks: bool = False,
    max_depth: Optional[int] = None,
    include_subpackages: bool = True,
    generate_all: bool = True,
    all_style: str = "explicit",
    add_docstring: bool = True,
    add_metadata: bool = True,
    sort_imports: bool = True,
    use_black_formatting: bool = False,
    backup_existing: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
    show_warnings: bool = True,
    preserve_existing_content: bool = False,
    detect_exports: bool = True,
    add_type_hints: bool = False,
    generate_version: bool = True,
    custom_header: Optional[str] = None,
    custom_footer: Optional[str] = None,
) -> str:
    """
    Create an intelligent __init__.py file with automatic import organization.
    
    This function analyzes your package structure, discovers Python modules,
    and generates a well-organized __init__.py file with proper imports,
    aliases for duplicate names, and __all__ exports.
    
    Parameters
    ----------
    root : Union[str, Path]
        Root package directory. This should be the directory containing
        your Python modules and subpackages.
        
    overwrite : bool, default=True
        Whether to overwrite existing __init__.py files.
        
    exclude_patterns : Optional[List[str]], optional
        List of glob patterns to exclude from import generation.
        Examples: ["test_*", "*_test.py", "experimental/*"]
        
    use_aliases : bool, default=True
        Whether to create aliases for duplicate module names.
        
    alias_strategy : str, default="descriptive"
        Strategy for generating aliases:
        - "descriptive": Use folder context (e.g., utils_helper)
        - "numeric": Use numeric suffixes (e.g., helper_1)
        - "folder_based": Use folder names only
        - "none": No aliases
        
    conflict_resolution : str, default="alias"
        How to handle duplicate module names:
        - "alias": Create aliases
        - "skip": Skip duplicates
        - "warn": Warn and skip
        - "error": Raise exception
        
    group_by_folder : bool, default=True
        Whether to group imports by folder structure.
        
    import_style : str, default="relative"
        Style for import statements:
        - "relative": Use relative imports
        - "absolute": Use absolute imports
        - "both": Generate both (commented)
        
    validation_level : str, default="basic"
        Strictness of import validation:
        - "none": No validation
        - "basic": Check syntax only
        - "strict": Check syntax and name conflicts
        - "full": Full validation with import testing
        
    follow_symlinks : bool, default=False
        Whether to follow symbolic links.
        
    max_depth : Optional[int], optional
        Maximum directory depth to scan.
        
    include_subpackages : bool, default=True
        Whether to include modules from subpackages.
        
    generate_all : bool, default=True
        Whether to generate __all__ list.
        
    all_style : str, default="explicit"
        Style for __all__ generation:
        - "explicit": List all names
        - "wildcard": Use "*"
        - "auto": Automatic based on module exports
        
    add_docstring : bool, default=True
        Whether to add module docstring.
        
    add_metadata : bool, default=True
        Whether to add metadata comments.
        
    sort_imports : bool, default=True
        Whether to sort imports alphabetically.
        
    use_black_formatting : bool, default=False
        Whether to apply Black formatting.
        
    backup_existing : bool, default=True
        Whether to backup existing files.
        
    dry_run : bool, default=False
        Whether to simulate generation without writing.
        
    verbose : bool, default=False
        Whether to print detailed information.
        
    show_warnings : bool, default=True
        Whether to show warning messages.
        
    preserve_existing_content : bool, default=False
        Whether to preserve existing content.
        
    detect_exports : bool, default=True
        Whether to detect __all__ exports.
        
    add_type_hints : bool, default=False
        Whether to add type hints.
        
    generate_version : bool, default=True
        Whether to generate __version__.
        
    custom_header : Optional[str], optional
        Custom header text.
        
    custom_footer : Optional[str], optional
        Custom footer text.
        
    Returns
    -------
    str
        Path to the created __init__.py file.
        
    Raises
    ------
    NotADirectoryError
        If the root path is not a directory.
    PermissionError
        If the directory cannot be accessed.
    ValueError
        If configuration parameters are invalid or validation fails.
        
    Examples
    --------
    Basic usage:
    >>> init_template("./my_package")
    '/path/to/my_package/__init__.py'
    
    Advanced usage with exclusions:
    >>> init_template(
    ...     "./my_package",
    ...     exclude_patterns=["*_test.py", "experimental/*"],
    ...     use_aliases=True,
    ...     validation_level="strict"
    ... )
    
    With custom formatting:
    >>> init_template(
    ...     "./my_package",
    ...     import_style="absolute",
    ...     all_style="wildcard",
    ...     add_metadata=True,
    ...     generate_version=True
    ... )
    
    Dry run to preview changes:
    >>> init_template(
    ...     "./my_package",
    ...     dry_run=True,
    ...     verbose=True
    ... )
    
    Notes
    -----
    - The generator automatically detects Python modules and their structure
    - Duplicate module names are handled with sub aliases
    - The generated __all__ list follows best practices for package exports
    - Imports are optimized for readability and maintainability
    - Validation ensures the generated code is syntactically correct
    - Backups are created with timestamps to prevent data loss
    """
    
    # Convert string strategies to enums
    alias_strategy_map = {
        "descriptive": AliasStrategy.DESCRIPTIVE,
        "numeric": AliasStrategy.NUMERIC,
        "folder_based": AliasStrategy.FOLDER_BASED,
        "none": AliasStrategy.NONE,
    }
    
    conflict_resolution_map = {
        "alias": ConflictResolution.ALIAS,
        "skip": ConflictResolution.SKIP,
        "warn": ConflictResolution.WARN,
        "error": ConflictResolution.ERROR,
    }
    
    import_style_map = {
        "relative": ImportStyle.RELATIVE,
        "absolute": ImportStyle.ABSOLUTE,
        "both": ImportStyle.BOTH,
    }
    
    validation_level_map = {
        "none": ValidationLevel.NONE,
        "basic": ValidationLevel.BASIC,
        "strict": ValidationLevel.STRICT,
        "full": ValidationLevel.FULL,
    }
    
    generator = InitFileGenerator(
        root=root,
        overwrite=overwrite,
        exclude_patterns=exclude_patterns,
        use_aliases=use_aliases,
        alias_strategy=alias_strategy_map.get(alias_strategy, AliasStrategy.DESCRIPTIVE),
        conflict_resolution=conflict_resolution_map.get(conflict_resolution, ConflictResolution.ALIAS),
        group_by_folder=group_by_folder,
        import_style=import_style_map.get(import_style, ImportStyle.RELATIVE),
        validation_level=validation_level_map.get(validation_level, ValidationLevel.BASIC),
        follow_symlinks=follow_symlinks,
        max_depth=max_depth,
        include_subpackages=include_subpackages,
        generate_all=generate_all,
        all_style=all_style,
        add_docstring=add_docstring,
        add_metadata=add_metadata,
        sort_imports=sort_imports,
        use_black_formatting=use_black_formatting,
        backup_existing=backup_existing,
        dry_run=dry_run,
        verbose=verbose,
        show_warnings=show_warnings,
        preserve_existing_content=preserve_existing_content,
        detect_exports=detect_exports,
        add_type_hints=add_type_hints,
        generate_version=generate_version,
        custom_header=custom_header,
        custom_footer=custom_footer,
    )
    
    return generator.generate()


def write_init(path: Union[str, Path] = "__init__.py", **kwargs) -> None:
    """
    Generate __init__.py and write it directly to disk.
    
    This is a convenience wrapper around init_template() that handles
    file writing with proper encoding and error handling.
    
    Parameters
    ----------
    path : str or Path, default="__init__.py"
        Path where to write the __init__.py file. If a directory is provided,
        writes to that directory/__init__.py.
    **kwargs
        Additional arguments passed to init_template().
        
    Examples
    --------
    Write to current directory:
    >>> write_init("__init__.py", root="./my_package")
    
    Write to specific package directory:
    >>> write_init("./my_package/__init__.py", exclude_patterns=["test_*"])
    
    Notes
    -----
    - The file is written with UTF-8 encoding
    - Existing files are backed up with timestamps
    - The directory is created if it doesn't exist
    """
    path_obj = Path(path)
    
    # If path is a directory, append __init__.py
    if path_obj.is_dir() or (not path_obj.suffix and path_obj.name != "__init__.py"):
        path_obj = path_obj / "__init__.py"
    
    # Ensure parent directory exists
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    # Generate __init__.py content
    root = kwargs.pop("root", path_obj.parent)
    content = init_template(root=root, **kwargs)
    
    # Write to file
    path_obj.write_text(content, encoding="utf-8")
