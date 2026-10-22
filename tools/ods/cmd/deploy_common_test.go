package cmd

import (
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/config"
)

const deployRunJSONFields = "--json databaseId,status,conclusion,url,event,headBranch"

func TestResolveDeployTarget_prefersFlagsThenSavedConfig(t *testing.T) {
	edge := func(c *config.Config) *string { return &c.DeployEdge.TargetWorkflow }
	wiki := func(c *config.Config) *string { return &c.DeployWiki.TargetWorkflow }
	cases := []struct {
		name         string
		flagRepo     string
		flagWorkflow string
		selector     func(*config.Config) *string
		wantRepo     string
		wantWorkflow string
	}{
		{"saved edge target", "", "", edge, "org/deploys", "edge.yml"},
		{"saved wiki target shares the repo", "", "", wiki, "org/deploys", "wiki.yml"},
		{"flags override both", "org/other", "other.yml", edge, "org/other", "other.yml"},
		{"repo flag keeps the saved workflow", "org/other", "", wiki, "org/other", "wiki.yml"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			path := deployIsolateConfigAndAppData(t)
			deploySaveConfig(t, &config.Config{
				Deploy:     config.DeployConfig{TargetRepo: "org/deploys"},
				DeployEdge: config.DeployCommandConfig{TargetWorkflow: "edge.yml"},
				DeployWiki: config.DeployCommandConfig{TargetWorkflow: "wiki.yml"},
			})
			before, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}

			repo, workflow, err := resolveDeployTarget(c.flagRepo, c.flagWorkflow, c.selector)
			if err != nil {
				t.Fatalf("resolveDeployTarget: %v", err)
			}
			if repo != c.wantRepo || workflow != c.wantWorkflow {
				t.Fatalf("expected %q %q, got %q %q", c.wantRepo, c.wantWorkflow, repo, workflow)
			}
			// Flags are one-off overrides and must not be persisted.
			after, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			if string(after) != string(before) {
				t.Fatalf("config must be unchanged, got %s", after)
			}
		})
	}
}

func TestResolveDeployTarget_failsOnUnreadableConfig(t *testing.T) {
	path := deployIsolateConfigAndAppData(t)
	deployWriteFile(t, path, "{not json")

	_, _, err := resolveDeployTarget("org/repo", "deploy.yml", func(c *config.Config) *string { return &c.DeployEdge.TargetWorkflow })
	if err == nil || !strings.Contains(err.Error(), "Failed to load ods config") {
		t.Fatalf("expected config load error, got %v", err)
	}
}

func TestListWorkflowRuns_passesFiltersAndSortsNewestFirst(t *testing.T) {
	cases := []struct {
		name     string
		event    string
		branch   string
		wantArgs string
	}{
		{"no filters", "", "", "run list -R org/repo --workflow build.yml --limit 7 " + deployRunJSONFields},
		{"event and branch", "push", "edge", "run list -R org/repo --workflow build.yml --limit 7 " + deployRunJSONFields + " --event push --branch edge"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			gh := deployNewFakeGH(t, map[string][]deployGHReply{
				"run-list": {deployRuns(t, workflowRun{DatabaseID: 3}, workflowRun{DatabaseID: 9}, workflowRun{DatabaseID: 5})},
			})

			runs, err := listWorkflowRuns("org/repo", "build.yml", c.event, c.branch, 7)
			if err != nil {
				t.Fatalf("listWorkflowRuns: %v", err)
			}
			var ids []int64
			for _, r := range runs {
				ids = append(ids, r.DatabaseID)
			}
			if !slices.Equal(ids, []int64{9, 5, 3}) {
				t.Fatalf("expected newest-first ids [9 5 3], got %v", ids)
			}
			if got := gh.calls(); !slices.Equal(got, []string{c.wantArgs}) {
				t.Fatalf("expected gh call %q, got %q", c.wantArgs, got)
			}
		})
	}
}

func TestListWorkflowRuns_reportsGhFailures(t *testing.T) {
	cases := []struct {
		name    string
		reply   deployGHReply
		wantErr []string
	}{
		{"gh exits non-zero", deployGHFailure("HTTP 404: workflow not found"), []string{"gh run list failed", "HTTP 404: workflow not found"}},
		{"output is not JSON", deployGHReply{stdout: "oops"}, []string{"failed to parse gh run list output"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			deployNewFakeGH(t, map[string][]deployGHReply{"run-list": {c.reply}})

			_, err := listWorkflowRuns("org/repo", "build.yml", "", "", 5)
			for _, want := range c.wantErr {
				if err == nil || !strings.Contains(err.Error(), want) {
					t.Fatalf("expected error containing %q, got %v", want, err)
				}
			}
		})
	}
}

