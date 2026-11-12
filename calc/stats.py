"""Statistics for lists of numbers."""


from calc import CalcError


def mean(numbers):
    if not numbers:
        raise CalcError("the mean of no numbers")
    return sum(numbers) / len(numbers)
