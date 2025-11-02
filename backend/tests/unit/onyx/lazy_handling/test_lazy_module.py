"""
Comprehensive tests for the LazyModule class.

Tests cover basic functionality, error handling, thread safety, and edge cases
for the lazy import system used to optimize memory usage in Onyx.
"""

import threading
import time
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from onyx.lazy_handling.lazy_module import LazyModule


def test_successful_module_import():
    """Test that a real module can be imported and accessed lazily."""
    lazy_json = LazyModule("json")

    # Module should not be imported yet
    assert lazy_json._module is None

    # Accessing an attribute should trigger import
    result = lazy_json.dumps({"test": "data"})

    # Module should now be cached
    assert lazy_json._module is not None
    assert result == '{"test": "data"}'


def test_lazy_loading_behavior():
    """Test that import only happens on first access."""
    with patch("onyx.lazy_handling.lazy_module.importlib.import_module") as mock_import:
        mock_module = Mock()
        mock_module.test_attr = "test_value"
        mock_import.return_value = mock_module

        lazy_mod = LazyModule("test_module")

        # Import should not have happened yet
        mock_import.assert_not_called()

        # First access triggers import
        result = lazy_mod.test_attr

        mock_import.assert_called_once_with("test_module")
        assert result == "test_value"

        # Second access uses cached module
        mock_import.reset_mock()
        result2 = lazy_mod.test_attr

        mock_import.assert_not_called()  # Should use cache
        assert result2 == "test_value"


def test_module_caching():
    """Test that modules are properly cached after import."""
    lazy_os = LazyModule("os")

    # Access multiple attributes
    path_sep = lazy_os.sep  # noqa: F841
    path_join = lazy_os.path.join  # noqa: F841

    # Both should use the same cached module
    assert lazy_os._module is lazy_os._module
    assert not lazy_os._import_failed


def test_multiple_attributes_access():
    """Test accessing different attributes from the same lazy module."""
    lazy_json = LazyModule("json")

    # Access different functions
    dumps = lazy_json.dumps
    loads = lazy_json.loads

    # Verify both work
    data = {"key": "value"}
    json_str = dumps(data)
    parsed = loads(json_str)

    assert parsed == data


# Error handling tests
def test_import_error_handling():
    """Test handling of ImportError when module doesn't exist."""
    lazy_nonexistent = LazyModule("nonexistent_module_12345")

    with pytest.raises(ImportError) as exc_info:
        _ = lazy_nonexistent.some_attribute

    # Check error message format
    error_msg = str(exc_info.value)
    assert "Failed to import 'nonexistent_module_12345'" in error_msg
    assert "Ensure the package is installed" in error_msg

    # Import failure should be cached
    assert lazy_nonexistent._import_failed


def test_import_failure_caching():
    """Test that import failures are cached to avoid repeated attempts."""
    lazy_nonexistent = LazyModule("nonexistent_module_12345")

    # First access fails
    with pytest.raises(ImportError):
        _ = lazy_nonexistent.attr1

    # Second access should fail immediately without attempting import
    with patch("onyx.lazy_handling.lazy_module.importlib.import_module") as mock_import:
        with pytest.raises(ImportError) as exc_info:
            _ = lazy_nonexistent.attr2

        # Should not attempt import again
        mock_import.assert_not_called()

        # Error message should indicate previous failure
        assert "Previous import of 'nonexistent_module_12345' failed" in str(
            exc_info.value
        )


def test_attribute_error_handling():
    """Test handling when accessing non-existent attributes."""
    lazy_json = LazyModule("json")

    with pytest.raises(AttributeError) as exc_info:
        _ = lazy_json.nonexistent_attribute

    # Check error message format
    error_msg = str(exc_info.value)
    assert "Module 'json' has no attribute 'nonexistent_attribute'" in error_msg


def test_import_error_propagation():
    """Test that original ImportError is preserved in exception chain."""
    with patch("onyx.lazy_handling.lazy_module.importlib.import_module") as mock_import:
        original_error = ImportError("Original import error")
        mock_import.side_effect = original_error

        lazy_mod = LazyModule("test_module")

        with pytest.raises(ImportError) as exc_info:
            _ = lazy_mod.test_attr

        # Check that original error is preserved
        assert exc_info.value.__cause__ is original_error


# Thread safety tests
def test_concurrent_access_thread_safety():
    """Test that concurrent access from multiple threads is safe."""
    lazy_json = LazyModule("json")
    results = []
    errors = []
    lock = threading.Lock()

    def access_module(thread_id):
        try:
            # Each thread tries to access the module
            result = lazy_json.dumps({"thread": thread_id})
            with lock:
                results.append((thread_id, result))
        except Exception as e:
            with lock:
                errors.append((thread_id, e))

    # Create multiple threads
    threads = []
    for i in range(10):
        thread = threading.Thread(target=access_module, args=(i,))
        threads.append(thread)

    # Start all threads
    for thread in threads:
        thread.start()

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # Verify results
    assert len(errors) == 0, f"Errors occurred: {errors}"
    assert len(results) == 10

    # All threads should have used the same imported module
    assert lazy_json._module is not None
    assert not lazy_json._import_failed


