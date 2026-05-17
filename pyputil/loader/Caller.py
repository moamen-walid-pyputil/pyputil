#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import importlib
import inspect
import asyncio
import hashlib
import json
import logging
import time
from types import ModuleType
from typing import (
    Any, Optional, Union, Callable, Dict, List, Tuple, 
    TypeVar, Generic, Awaitable, cast
)
from functools import wraps
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
import traceback

# Configure module-level logger
logger = logging.getLogger(__name__)

# Type variables for better type hints
T = TypeVar('T')
CallResult = TypeVar('CallResult')


@dataclass
class CallContext:
    """
    Context object passed through middleware pipeline.
    
    Contains all information about the current call and allows middlewares
    to modify the execution flow.
    
    Attributes
    ----------
    target : str
        Target function/method name or path (e.g., 'module.func').
    args : tuple
        Positional arguments for the call.
    kwargs : dict
        Keyword arguments for the call.
    timeout : float
        Timeout in seconds for the call.
    max_retries : int
        Maximum number of retry attempts.
    use_cache : bool
        Whether to use caching for this call.
    start_time : float
        Timestamp when call was initiated.
    attempt : int
        Current retry attempt number (1-indexed).
    metadata : Dict[str, Any]
        Additional metadata that middlewares can use.
    """
    target: str
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    timeout: float = 30.0
    max_retries: int = 3
    use_cache: bool = True
    start_time: float = field(default_factory=time.time)
    attempt: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CallRecord:
    """
    Record of a completed call for history tracking.
    
    Attributes
    ----------
    target : str
        Target function/method name.
    args : tuple
        Positional arguments used.
    kwargs : dict
        Keyword arguments used.
    result : Any, optional
        Result of successful call.
    error : str, optional
        Error message if call failed.
    timestamp : float
        Time when call completed.
    duration : float
        Duration of call in seconds.
    success : bool
        Whether call was successful.
    attempt_count : int
        Number of attempts made.
    """
    target: str
    args: tuple
    kwargs: dict
    timestamp: float
    duration: float
    success: bool
    attempt_count: int = 1
    result: Any = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert record to dictionary for serialization."""
        return {
            'target': self.target,
            'args': self.args,
            'kwargs': self.kwargs,
            'result': self.result,
            'error': self.error,
            'timestamp': self.timestamp,
            'duration': self.duration,
            'success': self.success,
            'attempt_count': self.attempt_count
        }


class CallerError(Exception):
    """Base exception for caller-related errors."""
    pass


class TargetNotFoundError(CallerError):
    """Raised when target function/method cannot be found."""
    pass


class CallTimeoutError(CallerError):
    """Raised when call exceeds timeout."""
    pass


class InvalidTargetError(CallerError):
    """Raised when target is not callable."""
    pass


class MiddlewareType:
    """
    Type definition for middleware functions.
    
    Middleware functions should have signature:
    async def middleware(ctx: CallContext, next_call: Callable) -> Any
    """
    pass


class Caller:
    """
    Dynamic caller with middleware pipeline and comprehensive features.
    
    This class provides a flexible way to dynamically call functions and methods
    with support for caching, retries, timeout, middleware pipelines, and
    comprehensive call history tracking.
    
    Parameters
    ----------
    cache_ttl : int, default=300
        Cache time-to-live in seconds. Set to 0 to disable caching.
    max_retries : int, default=3
        Maximum number of retry attempts for failed calls.
    timeout : float, default=30.0
        Default timeout in seconds for calls.
    enable_logging : bool, default=True
        Whether to enable built-in logging middleware.
    cache_size_limit : int, default=1000
        Maximum number of items to store in cache.
    
    Attributes
    ----------
    last_call : Optional[str]
        Target of the most recent call.
    last_result : Any
        Result of the most recent call.
    call_history : List[CallRecord]
        History of all calls made.
    cache_stats : Dict[str, int]
        Statistics about cache usage.
    
    Examples
    --------
    Basic usage:
    >>> caller = Caller()
    >>> result = caller.call('math.sqrt', 16)
    >>> print(result)
    4.0
    
    With caching:
    >>> caller = Caller(cache_ttl=60)
    >>> result1 = caller.call('math.sqrt', 25)  # Executes
    >>> result2 = caller.call('math.sqrt', 25)  # Returns from cache
    
    Async usage:
    >>> async def example():
    ...     caller = Caller()
    ...     result = await caller.acall('asyncio.sleep', 1)
    ...     return result
    
    Custom middleware:
    >>> async def timing_middleware(ctx, next_call):
    ...     start = time.time()
    ...     result = await next_call(ctx)
    ...     print(f"Call took {time.time() - start:.2f}s")
    ...     return result
    >>> caller.add_middleware(timing_middleware)
    
    Notes
    -----
    - The caller uses a middleware pipeline where each middleware can modify
      the call context, add functionality, or short-circuit the call.
    - Built-in middlewares are automatically registered for caching, retries,
      timeout, and logging.
    - The caller is thread-safe when used with async/await patterns.
    """
    
    def __init__(
        self,
        cache_ttl: int = 300,
        max_retries: int = 3,
        timeout: float = 30.0,
        enable_logging: bool = True,
        cache_size_limit: int = 1000
    ):
        self._cache_ttl = cache_ttl
        self._max_retries = max_retries
        self._timeout = timeout
        self._cache_size_limit = cache_size_limit
        
        # Internal state
        self._last_call: Optional[str] = None
        self._last_result: Any = None
        self._call_history: List[CallRecord] = []
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._middlewares: List[Callable] = []
        self._cache_stats: Dict[str, int] = {
            'hits': 0,
            'misses': 0,
            'expired': 0,
            'size': 0
        }
        
        # Register built-in middlewares
        self._register_builtin_middlewares(enable_logging)
    
    def _register_builtin_middlewares(self, enable_logging: bool = True) -> None:
        """Register built-in middleware functions in correct order."""
        # Order matters: cache -> retry -> timeout -> logging
        self.add_middleware(self._cache_middleware)
        self.add_middleware(self._retry_middleware)
        self.add_middleware(self._timeout_middleware)
        if enable_logging:
            self.add_middleware(self._logging_middleware)
    
    def _generate_cache_key(self, context: CallContext) -> str:
        """
        Generate unique cache key from call context.
        
        Parameters
        ----------
        context : CallContext
            Call context containing target, args, and kwargs.
            
        Returns
        -------
        str
            MD5 hash cache key.
        """
        # Create deterministic representation
        key_data = {
            'target': context.target,
            'args': context.args,
            'kwargs': context.kwargs
        }
        
        # Convert to JSON with sorted keys for consistency
        key_str = json.dumps(key_data, sort_keys=True, default=str)
        
        # Generate hash for efficient storage
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _prune_cache(self) -> None:
        """Remove expired and excess cache entries."""
        current_time = time.time()
        
        # Remove expired entries
        expired_keys = [
            key for key, (_, timestamp) in self._cache.items()
            if current_time - timestamp > self._cache_ttl
        ]
        
        for key in expired_keys:
            del self._cache[key]
            self._cache_stats['expired'] += 1
        
        # Remove oldest entries if over limit
        if len(self._cache) > self._cache_size_limit:
            # Sort by timestamp and remove oldest
            sorted_items = sorted(
                self._cache.items(),
                key=lambda x: x[1][1]
            )
            to_remove = len(self._cache) - self._cache_size_limit
            for i in range(to_remove):
                del self._cache[sorted_items[i][0]]
        
        self._cache_stats['size'] = len(self._cache)
    
    async def _execute_with_middlewares(self, context: CallContext) -> Any:
        """
        Execute call through middleware pipeline.
        
        Parameters
        ----------
        context : CallContext
            Call context to pass through pipeline.
            
        Returns
        -------
        Any
            Result of the call.
            
        Raises
        ------
        Exception
            Any exception raised during execution.
        """
        # Create pipeline closure with index
        async def execute_pipeline(index: int = 0) -> Any:
            """Recursively execute middleware pipeline."""
            if index < len(self._middlewares):
                middleware = self._middlewares[index]
                # Create next call function
                async def next_call(ctx: CallContext) -> Any:
                    return await execute_pipeline(index + 1)
                return await middleware(context, next_call)
            else:
                return await self._execute_final_call(context)
        
        return await execute_pipeline()
    
    async def _execute_final_call(self, context: CallContext) -> Any:
        """
        Execute the final target function/method.
        
        Parameters
        ----------
        context : CallContext
            Call context with target and arguments.
            
        Returns
        -------
        Any
            Result of the target function/method.
            
        Raises
        ------
        TargetNotFoundError
            If target cannot be found.
        InvalidTargetError
            If target is not callable.
        """
        # Resolve target
        if '.' in context.target:
            module_name, func_name = context.target.rsplit('.', 1)
            method = self._get_from_module(module_name, func_name)
        else:
            # Try to get from current scope
            method = self._get_from_scope(context.target)
        
        # Validate method
        if method is None:
            raise TargetNotFoundError(
                f"Target '{context.target}' not found in module or scope"
            )
        
        if not callable(method):
            raise InvalidTargetError(
                f"Target '{context.target}' exists but is not callable (type: {type(method).__name__})"
            )
        
        # Execute with proper await handling
        try:
            if inspect.iscoroutinefunction(method):
                result = await method(*context.args, **context.kwargs)
            else:
                # Run sync function in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: method(*context.args, **context.kwargs)
                )
            
            return result
            
        except Exception as e:
            # Re-raise with context
            raise RuntimeError(
                f"Error calling '{context.target}': {str(e)}"
            ) from e
    
    # Built-in Middlewares
    async def _cache_middleware(
        self,
        context: CallContext,
        next_call: Callable[[CallContext], Awaitable[Any]]
    ) -> Any:
        """
        Cache middleware for result caching.
        
        This middleware caches results based on call signature and respects
        TTL and cache size limits.
        
        Parameters
        ----------
        context : CallContext
            Call context.
        next_call : Callable
            Next middleware in pipeline.
            
        Returns
        -------
        Any
            Cached or fresh result.
        """
        if not context.use_cache or self._cache_ttl <= 0:
            return await next_call(context)
        
        cache_key = self._generate_cache_key(context)
        current_time = time.time()
        
        # Check cache
        if cache_key in self._cache:
            result, timestamp = self._cache[cache_key]
            if current_time - timestamp < self._cache_ttl:
                self._cache_stats['hits'] += 1
                logger.debug(f"Cache hit for {context.target}")
                return result
            else:
                self._cache_stats['misses'] += 1
                del self._cache[cache_key]
        else:
            self._cache_stats['misses'] += 1
        
        # Execute and cache
        result = await next_call(context)
        self._cache[cache_key] = (result, current_time)
        self._prune_cache()
        
        return result
    
    async def _retry_middleware(
        self,
        context: CallContext,
        next_call: Callable[[CallContext], Awaitable[Any]]
    ) -> Any:
        """
        Retry middleware for handling transient failures.
        
        Implements exponential backoff for retry attempts.
        
        Parameters
        ----------
        context : CallContext
            Call context.
        next_call : Callable
            Next middleware in pipeline.
            
        Returns
        -------
        Any
            Result from successful attempt.
            
        Raises
        ------
        Exception
            Last exception if all retries fail.
        """
        last_exception = None
        max_retries = context.max_retries
        
        for attempt in range(1, max_retries + 1):
            context.attempt = attempt
            try:
                return await next_call(context)
            except Exception as e:
                last_exception = e
                logger.warning(
                    f"Attempt {attempt}/{max_retries} failed for {context.target}: {e}"
                )
                
                if attempt < max_retries:
                    # Exponential backoff with jitter
                    wait_time = min(2 ** (attempt - 1), 30)  # Cap at 30 seconds
                    # Add small jitter to avoid thundering herd
                    wait_time += (attempt * 0.1)
                    await asyncio.sleep(wait_time)
        
        # All retries exhausted
        raise last_exception
    
    async def _timeout_middleware(
        self,
        context: CallContext,
        next_call: Callable[[CallContext], Awaitable[Any]]
    ) -> Any:
        """
        Timeout middleware for enforcing call duration limits.
        
        Parameters
        ----------
        context : CallContext
            Call context.
        next_call : Callable
            Next middleware in pipeline.
            
        Returns
        -------
        Any
            Result if call completes within timeout.
            
        Raises
        ------
        CallTimeoutError
            If call exceeds timeout.
        """
        try:
            return await asyncio.wait_for(
                next_call(context),
                timeout=context.timeout
            )
        except asyncio.TimeoutError as e:
            raise CallTimeoutError(
                f"Call to '{context.target}' timed out after {context.timeout}s "
                f"(attempt {context.attempt})"
            ) from e
    
    async def _logging_middleware(
        self,
        context: CallContext,
        next_call: Callable[[CallContext], Awaitable[Any]]
    ) -> Any:
        """
        Logging middleware for call monitoring and debugging.
        
        Logs call start, completion, and errors at appropriate levels.
        
        Parameters
        ----------
        context : CallContext
            Call context.
        next_call : Callable
            Next middleware in pipeline.
            
        Returns
        -------
        Any
            Result of the call.
        """
        start_time = time.time()
        logger.debug(
            f"Calling {context.target} (attempt {context.attempt}) "
            f"args={context.args}, kwargs={context.kwargs}"
        )
        
        try:
            result = await next_call(context)
            duration = time.time() - start_time
            logger.debug(
                f"Completed {context.target} in {duration:.3f}s "
                f"(attempt {context.attempt})"
            )
            return result
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"Failed {context.target} after {duration:.3f}s "
                f"(attempt {context.attempt}): {e}"
            )
            raise
    
    # Core Public Methods
    async def acall(
        self,
        target: str,
        *args: Any,
        timeout: Optional[float] = None,
        retries: Optional[int] = None,
        use_cache: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> Any:
        """
        Asynchronously call a function or method with enhanced features.
        
        Parameters
        ----------
        target : str
            Target to call. Can be a function name or 'module.function' format.
        *args : Any
            Positional arguments for the call.
        timeout : float, optional
            Call timeout in seconds. Overrides instance default.
        retries : int, optional
            Maximum retry attempts. Overrides instance default.
        use_cache : bool, optional
            Enable/disable caching for this call. Overrides instance default.
        metadata : Dict[str, Any], optional
            Additional metadata to pass through context.
        **kwargs : Any
            Keyword arguments for the call.
            
        Returns
        -------
        Any
            Result of the target function/method.
            
        Raises
        ------
        TargetNotFoundError
            If target cannot be resolved.
        CallTimeoutError
            If call exceeds timeout.
        InvalidTargetError
            If target is not callable.
            
        Examples
        --------
        >>> caller = Caller()
        >>> result = await caller.acall('math.sqrt', 16)
        >>> print(result)
        4.0
        
        >>> # With custom timeout
        >>> result = await caller.acall('time.sleep', 5, timeout=1)
        Traceback (most recent call last):
        ...
        CallTimeoutError: Call to 'time.sleep' timed out after 1.0s
        
        >>> # With cache disabled
        >>> result = await caller.acall('random.random', use_cache=False)
        """
        # Create call context
        context = CallContext(
            target=target,
            args=args,
            kwargs=kwargs,
            timeout=timeout if timeout is not None else self._timeout,
            max_retries=retries if retries is not None else self._max_retries,
            use_cache=use_cache if use_cache is not None else True,
            start_time=time.time(),
            attempt=1,
            metadata=metadata or {}
        )
        
        # Execute through pipeline
        try:
            result = await self._execute_with_middlewares(context)
            
            # Update state
            self._last_call = target
            self._last_result = result
            
            # Record success
            self._call_history.append(CallRecord(
                target=target,
                args=args,
                kwargs=kwargs,
                result=result,
                timestamp=time.time(),
                duration=time.time() - context.start_time,
                success=True,
                attempt_count=context.attempt
            ))
            
            return result
            
        except Exception as e:
            # Record failure
            self._call_history.append(CallRecord(
                target=target,
                args=args,
                kwargs=kwargs,
                error=str(e),
                timestamp=time.time(),
                duration=time.time() - context.start_time,
                success=False,
                attempt_count=context.attempt
            ))
            raise
    
    def call(
        self,
        target: str,
        *args: Any,
        **kwargs: Any
    ) -> Any:
        """
        Synchronously call a function or method with enhanced features.
        
        This is a synchronous wrapper around acall that properly handles
        async event loops.
        
        Parameters
        ----------
        target : str
            Target to call. Can be a function name or 'module.function' format.
        *args : Any
            Positional arguments for the call.
        **kwargs : Any
            Keyword arguments for the call (including timeout, retries, use_cache).
            
        Returns
        -------
        Any
            Result of the target function/method.
            
        Examples
        --------
        >>> caller = Caller()
        >>> result = caller.call('math.sqrt', 16)
        >>> print(result)
        4.0
        """
        try:
            # Try to get existing event loop
            loop = asyncio.get_running_loop()
            # If we're already in async context, warn and create task
            import warnings
            warnings.warn(
                "Calling sync call() from async context. Use acall() instead.",
                RuntimeWarning
            )
            # Create new loop in thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    self.acall(target, *args, **kwargs)
                )
                return future.result()
        except RuntimeError:
            # No running loop, we can create one
            return asyncio.run(self.acall(target, *args, **kwargs))
    
    def add_middleware(self, middleware: Callable) -> None:
        """
        Add a custom middleware to the call pipeline.
        
        Middleware functions should have signature:
        async def middleware(ctx: CallContext, next_call: Callable) -> Any
        
        Parameters
        ----------
        middleware : Callable
            Async middleware function.
            
        Examples
        --------
        >>> async def audit_middleware(ctx, next_call):
        ...     print(f"Calling {ctx.target}")
        ...     result = await next_call(ctx)
        ...     print(f"Result: {result}")
        ...     return result
        >>> caller.add_middleware(audit_middleware)
        """
        if not callable(middleware):
            raise TypeError(f"Middleware must be callable, got {type(middleware)}")
        
        if not inspect.iscoroutinefunction(middleware):
            raise TypeError("Middleware must be an async function")
        
        self._middlewares.append(middleware)
        logger.debug(f"Added middleware: {middleware.__name__}")
    
    def remove_middleware(self, middleware: Callable) -> bool:
        """
        Remove a previously added middleware.
        
        Parameters
        ----------
        middleware : Callable
            Middleware function to remove.
            
        Returns
        -------
        bool
            True if middleware was found and removed, False otherwise.
        """
        try:
            self._middlewares.remove(middleware)
            logger.debug(f"Removed middleware: {middleware.__name__}")
            return True
        except ValueError:
            return False
    
    def clear_cache(self) -> int:
        """
        Clear all cached results.
        
        Returns
        -------
        int
            Number of cache entries cleared.
        """
        count = len(self._cache)
        self._cache.clear()
        self._cache_stats['size'] = 0
        logger.debug(f"Cleared {count} cache entries")
        return count
    
    def get_cache_stats(self) -> Dict[str, int]:
        """
        Get cache statistics.
        
        Returns
        -------
        Dict[str, int]
            Dictionary with cache statistics (hits, misses, size, etc.)
        """
        self._prune_cache()
        return self._cache_stats.copy()
    
    def get_call_history(
        self,
        limit: Optional[int] = None,
        success_only: bool = False,
        target_filter: Optional[str] = None
    ) -> List[CallRecord]:
        """
        Get call history with optional filtering.
        
        Parameters
        ----------
        limit : int, optional
            Maximum number of records to return (most recent).
        success_only : bool, default=False
            If True, only return successful calls.
        target_filter : str, optional
            Only return calls with target containing this string.
            
        Returns
        -------
        List[CallRecord]
            Filtered list of call records.
        """
        records = self._call_history
        
        if success_only:
            records = [r for r in records if r.success]
        
        if target_filter:
            records = [r for r in records if target_filter in r.target]
        
        if limit:
            records = records[-limit:]
        
        return records
    
    @asynccontextmanager
    async def temporary_middleware(self, middleware: Callable):
        """
        Context manager for temporary middleware.
        
        Parameters
        ----------
        middleware : Callable
            Middleware to add temporarily.
            
        Yields
        ------
        Caller
            Self reference for chaining.
            
        Examples
        --------
        >>> async with caller.temporary_middleware(profiling_middleware):
        ...     result = await caller.acall('expensive_function')
        """
        self.add_middleware(middleware)
        try:
            yield self
        finally:
            self.remove_middleware(middleware)
    
    def _get_from_module(self, module_name: str, func_name: str) -> Any:
        """
        Get a function from a module by name.
        
        Parameters
        ----------
        module_name : str
            Name of the module.
        func_name : str
            Name of the function/method.
            
        Returns
        -------
        Any
            The requested function or None if not found.
        """
        try:
            module = importlib.import_module(module_name)
            return getattr(module, func_name, None)
        except ImportError as e:
            logger.debug(f"Could not import module {module_name}: {e}")
            return None
    
    def _get_from_scope(self, name: str) -> Any:
        """
        Get a function from the current scope.
        
        Parameters
        ----------
        name : str
            Name of the function/method.
            
        Returns
        -------
        Any
            The requested function or None if not found.
        """
        # Try to get from builtins first
        if hasattr(__builtins__, name):
            return getattr(__builtins__, name)
        
        # Try to get from caller's frame
        try:
            frame = inspect.currentframe()
            if frame and frame.f_back:
                return frame.f_back.f_globals.get(name)
        except Exception:
            pass
        
        return None
    
    # Properties
    @property
    def last_call(self) -> Optional[str]:
        """Get the target of the most recent call."""
        return self._last_call
    
    @property
    def last_result(self) -> Any:
        """Get the result of the most recent call."""
        return self._last_result
    
    @property
    def call_history(self) -> List[CallRecord]:
        """Get a copy of the call history."""
        return self._call_history.copy()
    
    @property
    def cache_size(self) -> int:
        """Get current number of cached results."""
        self._prune_cache()
        return len(self._cache)
    
    @property
    def middleware_count(self) -> int:
        """Get number of registered middlewares."""
        return len(self._middlewares)
    
    @property
    def success_rate(self) -> float:
        """
        Calculate success rate of calls.
        
        Returns
        -------
        float
            Success rate as percentage (0-100).
        """
        if not self._call_history:
            return 0.0
        
        successful = sum(1 for r in self._call_history if r.success)
        return (successful / len(self._call_history)) * 100.0