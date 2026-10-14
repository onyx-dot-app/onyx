package cmd

import (
	"slices"
	"strings"
	"testing"
)

const (
	deployCloudTag   = "v4.7.0-cloud.3"
	deployCloudRunID = 900
	deployRunURL     = "https://github.com/onyx-dot-app/onyx/actions/runs/900"
	deployPRURL      = "https://github.com/onyx-dot-app/onyx-infra/pull/12"
)

func deployPRs(prs string) deployGHReply {
	return deployGHReply{stdout: prs}
}

func TestWatchCloudRelease(t *testing.T) {
	cloudRun := workflowRun{DatabaseID: deployCloudRunID, URL: deployRunURL}
	succeeded := workflowRun{DatabaseID: deployCloudRunID, Status: "completed", Conclusion: "success", URL: deployRunURL}
	failed := workflowRun{DatabaseID: deployCloudRunID, Status: "completed", Conclusion: "failure", URL: deployRunURL}
	openPR := deployPRs(`[{"number":12,"state":"OPEN","url":"` + deployPRURL + `"}]`)
	noPR := deployPRs(`[]`)
	dispatched := deployGHReply{stdout: `{"jobs":[{"name":"build","conclusion":"failure"},{"name":"dispatch-cloud-deployment","conclusion":"success"}]}`}

	cases := []struct {
		name        string
		replies     map[string][]deployGHReply
		wantErr     string
		wantStdout  string
		wantLogs    []string
		wantPRPolls int
		// pollsUntilTimeout means the PR poll count depends on timing, so only
		// at least one poll is required.
		pollsUntilTimeout bool
	}{
		{
			name: "build succeeds and the bump PR opens after a poll",
			replies: map[string][]deployGHReply{
				"run-list": {deployRuns(t, cloudRun)},
				"run-view": {deployRun(t, succeeded)},
				"pr-list":  {noPR, openPR},
			},
			wantStdout:  deployRunURL + "\n" + deployPRURL + "\n",
			wantLogs:    []string{"Bump PR ready for approval"},
			wantPRPolls: 2,
		},
		{
			name: "build succeeds but no bump PR appears",
			replies: map[string][]deployGHReply{
				"run-list": {deployRuns(t, cloudRun)},
				"run-view": {deployRun(t, succeeded)},
				"pr-list":  {noPR},
			},
			wantErr:           "no bump PR for v4.7.0-cloud.3 appeared within 500ms; check https://github.com/onyx-dot-app/onyx-infra/actions/workflows/bump-cloud-version.yml",
			wantStdout:        deployRunURL + "\n",
			pollsUntilTimeout: true,
		},
		{
			name: "re-attach finds an already merged PR",
			replies: map[string][]deployGHReply{
				"run-list": {deployRuns(t, cloudRun)},
				"run-view": {deployRun(t, succeeded)},
				"pr-list":  {deployPRs(`[{"number":12,"state":"MERGED","url":"` + deployPRURL + `"}]`)},
			},
			wantStdout:  deployRunURL + "\n" + deployPRURL + "\n",
			wantLogs:    []string{"Bump PR already merged"},
			wantPRPolls: 1,
		},
		{
			name: "failed build whose dispatch succeeded still reports the PR",
			replies: map[string][]deployGHReply{
				"run-list": {deployRuns(t, cloudRun)},
				"run-view": {deployRun(t, failed)},
				"run-jobs": {dispatched},
				"pr-list":  {deployPRs(`[{"number":12,"state":"CLOSED","url":"` + deployPRURL + `"}]`)},
			},
			wantStdout:  deployRunURL + "\n" + deployPRURL + "\n",
			wantLogs:    []string{"review it before approving", "Bump PR was closed without merging"},
			wantPRPolls: 1,
		},
		{
			name: "failed build without a dispatch does not wait for a PR",
			replies: map[string][]deployGHReply{
				"run-list": {deployRuns(t, cloudRun)},
				"run-view": {deployRun(t, failed)},
				"run-jobs": {{stdout: `{"jobs":[{"name":"dispatch-cloud-deployment","conclusion":"skipped"}]}`}},
			},
			wantErr:    `build run 900 concluded with status "failure"`,
			wantStdout: deployRunURL + "\n",
			wantLogs:   []string{"a bump PR is not expected"},
		},
		{
			name: "failed build whose dispatch job is missing",
			replies: map[string][]deployGHReply{
				"run-list": {deployRuns(t, cloudRun)},
				"run-view": {deployRun(t, failed)},
				"run-jobs": {{stdout: `{"jobs":[{"name":"build","conclusion":"failure"}]}`}},
			},
			wantErr:    `build run 900 concluded with status "failure"`,
			wantStdout: deployRunURL + "\n",
			wantLogs:   []string{"a bump PR is not expected"},
		},
		{
			name: "failed build whose jobs cannot be read",
			replies: map[string][]deployGHReply{
				"run-list": {deployRuns(t, cloudRun)},
				"run-view": {deployRun(t, failed)},
				"run-jobs": {deployGHFailure("HTTP 502")},
			},
			wantErr:    `build run 900 concluded with status "failure"`,
			wantStdout: deployRunURL + "\n",
			wantLogs:   []string{"Could not check the bump dispatch job", "HTTP 502"},
		},
		{
			name: "failed build whose PR lookup fails",
			replies: map[string][]deployGHReply{
				"run-list": {deployRuns(t, cloudRun)},
				"run-view": {deployRun(t, failed)},
				"run-jobs": {dispatched},
				"pr-list":  {deployGHFailure("HTTP 401")},
			},
			wantErr:     `build run 900 concluded with status "failure"`,
			wantStdout:  deployRunURL + "\n",
			wantLogs:    []string{"Bump PR lookup failed", "HTTP 401"},
			wantPRPolls: 1,
		},
		{
			name: "deployment run lookup fails",
			replies: map[string][]deployGHReply{
				"run-list": {deployGHFailure("HTTP 500")},
			},
			wantErr: "could not find the deployment run for v4.7.0-cloud.3 (see https://github.com/onyx-dot-app/onyx/actions/workflows/deployment.yml)",
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			gh := deployNewFakeGH(t, c.replies)
			out := deployCaptureOutput(t)

			err := watchCloudRelease(deployFastPolling(), deployCloudTag)

			if c.wantErr == "" && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if c.wantErr != "" && (err == nil || !strings.Contains(err.Error(), c.wantErr)) {
				t.Fatalf("expected error containing %q, got %v", c.wantErr, err)
			}
			if got := out.printed(t); got != c.wantStdout {
				t.Fatalf("expected stdout %q, got %q", c.wantStdout, got)
			}
			logs := out.logs.String()
			for _, want := range c.wantLogs {
				if !strings.Contains(logs, want) {
					t.Fatalf("expected logs to contain %q, got %q", want, logs)
				}
			}
			deployAssertBumpPRPolls(t, gh.calls(), c.wantPRPolls, c.pollsUntilTimeout)
		})
	}
}

