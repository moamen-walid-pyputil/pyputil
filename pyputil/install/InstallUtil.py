#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from ..util import importable
from ..modules import isbuiltin, get_deps_from_code, get_module_deps
from typing import Optional, Literal, List
import sys
import site
import shutil
import sysconfig
from pathlib import Path


def _resolve_install_dir(
    target: Literal["site", "dynload"] = "site",
    path: Optional[str] = None
) -> Path:
    """
    Resolve the directory where a module or file should be installed.

    This function determines the correct installation directory depending
    on the target type. It can resolve either the standard ``site-packages``
    directory or the directory used for compiled extension modules
    (e.g. modules like ``math``).

    Parameters
    ----------
    target : {"site", "dynload"}, optional
        Type of installation directory:

        - ``"site"``
            Standard Python package directory (site-packages).
        - ``"dynload"``
            Directory for compiled extension modules
            (e.g. ``lib-dynload`` where modules like ``math`` live).

    path : str or None, optional
        Custom directory path. If provided, this path is used directly
        instead of resolving automatically.

    Returns
    -------
    Path
        Absolute resolved path to the installation directory.

    Raises
    ------
    FileNotFoundError
        If the resolved directory does not exist.
    ValueError
        If an invalid target is provided.

    Examples
    --------
    Get the site-packages directory:

    >>> _resolve_install_dir()
    Path('/usr/lib/python3.x/site-packages')

    Get the compiled modules directory:

    >>> _resolve_install_dir("dynload")
    Path('/usr/lib/python3.x/lib-dynload')

    Use a custom directory:

    >>> _resolve_install_dir(path="/custom/python/libs")
    Path('/custom/python/libs')
    """

    if path:
        p = Path(path)

    else:
        if target == "site":
            paths = site.getsitepackages()
            p = Path(paths[0])

        elif target == "dynload":
            dyn = sysconfig.get_config_var("DESTSHARED")
            if not dyn:
                raise FileNotFoundError("lib-dynload directory not found")
            p = Path(dyn)

        else:
            raise ValueError(f"Invalid target: {target}")

    if not p.exists():
        raise FileNotFoundError(f"Install directory not found: {p}")

    return p.resolve()


def install_file(
    filename: str,
    *,
    target: Literal["site", "dynload"] = "site",
    path: Optional[str] = None,
    mode: Literal["move", "copy", "symlink"] = "move",
    overwrite: bool = False,
) -> str:
    """
    Install a file into a Python library directory.

    This function places a file into a Python installation directory
    using one of three strategies: move, copy, or symbolic link.

    It can install files into:

    - ``site-packages`` for regular Python packages
    - ``lib-dynload`` for compiled extension modules

    Parameters
    ----------
    filename : str
        Path to the source file that will be installed.

    target : {"site", "dynload"}, optional
        Type of installation location.

        - ``"site"``
            Install into the standard ``site-packages`` directory.
        - ``"dynload"``
            Install into the compiled extension modules directory
            (e.g. where modules like ``math`` exist).

    path : str or None, optional
        Custom installation directory. If provided, this overrides
        automatic resolution.

    mode : {"move", "copy", "symlink"}, optional
        Method used to place the file into the installation directory.

        - ``"move"``
            Move the file (removes it from the original location).
        - ``"copy"``
            Copy the file while keeping the original.
        - ``"symlink"``
            Create a symbolic link pointing to the original file.

    overwrite : bool, optional
        If True, existing files will be replaced.

    Returns
    -------
    str
        Absolute path to the installed file.

    Raises
    ------
    FileNotFoundError
        If the source file does not exist.
    IsADirectoryError
        If the provided path is not a file.
    FileExistsError
        If the destination already exists and overwrite is False.
    PermissionError
        If Python does not have permission to write to the directory.
    ValueError
        If an invalid mode or target is provided.

    Examples
    --------
    Install a normal Python module:

    >>> install_file("mymodule.py")

    Copy a module instead of moving it:

    >>> install_file("mymodule.py", mode="copy")

    Install a compiled extension module:

    >>> install_file("fastmath.so", target="dynload")

    Create a symbolic link inside site-packages:

    >>> install_file("devmodule.py", mode="symlink")

    Overwrite an existing module:

    >>> install_file("mymodule.py", overwrite=True)

    Notes
    -----
    Installing into system directories may require administrator
    privileges depending on the operating system and Python setup.

    Compiled modules installed into ``lib-dynload`` should match
    the current Python ABI version to avoid import errors.
    """

    src = Path(filename).expanduser().resolve()

    if not src.exists():
        raise FileNotFoundError(f"Source file does not exist: {src}")

    if not src.is_file():
        raise IsADirectoryError(f"Expected file, got directory: {src}")

    install_dir = _resolve_install_dir(target, path)
    dst = install_dir / src.name

    if dst.exists() or dst.is_symlink():
        if not overwrite:
            raise FileExistsError(f"File already exists: {dst}")
        dst.unlink()

    try:
        if mode == "copy":
            shutil.copy2(src, dst)

        elif mode == "move":
            shutil.move(str(src), dst)

        elif mode == "symlink":
            dst.symlink_to(src)

        else:
            raise ValueError(f"Invalid mode: {mode}")

    except PermissionError:
        raise PermissionError(
            f"Permission denied writing to {install_dir}"
        )

    return str(dst)