func TestLatestWorkflowRunID(t *testing.T) {
	cases := []struct {
		name  string
		reply deployGHReply
		want  int64
	}{
		{"highest id among runs", deployRuns(t, workflowRun{DatabaseID: 12}, workflowRun{DatabaseID: 40}, workflowRun{DatabaseID: 31}), 40},
		{"no runs yet", deployRuns(t), 0},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			gh := deployNewFakeGH(t, map[string][]deployGHReply{"run-list": {c.reply}})

			got, err := latestWorkflowRunID("org/repo", "build.yml", "workflow_dispatch", "")
			if err != nil {
				t.Fatalf("latestWorkflowRunID: %v", err)
			}
			if got != c.want {
				t.Fatalf("expected %d, got %d", c.want, got)
			}
			want := "run list -R org/repo --workflow build.yml --limit 10 " + deployRunJSONFields + " --event workflow_dispatch"
			if calls := gh.calls(); !slices.Equal(calls, []string{want}) {
				t.Fatalf("expected gh call %q, got %q", want, calls)
			}
		})
	}

	t.Run("gh failure", func(t *testing.T) {
		deployNewFakeGH(t, map[string][]deployGHReply{"run-list": {deployGHFailure("boom")}})
		if _, err := latestWorkflowRunID("org/repo", "build.yml", "", ""); err == nil || !strings.Contains(err.Error(), "boom") {
			t.Fatalf("expected gh failure, got %v", err)
		}
	})
}

func TestWaitForNewRun_ignoresRunsUpToThePriorID(t *testing.T) {
	gh := deployNewFakeGH(t, map[string][]deployGHReply{
		"run-list": {
			deployRuns(t, workflowRun{DatabaseID: 5}),
			deployRuns(t, workflowRun{DatabaseID: 5}, workflowRun{DatabaseID: 6, URL: "https://run/6"}),
		},
	})

	run, err := waitForNewRun(deployFastPolling(), "org/repo", "build.yml", "push", "edge", 5)
	if err != nil {
		t.Fatalf("waitForNewRun: %v", err)
	}
	if run.DatabaseID != 6 || run.URL != "https://run/6" {
		t.Fatalf("expected run 6, got %+v", run)
	}
	want := "run list -R org/repo --workflow build.yml --limit 5 " + deployRunJSONFields + " --event push --branch edge"
	if calls := gh.calls(); !slices.Equal(calls, []string{want, want}) {
		t.Fatalf("expected two polls of %q, got %q", want, calls)
	}
}

func TestWaitForNewRun_failures(t *testing.T) {
	cases := []struct {
		name    string
		reply   deployGHReply
		wantErr string
	}{
		{"no new run before the timeout", deployRuns(t, workflowRun{DatabaseID: 5}), "no new run appeared within 500ms"},
		{"gh failure", deployGHFailure("rate limited"), "rate limited"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			deployNewFakeGH(t, map[string][]deployGHReply{"run-list": {c.reply}})

			_, err := waitForNewRun(deployFastPolling(), "org/repo", "build.yml", "", "", 5)
			if err == nil || !strings.Contains(err.Error(), c.wantErr) {
				t.Fatalf("expected error containing %q, got %v", c.wantErr, err)
			}
		})
	}
}

func TestWaitForRunCompletion(t *testing.T) {
	inProgress := workflowRun{DatabaseID: 42, Status: "in_progress", URL: "https://run/42"}
	cases := []struct {
		name      string
		replies   []deployGHReply
		timeout   time.Duration
		wantErr   string
		wantPolls int
	}{
		{
			name:      "polls until success",
			replies:   []deployGHReply{deployRun(t, inProgress), deployRun(t, workflowRun{DatabaseID: 42, Status: "completed", Conclusion: "success"})},
			timeout:   time.Minute,
			wantPolls: 2,
		},
		{
			name:      "completed without success",
			replies:   []deployGHReply{deployRun(t, workflowRun{DatabaseID: 42, Status: "completed", Conclusion: "failure", URL: "https://run/42"})},
			timeout:   time.Minute,
			wantErr:   `build run 42 concluded with status "failure" (see https://run/42)`,
			wantPolls: 1,
		},
		{
			name:      "timeout",
			replies:   []deployGHReply{deployRun(t, inProgress)},
			timeout:   0,
			wantErr:   "build run 42 did not complete within 0s (see https://run/42)",
			wantPolls: 1,
		},
		{
			name:      "gh failure",
			replies:   []deployGHReply{deployGHFailure("not found")},
			timeout:   time.Minute,
			wantErr:   "gh run view failed",
			wantPolls: 1,
		},
		{
			name:      "output is not JSON",
			replies:   []deployGHReply{{stdout: "<html>"}},
			timeout:   time.Minute,
			wantErr:   "failed to parse gh run view output",
			wantPolls: 1,
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			gh := deployNewFakeGH(t, map[string][]deployGHReply{"run-view": c.replies})

			err := waitForRunCompletion(deployFastPolling(), "org/repo", 42, c.timeout, "build")
			if c.wantErr == "" && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if c.wantErr != "" && (err == nil || !strings.Contains(err.Error(), c.wantErr)) {
				t.Fatalf("expected error containing %q, got %v", c.wantErr, err)
			}
			calls := gh.calls()
			if len(calls) != c.wantPolls {
				t.Fatalf("expected %d polls, got %q", c.wantPolls, calls)
			}
			if want := "run view 42 -R org/repo " + deployRunJSONFields; calls[0] != want {
				t.Fatalf("expected %q, got %q", want, calls[0])
			}
		})
	}
}

