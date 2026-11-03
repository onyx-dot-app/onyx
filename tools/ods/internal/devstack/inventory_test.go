package devstack

import (
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
)

type fakeMachine struct {
	containers []docker.ComposeContainer
	dockerErr  error
	owners     []ownerRecord
	states     []stateRecord
	leases     []Lease
	alivePIDs  map[int]bool
	existing   map[string]bool
	worktrees  map[string]string
}

func (m *fakeMachine) input() inventoryInput {
	return inventoryInput{
		Containers: m.containers,
		DockerErr:  m.dockerErr,
		Owners:     m.owners,
		States:     m.states,
		Leases:     m.leases,
		Alive:      func(rec ServiceRecord) bool { return m.alivePIDs[rec.PID] },
		Exists:     func(path string) bool { return m.existing[path] },
		Checkout: func(path string) checkoutInfo {
			branch, ok := m.worktrees[path]
			return checkoutInfo{Worktree: ok, Branch: branch}
		},
	}
}

// worktree adds an existing checkout with its Compose directory.
func (m *fakeMachine) worktree(root, branch string) {
	if m.existing == nil {
		m.existing, m.worktrees = map[string]bool{}, map[string]string{}
	}
	m.existing[root] = true
	m.existing[filepath.Join(root, "deployment", "docker_compose")] = true
	m.worktrees[root] = branch
}

func onyxContainers(project, root string, running bool, started time.Time) []docker.ComposeContainer {
	state := "exited"
	if running {
		state = "running"
	}
	var containers []docker.ComposeContainer
	for _, service := range []string{"relational_db", "cache", "opensearch"} {
		containers = append(containers, docker.ComposeContainer{
			Project: project, Service: service, State: state, StartedAt: started,
			WorkingDir: filepath.Join(root, "deployment", "docker_compose"),
		})
	}
	return containers
}

func isolatedState(common, worktree, project, root, phase string, pids ...int) stateRecord {
	st := &State{Project: project, Root: root, Profile: "minimal", Phase: phase, Ports: map[string]int{"web": 3004}}
	for i, pid := range pids {
		slug := []string{"web", "api", "worker"}[i%3]
		st.Services = append(st.Services, ServiceRecord{Name: slug, Slug: slug, PID: pid, PGID: pid, Port: 3004})
	}
	return stateRecord{Dir: filepath.Join(common, "worktrees", worktree, "ods-stack"), State: st, ModTime: time.Now().Add(-time.Hour)}
}

func rowFor(t *testing.T, inv Inventory, project string) StackRow {
	t.Helper()
	for _, row := range inv.Rows {
		if row.Project == project {
			return row
		}
	}
	t.Fatalf("no row for %s in %+v", project, inv.Rows)
	return StackRow{}
}

func TestInventoryLiveStack(t *testing.T) {
	m := &fakeMachine{alivePIDs: map[int]bool{11: true, 12: true}}
	m.worktree("/repo/.worktrees/live", "feature")
	m.containers = onyxContainers("live-1", "/repo/.worktrees/live", true, time.Now().Add(-2*time.Hour))
	m.states = []stateRecord{isolatedState("/repo/.git", "live", "live-1", "/repo/.worktrees/live", PhaseReady, 11, 12)}
	m.leases = []Lease{{Root: "/repo/.worktrees/live", Name: "web", Port: 3004}}
	row := rowFor(t, buildInventory(m.input()), "live-1")
	if row.Status != StatusActive || row.App.Running != 2 || row.App.Total != 2 || row.Infra.Running != 3 || row.Infra.Total != 3 {
		t.Fatalf("live stack: %+v app=%+v infra=%+v", row, row.App, row.Infra)
	}
	if row.Web != "http://localhost:3004" || row.Branch != "feature" || row.Mode != Isolated || row.Leases["web"] != 3004 {
		t.Fatalf("live stack details: %+v", row)
	}
	if time.Since(row.Since) < 2*time.Hour-time.Minute {
		t.Fatalf("age should come from the oldest running container: %v", row.Since)
	}
}

