#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Module caching and optimization.

Creates cached versions of Python modules to speed up loading.
It removes unnecessary elements and stores optimized bytecode.
"""

import sys
import os
import ast
import time
import hashlib
import marshal
import json
from types import ModuleType
from pathlib import Path
import importlib.util
import inspect
import traceback
from typing import Dict, Any, Optional, Tuple, Union, List, Set
import builtins

CACHE_DIR = Path(".cachex")
CACHE_DIR.mkdir(exist_ok=True)

# Global cache for compiled modules
_MODULE_CACHE: Dict[str, ModuleType] = {}
_DEPENDENCY_MAP: Dict[str, Set[str]] = {}


class BuildCache:
    """
    Cache manager for Python modules.

    Handles caching, loading, and invalidation of compiled modules.
    """

    def __init__(self, cache_dir: str = CACHE_DIR):
        """
        Initialize cache manager.

        Parameters
        ----------
        cache_dir : Path
            Directory for cache files.
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.metadata_file = cache_dir / "metadata.json"
        self._load_metadata()

    def _load_metadata(self) -> None:
        """
        Load cache metadata from disk.

        Creates empty metadata if file doesn't exist.
        """
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r") as f:
                    self.metadata = json.load(f)
            except:
                self.metadata = {}
        else:
            self.metadata = {}

    def _save_metadata(self) -> None:
        """
        Save cache metadata to disk.
        """
        with open(self.metadata_file, "w") as f:
            json.dump(self.metadata, f, indent=2)

    def get_cache_key(self, module_path: str) -> str:
        """
        Generate cache key for a module.

        Parameters
        ----------
        module_path : str
            Path to module file.

        Returns
        -------
        str
            Cache key based on file content and metadata.
        """
        module_path = Path(module_path)
        source = module_path.read_text(encoding="utf-8")
        stat = module_path.stat()

        # Include source, mtime, size, and path for uniqueness
        key_data = f"{source}{stat.st_mtime}{stat.st_size}{module_path}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:32]

    def get_cache_file(self, module_path: str, key: str) -> Path:
        """
        Get cache file path for a module.

        Parameters
        ----------
        module_path : Path
            Original module path.
        key : str
            Cache key.

        Returns
        -------
        Path
            Path to cache file.
        """
        return self.cache_dir / f"{Path(module_path).stem}.{key}.cx"

    def is_cache_valid(self, module_path: str, cache_file: Path) -> bool:
        """
        Check if cached version is still valid.

        Parameters
        ----------
        module_path : str
            Original module path.
        cache_file : Path
            Cache file path.

        Returns
        -------
        bool
            True if cache is valid, False otherwise.
        """
        cache_file = Path(cache_file)

        if not cache_file.exists():
            return False

        if not module_path.exists():
            return False

        try:
            with open(cache_file, "rb") as f:
                payload = marshal.load(f)

            current_key = self.get_cache_key(module_path)
            return payload.get("hash") == current_key
        except:
            return False

    def load_from_cache(self, cache_file: str) -> Optional[ModuleType]:
        """
        Load module from cache file.

        Parameters
        ----------
        cache_file : str
            path to cache file.

        Returns
        -------
        ModuleType or None
            Loaded module or None if loading fails.
        """
        cache_file = Path(cache_file)

        try:
            with open(cache_file, "rb") as f:
                payload = marshal.load(f)

            code = marshal.loads(payload["module"])
            module_name = cache_file.stem.split(".")[0]
            module = ModuleType(module_name)

            # Store metadata
            module.__cache_metadata__ = {
                "timestamp": payload.get("timestamp"),
                "hash": payload.get("hash"),
                "source": str(payload.get("source_path")),
            }

            exec(code, module.__dict__)
            return module
        except Exception as e:
            return None

    def save_to_cache(self, module_path: str, key: str, compiled_code: bytes) -> None:
        """
        Save compiled module to cache.

        Parameters
        ----------
        module_path : str
            Original module path.
        key : str
            Cache key.
        compiled_code : bytes
            Compiled bytecode.
        """
        
        cache_file = self.get_cache_file(module_path, key)

        payload = {
            "timestamp": time.time(),
            "hash": key,
            "source_path": str(module_path),
            "module": compiled_code,
        }

        with open(cache_file, "wb") as f:
            marshal.dump(payload, f)

        # Update metadata
        self.metadata[module_path] = {
            "cached_at": time.time(),
            "cache_key": key,
            "cache_file": str(cache_file),
        }
        self._save_metadata()


