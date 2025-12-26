"""Example Python file for testing."""


def hello_world():
    """Print hello world."""
    print("Hello, World!")


class Calculator:
    """Simple calculator class."""

    def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    def multiply(self, a: int, b: int) -> int:
        """Multiply two numbers."""
        return a * b


if __name__ == "__main__":
    calc = Calculator()
    print(f"2 + 3 = {calc.add(2, 3)}")
    print(f"4 * 5 = {calc.multiply(4, 5)}")
