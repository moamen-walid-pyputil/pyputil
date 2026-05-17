#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from enum import Enum


class PrivacyLevel(Enum):
    """
    Privacy levels for API members.

    Defines different levels of access control for API members.

    Attributes
    ----------
    PUBLIC : str
        Accessible to everyone
    PROTECTED : str
        Accessible within package and subclasses
    PRIVATE : str
        Accessible only within defining module/class
    INTERNAL : str
        Internal use only
    SECRET : str
        Requires authentication/authorization
    """

    PUBLIC = "public"
    PROTECTED = "protected"
    PRIVATE = "private"
    INTERNAL = "internal"
    SECRET = "secret"  # Requires authentication/authorization


class APIMemberType(Enum):
    """
    Types of API members.

    Categorizes different types of API members for metadata and handling.

    Attributes
    ----------
    FUNCTION : str
        Regular function
    CLASS : str
        Class definition
    MODULE : str
        Module/package
    VARIABLE : str
        Regular variable
    CONSTANT : str
        Constant (usually uppercase)
    PROPERTY : str
        Property descriptor
    METHOD : str
        Class method
    ASYNC_FUNCTION : str
        Async function
    ASYNC_METHOD : str
        Async method
    CONTEXT_MANAGER : str
        Context manager
    DECORATOR : str
        Decorator function
    GENERATOR : str
        Generator function
    """

    FUNCTION = "function"
    CLASS = "class"
    MODULE = "module"
    VARIABLE = "variable"
    CONSTANT = "constant"
    PROPERTY = "property"
    METHOD = "method"
    ASYNC_FUNCTION = "async_function"
    ASYNC_METHOD = "async_method"
    CONTEXT_MANAGER = "context_manager"
    DECORATOR = "decorator"
    GENERATOR = "generator"
