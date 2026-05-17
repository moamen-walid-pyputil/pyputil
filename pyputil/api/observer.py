#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from typing import Dict, List, Callable, Any


class APIObserver:
    """
    Observer pattern for API events.

    Implements publish-subscribe pattern for API lifecycle events.

    Attributes
    ----------
    _observers : Dict[str, List[Callable]]
        Event subscribers

    Examples
    --------
    >>> observer = APIObserver()
    >>> observer.subscribe('before_access', log_access)
    >>> observer.notify('before_access', 'api_function')
    """

    def __init__(self):
        """Initialize observer with event categories."""
        self._observers: Dict[str, List[Callable]] = {
            "before_access": [],
            "after_access": [],
            "on_error": [],
            "on_deprecated": [],
            "on_experimental": [],
        }

    def subscribe(self, event: str, callback: Callable):
        """
        Subscribe to API events.

        Parameters
        ----------
        event : str
            Event type to subscribe to
        callback : Callable
            Callback function

        Raises
        ------
        ValueError
            If event type is not recognized

        Notes
        -----
        Supported events: 'before_access', 'after_access', 'on_error',
        'on_deprecated', 'on_experimental'
        """
        if event not in self._observers:
            raise ValueError(f"Unknown event type: {event}")

        self._observers[event].append(callback)

    def notify(self, event: str, *args, **kwargs):
        """
        Notify observers of an event.

        Parameters
        ----------
        event : str
            Event type
        *args
            Positional arguments for callback
        **kwargs
            Keyword arguments for callback

        Notes
        -----
        Callbacks are executed in order of subscription.
        Exceptions in callbacks are caught and logged.
        """
        for callback in self._observers.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                # Log error but don't break notification chain
                import logging

                logging.error(f"Error in observer callback for {event}: {e}")
