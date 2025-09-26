import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List
from typing import Set

# Configure the logger
logging.basicConfig(
    level=logging.INFO,  # Set the log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # Log format
    handlers=[logging.StreamHandler()],  # Output logs to console
)

logger = logging.getLogger(__name__)

_MODULES_TO_LAZY_IMPORT = {"vertexai", "openai", "markitdown", "tiktoken"}


@dataclass
class EagerImportResult:
    """Result of checking a file for eager imports."""

    violation_lines: List[tuple[int, str]]  # (line_number, line_content) tuples
    violated_modules: Set[str]  # modules that were actually violated


def find_eager_imports(
    file_path: Path, protected_modules: Set[str]
) -> EagerImportResult:
    """
    Find eager imports of protected modules in a given file.

    Eager imports are top-level (module-level) imports that happen immediately
    when the module is loaded, as opposed to lazy imports that happen inside
    functions only when called.

    Args:
        file_path: Path to Python file to check
        protected_modules: Set of module names that should only be imported lazily

    Returns:
        EagerImportResult containing violations list and violated modules set
    """
    violation_lines = []
    violated_modules = set()

    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split("\n")

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()

            # Skip comments and empty lines
            if not stripped or stripped.startswith("#"):
                continue

            # Only check imports at module level (indentation == 0)
            current_indent = len(line) - len(line.lstrip())
            if current_indent == 0:
                # Check for eager imports of protected modules
                for module in protected_modules:
                    # Pattern 1: import module
                    if re.match(rf"^import\s+{re.escape(module)}(\s|$|\.)", stripped):
                        violation_lines.append((line_num, line))
                        violated_modules.add(module)

                    # Pattern 2: from module import ...
                    elif re.match(rf"^from\s+{re.escape(module)}(\s|\.|$)", stripped):
                        violation_lines.append((line_num, line))
                        violated_modules.add(module)

                    # Pattern 3: from ... import module (less common but possible)
                    elif re.search(
                        rf"^from\s+[\w.]+\s+import\s+.*\b{re.escape(module)}\b",
                        stripped,
                    ):
                        violation_lines.append((line_num, line))
                        violated_modules.add(module)

    except Exception as e:
        print(f"Error reading {file_path}: {e}")

    return EagerImportResult(
        violation_lines=violation_lines, violated_modules=violated_modules
    )


def find_python_files(
    backend_dir: Path, ignore_directories: Set[str] | None = None
) -> List[Path]:
    """
    Find all Python files in the backend directory, excluding test files and ignored directories.

    Args:
        backend_dir: Path to the backend directory to search
        ignore_directories: Set of directory names to ignore (e.g., {"model_server", "tests"})

    Returns:
        List of Python file paths to check
    """
    if ignore_directories is None:
        ignore_directories = set()

    # Always ignore virtual environment directories
    venv_dirs = {".venv", "venv", ".env", "env", "__pycache__"}
    ignore_directories = ignore_directories.union(venv_dirs)

    python_files = []
    for file_path in backend_dir.glob("**/*.py"):
        # Skip test files (they can contain test imports)
        path_parts = file_path.parts
        if (
            "tests" in path_parts
            or file_path.name.startswith("test_")
            or file_path.name.endswith("_test.py")
        ):
            continue

        # Skip ignored directories (check directory names, not file names)
        if any(ignored_dir in path_parts[:-1] for ignored_dir in ignore_directories):
            continue

        python_files.append(file_path)

    return python_files


def main(
    modules_to_lazy_import: Set[str], directories_to_ignore: Set[str] | None = None
) -> None:
    backend_dir = Path(__file__).parent.parent  # Go up from scripts/ to backend/

    logger.info(
        f"Checking for direct imports of lazy modules: {', '.join(modules_to_lazy_import)}"
    )

    # Find all Python files to check
    target_python_files = find_python_files(backend_dir, directories_to_ignore)

    violations_found = False
    all_violated_modules = set()

    # Check each Python file
    for file_path in target_python_files:
        result = find_eager_imports(file_path, modules_to_lazy_import)

        if result.violation_lines:
            violations_found = True
            all_violated_modules.update(result.violated_modules)
            rel_path = file_path.relative_to(backend_dir)
            logger.error(f"\n❌ Eager import violations found in {rel_path}:")

            for line_num, line in result.violation_lines:
                logger.error(f"  Line {line_num}: {line.strip()}")

            # Suggest fix only for violated modules
            if result.violated_modules:
                logger.error(
                    f"  💡 You must import {', '.join(sorted(result.violated_modules))} only within functions when needed"
                )

    if violations_found:
        violated_modules_str = ", ".join(sorted(all_violated_modules))
        raise RuntimeError(
            f"Found eager imports of {violated_modules_str}. You must import them only when needed."
        )
    else:
        logger.info("✅ All lazy modules are properly imported!")


if __name__ == "__main__":
    try:
        main(_MODULES_TO_LAZY_IMPORT)
        sys.exit(0)
    except RuntimeError:
        sys.exit(1)
