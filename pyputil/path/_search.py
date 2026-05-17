#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import re
import os
from pathlib import Path
from typing import List, Dict
from .filetools import read
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass


@dataclass
class Result:
    """Structured result for a single match.

    Attributes
    ----------
    file : str
        Absolute path of the scanned file.
    line : str
        Content of the line where the match occurred.
    lineno : int
        Line index within the file.
    match : str
        Type of match; either "substring" or "whole_word".
    context_before : list[str]
        Lines immediately before the match for context.
    context_after : list[str]
        Lines immediately after the match for context.
    """

    file: str
    line: str
    lineno: int
    match: str
    context_before: List[str]
    context_after: List[str]


def _search_in_file(
    file_path: Path,
    target: str,
    case_sensitive: bool = False,
    match_whole_word: bool = False,
    context: int = 2,
) -> List[Result]:
    """Search a file for a substring or whole-word match.

    Parameters
    ----------
    file_path : Path
        The path of the file to scan.
    target : str
        String to locate within the file.
    case_sensitive : bool, optional
        Use case-sensitive search. Defaults to False.
    match_whole_word : bool, optional
        Match only complete words. Defaults to False.
    context : int, optional
        Number of lines before and after the match to include as context.

    Returns
    -------
    List[Result]
        List of matches found in the file.
    """
    results = []
    try:
        lines = read(str(file_path), "rl")
    except (OSError, UnicodeError, FileNotFoundError):
        return results

    # Clean lines
    lines = [line.rstrip("\n") for line in lines]

    # Prepare searchable target and line
    target_cmp = target if case_sensitive else target.lower()

    for idx, line in enumerate(lines):
        line_cmp = line if case_sensitive else line.lower()
        match_type = None

        # Whole-word match using regex
        if match_whole_word:
            pattern = r"\b{}\b".format(re.escape(target))
            flags = 0 if case_sensitive else re.IGNORECASE
            if re.search(pattern, line, flags=flags):
                match_type = "whole_word"

        # Substring match
        elif target_cmp in line_cmp:
            match_type = "substring"

        if match_type:
            start = max(0, idx - context)
            end = min(len(lines), idx + context + 1)
            before = lines[start:idx]
            after = lines[idx + 1 : end]

            results.append(
                Result(
                    file=str(file_path),
                    line=line,
                    lineno=idx,
                    match=match_type,
                    context_before=before,
                    context_after=after,
                )
            )

    return results


def _path_search(
    root: str,
    target: str,
    pattern: str = "*",
    case_sensitive: bool = False,
    match_whole_word: bool = False,
    context: int = 2,
    max_fast: int = None,
) -> List[Result]:
    """
    Search recursively in a directory for a target string.

    Parameters
    ----------
    root : str
        Path to the directory to scan.
    target : str
        String to search for.
    pattern : str, optional
        Glob pattern to filter files. Defaults to "*".
    case_sensitive : bool, optional
        Enable case sensitivity. Defaults to False.
    match_whole_word : bool, optional
        Match only entire words. Defaults to False.
    context : int, optional
        Number of context lines to include. Defaults to 2.
    max_fast : int, optional
        Number of worker threads. Defaults to 5 × CPU count.

    Returns
    -------
    List[Result]
        All matches found across the directory tree.
    """
    root_path = Path(root)
    files = [f for f in root_path.rglob(pattern) if f.is_file()]

    if max_fast is None:
        max_fast = os.cpu_count() * 5

    results: List[Result] = []

    with ThreadPoolExecutor(max_workers=max_fast) as executor:
        futures = {
            executor.submit(
                _search_in_file, f, target, case_sensitive, match_whole_word, context
            ): f
            for f in files
        }

        for future in as_completed(futures):
            res = future.result()
            if res:
                results.extend(res)

    return results
