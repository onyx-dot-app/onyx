from __future__ import annotations

import importlib
import os
import pkgutil
import sys
from types import ModuleType
from typing import List
from typing import Type
from typing import TypeVar

T = TypeVar("T")


def import_all_modules_from_dir(dir_path: str) -> List[ModuleType]:
    """
    Imports all modules found in the given directory and its subdirectories,
    returning a list of imported module objects.
    """
    dir_path = os.path.abspath(dir_path)

    if dir_path not in sys.path:
        sys.path.insert(0, dir_path)

    imported_modules: List[ModuleType] = []

    for _, package_name, _ in pkgutil.walk_packages([dir_path]):
        try:
            module = importlib.import_module(package_name)
            imported_modules.append(module)
        except Exception as e:
            # Handle or log exceptions as needed
            print(f"Could not import {package_name}: {e}")

    return imported_modules


def all_subclasses(cls: Type[T]) -> List[Type[T]]:
    """
    Recursively find all subclasses of the given class.
    """
    direct_subs = cls.__subclasses__()
    result: List[Type[T]] = []
    for subclass in direct_subs:
        result.append(subclass)
        # Extend the result by recursively calling all_subclasses
        result.extend(all_subclasses(subclass))
    return result


def find_all_subclasses_in_dir(parent_class: Type[T], directory: str) -> List[Type[T]]:
    """
    Imports all modules from the given directory (and subdirectories),
    then returns all classes that are subclasses of parent_class.

    :param parent_class: The class to find subclasses of.
    :param directory: The directory to search for subclasses.
    :return: A list of all subclasses of parent_class found in the directory.
    """
    # First import all modules to ensure classes are loaded into memory
    import_all_modules_from_dir(directory)

    # Gather all subclasses of the given parent class
    subclasses = all_subclasses(parent_class)
    return subclasses


# Example usage:
if __name__ == "__main__":

    class Animal:
        pass

    # Suppose "mymodules" contains files that define classes inheriting from Animal
    found_subclasses = find_all_subclasses_in_dir(Animal, "mymodules")
    for sc in found_subclasses:
        print("Found subclass:", sc.__name__)
