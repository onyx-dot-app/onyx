package cmd

import (
	"slices"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/config"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// TestDeployEdge walks the edge flow against a real origin and a fake gh. Each
// case lists how many of the full flow's gh calls must happen, so a failing
// step must stop every later step. Consecutive identical run list polls are
// collapsed before comparing.
func TestDeployEdge(t *testing.T) {
	fullCalls := []string{
		"--version",
		"run list -R onyx-dot-app/onyx --workflow deployment.yml --limit 10 " + deployRunJSONFields + " --event push --branch edge",
		"run list -R onyx-dot-app/onyx --workflow deployment.yml --limit 5 " + deployRunJSONFields + " --event push --branch edge",
		"run view 101 -R onyx-dot-app/onyx " + deployRunJSONFields,
		"run list -R org/deploys --workflow edge.yml --limit 10 " + deployRunJSONFields + " --event workflow_dispatch",
		"workflow run edge.yml -R org/deploys -f version_tag=edge",
		"run list -R org/deploys --workflow edge.yml --limit 5 " + deployRunJSONFields + " --event workflow_dispatch",
		"run view 8 -R org/deploys " + deployRunJSONFields,
	}
	buildSucceeded := deployRun(t, workflowRun{DatabaseID: 101, Status: "completed", Conclusion: "success"})
	deploySucceeded := deployRun(t, workflowRun{DatabaseID: 8, Status: "completed", Conclusion: "success"})
	failed := deployRun(t, workflowRun{Status: "completed", Conclusion: "failure"})
	runLists := []deployGHReply{
		deployRuns(t, workflowRun{DatabaseID: 100}),
		deployRuns(t, workflowRun{DatabaseID: 100}, workflowRun{DatabaseID: 101}),
		deployRuns(t, workflowRun{DatabaseID: 7}),
		deployRuns(t, workflowRun{DatabaseID: 8}, workflowRun{DatabaseID: 7}),
	}

	cases := []struct {
		name          string
		opts          DeployEdgeOptions
		corruptConfig bool
		rejectPushes  bool
		// override replaces the default replies for a gh subcommand.
		override  map[string][]deployGHReply
		wantErr   string
		wantCalls int
		wantPush  bool
	}{
		{name: "builds and deploys", wantCalls: 8, wantPush: true},
		{name: "ref main moves the edge tag", opts: DeployEdgeOptions{Ref: "main"}, wantCalls: 8, wantPush: true},
		{name: "ref origin/main moves the edge tag", opts: DeployEdgeOptions{Ref: "origin/main"}, wantCalls: 8, wantPush: true},
		{name: "no-wait-deploy skips the deploy watch", opts: DeployEdgeOptions{NoWaitDeploy: true}, wantCalls: 7, wantPush: true},
		{name: "dry run pushes and dispatches nothing", opts: DeployEdgeOptions{DryRun: true}, wantCalls: 2},
		{name: "unreadable config", corruptConfig: true, wantErr: "Failed to load ods config", wantCalls: 1},
		{
			name:      "prior build lookup fails before the push",
			override:  map[string][]deployGHReply{"run-list": {deployGHFailure("HTTP 500")}},
			wantErr:   "Failed to query existing deployment runs",
			wantCalls: 2,
		},
		{name: "rejected push", rejectPushes: true, wantErr: "Failed to push edge tag", wantCalls: 2},
		{
			name:      "build run never appears",
			override:  map[string][]deployGHReply{"run-list": {runLists[0]}},
			wantErr:   "Failed to find triggered build run",
			wantCalls: 3,
			wantPush:  true,
		},
		{
			name:      "failed build is not deployed",
			override:  map[string][]deployGHReply{"run-view": {failed}},
			wantErr:   "Build did not complete successfully",
			wantCalls: 4,
			wantPush:  true,
		},
		{
			name:      "prior deploy lookup fails",
			override:  map[string][]deployGHReply{"run-list": {runLists[0], runLists[1], deployGHFailure("HTTP 500")}},
			wantErr:   "Failed to query existing deploy runs",
			wantCalls: 5,
			wantPush:  true,
		},
		{
			name:      "deploy dispatch fails",
			override:  map[string][]deployGHReply{"workflow-run": {deployGHFailure("HTTP 403")}},
			wantErr:   "Failed to dispatch deploy workflow",
			wantCalls: 6,
			wantPush:  true,
		},
		{
			name:      "deploy run never appears",
			override:  map[string][]deployGHReply{"run-list": {runLists[0], runLists[1], runLists[2]}},
			wantErr:   "Failed to find dispatched deploy run",
			wantCalls: 7,
			wantPush:  true,
		},
		{
			name:      "failed deploy",
			override:  map[string][]deployGHReply{"run-view": {buildSucceeded, failed}},
			wantErr:   "Deploy did not complete successfully",
			wantCalls: 8,
			wantPush:  true,
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			path := deployIsolateConfigAndAppData(t)
			deploySaveConfig(t, &config.Config{
				Deploy:     config.DeployConfig{TargetRepo: "org/deploys"},
				DeployEdge: config.DeployCommandConfig{TargetWorkflow: "edge.yml"},
			})
			if c.corruptConfig {
				deployWriteFile(t, path, "{")
			}
			repo := gittest.SetupReleaseBranchRepo(t)
			if c.rejectPushes {
				gittest.RejectPushes(t, repo.Origin)
			}
			replies := map[string][]deployGHReply{
				"run-list":     runLists,
				"run-view":     {buildSucceeded, deploySucceeded},
				"workflow-run": {{}},
			}
			for key, list := range c.override {
				replies[key] = list
			}
			gh := deployNewFakeGH(t, replies)
			deployCaptureOutput(t)

			opts := c.opts
			opts.Yes = true
			err := deployEdge(&opts, deployFastPolling())

			if c.wantErr == "" && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if c.wantErr != "" && (err == nil || !strings.Contains(err.Error(), c.wantErr)) {
				t.Fatalf("expected error containing %q, got %v", c.wantErr, err)
			}
			if calls, want := deployCompactRunListPolls(gh.calls()), fullCalls[:c.wantCalls]; !slices.Equal(calls, want) {
				t.Fatalf("expected gh calls %q, got %q", want, calls)
			}
			pushed := gittest.TagExists(repo.Origin, edgeTagName)
			if pushed != c.wantPush {
				t.Fatalf("expected edge tag on origin: %v, got %v", c.wantPush, pushed)
			}
			if pushed {
				if sha := gittest.Git(t, repo.Origin, "rev-parse", "refs/tags/edge^{commit}"); sha != repo.PostCutSHA {
					t.Fatalf("expected edge at origin/main %s, got %s", repo.PostCutSHA, sha)
				}
			}
		})
	}
}

