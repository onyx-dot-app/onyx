package devstack

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
)

// Inventory statuses, in the order `ods stack ls` sorts them.
const (
	StatusOrphaned   = "orphaned"
	StatusActive     = "active"
	StatusAppStopped = "app-stopped"
	StatusInfraOnly  = "infra-only"
	StatusStopped    = "stopped"
	StatusStaleLease = "stale-lease"
)

var statusOrder = map[string]int{StatusOrphaned: 0, StatusActive: 1, StatusAppStopped: 2, StatusInfraOnly: 3, StatusStopped: 4, StatusStaleLease: 5}

const (
	sharedStateDirName   = "ods-stack-shared"
	isolatedStateDirName = "ods-stack"
	frontendStateDirName = "ods-stack-frontend"
	composeWorkingSuffix = "deployment/docker_compose"
	ownerFileName        = "owner.json"
	projectsDirName      = "projects"
)

// AppCount is the number of recorded application services that are alive.
type AppCount struct {
	Running int `json:"running"`
	Total   int `json:"total"`
}

// InfraCount is the number of Compose containers of a project that run.
type InfraCount struct {
	Running int    `json:"running"`
	Total   int    `json:"total"`
	Health  string `json:"health,omitempty"`
}

// StackRow is one dev stack as found on the machine.
type StackRow struct {
	Project string `json:"project"`
	Status  string `json:"status"`
	Root    string `json:"root"`
	// RootExists and Worktree describe Root now: a removed checkout has
	// neither, a directory left behind by a removed worktree has no Worktree.
	RootExists bool        `json:"root_exists"`
	Worktree   bool        `json:"worktree"`
	Branch     string      `json:"branch,omitempty"`
	Mode       Mode        `json:"mode,omitempty"`
	Profile    string      `json:"profile,omitempty"`
	Phase      string      `json:"phase,omitempty"`
	App        *AppCount   `json:"app"`
	Infra      *InfraCount `json:"infra"`
	Web        string      `json:"web,omitempty"`
	// Since is when the oldest running container started, or else when the
	// state was last written.
	Since        time.Time      `json:"since,omitzero"`
	StateDir     string         `json:"state_dir,omitempty"`
	WorkingDir   string         `json:"compose_working_dir,omitempty"`
	OwnerRecord  string         `json:"owner_record,omitempty"`
	LeaseRoot    string         `json:"lease_root,omitempty"`
	Leases       map[string]int `json:"leases,omitempty"`
	OrphanReason string         `json:"orphan_reason,omitempty"`
	// Next is the command that stops the stack, or "" when nothing runs.
	Next   string   `json:"next,omitempty"`
	Errors []string `json:"errors"`

	state      *State
	containers int
}

// Running reports whether the row has a live application process or a
// running container.
func (r StackRow) Running() bool {
	return (r.App != nil && r.App.Running > 0) || (r.Infra != nil && r.Infra.Running > 0)
}

// Inventory is every stack found on the machine.
type Inventory struct {
	Rows     []StackRow
	Warnings []string
	// Unreadable is set when neither Docker nor the port registry could be read.
	Unreadable bool
}

type ownerRecord struct {
	Path string
	// Key is the owner directory name, ProjectName(project).
	Key      string
	StateDir string
	Err      error
}

type stateRecord struct {
	Dir     string
	State   *State
	Err     error
	ModTime time.Time
}

type checkoutInfo struct {
	Worktree bool
	Branch   string
}

type inventoryInput struct {
	Containers []docker.ComposeContainer
	DockerErr  error
	Owners     []ownerRecord
	OwnersErr  error
	States     []stateRecord
	Leases     []Lease
	LeasesErr  error
	Alive      func(ServiceRecord) bool
	Exists     func(string) bool
	Checkout   func(string) checkoutInfo
}

// DiscoverOptions select the sources Discover reads.
type DiscoverOptions struct {
	// ListContainers lists the Compose containers; nil uses Docker.
	ListContainers func() ([]docker.ComposeContainer, error)
	// Dirs are extra directories, such as the working directory, whose
	// repositories are searched for stack state.
	Dirs []string
}

