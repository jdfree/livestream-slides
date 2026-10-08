"""Operators that can be replayed against a bundle. Add one here to make it
selectable from the runner's --operator flag."""
from .ml1 import ML1Operator

OPERATORS = {"ML1": ML1Operator}


def get(name: str):
    try:
        return OPERATORS[name]()
    except KeyError:
        raise SystemExit(f"unknown operator {name!r}; known: {', '.join(OPERATORS)}")
