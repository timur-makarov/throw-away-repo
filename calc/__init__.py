"""A tiny calculator: the test project for Rail's live run."""


class CalcError(Exception):
    """A calculation the calculator refuses, such as division by zero."""


def add(a, b):
    return a + b


def mul(a, b):
    return a * b


def sub(a, b):
    return a - b


def div(a, b):
    if b == 0:
        raise CalcError("division by zero")
    return a / b


def power(base, exponent):
    return base ** exponent
