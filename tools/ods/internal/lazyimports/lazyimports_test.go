package lazyimports

import (
	"os"
	"path/filepath"
	"testing"
)

// Helper function to create a temporary Python file with given content.
func createTempPythonFile(t *testing.T, content string) string {
	t.Helper()
	f, err := os.CreateTemp("", "test_*.py")
	if err != nil {
		t.Fatalf("Failed to create temp file: %v", err)
	}
	if _, err := f.WriteString(content); err != nil {
		_ = f.Close()
		_ = os.Remove(f.Name())
		t.Fatalf("Failed to write temp file: %v", err)
	}
	if err := f.Close(); err != nil {
		_ = os.Remove(f.Name())
		t.Fatalf("Failed to close temp file: %v", err)
	}
	return f.Name()
}

// Helper function to create patterns for given modules.
func createPatterns(modules []string) []modulePatterns {
	patterns := make([]modulePatterns, len(modules))
	for i, mod := range modules {
		patterns[i] = compileModulePatterns(mod)
	}
	return patterns
}

// Helper function to extract line numbers from violation lines.
func extractLineNumbers(violations []ViolationLine) []int {
	nums := make([]int, len(violations))
	for i, v := range violations {
		nums[i] = v.LineNum
	}
	return nums
}

// Helper function to check if a line number is in the list.
func containsLineNum(nums []int, target int) bool {
	for _, n := range nums {
		if n == target {
			return true
		}
	}
	return false
}

func TestFindEagerImportsBasicViolations(t *testing.T) {
	// Test detection of basic eager import violations.
	testContent := `
import google.genai
from google.genai import types
import transformers
from transformers import AutoTokenizer
import os  # This should not be flagged
from typing import Dict
`

	testPath := createTempPythonFile(t, testContent)
	defer func() { _ = os.Remove(testPath) }()

	patterns := createPatterns([]string{"google.genai", "transformers"})
	result, err := findEagerImports(testPath, patterns)
	if err != nil {
		t.Fatalf("findEagerImports failed: %v", err)
	}

	// Should find 4 violations (lines 2, 3, 4, 5)
	if len(result.ViolationLines) != 4 {
		t.Errorf("Expected 4 violations, got %d", len(result.ViolationLines))
	}

	if len(result.ViolatedModules) != 2 {
		t.Errorf("Expected 2 violated modules, got %d", len(result.ViolatedModules))
	}

	if _, ok := result.ViolatedModules["google.genai"]; !ok {
		t.Error("Expected google.genai in violated modules")
	}
	if _, ok := result.ViolatedModules["transformers"]; !ok {
		t.Error("Expected transformers in violated modules")
	}

	// Check specific violations
	lineNumbers := extractLineNumbers(result.ViolationLines)
	expectedLines := []int{2, 3, 4, 5}
	for _, expected := range expectedLines {
		if !containsLineNum(lineNumbers, expected) {
			t.Errorf("Expected line %d in violations", expected)
		}
	}

	// Lines 6 and 7 should not be flagged
	unexpectedLines := []int{6, 7}
	for _, unexpected := range unexpectedLines {
		if containsLineNum(lineNumbers, unexpected) {
			t.Errorf("Line %d should not be in violations", unexpected)
		}
	}
}