class _ASTOptimizer(ast.NodeTransformer):
    """
    Optimize AST by removing unnecessary elements.
    """

    def __init__(self, remove_docstrings: bool = True):
        """
        Initialize AST optimizer.

        Parameters
        ----------
        remove_docstrings : bool
            Remove docstrings if True.
        """
        self.remove_docstrings = remove_docstrings

    def visit_Module(self, node: ast.Module) -> ast.Module:
        """
        Visit module node.

        Parameters
        ----------
        node : ast.Module
            Module AST node.

        Returns
        -------
        ast.Module
            Optimized module node.
        """
        self.generic_visit(node)

        # Remove module-level docstring
        if (
            self.remove_docstrings
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Str)
        ):
            node.body.pop(0)

        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        """
        Visit function definition node.

        Parameters
        ----------
        node : ast.FunctionDef
            Function definition AST node.

        Returns
        -------
        ast.FunctionDef
            Optimized function node.
        """
        self.generic_visit(node)

        # Remove function docstring
        if (
            self.remove_docstrings
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Str)
        ):
            node.body.pop(0)

        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        """
        Visit class definition node.

        Parameters
        ----------
        node : ast.ClassDef
            Class definition AST node.

        Returns
        -------
        ast.ClassDef
            Optimized class node.
        """
        self.generic_visit(node)

        # Remove class docstring
        if (
            self.remove_docstrings
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Str)
        ):
            node.body.pop(0)

        return node

    def visit_Pass(self, node: ast.Pass) -> Optional[ast.Pass]:
        """
        Visit pass statement node.

        Parameters
        ----------
        node : ast.Pass
            Pass statement AST node.

        Returns
        -------
        ast.Pass or None
            None to remove pass statement.
        """
        return None

    def visit_Expr(self, node: ast.Expr) -> Optional[ast.Expr]:
        """
        Visit expression node.

        Parameters
        ----------
        node : ast.Expr
            Expression AST node.

        Returns
        -------
        ast.Expr or None
            Expression node or None if it's just a string.
        """
        self.generic_visit(node)

        # Remove standalone string expressions (likely docstrings)
        if isinstance(node.value, ast.Str):
            return None

        return node


def cache_module(source: str, module_path: str) -> ast.Module:
    """
    Cache and optimized module source code.

    Parameters
    ----------
    source : str
        Module source code.
    module_path : str
        Path to module file.

    Returns
    -------
    ast.Module
        Optimized AST.
    """
    tree = ast.parse(source, filename=module_path)

    optimizer = _ASTOptimizer(remove_docstrings=True)
    tree = optimizer.visit(tree)

    ast.fix_missing_locations(tree)
    return tree


def build(
    module_path: Union[str, Path],
    cache_dir: Union[str, Path] = CACHE_DIR,
    force_rebuild: bool = False,
) -> ModuleType:
    """
    Build optimized cached version of a module.

    Parameters
    ----------
    module_path : str or Path
        Str module path or pathlib.Path object.
    cache_dir : str or Path, optional
        Cache directory path.
    force_rebuild : bool, optional
        Force rebuild even if cache exists.

    Returns
    -------
    ModuleType
        Optimized module object.

    Raises
    ------
    FileNotFoundError
        If module file doesn't exist.

    Examples
    --------
    >>> mod = build("utils/maths.py")
    >>> result = mod.add(5, 3)
    8
    """
    module_path = Path(module_path)
    if not module_path.exists():
        raise FileNotFoundError(f"Module path not found: '{module_path}'")
    cache_manager = BuildCache(Path(cache_dir))

    # Check global cache first
    cache_key = str(module_path)
    if cache_key in _MODULE_CACHE and not force_rebuild:
        return _MODULE_CACHE[cache_key]

    # Get cache key
    key = cache_manager.get_cache_key(module_path)
    cache_file = cache_manager.get_cache_file(module_path, key)

    # Try to load from cache
    if not force_rebuild and cache_manager.is_cache_valid(module_path, cache_file):
        module = cache_manager.load_from_cache(cache_file)
        if module:
            _MODULE_CACHE[cache_key] = module
            return module

    # Read and optimize source
    source = module_path.read_text(encoding="utf-8")

    # Compile optimized code
    compiled = compile(source, str(module_path), "exec")
    compiled_bytes = marshal.dumps(compiled)

    # Save to cache
    cache_manager.save_to_cache(str(module_path), key, compiled_bytes)

    # Create module
    module = ModuleType(module_path.stem)

    # Add cache metadata
    module.__cache_metadata__ = {
        "timestamp": time.time(),
        "hash": key,
        "source": str(module_path),
        "cached": True,
    }

    exec(compiled, module.__dict__)

    # Store in global cache
    _MODULE_CACHE[cache_key] = module

    return module


