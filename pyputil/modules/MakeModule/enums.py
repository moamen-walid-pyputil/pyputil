#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from enum import Enum


class ModuleState(Enum):
    """
    Enumeration representing different states of a module.

    Attributes
    ----------
    CREATED : str
        Module has been created
    MODIFIED : str
        Module has been modified
    MOVED : str
        Module has been moved
    SYMLINKED : str
        Module has been symlinked
    PUBLISHED : str
        Module has been published
    BUILT : str
        Module has been built
    REMOVED : str
        Module has been removed
    """

    CREATED = "created"
    MODIFIED = "modified"
    MOVED = "moved"
    SYMLINKED = "symlinked"
    PUBLISHED = "published"
    BUILT = "built"
    REMOVED = "removed"