func TestDeployEdge_forcePushMovesAnExistingEdgeTag(t *testing.T) {
	deployIsolateConfigAndAppData(t)
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "edge", repo.PreCutSHA)
	gittest.Git(t, repo.Work, "push", "--quiet", "origin", "edge")
	deployNewFakeGH(t, map[string][]deployGHReply{
		"run-list": {
			deployRuns(t, workflowRun{DatabaseID: 100}),
			deployRuns(t, workflowRun{DatabaseID: 101}),
			deployRuns(t),
			deployRuns(t, workflowRun{DatabaseID: 1}),
		},
		"run-view":     {deployRun(t, workflowRun{DatabaseID: 101, Status: "completed", Conclusion: "success"})},
		"workflow-run": {{}},
	})
	deployCaptureOutput(t)

	err := deployEdge(&DeployEdgeOptions{TargetRepo: "org/deploys", TargetWorkflow: "edge.yml", Yes: true, NoWaitDeploy: true}, deployFastPolling())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if sha := gittest.Git(t, repo.Origin, "rev-parse", "refs/tags/edge^{commit}"); sha != repo.PostCutSHA {
		t.Fatalf("expected edge moved to %s, got %s", repo.PostCutSHA, sha)
	}
}

// deployCompactRunListPolls collapses consecutive identical "run list" calls,
// which come from discovery polling. Other repeated calls stay visible.
func deployCompactRunListPolls(calls []string) []string {
	var out []string
	for i, call := range calls {
		if i > 0 && call == calls[i-1] && strings.HasPrefix(call, "run list ") {
			continue
		}
		out = append(out, call)
	}
	return out
}

