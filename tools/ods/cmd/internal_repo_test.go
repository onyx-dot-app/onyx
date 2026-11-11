package cmd

import (
	"slices"
	"strings"
	"testing"
)

func TestResolveInternalRepo(t *testing.T) {
	const env = "ODS_TEST_INTERNAL_REPO"
	cases := []struct {
		name      string
		envValue  string
		replies   map[string][]deployGHReply
		want      string
		wantErr   string
		wantCalls []string
	}{
		{
			name:     "the env var wins without a gh call",
			envValue: "env-org/env-repo",
			want:     "env-org/env-repo",
		},
		{
			name:      "falls back to the onyx repo variable",
			replies:   map[string][]deployGHReply{"variable-get": {{stdout: deployTestInternalRepo + "\n"}}},
			want:      deployTestInternalRepo,
			wantCalls: []string{"variable get CLOUD_DEPLOYMENT_REPO -R onyx-dot-app/onyx"},
		},
		{
			name:      "a failed lookup names the env var",
			replies:   map[string][]deployGHReply{"variable-get": {deployGHFailure("HTTP 403")}},
			wantErr:   "Set " + env + " to the internal infra repo",
			wantCalls: []string{"variable get CLOUD_DEPLOYMENT_REPO -R onyx-dot-app/onyx"},
		},
		{
			name:      "an empty variable is an error",
			replies:   map[string][]deployGHReply{"variable-get": {{stdout: "\n"}}},
			wantErr:   "variable of onyx-dot-app/onyx is empty",
			wantCalls: []string{"variable get CLOUD_DEPLOYMENT_REPO -R onyx-dot-app/onyx"},
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			// Precondition.
			gh := deployNewFakeGH(t, c.replies)
			t.Setenv(env, c.envValue)

			// Under test.
			got, err := resolveInternalRepo(env)

			// Postcondition.
			if c.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), c.wantErr) {
					t.Fatalf("expected an error containing %q, got %v", c.wantErr, err)
				}
			} else if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != c.want {
				t.Errorf("expected %q, got %q", c.want, got)
			}
			if calls := gh.calls(); !slices.Equal(calls, c.wantCalls) {
				t.Errorf("expected gh calls %q, got %q", c.wantCalls, calls)
			}
		})
	}
}
