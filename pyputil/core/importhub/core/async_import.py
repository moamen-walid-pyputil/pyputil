#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Asynchronous import functionality.
"""

import asyncio
import functools
from typing import Any, Coroutine
import concurrent.futures
from typing import Optional
from .loader import get_loader


class AsyncImporter:
    """
    Handles asynchronous module imports.
    
    Executes imports in a thread pool to avoid blocking the event loop.
    """
    
    def __init__(self, max_workers: int = 4):
        """
        Initialize async importer with thread pool.
        
        Parameters
        ----------
        max_workers : int
            Maximum number of worker threads.
        """
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers
        )
    
    async def import_module(
        self,
        module_name: str,
        reload: bool = False,
        lazy: bool = False,
        inject_globals: Optional[dict] = None,
        search_paths: Optional[list] = None,
    ) -> Any:
        """
        Import module asynchronously.
        
        Parameters
        ----------
        module_name : str
            Module name.
        reload : bool
            Force reload.
        lazy : bool
            Lazy loading.
        inject_globals : dict, optional
            Globals to inject.
        search_paths : list, optional
            Additional search paths.
        
        Returns
        -------
        Any
            Imported module.
        """
        loop = asyncio.get_event_loop()
        
        # Run import in thread pool
        return await loop.run_in_executor(
            self._executor,
            functools.partial(
                get_loader().load_module,
                module_name=module_name,
                reload=reload,
                lazy=lazy,
                inject_globals=inject_globals,
                search_paths=search_paths,
            )
        )
    
    async def import_from_file(
        self,
        file_path: str,
        reload: bool = False,
        inject_globals: Optional[dict] = None,
    ) -> Any:
        """
        Import from file asynchronously.
        
        Parameters
        ----------
        file_path : str
            Path to file.
        reload : bool
            Force reload.
        inject_globals : dict, optional
            Globals to inject.
        
        Returns
        -------
        Any
            Imported module.
        """
        loop = asyncio.get_event_loop()
        
        return await loop.run_in_executor(
            self._executor,
            functools.partial(
                get_loader().load_from_file,
                file_path=file_path,
                reload=reload,
                inject_globals=inject_globals,
            )
        )
    
    def shutdown(self):
        """Shutdown the thread pool."""
        self._executor.shutdown(wait=True)


# Global async importer instance
_global_async_importer = AsyncImporter()


def get_async_importer() -> AsyncImporter:
    """Get the global async importer instance."""
    return _global_async_importer