// Discover lists every dev stack on the machine from Docker, the project
// owner records, the stack state files, and the port leases. It takes no
// locks and changes nothing.
func Discover(registry *Registry, opts DiscoverOptions) Inventory {
	return buildInventory(readInventoryInput(registry, opts))
}

func readInventoryInput(registry *Registry, opts DiscoverOptions) inventoryInput {
	in := inventoryInput{Alive: groupIsOurs, Exists: pathExists, Checkout: inspectCheckout}
	list := opts.ListContainers
	if list == nil {
		list = docker.ListComposeContainers
	}
	in.Containers, in.DockerErr = list()
	in.Owners, in.OwnersErr = readOwners(registry)
	in.Leases, in.LeasesErr = registry.Leases()

	// Roots lead to Git common directories, whose state directories are
	// read; each state's root can lead to another repository.
	var roots, dirs []string
	for _, owner := range in.Owners {
		roots = append(roots, owner.StateDir)
		dirs = append(dirs, owner.StateDir)
	}
	for _, lease := range in.Leases {
		roots = append(roots, lease.Root)
	}
	for _, c := range in.Containers {
		roots = append(roots, composeRoot(c.WorkingDir))
	}
	roots = append(roots, opts.Dirs...)
	commons, read := map[string]bool{}, map[string]bool{}
	for len(roots) > 0 || len(dirs) > 0 {
		if len(dirs) == 0 {
			root := roots[0]
			roots = roots[1:]
			if common := commonDirOf(root); root != "" && common != "" && !commons[common] {
				commons[common] = true
				dirs = append(dirs, stateDirCandidates(common)...)
			}
			continue
		}
		dir := dirs[0]
		dirs = dirs[1:]
		if dir == "" || read[dir] {
			continue
		}
		read[dir] = true
		info, err := os.Stat(filepath.Join(dir, stateFileName))
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		record := stateRecord{Dir: dir, Err: err}
		if err == nil {
			record.ModTime = info.ModTime()
			record.State, record.Err = (&Stack{StateDir: dir}).ReadState()
		}
		in.States = append(in.States, record)
		if record.State != nil {
			roots = append(roots, record.State.Root)
		}
	}
	return in
}

func readOwners(registry *Registry) ([]ownerRecord, error) {
	if registry == nil {
		return nil, nil
	}
	paths, err := filepath.Glob(filepath.Join(registry.Dir, projectsDirName, "*", ownerFileName))
	if err != nil {
		return nil, err
	}
	owners := make([]ownerRecord, 0, len(paths))
	for _, path := range paths {
		owners = append(owners, readOwner(path))
	}
	return owners, nil
}

func readOwner(path string) ownerRecord {
	record := ownerRecord{Path: path, Key: filepath.Base(filepath.Dir(path))}
	data, err := os.ReadFile(path)
	if err != nil {
		record.Err = err
		return record
	}
	var owner projectOwner
	if err := json.Unmarshal(data, &owner); err != nil {
		record.Err = fmt.Errorf("parse project owner %s: %w", path, err)
		return record
	}
	if owner.StateDir == "" || !filepath.IsAbs(owner.StateDir) {
		record.Err = fmt.Errorf("invalid project owner %s", path)
		return record
	}
	record.StateDir = owner.StateDir
	return record
}

