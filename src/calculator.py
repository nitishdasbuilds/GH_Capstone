"""A small sample application used to exercise the doc_sync watcher.

This module intentionally contains simple, well-documented arithmetic
functions and a ``Calculator`` class so that ``src/doc_sync.py`` has
meaningful module/function structure to extract and render into
``README.md``. It has no dependency on ``doc_sync.py``.
"""

from __future__ import annotations


def add(a: float, b: float) -> float:
    """Return the sum of ``a`` and ``b``."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Return the result of subtracting ``b`` from ``a``."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Return the product of ``a`` and ``b``."""
    return a * b


def divide(a: float, b: float) -> float:
    """Return the result of dividing ``a`` by ``b``.

    Raises:
        ZeroDivisionError: If ``b`` is zero.
    """
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return a / b

#Adding a comment
class Calculator:
    """A tiny stateful calculator that accumulates a running total."""

    def __init__(self, initial: float = 0.0) -> None:
        """Initialize the calculator with an optional starting value."""
        self.value = initial

    def add(self, amount: float) -> float:
        """Add ``amount`` to the running total and return the new total."""
        self.value = add(self.value, amount)
        return self.value

    def subtract(self, amount: float) -> float:
        """Subtract ``amount`` from the running total and return the new total."""
        self.value = subtract(self.value, amount)
        return self.value

    def reset(self) -> float:
        """Reset the running total to zero and return it."""
        self.value = 0.0
        return self.value
