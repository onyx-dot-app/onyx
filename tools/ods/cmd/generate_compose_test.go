package cmd

import (
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/composegen"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/deployfilessync"
)

const composeTemplate = `services:
  api_server:
    #!value prod,no-letsencrypt: image: onyx:prod
    image: onyx:dev
`

// composeGenerateRepo creates a repo with the compose template and every
// non-generated file that onyx-cli embeds, and returns the repo root and the
// generated variants keyed by filename.
func composeGenerateRepo(t *testing.T) (string, map[string]string) {
	t.Helper()
	root := composeRepo(t)
	dir := filepath.Join(root, "deployment", "docker_compose")
	if err := os.WriteFile(filepath.Join(dir, composegen.TemplateName), []byte(composeTemplate), 0o644); err != nil {
		t.Fatal(err)
	}
	generated, err := composegen.GenerateAll(strings.Split(strings.TrimSuffix(composeTemplate, "\n"), "\n"))
	if err != nil {
		t.Fatal(err)
	}
	for _, rel := range deployfilessync.RelPaths {
		if _, ok := generated[filepath.Base(rel)]; ok && filepath.Dir(rel) == "docker_compose" {
			continue
		}
		writeFile(t, filepath.Join(root, "deployment", filepath.FromSlash(rel)), rel+"\n")
	}
	return root, generated
}

func TestRunGenerateCompose_writeThenCheckIsClean(t *testing.T) {
	root, generated := composeGenerateRepo(t)
	dir := filepath.Join(root, "deployment", "docker_compose")
	embedded := deployfilessync.DestDir(root)

	var stale bool
	var err error
	composeCapture(t, &os.Stdout, func() {
		stale, err = runGenerateCompose(true)
	})
	if err != nil || stale {
		t.Fatalf("write:expected no error and not stale, got %v, %v", stale, err)
	}
	for _, variant := range composegen.Variants {
		if got := composeReadFile(t, filepath.Join(dir, variant.Filename)); got != generated[variant.Filename] {
			t.Fatalf("%s: expected %q, got %q", variant.Filename, generated[variant.Filename], got)
		}
	}
	if got := composeReadFile(t, filepath.Join(embedded, "docker_compose", "docker-compose.prod.yml")); got != generated["docker-compose.prod.yml"] {
		t.Fatalf("expected the embedded prod compose file to match the rendered output, got %q", got)
	}
	if got := composeReadFile(t, filepath.Join(embedded, "data", "nginx", "run-nginx.sh")); got != "data/nginx/run-nginx.sh\n" {
		t.Fatalf("expected the embedded nginx script to match its source, got %q", got)
	}

	stderr := composeCapture(t, &os.Stderr, func() {
		stale, err = runGenerateCompose(false)
	})
	if err != nil || stale {
		t.Fatalf("check: expected no error and not stale, got %v, %v", stale, err)
	}
	if stderr != "" {
		t.Fatalf("expected no diff output, got %q", stderr)
	}
}

