package paths

import (
	"os"
	"path/filepath"
	"testing"
)

// isolate points HOME/XDG at temp dirs and runs the test from a fresh cwd so
// legacy ./onyx_data detection is hermetic.
func isolate(t *testing.T) (cwd, xdg string) {
	t.Helper()
	cwd = t.TempDir()
	xdg = t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", xdg)
	t.Setenv("ONYX_DEPLOYMENT_DIR", "")
	t.Setenv("INSTALL_PREFIX", "")
	orig, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	if err := os.Chdir(cwd); err != nil {
		t.Fatalf("chdir: %v", err)
	}
	t.Cleanup(func() {
		if err := os.Chdir(orig); err != nil {
			t.Fatalf("restore cwd: %v", err)
		}
	})
	return cwd, xdg
}

func markInstall(t *testing.T, root string) {
	t.Helper()
	dir := filepath.Join(root, "deployment")
	if err := os.MkdirAll(dir, 0755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "docker-compose.yml"), []byte("name: onyx\n"), 0644); err != nil {
		t.Fatalf("write marker: %v", err)
	}
}

func TestResolveFlagWinsOverEverything(t *testing.T) {
	isolate(t)
	t.Setenv("ONYX_DEPLOYMENT_DIR", "/elsewhere")
	got := Resolve("/explicit")
	if got.Dir != "/explicit" || got.Source != SourceFlag {
		t.Fatalf("got %+v", got)
	}
}

func TestResolveEnvPrecedence(t *testing.T) {
	isolate(t)
	t.Setenv("ONYX_DEPLOYMENT_DIR", "/deployment-dir")
	t.Setenv("INSTALL_PREFIX", "/install-prefix")
	got := Resolve("")
	if got.Dir != "/deployment-dir" || got.Source != SourceEnvDeploymentDir {
		t.Fatalf("got %+v", got)
	}

	t.Setenv("ONYX_DEPLOYMENT_DIR", "")
	got = Resolve("")
	if got.Dir != "/install-prefix" || got.Source != SourceEnvInstallPrefix {
		t.Fatalf("got %+v", got)
	}
}

func TestResolveDefaultsToXDGDir(t *testing.T) {
	_, xdg := isolate(t)
	got := Resolve("")
	want := filepath.Join(xdg, "onyx")
	if got.Dir != want || got.Source != SourceDefault {
		t.Fatalf("got %+v, want dir %s", got, want)
	}
	if len(got.Ambiguous) != 0 {
		t.Fatalf("unexpected ambiguity: %+v", got)
	}
}

func TestResolvePrefersLegacyInstallInCwd(t *testing.T) {
	cwd, _ := isolate(t)
	markInstall(t, filepath.Join(cwd, "onyx_data"))
	got := Resolve("")
	if got.Dir != "onyx_data" || got.Source != SourceLegacyCwd {
		t.Fatalf("got %+v", got)
	}
	if len(got.Ambiguous) != 0 {
		t.Fatalf("unexpected ambiguity: %+v", got)
	}
}

func TestResolveFlagsAmbiguityWhenBothExist(t *testing.T) {
	cwd, xdg := isolate(t)
	markInstall(t, filepath.Join(cwd, "onyx_data"))
	markInstall(t, filepath.Join(xdg, "onyx"))
	got := Resolve("")
	if got.Source != SourceLegacyCwd {
		t.Fatalf("got %+v", got)
	}
	if len(got.Ambiguous) != 1 || got.Ambiguous[0] != filepath.Join(xdg, "onyx") {
		t.Fatalf("ambiguity not reported: %+v", got)
	}
}

func TestResolveIgnoresNonInstallLegacyDir(t *testing.T) {
	cwd, xdg := isolate(t)
	// A directory named onyx_data without install markers is not adopted.
	if err := os.MkdirAll(filepath.Join(cwd, "onyx_data"), 0755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	got := Resolve("")
	if got.Source != SourceDefault || got.Dir != filepath.Join(xdg, "onyx") {
		t.Fatalf("got %+v", got)
	}
}

func TestIsInstallEnvMarker(t *testing.T) {
	root := t.TempDir()
	if IsInstall(root) {
		t.Fatal("empty dir should not be an install")
	}
	dir := filepath.Join(root, "deployment")
	if err := os.MkdirAll(dir, 0755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, ".env"), []byte("IMAGE_TAG=latest\n"), 0644); err != nil {
		t.Fatalf("write: %v", err)
	}
	if !IsInstall(root) {
		t.Fatal(".env marker should count as an install")
	}
}

// Install markers say a directory holds a deployment; they say nothing about
// what else it holds. Since uninstall removes the root recursively, roots
// whose contents can't be written off wholesale are refused separately.
func TestCheckDeletableRefusesBroadRoots(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home) // os.UserHomeDir on Windows

	for _, dir := range []string{
		string(os.PathSeparator),
		home,
		filepath.Dir(home), // contains the home directory
		filepath.Join(string(os.PathSeparator), "usr"),
	} {
		if err := CheckDeletable(dir); err == nil {
			t.Errorf("CheckDeletable(%q) allowed a recursive delete", dir)
		}
	}

	for _, dir := range []string{
		filepath.Join(home, ".config", "onyx"),
		filepath.Join(home, "onyx_data"),
		t.TempDir(),
	} {
		if err := CheckDeletable(dir); err != nil {
			t.Errorf("CheckDeletable(%q) = %v, want a deployment directory to be deletable", dir, err)
		}
	}
}
