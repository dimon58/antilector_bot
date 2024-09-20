from typing import TypeVar

T = TypeVar("T")


def get_all_subclasses(cls: type[T]) -> list[T]:
    all_subclasses = []

    for subclass in cls.__subclasses__():
        all_subclasses.append(subclass)
        all_subclasses.extend(get_all_subclasses(subclass))

    return all_subclasses


def find_subclass(cls: type[T], subclass_name: str, *, strict_subclass: bool = True) -> type[T]:
    if not strict_subclass and cls.__name__ == subclass_name:
        return cls

    for subclass in cls.__subclasses__():
        if subclass.__name__ == subclass_name:
            return subclass

        found = find_subclass(subclass, subclass_name)
        if found is not None:
            return found

    return None