func TestFindEagerImportsFunctionLevelAllowed(t *testing.T) {
	// Test that imports inside functions are allowed (lazy imports).
	testContent := `import os

def some_function():
    import google.genai
    from transformers import AutoTokenizer
    return google.genai.some_method()

class MyClass:
    def method(self):
        import google.genai
        return google.genai.other_method()

# Top-level imports should be flagged
import google.genai
from transformers import BertModel
`

	testPath := createTempPythonFile(t, testContent)
	defer func() { _ = os.Remove(testPath) }()

	patterns := createPatterns([]string{"google.genai", "transformers"})
	result, err := findEagerImports(testPath, patterns)
	if err != nil {
		t.Fatalf("findEagerImports failed: %v", err)
	}

	// Should only find violations for top-level imports (lines 14, 15)
	if len(result.ViolationLines) != 2 {
		t.Errorf("Expected 2 violations, got %d", len(result.ViolationLines))
	}

	lineNumbers := extractLineNumbers(result.ViolationLines)

	// Top-level imports should be flagged
	if !containsLineNum(lineNumbers, 14) {
		t.Error("Expected line 14 (import google.genai top-level) in violations")
	}
	if !containsLineNum(lineNumbers, 15) {
		t.Error("Expected line 15 (from transformers import BertModel top-level) in violations")
	}

	// Function-level imports should NOT be flagged
	functionLevelLines := []int{4, 5, 10}
	for _, line := range functionLevelLines {
		if containsLineNum(lineNumbers, line) {
			t.Errorf("Line %d (function-level import) should not be in violations", line)
		}
	}
}

func TestFindEagerImportsComplexPatterns(t *testing.T) {
	// Test detection of various import patterns.
	testContent := `
import google.genai.types  # Should be flagged
from google.genai import models  # Should be flagged
import genai_utils  # Should not be flagged (different module)
from genai_wrapper import something  # Should not be flagged
import mygenai  # Should not be flagged
`

	testPath := createTempPythonFile(t, testContent)
	defer func() { _ = os.Remove(testPath) }()

	patterns := createPatterns([]string{"google.genai"})
	result, err := findEagerImports(testPath, patterns)
	if err != nil {
		t.Fatalf("findEagerImports failed: %v", err)
	}

	// Should find 2 violations (lines 2, 3)
	if len(result.ViolationLines) != 2 {
		t.Errorf("Expected 2 violations, got %d", len(result.ViolationLines))
	}

	if _, ok := result.ViolatedModules["google.genai"]; !ok {
		t.Error("Expected google.genai in violated modules")
	}

	lineNumbers := extractLineNumbers(result.ViolationLines)

	// Lines 2, 3 should be flagged
	if !containsLineNum(lineNumbers, 2) {
		t.Error("Expected line 2 in violations")
	}
	if !containsLineNum(lineNumbers, 3) {
		t.Error("Expected line 3 in violations")
	}

	// Lines 4, 5, 6 should NOT be flagged
	unexpectedLines := []int{4, 5, 6}
	for _, line := range unexpectedLines {
		if containsLineNum(lineNumbers, line) {
			t.Errorf("Line %d should not be in violations", line)
		}
	}
}

func TestFindEagerImportsCommentsIgnored(t *testing.T) {
	// Test that commented imports are ignored.
	testContent := `
# import google.genai  # This should be ignored
import os
# from google.genai import something  # This should be ignored
`

	testPath := createTempPythonFile(t, testContent)
	defer func() { _ = os.Remove(testPath) }()

	patterns := createPatterns([]string{"google.genai"})
	result, err := findEagerImports(testPath, patterns)
	if err != nil {
		t.Fatalf("findEagerImports failed: %v", err)
	}

	// Should find no violations
	if len(result.ViolationLines) != 0 {
		t.Errorf("Expected 0 violations, got %d", len(result.ViolationLines))
	}
	if len(result.ViolatedModules) != 0 {
		t.Errorf("Expected 0 violated modules, got %d", len(result.ViolatedModules))
	}
}

func TestFindEagerImportsNoViolations(t *testing.T) {
	// Test file with no violations.
	testContent := `
import os
from typing import Dict, List
from pathlib import Path

def some_function():
    import google.genai
    return google.genai.some_method()
`

	testPath := createTempPythonFile(t, testContent)
	defer func() { _ = os.Remove(testPath) }()

	patterns := createPatterns([]string{"google.genai", "transformers"})
	result, err := findEagerImports(testPath, patterns)
	if err != nil {
		t.Fatalf("findEagerImports failed: %v", err)
	}

	// Should find no violations
	if len(result.ViolationLines) != 0 {
		t.Errorf("Expected 0 violations, got %d", len(result.ViolationLines))
	}
	if len(result.ViolatedModules) != 0 {
		t.Errorf("Expected 0 violated modules, got %d", len(result.ViolatedModules))
	}
}