// commonDirOf returns the Git common directory a stack root or state
// directory belongs to, or "" when it cannot be reached.
func commonDirOf(path string) string {
	switch filepath.Base(path) {
	case sharedStateDirName, isolatedStateDirName, frontendStateDirName:
		parent := filepath.Dir(path)
		if filepath.Base(filepath.Dir(parent)) == "worktrees" {
			parent = filepath.Dir(filepath.Dir(parent))
		}
		if pathExists(parent) {
			return parent
		}
		return ""
	}
	if !pathExists(path) {
		return ""
	}
	common, err := gitOutput(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
	if err != nil {
		return ""
	}
	if resolved, err := filepath.EvalSymlinks(common); err == nil {
		common = resolved
	}
	return common
}

func stateDirCandidates(common string) []string {
	dirs := []string{
		filepath.Join(common, isolatedStateDirName),
		filepath.Join(common, sharedStateDirName),
		filepath.Join(common, frontendStateDirName),
	}
	for _, name := range []string{isolatedStateDirName, frontendStateDirName} {
		matches, err := filepath.Glob(filepath.Join(common, "worktrees", "*", name))
		if err == nil {
			dirs = append(dirs, matches...)
		}
	}
	return dirs
}

// composeRoot is the checkout of a Compose working directory.
func composeRoot(workingDir string) string {
	clean := filepath.Clean(workingDir)
	suffix := filepath.FromSlash(composeWorkingSuffix)
	if strings.HasSuffix(clean, string(filepath.Separator)+suffix) {
		return strings.TrimSuffix(clean, string(filepath.Separator)+suffix)
	}
	return clean
}

func modeOfStateDir(dir string) Mode {
	switch filepath.Base(dir) {
	case sharedStateDirName:
		return Shared
	case frontendStateDirName:
		return Frontend
	}
	return Isolated
}

func pathExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func inspectCheckout(root string) checkoutInfo {
	top, err := gitOutput(root, "rev-parse", "--show-toplevel")
	if err != nil {
		return checkoutInfo{}
	}
	resolvedTop, err1 := filepath.EvalSymlinks(top)
	resolvedRoot, err2 := filepath.EvalSymlinks(root)
	if err1 != nil || err2 != nil || resolvedTop != resolvedRoot {
		return checkoutInfo{}
	}
	branch, _ := gitOutput(root, "branch", "--show-current")
	return checkoutInfo{Worktree: true, Branch: branch}
}

// isOnyxProject recognizes an Onyx Compose project by its services.
func isOnyxProject(containers []docker.ComposeContainer) bool {
	services := map[string]bool{}
	for _, c := range containers {
		services[c.Service] = true
	}
	return services[docker.RelationalDB.Name] && services["cache"]
}

func buildInventory(in inventoryInput) Inventory {
	var inv Inventory
	if in.DockerErr != nil {
		inv.Warnings = append(inv.Warnings, fmt.Sprintf("Docker is unavailable, so containers are not shown: %v", in.DockerErr))
	}
	if in.OwnersErr != nil {
		inv.Warnings = append(inv.Warnings, fmt.Sprintf("cannot read project owner records: %v", in.OwnersErr))
	}
	if in.LeasesErr != nil {
		inv.Warnings = append(inv.Warnings, fmt.Sprintf("cannot read port leases: %v", in.LeasesErr))
	}
	inv.Unreadable = in.DockerErr != nil && (in.OwnersErr != nil || in.LeasesErr != nil) && len(in.States) == 0

	ownersByKey := map[string][]ownerRecord{}
	ownersByStateDir := map[string]ownerRecord{}
	for _, owner := range in.Owners {
		if owner.Err != nil {
			inv.Warnings = append(inv.Warnings, owner.Err.Error())
			continue
		}
		ownersByKey[owner.Key] = append(ownersByKey[owner.Key], owner)
		ownersByStateDir[owner.StateDir] = owner
	}

	statesByDir := map[string]stateRecord{}
	claims := map[string][]stateRecord{}
	for _, record := range in.States {
		statesByDir[record.Dir] = record
		if record.State != nil && record.State.Project != "" && modeOfStateDir(record.Dir) != Frontend {
			claims[record.State.Project] = append(claims[record.State.Project], record)
		}
	}

	groups := map[string][]docker.ComposeContainer{}
	for _, c := range in.Containers {
		groups[c.Project] = append(groups[c.Project], c)
	}
	for project, containers := range groups {
		if len(claims[project]) == 0 && len(ownersByKey[ProjectName(project)]) == 0 && !isOnyxProject(containers) {
			delete(groups, project)
		}
	}

	primary := map[string]string{}
	for project, records := range claims {
		primary[project] = choosePrimary(project, records, ownersByKey)
	}

	var rows []*StackRow
	for _, record := range in.States {
		row := &StackRow{StateDir: record.Dir, Mode: modeOfStateDir(record.Dir), Since: record.ModTime, Errors: []string{}}
		if owner, ok := ownersByStateDir[record.Dir]; ok {
			row.OwnerRecord = owner.Path
		}
		if record.Err != nil {
			row.Errors = append(row.Errors, record.Err.Error())
		}
		if st := record.State; st != nil {
			row.state = st
			row.Project, row.Root, row.Profile, row.Phase = st.Project, st.Root, st.Profile, st.Phase
			row.Errors = append(row.Errors, st.Errors...)
			row.App, row.Web = appCount(st, in.Alive)
			if row.Mode != Frontend && primary[st.Project] == record.Dir {
				if containers, ok := groups[st.Project]; ok {
					row.attachContainers(containers)
					delete(groups, st.Project)
				}
			}
		}
		rows = append(rows, row)
	}

	projects := make([]string, 0, len(groups))
	for project := range groups {
		projects = append(projects, project)
	}
	sort.Strings(projects)
	for _, project := range projects {
		row := &StackRow{Project: project, Errors: []string{}}
		row.attachContainers(groups[project])
		row.Root = composeRoot(row.WorkingDir)
		for _, owner := range ownersByKey[ProjectName(project)] {
			row.OwnerRecord = owner.Path
			record, ok := statesByDir[owner.StateDir]
			switch {
			case !ok:
				row.Errors = append(row.Errors, fmt.Sprintf("owner record %s points to %s, which has no state", owner.Path, owner.StateDir))
			case record.Err != nil:
				row.Errors = append(row.Errors, record.Err.Error())
			}
		}
		rows = append(rows, row)
	}

	attached := map[string]bool{}
	for _, row := range rows {
		attached[row.OwnerRecord] = true
	}
	for _, owner := range in.Owners {
		if owner.Err == nil && !attached[owner.Path] {
			rows = append(rows, &StackRow{OwnerRecord: owner.Path, StateDir: owner.StateDir, Mode: modeOfStateDir(owner.StateDir),
				Status: StatusOrphaned, OrphanReason: "the owner record points to missing state", Errors: []string{}})
		}
	}
	for _, row := range rows {
		if row.Root != "" {
			row.RootExists = in.Exists(row.Root)
			if row.RootExists {
				info := in.Checkout(row.Root)
				row.Worktree, row.Branch = info.Worktree, info.Branch
			}
		}
	}

	leasesByRoot := map[string]map[string]int{}
	var leaseRoots []string
	for _, lease := range in.Leases {
		if leasesByRoot[lease.Root] == nil {
			leasesByRoot[lease.Root] = map[string]int{}
			leaseRoots = append(leaseRoots, lease.Root)
		}
		leasesByRoot[lease.Root][lease.Name] = lease.Port
	}
	for _, root := range leaseRoots {
		if row := leaseOwner(rows, root); row != nil {
			row.LeaseRoot, row.Leases = root, leasesByRoot[root]
			continue
		}
		rows = append(rows, &StackRow{Root: root, RootExists: in.Exists(root), Status: StatusStaleLease, LeaseRoot: root, Leases: leasesByRoot[root], Errors: []string{}})
	}

	for _, row := range rows {
		if row.Status == "" {
			row.Status, row.OrphanReason = rowStatus(row, len(claims[row.Project]) > 0)
		}
		row.Next = nextCommand(row)
		inv.Rows = append(inv.Rows, *row)
	}
	sort.SliceStable(inv.Rows, func(i, j int) bool {
		a, b := inv.Rows[i], inv.Rows[j]
		if statusOrder[a.Status] != statusOrder[b.Status] {
			return statusOrder[a.Status] < statusOrder[b.Status]
		}
		if !a.Since.Equal(b.Since) {
			return a.Since.Before(b.Since)
		}
		return a.Project < b.Project
	})
	return inv
}

// choosePrimary picks the state that owns a project's infrastructure: the
// owner record's state, else the newest.
func choosePrimary(project string, records []stateRecord, owners map[string][]ownerRecord) string {
	best := records[0]
	for _, record := range records {
		for _, owner := range owners[ProjectName(project)] {
			if record.Dir == owner.StateDir {
				return record.Dir
			}
		}
		if record.State.UpdatedAt.After(best.State.UpdatedAt) {
			best = record
		}
	}
	return best.Dir
}

func appCount(st *State, alive func(ServiceRecord) bool) (*AppCount, string) {
	count := &AppCount{}
	web := ""
	for _, rec := range st.Services {
		if rec.Skipped != "" {
			continue
		}
		count.Total++
		if !alive(rec) {
			continue
		}
		count.Running++
		if rec.Slug == "web" {
			port := rec.Port
			if port == 0 {
				port = st.Ports["web"]
			}
			if port > 0 {
				web = fmt.Sprintf("http://localhost:%d", port)
			}
		}
	}
	return count, web
}

func (r *StackRow) attachContainers(containers []docker.ComposeContainer) {
	infra := &InfraCount{Total: len(containers)}
	var oldest time.Time
	health := map[string]bool{}
	for _, c := range containers {
		if r.WorkingDir == "" {
			r.WorkingDir = c.WorkingDir
		}
		if !c.Running() {
			continue
		}
		infra.Running++
		if c.Health != "" {
			health[c.Health] = true
		}
		if !c.StartedAt.IsZero() && (oldest.IsZero() || c.StartedAt.Before(oldest)) {
			oldest = c.StartedAt
		}
	}
	switch {
	case health["unhealthy"]:
		infra.Health = "unhealthy"
	case health["starting"]:
		infra.Health = "starting"
	case health["healthy"]:
		infra.Health = "healthy"
	}
	if oldest.IsZero() && r.Since.IsZero() {
		for _, c := range containers {
			if !c.CreatedAt.IsZero() && (oldest.IsZero() || c.CreatedAt.Before(oldest)) {
				oldest = c.CreatedAt
			}
		}
	}
	if !oldest.IsZero() {
		r.Since = oldest
	}
	r.Infra = infra
	r.containers = len(containers)
}

// leaseOwner finds the stack whose leases are keyed by root: an isolated
// stack leases under its checkout, a shared or frontend stack under its
// state directory.
func leaseOwner(rows []*StackRow, root string) *StackRow {
	for _, row := range rows {
		if row.StateDir == root && row.Mode != Isolated {
			return row
		}
	}
	for _, row := range rows {
		if row.state != nil && row.Mode == Isolated && row.Root == root {
			return row
		}
	}
	for _, row := range rows {
		if row.state == nil && row.Root == root {
			return row
		}
	}
	return nil
}

// nextCommand is the command that stops row's stack.
func nextCommand(row *StackRow) string {
	inRoot := func(args string) string {
		return "cd " + shellQuote(row.Root) + " && ods " + args
	}
	switch row.Status {
	case StatusOrphaned:
		if row.Mode == Frontend || row.Project == "" {
			return "ods stack prune"
		}
		return "ods stack down --project " + row.Project
	case StatusActive, StatusAppStopped, StatusInfraOnly:
		switch {
		case row.state == nil:
			return "ods stack down --project " + row.Project
		case row.Mode == Frontend:
			return "stop the 'ods web dev' process in " + row.Root
		case row.Mode == Isolated:
			return inRoot("--isolated stack down")
		}
		return inRoot("stack down")
	case StatusStopped:
		if row.containers > 0 && row.Project != "" {
			return "ods stack down --project " + row.Project
		}
	}
	return ""
}

func shellQuote(path string) string {
	if path != "" && !strings.ContainsAny(path, " \t'\"$`\\;&|<>()*?[]{}~!#") {
		return path
	}
	return "'" + strings.ReplaceAll(path, "'", `'\''`) + "'"
}

func rowStatus(row *StackRow, claimed bool) (string, string) {
	reason := ""
	switch {
	case row.state != nil && row.Root != "" && !row.RootExists:
		reason = "the checkout no longer exists"
	case row.state != nil && row.Root != "" && !row.Worktree:
		reason = "the checkout is no longer a git worktree"
	case row.state == nil && row.WorkingDir != "" && !claimed && !row.RootExists:
		reason = "the Compose working directory no longer exists"
	case row.state == nil && row.OwnerRecord != "" && !claimed && !row.Worktree:
		reason = "the owning worktree was removed"
	}
	appRunning := row.App != nil && row.App.Running > 0
	infraRunning := row.Infra != nil && row.Infra.Running > 0
	if reason != "" && (appRunning || row.containers > 0 || len(row.Leases) > 0 || row.OwnerRecord != "") {
		return StatusOrphaned, reason
	}
	switch {
	case appRunning:
		return StatusActive, ""
	case infraRunning && row.state != nil && row.Phase == PhaseStopped:
		return StatusAppStopped, ""
	case infraRunning:
		return StatusInfraOnly, ""
	}
	return StatusStopped, ""
}
