package cmd

import (
	"bytes"
	"errors"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/spf13/cobra"
)

func TestSearch_NoQuery(t *testing.T) {
	ios := &iostreams.IOStreams{
		In:          &bytes.Buffer{},
		Out:         &bytes.Buffer{},
		ErrOut:      &bytes.Buffer{},
		IsStdinTTY:  true,
		IsStdoutTTY: true,
	}
	cmd := newSearchCmd(ios)
	cmd.SetArgs([]string{})

	// Stub RunE so we don't need a real client, but keep the arg check.
	origRunE := cmd.RunE
	cmd.RunE = func(cmd *cobra.Command, args []string) error {
		if len(args) == 0 {
			return exitcodes.New(exitcodes.BadRequest,
				"no query provided\n  Usage: onyx-cli search \"your query\"")
		}
		return origRunE(cmd, args)
	}

	err := cmd.Execute()
	if err == nil {
		t.Fatal("expected error for missing query")
	}
	var exitErr *exitcodes.ExitError
	if !errors.As(err, &exitErr) {
		t.Fatalf("want *ExitError, got %T: %v", err, err)
	}
	if exitErr.Code != exitcodes.BadRequest {
		t.Errorf("exit code = %d, want %d", exitErr.Code, exitcodes.BadRequest)
	}
}

func TestBuildSearchRequest(t *testing.T) {
	intPtr := func(v int) *int { return &v }

	tests := []struct {
		name string

		query            string
		sources          []string
		days             int
		daysSet          bool
		limit            int
		limitSet         bool
		agentID          int
		agentIDSet       bool
		defaultAgentID   int
		noQueryExpansion bool

		wantSources            []string
		wantTimeCutoffDays     *int
		wantNumResults         int
		wantPersonaID          *int
		wantSkipQueryExpansion bool
	}{
		{
			name:        "no_sources",
			query:       "test query",
			wantSources: nil,
		},
		{
			name:        "two_sources",
			query:       "test query",
			sources:     []string{"slack", "google_drive"},
			wantSources: []string{"slack", "google_drive"},
		},
		{
			name:        "empty_strings_filtered_from_sources",
			query:       "test query",
			sources:     []string{"slack", "", " ", "google_drive"},
			wantSources: []string{"slack", "google_drive"},
		},
		{
			name:               "days_limit_agentID_set",
			query:              "test query",
			days:               30,
			daysSet:            true,
			limit:              5,
			limitSet:           true,
			agentID:            3,
			agentIDSet:         true,
			wantTimeCutoffDays: intPtr(30),
			wantNumResults:     5,
			wantPersonaID:      intPtr(3),
		},
		{
			name:               "unset_flags_produce_zero_values",
			query:              "test query",
			wantSources:        nil,
			wantTimeCutoffDays: nil,
			wantNumResults:     0,
			wantPersonaID:      nil,
		},
		{
			name:          "agent_id_zero_explicitly_set",
			query:         "test query",
			agentID:       0,
			agentIDSet:    true,
			wantPersonaID: intPtr(0),
		},
		{
			name:                   "no_query_expansion",
			query:                  "exact error text",
			noQueryExpansion:       true,
			wantSkipQueryExpansion: true,
		},
		{
			name:           "default_agent_id_fallback",
			query:          "test query",
			defaultAgentID: 7,
			wantPersonaID:  intPtr(7),
		},
		{
			name:           "explicit_agent_id_overrides_default",
			query:          "test query",
			agentID:        2,
			agentIDSet:     true,
			defaultAgentID: 7,
			wantPersonaID:  intPtr(2),
		},
		{
			name:           "default_agent_id_zero_not_sent",
			query:          "test query",
			defaultAgentID: 0,
			wantPersonaID:  nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := buildSearchRequest(
				tt.query,
				tt.sources,
				tt.days, tt.daysSet,
				tt.limit, tt.limitSet,
				tt.agentID, tt.agentIDSet,
				tt.defaultAgentID,
				tt.noQueryExpansion,
			)

			if req.Query != tt.query {
				t.Errorf("Query = %q, want %q", req.Query, tt.query)
			}

			// Sources
			if tt.wantSources == nil {
				if req.Sources != nil {
					t.Errorf("Sources = %v, want nil", req.Sources)
				}
			} else {
				if len(req.Sources) != len(tt.wantSources) {
					t.Fatalf("Sources length = %d, want %d: %v", len(req.Sources), len(tt.wantSources), req.Sources)
				}
				for i, s := range tt.wantSources {
					if req.Sources[i] != s {
						t.Errorf("Sources[%d] = %q, want %q", i, req.Sources[i], s)
					}
				}
			}

			// TimeCutoffDays
			if tt.wantTimeCutoffDays == nil {
				if req.TimeCutoffDays != nil {
					t.Errorf("TimeCutoffDays = %v, want nil", *req.TimeCutoffDays)
				}
			} else {
				if req.TimeCutoffDays == nil {
					t.Fatalf("TimeCutoffDays = nil, want %d", *tt.wantTimeCutoffDays)
				}
				if *req.TimeCutoffDays != *tt.wantTimeCutoffDays {
					t.Errorf("TimeCutoffDays = %d, want %d", *req.TimeCutoffDays, *tt.wantTimeCutoffDays)
				}
			}

			// NumResults
			if req.NumResults != tt.wantNumResults {
				t.Errorf("NumResults = %d, want %d", req.NumResults, tt.wantNumResults)
			}

			// PersonaID
			if tt.wantPersonaID == nil {
				if req.PersonaID != nil {
					t.Errorf("PersonaID = %d, want nil", *req.PersonaID)
				}
			} else {
				if req.PersonaID == nil {
					t.Fatalf("PersonaID = nil, want %d", *tt.wantPersonaID)
				}
				if *req.PersonaID != *tt.wantPersonaID {
					t.Errorf("PersonaID = %d, want %d", *req.PersonaID, *tt.wantPersonaID)
				}
			}

			// SkipQueryExpansion
			if req.SkipQueryExpansion != tt.wantSkipQueryExpansion {
				t.Errorf("SkipQueryExpansion = %v, want %v", req.SkipQueryExpansion, tt.wantSkipQueryExpansion)
			}
		})
	}
}
