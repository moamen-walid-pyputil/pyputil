#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import importlib.machinery
from string import ascii_letters, digits
from pathlib import Path


ALLOWED_SYMBOLS = ascii_letters + digits + "_"


def clean(name: str) -> str:
    """
    Remove all characters from a name except ASCII letters, digits and "_".

    Parameters
    ----------
    name : str
        Original name that may contain invalid characters.

    Returns
    -------
    str
        Name containing digits + ASCII letters +  "_"
    """
    name = Path(name).stem
    return "".join(c for c in name if c in ALLOWED_SYMBOLS)
    


def suffix() -> str:
    """
    Get the platform-specific extension module suffix.

    Returns
    -------
    str
        Extension suffix used for compiled Python modules
        (e.g. '.cp311-win_amd64.pyd', '.cpython-311-x86_64-linux-gnu.so').
    """
    return importlib.machinery.EXTENSION_SUFFIXES[0]


def compiled_name(name: str) -> str | None:
    """
    Build a compiled extension filename from a given name.

    The name is first sanitized to contain only ASCII letters,
    then the platform-specific extension suffix is appended.

    Parameters
    ----------
    name : str
        Base name of the module.

    Returns
    -------
    str | None
        Compiled module filename, or None if the name becomes empty
        after sanitization.
    """
    n = clean(name)

    if not n:
        return None

    return f"{n}{suffix()}"