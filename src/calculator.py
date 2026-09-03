"""Sample application used to demonstrate the doc_sync file watcher.

This module has no dependency on doc_sync.py. It exists purely to give the
watcher (src/doc_sync.py) something meaningful to monitor and document.
"""

from __future__ import annotations


def add(a: float, b: float) -> float:
    """Return the sum of two numbers.

    Args:
        a: The first operand.
        b: The second operand.

    Returns:
        The sum of ``a`` and ``b``.
    """
    return a + b


def subtract(a: float, b: float) -> float:
    """Return the difference between two numbers.

    Args:
        a: The value to subtract from.
        b: The value to subtract.

    Returns:
        The result of ``a - b``.
    """
    return a - b


def multiply(a: float, b: float) -> float:
    """Return the product of two numbers.

    Args:
        a: The first factor.
        b: The second factor.

    Returns:
        The product of ``a`` and ``b``.
    """
    return a * b


def divide(a: float, b: float) -> float:
    """Return the quotient of two numbers.

    Args:
        a: The dividend.
        b: The divisor. Must not be zero.

    Returns:
        The result of ``a / b``.

    Raises:
        ZeroDivisionError: If ``b`` is zero.
    """
    if b == 0:
        raise ZeroDivisionError("division by zero is not allowed")
    return a / b


class Calculator:
    """A simple calculator that keeps a running total.

    Attributes:
        total: The current running total, starting at 0.
    """

    def __init__(self, initial: float = 0.0) -> None:
        """Initialize the calculator with an optional starting value.

        Args:
            initial: The starting value for the running total.
        """
        self.total: float = initial

    def add(self, value: float) -> float:
        """Add ``value`` to the running total and return the new total."""
        self.total = add(self.total, value)
        return self.total

    def subtract(self, value: float) -> float:
        """Subtract ``value`` from the running total and return the new total."""
        self.total = subtract(self.total, value)
        return self.total

    def multiply(self, value: float) -> float:
        """Multiply the running total by ``value`` and return the new total."""
        self.total = multiply(self.total, value)
        return self.total

    def divide(self, value: float) -> float:
        """Divide the running total by ``value`` and return the new total."""
        self.total = divide(self.total, value)
        return self.total

    def reset(self) -> None:
        """Reset the running total back to zero."""
        self.total = 0.0

    def square(self, value: float) -> float:
        """Return the square of the running total multiplied by value."""
        self.total = multiply(self.total, value)
        return self.total


if __name__ == "__main__":
    calc = Calculator()
    calc.add(10)
    calc.multiply(3)
    calc.subtract(5)
    print(f"Result: {calc.total}")
