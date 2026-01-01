"""Simple hello world helper for Codex validation."""


def say_hello(name: str) -> str:
    """Return a friendly greeting for the provided name."""
    return f"Hello from Codex, {name}!"


if __name__ == "__main__":
    print(say_hello("World"))
