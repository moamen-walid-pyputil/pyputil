#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
 Object Introspection and Analysis Module.

This module provides comprehensive tools for deep inspection, analysis,
and metadata extraction from Python objects. It supports functions,
classes, modules, methods, properties, descriptors, and various other
Python constructs with robust error handling.
"""

from typing import (
    Any, Dict, List, Union, Optional, Set, Tuple, Callable,
    get_type_hints, get_origin, get_args
)
from types import (
    FunctionType, BuiltinFunctionType, MethodType,
    ModuleType, CodeType, MethodDescriptorType,
    MemberDescriptorType, GetSetDescriptorType,
    ClassMethodDescriptorType, WrapperDescriptorType,
    MethodWrapperType, CoroutineType, AsyncGeneratorType,
    GeneratorType, TracebackType, FrameType,
    MappingProxyType, BuiltinMethodType
)
import inspect
import sys
from textwrap import dedent
from pathlib import Path
from functools import lru_cache
from .utils import get_code, create_dict


# Type aliases for internal use
_AttributeInfo = Dict[str, Any]
_CategoryResult = List[str]
_TypeDict = Dict[str, str]


def __info_dict__(obj: Any) -> Dict[str, Any]:
    """
    Generate a comprehensive metadata dictionary for any Python object.

    This function safely extracts fundamental information about a Python object,
    including its name, representation, type, memory footprint, source location,
    and documentation. All extraction operations are wrapped in individual
    try-except blocks to ensure robustness against objects with missing or
    inaccessible attributes.

    Parameters
    ----------
    obj : Any
        The target Python object to analyze. Can be any valid Python object
        including functions, classes, modules, instances, builtins, or
        objects from C extensions.

    Returns
    -------
    Dict[str, Any]
        A dictionary containing comprehensive object metadata with the
        following keys:

        - **object** : Any
            Reference to the original object (unchanged).
        - **name** : str or None
            The object's ``__name__`` attribute if available, else None.
            For classes and functions, this is their declared name.
        - **qualname** : str or None
            The object's ``__qualname__`` if available (Python 3.3+),
            providing the fully qualified name including class context.
        - **repr** : str
            Safe textual representation via :func:`repr`. Falls back to
            ``"<representation unavailable>"`` if repr() raises an exception.
        - **type** : str
            The name of the object's type (i.e., ``type(obj).__name__``).
            For metaclasses, this returns the metaclass name.
        - **module** : str or None
            The ``__module__`` attribute if available, indicating where
            the object was defined.
        - **location** : str or None
            Absolute file path where the object is defined, extracted via
            :func:`inspect.getfile`. Returns None for builtins and
            dynamically created objects.
        - **size** : int or None
            Memory size in bytes as reported by :func:`sys.getsizeof`.
            Returns None if the size cannot be determined (e.g., for
            objects that don't support sizeof).
        - **doc** : str or None
            The object's docstring (``__doc__`` attribute) if available.
        - **annotations** : Dict[str, Any] or None
            Type annotations if available via :func:`typing.get_type_hints`.
        - **is_callable** : bool
            Whether the object is callable (i.e., can be invoked as a function).
        - **is_builtin** : bool
            Whether the object is a built-in type or function (implemented in C).
        - **is_abstract** : bool
            Whether the object is an abstract base class.
        - **base_classes** : List[str]
            List of base class names if the object is a class, empty list otherwise.
        - **mro** : List[str]
            Method Resolution Order as a list of class names if applicable.

    Raises
    ------
    This function intentionally catches all exceptions internally and
    never raises them to the caller, ensuring safe introspection of
    any object.

    Notes
    -----
    - For objects implemented in C extensions, location and source-related
      fields may be None.
    - Memory size is approximate and does not include memory referenced
      by the object's attributes.
    - The function uses individual try-except blocks for each extraction
      to maximize the amount of information gathered even when some
      attributes are inaccessible.

    Examples
    --------
    >>> def example_function(x: int) -> str:
    ...     '''Convert integer to string.'''
    ...     return str(x)
    ...
    >>> info = __info_dict__(example_function)
    >>> info['name']
    'example_function'
    >>> info['type']
    'function'
    >>> info['doc']
    'Convert integer to string.'
    >>> info['annotations']
    {'x': <class 'int'>, 'return': <class 'str'>}

    >>> import math
    >>> info = __info_dict__(math.sqrt)
    >>> info['is_builtin']
    True
    >>> info['location'] is None
    True
    """
    # Safe repr extraction
    try:
        obj_repr = repr(obj)
    except Exception:
        obj_repr = "<representation unavailable>"

    # Safe size extraction
    try:
        obj_size = sys.getsizeof(obj)
    except (TypeError, AttributeError):
        obj_size = None

    # Safe location extraction
    try:
        obj_location = inspect.getfile(obj)
    except (TypeError, OSError):
        obj_location = None

    # Safe module extraction
    obj_module = getattr(obj, "__module__", None)

    # Safe qualname extraction
    obj_qualname = getattr(obj, "__qualname__", None)

    # Safe annotations extraction
    try:
        obj_annotations = get_type_hints(obj)
    except (TypeError, AttributeError, NameError):
        obj_annotations = None

    # Callable check
    obj_is_callable = callable(obj)

    # Check if builtin
    obj_is_builtin = (
        inspect.isbuiltin(obj) or
        (isinstance(obj, type) and hasattr(obj, '__module__') and
         getattr(obj, '__module__') == 'builtins')
    )

    # Check if abstract
    obj_is_abstract = (
        inspect.isabstract(obj) if isinstance(obj, type) else False
    )

    # Base classes and MRO
    base_classes = []
    mro_list = []
    if isinstance(obj, type):
        try:
            base_classes = [
                base.__name__ for base in obj.__bases__
                if base is not object
            ]
            mro_list = [cls.__name__ for cls in inspect.getmro(obj)]
        except AttributeError:
            pass

    return {
        "object": obj,
        "name": getattr(obj, "__name__", None),
        "qualname": obj_qualname,
        "repr": obj_repr,
        "type": type(obj).__name__,
        "module": obj_module,
        "location": obj_location,
        "size": obj_size,
        "doc": inspect.getdoc(obj) or getattr(obj, "__doc__", None),
        "annotations": obj_annotations,
        "is_callable": obj_is_callable,
        "is_builtin": obj_is_builtin,
        "is_abstract": obj_is_abstract,
        "base_classes": base_classes,
        "mro": mro_list,
    }


class ObjectParser:
    """
     object inspector for comprehensive runtime analysis.

    This class performs deep introspection and categorization of any
    Python object's attributes. It goes beyond simple ``dir()`` to
    classify attributes by their runtime characteristics: methods,
    static methods, class methods, properties, descriptors, generators,
    coroutines, slots, annotations, and more.

    The parser is designed for use in debugging, documentation generation,
    IDE tooling, serialization frameworks, and dynamic code analysis.
    All inspection methods are read-only and do not modify the target object.

    Parameters
    ----------
    obj : Any
        The Python object to inspect. Can be an instance, class, module,
        function, or any other Python entity.

    Attributes
    ----------
    obj : Any
        The original object being inspected.
    obj_type : type
        The type of the original object (i.e., ``type(obj)``).
    type_name : str
        String representation of the type (e.g., ``'function'``, ``'type'``).
    dict : Dict[str, Any]
        Comprehensive metadata dictionary from :func:`__info_dict__`.
    namespace : Dict[str, Any]
        Object's ``__dict__`` or equivalent, safely extracted via `utils.create_dict`.
    code : CodeType or None
        The code object if available (functions, methods, classes).
    attrs : List[str]
        Complete list of attribute names from ``dir(obj)``.
    class_attrs : Dict[str, Any]
        Class-level attributes from ``type(obj).__dict__`` if applicable.

    Raises
    ------
    TypeError
        If the input cannot be processed (raised only in extreme edge cases
        where even basic type inspection fails).

    Warnings
    --------
    - Accessing certain attributes (especially properties and descriptors)
      may trigger side effects in poorly designed objects.
    - The parser uses :func:`getattr` but never calls methods unless
      ``call=True`` in the :meth:`get` method.
    - For objects with ``__slots__``, the namespace dictionary may be
      smaller than expected since slot attributes are stored differently.

    See Also
    --------
    inspect.getmembers : Standard library attribute listing.
    dir : Built-in attribute listing.
    typing.get_type_hints : Type hint extraction.

    Examples
    --------
    >>> class Example:
    ...     '''A sample class for demonstration.'''
    ...
    ...     class_var: int = 100
    ...     __slots__ = ('name', 'value')
    ...
    ...     def __init__(self, name: str, value: float = 0.0):
    ...         self.name = name
    ...         self.value = value
    ...
    ...     @property
    ...     def display_name(self) -> str:
    ...         return f"Item: {self.name}"
    ...
    ...     @staticmethod
    ...     def factory() -> 'Example':
    ...         return Example("default")
    ...
    ...     @classmethod
    ...     def from_dict(cls, data: dict) -> 'Example':
    ...         return cls(**data)
    ...
    ...     def compute(self, multiplier: int = 1) -> float:
    ...         '''Multiply the value.'''
    ...         return self.value * multiplier
    ...
    ...     def _private_helper(self) -> None:
    ...         pass
    ...
    ...     def __str__(self) -> str:
    ...         return f"Example({self.name}, {self.value})"
    ...
    >>> obj = Example("test", 42.0)
    >>> parser = ObjectParser(obj)
    >>>
    >>> parser.type_name
    'Example'
    >>>
    >>> parser.methods()
    ['_private_helper', 'compute']
    >>>
    >>> parser.properties()
    ['display_name']
    >>>
    >>> parser.staticmethods()
    ['factory']
    >>>
    >>> parser.classmethods()
    ['from_dict']
    >>>
    >>> parser.magic_methods()
    ['__str__']
    >>>
    >>> parser.slots()
    ['name', 'value']
    >>>
    >>> parser.description()
    {'name': 'str', 'value': 'float'}
    >>>
    >>> parser.annotations()
    {'class_var': <class 'int'>}
    >>>
    >>> parser.body("compute")
    'def compute(self, multiplier: int = 1) -> float:\\n    \\'\\'\\'Multiply the value.\\'\\'\\'\\n    return self.value * multiplier\\n'

    Edge Cases
    ----------
    >>> import math
    >>> parser = ObjectParser(math)
    >>> len(parser.builtins()) > 0
    True
    >>> parser.location()  # doctest: +SKIP
    '/usr/lib/python3/lib-dynload/math.cpython-*.so'
    """

    # Class-level constant for descriptor type classification
    _DESCRIPTOR_TYPES: Tuple[type, ...] = (
        MethodDescriptorType,
        MemberDescriptorType,
        GetSetDescriptorType,
        ClassMethodDescriptorType,
        WrapperDescriptorType,
    )

    # Builtin method types
    _BUILTIN_METHOD_TYPES: Tuple[type, ...] = (
        BuiltinMethodType,
        MethodWrapperType,
    )

    def __init__(self, obj: Any) -> None:
        self.obj = obj
        self.obj_type = type(obj)
        self.type_name = self.obj_type.__name__

        # Extract metadata
        self.dict = __info_dict__(obj)

        # Extract namespace safely
        self.namespace: Dict[str, Any] = create_dict(obj)

        # Extract code object
        self.code: Optional[CodeType] = get_code(obj)

        # Get all attributes
        self.attrs: List[str] = dir(obj)

        # Get class-level attributes (if applicable)
        self.class_attrs: Dict[str, Any] = self._extract_class_attrs()

        # Cache for expensive operations
        self._cached_variables: Optional[List[str]] = None
        self._cached_callable: Optional[List[str]] = None

    def _extract_class_attrs(self) -> Dict[str, Any]:
        """
        Safely extract class-level attributes from type hierarchy.

        This method gathers attributes from the object's type and all its
        parent classes, respecting the MRO. It handles exceptions for
        objects without a standard ``__dict__`` (e.g., built-in types).

        Returns
        -------
        Dict[str, Any]
            Dictionary of class-level attribute names to their values.
            Empty dict for objects without class attributes or if
            extraction fails.
        """
        class_attrs: Dict[str, Any] = {}

        try:
            # Get the type to inspect
            target_type = self.obj if isinstance(self.obj, type) else type(self.obj)

            # Walk through MRO to collect class attributes
            for cls in inspect.getmro(target_type):
                try:
                    cls_dict = cls.__dict__
                    if isinstance(cls_dict, MappingProxyType):
                        cls_dict = dict(cls_dict)
                    class_attrs.update(cls_dict)
                except AttributeError:
                    continue
        except Exception:
            pass

        return class_attrs

    @property
    def location(self) -> Optional[str]:
        """
        Get the file path where the object is defined.

        Returns
        -------
        str or None
            Absolute path to the source file, or None for builtins
            and dynamically created objects.

        Examples
        --------
        >>> import os
        >>> parser = ObjectParser(os.path)
        >>> parser.location is not None
        True
        """
        return self.dict.get("location")

    @property
    def module(self) -> Optional[str]:
        """
        Get the module name where the object is defined.

        Returns
        -------
        str or None
            Module name string, or None if not available.
        """
        return self.dict.get("module")

    def description(self) -> Dict[str, str]:
        """
        Generate a mapping of attribute names to their type names.

        Returns only attributes found in the instance namespace (``__dict__``
        or ``__slots__``), not including class-level attributes or methods.

        Returns
        -------
        Dict[str, str]
            Dictionary where keys are attribute names and values are
            their type names (e.g., ``{'name': 'str', 'count': 'int'}``).

        Notes
        -----
        - For objects using ``__slots__``, slot values are included if
          they are initialized.
        - Class-level attributes and methods are excluded from this view.
        - Use :meth:`class_attributes` to see class-level definitions.

        Examples
        --------
        >>> class Point:
        ...     def __init__(self, x: float, y: float):
        ...         self.x = x
        ...         self.y = y
        ...         self.label = "origin"
        ...
        >>> parser = ObjectParser(Point(1.0, 2.0))
        >>> desc = parser.description()
        >>> sorted(desc.keys())
        ['label', 'x', 'y']
        >>> desc['x']
        'float'
        """
        return {
            name: type(value).__name__
            for name, value in self.namespace.items()
        }

    def get(self, name: str, call: bool = False, *args: Any, **kwargs: Any) -> Any:
        """
        Retrieve an attribute value safely, optionally calling it.

        Uses :func:`inspect.getattr_static` for safe attribute access
        without triggering descriptors or properties prematurely.

        Parameters
        ----------
        name : str
            The attribute name to retrieve.
        call : bool, optional
            If True and the attribute is callable, invoke it with
            ``*args`` and ``**kwargs`` and return the result.
            Default is False (return the attribute itself).
        *args : Any
            Positional arguments to pass if calling the attribute.
        **kwargs : Any
            Keyword arguments to pass if calling the attribute.

        Returns
        -------
        Any
            - The attribute value if ``call=False``.
            - The result of calling the attribute if ``call=True`` and
              the attribute is callable.
            - None if the attribute does not exist.

        Raises
        ------
        This method catches all exceptions internally and returns None
        on failure. Use with caution when ``call=True`` as the callable
        may have side effects.

        Warns
        -----
        When ``call=True``, the method will invoke the attribute with
        the provided arguments. Ensure this is safe for your use case
        (e.g., database queries, network calls, or state mutations).

        Examples
        --------
        >>> class Counter:
        ...     def __init__(self):
        ...         self.count = 0
        ...     def increment(self, amount: int = 1) -> int:
        ...         self.count += amount
        ...         return self.count
        ...
        >>> parser = ObjectParser(Counter())
        >>> parser.get("count")
        0
        >>> parser.get("increment", call=True, amount=5)
        5
        >>> parser.get("nonexistent") is None
        True
        """
        try:
            obj = inspect.getattr_static(self.obj, name, None)
        except AttributeError:
            return None

        if obj is None:
            return None

        if callable(obj) and call:
            try:
                return obj(*args, **kwargs)
            except Exception:
                return None

        return obj

    def _filter(
        self,
        *types: type,
        include_subclasses: bool = True,
        source: str = "instance"
    ) -> List[str]:
        """
        Filter attributes by type, with optional MRO-aware matching.

        Parameters
        ----------
        *types : type
            One or more Python types to match against attribute values.
        include_subclasses : bool, optional
            If True (default), match subclasses of the specified types
            as well (using :func:`isinstance`). If False, require exact
            type match (using ``type(value) in types``).
        source : {"instance", "class", "both"}, optional
            - ``"instance"``: Search in the object's ``__dict__`` (default).
            - ``"class"``: Search in the object's class ``__dict__``.
            - ``"both"``: Search in both and merge results.

        Returns
        -------
        List[str]
            Names of attributes matching the specified types.
            Sorted alphabetically for consistency.

        Notes
        -----
        This method underpins most categorization helpers
        (:meth:`functions`, :meth:`methods`, :meth:`classes`, etc.).

        See Also
        --------
        functions : List user-defined functions.
        methods : List bound methods.
        builtins : List built-in functions.
        classes : List nested classes.
        """
        if not types:
            return []

        result_set: Set[str] = set()

        def check_value(value: Any) -> bool:
            """Check if value matches any of the target types."""
            if include_subclasses:
                return isinstance(value, types)
            return type(value) in types

        # Search in instance namespace
        if source in ("instance", "both"):
            for name in self.attrs:
                try:
                    value = getattr(self.obj, name, None)
                    if check_value(value):
                        result_set.add(name)
                except Exception:
                    continue

        # Search in class namespace
        if source in ("class", "both"):
            for name, value in self.class_attrs.items():
                if check_value(value):
                    result_set.add(name)

        return sorted(result_set)

    def functions(self) -> List[str]:
        """
        List user-defined functions in the object's namespace.

        Identifies attributes that are instances of
        :class:`types.FunctionType`.

        Returns
        -------
        List[str]
            Alphabetically sorted list of function names.

        See Also
        --------
        methods : Bound methods of an instance.
        builtins : Built-in functions (C-implemented).
        callable : All callable attributes.

        Examples
        --------
        >>> import math
        >>> parser = ObjectParser(math)
        >>> 'sqrt' in parser.functions()
        False  # math.sqrt is a builtin, not FunctionType
        >>> 'sqrt' in parser.builtins()
        True
        """
        return self._filter(FunctionType)

    def methods(self) -> List[str]:
        """
        List bound methods of the object.

        Returns methods that are bound to this specific instance
        (i.e., instances of :class:`types.MethodType`). This excludes
        static methods, class methods, and unbound functions.

        Returns
        -------
        List[str]
            Alphabetically sorted list of bound method names.

        Notes
        -----
        - Bound methods are methods that have ``self`` already bound to
          the instance, e.g., ``obj.method`` yields a bound method.
        - This does not include special methods (``__dunder__``) unless
          they are explicitly defined in the instance's namespace.

        Examples
        --------
        >>> class Calculator:
        ...     def add(self, a: int, b: int) -> int:
        ...         return a + b
        ...     @staticmethod
        ...     def version() -> str:
        ...         return "1.0"
        ...     @classmethod
        ...     def create(cls) -> 'Calculator':
        ...         return cls()
        ...
        >>> parser = ObjectParser(Calculator())
        >>> parser.methods()
        ['add']
        >>> 'version' in parser.methods()
        False
        >>> 'create' in parser.methods()
        False
        """
        return self._filter(MethodType)

    def classes(self) -> List[str]:
        """
        List nested classes within the object.

        Identifies attributes that are classes themselves
        (i.e., instances of :class:`type`).

        Returns
        -------
        List[str]
            Alphabetically sorted list of nested class names.

        Examples
        --------
        >>> class Outer:
        ...     class Inner:
        ...         pass
        ...     class Helper:
        ...         pass
        ...
        >>> parser = ObjectParser(Outer())
        >>> parser.classes()
        []  # Classes are on the class, not the instance
        >>> parser_class = ObjectParser(Outer)
        >>> sorted(parser_class.classes())
        ['Helper', 'Inner']
        """
        return self._filter(type)

    def variables(self) -> List[str]:
        """
        Identify all non-callable data attributes (variables).

        This method filters out functions, methods, classes, modules,
        code objects, properties, descriptors, and other callable or
        structural attributes, returning only plain data attributes.

        Returns
        -------
        List[str]
            Alphabetically sorted list of variable names.

        Notes
        -----
        Variables are defined as attributes that are:
        - Not callable
        - Not a module
        - Not a class/type
        - Not a code object
        - Not a property (instance of :class:`property`)
        - Not any descriptor type

        This method uses caching for performance; cache is invalidated
        when new attributes are added to the object.

        Examples
        --------
        >>> class Configuration:
        ...     DEFAULT_PORT: int = 8080  # Class variable
        ...     def __init__(self):
        ...         self.host: str = "localhost"  # Instance variable
        ...         self.ports: List[int] = [80, 443]
        ...
        ...     def validate(self) -> bool:
        ...         return len(self.ports) > 0
        ...
        >>> parser = ObjectParser(Configuration())
        >>> sorted(parser.variables())
        ['host', 'ports']
        # Note: DEFAULT_PORT is a class variable, not in instance namespace
        """
        if self._cached_variables is not None:
            return self._cached_variables

        # Gather all structural/callable names to exclude
        exclude_sets: List[Set[str]] = [
            set(self.callable()),
            set(self.modules()),
            set(self.classes()),
            set(self.code_objects()),
            set(self.properties()),
            set(self.descriptors()),
        ]

        # Build the exclusion set
        excluded: Set[str] = set()
        for excl_set in exclude_sets:
            excluded.update(excl_set)

        # Select names not in any exclusion set
        variables = sorted(
            name for name in self.attrs
            if name not in excluded
        )

        self._cached_variables = variables
        return variables

    def builtins(self) -> List[str]:
        """
        List built-in function attributes.

        Identifies attributes that are instances of
        :class:`types.BuiltinFunctionType`.

        Returns
        -------
        List[str]
            Alphabetically sorted list of built-in function names.

        Notes
        -----
        Built-in functions are implemented in C and have no Python
        source code. They are typically found in modules like ``math``,
        ``os``, ``sys``, etc.

        Examples
        --------
        >>> import math
        >>> parser = ObjectParser(math)
        >>> 'sin' in parser.builtins()
        True
        >>> 'sqrt' in parser.builtins()
        True
        >>> 'pi' in parser.builtins()
        False  # pi is a float, not a function
        """
        return self._filter(BuiltinFunctionType)

    def modules(self) -> List[str]:
        """
        List module attributes within the object.

        Identifies attributes that are instances of
        :class:`types.ModuleType`.

        Returns
        -------
        List[str]
            Alphabetically sorted list of module names.

        Examples
        --------
        >>> import sys
        >>> parser = ObjectParser(sys.modules['__main__'])
        >>> 'os' in parser.modules()
        True  # If os is imported in __main__
        """
        return self._filter(ModuleType)

    def properties(self) -> List[str]:
        """
        List ``@property`` decorated attributes.

        Identifies attributes that are instances of :class:`property`
        at the class level. This correctly handles properties defined
        using the ``@property`` decorator.

        Returns
        -------
        List[str]
            Alphabetically sorted list of property names.

        Notes
        -----
        Properties are detected by inspecting the class's ``__dict__``,
        not the instance, because accessing a property on an instance
        triggers its getter and returns the computed value, not the
        property object itself.

        Examples
        --------
        >>> class Temperature:
        ...     def __init__(self, celsius: float):
        ...         self._celsius = celsius
        ...
        ...     @property
        ...     def fahrenheit(self) -> float:
        ...         return self._celsius * 9/5 + 32
        ...
        ...     @property
        ...     def kelvin(self) -> float:
        ...         return self._celsius + 273.15
        ...
        >>> parser = ObjectParser(Temperature(25.0))
        >>> sorted(parser.properties())
        ['fahrenheit', 'kelvin']
        """
        # Check class-level for property objects
        if isinstance(self.obj, type):
            target = self.obj
        else:
            target = type(self.obj)

        return sorted([
            name
            for name, value in target.__dict__.items()
            if isinstance(value, property)
        ])

    def staticmethods(self) -> List[str]:
        """
        List ``@staticmethod`` decorated methods.

        Identifies methods that are wrapped with :class:`staticmethod`
        at the class level.

        Returns
        -------
        List[str]
            Alphabetically sorted list of static method names.

        See Also
        --------
        classmethods : Class method equivalents.
        methods : Regular instance methods.

        Examples
        --------
        >>> class Utility:
        ...     @staticmethod
        ...     def normalize(text: str) -> str:
        ...         return text.strip().lower()
        ...
        ...     @staticmethod
        ...     def is_valid(value: int) -> bool:
        ...         return value > 0
        ...
        >>> parser = ObjectParser(Utility)
        >>> sorted(parser.staticmethods())
        ['is_valid', 'normalize']
        """
        if isinstance(self.obj, type):
            target = self.obj
        else:
            target = type(self.obj)

        return sorted([
            name
            for name, value in target.__dict__.items()
            if isinstance(value, staticmethod)
        ])

    def classmethods(self) -> List[str]:
        """
        List ``@classmethod`` decorated methods.

        Identifies methods that are wrapped with :class:`classmethod`
        at the class level.

        Returns
        -------
        List[str]
            Alphabetically sorted list of class method names.

        See Also
        --------
        staticmethods : Static method equivalents.
        methods : Regular instance methods.

        Examples
        --------
        >>> class Factory:
        ...     @classmethod
        ...     def from_string(cls, data: str) -> 'Factory':
        ...         return cls(data)
        ...
        ...     @classmethod
        ...     def default(cls) -> 'Factory':
        ...         return cls("default")
        ...
        >>> parser = ObjectParser(Factory)
        >>> sorted(parser.classmethods())
        ['default', 'from_string']
        """
        if isinstance(self.obj, type):
            target = self.obj
        else:
            target = type(self.obj)

        return sorted([
            name
            for name, value in target.__dict__.items()
            if isinstance(value, classmethod)
        ])

    def descriptors(self) -> List[str]:
        """
        List descriptor protocol implementations.

        Descriptors are objects that implement ``__get__``, ``__set__``,
        or ``__delete__`` methods. This includes built-in descriptor
        types like :class:`MethodDescriptorType`, :class:`MemberDescriptorType`,
        :class:`GetSetDescriptorType`, etc.

        Returns
        -------
        List[str]
            Alphabetically sorted list of descriptor names found in
            the class hierarchy.

        Notes
        -----
        Descriptors are the mechanism behind properties, methods,
        static methods, and class methods. This method returns all
        descriptor instances, not just user-defined ones.

        Examples
        --------
        >>> class DataDescriptor:
        ...     def __get__(self, obj, objtype=None):
        ...         return 42
        ...     def __set__(self, obj, value):
        ...         pass
        ...
        >>> class Container:
        ...     data = DataDescriptor()
        ...
        >>> parser = ObjectParser(Container)
        >>> 'data' in parser.descriptors()
        True
        """
        if isinstance(self.obj, type):
            target = self.obj
        else:
            target = type(self.obj)

        descriptor_names: Set[str] = set()

        for cls in inspect.getmro(target):
            for name, value in cls.__dict__.items():
                if isinstance(value, self._DESCRIPTOR_TYPES):
                    descriptor_names.add(name)
                # Check for custom descriptors
                elif (
                    hasattr(value, '__get__') or
                    hasattr(value, '__set__') or
                    hasattr(value, '__delete__')
                ):
                    descriptor_names.add(name)

        return sorted(descriptor_names)

    def magic_methods(self) -> List[str]:
        """
        List magic (dunder) method names.

        Magic methods are special methods surrounded by double underscores
        (e.g., ``__init__``, ``__str__``, ``__repr__``).

        Returns
        -------
        List[str]
            Alphabetically sorted list of magic method names.

        Notes
        -----
        - This includes built-in magic methods inherited from ``object``
          and any custom overrides.
        - The naming convention follows the pattern ``__name__``.

        Examples
        --------
        >>> class Item:
        ...     def __init__(self, name: str):
        ...         self.name = name
        ...     def __str__(self) -> str:
        ...         return self.name
        ...     def __eq__(self, other) -> bool:
        ...         return self.name == other.name
        ...
        >>> parser = ObjectParser(Item("test"))
        >>> '__str__' in parser.magic_methods()
        True
        >>> '__eq__' in parser.magic_methods()
        True
        """
        return sorted(
            attr for attr in self.attrs
            if len(attr) > 4
            and attr.startswith("__")
            and attr.endswith("__")
        )

    def private(self) -> List[str]:
        """
        List private and protected attribute names.

        Returns names that start with a single underscore (``_``)
        but not double underscore (``__``). These are conventionally
        considered "protected" or "internal" attributes.

        Returns
        -------
        List[str]
            Alphabetically sorted list of private/protected attribute names.

        See Also
        --------
        name_mangled : Name-mangled attributes (double underscore prefix).

        Examples
        --------
        >>> class Database:
        ...     def __init__(self):
        ...         self._connection = None
        ...         self._closed = False
        ...         self.public_flag = True
        ...
        >>> parser = ObjectParser(Database())
        >>> sorted(parser.private())
        ['_closed', '_connection']
        """
        return sorted(
            attr for attr in self.attrs
            if attr.startswith("_")
            and not attr.startswith("__")
        )

    def name_mangled(self) -> List[str]:
        """
        List name-mangled attributes.

        Returns names that start with double underscore but not
        ending with double underscore. These undergo Python's
        name mangling in classes (e.g., ``__private`` becomes
        ``_ClassName__private``).

        Returns
        -------
        List[str]
            Alphabetically sorted list of name-mangled attributes.

        Notes
        -----
        Name mangling is not truly private; it's a convention to
        avoid name conflicts in subclasses by transforming
        ``__attr`` to ``_ClassName__attr``.

        Examples
        --------
        >>> class BaseClass:
        ...     def __init__(self):
        ...         self.__secret = 42  # Mangled to _BaseClass__secret
        ...         self.public = 100
        ...
        >>> parser = ObjectParser(BaseClass())
        >>> parser.name_mangled()
        ['_BaseClass__secret']
        """
        return sorted(
            attr for attr in self.attrs
            if attr.startswith("__")
            and not attr.endswith("__")
        )

    def slots(self) -> List[str]:
        """
        List attribute names defined in ``__slots__``.

        Returns
        -------
        List[str]
            Slot names if ``__slots__`` is defined, empty list otherwise.
            Handles both string and iterable slot definitions.

        Notes
        -----
        ``__slots__`` is a performance optimization that restricts
        instance attributes to a fixed set, saving memory by avoiding
        ``__dict__`` creation.

        Examples
        --------
        >>> class Point:
        ...     __slots__ = ('x', 'y')
        ...     def __init__(self, x: float, y: float):
        ...         self.x = x
        ...         self.y = y
        ...
        >>> parser = ObjectParser(Point(1.0, 2.0))
        >>> parser.slots()
        ['x', 'y']
        """
        raw_slots = getattr(self.obj, "__slots__", [])

        # Handle __slots__ defined as a string
        if isinstance(raw_slots, str):
            return [raw_slots]

        # Handle __slots__ defined as an iterable
        try:
            return list(raw_slots)
        except TypeError:
            return []

    def annotations(self) -> Dict[str, Any]:
        """
        Extract type annotations for the object.

        Uses :func:`typing.get_type_hints` to resolve forward references
        and string annotations to actual type objects.

        Returns
        -------
        Dict[str, Any]
            Dictionary mapping attribute names to their type annotations.
            Empty dict if no annotations are defined or if resolution fails.

        Notes
        -----
        - For classes, this returns class-level annotations.
        - For functions, this returns parameter and return annotations.
        - Forward references (strings) are resolved when possible.
        - Inherited annotations from parent classes are included.

        Examples
        --------
        >>> class TypedContainer:
        ...     items: List[int]
        ...     label: str = "default"
        ...
        >>> from typing import List
        >>> parser = ObjectParser(TypedContainer)
        >>> annotations = parser.annotations()
        >>> 'items' in annotations
        True
        >>> 'label' in annotations
        True
        """
        try:
            if isinstance(self.obj, type):
                return get_type_hints(self.obj)
            else:
                return get_type_hints(type(self.obj))
        except (TypeError, AttributeError, NameError, KeyError):
            return {}

    def inheritance(self) -> List[str]:
        """
        Show the inheritance chain (Method Resolution Order).

        Returns
        -------
        List[str]
            List of class names in MRO order (from the object's class
            up to ``object``). Empty list if the object is not a class
            or doesn't have an MRO.

        Examples
        --------
        >>> class A: pass
        >>> class B(A): pass
        >>> class C(B): pass
        >>> parser = ObjectParser(C)
        >>> parser.inheritance()
        ['C', 'B', 'A', 'object']
        """
        if isinstance(self.obj, type):
            target = self.obj
        else:
            target = type(self.obj)

        try:
            return [cls.__name__ for cls in inspect.getmro(target)]
        except (TypeError, AttributeError):
            return []

    def code_objects(self) -> List[str]:
        """
        List attributes containing raw code objects.

        Code objects represent compiled Python bytecode and are
        instances of :class:`types.CodeType`.

        Returns
        -------
        List[str]
            Alphabetically sorted list of attribute names that hold
            code objects.

        Examples
        --------
        >>> def example():
        ...     pass
        ...
        >>> parser = ObjectParser(example)
        >>> '__code__' in parser.code_objects()
        True
        """
        return self._filter(CodeType)

    def callable(self) -> List[str]:
        """
        List all callable attributes.

        Uses the built-in :func:`callable` function to identify
        attributes that can be invoked as functions.

        Returns
        -------
        List[str]
            Alphabetically sorted list of callable attribute names.

        Notes
        -----
        This includes:
        - Functions and methods
        - Classes (constructors)
        - Objects with ``__call__`` method
        - Built-in callables
        - Generators and coroutines

        Examples
        --------
        >>> class CallableExample:
        ...     def __call__(self):
        ...         return "called"
        ...
        >>> parser = ObjectParser(CallableExample())
        >>> '__call__' in parser.callable()
        True
        """
        if self._cached_callable is not None:
            return self._cached_callable

        callables = sorted(
            name for name in self.attrs
            if callable(getattr(self.obj, name, None))
        )

        self._cached_callable = callables
        return callables

    def generators(self) -> List[str]:
        """
        List generator functions in the object.

        Returns
        -------
        List[str]
            Names of generator function attributes.

        Examples
        --------
        >>> class GeneratorHost:
        ...     def gen(self):
        ...         yield 1
        ...         yield 2
        ...
        >>> parser = ObjectParser(GeneratorHost())
        >>> 'gen' in parser.generators()
        False  # It's a method, not a generator yet
        """
        return self._filter(GeneratorType)

    def coroutines(self) -> List[str]:
        """
        List coroutine function attributes.

        Returns
        -------
        List[str]
            Names of coroutine function attributes (async def).

        Examples
        --------
        >>> import asyncio
        >>> class AsyncHost:
        ...     async def fetch(self):
        ...         return 42
        ...
        >>> parser = ObjectParser(AsyncHost())
        >>> 'fetch' in parser.coroutines()
        False  # It's a coroutine function, not a coroutine object
        """
        return self._filter(CoroutineType)

    def class_attributes(self) -> Dict[str, Any]:
        """
        Get all class-level attributes across the MRO.

        Returns
        -------
        Dict[str, Any]
            Complete dictionary of class attributes from the entire
            inheritance chain.

        Examples
        --------
        >>> class Base:
        ...     BASE_VAL = 10
        ...
        >>> class Derived(Base):
        ...     DERIVED_VAL = 20
        ...
        >>> parser = ObjectParser(Derived)
        >>> attrs = parser.class_attributes()
        >>> 'BASE_VAL' in attrs
        True
        >>> 'DERIVED_VAL' in attrs
        True
        """
        return dict(self.class_attrs)

    def abstract_methods(self) -> List[str]:
        """
        List abstract methods (requires ABC).

        Returns
        -------
        List[str]
            Names of abstract methods if the object is an abstract class.
            Empty list otherwise.

        Examples
        --------
        >>> from abc import ABC, abstractmethod
        >>> class AbstractBase(ABC):
        ...     @abstractmethod
        ...     def process(self):
        ...         pass
        ...
        >>> parser = ObjectParser(AbstractBase)
        >>> 'process' in parser.abstract_methods()
        True
        """
        if not isinstance(self.obj, type):
            return []

        try:
            if not inspect.isabstract(self.obj):
                return []
            return sorted(list(self.obj.__abstractmethods__))
        except AttributeError:
            return []

    def body(self, name: Optional[str] = None) -> Optional[str]:
        """
        Extract source code for the object or one of its attributes.

        Attempts to retrieve the Python source code using
        :func:`inspect.getsource`, then dedents and returns it.

        Parameters
        ----------
        name : str, optional
            Attribute name to extract source for. If None, attempts to
            retrieve source for the main object itself.

        Returns
        -------
        str or None
            Dedented source code string if available. Returns None if:
            - The object is a built-in (C implementation)
            - The source file is not accessible
            - The object was dynamically created
            - An exception occurs during source extraction

        Notes
        -----
        - Source extraction requires the object to be defined in a
          Python source file accessible on the file system.
        - Built-ins and C extensions have no Python source code.
        - The returned string is dedented using :func:`textwrap.dedent`
          for consistent formatting.

        Examples
        --------
        >>> def sample(x: int) -> str:
        ...     '''Sample function.'''
        ...     return str(x)
        ...
        >>> parser = ObjectParser(sample)
        >>> body = parser.body()
        >>> 'def sample(x:' in body
        True

        >>> import math
        >>> parser = ObjectParser(math)
        >>> parser.body() is None
        True  # Built-in module - no Python source available
        """
        if name is not None:
            obj = self.get(name, call=False)
            if obj is None:
                return None
        else:
            obj = self.obj

        try:
            text = inspect.getsource(obj)
            return dedent(text)
        except (TypeError, OSError, IndentationError):
            return None

    def signature(self, name: Optional[str] = None) -> Optional[str]:
        """
        Get the signature of a callable attribute or the object itself.

        Parameters
        ----------
        name : str, optional
            Attribute name to inspect. If None, inspects the main object.

        Returns
        -------
        str or None
            String representation of the callable's signature, or None
            if the signature cannot be determined.

        Examples
        --------
        >>> def greet(name: str, greeting: str = "Hello") -> str:
        ...     return f"{greeting}, {name}!"
        ...
        >>> parser = ObjectParser(greet)
        >>> parser.signature()
        '(name: str, greeting: str = 'Hello') -> str'
        """
        if name is not None:
            obj = self.get(name, call=False)
            if obj is None or not callable(obj):
                return None
        else:
            obj = self.obj
            if not callable(obj):
                return None

        try:
            return str(inspect.signature(obj))
        except (ValueError, TypeError):
            return None

    def file_info(self) -> Optional[Dict[str, Any]]:
        """
        Get information about the source file.

        Returns
        -------
        Dict[str, Any] or None
            Dictionary with file metadata if available, None otherwise.
            Includes: ``path``, ``exists``, ``lines``,
            ``first_line`` (firstlineno), ``last_line``.

        Examples
        --------
        >>> from pathlib import Path
        >>> parser = ObjectParser(ObjectParser)  # This class itself
        >>> info = parser.file_info()
        >>> info is not None
        True
        >>> 'path' in info
        True
        """
        try:
            src_file = inspect.getfile(self.obj)
            src_path = Path(src_file)
            src_lines, first_line = inspect.getsourcelines(self.obj)

            return {
                "path": str(src_path),
                "exists": src_path.exists(),
                "size_bytes": src_path.stat().st_size if src_path.exists() else None,
                "line_count": len(src_lines),
                "first_line": first_line,
                "last_line": first_line + len(src_lines) - 1,
            }
        except (TypeError, OSError):
            return None

    def summary(self) -> Dict[str, Any]:
        """
        Generate a comprehensive summary of the parsed object.

        Combines metadata, categorized attributes, and structural
        information into a single dictionary suitable for serialization
        or reporting.

        Returns
        -------
        Dict[str, Any]
            Comprehensive summary dictionary with all inspection results
            organized by category.

        Examples
        --------
        >>> class Summarized:
        ...     '''Docstring for summary.'''
        ...     val: int = 42
        ...     def method(self) -> None: pass
        ...
        >>> parser = ObjectParser(Summarized)
        >>> summary = parser.summary()
        >>> sorted(summary.keys())  # doctest: +NORMALIZE_WHITESPACE
        ['abstract_methods', 'annotations', 'attributes_total', 'body',
         'callable', 'class_attributes_count', 'classmethods', 'code_objects',
         'coroutines', 'descriptors', 'file_info', 'functions', 'generators',
         'inheritance', 'location', 'magic_methods', 'metadata', 'methods',
         'modules', 'name_mangled', 'private', 'properties', 'signature',
         'slots', 'staticmethods', 'variables']
        """
        return {
            # Metadata
            "metadata": self.dict,
            "location": self.location,
            "signature": self.signature(),
            "body": self.body(),
            "file_info": self.file_info(),

            # Categorized attributes
            "functions": self.functions(),
            "methods": self.methods(),
            "builtins": self.builtins(),
            "classes": self.classes(),
            "variables": self.variables(),
            "properties": self.properties(),
            "staticmethods": self.staticmethods(),
            "classmethods": self.classmethods(),
            "descriptors": self.descriptors(),
            "magic_methods": self.magic_methods(),
            "private": self.private(),
            "name_mangled": self.name_mangled(),
            "slots": self.slots(),
            "generators": self.generators(),
            "coroutines": self.coroutines(),
            "code_objects": self.code_objects(),
            "callable": self.callable(),

            # Structural information
            "annotations": self.annotations(),
            "inheritance": self.inheritance(),
            "abstract_methods": self.abstract_methods(),

            # Counts
            "attributes_total": len(self.attrs),
            "class_attributes_count": len(self.class_attrs),
        }

    def __repr__(self) -> str:
        """
        Human-readable representation of the parser.

        Returns
        -------
        str
            String showing the parser type and the object being analyzed.
        """
        obj_name = self.dict.get("name") or self.dict.get("repr", "unknown")
        return f"ObjectParser({obj_name}, type={self.type_name})"

    def __str__(self) -> str:
        """
        Detailed string representation with key information.

        Returns
        -------
        str
            Multi-line string summarizing the parsed object's
            characteristics.
        """
        lines = [
            f"ObjectParser for: {self.dict.get('repr', 'unknown')}",
            f"  Type: {self.type_name}",
            f"  Module: {self.module or 'N/A'}",
            f"  Location: {self.location or 'N/A'}",
            f"  Callable: {self.dict.get('is_callable', False)}",
            f"  Built-in: {self.dict.get('is_builtin', False)}",
            f"  Total attributes: {len(self.attrs)}",
            f"  Methods: {len(self.methods())}",
            f"  Properties: {len(self.properties())}",
            f"  Variables: {len(self.variables())}",
        ]
        return "\n".join(lines)

    def reset_caches(self) -> None:
        """
        Reset internal caches to force re-computation.

        This is useful when the object's attributes have been
        modified after parser initialization and you need fresh
        inspection results.

        Examples
        --------
        >>> obj = type('Dynamic', (), {})()
        >>> parser = ObjectParser(obj)
        >>> obj.new_attr = 42  # Add attribute after parsing
        >>> parser.variables()  # Won't see new_attr
        []
        >>> parser.reset_caches()
        >>> parser.variables()
        ['new_attr']
        """
        self._cached_variables = None
        self._cached_callable = None
        # Refresh attributes in case they changed
        self.attrs = dir(self.obj)
        self.namespace = create_dict(self.obj)
        self.dict = __info_dict__(self.obj)