func TestRunGenerateCompose_checkReportsStaleFilesWithoutWriting(t *testing.T) {
	root, _ := composeGenerateRepo(t)
	composeCapture(t, &os.Stdout, func() {
		if _, err := runGenerateCompose(true); err != nil {
			t.Fatal(err)
		}
	})
	prodPath := filepath.Join(root, "deployment", "docker_compose", "docker-compose.prod.yml")
	if err := os.WriteFile(prodPath, []byte("stale: true\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	sourcePath := filepath.Join(root, "deployment", "docker_compose", "env.template")
	if err := os.WriteFile(sourcePath, []byte("NEW=1\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	var stale bool
	var err error
	stderr := composeCapture(t, &os.Stderr, func() {
		stale, err = runGenerateCompose(false)
	})

	if err != nil || !stale {
		t.Fatalf("expected stale without error, got %v, %v", stale, err)
	}
	for _, want := range []string{
		"--- docker-compose.prod.yml\n+++ docker-compose.prod.yml (from docker-compose.template.yml)\n-stale: true\n",
		"+    image: onyx:prod\n",
		"--- embedded/docker_compose/env.template\n+++ embedded/docker_compose/env.template (from deployment/docker_compose/env.template)\n-docker_compose/env.template\n+NEW=1\n",
		"docker-compose.prod.yml is stale (re-run with --write).\nembedded copy of docker_compose/env.template is stale (re-run with --write).\n",
	} {
		if !strings.Contains(stderr, want) {
			t.Fatalf("expected stderr to contain %q, got %q", want, stderr)
		}
	}
	if got := composeReadFile(t, prodPath); got != "stale: true\n" {
		t.Fatalf("check mode must not rewrite files, got %q", got)
	}
	embeddedCopy := filepath.Join(deployfilessync.DestDir(root), "docker_compose", "env.template")
	if got := composeReadFile(t, embeddedCopy); got != "docker_compose/env.template\n" {
		t.Fatalf("check mode must not sync embedded copies, got %q", got)
	}
}

func TestRunGenerateCompose_writeReportsWhatChanged(t *testing.T) {
	composeGenerateRepo(t)

	var stale bool
	var err error
	stdout := composeCapture(t, &os.Stdout, func() {
		stale, err = runGenerateCompose(true)
	})

	if err != nil || stale {
		t.Fatalf("expected no error and not stale, got %v, %v", stale, err)
	}
	lines := strings.Split(strings.TrimSuffix(stdout, "\n"), "\n")
	want := []string{
		"regenerated docker-compose.yml",
		"regenerated docker-compose.prod.yml",
		"regenerated docker-compose.prod-no-letsencrypt.yml",
	}
	for _, rel := range deployfilessync.RelPaths {
		want = append(want, "synced embedded copy of "+rel)
	}
	if !slices.Equal(lines, want) {
		t.Fatalf("expected %q, got %q", want, lines)
	}
}

func TestRunGenerateCompose_errors(t *testing.T) {
	tests := []struct {
		name       string
		setup      func(t *testing.T)
		wantPrefix string
	}{
		{
			name:       "outside a git repo",
			setup:      composeNoRepo,
			wantPrefix: "Failed to find git root: ",
		},
		{
			name:       "missing template",
			setup:      func(t *testing.T) { composeRepo(t) },
			wantPrefix: "Failed to read template: ",
		},
		{
			name: "invalid template",
			setup: func(t *testing.T) {
				root, _ := composeGenerateRepo(t)
				writeFile(t, filepath.Join(root, "deployment", "docker_compose", composegen.TemplateName), "#!bogus\n")
			},
			wantPrefix: "docker-compose.template.yml:1: unknown template directive: #!bogus",
		},
		{
			name: "unreadable generated file",
			setup: func(t *testing.T) {
				root, _ := composeGenerateRepo(t)
				if err := os.Mkdir(filepath.Join(root, "deployment", "docker_compose", "docker-compose.yml"), 0o755); err != nil {
					t.Fatal(err)
				}
			},
			wantPrefix: "Failed to read docker-compose.yml: ",
		},
		{
			name: "missing embedded source",
			setup: func(t *testing.T) {
				root, _ := composeGenerateRepo(t)
				composeCapture(t, &os.Stdout, func() {
					if _, err := runGenerateCompose(true); err != nil {
						t.Fatal(err)
					}
				})
				if err := os.Remove(filepath.Join(root, "deployment", "data", "nginx", "run-nginx.sh")); err != nil {
					t.Fatal(err)
				}
			},
			wantPrefix: "failed to read source data/nginx/run-nginx.sh: ",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tt.setup(t)
			for _, write := range []bool{false, true} {
				var err error
				composeCapture(t, &os.Stderr, func() {
					composeCapture(t, &os.Stdout, func() {
						_, err = runGenerateCompose(write)
					})
				})
				if err == nil || !strings.HasPrefix(err.Error(), tt.wantPrefix) {
					t.Fatalf("write=%v: expected error starting with %q, got %v", write, tt.wantPrefix, err)
				}
			}
		})
	}
}

func TestLineDiff(t *testing.T) {
	got := lineDiff("docker-compose.yml", "docker-compose.template.yml", "a\nb\nc\n", "a\nB\nc\nd\n")
	want := "--- docker-compose.yml\n+++ docker-compose.yml (from docker-compose.template.yml)\n-b\n+B\n+d\n"
	if got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}
