#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Python Module Explorer (pmeX).

Main Components:
- pmeX: Main class for module exploration

Examples
--------
>>> import pyputil.core as pc
>>> explorer = pc.pmeX(math)
>>> explorer.inject("pi = 3.14")
>>> cloned = explorer.clone()
"""

from .core import pmeX

__all__ = ["pmeX"]