func TestDevBuildTagName(t *testing.T) {
	const sha = "c86bc0eb5969add716957c9ca48b6a164358cb63"
	cases := []struct {
		ref  string
		want string
	}{
		{ref: "user/python-agent-sdk", want: "dev-build-python-agent-sdk-c86bc0e"},
		{ref: "origin/user/feat", want: "dev-build-feat-c86bc0e"},
		{ref: "release", want: "dev-build-release-c86bc0e"},
		{ref: "user/Feat_X//v2", want: "dev-build-feat-x-v2-c86bc0e"},
		{ref: "user/" + strings.Repeat("a", 39) + "-b", want: "dev-build-" + strings.Repeat("a", 39) + "-c86bc0e"},
		{ref: "user/___", want: "dev-build-c86bc0e"},
		{ref: sha, want: "dev-build-c86bc0e"},
	}
	for _, c := range cases {
		t.Run(c.ref, func(t *testing.T) {
			got := devBuildTagName(c.ref, sha)
			if got != c.want {
				t.Fatalf("expected %q, got %q", c.want, got)
			}
			if err := validateDevBuildTag(got); err != nil {
				t.Fatalf("derived tag %q is invalid: %v", got, err)
			}
		})
	}
}

func TestValidateDevBuildTag(t *testing.T) {
	cases := []struct {
		tag     string
		wantErr string
	}{
		{tag: "dev-build-feature-1a2b3c4"},
		{tag: "dev-build-v1.2_x"},
		{tag: "feature-1a2b3c4", wantErr: "must start with dev-build-"},
		{tag: "dev-build-", wantErr: "must start with dev-build-"},
		{tag: "dev-build-cloud-fix", wantErr: "must not contain \"cloud\""},
		{tag: "dev-build-Cloud-fix", wantErr: "must not contain \"cloud\""},
		{tag: "dev-build-a/b", wantErr: "valid Docker tag"},
		{tag: "dev-build-a..b", wantErr: "valid git tag name"},
		{tag: "dev-build-demo-dev", wantErr: "must not end in \"-dev\""},
		{tag: "dev-build-demo-DEV", wantErr: "must not end in \"-dev\""},
		{tag: "dev-build-dev-tools"},
		{tag: "dev-build-foo.", wantErr: "valid git tag name"},
		{tag: "dev-build-foo.lock", wantErr: "valid git tag name"},
		{tag: "dev-build-" + strings.Repeat("a", 115), wantErr: "valid Docker tag"},
	}
	for _, c := range cases {
		t.Run(c.tag, func(t *testing.T) {
			err := validateDevBuildTag(c.tag)
			if c.wantErr == "" && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if c.wantErr != "" && (err == nil || !strings.Contains(err.Error(), c.wantErr)) {
				t.Fatalf("expected error containing %q, got %v", c.wantErr, err)
			}
		})
	}
}

const edgeTestBranch = "user/feat-x"

// edgeBranchRepo is an origin and work clone with edgeTestBranch pushed.
type edgeBranchRepo struct {
	origin string
	work   string
	sha    string
	tag    string
}

func setupEdgeBranchRepo(t *testing.T) edgeBranchRepo {
	t.Helper()
	origin, work := gittest.InitOriginAndWork(t)
	gittest.Commit(t, work, "a.txt")
	gittest.PublishMain(t, work)
	gittest.Git(t, work, "checkout", "--quiet", "-b", edgeTestBranch)
	sha := gittest.Commit(t, work, "b.txt")
	gittest.Git(t, work, "push", "--quiet", "origin", edgeTestBranch)
	t.Chdir(work)
	return edgeBranchRepo{origin: origin, work: work, sha: sha, tag: "dev-build-feat-x-" + sha[:7]}
}

