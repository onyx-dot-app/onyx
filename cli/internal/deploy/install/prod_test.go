package install

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/deployfiles"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/state"
)

// prodFixture lays out an adoptable prod deployment: compose base + prod
// overlay on disk, an .env naming the running version, and a .env.nginx
// naming the domain — the shape a host deployed from the repo's
// deployment/docker_compose has. No manifest: the CLI has never touched it.
func prodFixture(t *testing.T, tag string) string {
	t.Helper()
	isolateEnv(t)
	shimDockerOnPath(t)
	root := t.TempDir()
	dep := filepath.Join(root, "deployment")
	if err := os.MkdirAll(dep, 0755); err != nil {
		t.Fatal(err)
	}
	for name, content := range map[string]string{
		"docker-compose.yml":      "name: onyx\nservices: {}\n",
		"docker-compose.prod.yml": "name: onyx\nservices: {}\n",
		".env":                    "IMAGE_TAG=" + tag + "\nAUTH_TYPE=google_oauth\n",
		".env.nginx":              "DOMAIN=demo.example.com\nEMAIL=ops@example.com\n",
	} {
		if err := os.WriteFile(filepath.Join(dep, name), []byte(content), 0644); err != nil {
			t.Fatal(err)
		}
	}
	return root
}

// Adopting a prod deployment: the overlay on disk selects prod mode with no
// flag, both compose files ride every invocation, the requested project name
// is used and recorded, HOST_PORT never appears, and the summary names the
// real URL instead of localhost.
func TestUpgradeAdoptsProdDeployment(t *testing.T) {
	root := prodFixture(t, "v4.0.0")
	runner := &fakeRunner{handler: healthyDockerHandler}
	deps := testDeps(t, runner, notFoundServer(t))

	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true,
		Project: "danswer-stack", Force: true,
	})
	if err != nil {
		t.Fatalf("RunUpgrade: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	var up string
	for _, c := range runner.calls {
		line := argv(c)
		if strings.Contains(line, " up ") {
			up = line
			if _, ok := c.Env["HOST_PORT"]; ok {
				t.Errorf("prod up ran with HOST_PORT=%q — the overlay publishes 80/443", c.Env["HOST_PORT"])
			}
			if c.Env["IMAGE_TAG"] != "v4.2.0" {
				t.Errorf("up ran with IMAGE_TAG=%q", c.Env["IMAGE_TAG"])
			}
		}
	}
	if up == "" {
		t.Fatal("compose up never ran")
	}
	if !strings.Contains(up, "-p danswer-stack") {
		t.Errorf("project name not passed: %s", up)
	}
	if !strings.Contains(up, "-f docker-compose.yml -f docker-compose.prod.yml") {
		t.Errorf("prod overlay not applied: %s", up)
	}

	env, _ := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if Var(string(env), "IMAGE_TAG") != "v4.2.0" {
		t.Errorf("IMAGE_TAG = %q", Var(string(env), "IMAGE_TAG"))
	}
	if strings.Contains(string(env), "HOST_PORT") {
		t.Error("HOST_PORT written into a prod .env")
	}
	nginxEnv, _ := os.ReadFile(filepath.Join(root, "deployment", ".env.nginx"))
	if Var(string(nginxEnv), "DOMAIN") != "demo.example.com" {
		t.Error(".env.nginx must never be rewritten — it holds the live domain")
	}

	m, err := state.Load(root)
	if err != nil || m == nil {
		t.Fatalf("manifest: %+v, %v", m, err)
	}
	if m.Mode != state.ModeProd {
		t.Errorf("mode = %q, want prod", m.Mode)
	}
	if m.Project != "danswer-stack" {
		t.Errorf("project = %q, want danswer-stack", m.Project)
	}
	if m.InstalledTag != "v4.2.0" {
		t.Errorf("manifest tag = %q", m.InstalledTag)
	}

	// The prod managed set landed; the install root got no README (these
	// deployments often live inside a checkout that has its own).
	for _, rel := range []string{
		"deployment/env.prod.template",
		"deployment/env.nginx.template",
		"data/nginx/app.conf.template.prod",
		"data/nginx/run-nginx.sh",
	} {
		if _, err := os.Stat(filepath.Join(root, filepath.FromSlash(rel))); err != nil {
			t.Errorf("managed file %s missing: %v", rel, err)
		}
	}
	if _, err := os.Stat(filepath.Join(root, "README.md")); !os.IsNotExist(err) {
		t.Error("prod mode must not drop a README.md into the install root")
	}

	if !strings.Contains(outBuf(deps).String(), "https://demo.example.com") {
		t.Errorf("summary must name the real URL:\n%s", outBuf(deps).String())
	}
	if strings.Contains(outBuf(deps).String(), "http://localhost") {
		t.Errorf("summary must not point at localhost:\n%s", outBuf(deps).String())
	}
}

// Refs cut before docker-compose.prod.yml became an overlay carry the old
// standalone file; fetched onto a prod deployment it would stack a second
// full stack (and the dev port) on the base file. The refresh must recognize
// it and keep the bundled overlay instead.
func TestUpgradeProdRejectsPreOverlayProdFile(t *testing.T) {
	root := prodFixture(t, "v4.0.0")
	runner := &fakeRunner{handler: healthyDockerHandler}
	// The server hands the same body to every file request: a plausible
	// compose file that is NOT overlay-shaped (no !override).
	deps := testDeps(t, runner, rawServer(t, "# generated standalone prod file\nname: onyx\nservices: {}\n"))

	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true, Force: true,
	})
	if err != nil {
		t.Fatalf("RunUpgrade: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	base, _ := os.ReadFile(filepath.Join(root, "deployment", "docker-compose.yml"))
	if !strings.Contains(string(base), "standalone prod file") {
		t.Error("base compose file should refresh from the ref as usual")
	}
	overlay, _ := os.ReadFile(filepath.Join(root, "deployment", "docker-compose.prod.yml"))
	if !strings.Contains(string(overlay), "!override") {
		t.Errorf("prod overlay must fall back to the bundled overlay, got:\n%s", overlay)
	}
	if !strings.Contains(outBuf(deps).String(), "predates the overlay format") {
		t.Errorf("fallback must be explained:\n%s", outBuf(deps).String())
	}
}

// --local trusts what's on disk — except a pre-overlay docker-compose.prod.yml,
// which is not a customization: stacked on the base file it re-publishes the
// dev port. With --force it is replaced by the bundled overlay (backed up).
func TestUpgradeProdLocalReplacesLegacyProdFile(t *testing.T) {
	root := prodFixture(t, "v4.0.0") // fixture prod.yml is legacy-shaped (no !override)
	runner := &fakeRunner{handler: healthyDockerHandler}
	deps := testDeps(t, runner, notFoundServer(t))

	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Local: true, Tag: "v4.2.0", Dir: root, NoWait: true, Force: true,
	})
	if err != nil {
		t.Fatalf("RunUpgrade: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	overlay, _ := os.ReadFile(filepath.Join(root, "deployment", "docker-compose.prod.yml"))
	if !strings.Contains(string(overlay), "!override") {
		t.Errorf("legacy prod file must be replaced by the bundled overlay under --local, got:\n%s", overlay)
	}
	backups, _ := filepath.Glob(filepath.Join(root, "deployment", "docker-compose.prod.yml.bak-*"))
	if len(backups) == 0 {
		t.Error("replacing the legacy prod file must leave a backup")
	}
	// The rest of --local behavior is untouched: the on-disk base compose
	// file was trusted as-is.
	base, _ := os.ReadFile(filepath.Join(root, "deployment", "docker-compose.yml"))
	if string(base) != "name: onyx\nservices: {}\n" {
		t.Errorf("--local must keep the on-disk base compose file, got:\n%s", base)
	}
}

// Without consent to replace it, adoption must stop rather than proceed into
// a merge that would publish the dev port on a prod host.
func TestUpgradeProdRefusesToKeepLegacyProdFile(t *testing.T) {
	root := prodFixture(t, "v4.0.0")
	runner := &fakeRunner{handler: healthyDockerHandler}
	deps := testDeps(t, runner, notFoundServer(t))

	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Local: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	})
	if err == nil || !strings.Contains(err.Error(), "--force") {
		t.Fatalf("err = %v, want a hard stop naming --force", err)
	}

	env, _ := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if Var(string(env), "IMAGE_TAG") != "v4.0.0" {
		t.Error("refused adoption must not touch .env")
	}
	for _, c := range runner.calls {
		if line := argv(c); strings.Contains(line, " pull") || strings.Contains(line, " up ") {
			t.Errorf("deployed despite the refusal: %s", line)
		}
	}
}

