#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from types import ModuleType as module
from typing import Union, List, Tuple, Optional, Iterable, Dict
from pathlib import Path
import importlib


def _file_size(file: Path) -> int:
    """
    Safely retrieve file size in bytes.

    Parameters
    ----------
    file : pathlib.Path
        Path to the target file.

    Returns
    -------
    int
        File size in bytes. Returns 0 if the file is inaccessible,
        does not exist, or permission is denied.

    Notes
    -----
    This function handles common filesystem errors gracefully,
    ensuring that permission issues or missing files don't
    interrupt the overall size calculation process.
    """
    try:
        return file.stat().st_size
    except (FileNotFoundError, PermissionError, OSError):
        return 0


def _format_size(bytes_value: int) -> str:
    """
    Convert bytes to human-readable format.

    Parameters
    ----------
    bytes_value : int
        Size in bytes.

    Returns
    -------
    str
        Human-readable size string (e.g., '1.5 KB', '23.4 MB').

    Notes
    -----
    Uses binary prefixes (1024-based) for accurate representation
    of file sizes as commonly displayed by operating systems.
    """
    if bytes_value == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(bytes_value)
    unit_index = 0

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    # Use appropriate decimal places based on magnitude
    if size >= 100:
        return f"{size:.0f} {units[unit_index]}"
    elif size >= 10:
        return f"{size:.1f} {units[unit_index]}"
    else:
        return f"{size:.2f} {units[unit_index]}"


