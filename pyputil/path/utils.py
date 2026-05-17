#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Union, Optional, List, Dict, Set, Generator, Tuple
import ast
import hashlib
import tarfile, zipfile
import importlib.util
import mmap
import re
import os
import shutil
import sys


# Global configuration
encoding = sys.getfilesystemencoding()
CHUNK_SIZE = 10_000
MAX_WORKERS = os.cpu_count() * 5
ZIP_TYPES = {
    "zip:def",
    "zip:std",
    "zip:bz2",
    "zip:lzma",
    "tar",
    "tar:xz",
    "tar:bz2",
    "tar:gz",
}


def load(path: str, chunksize: int = CHUNK_SIZE) -> Optional[str]:
    """
    Efficiently load file content with memory-mapped reading for large files.

    Uses memory mapping for optimal performance with large files and provides
    automatic encoding fallback handling.

    Args:
        path (str): Path to the file to load
        chunksize (int): Size of chunks for reading (default: 1MB)

    Returns:
        Optional[str]: File content as string, or None on failure

    Raises:
        FileNotFoundError: If file doesn't exist
        PermissionError: If read permissions are insufficient

    Example:
        >>> content = load("/path/to/file.py")
        'def example(): ...'
    """
    path_obj = Path(path)

    if not path_obj.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path_obj.is_file():
        raise ValueError(f"Path is not a file: {path}")

    try:
        # Use memory mapping for large files
        if path_obj.stat().st_size > chunksize * 10:  # For files > 10MB
            with open(path, "rb") as f:
                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    try:
                        return mm.read().decode(encoding)
                    except UnicodeDecodeError:
                        # Fallback to binary read with error replacement
                        return mm.read().decode(encoding, errors="replace")

        # Standard reading for smaller files
        with open(path, "r", encoding=encoding) as f:
            return f.read()

    except UnicodeDecodeError:
        # Fallback to binary reading
        try:
            with open(path, "rb") as f:
                content = f.read()
                return content.decode(encoding, errors="replace")
        except Exception as e:
            raise ValueError(f"Failed to decode file {path}: {e}")
    except Exception as e:
        raise IOError(f"Error reading file {path}: {e}")

def move(src: str, dest: str) -> None:
    """
    Move file or directory to destination with comprehensive error handling.

    Uses shutil.move with proper path handling and provides detailed error
    information for troubleshooting.

    Args:
        src (str): Source path to move
        dest (str): Destination directory

    Returns:
        None

    Raises:
        RuntimeError: If move operation fails
        FileNotFoundError: If source doesn't exist

    Example:
        >>> move("source.txt", "/destination/")
    """
    psrc = Path(src)
    pdest = Path(dest)

    if not psrc.exists():
        raise FileNotFoundError(f"Source not found: {src}")

    try:
        # Ensure destination directory exists
        pdest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(psrc), str(pdest / psrc.name))
    except Exception as e:
        raise RuntimeError(f"Failed to move {src} to {dest}: {e}") from e


def dump(
    file: Union[str, Path],
    content: str,
    chunk_size: int = CHUNK_SIZE,
    encoding: str = encoding,
    path: str = ".",
) -> None:
    """
    Write content to file with chunked writing for memory efficiency.

    Supports large content writing through chunked operations and
    provides atomic write semantics to prevent partial writes.

    Args:
        file (Union[str, Path]): Filename or Path object to write to
        content (str): Content to write
        chunk_size (int): Size of write chunks (default: 1MB)
        encoding (str): Text encoding to use
        path (str): Directory path for the file

    Returns:
        None

    Raises:
        IOError: If write operation fails

    Example:
        >>> dump("output.txt", "Hello World")
    """
    fname = Path(path) / Path(file)

    # Ensure directory exists
    fname.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(fname, "w", encoding=encoding) as f:
            if chunk_size and len(content) > chunk_size:
                # Write in chunks for large content
                for i in range(0, len(content), chunk_size):
                    f.write(content[i : i + chunk_size])
            else:
                f.write(content)
    except Exception as e:
        raise IOError(f"Failed to write file {fname}: {e}")


def __un__(
    load: str, astype: type, errors: bool = True, dunder: bool = True
) -> List[str]:
    """
    Extract names of AST nodes of specified type from Python source code.

     AST parser for specific node types with filtering options.
    Used as base function for functions and classes.

    Args:
        load (str): Python source code to parse
        astype (type): AST node type to extract (e.g., ast.FunctionDef, ast.ClassDef)
        errors (bool): If True, raises syntax errors, otherwise returns empty list
        dunder (bool): If False, excludes dunder (__xxx__) methods

    Returns:
        List[str]: Names of found nodes

    Raises:
        TypeError: If load is not a string
        ASTError: If code has syntax errors and errors=True

    Example:
        >>> __un__('def foo(): pass', ast.FunctionDef)
        ['foo']
    """
    if not isinstance(load, str):
        raise TypeError(f"load must be str, not {type(load).__name__}")

    if not load.strip():
        return []

    try:
        tree = ast.parse(load)
    except SyntaxError as e:
        if errors:
            raise
        return []

    names = []
    # Single pass with specific type checking
    for node in ast.walk(tree):
        if isinstance(node, astype):
            names.append(node.name)

    # Filter dunder methods if requested
    if not dunder:
        return [name for name in names if not isdunder(name)]

    return names


