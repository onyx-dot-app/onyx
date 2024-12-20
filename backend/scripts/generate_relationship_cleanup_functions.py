import inspect
import os
import re
import sys


_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_TARGET_DIRECTORY = os.path.join(_SCRIPT_DIR, "..", "danswer", "db")
_OUTPUT_FILE = os.path.join(_TARGET_DIRECTORY, "relationship_cleanup.py")

_RELATIONSHIP_CLEANUP_FUNC_NAME_TEMPLATE = "cleanup_{}_relationships"


def generate_relationship_cleanup_functions() -> None:
    # Define the regex pattern
    pattern = r"class\s+\w+__\w+"

    # Get all classes from the models module
    all_classes = [
        obj
        for name, obj in inspect.getmembers(sys.modules[__name__])
        if inspect.isclass(obj)
    ]

    # Filter classes based on the regex pattern
    matching_classes = [
        cls for cls in all_classes if re.match(pattern, f"class {cls.__name__}")
    ]

    # Generate imports for matching classes
    imports = "from sqlalchemy.orm import Session\n"
    imports += "from danswer.db.models import "
    imports += "\nfrom danswer.db.models import ".join(
        f"{cls.__name__}" for cls in matching_classes
    )

    output = imports + "\n"

    # Generate cleanup functions
    for cls in matching_classes:
        class_name = cls.__name__
        table_name = class_name.lower()

        # Inspect class variables to find id fields
        id_fields = [var for var in vars(cls) if var.endswith("_id")]

        # Pretty print class and fields
        print(f"\nClass: {class_name}")
        print(f"\tFields: {id_fields}")

        if len(id_fields) < 2:
            print(f"Relationship table {class_name} has less than 2 found id fields")
            print(
                "For this script to work, name id fields with the 'id' somewhere in the name"
            )
            raise

        function_name = _RELATIONSHIP_CLEANUP_FUNC_NAME_TEMPLATE.format(table_name)

        # Generate function signature
        signature = f"def {function_name}(\n    db_session: Session,\n"
        signature += ",\n".join(
            f"    {field}: int | None = None" for field in id_fields
        )
        signature += ",\n    commit: bool = False\n) -> None:"

        # Generate function body
        body = f'    """Cleanup {class_name} relationships."""\n'
        body += f"    query = db_session.query({class_name})\n\n"

        # Add check for all None inputs
        body += "\n    if all(param is None for param in ["
        body += ", ".join(id_fields)
        body += "]):\n"
        body += (
            '        raise ValueError("At least one parameter must be provided.")\n\n'
        )

        for field in id_fields:
            body += f"    if {field}:\n"
            body += f"        query = query.where({class_name}.{field} == {field})\n"

        body += "\n    query.delete(synchronize_session=False)\n\n"
        body += "    if commit:\n"
        body += "        db_session.commit()\n"

        # Combine signature and body
        output += f"\n{signature}\n{body}\n"

    os.makedirs(os.path.dirname(_OUTPUT_FILE), exist_ok=True)
    with open(_OUTPUT_FILE, "w") as f:
        f.write(output)

    print(f"Generated cleanup functions in {_OUTPUT_FILE}")


def generate_functions_for_object_deletion() -> None:
    pattern = r"class\s+\w+__\w+"
    all_classes = [
        obj
        for name, obj in inspect.getmembers(sys.modules[__name__])
        if inspect.isclass(obj)
    ]
    matching_classes = [
        cls for cls in all_classes if re.match(pattern, f"class {cls.__name__}")
    ]

    object_names = set()
    for cls in matching_classes:
        object_names.update(cls.__name__.split("__"))

    with open(_OUTPUT_FILE, "a") as f:
        for object_name in object_names:
            function_name = f"cleanup_relationships_for_{object_name.lower()}_deletion"

            f.write(
                f"\n\ndef {function_name}(db_session: Session, {object_name.lower()}_id: int, commit: bool = False) -> None:\n"
            )
            f.write(
                f'    """Cleanup all relationships for {object_name} deletion."""\n'
            )

            for cls in matching_classes:
                if object_name in cls.__name__:
                    relationship_function = (
                        _RELATIONSHIP_CLEANUP_FUNC_NAME_TEMPLATE.format(
                            cls.__name__.lower()
                        )
                    )
                    id_param = f"{object_name.lower()}_id"
                    other_params = ", ".join(
                        [
                            f"{field}=None"
                            for field in vars(cls)
                            if field.endswith("_id")
                            and not field.startswith(f"{object_name.lower()}_")
                        ]
                    )
                    f.write(
                        f"    {relationship_function}(db_session, {id_param}={id_param}, {other_params})\n"
                    )

            f.write("\n    if commit:\n")
            f.write("        db_session.commit()\n")

        f.write("\n")  # Add an empty line at the end of the file

    print(f"Generated object deletion cleanup functions in {_OUTPUT_FILE}")


if __name__ == "__main__":
    generate_relationship_cleanup_functions()
    generate_functions_for_object_deletion()