class size:
    """
    Compute and analyze size statistics for Python modules and packages.

    This class provides comprehensive size inspection capabilities for
    Python modules or packages, including total size calculation, file
    filtering, size-based searching, and suffix-based aggregation.

    Parameters
    ----------
    ModuleName : str or module
        The name of the module (as a string) or an imported module object
        to analyze.
    ignore : list of str, optional
        File suffixes to exclude from analysis (e.g., ``['.pyc', '.so']``).
        Files with these suffixes will be skipped during iteration and
        calculation.

    Attributes
    ----------
    name : str
        The name of the module being analyzed.
    path : pathlib.Path
        The root path of the module or package on disk.
    ignore : list of str
        List of file suffixes being ignored during analysis.
    ismodule : bool
        ``True`` if the target is a single module file (not a package).
    isinit : bool
        ``True`` if the target is an ``__init__.py`` file.
    size : int
        Total size of the module/package in bytes.
    readable : str
        Total size in human-readable format (e.g., '1.5 MB').

    Raises
    ------
    ModuleNotFoundError
        If the specified module cannot be found in the Python path.

    Examples
    --------
    >>> s = size("os")
    >>> s.size
    123456
    >>> s.readable
    '120.56 KB'

    >>> # Find files larger than 1KB
    >>> s.find(size=1024, cmp=">")
    ['path.py', 'walk.py']

    >>> # Get size statistics by file type
    >>> s.by_suffix(".py")
    98000
    >>> s.by_suffix_readable(".py")
    '95.70 KB'

    >>> # Filter results with size thresholds
    >>> s.filter_sizes(min_size=500, max_size=2000)
    {'file1.py': 1024, 'file2.py': 750}
    >>> s.filter_sizes_readable(min_size=500, max_size=2000)
    {'file1.py': '1.00 KB', 'file2.py': '750 B'}
    """

    def __init__(
        self,
        ModuleName: Union[str, module],
        ignore: Optional[List[str]] = None,
    ) -> None:
        # Store module name
        self.name = (
            ModuleName.__name__ if isinstance(ModuleName, module) else ModuleName
        )

        # Initialize ignore list
        self.ignore = ignore or []

        # Find module specification
        spec = importlib.util.find_spec(self.name)
        if spec is None:
            raise ModuleNotFoundError(f"Module '{self.name}' not found")

        # Determine module path
        if spec.submodule_search_locations:
            self.path = Path(spec.submodule_search_locations[0])
        else:
            self.path = Path(spec.origin)

        # Module type detection
        self.ismodule = self.path.is_file() and self.path.name != "__init__.py"
        self.isinit = self.path.is_file() and self.path.name == "__init__.py"

    def __repr__(self) -> str:
        return f"size(name='{self.name}', size={self.readable}, path='{self.path}')"

    # -------------------------
    # internal helpers
    # -------------------------
    def _iter_files(self, suffix: Optional[str] = None) -> Iterable[Path]:
        """
        Generate file paths respecting ignore list and suffix filter.

        Parameters
        ----------
        suffix : str, optional
            File suffix pattern to filter by (e.g., ``'.py'``). If None,
            all files are included.

        Yields
        ------
        pathlib.Path
            Valid file paths matching the criteria.

        Notes
        -----
        This is an internal generator that handles the traversal logic
        for both single modules and packages, applying the ignore list
        to exclude unwanted file types.
        """
        base = self.path.parent if self.isinit else self.path
        suffix = ("*" + suffix) if suffix and "*" not in suffix else (suffix or "*")

        if self.ismodule:
            yield self.path
            return

        for f in base.rglob(suffix):
            if f.is_file() and f.suffix not in self.ignore:
                yield f

    # -------------------------
    # public API - Properties
    # -------------------------
    @property
    def size(self) -> int:
        """
        Total size of the module or package in bytes.

        Returns
        -------
        int
            The sum of sizes of all files (excluding ignored suffixes)
            in the module or package.

        Notes
        -----
        Uses sequential scanning which is efficient for disk I/O operations.
        Thread-based approaches typically don't provide significant speedup
        for disk-bound operations.

        See Also
        --------
        readable : Human-readable version of this value.
        """
        return sum(_file_size(f) for f in self._iter_files())

    @property
    def readable(self) -> str:
        """
        Total size of the module or package in human-readable format.

        Returns
        -------
        str
            Total size formatted with appropriate unit suffix
            (B, KB, MB, GB, TB).

        Examples
        --------
        >>> s = size("numpy")
        >>> s.readable
        '23.45 MB'
        """
        return _format_size(self.size)

    # -------------------------
    # public API - Core Methods
    # -------------------------
    def find(
        self,
        size: Optional[int] = None,
        cmp: str = "<=",
        maxfiles: Optional[int] = None,
        withsize: bool = False,
        fullname: bool = False,
    ) -> List[Union[str, Tuple[str, int]]]:
        """
        Find files matching specified size conditions.

        Parameters
        ----------
        size : int, optional
            Target size in bytes to compare against. If None, all files
            are returned regardless of size.
        cmp : {'==', '>=', '<=', '>', '<'}, default '<=''
            Comparison operator for size filtering:

            - ``'=='`` : Equal to `size`
            - ``'>='`` : Greater than or equal to `size`
            - ``'<='`` : Less than or equal to `size`
            - ``'>'`` : Greater than `size`
            - ``'<'`` : Less than `size`

        maxfiles : int, optional
            Maximum number of files to scan. Useful for limiting
            I/O operations on large packages.
        withsize : bool, default False
            If ``True``, return tuples of ``(filename, size_in_bytes)``
            instead of just filenames.
        fullname : bool, default False
            If ``True``, return full file paths instead of just filenames.

        Returns
        -------
        list of str or list of tuple
            List of matching files. Each element is either:

            - A string (filename or full path) if ``withsize=False``
            - A tuple ``(filename, size_in_bytes)`` if ``withsize=True``

        Raises
        ------
        ValueError
            If an invalid comparison operator is provided.

        Examples
        --------
        >>> s = size("requests")
        >>> s.find(size=1024, cmp=">")
        ['adapters.py', 'models.py', 'sessions.py']

        >>> s.find(size=500, withsize=True, maxfiles=5)
        [('api.py', 2456), ('auth.py', 1234), ('cookies.py', 890)]

        >>> s.find(cmp="<", size=200, fullname=True)
        ['/usr/lib/python3/dist-packages/requests/help.py']
        """
        # Validate comparison operator
        valid_cmps = {"==", ">=", "<=", ">", "<"}
        if cmp not in valid_cmps:
            raise ValueError(
                f"Invalid comparison operator '{cmp}'. "
                f"Must be one of {valid_cmps}."
            )

        def compare(val: int) -> bool:
            """Apply comparison operator to file size."""
            if size is None:
                return True
            if cmp == "==":
                return val == size
            if cmp == ">=":
                return val >= size
            if cmp == "<=":
                return val <= size
            if cmp == ">":
                return val > size
            if cmp == "<":
                return val < size

        results = []

        for i, f in enumerate(self._iter_files()):
            if maxfiles is not None and i >= maxfiles:
                break

            fsize = _file_size(f)
            if not compare(fsize):
                continue

            name = str(f) if fullname else f.name
            results.append((name, fsize) if withsize else name)

        return results

    def find_readable(
        self,
        size: Optional[int] = None,
        cmp: str = "<=",
        maxfiles: Optional[int] = None,
        fullname: bool = False,
    ) -> List[Union[str, Tuple[str, str]]]:
        """
        Find files matching size conditions with human-readable sizes.

        Parameters
        ----------
        size : int, optional
            Target size in bytes to compare against.
        cmp : {'==', '>=', '<=', '>', '<'}, default '<=''
            Comparison operator for size filtering.
        maxfiles : int, optional
            Maximum number of files to scan.
        fullname : bool, default False
            If ``True``, return full file paths instead of just filenames.

        Returns
        -------
        list of tuple
            List of tuples ``(filename, readable_size)`` where readable_size
            is a formatted string like '1.5 KB'.

        Examples
        --------
        >>> s = size("requests")
        >>> s.find_readable(size=1024, cmp=">", maxfiles=3)
        [('adapters.py', '12.5 KB'), ('models.py', '8.3 KB'), ('sessions.py', '6.1 KB')]
        """
        results = self.find(
            size=size, cmp=cmp, maxfiles=maxfiles, withsize=True, fullname=fullname
        )
        return [(name, _format_size(sz)) for name, sz in results]

    def by_suffix(self, suffix: str) -> int:
        """
        Calculate total size of files with a specific suffix.

        Parameters
        ----------
        suffix : str
            File suffix to filter by (e.g., ``'.py'``, ``'.json'``).
            Should include the leading dot.

        Returns
        -------
        int
            Total size in bytes of all files with the specified suffix.
            Returns 0 if the suffix is in the ignore list or no matching
            files are found.

        See Also
        --------
        by_suffix_readable : Human-readable version of this value.

        Examples
        --------
        >>> s = size("numpy")
        >>> s.by_suffix(".py")
        1234567
        >>> s.by_suffix(".so")
        5043210
        """
        if suffix in self.ignore:
            return 0
        return sum(_file_size(f) for f in self._iter_files(suffix))

    def by_suffix_readable(self, suffix: str) -> str:
        """
        Calculate total size of files with a specific suffix in readable format.

        Parameters
        ----------
        suffix : str
            File suffix to filter by (e.g., ``'.py'``).

        Returns
        -------
        str
            Total size in human-readable format.
            Returns '0 B' if the suffix is in the ignore list.

        Examples
        --------
        >>> s = size("numpy")
        >>> s.by_suffix_readable(".py")
        '1.18 MB'
        >>> s.by_suffix_readable(".so")
        '4.81 MB'
        """
        return _format_size(self.by_suffix(suffix))

    def filter_sizes(
        self,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        suffix: Optional[str] = None,
        sort_by_size: bool = False,
        reverse: bool = False,
    ) -> Dict[str, int]:
        """
        Filter files by size range with optional sorting and suffix filtering.

        Parameters
        ----------
        min_size : int, optional
            Minimum file size in bytes (inclusive).
        max_size : int, optional
            Maximum file size in bytes (inclusive).
        suffix : str, optional
            File suffix to filter by (e.g., ``'.py'``).
        sort_by_size : bool, default False
            If ``True``, sort results by file size.
        reverse : bool, default False
            If ``True`` and ``sort_by_size=True``, sort in descending order.

        Returns
        -------
        dict
            Dictionary mapping filenames to their sizes in bytes.
            Only includes files within the specified size range.

        Notes
        -----
        Size boundaries are inclusive. A file with size exactly equal
        to ``min_size`` or ``max_size`` will be included in the results.

        See Also
        --------
        filter_sizes_readable : Same method returning human-readable sizes.

        Examples
        --------
        >>> s = size("django")
        >>> # Files between 1KB and 1MB
        >>> s.filter_sizes(min_size=1024, max_size=1048576)
        {'models.py': 45000, 'views.py': 32000, 'urls.py': 5000}

        >>> # Python files sorted by size (largest first)
        >>> s.filter_sizes(suffix=".py", sort_by_size=True, reverse=True)
        {'admin.py': 125000, 'models.py': 45000, 'tests.py': 28000}
        """
        filtered = {}

        for f in self._iter_files(suffix):
            fsize = _file_size(f)
            
            # Apply size filters
            if min_size is not None and fsize < min_size:
                continue
            if max_size is not None and fsize > max_size:
                continue
            
            filtered[f.name] = fsize

        if sort_by_size:
            return dict(
                sorted(filtered.items(), key=lambda x: x[1], reverse=reverse)
            )
        
        return filtered

    def filter_sizes_readable(
        self,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        suffix: Optional[str] = None,
        sort_by_size: bool = False,
        reverse: bool = False,
    ) -> Dict[str, str]:
        """
        Filter files by size range with human-readable sizes.

        Parameters
        ----------
        min_size : int, optional
            Minimum file size in bytes (inclusive).
        max_size : int, optional
            Maximum file size in bytes (inclusive).
        suffix : str, optional
            File suffix to filter by (e.g., ``'.py'``).
        sort_by_size : bool, default False
            If ``True``, sort results by file size.
        reverse : bool, default False
            If ``True`` and ``sort_by_size=True``, sort in descending order.

        Returns
        -------
        dict
            Dictionary mapping filenames to their sizes as formatted strings
            (e.g., '1.5 KB').

        Examples
        --------
        >>> s = size("django")
        >>> s.filter_sizes_readable(min_size=1024, max_size=1048576)
        {'models.py': '43.95 KB', 'views.py': '31.25 KB', 'urls.py': '4.88 KB'}
        """
        filtered = self.filter_sizes(
            min_size=min_size,
            max_size=max_size,
            suffix=suffix,
            sort_by_size=sort_by_size,
            reverse=reverse,
        )
        return {name: _format_size(sz) for name, sz in filtered.items()}

    def size_breakdown(self, top_n: Optional[int] = None) -> List[Tuple[str, int, float]]:
        """
        Get a detailed breakdown of file sizes with percentage contribution.

        Parameters
        ----------
        top_n : int, optional
            Limit results to the top N largest files. If None, returns
            all files sorted by size.

        Returns
        -------
        list of tuple
            List of tuples ``(filename, size_in_bytes, percentage)``
            sorted by size in descending order. Percentage is relative
            to the total module/package size.

        Notes
        -----
        This method provides insight into which files contribute most
        to the overall package size, useful for optimization efforts.

        See Also
        --------
        size_breakdown_readable : Same method with human-readable sizes.

        Examples
        --------
        >>> s = size("pandas")
        >>> s.size_breakdown(top_n=3)
        [('_libs.so', 5400000, 45.2), ('core.py', 2300000, 19.3), 
         ('io.py', 1200000, 10.1)]
        """
        total = self.size
        if total == 0:
            return []

        file_sizes = []
        for f in self._iter_files():
            fsize = _file_size(f)
            percentage = (fsize / total) * 100
            file_sizes.append((f.name, fsize, round(percentage, 2)))

        # Sort by size (descending)
        file_sizes.sort(key=lambda x: x[1], reverse=True)

        if top_n is not None:
            return file_sizes[:top_n]
        
        return file_sizes

    def size_breakdown_readable(
        self, top_n: Optional[int] = None
    ) -> List[Tuple[str, str, float]]:
        """
        Get a detailed breakdown with human-readable sizes.

        Parameters
        ----------
        top_n : int, optional
            Limit results to the top N largest files. If None, returns
            all files sorted by size.

        Returns
        -------
        list of tuple
            List of tuples ``(filename, readable_size, percentage)``
            sorted by size in descending order.

        Examples
        --------
        >>> s = size("pandas")
        >>> s.size_breakdown_readable(top_n=3)
        [('_libs.so', '5.15 MB', 45.2), ('core.py', '2.19 MB', 19.3), 
         ('io.py', '1.15 MB', 10.1)]
        """
        breakdown = self.size_breakdown(top_n=top_n)
        return [(name, _format_size(sz), pct) for name, sz, pct in breakdown]

    def count_files(self, suffix: Optional[str] = None) -> int:
        """
        Count the number of files in the module or package.

        Parameters
        ----------
        suffix : str, optional
            File suffix to filter by (e.g., ``'.py'``). If None,
            counts all non-ignored files.

        Returns
        -------
        int
            Number of files matching the criteria.

        Examples
        --------
        >>> s = size("matplotlib")
        >>> s.count_files()
        847
        >>> s.count_files(".py")
        650
        """
        return sum(1 for _ in self._iter_files(suffix))
