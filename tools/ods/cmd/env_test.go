package cmd

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSetEnvValues_createsFileWhenMissing(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")

	err := setEnvValues(envPath, map[string]string{
		"FOO": "bar",
		"BAZ": "qux",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	data, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatalf("failed to read file: %v", err)
	}

	content := string(data)
	if !strings.Contains(content, "FOO=bar") {
		t.Errorf("expected FOO=bar in output, got:\n%s", content)
	}
	if !strings.Contains(content, "BAZ=qux") {
		t.Errorf("expected BAZ=qux in output, got:\n%s", content)
	}
}

func TestSetEnvValues_upsertsExistingKeys(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")

	initial := "FOO=old\nOTHER=keep\n"
	if err := os.WriteFile(envPath, []byte(initial), 0644); err != nil {
		t.Fatalf("failed to write initial file: %v", err)
	}

	err := setEnvValues(envPath, map[string]string{
		"FOO": "new",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	data, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatalf("failed to read file: %v", err)
	}

	content := string(data)
	if !strings.Contains(content, "FOO=new") {
		t.Errorf("expected FOO=new, got:\n%s", content)
	}
	if strings.Contains(content, "FOO=old") {
		t.Errorf("old value FOO=old should be replaced, got:\n%s", content)
	}
	if !strings.Contains(content, "OTHER=keep") {
		t.Errorf("OTHER=keep should be preserved, got:\n%s", content)
	}
}

func TestSetEnvValues_appendsNewKeys(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")

	initial := "EXISTING=value\n"
	if err := os.WriteFile(envPath, []byte(initial), 0644); err != nil {
		t.Fatalf("failed to write initial file: %v", err)
	}

	err := setEnvValues(envPath, map[string]string{
		"NEW_KEY": "new_value",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	data, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatalf("failed to read file: %v", err)
	}

	content := string(data)
	if !strings.Contains(content, "EXISTING=value") {
		t.Errorf("EXISTING=value should be preserved, got:\n%s", content)
	}
	if !strings.Contains(content, "NEW_KEY=new_value") {
		t.Errorf("expected NEW_KEY=new_value appended, got:\n%s", content)
	}
}

func TestSetEnvValues_doesNotDuplicateOnRepeatedCalls(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")

	values := map[string]string{
		"PORT": "5432",
	}

	for i := 0; i < 5; i++ {
		if err := setEnvValues(envPath, values); err != nil {
			t.Fatalf("call %d: unexpected error: %v", i, err)
		}
	}

	data, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatalf("failed to read file: %v", err)
	}

	count := strings.Count(string(data), "PORT=5432")
	if count != 1 {
		t.Errorf("expected exactly 1 occurrence of PORT=5432 after 5 calls, got %d:\n%s", count, string(data))
	}
}

func TestSetEnvValues_doesNotMatchCommentedOutKeys(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")

	initial := "# FOO=old_commented\nBAR=keep\n"
	if err := os.WriteFile(envPath, []byte(initial), 0644); err != nil {
		t.Fatalf("failed to write initial file: %v", err)
	}

	err := setEnvValues(envPath, map[string]string{
		"FOO": "new",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	data, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatalf("failed to read file: %v", err)
	}

	content := string(data)
	if !strings.Contains(content, "# FOO=old_commented") {
		t.Errorf("comment line should be preserved, got:\n%s", content)
	}
	if !strings.Contains(content, "FOO=new") {
		t.Errorf("expected FOO=new appended, got:\n%s", content)
	}
}

func TestSetEnvValues_overwritesWithNewValue(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")

	if err := setEnvValues(envPath, map[string]string{"PORT": "5432"}); err != nil {
		t.Fatalf("first call: %v", err)
	}
	if err := setEnvValues(envPath, map[string]string{"PORT": "15432"}); err != nil {
		t.Fatalf("second call: %v", err)
	}

	data, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatalf("failed to read file: %v", err)
	}

	content := string(data)
	if strings.Contains(content, "PORT=5432") {
		t.Errorf("old value PORT=5432 should be gone, got:\n%s", content)
	}
	if !strings.Contains(content, "PORT=15432") {
		t.Errorf("expected PORT=15432, got:\n%s", content)
	}
	if strings.Count(content, "PORT=") != 1 {
		t.Errorf("expected exactly 1 PORT= line, got:\n%s", content)
	}
}