func TestInventoryAppStoppedAndInfraOnly(t *testing.T) {
	m := &fakeMachine{}
	m.worktree("/repo", "main")
	m.worktree("/repo/.worktrees/crashed", "crashed")
	m.containers = append(onyxContainers("stopped-app", "/repo", true, time.Now()), onyxContainers("crashed-app", "/repo/.worktrees/crashed", true, time.Now())...)
	shared := stateRecord{Dir: "/repo/.git/ods-stack-shared", State: &State{Project: "stopped-app", Root: "/repo", Phase: PhaseStopped}}
	crashed := isolatedState("/repo/.git", "crashed", "crashed-app", "/repo/.worktrees/crashed", PhaseReady, 21, 22)
	m.states = []stateRecord{shared, crashed}
	inv := buildInventory(m.input())
	if row := rowFor(t, inv, "stopped-app"); row.Status != StatusAppStopped || row.Mode != Shared {
		t.Fatalf("stopped app: %+v", row)
	}
	if row := rowFor(t, inv, "crashed-app"); row.Status != StatusInfraOnly || row.App.Running != 0 || row.App.Total != 2 {
		t.Fatalf("dead app processes: %+v", row)
	}
}

func TestInventoryComposeOnlyProjectIsInfraOnly(t *testing.T) {
	m := &fakeMachine{}
	m.worktree("/repo", "main")
	m.containers = onyxContainers("onyx", "/repo", true, time.Now())
	m.containers = append(m.containers, docker.ComposeContainer{Project: "unrelated", Service: "web", State: "running"})
	inv := buildInventory(m.input())
	if row := rowFor(t, inv, "onyx"); row.Status != StatusInfraOnly || row.App != nil || row.Root != "/repo" {
		t.Fatalf("compose-only project: %+v", row)
	}
	for _, row := range inv.Rows {
		if row.Project == "unrelated" {
			t.Fatal("listed a Compose project that is not Onyx")
		}
	}
}

func TestInventoryOrphanWithMissingRoot(t *testing.T) {
	m := &fakeMachine{}
	m.containers = onyxContainers("gone-1", "/repo/.worktrees/gone", true, time.Now().Add(-96*time.Hour))
	m.owners = []ownerRecord{{Path: "/data/projects/x/owner.json", Key: ProjectName("gone-1"), StateDir: "/repo/.git/worktrees/gone/ods-stack"}}
	m.leases = []Lease{{Root: "/repo/.worktrees/gone", Name: "POSTGRES_HOST_PORT", Port: 5433}}
	row := rowFor(t, buildInventory(m.input()), "gone-1")
	if row.Status != StatusOrphaned || row.RootExists || row.Root != "/repo/.worktrees/gone" || row.LeaseRoot != "/repo/.worktrees/gone" {
		t.Fatalf("orphan: %+v", row)
	}
	if len(row.Errors) != 1 || row.OwnerRecord == "" {
		t.Fatalf("missing owner state should be reported: %+v", row.Errors)
	}
}

func TestInventoryOrphanWhoseStateOutlivedItsRoot(t *testing.T) {
	m := &fakeMachine{alivePIDs: map[int]bool{31: true}}
	m.states = []stateRecord{isolatedState("/repo/.git", "deleted", "deleted-1", "/repo/.worktrees/deleted", PhaseReady, 31)}
	row := rowFor(t, buildInventory(m.input()), "deleted-1")
	if row.Status != StatusOrphaned || row.App.Running != 1 {
		t.Fatalf("live processes of a deleted checkout: %+v", row)
	}
}

func TestInventoryRemovedWorktreeWhoseDirectoryRemains(t *testing.T) {
	m := &fakeMachine{existing: map[string]bool{"/repo/.worktrees/left": true, "/repo/.worktrees/left/deployment/docker_compose": true}}
	m.containers = onyxContainers("left-1", "/repo/.worktrees/left", true, time.Now())
	m.owners = []ownerRecord{{Path: "/data/projects/y/owner.json", Key: ProjectName("left-1"), StateDir: "/repo/.git/worktrees/left/ods-stack"}}
	row := rowFor(t, buildInventory(m.input()), "left-1")
	if row.Status != StatusOrphaned || !row.RootExists || row.Worktree {
		t.Fatalf("directory of a removed worktree: %+v", row)
	}

	// The same directory without an owner record is a plain Compose project.
	m.owners = nil
	if row := rowFor(t, buildInventory(m.input()), "left-1"); row.Status != StatusInfraOnly {
		t.Fatalf("unmanaged Compose project was flagged: %+v", row)
	}
}

func TestInventoryStaleLease(t *testing.T) {
	m := &fakeMachine{}
	m.worktree("/repo/.worktrees/old", "old")
	m.leases = []Lease{{Root: "/repo/.worktrees/old", Name: "web", Port: 3001}}
	inv := buildInventory(m.input())
	if len(inv.Rows) != 1 || inv.Rows[0].Status != StatusStaleLease || inv.Rows[0].Leases["web"] != 3001 || inv.Rows[0].Running() {
		t.Fatalf("stale lease: %+v", inv.Rows)
	}
}

