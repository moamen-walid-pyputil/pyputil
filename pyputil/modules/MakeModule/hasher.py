#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Cryptographic hashing utilities for module verification.
"""

import hashlib
from typing import Dict, Any


class CryptographicHasher:
    """
    Cryptographic hashing utility.

    Parameters
    ----------
    algorithm : str, default="blake2b"
        Hashing algorithm to use. Supported: "blake2b", "sha3_256", "md5"

    Attributes
    ----------
    algorithm : str
        Selected hashing algorithm
    _cache : Dict[str, str]
        Cache for computed hashes
    """

    def __init__(self, algorithm: str = "blake2b"):
        """
        Initialize CryptographicHasher with specified algorithm.

        Parameters
        ----------
        algorithm : str
            Hashing algorithm to use
        """
        self.algorithm = algorithm
        self._cache: Dict[str, str] = {}

    def compute_hash(self, data: bytes, salt: bytes = b"") -> str:
        """
        Compute cryptographic hash of data with optional salt.

        Parameters
        ----------
        data : bytes
            Data to hash
        salt : bytes, default=b""
            Salt for hashing (for blake2b only)

        Returns
        -------
        str
            Hexadecimal hash digest

        Notes
        -----
        Results are cached for performance. Cache key is combination of
        data and salt.
        """
        cache_key = f"{data}{salt}".encode()
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Select hashing algorithm
        if self.algorithm == "blake2b":
            hasher = hashlib.blake2b(salt=salt)
        elif self.algorithm == "sha3_256":
            hasher = hashlib.sha3_256()
        else:
            hasher = hashlib.md5()

        # Compute hash
        hasher.update(data)
        digest = hasher.hexdigest()

        # Cache result
        self._cache[cache_key] = digest
        return digest

    def clear_cache(self) -> None:
        """
        Clear the hash cache.
        """
        self._cache.clear()
