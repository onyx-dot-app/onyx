import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.check_lazy_imports import EagerImportResult
from scripts.check_lazy_imports import find_eager_imports
from scripts.check_lazy_imports import find_python_files
from scripts.check_lazy_imports import LazyImportSettings
from scripts.check_lazy_imports import main


def test_find_eager_imports_basic_violations() -> None:
    """Test detection of basic eager import violations."""
    test_content = """
import vertexai
from vertexai import generative_models
import transformers
from transformers import AutoTokenizer
import os  # This should not be flagged
from typing import Dict
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_content)
        test_path = Path(f.name)

    try:
        protected_modules = {"vertexai", "transformers"}
        result = find_eager_imports(test_path, protected_modules)

        # Should find 4 violations (lines 2, 3, 4, 5)
        assert len(result.violation_lines) == 4
        assert result.violated_modules == {"vertexai", "transformers"}

        # Check specific violations
        violation_line_numbers = [line_num for line_num, _ in result.violation_lines]
        assert 2 in violation_line_numbers  # import vertexai
        assert 3 in violation_line_numbers  # from vertexai import generative_models
        assert 4 in violation_line_numbers  # import transformers
        assert 5 in violation_line_numbers  # from transformers import AutoTokenizer

        # Lines 6 and 7 should not be flagged
        assert 6 not in violation_line_numbers  # import os
        assert 7 not in violation_line_numbers  # from typing import Dict

    finally:
        test_path.unlink()


def test_find_eager_imports_function_level_allowed() -> None:
    """Test that imports inside functions are allowed (lazy imports)."""
    test_content = """import os

def some_function():
    import vertexai
    from transformers import AutoTokenizer
    return vertexai.some_method()

class MyClass:
    def method(self):
        import vertexai
        return vertexai.other_method()

# Top-level imports should be flagged
import vertexai
from transformers import BertModel
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_content)
        test_path = Path(f.name)

    try:
        protected_modules = {"vertexai", "transformers"}
        result = find_eager_imports(test_path, protected_modules)

        # Should only find violations for top-level imports (lines 14, 15)
        assert len(result.violation_lines) == 2
        assert result.violated_modules == {"vertexai", "transformers"}

        violation_line_numbers = [line_num for line_num, _ in result.violation_lines]
        assert 14 in violation_line_numbers  # import vertexai (top-level)
        assert (
            15 in violation_line_numbers
        )  # from transformers import BertModel (top-level)

        # Function-level imports should not be flagged
        assert 4 not in violation_line_numbers  # import vertexai (in function)
        assert (
            5 not in violation_line_numbers
        )  # from transformers import AutoTokenizer (in function)
        assert 9 not in violation_line_numbers  # import vertexai (in method)

    finally:
        test_path.unlink()


def test_find_eager_imports_complex_patterns() -> None:
    """Test detection of various import patterns."""
    test_content = """
import vertexai.generative_models  # Should be flagged
from some_package import vertexai  # Should be flagged
import vertexai_utils  # Should not be flagged (different module)
from vertexai_wrapper import something  # Should not be flagged
import myvertexai  # Should not be flagged
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_content)
        test_path = Path(f.name)

    try:
        protected_modules = {"vertexai"}
        result = find_eager_imports(test_path, protected_modules)

        # Should find 2 violations (lines 2, 3)
        assert len(result.violation_lines) == 2
        assert result.violated_modules == {"vertexai"}

        violation_line_numbers = [line_num for line_num, _ in result.violation_lines]
        assert 2 in violation_line_numbers  # import vertexai.generative_models
        assert 3 in violation_line_numbers  # from some_package import vertexai

        # Lines 4, 5, 6 should not be flagged
        assert 4 not in violation_line_numbers
        assert 5 not in violation_line_numbers
        assert 6 not in violation_line_numbers

    finally:
        test_path.unlink()


def test_find_eager_imports_comments_ignored() -> None:
    """Test that commented imports are ignored."""
    test_content = """
# import vertexai  # This should be ignored
import os
# from vertexai import something  # This should be ignored
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_content)
        test_path = Path(f.name)

    try:
        protected_modules = {"vertexai"}
        result = find_eager_imports(test_path, protected_modules)

        # Should find no violations
        assert len(result.violation_lines) == 0
        assert result.violated_modules == set()

    finally:
        test_path.unlink()