func TestFindEagerImportsFileReadError(t *testing.T) {
	// Test that an unreadable file fails the check instead of passing it.
	nonexistentPath := "/nonexistent/path/test.py"

	patterns := createPatterns([]string{"google.genai"})
	if _, err := findEagerImports(nonexistentPath, patterns); err == nil {
		t.Fatalf("Expected an error for a nonexistent file")
	}
}

func TestLitellmSingletonEagerImportDetection(t *testing.T) {
	// Test detection of eager import of litellm_singleton module.
	testContent := `
import os
from onyx.llm.litellm_singleton import litellm  # Should be flagged as eager import
from typing import Dict

def some_function():
    # This would be OK - lazy import
    from onyx.llm.litellm_singleton import litellm
    return litellm.some_method()
`

	testPath := createTempPythonFile(t, testContent)
	defer func() { _ = os.Remove(testPath) }()

	patterns := createPatterns([]string{"onyx.llm.litellm_singleton"})
	result, err := findEagerImports(testPath, patterns)
	if err != nil {
		t.Fatalf("findEagerImports failed: %v", err)
	}

	// Should find one violation (line 3)
	if len(result.ViolationLines) != 1 {
		t.Errorf("Expected 1 violation, got %d", len(result.ViolationLines))
	}

	if _, ok := result.ViolatedModules["onyx.llm.litellm_singleton"]; !ok {
		t.Error("Expected onyx.llm.litellm_singleton in violated modules")
	}

	if len(result.ViolationLines) > 0 {
		line := result.ViolationLines[0]
		if line.LineNum != 3 {
			t.Errorf("Expected violation on line 3, got line %d", line.LineNum)
		}
	}
}

func TestLitellmSingletonLazyImportOK(t *testing.T) {
	// Test that lazy import of litellm_singleton is allowed.
	testContent := `
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
`

	testPath := createTempPythonFile(t, testContent)
	defer func() { _ = os.Remove(testPath) }()

	patterns := createPatterns([]string{"onyx.llm.litellm_singleton"})
	result, err := findEagerImports(testPath, patterns)
	if err != nil {
		t.Fatalf("findEagerImports failed: %v", err)
	}

	// Should find no violations
	if len(result.ViolationLines) != 0 {
		t.Errorf("Expected 0 violations, got %d", len(result.ViolationLines))
	}
}