// TestDeployEdge_branch walks the --ref flow against a real origin and a fake
// gh, in the same way as TestDeployEdge.
func TestDeployEdge_branch(t *testing.T) {
	buildSucceeded := deployRun(t, workflowRun{DatabaseID: 101, Status: "completed", Conclusion: "success"})
	deploySucceeded := deployRun(t, workflowRun{DatabaseID: 8, Status: "completed", Conclusion: "success"})
	failed := deployRun(t, workflowRun{Status: "completed", Conclusion: "failure"})

	cases := []struct {
		name         string
		opts         DeployEdgeOptions
		rejectPushes bool
		override     map[string][]deployGHReply
		wantErr      string
		wantCalls    int
		wantPush     bool
		wantTag      string
	}{
		{name: "builds and deploys a branch", wantCalls: 8, wantPush: true},
		{name: "tag override", opts: DeployEdgeOptions{Tag: "dev-build-custom"}, wantCalls: 8, wantPush: true, wantTag: "dev-build-custom"},
		{name: "no-wait-deploy skips the deploy watch", opts: DeployEdgeOptions{NoWaitDeploy: true}, wantCalls: 7, wantPush: true},
		{name: "dry run pushes and dispatches nothing", opts: DeployEdgeOptions{DryRun: true}, wantCalls: 1},
		{name: "ref missing on origin", opts: DeployEdgeOptions{Ref: "user/unpushed"}, wantErr: "origin does not have user/unpushed", wantCalls: 1},
		{name: "invalid tag override", opts: DeployEdgeOptions{Tag: "my-tag"}, wantErr: "must start with dev-build-", wantCalls: 1},
		{name: "rejected push", rejectPushes: true, wantErr: "Failed to push tag", wantCalls: 2},
		{
			name:      "failed build is not deployed",
			override:  map[string][]deployGHReply{"run-view": {failed}},
			wantErr:   "Build did not complete successfully",
			wantCalls: 4,
			wantPush:  true,
		},
		{
			name:      "failed deploy",
			override:  map[string][]deployGHReply{"run-view": {buildSucceeded, failed}},
			wantErr:   "Deploy did not complete successfully",
			wantCalls: 8,
			wantPush:  true,
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			deployIsolateConfigAndAppData(t)
			deploySaveConfig(t, &config.Config{
				Deploy:     config.DeployConfig{TargetRepo: "org/deploys"},
				DeployEdge: config.DeployCommandConfig{TargetWorkflow: "edge.yml"},
			})
			repo := setupEdgeBranchRepo(t)
			if c.rejectPushes {
				gittest.RejectPushes(t, repo.origin)
			}
			runLists := []deployGHReply{
				deployRuns(t, workflowRun{DatabaseID: 100, HeadSHA: "0ld"}),
				deployRuns(t, workflowRun{DatabaseID: 100, HeadSHA: "0ld"}, workflowRun{DatabaseID: 101, HeadSHA: repo.sha}),
				deployRuns(t, workflowRun{DatabaseID: 7}),
				deployRuns(t, workflowRun{DatabaseID: 8}, workflowRun{DatabaseID: 7}),
			}
			replies := map[string][]deployGHReply{
				"run-list":     runLists,
				"run-view":     {buildSucceeded, deploySucceeded},
				"workflow-run": {{}},
			}
			for key, list := range c.override {
				replies[key] = list
			}
			gh := deployNewFakeGH(t, replies)
			deployCaptureOutput(t)

			opts := c.opts
			if opts.Ref == "" {
				opts.Ref = edgeTestBranch
			}
			opts.Yes = true
			err := deployEdge(&opts, deployFastPolling())

			if c.wantErr == "" && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if c.wantErr != "" && (err == nil || !strings.Contains(err.Error(), c.wantErr)) {
				t.Fatalf("expected error containing %q, got %v", c.wantErr, err)
			}
			tag := repo.tag
			if c.wantTag != "" {
				tag = c.wantTag
			}
			fullCalls := []string{
				"--version",
				"run list -R onyx-dot-app/onyx --workflow deployment.yml --limit 10 " + deployRunJSONFields + " --event push --branch " + tag,
				"run list -R onyx-dot-app/onyx --workflow deployment.yml --limit 5 " + deployRunJSONFields + " --event push --branch " + tag,
				"run view 101 -R onyx-dot-app/onyx " + deployRunJSONFields,
				"run list -R org/deploys --workflow edge.yml --limit 10 " + deployRunJSONFields + " --event workflow_dispatch",
				"workflow run edge.yml -R org/deploys -f version_tag=" + tag,
				"run list -R org/deploys --workflow edge.yml --limit 5 " + deployRunJSONFields + " --event workflow_dispatch",
				"run view 8 -R org/deploys " + deployRunJSONFields,
			}
			if calls, want := deployCompactRunListPolls(gh.calls()), fullCalls[:c.wantCalls]; !slices.Equal(calls, want) {
				t.Fatalf("expected gh calls %q, got %q", want, calls)
			}
			pushed := gittest.TagExists(repo.origin, tag)
			if pushed != c.wantPush {
				t.Fatalf("expected %s on origin: %v, got %v", tag, c.wantPush, pushed)
			}
			if pushed {
				if sha := gittest.Git(t, repo.origin, "rev-parse", "refs/tags/"+tag+"^{commit}"); sha != repo.sha {
					t.Fatalf("expected %s at %s, got %s", tag, repo.sha, sha)
				}
			}
			if gittest.TagExists(repo.origin, edgeTagName) {
				t.Fatal("a branch deploy must not move the edge tag")
			}
			if local := gittest.Git(t, repo.work, "tag", "--list", tag); local != "" {
				t.Fatalf("a branch deploy must not create local tag %s", local)
			}
		})
	}
}

