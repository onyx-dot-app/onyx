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

// prodFixture lays out an adoptable prod deployment: the standalone
// docker-compose.prod.yml, an .env naming the running version, and a
// .env.nginx naming the domain. Deliberately no docker-compose.yml — prod
// runs without it, and the verbs must not depend on it. No manifest: the CLI
// has never touched it.
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

// Adopting a prod deployment: the prod compose file on disk selects prod mode
// with no flag, it is the ONLY -f compose drives, the requested project name
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
				t.Errorf("prod up ran with HOST_PORT=%q — docker-compose.prod.yml publishes 80/443", c.Env["HOST_PORT"])
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
	if !strings.Contains(up, "-f docker-compose.prod.yml") {
		t.Errorf("prod compose file not used: %s", up)
	}
	if strings.Contains(up, "-f docker-compose.yml") {
		t.Errorf("prod is a standalone deployment — the base file must not ride along: %s", up)
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

	// The prod managed set landed; no base compose file and no README were
	// dropped into the root (these deployments often live inside a checkout
	// that has its own).
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
	for _, rel := range []string{"README.md", "deployment/docker-compose.yml"} {
		if _, err := os.Stat(filepath.Join(root, filepath.FromSlash(rel))); !os.IsNotExist(err) {
			t.Errorf("prod mode must not create %s", rel)
		}
	}

	if !strings.Contains(outBuf(deps).String(), "https://demo.example.com") {
		t.Errorf("summary must name the real URL:\n%s", outBuf(deps).String())
	}
	if strings.Contains(outBuf(deps).String(), "http://localhost") {
		t.Errorf("summary must not point at localhost:\n%s", outBuf(deps).String())
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

// Stop auto-detects the standalone prod file from disk (no docker-compose.yml
// needed) and rides the recorded project, like it does for lite overlays.
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
		t.Errorf("prod compose file not auto-detected: %s", stop)
	}
	if strings.Contains(stop, "-f docker-compose.yml") {
		t.Errorf("prod runs standalone — the base file must not ride along: %s", stop)
	}
	if !strings.Contains(stop, "-p onyx-stack") {
		t.Errorf("recorded project not used: %s", stop)
	}
}

// The prod managed set carries the standalone prod compose file and its
// templates — not the base compose file, the README, or the dev-flavored
// files; the standard set is unchanged.
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
		deployfiles.ProdCompose, deployfiles.EnvProdTemplate,
		deployfiles.EnvNginxTemplate, deployfiles.NginxAppConfProd, deployfiles.NginxRunScript,
	} {
		if !has(prod, want) {
			t.Errorf("prod set missing %s", want.DestRel)
		}
	}
	for _, unwanted := range []deployfiles.File{
		deployfiles.Compose, deployfiles.Readme, deployfiles.EnvTemplate,
		deployfiles.NginxAppConf, deployfiles.LiteOverlay,
	} {
		if has(prod, unwanted) {
			t.Errorf("prod set must not carry %s", unwanted.DestRel)
		}
	}

	standard := managedFiles(false, false, false)
	if !has(standard, deployfiles.Readme) || !has(standard, deployfiles.Compose) || has(standard, deployfiles.ProdCompose) {
		t.Error("standard set changed")
	}
}
