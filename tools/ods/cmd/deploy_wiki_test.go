package cmd

import (
	"regexp"
	"slices"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/config"
)

// TestDeployWiki checks the gh calls of each wiki flow and that a failing step
// stops every later step. Repeated discovery polls are collapsed before
// comparing. The expected calls use a placeholder for the date-based tag, which
// is replaced by the tag the command reports.
func TestDeployWiki(t *testing.T) {
	const versionTag = "<version-tag>"
	reportedTag := regexp.MustCompile(`Target version tag: (nightly-latest-\d{8})\b`)
	checkGH := "--version"
	build := []string{
		"run list -R onyx-dot-app/agent-wiki --workflow nightly-build.yml --limit 10 " + deployRunJSONFields + " --event workflow_dispatch",
		"workflow run nightly-build.yml -R onyx-dot-app/agent-wiki",
		"run list -R onyx-dot-app/agent-wiki --workflow nightly-build.yml --limit 5 " + deployRunJSONFields + " --event workflow_dispatch",
		"run view 51 -R onyx-dot-app/agent-wiki " + deployRunJSONFields,
	}
	deploy := []string{
		"run list -R org/deploys --workflow wiki.yml --limit 10 " + deployRunJSONFields + " --event workflow_dispatch",
		"workflow run wiki.yml -R org/deploys -f version_tag=" + versionTag,
		"run list -R org/deploys --workflow wiki.yml --limit 5 " + deployRunJSONFields + " --event workflow_dispatch",
		"run view 8 -R org/deploys " + deployRunJSONFields,
	}
	fullCalls := slices.Concat([]string{checkGH}, build, deploy)

	buildLists := []deployGHReply{deployRuns(t, workflowRun{DatabaseID: 50}), deployRuns(t, workflowRun{DatabaseID: 51})}
	deployLists := []deployGHReply{deployRuns(t, workflowRun{DatabaseID: 7}), deployRuns(t, workflowRun{DatabaseID: 8})}
	buildSucceeded := deployRun(t, workflowRun{DatabaseID: 51, Status: "completed", Conclusion: "success"})
	deploySucceeded := deployRun(t, workflowRun{DatabaseID: 8, Status: "completed", Conclusion: "success"})
	failed := deployRun(t, workflowRun{Status: "completed", Conclusion: "failure"})
	fullReplies := map[string][]deployGHReply{
		"run-list":     slices.Concat(buildLists, deployLists),
		"run-view":     {buildSucceeded, deploySucceeded},
		"workflow-run": {{}},
	}

	cases := []struct {
		name      string
		opts      DeployWikiOptions
		replies   map[string][]deployGHReply
		wantErr   string
		wantCalls []string
	}{
		{name: "builds then deploys today's tag", replies: fullReplies, wantCalls: fullCalls},
		{
			name:      "no-build and no-wait-deploy only dispatch the deploy",
			opts:      DeployWikiOptions{NoBuild: true, NoWaitDeploy: true},
			replies:   map[string][]deployGHReply{"run-list": deployLists, "workflow-run": {{}}},
			wantCalls: slices.Concat([]string{checkGH}, deploy[:3]),
		},
		{name: "dry run dispatches nothing", opts: DeployWikiOptions{DryRun: true}, replies: fullReplies, wantCalls: []string{checkGH}},
		{
			name:      "prior build lookup fails",
			replies:   map[string][]deployGHReply{"run-list": {deployGHFailure("HTTP 500")}},
			wantErr:   "Failed to query existing build runs",
			wantCalls: []string{checkGH, build[0]},
		},
		{
			name:      "build dispatch fails",
			replies:   map[string][]deployGHReply{"run-list": buildLists, "workflow-run": {deployGHFailure("HTTP 403")}},
			wantErr:   "Failed to dispatch build workflow",
			wantCalls: slices.Concat([]string{checkGH}, build[:2]),
		},
		{
			name:      "build run never appears",
			replies:   map[string][]deployGHReply{"run-list": buildLists[:1], "workflow-run": {{}}},
			wantErr:   "Failed to find triggered build run",
			wantCalls: slices.Concat([]string{checkGH}, build[:3]),
		},
		{
			name:      "failed build is not deployed",
			replies:   map[string][]deployGHReply{"run-list": buildLists, "run-view": {failed}, "workflow-run": {{}}},
			wantErr:   "Build did not complete successfully",
			wantCalls: slices.Concat([]string{checkGH}, build),
		},
		{
			name:      "prior deploy lookup fails",
			opts:      DeployWikiOptions{NoBuild: true},
			replies:   map[string][]deployGHReply{"run-list": {deployGHFailure("HTTP 500")}},
			wantErr:   "Failed to query existing deploy runs",
			wantCalls: []string{checkGH, deploy[0]},
		},
		{
			name:      "deploy dispatch fails",
			opts:      DeployWikiOptions{NoBuild: true},
			replies:   map[string][]deployGHReply{"run-list": deployLists, "workflow-run": {deployGHFailure("HTTP 403")}},
			wantErr:   "Failed to dispatch deploy workflow",
			wantCalls: slices.Concat([]string{checkGH}, deploy[:2]),
		},
		{
			name:      "deploy run never appears",
			opts:      DeployWikiOptions{NoBuild: true},
			replies:   map[string][]deployGHReply{"run-list": deployLists[:1], "workflow-run": {{}}},
			wantErr:   "Failed to find dispatched deploy run",
			wantCalls: slices.Concat([]string{checkGH}, deploy[:3]),
		},
		{
			name:      "failed deploy",
			opts:      DeployWikiOptions{NoBuild: true},
			replies:   map[string][]deployGHReply{"run-list": deployLists, "run-view": {failed}, "workflow-run": {{}}},
			wantErr:   "Deploy did not complete successfully",
			wantCalls: slices.Concat([]string{checkGH}, deploy),
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			deployIsolateConfigAndAppData(t)
			deploySaveConfig(t, &config.Config{
				Deploy:     config.DeployConfig{TargetRepo: "org/deploys"},
				DeployWiki: config.DeployCommandConfig{TargetWorkflow: "wiki.yml"},
			})
			gh := deployNewFakeGH(t, c.replies)
			out := deployCaptureOutput(t)

			opts := c.opts
			opts.Yes = true
			err := deployWiki(&opts, deployFastPolling())

			if c.wantErr == "" && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if c.wantErr != "" && (err == nil || !strings.Contains(err.Error(), c.wantErr)) {
				t.Fatalf("expected error containing %q, got %v", c.wantErr, err)
			}
			match := reportedTag.FindStringSubmatch(out.logs.String())
			if match == nil {
				t.Fatalf("expected a reported nightly-latest-YYYYMMDD tag, got logs %q", out.logs.String())
			}
			wantCalls := make([]string, len(c.wantCalls))
			for i, call := range c.wantCalls {
				wantCalls[i] = strings.ReplaceAll(call, versionTag, match[1])
			}
			if calls := deployCompactRunListPolls(gh.calls()); !slices.Equal(calls, wantCalls) {
				t.Fatalf("expected gh calls %q, got %q", wantCalls, calls)
			}
		})
	}
}

func TestDeployWiki_unreadableConfigStopsBeforeGitHub(t *testing.T) {
	path := deployIsolateConfigAndAppData(t)
	deployWriteFile(t, path, "[]")
	gh := deployNewFakeGH(t, nil)
	deployCaptureOutput(t)

	err := deployWiki(&DeployWikiOptions{Yes: true}, deployFastPolling())
	if err == nil || !strings.Contains(err.Error(), "Failed to load ods config") {
		t.Fatalf("expected config load error, got %v", err)
	}
	if calls := gh.calls(); !slices.Equal(calls, []string{"--version"}) {
		t.Fatalf("expected only the gh install check, got %q", calls)
	}
}
