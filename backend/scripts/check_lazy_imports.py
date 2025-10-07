import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict
from typing import List
from typing import Set

# Configure the logger
logging.basicConfig(
    level=logging.INFO,  # Set the log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # Log format
    handlers=[logging.StreamHandler()],  # Output logs to console
)

logger = logging.getLogger(__name__)


@dataclass
class LazyImportSettings:
    """Settings for which files to ignore when checking for lazy imports."""

    ignore_files: Set[str] | None = None


# Map of modules to lazy import -> settings for what to ignore
_LAZY_IMPORT_MODULES_TO_IGNORE_SETTINGS: Dict[str, LazyImportSettings] = {
    "vertexai": LazyImportSettings(),
    "openai": LazyImportSettings(),
    "markitdown": LazyImportSettings(),
    "tiktoken": LazyImportSettings(),
    "transformers": LazyImportSettings(ignore_files={"model_server/main.py"}),
    "setfit": LazyImportSettings(),
    "unstructured": LazyImportSettings(),
    "onyx.llm.litellm_singleton": LazyImportSettings(),
    "litellm": LazyImportSettings(
        ignore_files={
            "onyx/llm/litellm_singleton.py",
        }
    ),
    "nltk": LazyImportSettings(),
    "trafilatura": LazyImportSettings(),
    "pypdf": LazyImportSettings(),
    "unstructured_client": LazyImportSettings(),
}


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


def find_python_files(backend_dir: Path) -> List[Path]:
    """
    Find all Python files in the backend directory, excluding test files.

    Args:
        backend_dir: Path to the backend directory to search

    Returns:
        List of Python file paths to check
    """

    # Always ignore virtual environment directories
    ignore_directories = {".venv", "venv", ".env", "env", "__pycache__"}

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

        # Skip ignored directories
        if any(ignored_dir in path_parts for ignored_dir in ignore_directories):
            continue

        python_files.append(file_path)

    return python_files


def should_check_file_for_module(
    file_path: Path, backend_dir: Path, settings: LazyImportSettings
) -> bool:
    """
    Check if a file should be checked for a specific module's imports.

    Args:
        file_path: Path to the file to check
        backend_dir: Path to the backend directory
        settings: Settings containing files to ignore for this module

    Returns:
        True if the file should be checked, False if it should be ignored
    """
    if not settings.ignore_files:
        # Empty set means check everywhere
        return True

    # Get relative path from backend directory
    rel_path = file_path.relative_to(backend_dir)
    rel_path_str = rel_path.as_posix()

    return rel_path_str not in settings.ignore_files


def main(modules_to_lazy_import: Dict[str, LazyImportSettings]) -> None:
    backend_dir = Path(__file__).parent.parent  # Go up from scripts/ to backend/

    logger.info(
        f"Checking for direct imports of lazy modules: {', '.join(modules_to_lazy_import.keys())}"
    )

    # Find all Python files to check
    target_python_files = find_python_files(backend_dir)

    violations_found = False
    all_violated_modules = set()

    # Check each Python file for each module with its specific ignore directories
    for file_path in target_python_files:
        # Determine which modules should be checked for this file
        modules_to_check = set()
        for module_name, settings in modules_to_lazy_import.items():
            if should_check_file_for_module(file_path, backend_dir, settings):
                modules_to_check.add(module_name)

        if not modules_to_check:
            # This file is ignored for all modules
            continue

        result = find_eager_imports(file_path, modules_to_check)

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
                    f"  💡 You must lazy import {', '.join(sorted(result.violated_modules))} within functions when needed"
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
        main(_LAZY_IMPORT_MODULES_TO_IGNORE_SETTINGS)
        sys.exit(0)
    except RuntimeError:
        sys.exit(1)
