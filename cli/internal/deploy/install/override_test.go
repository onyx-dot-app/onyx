package install

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/deployfiles"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/paths"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/state"
)

const overrideBody = "services:\n  nginx:\n    ports: !override []\n"

// writeOverride drops a user-owned override, under the given name, into the
// deployment directory.
func writeOverride(t *testing.T, root, name string) string {
	t.Helper()
	dir := filepath.Join(root, "deployment")
	if err := os.MkdirAll(dir, 0755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte(overrideBody), 0644); err != nil {
		t.Fatal(err)
	}
	return path
}

// composeArgv returns the argv of the last compose call ending in suffix.
func composeArgv(t *testing.T, runner *fakeRunner, suffix string) string {
	t.Helper()
	var found string
	for _, c := range runner.calls {
		if a := argv(c); strings.Contains(a, suffix) {
			found = a
		}
	}
	if found == "" {
		t.Fatalf("no compose call containing %q", suffix)
	}
	return found
}

// assertOverrideUntouched checks the CLI left the user's file exactly as it
// found it: same bytes, no backup, and nothing recorded in the manifest.
func assertOverrideUntouched(t *testing.T, root, path string) {
	t.Helper()
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("override gone: %v", err)
	}
	if string(got) != overrideBody {
		t.Errorf("override rewritten:\n%s", got)
	}
	backups, err := filepath.Glob(path + ".bak-*")
	if err != nil {
		t.Fatal(err)
	}
	if len(backups) > 0 {
		t.Errorf("override backed up: %v", backups)
	}
	m, err := state.Load(root)
	if err != nil || m == nil {
		t.Fatalf("manifest: %v, %v", m, err)
	}
	if _, ok := m.Files["deployment/"+filepath.Base(path)]; ok {
		t.Errorf("override recorded as managed: %v", m.Files)
	}
}

// An override present at install time is stacked after every managed file, so
// its edits win the merge, and the checksum/backup system never sees it.
func TestInstallStacksComposeOverrideLast(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	runner := &fakeRunner{handler: healthyDockerHandler}
	deps := testDeps(t, runner, notFoundServer(t))
	root := t.TempDir()
	path := writeOverride(t, root, "docker-compose.override.yml")

	err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, // non-interactive default mode is Lite
		Dev:      true,
		Tag:      "v4.2.0",
		Dir:      root,
		NoWait:   true,
	})
	if err != nil {
		t.Fatalf("RunInstall: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	up := composeArgv(t, runner, "up -d")
	base := strings.Index(up, "-f docker-compose.yml")
	lite := strings.Index(up, "-f docker-compose.onyx-lite.yml")
	dev := strings.Index(up, "-f docker-compose.dev.yml")
	override := strings.Index(up, "-f docker-compose.override.yml")
	if base < 0 || lite < 0 || dev < 0 || override < 0 {
		t.Fatalf("up argv missing a compose file: %s", up)
	}
	if override < base || override < lite || override < dev {
		t.Errorf("override must come last in the -f list: %s", up)
	}

	assertOverrideUntouched(t, root, path)
	if !strings.Contains(outBuf(deps).String(), "docker-compose.override.yml") {
		t.Errorf("override pickup not announced:\n%s", outBuf(deps).String())
	}
}

// An override dropped in after the install is picked up by the lifecycle
// verbs and survives an upgrade, which refreshes every managed file.
func TestComposeOverrideAutoDetectedAndSurvivesUpgrade(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")
	path := writeOverride(t, root, "docker-compose.override.yml")

	upgradeRunner := &fakeRunner{handler: healthyDockerHandler}
	upgradeDeps := testDeps(t, upgradeRunner, rawServer(t, "# compose at v4.2.0\nname: onyx\n"))
	if err := RunUpgrade(context.Background(), upgradeDeps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	}); err != nil {
		t.Fatalf("RunUpgrade: %v\noutput:\n%s", err, outBuf(upgradeDeps).String())
	}
	if up := composeArgv(t, upgradeRunner, "up -d"); !strings.Contains(up, "-f docker-compose.override.yml") {
		t.Errorf("upgrade dropped the override: %s", up)
	}
	assertOverrideUntouched(t, root, path)

	stopRunner := &fakeRunner{handler: healthyDockerHandler}
	stopDeps := testDeps(t, stopRunner, notFoundServer(t))
	if err := RunStop(context.Background(), stopDeps, Options{Dir: root}); err != nil {
		t.Fatalf("RunStop: %v\noutput:\n%s", err, outBuf(stopDeps).String())
	}
	if stop := composeArgv(t, stopRunner, " stop"); !strings.Contains(stop, "-f docker-compose.override.yml") {
		t.Errorf("override not auto-detected by stop: %s", stop)
	}

	logsRunner := &fakeRunner{handler: healthyDockerHandler}
	logsDeps := testDeps(t, logsRunner, notFoundServer(t))
	if err := RunLogs(context.Background(), logsDeps, Options{Dir: root}, LogOptions{Tail: "200"}); err != nil {
		t.Fatalf("RunLogs: %v\noutput:\n%s", err, outBuf(logsDeps).String())
	}
	if logs := composeArgv(t, logsRunner, " logs"); !strings.Contains(logs, "-f docker-compose.override.yml") {
		t.Errorf("override not auto-detected by logs: %s", logs)
	}
}