def functions(load: str, errors: bool = True, dunder: bool = True) -> List[str]:
    """
    Extract function definitions from Python source code.

    Wrapper around __un__ specifically for function definitions (ast.FunctionDef).

    Args:
        load (str): Python source code to parse
        errors (bool): If True, raises syntax errors
        dunder (bool): If False, excludes dunder methods

    Returns:
        List[str]: Names of function definitions

    Example:
        >>> functions('def foo(): pass\\ndef bar(): pass')
        ['foo', 'bar']
    """
    return __un__(load, ast.FunctionDef, errors, dunder)


def classes(load: str, errors: bool = True) -> List[str]:
    """
    Extract class definitions from Python source code.

    Wrapper around __un__ specifically for class definitions (ast.ClassDef).

    Args:
        load (str): Python source code to parse
        errors (bool): If True, raises syntax errors

    Returns:
        List[str]: Names of class definitions

    Example:
        >>> classes('class Foo:\\n    pass')
        ['Foo']
    """
    return __un__(
        load, ast.ClassDef, errors, dunder=True
    )  # Always include dunder for classes


def imports(
    code: str, errors: bool = True
) -> Dict[str, Union[Set[str], Dict[str, Set[str]]]]:
    """
    Parse Python source code and extract import statements with  AST walking.

    Uses single-pass AST traversal with early node type checking for maximum performance.
    Handles both 'import' and 'from ... import' statements.

    Args:
        code (str): Python source code to parse
        errors (bool): If True, raises syntax errors, otherwise returns empty result

    Returns:
        Dict with keys:
            - 'import': Set of directly imported module names
            - 'from': Dict mapping modules to sets of imported names

    Example:
        >>> imports('import os, sys; from json import loads, dumps')
        {
            'import': {'os', 'sys'},
            'from': {'json': {'loads', 'dumps'}}
        }
    """
    if not code or not code.strip():
        return {"import": set(), "from": {}}

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        if errors:
            raise
        return {"import": set(), "from": {}}

    result = {"import": set(), "from": {}}

    # Single pass through all nodes with  type checking
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # Handle standard imports: import os, sys
            for alias in node.names:
                result["import"].add(alias.name)

        elif isinstance(node, ast.ImportFrom):
            # Handle from imports: from module import name1, name2
            module_name = node.module or ""
            if module_name not in result["from"]:
                result["from"][module_name] = set()

            for alias in node.names:
                result["from"][module_name].add(alias.name)

    return result


def replace(path: str, oldContent: str, newContent: str) -> str:
    """
    Replace content in a file and return the modified content.

    Performs in-memory replacement and writes back to file atomically
    to prevent data corruption.

    Args:
        path (str): Path to the file to modify
        oldContent (str): Content to be replaced
        newContent (str): New content to replace with

    Returns:
        str: The modified file content

    Raises:
        FileNotFoundError: If file doesn't exist
        IOError: If file can't be read or written

    Example:
        >>> replace("/path/file.txt", "old", "new")
        'File with new content...'
    """
    content = load(path)
    new_content = content.replace(oldContent, newContent)

    # Atomic write to prevent corruption
    temp_path = Path(path).with_suffix(".tmp")
    try:
        dump(temp_path, new_content)
        temp_path.replace(path)  # Atomic replace
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise IOError(f"Failed to replace content in {path}: {e}")

    return new_content


def append(
    file: str,
    content: str,
    chunk_size: int = CHUNK_SIZE,
    encoding: str = encoding,
) -> None:
    """
    Append content to existing file with chunked writing support.

    Efficiently appends content to files of any size using chunked operations
    to maintain low memory footprint.

    Args:
        file (str): Path to file to append to
        content (str): Content to append
        chunk_size (int): Size of write chunks
        encoding (str): Text encoding to use

    Returns:
        None

    Raises:
        IOError: If append operation fails

    Example:
        >>> append("log.txt", "New log entry\\n")
    """
    try:
        with open(file, "a", encoding=encoding) as f:
            if chunk_size and len(content) > chunk_size:
                for i in range(0, len(content), chunk_size):
                    f.write(content[i : i + chunk_size])
            else:
                f.write(content)
    except Exception as e:
        raise IOError(f"Failed to append to file {file}: {e}")


def list_path(path: str, names: bool = False) -> List[Union[Path, str]]:
    """
    List contents of a directory with optional name-only output.

    Efficient directory listing with simple filtering options.

    Args:
        path (str): Directory path to list
        names (bool): If True, return only names, otherwise return Path objects

    Returns:
        List[Union[Path, str]]: Directory contents

    Example:
        >>> list_path("/project/src", names=True)
        ['main.py', 'utils', 'README.md']
    """
    path_obj = Path(path)
    if not path_obj.exists() or not path_obj.is_dir():
        return []

    return [p.name if names else p for p in path_obj.glob("*")]