func TestInventoryWithoutDocker(t *testing.T) {
	m := &fakeMachine{dockerErr: errors.New("cannot connect"), alivePIDs: map[int]bool{41: true}}
	m.worktree("/repo/.worktrees/a", "a")
	m.states = []stateRecord{
		isolatedState("/repo/.git", "a", "a-1", "/repo/.worktrees/a", PhaseReady, 41),
		{Dir: "/repo/.git/worktrees/b/ods-stack", Err: errors.New("parse state.json: unexpected end of JSON input")},
	}
	inv := buildInventory(m.input())
	if inv.Unreadable || len(inv.Warnings) != 1 {
		t.Fatalf("Docker outage should only warn: %+v", inv)
	}
	if row := rowFor(t, inv, "a-1"); row.Status != StatusActive || row.Infra != nil {
		t.Fatalf("state-only row: %+v", row)
	}
	corrupt := rowFor(t, inv, "")
	if corrupt.Status != StatusStopped || len(corrupt.Errors) != 1 {
		t.Fatalf("corrupt state should degrade its row: %+v", corrupt)
	}
}

func TestInventoryUnreadableWhenNoSourceCanBeRead(t *testing.T) {
	m := &fakeMachine{dockerErr: errors.New("no docker")}
	in := m.input()
	in.LeasesErr = errors.New("parse port registry")
	if !buildInventory(in).Unreadable {
		t.Fatal("no readable source should be reported")
	}
}

func TestInventorySortsOrphansFirstThenOldest(t *testing.T) {
	m := &fakeMachine{alivePIDs: map[int]bool{51: true, 52: true}}
	m.worktree("/r/new", "new")
	m.worktree("/r/old", "old")
	m.states = []stateRecord{
		isolatedState("/r/.git", "new", "new-1", "/r/new", PhaseReady, 51),
		isolatedState("/r/.git", "old", "old-1", "/r/old", PhaseReady, 52),
		isolatedState("/r/.git", "gone", "gone-1", "/r/gone", PhaseReady, 52),
	}
	m.states[0].ModTime = time.Now()
	m.states[1].ModTime = time.Now().Add(-48 * time.Hour)
	inv := buildInventory(m.input())
	var got []string
	for _, row := range inv.Rows {
		got = append(got, row.Project)
	}
	if len(got) != 3 || got[0] != "gone-1" || got[1] != "old-1" || got[2] != "new-1" {
		t.Fatalf("order = %v", got)
	}
}

func TestComposeRootStripsComposeDirectory(t *testing.T) {
	if got := composeRoot("/a/b/deployment/docker_compose"); got != "/a/b" {
		t.Fatalf("composeRoot = %s", got)
	}
}

func TestInventoryNextCommandStopsEachStack(t *testing.T) {
	m := &fakeMachine{alivePIDs: map[int]bool{61: true}}
	m.worktree("/repo/wt a", "a")
	m.worktree("/repo", "main")
	m.containers = onyxContainers("compose-only", "/repo", true, time.Now())
	m.states = []stateRecord{
		isolatedState("/repo/.git", "a", "iso-1", "/repo/wt a", PhaseReady, 61),
		isolatedState("/repo/.git", "gone", "gone-1", "/repo/gone", PhaseReady, 61),
	}
	inv := buildInventory(m.input())
	for project, want := range map[string]string{
		"iso-1":        "cd '/repo/wt a' && ods --isolated stack down",
		"gone-1":       "ods stack down --project gone-1",
		"compose-only": "ods stack down --project compose-only",
	} {
		if got := rowFor(t, inv, project).Next; got != want {
			t.Errorf("%s next = %q, want %q", project, got, want)
		}
	}
}

func TestInventoryListsOwnerRecordWithoutStateOrContainers(t *testing.T) {
	m := &fakeMachine{}
	m.owners = []ownerRecord{{Path: "/data/projects/z/owner.json", Key: "z", StateDir: "/repo/.git/worktrees/z/ods-stack"}}
	inv := buildInventory(m.input())
	if len(inv.Rows) != 1 || inv.Rows[0].Status != StatusOrphaned || inv.Rows[0].Next != "ods stack prune" {
		t.Fatalf("owner-only record: %+v", inv.Rows)
	}
}
