package auditcmd

import (
	"bytes"
	"errors"
	"path/filepath"
	"strings"
	"testing"

	"github.com/google/go-containerregistry/pkg/crane"
	"github.com/google/go-containerregistry/pkg/name"
	"github.com/google/go-containerregistry/pkg/v1/empty"
	"github.com/google/go-containerregistry/pkg/v1/mutate"
	"github.com/google/go-containerregistry/pkg/v1/tarball"
)

const criticalAlert = `[{
  "state": "open",
  "dependency": {"package": {"ecosystem": "pip", "name": "requests"}, "manifest_path": "pyproject.toml"},
  "security_advisory": {"ghsa_id": "GHSA-aaaa-bbbb-cccc", "summary": "Requests SSRF", "severity": "critical"},
  "security_vulnerability": {"severity": "critical"}
}]`

// requireCommandError asserts err is a commandError logged as want.
func requireCommandError(t *testing.T, err error, want string) {
	t.Helper()
	var cmdErr *commandError
	if !errors.As(err, &cmdErr) {
		t.Fatalf("expected a command error %q, got %T: %v", want, err, err)
	}
	if !strings.HasPrefix(cmdErr.Error(), want) {
		t.Fatalf("expected the message to start with %q, got %q", want, cmdErr.Error())
	}
}

func TestRunAudit_exitDecision(t *testing.T) {
	cases := []struct {
		name      string
		failOn    string
		allowlist string
		wantErr   string // empty means the audit passes
	}{
		{
			name:      "critical finding blocks",
			failOn:    "critical",
			allowlist: `{"ignores":[]}`,
			wantErr:   "1 finding(s) at or above critical severity must be resolved or suppressed",
		},
		{
			name:      "suppressed finding passes",
			failOn:    "low",
			allowlist: `{"ignores":[{"id":"ghsa-aaaa-bbbb-cccc","reason":"not reachable"}]}`,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			bin := fakeBinDir(t)
			chdirNewRepo(t)
			fakeDependabot(t, bin, criticalAlert)
			allowlist := writeFixture(t, t.TempDir(), "ignores.json", tc.allowlist)

			var stdout, stderr bytes.Buffer
			err := runAudit(&AuditOptions{
				Dependabot: true,
				Format:     "text",
				FailOn:     tc.failOn,
				IgnoreURL:  allowlist,
			}, &stdout, &stderr)

			if tc.wantErr == "" {
				if err != nil {
					t.Fatalf("expected the audit to pass, got %v", err)
				}
				if got := strings.TrimSpace(stdout.String()); got != "No dependency vulnerabilities found.\n(1 suppressed by allowlist)" {
					t.Fatalf("expected the clean report, got %q", got)
				}
				return
			}
			var blocking *blockingError
			if !errors.As(err, &blocking) || err.Error() != tc.wantErr {
				t.Fatalf("expected a blocking error %q, got %T: %v", tc.wantErr, err, err)
			}
			if !strings.Contains(stdout.String(), "GHSA-aaaa-bbbb-cccc") {
				t.Fatalf("expected the finding in the report, got:\n%s", stdout.String())
			}
		})
	}
}

func TestRunAudit_failures(t *testing.T) {
	t.Run("invalid fail-on", func(t *testing.T) {
		// The threshold is checked before any backend runs.
		t.Setenv("PATH", t.TempDir())
		err := runAudit(&AuditOptions{FailOn: "severe"}, &bytes.Buffer{}, &bytes.Buffer{})
		requireCommandError(t, err, `Invalid --fail-on "severe" (want critical, high, moderate, or low)`)
	})

	t.Run("backend failure", func(t *testing.T) {
		bin := fakeBinDir(t)
		chdirNewRepo(t)
		writeFakeCommand(t, bin, "gh", "echo 'gh: Bad credentials (HTTP 401)' >&2\nexit 4")

		err := runAudit(&AuditOptions{Dependabot: true, FailOn: "critical", Format: "text"}, &bytes.Buffer{}, &bytes.Buffer{})
		requireCommandError(t, err, "Audit failed: dependabot audit failed: gh api dependabot/alerts failed: exit status 4")
	})
}

// fakeDockerWithEmptyImage installs a docker whose image ref is local and saves
// as an image holding no packages.
func fakeDockerWithEmptyImage(t *testing.T, bin, ref string) {
	t.Helper()
	layer, err := crane.Layer(map[string][]byte{"etc/motd": []byte("hello")})
	if err != nil {
		t.Fatal(err)
	}
	img, err := mutate.AppendLayers(empty.Image, layer)
	if err != nil {
		t.Fatal(err)
	}
	tag, err := name.ParseReference(ref)
	if err != nil {
		t.Fatal(err)
	}
	archive := filepath.Join(t.TempDir(), "image.tar")
	if err := tarball.WriteToFile(archive, tag, img); err != nil {
		t.Fatal(err)
	}
	t.Setenv("FAKE_DOCKER_ARCHIVE", archive)
	writeFakeCommand(t, bin, "docker", `case "$1" in
images) echo sha256:abc ;;
save) cp "$FAKE_DOCKER_ARCHIVE" "$3" ;;
*) exit 1 ;;
esac`)
}

func TestRunAuditImage(t *testing.T) {
	const ref = "registry.example.test/onyx/backend:v1.2.3"

	t.Run("clean image passes", func(t *testing.T) {
		bin := fakeBinDir(t)
		t.Setenv("TMPDIR", t.TempDir())
		fakeDockerWithEmptyImage(t, bin, ref)
		allowlist := writeFixture(t, t.TempDir(), "ignores.json", `{"ignores":[]}`)

		var stdout, stderr bytes.Buffer
		err := runAuditImage(ref, &AuditImageOptions{Format: "json,text", FailOn: "low", IgnoreURL: allowlist}, &stdout, &stderr)
		if err != nil {
			t.Fatalf("expected the image audit to pass, got %v", err)
		}
		if !strings.Contains(stdout.String(), `"findings"`) {
			t.Fatalf("expected the JSON result on stdout, got %q", stdout.String())
		}
		if got := strings.TrimSpace(stderr.String()); got != "No dependency vulnerabilities found." {
			t.Fatalf("expected the text report on stderr, got %q", got)
		}
	})

	t.Run("invalid fail-on", func(t *testing.T) {
		t.Setenv("PATH", t.TempDir())
		err := runAuditImage(ref, &AuditImageOptions{FailOn: ""}, &bytes.Buffer{}, &bytes.Buffer{})
		requireCommandError(t, err, `Invalid --fail-on "" (want critical, high, moderate, or low)`)
	})

	t.Run("scan failure", func(t *testing.T) {
		bin := fakeBinDir(t)
		t.Setenv("TMPDIR", t.TempDir())
		writeFakeCommand(t, bin, "docker", "exit 1")

		err := runAuditImage(ref, &AuditImageOptions{FailOn: "critical", Format: "text"}, &bytes.Buffer{}, &bytes.Buffer{})
		requireCommandError(t, err, "Image audit failed: image scan failed: ")
	})
}
