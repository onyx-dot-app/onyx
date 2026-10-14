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
