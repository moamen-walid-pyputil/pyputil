#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import random
import string
import sys
from typing import Any, Optional, Union
from collections.abc import Callable


class Fuzzing:
    """
    fuzzing for generating diverse test inputs.

    Parameters
    ----------
    max_depth : int, optional
        Maximum recursion depth for generating nested structures (default: 3).
    max_length : int, optional
        Maximum length for sequences (default: 10).
    include_edge_cases : bool, optional
        Whether to include common edge cases (default: True).
    seed : Optional[int], optional
        Random seed for reproducibility (default: None).

    Examples
    --------
    >>> fuzz = Fuzzing(max_depth=2)
    >>> value = fuzz.generate_for_type(int)
    >>> isinstance(value, int)
    True
    """

    def __init__(
        self,
        max_depth: int = 3,
        max_length: int = 10,
        include_edge_cases: bool = True,
        seed: Optional[int] = None,
    ):
        self.max_depth = max_depth
        self.max_length = max_length
        self.include_edge_cases = include_edge_cases
        self._random = random.Random(seed)
        self._generation_depth = 0

        # Type-specific generators
        self._generators = {
            int: self._generate_int,
            float: self._generate_float,
            str: self._generate_string,
            bool: self._generate_bool,
            list: self._generate_list,
            tuple: self._generate_tuple,
            dict: self._generate_dict,
            type(None): self._generate_none,
            bytes: self._generate_bytes,
            set: self._generate_set,
        }

    def generate_value(self, hint: Any = None) -> Any:
        """
        Generate a random test value, optionally based on type hint.

        Parameters
        ----------
        hint : Any, optional
            Type hint or annotation to guide generation.

        Returns
        -------
        Any
            Generated test value.

        Notes
        -----
        The function handles:
        - Basic types (int, float, str, bool)
        - Collections (list, dict, tuple, set)
        - Special values (None, empty collections, edge cases)
        - Recursive structures (with depth limit)
        """
        if self._generation_depth >= self.max_depth:
            return self._generate_simple()

        self._generation_depth += 1

        try:
            # Handle Union types
            if hasattr(hint, "__origin__") and hint.__origin__ is Union:
                type_args = hint.__args__
                chosen_type = self._random.choice(type_args)
                result = self.generate_value(chosen_type)
                self._generation_depth -= 1
                return result

            # Handle Optional types
            if (
                hasattr(hint, "__origin__")
                and hint.__origin__ is Union
                and type(None) in getattr(hint, "__args__", [])
            ):
                if self._random.random() < 0.3:  # 30% chance of None
                    self._generation_depth -= 1
                    return None
                # Choose non-None type
                non_none_args = [t for t in hint.__args__ if t is not type(None)]
                chosen_type = (
                    self._random.choice(non_none_args) if non_none_args else Any
                )
                result = self.generate_value(chosen_type)
                self._generation_depth -= 1
                return result

            # Handle List, Dict, etc.
            if hasattr(hint, "__origin__"):
                origin = hint.__origin__
                if origin in self._generators:
                    result = self._generators[origin]()
                    self._generation_depth -= 1
                    return result

            # Direct type matching
            if hint in self._generators:
                result = self._generators[hint]()
                self._generation_depth -= 1
                return result

            # Try to get type from annotation
            if isinstance(hint, type):
                # Try common parent classes
                for base_type in (int, float, str, bool, list, dict, tuple):
                    if issubclass(hint, base_type):
                        result = self._generators[base_type]()
                        self._generation_depth -= 1
                        return result

        except Exception:
            pass

        # Fallback to random simple value
        result = self._generate_simple()
        self._generation_depth -= 1
        return result

    def _generate_int(self) -> int:
        """Generate integer with edge cases."""
        if self.include_edge_cases and self._random.random() < 0.3:
            return self._random.choice([0, 1, -1, sys.maxsize, -sys.maxsize])
        return self._random.randint(-1000, 1000)

    def _generate_float(self) -> float:
        """Generate float with edge cases."""
        if self.include_edge_cases and self._random.random() < 0.3:
            return self._random.choice(
                [0.0, 1.0, -1.0, float("inf"), float("-inf"), float("nan")]
            )
        return self._random.uniform(-1000.0, 1000.0)

    def _generate_string(self) -> str:
        """Generate string with various patterns."""
        patterns = [
            "",  # Empty string
            " " * self._random.randint(1, 10),  # Whitespace
            "a" * self._random.randint(1, self.max_length),  # Repeated chars
            "".join(
                self._random.choices(
                    string.printable, k=self._random.randint(0, self.max_length)
                )
            ),
            "test_string_with_underscores",
            "string.with.dots",
            "string-with-dashes",
            "CamelCaseString",
            "snake_case_string",
        ]

        if self.include_edge_cases:
            patterns.extend(
                [
                    "\x00\x01\x02",  # Control characters
                    "\\n\\t\\r",  # Escape sequences
                    "unicode_测试_中文",
                    "emoji_😀🎉🌟",
                ]
            )

        return self._random.choice(patterns)

    def _generate_bool(self) -> bool:
        """Generate boolean value."""
        return self._random.choice([True, False])

    def _generate_list(self) -> list:
        """Generate list with random elements."""
        length = self._random.randint(0, self.max_length)
        return [self.generate_value() for _ in range(length)]

    def _generate_tuple(self) -> tuple:
        """Generate tuple with random elements."""
        length = self._random.randint(0, self.max_length)
        return tuple(self.generate_value() for _ in range(length))

    def _generate_dict(self) -> dict:
        """Generate dictionary with random keys and values."""
        length = self._random.randint(0, self.max_length)
        return {self._generate_string(): self.generate_value() for _ in range(length)}

    def _generate_none(self) -> None:
        """Generate None value."""
        return None

    def _generate_bytes(self) -> bytes:
        """Generate bytes object."""
        length = self._random.randint(0, self.max_length)
        return bytes(self._random.getrandbits(8) for _ in range(length))

    def _generate_set(self) -> set:
        """Generate set with unique elements."""
        length = self._random.randint(0, min(self.max_length, 5))
        elements = set()
        while len(elements) < length:
            elements.add(self.generate_value())
        return elements

    def _generate_simple(self) -> Any:
        """Generate a simple random value."""
        return self._random.choice(
            [
                None,
                self._generate_int(),
                self._generate_float(),
                self._generate_string(),
                self._generate_bool(),
                [],
                {},
            ]
        )