// The prod overlay's !override / !reset tags are a parse error before compose
// v2.24.4; the run must stop before touching anything.
func TestUpgradeProdRefusesOldCompose(t *testing.T) {
	root := prodFixture(t, "v4.0.0")
	oldCompose := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if argv(c) == "docker compose version" {
			return dockercmd.Result{Stdout: "Docker Compose version v2.24.0"}, nil
		}
		return healthyDockerHandler(c)
	}}
	deps := testDeps(t, oldCompose, notFoundServer(t))
	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true,
	})
	if err == nil || !strings.Contains(err.Error(), "2.24.4") {
		t.Fatalf("err = %v, want the prod compose-version refusal", err)
	}
	env, _ := os.ReadFile(filepath.Join(root, "deployment", ".env"))
	if Var(string(env), "IMAGE_TAG") != "v4.0.0" {
		t.Error("refused upgrade must not touch .env")
	}
}

// --prod on a deployment the manifest records as something else is a
// conversion, which an upgrade cannot perform (no TLS material, no .env.nginx).
func TestUpgradeRefusesProdConversion(t *testing.T) {
	runner := &fakeRunner{handler: healthyDockerHandler}
	root := installFixture(t, runner, "v4.0.0")

	deps := testDeps(t, runner, notFoundServer(t))
	err := RunUpgrade(context.Background(), deps, Options{
		NoPrompt: true, Tag: "v4.2.0", Dir: root, NoWait: true, Prod: true,
	})
	if err == nil || !strings.Contains(err.Error(), "cannot convert") {
		t.Fatalf("err = %v, want conversion refusal", err)
	}
}