def build_frame(
    track_usage: bool = False, cache_dir: Union[str, Path] = CACHE_DIR
) -> Union[Dict, Tuple]:
    """
    Build cached versions of all modules in current frame.

    Parameters
    ----------
    track_usage : bool, optional
        Track module usage statistics.
    cache_dir : str or Path, optional
        Cache directory path.

    Returns
    -------
    dict or tuple
        If track_usage is False: dict of module name -> ModuleType
        If track_usage is True: tuple of (modules_dict, usage_stats)

    Notes
    -----
    This function modifies the calling frame's namespace.
    """
    cache_manager = BuildCache(Path(cache_dir))
    usage_stats = {} if track_usage else None

    def _build_and_cache(module_path: str) -> ModuleType:
        """
        Build or load cached module.

        Parameters
        ----------
        module_path : str
            Path to module file.

        Returns
        -------
        ModuleType
            Cached module.
        """
        nonlocal usage_stats

        path = Path(module_path)
        if not path.exists():
            raise FileNotFoundError(f"Module not found: {module_path}")

        # Check cache
        key = cache_manager.get_cache_key(path)
        cache_file = cache_manager.get_cache_file(path, key)

        if cache_manager.is_cache_valid(path, cache_file):
            module = cache_manager.load_from_cache(cache_file)
            if module:
                if track_usage:
                    usage_stats[path.stem] = usage_stats.get(path.stem, 0) + 1
                return module

        # Build new
        source = path.read_text(encoding="utf-8")
        tree = optimize_module(source, module_path)
        compiled = compile(tree, module_path, "exec")
        compiled_bytes = marshal.dumps(compiled)

        # Save to cache
        cache_manager.save_to_cache(path, key, compiled_bytes)

        # Create module
        module = ModuleType(path.stem)
        module.__cache_metadata__ = {
            "timestamp": time.time(),
            "hash": key,
            "source": module_path,
            "cached": True,
        }

        exec(compiled, module.__dict__)

        if track_usage:
            usage_stats[path.stem] = usage_stats.get(path.stem, 0) + 1

        return module

    # Import hook for future imports
    class CacheImporter:
        """
        Import hook to intercept module loading.
        """

        def find_spec(self, fullname: str, path: Any = None, target: Any = None):
            """
            Find module specification.

            Parameters
            ----------
            fullname : str
                Full module name.
            path : Any, optional
                Search path.
            target : Any, optional
                Target module.

            Returns
            -------
            ModuleSpec or None
                Module specification if found.
            """
            try:
                spec = importlib.util.find_spec(fullname)
                if spec and spec.origin and spec.origin.endswith(".py"):
                    return importlib.util.spec_from_loader(
                        fullname, self, origin=spec.origin
                    )
            except Exception:
                pass
            return None

        def create_module(self, spec) -> None:
            """
            Create module object.

            Parameters
            ----------
            spec : ModuleSpec
                Module specification.

            Returns
            -------
            None
                Use default module creation.
            """
            return None

        def exec_module(self, module: ModuleType) -> None:
            """
            Execute module with caching.

            Parameters
            ----------
            module : ModuleType
                Module to execute.
            """
            spec = importlib.util.find_spec(module.__name__)
            if spec and spec.origin:
                try:
                    cached_mod = _build_and_cache(spec.origin)
                    module.__dict__.update(cached_mod.__dict__)
                except Exception:
                    pass

    # Install import hook
    sys.meta_path.insert(0, CacheImporter())

    # Process modules in current frame
    frame = inspect.currentframe().f_back
    cached_modules = {}

    for name, obj in list(frame.f_globals.items()):
        if inspect.ismodule(obj) and hasattr(obj, "__file__") and obj.__file__:
            try:
                cached_mod = _build_and_cache(obj.__file__)
                cached_modules[name] = cached_mod
                frame.f_globals[name] = cached_mod
            except Exception:
                # Keep original module if caching fails
                pass

    if track_usage:
        return cached_modules, usage_stats
    return cached_modules


def clear_cache(cache_dir: Union[str, Path] = CACHE_DIR) -> None:
    """
    Clear all cache files.

    Parameters
    ----------
    cache_dir : str or Path, optional
        Cache directory path.
    """
    cache_path = Path(cache_dir)

    if cache_path.exists():
        for file in cache_path.glob("*.cx"):
            file.unlink()

        metadata_file = cache_path / "metadata.json"
        if metadata_file.exists():
            metadata_file.unlink()

    # Clear global caches
    _MODULE_CACHE.clear()
    _DEPENDENCY_MAP.clear()


def get_cache_info(cache_dir: Union[str, Path] = CACHE_DIR) -> Dict:
    """
    Get information about cache contents.

    Parameters
    ----------
    cache_dir : str or Path, optional
        Cache directory path.

    Returns
    -------
    dict
        Cache information.
    """
    cache_path = Path(cache_dir)

    if not cache_path.exists():
        return {"total_files": 0, "size_bytes": 0, "files": []}

    cache_files = list(cache_path.glob("*.cx"))

    total_size = sum(f.stat().st_size for f in cache_files)

    info = {
        "total_files": len(cache_files),
        "size_bytes": total_size,
        "size_human": f"{total_size / 1024:.2f} KB",
        "files": [
            {
                "name": f.name,
                "size": f.stat().st_size,
                "modified": time.ctime(f.stat().st_mtime),
            }
            for f in cache_files
        ],
    }

    # Load metadata if exists
    metadata_file = cache_path / "metadata.json"
    if metadata_file.exists():
        try:
            with open(metadata_file, "r") as f:
                info["metadata"] = json.load(f)
        except:
            info["metadata"] = {}

    return info


def warmup_cache(
    module_paths: List[Union[str, Path]], cache_dir: Union[str, Path] = CACHE_DIR
) -> None:
    """
    Pre-build cache for multiple modules.

    Parameters
    ----------
    module_paths : list of str or Path
        List of module paths to cache.
    cache_dir : str or Path, optional
        Cache directory path.
    """
    for path in module_paths:
        try:
            build(path, cache_dir)
        except Exception:
            pass