func TestDispatchWorkflow(t *testing.T) {
	cases := []struct {
		name     string
		inputs   map[string]string
		wantArgs string
	}{
		{"no inputs", nil, "workflow run deploy.yml -R org/repo"},
		{"inputs become fields", map[string]string{"version_tag": "edge"}, "workflow run deploy.yml -R org/repo -f version_tag=edge"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			gh := deployNewFakeGH(t, map[string][]deployGHReply{"workflow-run": {{}}})

			if err := dispatchWorkflow("org/repo", "deploy.yml", c.inputs); err != nil {
				t.Fatalf("dispatchWorkflow: %v", err)
			}
			if calls := gh.calls(); !slices.Equal(calls, []string{c.wantArgs}) {
				t.Fatalf("expected gh call %q, got %q", c.wantArgs, calls)
			}
		})
	}

	t.Run("failure includes gh output", func(t *testing.T) {
		deployNewFakeGH(t, map[string][]deployGHReply{"workflow-run": {deployGHFailure("HTTP 403: must have admin rights")}})

		err := dispatchWorkflow("org/repo", "deploy.yml", nil)
		if err == nil || !strings.Contains(err.Error(), "gh workflow run failed") || !strings.Contains(err.Error(), "must have admin rights") {
			t.Fatalf("expected dispatch failure with gh output, got %v", err)
		}
	})
}

func TestAnnounceDeploymentRun_printsTheTagsRunURL(t *testing.T) {
	gh := deployNewFakeGH(t, map[string][]deployGHReply{
		"run-list": {deployRuns(t, workflowRun{DatabaseID: 77, URL: "https://github.com/onyx-dot-app/onyx/actions/runs/77"})},
	})
	out := deployCaptureOutput(t)

	announceDeploymentRun(deployFastPolling(), "v4.7.0-beta.1")

	if got := out.printed(t); got != "https://github.com/onyx-dot-app/onyx/actions/runs/77\n" {
		t.Fatalf("expected the run URL on stdout, got %q", got)
	}
	want := "run list -R onyx-dot-app/onyx --workflow deployment.yml --limit 5 " + deployRunJSONFields + " --event push --branch v4.7.0-beta.1"
	if calls := gh.calls(); !slices.Equal(calls, []string{want}) {
		t.Fatalf("expected gh call %q, got %q", want, calls)
	}
}

func TestAnnounceDeploymentRun_onlyWarnsWhenTheLookupFails(t *testing.T) {
	deployNewFakeGH(t, map[string][]deployGHReply{"run-list": {deployGHFailure("gh auth required")}})
	out := deployCaptureOutput(t)

	announceDeploymentRun(deployFastPolling(), "v4.7.0-beta.1")

	if got := out.printed(t); got != "" {
		t.Fatalf("expected nothing on stdout, got %q", got)
	}
	logs := out.logs.String()
	for _, want := range []string{"gh auth required", "https://github.com/onyx-dot-app/onyx/actions/workflows/deployment.yml"} {
		if !strings.Contains(logs, want) {
			t.Fatalf("expected logs to contain %q, got %q", want, logs)
		}
	}
}

// deployIsolateConfigAndAppData also points APPDATA at the temp config dir,
// because paths.ConfigDir reads APPDATA on Windows.
func deployIsolateConfigAndAppData(t *testing.T) string {
	t.Helper()
	path := deployIsolateConfig(t)
	t.Setenv("APPDATA", filepath.Dir(filepath.Dir(path)))
	return path
}