def test_find_eager_imports_no_violations() -> None:
    """Test file with no violations."""
    test_content = """
import os
from typing import Dict, List
from pathlib import Path

def some_function():
    import vertexai
    return vertexai.some_method()
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_content)
        test_path = Path(f.name)

    try:
        protected_modules = {"vertexai", "transformers"}
        result = find_eager_imports(test_path, protected_modules)

        # Should find no violations
        assert len(result.violation_lines) == 0
        assert result.violated_modules == set()

    finally:
        test_path.unlink()


def test_find_eager_imports_file_read_error() -> None:
    """Test handling of file read errors."""
    # Create a file path that will cause read errors
    nonexistent_path = Path("/nonexistent/path/test.py")

    protected_modules = {"vertexai"}
    result = find_eager_imports(nonexistent_path, protected_modules)

    # Should return empty result on error
    assert len(result.violation_lines) == 0
    assert result.violated_modules == set()


def test_litellm_singleton_eager_import_detection() -> None:
    """Test detection of eager import of litellm_singleton module."""
    test_content = """
import os
from onyx.llm.litellm_singleton import litellm  # Should be flagged as eager import
from typing import Dict

def some_function():
    # This would be OK - lazy import
    from onyx.llm.litellm_singleton import litellm
    return litellm.some_method()
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_content)
        test_path = Path(f.name)

    try:
        protected_modules = {"onyx.llm.litellm_singleton"}
        result = find_eager_imports(test_path, protected_modules)

        # Should find one violation (line 3)
        assert len(result.violation_lines) == 1
        assert result.violated_modules == {"onyx.llm.litellm_singleton"}

        line_num, line = result.violation_lines[0]
        assert "from onyx.llm.litellm_singleton import litellm" in line

    finally:
        test_path.unlink()


def test_litellm_singleton_lazy_import_ok() -> None:
    """Test that lazy import of litellm_singleton is allowed."""
    test_content = """
import os
from typing import Dict

def get_litellm():
    # This is OK - lazy import inside function
    from onyx.llm.litellm_singleton import litellm
    return litellm

class SomeClass:
    def method(self):
        # Also OK - lazy import inside method
        from onyx.llm.litellm_singleton import litellm
        return litellm.completion()
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_content)
        test_path = Path(f.name)

    try:
        protected_modules = {"onyx.llm.litellm_singleton"}
        result = find_eager_imports(test_path, protected_modules)

        # Should find no violations
        assert len(result.violation_lines) == 0
        assert result.violated_modules == set()

    finally:
        test_path.unlink()


def test_find_eager_imports_return_type() -> None:
    """Test that function returns correct EagerImportResult type."""
    test_content = """
import vertexai
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_content)
        test_path = Path(f.name)

    try:
        protected_modules = {"vertexai"}
        result = find_eager_imports(test_path, protected_modules)

        # Check return type
        assert isinstance(result, EagerImportResult)
        assert hasattr(result, "violation_lines")
        assert hasattr(result, "violated_modules")
        assert len(result.violation_lines) == 1
        assert result.violated_modules == {"vertexai"}

    finally:
        test_path.unlink()


def test_main_function_no_violations(tmp_path: Path) -> None:
    """Test main function with no violations."""
    # Create a temporary backend directory structure
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()

    # Create a Python file with no violations (avoid "test" in name)
    clean_file = backend_dir / "clean_module.py"
    clean_file.write_text(
        """
import os
from pathlib import Path

def use_vertexai():
    import vertexai
    return vertexai.some_method()

def use_playwright():
    from playwright.sync_api import sync_playwright
    return sync_playwright().start()

def use_nltk():
    import nltk
    return nltk.download('stopwords')
"""
    )

    # Mock __file__ to point to our temporary structure
    script_path = backend_dir / "scripts" / "check_lazy_imports.py"
    script_path.parent.mkdir(parents=True)

    with patch("scripts.check_lazy_imports.__file__", str(script_path)):
        # Should not raise an exception since all imports are inside functions
        main(
            {
                "vertexai": LazyImportSettings(),
                "playwright": LazyImportSettings(),
                "nltk": LazyImportSettings(),
            }
        )


def test_main_function_with_violations(tmp_path: Path) -> None:
    """Test main function with violations."""
    # Create a temporary backend directory structure
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()

    # Create a Python file with violations (avoid "test" in name)
    violation_file = backend_dir / "violation_module.py"
    violation_file.write_text(
        """
import vertexai
import nltk
from playwright.sync_api import sync_playwright
"""
    )

    # Mock __file__ to point to our temporary structure
    script_path = backend_dir / "scripts" / "check_lazy_imports.py"
    script_path.parent.mkdir(parents=True)

    with patch("scripts.check_lazy_imports.__file__", str(script_path)):
        # Should raise RuntimeError due to violations
        with pytest.raises(
            RuntimeError,
            match="Found eager imports of .+\\. You must import them only when needed",
        ):
            main(
                {
                    "vertexai": LazyImportSettings(),
                    "playwright": LazyImportSettings(),
                    "nltk": LazyImportSettings(),
                }
            )


