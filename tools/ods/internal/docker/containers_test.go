package docker

import (
	"strings"
	"testing"
)

const inspectJSON = `[{"Id":"abc","Name":"/p-relational_db-1","Created":"2026-01-01T00:00:00Z",
"State":{"Status":"running","StartedAt":"2026-01-02T00:00:00Z","Health":{"Status":"healthy"}},
"Config":{"Labels":{"com.docker.compose.project":"p","com.docker.compose.service":"relational_db","com.docker.compose.project.working_dir":"/w/deployment/docker_compose"}}},
{"Id":"def","Name":"/other","State":{"Status":"exited"},"Config":{"Labels":{}}}]`

func TestListComposeContainersReadsLabelsStateAndHealth(t *testing.T) {
	calls := fakeDocker(t, `case "$1" in
ps) echo abc; echo def ;;
inspect) cat <<'JSON'
`+inspectJSON+`
JSON
;;
esac`)
	containers, err := ListComposeContainers()
	if err != nil {
		t.Fatal(err)
	}
	if len(containers) != 1 {
		t.Fatalf("containers = %+v", containers)
	}
	c := containers[0]
	if c.Project != "p" || c.Service != "relational_db" || c.WorkingDir != "/w/deployment/docker_compose" || c.Name != "p-relational_db-1" || !c.Running() || c.Health != "healthy" || c.StartedAt.IsZero() {
		t.Fatalf("container = %+v", c)
	}
	got := readCalls(t, calls)
	if len(got) != 2 || !strings.HasPrefix(got[0], "ps -a -q --no-trunc --filter label=com.docker.compose.project") || got[1] != "inspect --type container abc def" {
		t.Fatalf("calls = %v", got)
	}
}

func TestListComposeContainersWithoutContainers(t *testing.T) {
	calls := fakeDocker(t, "exit 0")
	containers, err := ListComposeContainers()
	if err != nil || containers != nil {
		t.Fatalf("containers = %v, err = %v", containers, err)
	}
	if got := readCalls(t, calls); len(got) != 1 {
		t.Fatalf("inspected without containers: %v", got)
	}
}

func TestListComposeContainersSkipsContainerRemovedDuringInspect(t *testing.T) {
	fakeDocker(t, `case "$1" in
ps) echo abc; echo gone ;;
inspect)
  [ "$#" -gt 4 ] && exit 1
  [ "$4" = gone ] && exit 1
  cat <<'JSON'
`+inspectJSON+`
JSON
;;
esac`)
	containers, err := ListComposeContainers()
	if err != nil || len(containers) != 1 || containers[0].ID != "abc" {
		t.Fatalf("containers = %+v, err = %v", containers, err)
	}
}

func TestListComposeContainersReportsDockerErrors(t *testing.T) {
	fakeDocker(t, `echo "Cannot connect to the Docker daemon" >&2; exit 1`)
	if _, err := ListComposeContainers(); err == nil || !strings.Contains(err.Error(), "Cannot connect") {
		t.Fatalf("err = %v", err)
	}
}

func TestListComposeContainersRejectsInvalidInspectOutput(t *testing.T) {
	fakeDocker(t, `case "$1" in ps) echo abc ;; inspect) echo not-json ;; esac`)
	if _, err := ListComposeContainers(); err == nil || !strings.Contains(err.Error(), "parse docker inspect") {
		t.Fatalf("err = %v", err)
	}
	fakeDocker(t, `case "$1" in ps) echo abc; echo def ;; inspect) [ "$#" -gt 4 ] && exit 1; echo not-json ;; esac`)
	if _, err := ListComposeContainers(); err == nil {
		t.Fatal("invalid single inspect output was accepted")
	}
}

func TestListComposeContainersReportsMissingDocker(t *testing.T) {
	t.Setenv("PATH", t.TempDir())
	if _, err := ListComposeContainers(); err == nil {
		t.Fatal("listed containers without docker")
	}
	fakeDocker(t, "exit 1")
	if _, err := ListComposeContainers(); err == nil || !strings.Contains(err.Error(), "exit status 1") {
		t.Fatalf("err = %v", err)
	}
}