func TestFindPythonFilesBasic(t *testing.T) {
	// Test finding Python files with basic filtering.
	tmpDir, err := os.MkdirTemp("", "test_python_files_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer func() { _ = os.RemoveAll(tmpDir) }()

	// Create various files
	if err := os.WriteFile(filepath.Join(tmpDir, "normal.py"), []byte("import os"), 0644); err != nil {
		t.Fatalf("Failed to create normal.py: %v", err)
	}
	if err := os.WriteFile(filepath.Join(tmpDir, "test_file.py"), []byte("import os"), 0644); err != nil {
		t.Fatalf("Failed to create test_file.py: %v", err)
	}
	if err := os.WriteFile(filepath.Join(tmpDir, "file_test.py"), []byte("import os"), 0644); err != nil {
		t.Fatalf("Failed to create file_test.py: %v", err)
	}

	// Create subdirectory
	subdir := filepath.Join(tmpDir, "subdir")
	if err := os.MkdirAll(subdir, 0755); err != nil {
		t.Fatalf("Failed to create subdir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(subdir, "normal.py"), []byte("import os"), 0644); err != nil {
		t.Fatalf("Failed to create subdir/normal.py: %v", err)
	}

	// Create tests directory
	testsDir := filepath.Join(tmpDir, "tests")
	if err := os.MkdirAll(testsDir, 0755); err != nil {
		t.Fatalf("Failed to create tests dir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(testsDir, "test_something.py"), []byte("import os"), 0644); err != nil {
		t.Fatalf("Failed to create tests/test_something.py: %v", err)
	}

	files, err := FindPythonFiles(tmpDir)
	if err != nil {
		t.Fatalf("FindPythonFiles failed: %v", err)
	}

	fileNames := make(map[string]int)
	for _, f := range files {
		fileNames[filepath.Base(f)]++
	}

	// normal.py should appear twice (root and subdir)
	if fileNames["normal.py"] != 2 {
		t.Errorf("Expected 2 normal.py files, got %d", fileNames["normal.py"])
	}

	// test_file.py should be excluded
	if fileNames["test_file.py"] != 0 {
		t.Error("test_file.py should be excluded")
	}

	// file_test.py should be excluded
	if fileNames["file_test.py"] != 0 {
		t.Error("file_test.py should be excluded")
	}

	// test_something.py should be excluded (in tests directory)
	if fileNames["test_something.py"] != 0 {
		t.Error("test_something.py should be excluded")
	}
}

func TestFindPythonFilesIgnoreVenvDirectories(t *testing.T) {
	// Test that find_python_files automatically ignores virtual environment directories.
	tmpDir, err := os.MkdirTemp("", "test_venv_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer func() { _ = os.RemoveAll(tmpDir) }()

	// Create files in various directories
	if err := os.WriteFile(filepath.Join(tmpDir, "normal.py"), []byte("import os"), 0644); err != nil {
		t.Fatalf("Failed to create normal.py: %v", err)
	}

	// Create venv directory (should be automatically ignored)
	venvDir := filepath.Join(tmpDir, "venv")
	if err := os.MkdirAll(venvDir, 0755); err != nil {
		t.Fatalf("Failed to create venv dir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(venvDir, "venv_file.py"), []byte("import transformers"), 0644); err != nil {
		t.Fatalf("Failed to create venv/venv_file.py: %v", err)
	}

	// Create .venv directory (should be automatically ignored)
	dotVenvDir := filepath.Join(tmpDir, ".venv")
	if err := os.MkdirAll(dotVenvDir, 0755); err != nil {
		t.Fatalf("Failed to create .venv dir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dotVenvDir, "should_be_ignored.py"), []byte("import google.genai"), 0644); err != nil {
		t.Fatalf("Failed to create .venv/should_be_ignored.py: %v", err)
	}

	// Create a file with venv in filename (should be included)
	if err := os.WriteFile(filepath.Join(tmpDir, "venv_utils.py"), []byte("import os"), 0644); err != nil {
		t.Fatalf("Failed to create venv_utils.py: %v", err)
	}

	files, err := FindPythonFiles(tmpDir)
	if err != nil {
		t.Fatalf("FindPythonFiles failed: %v", err)
	}

	fileNames := make(map[string]bool)
	for _, f := range files {
		fileNames[filepath.Base(f)] = true
	}

	if !fileNames["normal.py"] {
		t.Error("normal.py should be included")
	}

	if fileNames["venv_file.py"] {
		t.Error("venv_file.py should be excluded (in venv directory)")
	}

	if fileNames["should_be_ignored.py"] {
		t.Error("should_be_ignored.py should be excluded (in .venv directory)")
	}

	if !fileNames["venv_utils.py"] {
		t.Error("venv_utils.py should be included (not in directory, just filename)")
	}
}

func TestFindPythonFilesNestedVenv(t *testing.T) {
	// Test that venv directories are ignored even when nested.
	tmpDir, err := os.MkdirTemp("", "test_nested_venv_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer func() { _ = os.RemoveAll(tmpDir) }()

	// Create nested structure with venv
	nestedPath := filepath.Join(tmpDir, "some", "path", "venv", "nested")
	if err := os.MkdirAll(nestedPath, 0755); err != nil {
		t.Fatalf("Failed to create nested path: %v", err)
	}
	if err := os.WriteFile(filepath.Join(nestedPath, "deep_venv.py"), []byte("import transformers"), 0644); err != nil {
		t.Fatalf("Failed to create deep_venv.py: %v", err)
	}

	files, err := FindPythonFiles(tmpDir)
	if err != nil {
		t.Fatalf("FindPythonFiles failed: %v", err)
	}

	// Should exclude the deeply nested file in venv
	if len(files) != 0 {
		t.Errorf("Expected 0 files, got %d", len(files))
	}
}

func TestPlaywrightViolations(t *testing.T) {
	// Test detection of playwright import violations.
	testContent := `
from playwright.sync_api import sync_playwright
from playwright.sync_api import BrowserContext, Playwright
import playwright.async_api
import playwright
import os  # This should not be flagged

def allowed_function():
    from playwright.sync_api import sync_playwright
    return sync_playwright()
`

	testPath := createTempPythonFile(t, testContent)
	defer func() { _ = os.Remove(testPath) }()

	patterns := createPatterns([]string{"playwright"})
	result, err := findEagerImports(testPath, patterns)
	if err != nil {
		t.Fatalf("findEagerImports failed: %v", err)
	}

	// Should find 4 violations (lines 2, 3, 4, 5)
	if len(result.ViolationLines) != 4 {
		t.Errorf("Expected 4 violations, got %d", len(result.ViolationLines))
	}

	if _, ok := result.ViolatedModules["playwright"]; !ok {
		t.Error("Expected playwright in violated modules")
	}

	lineNumbers := extractLineNumbers(result.ViolationLines)

	expectedLines := []int{2, 3, 4, 5}
	for _, expected := range expectedLines {
		if !containsLineNum(lineNumbers, expected) {
			t.Errorf("Expected line %d in violations", expected)
		}
	}

	// Line 6 (import os) should not be flagged
	if containsLineNum(lineNumbers, 6) {
		t.Error("Line 6 (import os) should not be flagged")
	}

	// Line 9 (import in function) should not be flagged
	if containsLineNum(lineNumbers, 9) {
		t.Error("Line 9 (import in function) should not be flagged")
	}
}

func TestNLTKViolations(t *testing.T) {
	// Test detection of NLTK import violations.
	testContent := `
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
import nltk.data
import requests  # This should not be flagged

def allowed_function():
    import nltk
    nltk.download('stopwords')
`

	testPath := createTempPythonFile(t, testContent)
	defer func() { _ = os.Remove(testPath) }()

	patterns := createPatterns([]string{"nltk"})
	result, err := findEagerImports(testPath, patterns)
	if err != nil {
		t.Fatalf("findEagerImports failed: %v", err)
	}

	// Should find 4 violations (lines 2, 3, 4, 5)
	if len(result.ViolationLines) != 4 {
		t.Errorf("Expected 4 violations, got %d", len(result.ViolationLines))
	}

	if _, ok := result.ViolatedModules["nltk"]; !ok {
		t.Error("Expected nltk in violated modules")
	}

	lineNumbers := extractLineNumbers(result.ViolationLines)

	expectedLines := []int{2, 3, 4, 5}
	for _, expected := range expectedLines {
		if !containsLineNum(lineNumbers, expected) {
			t.Errorf("Expected line %d in violations", expected)
		}
	}

	// Line 6 (import requests) should not be flagged
	if containsLineNum(lineNumbers, 6) {
		t.Error("Line 6 (import requests) should not be flagged")
	}

	// Line 9 (import in function) should not be flagged
	if containsLineNum(lineNumbers, 9) {
		t.Error("Line 9 (import in function) should not be flagged")
	}
}

func TestAllThreeProtectedModules(t *testing.T) {
	// Test detection of google.genai, playwright, and nltk violations together.
	testContent := `
import google.genai
import nltk
from playwright.sync_api import sync_playwright
import os  # This should not be flagged

def allowed_usage():
    import google.genai
    import nltk
    from playwright.sync_api import sync_playwright
    return "all good"
`

	testPath := createTempPythonFile(t, testContent)
	defer func() { _ = os.Remove(testPath) }()

	patterns := createPatterns([]string{"google.genai", "playwright", "nltk"})
	result, err := findEagerImports(testPath, patterns)
	if err != nil {
		t.Fatalf("findEagerImports failed: %v", err)
	}

	// Should find 3 violations (lines 2, 3, 4)
	if len(result.ViolationLines) != 3 {
		t.Errorf("Expected 3 violations, got %d", len(result.ViolationLines))
	}

	// All three modules should be in violated modules
	expectedModules := []string{"google.genai", "playwright", "nltk"}
	for _, mod := range expectedModules {
		if _, ok := result.ViolatedModules[mod]; !ok {
			t.Errorf("Expected %s in violated modules", mod)
		}
	}

	lineNumbers := extractLineNumbers(result.ViolationLines)

	// Top-level imports should be flagged
	expectedLines := []int{2, 3, 4}
	for _, expected := range expectedLines {
		if !containsLineNum(lineNumbers, expected) {
			t.Errorf("Expected line %d in violations", expected)
		}
	}

	// Line 5 (import os) should not be flagged
	if containsLineNum(lineNumbers, 5) {
		t.Error("Line 5 (import os) should not be flagged")
	}

	// Function-level imports should NOT be flagged
	functionLevelLines := []int{8, 9, 10}
	for _, line := range functionLevelLines {
		if containsLineNum(lineNumbers, line) {
			t.Errorf("Line %d (function-level import) should not be in violations", line)
		}
	}
}

func TestBraintrustAndExaViolations(t *testing.T) {
	// Both packages pull in openai (and braintrust also litellm) at import time.
	testContent := `
import braintrust
from braintrust import Eval
from exa_py import Exa
from exa_py.api import HighlightsContentsOptions
import braintrust_langchain  # Different package, not flagged

def allowed_function():
    from braintrust import init_dataset
    from exa_py import Exa
    return init_dataset, Exa
`

	testPath := createTempPythonFile(t, testContent)
	defer func() { _ = os.Remove(testPath) }()

	patterns := createPatterns([]string{"braintrust", "exa_py"})
	result, err := findEagerImports(testPath, patterns)
	if err != nil {
		t.Fatalf("findEagerImports failed: %v", err)
	}

	lineNumbers := extractLineNumbers(result.ViolationLines)
	expectedLines := []int{2, 3, 4, 5}
	if len(lineNumbers) != len(expectedLines) {
		t.Errorf("Expected %d violations, got %d (lines %v)", len(expectedLines), len(lineNumbers), lineNumbers)
	}
	for _, expected := range expectedLines {
		if !containsLineNum(lineNumbers, expected) {
			t.Errorf("Expected line %d in violations", expected)
		}
	}

	for _, mod := range []string{"braintrust", "exa_py"} {
		if _, ok := result.ViolatedModules[mod]; !ok {
			t.Errorf("Expected %s in violated modules", mod)
		}
	}
}

func TestIsValidPythonFile(t *testing.T) {
	tests := []struct {
		name     string
		path     string
		expected bool
	}{
		{"regular python file", "onyx/main.py", true},
		{"non-python file", "onyx/main.go", false},
		{"test file prefix", "onyx/test_main.py", false},
		{"test file suffix", "onyx/main_test.py", false},
		{"in tests directory", "tests/unit/test_main.py", false},
		{"in venv directory", "venv/lib/module.py", false},
		{"in .venv directory", ".venv/lib/module.py", false},
		{"in __pycache__ directory", "__pycache__/module.cpython-39.pyc", false},
		{"regular in subdir", "onyx/connectors/file.py", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := isValidPythonFile(tt.path)
			if result != tt.expected {
				t.Errorf("isValidPythonFile(%q) = %v, want %v", tt.path, result, tt.expected)
			}
		})
	}
}

func TestCompileModulePatterns(t *testing.T) {
	// Test pattern compilation for various modules.
	patterns := compileModulePatterns("google.genai")

	if patterns.moduleName != "google.genai" {
		t.Errorf("moduleName = %q, want %q", patterns.moduleName, "google.genai")
	}

	// Test import pattern
	testCases := []struct {
		line        string
		shouldMatch bool
		patternType string
	}{
		// Import pattern tests
		{"import google.genai", true, "import"},
		{"import google.genai.types", true, "import"},
		{"import google", false, "import"},
		{"import genai", false, "import"},
		// From pattern tests
		{"from google.genai import types", true, "from"},
		{"from google.genai.models import Model", true, "from"},
		{"from google import genai", false, "from"},
	}

	for _, tc := range testCases {
		var matched bool
		switch tc.patternType {
		case "import":
			matched = patterns.importPattern.MatchString(tc.line)
		case "from":
			matched = patterns.fromPattern.MatchString(tc.line)
		}
		if matched != tc.shouldMatch {
			t.Errorf("Pattern %s for %q = %v, want %v", tc.patternType, tc.line, matched, tc.shouldMatch)
		}
	}
}

func TestMultipleViolationsOnSameLine(t *testing.T) {
	// Test that a single line can match multiple modules.
	// Note: Python doesn't really support this, but let's verify behavior
	testContent := `
import google.genai
`

	testPath := createTempPythonFile(t, testContent)
	defer func() { _ = os.Remove(testPath) }()

	// Use patterns that might both match the same line
	patterns := createPatterns([]string{"google.genai", "google"})
	result, err := findEagerImports(testPath, patterns)
	if err != nil {
		t.Fatalf("findEagerImports failed: %v", err)
	}

	// The line should be flagged by google.genai pattern
	if len(result.ViolationLines) < 1 {
		t.Error("Expected at least 1 violation")
	}
}

func TestIgnoreEnvDirectory(t *testing.T) {
	// Test that env and .env directories are ignored.
	tmpDir, err := os.MkdirTemp("", "test_env_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer func() { _ = os.RemoveAll(tmpDir) }()

	// Create env directory
	envDir := filepath.Join(tmpDir, "env")
	if err := os.MkdirAll(envDir, 0755); err != nil {
		t.Fatalf("Failed to create env dir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(envDir, "env_file.py"), []byte("import os"), 0644); err != nil {
		t.Fatalf("Failed to create env/env_file.py: %v", err)
	}

	// Create .env directory
	dotEnvDir := filepath.Join(tmpDir, ".env")
	if err := os.MkdirAll(dotEnvDir, 0755); err != nil {
		t.Fatalf("Failed to create .env dir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dotEnvDir, "dotenv_file.py"), []byte("import os"), 0644); err != nil {
		t.Fatalf("Failed to create .env/dotenv_file.py: %v", err)
	}

	files, err := FindPythonFiles(tmpDir)
	if err != nil {
		t.Fatalf("FindPythonFiles failed: %v", err)
	}

	// Both directories should be ignored
	for _, f := range files {
		base := filepath.Base(f)
		if base == "env_file.py" || base == "dotenv_file.py" {
			t.Errorf("File %s should have been ignored", f)
		}
	}
}

func TestCollectPythonFilesResolvesSelectors(t *testing.T) {
	// Backend-relative selectors resolve via the backend fallback, and a
	// selector that resolves to nothing is an error.
	backendDir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(backendDir, "pkg"), 0755); err != nil {
		t.Fatalf("Failed to create pkg dir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(backendDir, "pkg", "a.py"), []byte("import os"), 0644); err != nil {
		t.Fatalf("Failed to create pkg/a.py: %v", err)
	}

	files, err := collectPythonFiles([]string{"pkg"}, backendDir)
	if err != nil {
		t.Fatalf("collectPythonFiles failed: %v", err)
	}
	if len(files) != 1 || files[0] != filepath.Join(backendDir, "pkg", "a.py") {
		t.Fatalf("Expected only pkg/a.py, got %v", files)
	}

	if _, err := collectPythonFiles([]string{"nonexistent"}, backendDir); err == nil {
		t.Fatalf("Expected an error for a selector that matches nothing")
	}
}