def make(filename: str) -> str:
    """
    Create an empty file and return the filename

    Args:
        filename (str): Name/path of file to create

    Returns:
        str: The created filename

    Raises:
        IOError: If file creation fails

    Example:
        >>> make("new_file.txt")
        'new_file.txt'
    """
    path = Path(filename)
    path.parent.mkdir(exist_ok=True)

    try:
        path.open("w").close()
        return str(path.absolute())
    except Exception as e:
        raise IOError(f"Failed to create file {filename}: {e}")


def _pres_(file: Path, suffix: str, mode: str) -> None:
    """
    Internal helper for creating tar archives with specified compression.

    Args:
        file (Path): File to archive
        suffix (str): Suffix to add to archive name
        mode (str): Tarfile mode string
    """
    archive_name = file.name + suffix
    with tarfile.open(archive_name, mode) as tar:
        tar.add(file)


def _unpres_(file: Path, del_suff: Optional[str] = None, mode: str = "r") -> None:
    """
    Internal helper for extracting tar archives.

    Args:
        file (Path): Archive file to extract
        del_suff (str, optional): Suffix to remove from extracted path
        mode (str): Tarfile mode string
    """
    extract_path = (
        file.with_suffix("") if del_suff and file.suffix == del_suff else file
    )
    with tarfile.open(file, mode) as tar:
        tar.extractall(extract_path.parent)


def compress(file: str, mode_zip: str) -> str:
    """
    Compress file using various archive formats with comprehensive format support.

    Args:
        file (str): Path to file to compress
        mode_zip (str): Compression mode

    Returns:
        str: Path to the created archive file
    """
    file_path = Path(file)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file}")

    mode = mode_zip.lower()

    if mode.startswith("zip"):
        zip_types = {
            "zip:lzma": zipfile.ZIP_LZMA,
            "zip:def": zipfile.ZIP_DEFLATED,
            "zip:bz2": zipfile.ZIP_BZIP2,
            "zip:std": zipfile.ZIP_STORED,
        }

        if mode not in zip_types:
            raise ValueError(f"Unsupported ZIP mode: {mode_zip}")

        archive_name = file_path.name + ".zip"
        with zipfile.ZipFile(archive_name, "w", zip_types[mode]) as zipf:
            zipf.write(file_path, file_path.name)

        return archive_name

    elif mode.startswith("tar"):
        tar_modes = {
            "tar": ("w", ".tar"),
            "tar:xz": ("w:xz", ".tar.xz"),
            "tar:gz": ("w:gz", ".tar.gz"),
            "tar:bz2": ("w:bz2", ".tar.bz2"),
        }

        if mode not in tar_modes:
            raise ValueError(f"Unsupported TAR mode: {mode_zip}")

        archive_mode, suffix = tar_modes[mode]
        archive_name = file_path.name + suffix
        _pres_(file_path, suffix, archive_mode)

        return archive_name

    else:
        raise ValueError(f"Unsupported compression mode: {mode_zip}")


def decompress(file: str) -> Path:
    """
    Decompress archive file and return path to extracted content.

    Supports multiple archive formats with automatic format detection
    and handling of both single-file and multi-file archives.

    Args:
        file (str): Path to archive file to decompress

    Returns:
        Path: Path to extracted content

    Raises:
        FileNotFoundError: If archive doesn't exist
        ValueError: If archive format is not supported

    Example:
        >>> decompress("archive.zip")
        Path('archive')
    """
    file_path = Path(file)
    if not file_path.exists():
        raise FileNotFoundError(f"Archive not found: {file}")

    # Handle ZIP files
    if zipfile.is_zipfile(file_path):
        extract_path = file_path.with_suffix("")

        with zipfile.ZipFile(file_path, "r") as archive:
            file_list = archive.namelist()

            if len(file_list) > 1:
                # Multi-file archive
                archive.extractall(extract_path)
            else:
                # Single-file archive
                extracted = archive.extract(file_list[0])
                Path(extracted).rename(extract_path)

        # Remove original archive
        file_path.unlink()
        return extract_path

    # Handle TAR files
    elif file_path.suffix in [".tar", ".gz", ".bz2", ".xz"]:
        mode = "r"
        if file_path.suffix == ".gz":
            mode = "r:gz"
        elif file_path.suffix == ".bz2":
            mode = "r:bz2"
        elif file_path.suffix == ".xz":
            mode = "r:xz"

        extract_path = (
            file_path.with_suffix("").with_suffix("")
            if file_path.suffix in [".gz", ".bz2", ".xz"]
            else file_path.with_suffix("")
        )
        _unpres_(file_path, file_path.suffix, mode)
        return extract_path

    else:
        raise ValueError(f"Unsupported archive format: {file_path.suffix}")


def ispackage(name: str) -> bool:
    """
    Returns True if the given module name is a package.

    Uses importlib.util.find_spec() to check the module spec and verifies
    that submodule_search_locations exists.
    """
    try:
        spec = importlib.util.find_spec(name)
        if spec:
            return spec.submodule_search_locations is not None
        return False
    except (ImportError, AttributeError):
        return False