func TestDeployEdge_branchReusesATagAlreadyAtTheCommit(t *testing.T) {
	deployIsolateConfigAndAppData(t)
	repo := setupEdgeBranchRepo(t)
	gittest.Git(t, repo.work, "tag", repo.tag, repo.sha)
	gittest.Git(t, repo.work, "push", "--quiet", "origin", repo.tag)
	// The newest run of the tag built another commit, and the run for this
	// commit is not listed yet on the first poll.
	gh := deployNewFakeGH(t, map[string][]deployGHReply{
		"run-list": {
			deployRuns(t, workflowRun{DatabaseID: 101, HeadSHA: "0ld"}),
			deployRuns(t, workflowRun{DatabaseID: 102, HeadSHA: repo.sha}, workflowRun{DatabaseID: 101, HeadSHA: "0ld"}),
			deployRuns(t, workflowRun{DatabaseID: 7}),
			deployRuns(t, workflowRun{DatabaseID: 8}),
		},
		"run-view":     {deployRun(t, workflowRun{DatabaseID: 102, Status: "completed", Conclusion: "success"})},
		"workflow-run": {{}},
	})
	deployCaptureOutput(t)

	opts := &DeployEdgeOptions{Ref: edgeTestBranch, TargetRepo: "org/deploys", TargetWorkflow: "edge.yml", Yes: true, NoWaitDeploy: true}
	if err := deployEdge(opts, deployFastPolling()); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := "run view 102 -R onyx-dot-app/onyx " + deployRunJSONFields
	if calls := gh.calls(); !slices.Contains(calls, want) {
		t.Fatalf("expected the build run at the tag's commit (%q), got %q", want, calls)
	}
}

func TestDeployEdge_branchRejectsATagAtAnotherCommit(t *testing.T) {
	deployIsolateConfigAndAppData(t)
	repo := setupEdgeBranchRepo(t)
	gittest.Git(t, repo.work, "tag", repo.tag, "main")
	gittest.Git(t, repo.work, "push", "--quiet", "origin", repo.tag)
	deployNewFakeGH(t, map[string][]deployGHReply{})
	deployCaptureOutput(t)

	opts := &DeployEdgeOptions{Ref: edgeTestBranch, TargetRepo: "org/deploys", TargetWorkflow: "edge.yml", Yes: true}
	err := deployEdge(opts, deployFastPolling())
	if err == nil || !strings.Contains(err.Error(), "already exists on origin") {
		t.Fatalf("expected an existing-tag error, got %v", err)
	}
}

func TestDeployEdge_tagNeedsABranchRef(t *testing.T) {
	for _, ref := range []string{"", "main", "origin/main"} {
		t.Run(ref, func(t *testing.T) {
			deployIsolateConfigAndAppData(t)
			setupEdgeBranchRepo(t)
			gh := deployNewFakeGH(t, map[string][]deployGHReply{})
			deployCaptureOutput(t)

			opts := &DeployEdgeOptions{Ref: ref, Tag: "dev-build-x", TargetRepo: "org/deploys", TargetWorkflow: "edge.yml", Yes: true}
			err := deployEdge(opts, deployFastPolling())
			if err == nil || !strings.Contains(err.Error(), "--tag needs --ref") {
				t.Fatalf("expected a --tag error, got %v", err)
			}
			if calls := gh.calls(); len(calls) != 1 {
				t.Fatalf("expected only the gh version check, got %q", calls)
			}
		})
	}
}