def test_main_function_specific_modules_only() -> None:
    """Test that only specific modules in protected list are flagged."""
    test_content = """
import requests  # Should not be flagged
import vertexai  # Should be flagged
import nltk  # Should be flagged
from playwright.sync_api import sync_playwright  # Should be flagged
import numpy  # Should not be flagged
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_content)
        test_path = Path(f.name)

    try:
        protected_modules = {"vertexai", "playwright", "nltk"}
        result = find_eager_imports(test_path, protected_modules)

        # Should only flag vertexai, nltk, and playwright
        assert len(result.violation_lines) == 3
        assert result.violated_modules == {"vertexai", "playwright", "nltk"}

        violation_line_numbers = [line_num for line_num, _ in result.violation_lines]
        assert 3 in violation_line_numbers  # import vertexai
        assert 4 in violation_line_numbers  # import nltk
        assert (
            5 in violation_line_numbers
        )  # from playwright.sync_api import sync_playwright
        assert 2 not in violation_line_numbers  # import requests (not protected)
        assert 6 not in violation_line_numbers  # import numpy (not protected)

    finally:
        test_path.unlink()


def test_mixed_violations_and_clean_imports() -> None:
    """Test files with both violations and allowed function-level imports."""
    test_content = """
# Top-level violation
import vertexai
import nltk

import os  # This is fine, not protected

def process_data():
    # Function-level import is allowed
    import vertexai
    import nltk
    from playwright.sync_api import sync_playwright
    return "processed"

class DataProcessor:
    def __init__(self):
        # Method-level import is allowed
        import playwright
        self.browser = playwright.chromium.launch()

# Another top-level violation
from playwright.sync_api import BrowserContext
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_content)
        test_path = Path(f.name)

    try:
        protected_modules = {"vertexai", "playwright", "nltk"}
        result = find_eager_imports(test_path, protected_modules)

        # Should find 3 top-level violations
        assert len(result.violation_lines) == 3
        assert result.violated_modules == {"vertexai", "playwright", "nltk"}

        violation_line_numbers = [line_num for line_num, _ in result.violation_lines]
        assert 3 in violation_line_numbers  # import vertexai (top-level)
        assert 4 in violation_line_numbers  # import nltk (top-level)
        assert (
            22 in violation_line_numbers
        )  # from playwright.sync_api import BrowserContext (top-level)

        # Function and method level imports should not be flagged
        assert 9 not in violation_line_numbers  # import vertexai (in function)
        assert 10 not in violation_line_numbers  # import nltk (in function)
        assert (
            11 not in violation_line_numbers
        )  # from playwright.sync_api import sync_playwright (in function)
        assert 17 not in violation_line_numbers  # import playwright (in method)

    finally:
        test_path.unlink()


def test_find_python_files_basic() -> None:
    """Test finding Python files with basic filtering."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        backend_dir = Path(tmp_dir)

        # Create various files
        (backend_dir / "normal.py").write_text("import os")
        (backend_dir / "test_file.py").write_text("import os")  # Should be excluded
        (backend_dir / "file_test.py").write_text("import os")  # Should be excluded

        # Create subdirectories
        (backend_dir / "subdir").mkdir()
        (backend_dir / "subdir" / "normal.py").write_text("import os")

        tests_dir = backend_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_something.py").write_text("import os")  # Should be excluded

        # Test - find_python_files no longer takes ignore directories parameter
        files = find_python_files(backend_dir)
        file_names = [f.name for f in files]

        assert "normal.py" in file_names
        assert "test_file.py" not in file_names
        assert "file_test.py" not in file_names
        assert "test_something.py" not in file_names
        assert (
            len([f for f in files if f.name == "normal.py"]) == 2
        )  # One in root, one in subdir


def test_find_python_files_ignore_venv_directories() -> None:
    """Test that find_python_files automatically ignores virtual environment directories."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        backend_dir = Path(tmp_dir)

        # Create files in various directories
        (backend_dir / "normal.py").write_text("import os")

        # Create venv directory (should be automatically ignored)
        venv_dir = backend_dir / "venv"
        venv_dir.mkdir()
        (venv_dir / "venv_file.py").write_text(
            "import transformers"
        )  # Should be excluded

        # Create .venv directory (should be automatically ignored)
        dot_venv_dir = backend_dir / ".venv"
        dot_venv_dir.mkdir()
        (dot_venv_dir / "should_be_ignored.py").write_text(
            "import vertexai"
        )  # Should be excluded

        # Create a file with venv in filename (should be included)
        (backend_dir / "venv_utils.py").write_text("import os")

        # Test - venv directories are automatically ignored
        files = find_python_files(backend_dir)
        file_names = [f.name for f in files]

        assert "normal.py" in file_names
        assert "venv_file.py" not in file_names  # Excluded because in venv directory
        assert (
            "should_be_ignored.py" not in file_names
        )  # Excluded because in .venv directory
        assert (
            "venv_utils.py" in file_names
        )  # Included because not in directory, just filename