// The override is selected by its presence on disk alone, in every mode and
// whether or not the caller asked for overlay auto-detection.
func TestComposeFileNamesOverride(t *testing.T) {
	for _, tc := range []struct {
		name string
		mode func(*installer)
		want []string
	}{
		{
			name: "standard",
			mode: func(in *installer) {},
			want: []string{"docker-compose.yml", "docker-compose.override.yml"},
		},
		{
			name: "lite with craft",
			mode: func(in *installer) { in.lite, in.craft = true, true },
			want: []string{
				"docker-compose.yml",
				"docker-compose.onyx-lite.yml",
				"docker-compose.craft.yml",
				"docker-compose.override.yml",
			},
		},
		{
			name: "prod",
			mode: func(in *installer) { in.prod = true },
			want: []string{"docker-compose.prod.yml", "docker-compose.override.yml"},
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			root := t.TempDir()
			writeOverride(t, root, "docker-compose.override.yml")
			for _, autoDetect := range []bool{false, true} {
				in := newInstaller(testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t)), Options{Dir: root})
				in.root = paths.InstallRoot{Dir: root}
				tc.mode(in)
				got := in.composeFileNames(autoDetect)
				if strings.Join(got, " ") != strings.Join(tc.want, " ") {
					t.Errorf("composeFileNames(%t) = %v, want %v", autoDetect, got, tc.want)
				}
			}
		})
	}
}

// Without an override on disk the -f list is unchanged.
func TestComposeFileNamesWithoutOverride(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "deployment"), 0755); err != nil {
		t.Fatal(err)
	}
	in := newInstaller(testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t)), Options{Dir: root})
	in.root = paths.InstallRoot{Dir: root}
	got := in.composeFileNames(true)
	if len(got) != 1 || got[0] != "docker-compose.yml" {
		t.Errorf("composeFileNames = %v, want just the base file", got)
	}
}

// composeOverrideName recognizes every filename Docker Compose's own
// auto-discovery does, not just docker-compose.override.yml.
func TestComposeOverrideNameVariants(t *testing.T) {
	for _, name := range deployfiles.OverrideNames {
		t.Run(name, func(t *testing.T) {
			root := t.TempDir()
			writeOverride(t, root, name)
			in := newInstaller(testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t)), Options{Dir: root})
			in.root = paths.InstallRoot{Dir: root}
			if got := in.composeOverrideName(); got != name {
				t.Errorf("composeOverrideName() = %q, want %q", got, name)
			}
		})
	}
}

// When more than one override filename is present, the one earliest in
// deployfiles.OverrideNames wins — matching real Compose, which resolves to a
// single implicit override file, not all of them at once.
func TestComposeOverridePrecedence(t *testing.T) {
	root := t.TempDir()
	for _, name := range []string{"docker-compose.override.yaml", "docker-compose.override.yml", "compose.override.yml"} {
		writeOverride(t, root, name)
	}
	in := newInstaller(testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t)), Options{Dir: root})
	in.root = paths.InstallRoot{Dir: root}
	const want = "compose.override.yml"
	if got := in.composeOverrideName(); got != want {
		t.Errorf("composeOverrideName() = %q, want the highest-precedence name %q", got, want)
	}
}
