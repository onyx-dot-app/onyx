package audit

import (
	"bytes"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/google/go-containerregistry/pkg/crane"
	"github.com/google/go-containerregistry/pkg/name"
	"github.com/google/go-containerregistry/pkg/v1/empty"
	"github.com/google/go-containerregistry/pkg/v1/mutate"
	"github.com/google/go-containerregistry/pkg/v1/tarball"
)

const testImageRef = "registry.example.test/onyx/backend:v1.2.3"

// fakeDockerWithImage installs a docker that reports ref as present locally and
// "saves" an image holding no packages, so the scan needs no vulnerability
// lookups. It returns the docker args log.
func fakeDockerWithImage(t *testing.T, bin string) func() [][]string {
	t.Helper()
	layer, err := crane.Layer(map[string][]byte{"etc/motd": []byte("hello")})
	if err != nil {
		t.Fatal(err)
	}
	img, err := mutate.AppendLayers(empty.Image, layer)
	if err != nil {
		t.Fatal(err)
	}
	ref, err := name.ParseReference(testImageRef)
	if err != nil {
		t.Fatal(err)
	}
	archive := filepath.Join(t.TempDir(), "image.tar")
	if err := tarball.WriteToFile(archive, ref, img); err != nil {
		t.Fatal(err)
	}
	t.Setenv("FAKE_DOCKER_ARCHIVE", archive)
	return writeFakeCommand(t, bin, "docker", `case "$1" in
images) echo sha256:abc ;;
save) cp "$FAKE_DOCKER_ARCHIVE" "$3" ;;
*) exit 1 ;;
esac`)
}

func TestRunImage_imageWithoutPackagesIsClean(t *testing.T) {
	bin := fakeBinDir(t)
	tmp := t.TempDir()
	t.Setenv("TMPDIR", tmp)
	dockerArgs := fakeDockerWithImage(t, bin)
	allowlist := writeFixture(t, t.TempDir(), "ignores.json", `{"ignores":[]}`)

	var stdout, stderr bytes.Buffer
	res, err := RunImage(ImageOptions{
		Image:     testImageRef,
		Format:    "sarif,text",
		FailOn:    SeverityLow,
		IgnoreURL: allowlist,
		Stdout:    &stdout,
		Stderr:    &stderr,
	})
	if err != nil {
		t.Fatalf("RunImage: %v", err)
	}
	if len(res.Findings) != 0 || len(res.Blocking) != 0 {
		t.Fatalf("expected a clean result, got %+v", res)
	}
	if !strings.Contains(stdout.String(), `"version": "2.1.0"`) {
		t.Fatalf("expected a SARIF document on stdout, got %q", stdout.String())
	}
	if got := strings.TrimSpace(stderr.String()); got != "No dependency vulnerabilities found." {
		t.Fatalf("expected the text report on stderr, got %q", got)
	}

	args := dockerArgs()
	if len(args) != 2 || !slices.Equal(args[0], []string{"images", "-q", testImageRef}) {
		t.Fatalf("expected a local image lookup then a save, got %q", args)
	}
	saveArgs := args[1]
	if len(saveArgs) != 4 || saveArgs[0] != "save" || saveArgs[1] != "-o" || saveArgs[3] != testImageRef {
		t.Fatalf("expected %q, got %q", "save -o <archive> "+testImageRef, args[1])
	}
	if filepath.Dir(saveArgs[2]) != tmp {
		t.Fatalf("expected the archive under TMPDIR %q, got %q", tmp, saveArgs[2])
	}
}

func TestRunImage_errors(t *testing.T) {
	t.Run("pull failure", func(t *testing.T) {
		bin := fakeBinDir(t)
		t.Setenv("TMPDIR", t.TempDir())
		dockerArgs := writeFakeCommand(t, bin, "docker", `[ "$1" = images ] && exit 0
echo 'manifest unknown' >&2
exit 1`)

		_, err := RunImage(ImageOptions{Image: testImageRef, Stdout: &bytes.Buffer{}, Stderr: &bytes.Buffer{}})
		if err == nil || !strings.HasPrefix(err.Error(), "image scan failed: failed to pull container image") {
			t.Fatalf("expected a pull failure, got %v", err)
		}
		args := dockerArgs()
		if len(args) != 2 || !slices.Equal(args[1], []string{"pull", "-q", testImageRef}) {
			t.Fatalf("expected a pull of %s after the lookup, got %q", testImageRef, args)
		}
	})

	t.Run("unavailable allowlist is not an error", func(t *testing.T) {
		bin := fakeBinDir(t)
		t.Setenv("TMPDIR", t.TempDir())
		fakeDockerWithImage(t, bin)

		var stdout bytes.Buffer
		res, err := RunImage(ImageOptions{
			Image:     testImageRef,
			IgnoreURL: filepath.Join(t.TempDir(), "missing.json"),
			Stdout:    &stdout,
			Stderr:    &bytes.Buffer{},
		})
		if err != nil || len(res.Findings) != 0 {
			t.Fatalf("expected a clean scan without the allowlist, got %+v, %v", res, err)
		}
		if got := strings.TrimSpace(stdout.String()); got != "No dependency vulnerabilities found." {
			t.Fatalf("expected the default text report on stdout, got %q", got)
		}
	})

	t.Run("unknown format", func(t *testing.T) {
		bin := fakeBinDir(t)
		t.Setenv("TMPDIR", t.TempDir())
		fakeDockerWithImage(t, bin)

		var stdout bytes.Buffer
		_, err := RunImage(ImageOptions{Image: testImageRef, Format: "xml", Stdout: &stdout, Stderr: &bytes.Buffer{}})
		if err == nil || !strings.Contains(err.Error(), `unknown format "xml"`) {
			t.Fatalf("expected an unknown format error, got %v", err)
		}
		if stdout.Len() != 0 {
			t.Fatalf("expected no partial report, got %q", stdout.String())
		}
	})
}