// deployAssertBumpPRPolls checks the watcher looked up the tag's bump branch in
// the infra repo, and did so wantPolls times. With untilTimeout it only
// requires at least one poll.
func deployAssertBumpPRPolls(t *testing.T, calls []string, wantPolls int, untilTimeout bool) {
	t.Helper()
	want := "pr list -R onyx-dot-app/onyx-infra --head bump-version/" + deployCloudTag + " --state all --json number,state,url"
	var got int
	for _, call := range calls {
		if strings.HasPrefix(call, "pr list") {
			if call != want {
				t.Fatalf("expected %q, got %q", want, call)
			}
			got++
		}
	}
	if untilTimeout {
		if got == 0 {
			t.Fatalf("expected bump PR polls until the timeout, got none in %q", calls)
		}
		return
	}
	if got != wantPolls {
		t.Fatalf("expected %d bump PR polls, got %d in %q", wantPolls, got, calls)
	}
}

func TestWatchCloudRelease_readsTheTagsRunAndJobs(t *testing.T) {
	gh := deployNewFakeGH(t, map[string][]deployGHReply{
		"run-list": {deployRuns(t, workflowRun{DatabaseID: deployCloudRunID, URL: deployRunURL})},
		"run-view": {deployRun(t, workflowRun{DatabaseID: deployCloudRunID, Status: "completed", Conclusion: "cancelled"})},
		"run-jobs": {{stdout: `{"jobs":[]}`}},
	})
	deployCaptureOutput(t)

	if err := watchCloudRelease(deployFastPolling(), deployCloudTag); err == nil {
		t.Fatal("expected the cancelled build to fail the watch")
	}

	want := []string{
		"run list -R onyx-dot-app/onyx --workflow deployment.yml --limit 5 " + deployRunJSONFields + " --event push --branch " + deployCloudTag,
		"run view 900 -R onyx-dot-app/onyx " + deployRunJSONFields,
		"run view 900 -R onyx-dot-app/onyx --json jobs",
	}
	if calls := gh.calls(); !slices.Equal(calls, want) {
		t.Fatalf("expected gh calls %q, got %q", want, calls)
	}
}
