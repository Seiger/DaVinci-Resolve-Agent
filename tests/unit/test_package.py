"""Package import tests."""

import agent


def test_package_imports() -> None:
    assert agent.__version__ == "0.1.0"