// Fresh prod installs are refused: they need a filled-in .env, .env.nginx and
// certificates before compose can even render, none of which install creates.
func TestInstallProdFreshRejected(t *testing.T) {
	isolateEnv(t)
	shimDockerOnPath(t)
	deps := testDeps(t, &fakeRunner{handler: healthyDockerHandler}, notFoundServer(t))
	err := RunInstall(context.Background(), deps, Options{
		NoPrompt: true, Prod: true, Dir: t.TempDir(), NoWait: true,
	})
	if err == nil || !strings.Contains(err.Error(), "deploy upgrade --prod") {
		t.Fatalf("err = %v, want fresh-prod refusal pointing at upgrade", err)
	}
}

// Read verbs resolve the project from the manifest, so a stack adopted under
// another compose project keeps being found without repeating --project.
func TestStatusUsesRecordedProjectAndDomain(t *testing.T) {
	root := prodFixture(t, "v4.2.0")
	m := &state.Manifest{InstalledTag: "v4.2.0", Mode: state.ModeProd, Project: "danswer-stack"}
	if err := m.Save(root); err != nil {
		t.Fatal(err)
	}

	runner := &fakeRunner{handler: func(c dockercmd.Command) (dockercmd.Result, error) {
		if strings.Contains(argv(c), "ps -a") {
			return dockercmd.Result{Stdout: "danswer-stack-api_server-1\tonyxdotapp/onyx-backend:v4.2.0\tUp 2 hours (healthy)\t80->80/tcp\tapi_server\n"}, nil
		}
		return healthyDockerHandler(c)
	}}
	deps := testDeps(t, runner, notFoundServer(t))
	if err := RunStatus(context.Background(), deps, Options{Dir: root}, true); err != nil {
		t.Fatalf("RunStatus: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	var ps string
	for _, c := range runner.calls {
		if strings.Contains(argv(c), "ps -a") {
			ps = argv(c)
		}
	}
	if !strings.Contains(ps, "label=com.docker.compose.project=danswer-stack") {
		t.Errorf("container listing must filter on the recorded project: %s", ps)
	}

	var st Status
	if err := json.Unmarshal(outBuf(deps).Bytes(), &st); err != nil {
		t.Fatalf("status output is not JSON: %v\n%s", err, outBuf(deps).String())
	}
	if st.Mode != "prod" {
		t.Errorf("mode = %q, want prod", st.Mode)
	}
	if st.AccessURL != "https://demo.example.com" {
		t.Errorf("access_url = %q, want the .env.nginx domain", st.AccessURL)
	}
}

// Stop auto-detects the prod overlay from disk and rides the recorded project,
// like it does for lite.
func TestStopAutoDetectsProd(t *testing.T) {
	root := prodFixture(t, "v4.2.0")
	m := &state.Manifest{InstalledTag: "v4.2.0", Mode: state.ModeProd, Project: "onyx-stack"}
	if err := m.Save(root); err != nil {
		t.Fatal(err)
	}

	runner := &fakeRunner{handler: healthyDockerHandler}
	deps := testDeps(t, runner, notFoundServer(t))
	if err := RunStop(context.Background(), deps, Options{Dir: root}); err != nil {
		t.Fatalf("RunStop: %v\noutput:\n%s", err, outBuf(deps).String())
	}

	var stop string
	for _, c := range runner.calls {
		if strings.HasSuffix(argv(c), " stop") {
			stop = argv(c)
		}
	}
	if stop == "" {
		t.Fatal("compose stop never ran")
	}
	if !strings.Contains(stop, "-f docker-compose.prod.yml") {
		t.Errorf("prod overlay not auto-detected: %s", stop)
	}
	if !strings.Contains(stop, "-p onyx-stack") {
		t.Errorf("recorded project not used: %s", stop)
	}
}

// The prod managed set carries the prod overlay and templates, and neither
// the README nor the dev-flavored files; the standard set is unchanged.
func TestManagedFilesProdSet(t *testing.T) {
	has := func(files []deployfiles.File, f deployfiles.File) bool {
		for _, x := range files {
			if x.DestRel == f.DestRel {
				return true
			}
		}
		return false
	}

	prod := managedFiles(true, false, false)
	for _, want := range []deployfiles.File{
		deployfiles.Compose, deployfiles.ProdOverlay, deployfiles.EnvProdTemplate,
		deployfiles.EnvNginxTemplate, deployfiles.NginxAppConfProd, deployfiles.NginxRunScript,
	} {
		if !has(prod, want) {
			t.Errorf("prod set missing %s", want.DestRel)
		}
	}
	for _, unwanted := range []deployfiles.File{
		deployfiles.Readme, deployfiles.EnvTemplate, deployfiles.NginxAppConf, deployfiles.LiteOverlay,
	} {
		if has(prod, unwanted) {
			t.Errorf("prod set must not carry %s", unwanted.DestRel)
		}
	}

	standard := managedFiles(false, false, false)
	if !has(standard, deployfiles.Readme) || has(standard, deployfiles.ProdOverlay) {
		t.Error("standard set changed")
	}
}