def test_find_python_files_nested_venv() -> None:
    """Test that venv directories are ignored even when nested."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        backend_dir = Path(tmp_dir)

        # Create nested structure with venv
        nested_path = backend_dir / "some" / "path" / "venv" / "nested"
        nested_path.mkdir(parents=True)
        (nested_path / "deep_venv.py").write_text("import transformers")

        files = find_python_files(backend_dir)

        # Should exclude the deeply nested file in venv
        assert len(files) == 0


def test_playwright_violations() -> None:
    """Test detection of playwright import violations."""
    test_content = """
from playwright.sync_api import sync_playwright
from playwright.sync_api import BrowserContext, Playwright
import playwright.async_api
import playwright
import os  # This should not be flagged

def allowed_function():
    from playwright.sync_api import sync_playwright
    return sync_playwright()
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_content)
        test_path = Path(f.name)

    try:
        protected_modules = {"playwright"}
        result = find_eager_imports(test_path, protected_modules)

        # Should find 4 violations (lines 2, 3, 4, 5)
        assert len(result.violation_lines) == 4
        assert result.violated_modules == {"playwright"}

        violation_line_numbers = [line_num for line_num, _ in result.violation_lines]
        assert (
            2 in violation_line_numbers
        )  # from playwright.sync_api import sync_playwright
        assert (
            3 in violation_line_numbers
        )  # from playwright.sync_api import BrowserContext, Playwright
        assert 4 in violation_line_numbers  # import playwright.async_api
        assert 5 in violation_line_numbers  # import playwright
        assert 6 not in violation_line_numbers  # import os (not protected)
        assert 9 not in violation_line_numbers  # import in function (allowed)

    finally:
        test_path.unlink()


def test_nltk_violations() -> None:
    """Test detection of NLTK import violations."""
    test_content = """
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
import nltk.data
import requests  # This should not be flagged

def allowed_function():
    import nltk
    nltk.download('stopwords')
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_content)
        test_path = Path(f.name)

    try:
        protected_modules = {"nltk"}
        result = find_eager_imports(test_path, protected_modules)

        # Should find 4 violations (lines 2, 3, 4, 5)
        assert len(result.violation_lines) == 4
        assert result.violated_modules == {"nltk"}

        violation_line_numbers = [line_num for line_num, _ in result.violation_lines]
        assert 2 in violation_line_numbers  # import nltk
        assert 3 in violation_line_numbers  # from nltk.corpus import stopwords
        assert 4 in violation_line_numbers  # from nltk.tokenize import word_tokenize
        assert 5 in violation_line_numbers  # import nltk.data
        assert 6 not in violation_line_numbers  # import requests (not protected)
        assert 8 not in violation_line_numbers  # import in function (allowed)

    finally:
        test_path.unlink()


def test_all_three_protected_modules() -> None:
    """Test detection of vertexai, playwright, and nltk violations together."""
    test_content = """
import vertexai
import nltk
from playwright.sync_api import sync_playwright
import os  # This should not be flagged

def allowed_usage():
    import vertexai
    import nltk
    from playwright.sync_api import sync_playwright
    return "all good"
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_content)
        test_path = Path(f.name)

    try:
        protected_modules = {"vertexai", "playwright", "nltk"}
        result = find_eager_imports(test_path, protected_modules)

        # Should find 3 violations (lines 2, 3, 4)
        assert len(result.violation_lines) == 3
        assert result.violated_modules == {"vertexai", "playwright", "nltk"}

        violation_line_numbers = [line_num for line_num, _ in result.violation_lines]
        assert 2 in violation_line_numbers  # import vertexai
        assert 3 in violation_line_numbers  # import nltk
        assert (
            4 in violation_line_numbers
        )  # from playwright.sync_api import sync_playwright
        assert 5 not in violation_line_numbers  # import os (not protected)

        # Function-level imports should not be flagged
        assert 7 not in violation_line_numbers  # import vertexai (in function)
        assert 8 not in violation_line_numbers  # import nltk (in function)
        assert (
            9 not in violation_line_numbers
        )  # from playwright.sync_api import sync_playwright (in function)

    finally:
        test_path.unlink()