def install_path(
    dirname: str,
    *,
    target: Literal["site", "dynload"] = "site",
    path: Optional[str] = None,
    mode: Literal["move", "copy", "symlink"] = "move",
    overwrite: bool = False,
) -> str:
    """
    Install a directory into a Python library directory.

    This function installs a directory (such as a Python package) into
    a Python installation location using one of three strategies:
    move, copy, or symbolic link.

    It is commonly used for installing full packages that contain
    multiple modules, resources, or compiled extensions.

    Parameters
    ----------
    dirname : str
        Path to the source directory to install.

    target : {"site", "dynload"}, optional
        Type of installation location.

        - ``"site"``
            Install into the standard ``site-packages`` directory.
        - ``"dynload"``
            Install into the compiled extension modules directory.

    path : str or None, optional
        Custom installation directory. If provided, this overrides
        automatic resolution.

    mode : {"move", "copy", "symlink"}, optional
        Method used to install the directory.

        - ``"move"``
            Move the directory (removes it from the original location).
        - ``"copy"``
            Copy the directory recursively.
        - ``"symlink"``
            Create a symbolic link pointing to the directory.

    overwrite : bool, optional
        If True, existing directories will be replaced.

    Returns
    -------
    str
        Absolute path to the installed directory.

    Raises
    ------
    FileNotFoundError
        If the source directory does not exist.
    NotADirectoryError
        If the provided path is not a directory.
    FileExistsError
        If the destination already exists and overwrite is False.
    PermissionError
        If Python does not have permission to write to the directory.
    ValueError
        If an invalid mode or target is provided.

    Examples
    --------
    Install a package directory:

    >>> install_path("mypackage")

    Copy the package instead of moving it:

    >>> install_path("mypackage", mode="copy")

    Create a symbolic link for development:

    >>> install_path("mypackage", mode="symlink")

    Install into a custom directory:

    >>> install_path("mypackage", path="/custom/python/libs")
    """

    src = Path(dirname).expanduser().resolve()

    if not src.exists():
        raise FileNotFoundError(f"Source directory does not exist: {src}")

    if not src.is_dir():
        raise NotADirectoryError(f"Expected directory, got file: {src}")

    install_dir = _resolve_install_dir(target, path)
    dst = install_dir / src.name

    if dst.exists() or dst.is_symlink():
        if not overwrite:
            raise FileExistsError(f"Directory already exists: {dst}")

        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()

    try:
        if mode == "copy":
            shutil.copytree(src, dst)

        elif mode == "move":
            shutil.move(str(src), dst)

        elif mode == "symlink":
            dst.symlink_to(src, target_is_directory=True)

        else:
            raise ValueError(f"Invalid mode: {mode}")

    except PermissionError:
        raise PermissionError(
            f"Permission denied writing to {install_dir}"
        )

    return str(dst)


def get_uninstalled_packages(
    file_or_code: str, 
    allow_relative_import: bool = True,
    ignore: List[str] = None
) -> List[str]:
    """
    Identify Python modules that are required but not installed.

    This function analyzes either a file path or a string of Python code,
    extracts all imported modules, and returns a list of modules that are
    not built-in and cannot be imported in the current environment.

    Parameters
    ----------
    file_or_code : str
        A file path to a Python script or a string containing Python code.

    allow_relative_import : bool, optional
        Whether to include relative imports (e.g., ``from .module import x``)
        in the analysis. If False, relative imports are ignored.
        Default is True.

    ignore : List[str], optional
        A list of module names to ignore during the check. Any module in this
        list will be excluded from the result even if it is not importable.
        Default is None.

    Returns
    -------
    List[str]
        A sorted list of unique module names that are not installed or
        cannot be imported.

    Notes
    -----
    - Built-in modules (e.g., ``sys``) are ignored.
    - Relative imports can be optionally excluded using ``allow_relative_import``.

    Examples
    --------
    >>> get_uninstalled_packages("script.py")
    ['requests', 'numpy']

    >>> get_uninstalled_packages("import os\\nimport fake_module")
    ['fake_module']

    >>> get_uninstalled_packages("from .utils import x", allow_relative_import=False)
    []

    >>> get_uninstalled_packages("import numpy, pandas", ignore=["numpy"])
    ['pandas']
    """
    path: Path = Path(file_or_code)
    uninstalled: List[str] = []
    deps: List[str] = []

    if path.exists():
        deps = get_module_deps(path).all_modules
    else:
        deps = get_deps_from_code(file_or_code).all_modules

    for dep in deps:
        if isbuiltin(dep): 
            continue

        if not allow_relative_import and dep.startswith("."): 
            continue

        if ignore and dep in ignore: 
            continue

        if not importable(dep): 
            uninstalled.append(dep)

    return sorted(set(uninstalled))

    
