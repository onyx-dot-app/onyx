package lazyimports

import (
	"bufio"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// LazyImportSettings defines settings for which files to ignore when checking for lazy imports.
type LazyImportSettings struct {
	IgnoreFiles map[string]struct{}
}

// NewLazyImportSettings creates a new LazyImportSettings with optional ignore files.
func NewLazyImportSettings(ignoreFiles ...string) LazyImportSettings {
	settings := LazyImportSettings{
		IgnoreFiles: make(map[string]struct{}),
	}
	for _, f := range ignoreFiles {
		settings.IgnoreFiles[f] = struct{}{}
	}
	return settings
}

// Common ignore directories (virtual envs, caches)
var ignoreDirectories = map[string]struct{}{
	".venv":       {},
	"venv":        {},
	".env":        {},
	"env":         {},
	"__pycache__": {},
}

// modulePatterns holds pre-compiled regex patterns for a module.
type modulePatterns struct {
	moduleName string
	// Pattern 1: import module
	importPattern *regexp.Regexp
	// Pattern 2: from module import ...
	fromPattern *regexp.Regexp
	// Pattern 3: from ... import module
	fromImportPattern *regexp.Regexp
}

// compileModulePatterns pre-compiles regex patterns for a module.
func compileModulePatterns(module string) modulePatterns {
	escaped := regexp.QuoteMeta(module)
	return modulePatterns{
		moduleName:        module,
		importPattern:     regexp.MustCompile(`^import\s+` + escaped + `(\s|$|\.)`),
		fromPattern:       regexp.MustCompile(`^from\s+` + escaped + `(\s|\.|$)`),
		fromImportPattern: regexp.MustCompile(`^from\s+[\w.]+\s+import\s+.*\b` + escaped + `\b`),
	}
}

// DefaultLazyImportModules returns the default map of modules that should be lazily imported.
func DefaultLazyImportModules() map[string]LazyImportSettings {
	return map[string]LazyImportSettings{
		"google.genai":               NewLazyImportSettings(),
		"openai":                     NewLazyImportSettings(),
		"markitdown":                 NewLazyImportSettings(),
		"tiktoken":                   NewLazyImportSettings(),
		"transformers":               NewLazyImportSettings("model_server/main.py"),
		"setfit":                     NewLazyImportSettings(),
		"unstructured":               NewLazyImportSettings(),
		"onyx.llm.litellm_singleton": NewLazyImportSettings(),
		"litellm": NewLazyImportSettings(
			"onyx/llm/litellm_singleton/__init__.py",
			"onyx/llm/litellm_singleton/config.py",
			"onyx/llm/litellm_singleton/monkey_patches.py",
		),
		"nltk":                 NewLazyImportSettings(),
		"trafilatura":         NewLazyImportSettings(),
		"pypdf":               NewLazyImportSettings(),
		"unstructured_client": NewLazyImportSettings(),
	}
}

// ViolationLine represents a single line that contains a violation.
type ViolationLine struct {
	LineNum int
	Content string
}

// EagerImportResult holds the result of checking a file for eager imports.
type EagerImportResult struct {
	ViolationLines  []ViolationLine
	ViolatedModules map[string]struct{}
}

// FileViolation represents violations found in a specific file.
type FileViolation struct {
	RelPath         string
	ViolationLines  []ViolationLine
	ViolatedModules map[string]struct{}
}

// findEagerImports finds eager imports of protected modules in a given file.
func findEagerImports(filePath string, patterns []modulePatterns) EagerImportResult {
	result := EagerImportResult{
		ViolationLines:  []ViolationLine{},
		ViolatedModules: make(map[string]struct{}),
	}

	file, err := os.Open(filePath)
	if err != nil {
		log.Errorf("Error reading %s: %v", filePath, err)
		return result
	}
	defer func() {
		if err := file.Close(); err != nil {
			log.Debugf("Error closing %s: %v", filePath, err)
		}
	}()

	scanner := bufio.NewScanner(file)
	lineNum := 0

	for scanner.Scan() {
		lineNum++
		line := scanner.Text()
		stripped := strings.TrimSpace(line)

		// Skip comments and empty lines
		if stripped == "" || strings.HasPrefix(stripped, "#") {
			continue
		}

		// Only check imports at module level (indentation == 0)
		currentIndent := len(line) - len(strings.TrimLeft(line, " \t"))
		if currentIndent != 0 {
			continue
		}

		// Quick check: skip lines that don't start with import or from
		if !strings.HasPrefix(stripped, "import ") && !strings.HasPrefix(stripped, "from ") {
			continue
		}

		// Check for eager imports of protected modules using pre-compiled patterns
		for _, mp := range patterns {
			if mp.importPattern.MatchString(stripped) ||
				mp.fromPattern.MatchString(stripped) ||
				mp.fromImportPattern.MatchString(stripped) {
				result.ViolationLines = append(result.ViolationLines, ViolationLine{
					LineNum: lineNum,
					Content: line,
				})
				result.ViolatedModules[mp.moduleName] = struct{}{}
			}
		}
	}

	if err := scanner.Err(); err != nil {
		log.Errorf("Error scanning %s: %v", filePath, err)
	}

	return result
}

// isValidPythonFile applies shared filtering rules.
func isValidPythonFile(filePath string) bool {
	if !strings.HasSuffix(filePath, ".py") {
		return false
	}

	parts := strings.Split(filePath, string(os.PathSeparator))

	// Exclude tests
	for _, part := range parts {
		if part == "tests" {
			return false
		}
	}

	baseName := filepath.Base(filePath)
	if strings.HasPrefix(baseName, "test_") || strings.HasSuffix(baseName, "_test.py") {
		return false
	}

	// Exclude ignored directories
	for _, part := range parts {
		if _, ignored := ignoreDirectories[part]; ignored {
			return false
		}
	}

	return true
}

// collectPythonFiles collects Python files from a list of start points.
func collectPythonFiles(startPoints []string, backendDir string) ([]string, error) {
	var collected []string
	backendReal, err := filepath.Abs(backendDir)
	if err != nil {
		return nil, err
	}

	for _, p := range startPoints {
		absPath, err := filepath.Abs(p)
		if err != nil {
			log.Debugf("Skipping path that cannot be resolved: %s", p)
			continue
		}

		// Check if path is within backend directory
		relPath, err := filepath.Rel(backendReal, absPath)
		if err != nil || strings.HasPrefix(relPath, "..") {
			log.Debugf("Skipping path outside backend directory: %s", p)
			continue
		}

		info, err := os.Stat(absPath)
		if err != nil {
			log.Debugf("Skipping non-existent path: %s", p)
			continue
		}

		if info.IsDir() {
			err := filepath.Walk(absPath, func(path string, info os.FileInfo, err error) error {
				if err != nil {
					return nil // Skip files with errors
				}
				if !info.IsDir() && isValidPythonFile(path) {
					collected = append(collected, path)
				}
				return nil
			})
			if err != nil {
				log.Debugf("Error walking directory %s: %v", absPath, err)
			}
		} else {
			if isValidPythonFile(absPath) {
				collected = append(collected, absPath)
			}
		}
	}

	return collected, nil
}

// FindPythonFiles finds all Python files in the backend directory.
func FindPythonFiles(backendDir string) ([]string, error) {
	return collectPythonFiles([]string{backendDir}, backendDir)
}

// shouldCheckFileForModule checks if a file should be checked for a specific module's imports.
func shouldCheckFileForModule(filePath, backendDir string, settings LazyImportSettings) bool {
	if len(settings.IgnoreFiles) == 0 {
		return true
	}

	relPath, err := filepath.Rel(backendDir, filePath)
	if err != nil {
		return true
	}

	// Normalize to forward slashes for comparison
	relPathNorm := filepath.ToSlash(relPath)

	_, ignored := settings.IgnoreFiles[relPathNorm]
	return !ignored
}

// CheckLazyImports checks that specified modules are only lazily imported.
// Returns a list of file violations and a set of all violated modules.
func CheckLazyImports(modulesToLazyImport map[string]LazyImportSettings, providedPaths []string) ([]FileViolation, map[string]struct{}, error) {
	backendDir, err := paths.BackendDir()
	if err != nil {
		return nil, nil, err
	}

	log.Infof("Checking for direct imports of lazy modules: %s", formatModuleList(modulesToLazyImport))

	// Pre-compile all regex patterns once
	allPatterns := make(map[string]modulePatterns, len(modulesToLazyImport))
	for moduleName := range modulesToLazyImport {
		allPatterns[moduleName] = compileModulePatterns(moduleName)
	}

	// Determine Python files to check
	var targetFiles []string
	if len(providedPaths) > 0 {
		targetFiles, err = collectPythonFiles(providedPaths, backendDir)
		if err != nil {
			return nil, nil, err
		}
		if len(targetFiles) == 0 {
			log.Info("No matching Python files to check based on provided paths.")
			return nil, nil, nil
		}
	} else {
		targetFiles, err = FindPythonFiles(backendDir)
		if err != nil {
			return nil, nil, err
		}
	}

	var violations []FileViolation
	allViolatedModules := make(map[string]struct{})

	// Check each Python file for each module with its specific ignore settings
	for _, filePath := range targetFiles {
		// Determine which modules should be checked for this file
		var patternsToCheck []modulePatterns
		for moduleName, settings := range modulesToLazyImport {
			if shouldCheckFileForModule(filePath, backendDir, settings) {
				patternsToCheck = append(patternsToCheck, allPatterns[moduleName])
			}
		}

		if len(patternsToCheck) == 0 {
			continue
		}

		result := findEagerImports(filePath, patternsToCheck)

		if len(result.ViolationLines) > 0 {
			relPath, err := filepath.Rel(backendDir, filePath)
			if err != nil {
				relPath = filePath
			}

			violations = append(violations, FileViolation{
				RelPath:         relPath,
				ViolationLines:  result.ViolationLines,
				ViolatedModules: result.ViolatedModules,
			})

			for mod := range result.ViolatedModules {
				allViolatedModules[mod] = struct{}{}
			}
		}
	}

	return violations, allViolatedModules, nil
}

// formatModuleList formats the module names for display.
func formatModuleList(modules map[string]LazyImportSettings) string {
	names := make([]string, 0, len(modules))
	for name := range modules {
		names = append(names, name)
	}
	return strings.Join(names, ", ")
}

// FormatViolatedModules formats a set of violated modules as a sorted string.
func FormatViolatedModules(modules map[string]struct{}) string {
	names := make([]string, 0, len(modules))
	for name := range modules {
		names = append(names, name)
	}
	return strings.Join(names, ", ")
}