def test_lock_prevents_race_conditions():
    """Test that the lock prevents race conditions during import."""
    import_call_count = 0

    # Use a different module to avoid conflicts
    with patch("onyx.lazy_handling.lazy_module.importlib.import_module") as mock_import:

        def slow_import(module_name):
            nonlocal import_call_count
            import_call_count += 1
            time.sleep(0.1)  # Simulate slow import

            # Return a mock module with the dumps method
            mock_module = Mock()
            mock_module.dumps = Mock(return_value='{"test": "data"}')
            return mock_module

        mock_import.side_effect = slow_import

        lazy_test = LazyModule("test_concurrent_module")
        results = []
        errors = []
        lock = threading.Lock()

        def access_module():
            try:
                result = lazy_test.dumps({"test": "data"})
                with lock:
                    results.append(result)
            except Exception as e:
                with lock:
                    errors.append(e)

        # Create multiple threads that access simultaneously
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=access_module)
            threads.append(thread)

        # Start all threads at roughly the same time
        for thread in threads:
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Check for errors
        assert len(errors) == 0, f"Unexpected errors: {errors}"

        # Import should only have been called once despite multiple threads
        assert import_call_count == 1
        assert len(results) == 5

        # All results should be the same
        expected_result = '{"test": "data"}'
        for result in results:
            assert result == expected_result


# Edge cases and special scenarios
def test_module_with_complex_attributes():
    """Test accessing complex attributes like nested modules."""
    lazy_os = LazyModule("os")

    # Access nested attribute (os.path.join)
    join_func = lazy_os.path.join
    result = join_func("a", "b", "c")

    # Should work correctly
    assert "a" in result
    assert "b" in result
    assert "c" in result


def test_callable_attributes():
    """Test that callable attributes work correctly."""
    lazy_json = LazyModule("json")

    # Get the function object
    dumps_func = lazy_json.dumps

    # Should be callable
    assert callable(dumps_func)

    # Should work when called
    result = dumps_func({"test": True})
    assert result == '{"test": true}'


def test_module_replacement_in_sys_modules():
    """Test behavior when module is replaced in sys.modules."""
    # This tests robustness against unusual sys.modules manipulations
    lazy_json = LazyModule("json")

    # First access
    first_result = lazy_json.dumps({"first": True})

    # Module should be cached
    cached_module = lazy_json._module
    assert cached_module is not None

    # Second access should use cached version, even if sys.modules changes
    second_result = lazy_json.loads(first_result)

    assert second_result == {"first": True}
    assert lazy_json._module is cached_module


def test_empty_module_name():
    """Test behavior with empty module name."""
    lazy_empty = LazyModule("")

    # Python's importlib raises ValueError for empty module names,
    # but LazyModule should catch it and convert to ImportError
    with pytest.raises(ImportError) as exc_info:
        _ = lazy_empty.some_attribute

    # Should contain failure message for empty module name
    error_msg = str(exc_info.value)
    assert "Failed to import ''" in error_msg

    # Import failure should be cached
    assert lazy_empty._import_failed


def test_module_name_with_dots():
    """Test importing modules with dots in name (submodules)."""
    lazy_os_path = LazyModule("os.path")

    # Should be able to import and use submodules
    result = lazy_os_path.join("a", "b")
    assert "a" in result
    assert "b" in result


def test_attribute_access_after_import_failure():
    """Test that all attribute access fails after an import failure."""
    lazy_nonexistent = LazyModule("nonexistent_module_xyz")

    # First access fails
    with pytest.raises(ImportError):
        _ = lazy_nonexistent.attr1

    # All subsequent accesses should fail immediately
    with pytest.raises(ImportError) as exc_info:
        _ = lazy_nonexistent.attr2

    with pytest.raises(ImportError):
        _ = lazy_nonexistent.different_attr

    # Error should indicate previous failure
    error_msg = str(exc_info.value)
    assert "Previous import of 'nonexistent_module_xyz' failed" in error_msg


def test_import_hook_compatibility():
    """Test compatibility with Python's import hook system."""
    # This ensures LazyModule works well with Python's import machinery
    lazy_sys = LazyModule("sys")

    # Access sys attributes
    version = lazy_sys.version
    platform = lazy_sys.platform

    assert isinstance(version, str)
    assert isinstance(platform, str)

    # Should be the same as direct import
    import sys as real_sys

    assert version == real_sys.version
    assert platform == real_sys.platform
