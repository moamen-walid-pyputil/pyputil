#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import inspect
from types import ModuleType
from typing import Any, Optional

from .base import AttributeInfo, ModuleResult, AttributeType


def _analyze_attribute(
    attr: Any,
    name: str,
    is_private: bool,
    get_docstrings: bool = True,
    get_signatures: bool = True,
) -> AttributeInfo:
    """
    Analyze a single attribute and gather information about it.

    Parameters
    ----------
    attr : Any
        The attribute object to analyze
    name : str
        Name of the attribute
    is_private : bool
        Whether the attribute is private
    get_docstrings : bool, optional
        Whether to extract docstrings (default: True)
    get_signatures : bool, optional
        Whether to extract signatures (default: True)

    Returns
    -------
    AttributeInfo
        Information about the analyzed attribute
    """

    attr_info = AttributeInfo(
        name=name,
        type=AttributeType.UNKNOWN,
        is_private=is_private,
        is_callable=callable(attr),
    )

    # Determine attribute type
    if inspect.isfunction(attr):
        attr_info.type = AttributeType.FUNCTION
    elif inspect.isclass(attr):
        attr_info.type = AttributeType.CLASS
    elif inspect.ismodule(attr):
        attr_info.type = AttributeType.MODULE
    elif inspect.ismethod(attr):
        attr_info.type = AttributeType.METHOD
    elif inspect.isbuiltin(attr):
        attr_info.type = AttributeType.BUILTIN
    elif hasattr(type(attr), "__get__") and hasattr(type(attr), "__set__"):
        attr_info.type = AttributeType.PROPERTY
    else:
        attr_info.type = AttributeType.VARIABLE

    # Gather documentation
    if get_docstrings:
        try:
            attr_info.docstring = inspect.getdoc(attr)
        except:
            pass

    # Gather signature for callables
    if get_signatures and (inspect.isfunction(attr) or inspect.ismethod(attr)):
        try:
            sig = inspect.signature(attr)
            attr_info.signature = str(sig)
            attr_info.has_arguments = len(sig.parameters) > 0
        except (ValueError, TypeError):
            pass

    # Gather source information
    try:
        attr_info.source_file = inspect.getfile(attr)
        _, attr_info.source_line = inspect.getsourcelines(attr)
    except (TypeError, OSError):
        pass

    return attr_info
