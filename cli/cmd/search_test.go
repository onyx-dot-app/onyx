package cmd

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"
	"unicode/utf8"

	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
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
		agentID          int
		agentIDSet       bool
		defaultAgentID   int
		noQueryExpansion bool

		wantSources []string
		// wantDaysAgo is the expected "N days ago" cutoff; buildSearchRequest
		// converts this to an ISO timestamp ~N*24h before now, asserted
		// within a 10s tolerance below.
		wantDaysAgo            *int
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
			name:          "days_agentID_set",
			query:         "test query",
			days:          30,
			daysSet:       true,
			agentID:       3,
			agentIDSet:    true,
			wantDaysAgo:   intPtr(30),
			wantPersonaID: intPtr(3),
		},
		{
			name:          "unset_flags_produce_zero_values",
			query:         "test query",
			wantSources:   nil,
			wantDaysAgo:   nil,
			wantPersonaID: nil,
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
			req := buildSearchRequest(searchFlags{
				query:            tt.query,
				sources:          tt.sources,
				days:             tt.days,
				daysSet:          tt.daysSet,
				agentID:          tt.agentID,
				agentIDSet:       tt.agentIDSet,
				defaultAgentID:   tt.defaultAgentID,
				noQueryExpansion: tt.noQueryExpansion,
			})

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

			// TimeCutoff: when days is set, expect an ISO timestamp roughly
			// `days` days before now.
			if tt.wantDaysAgo == nil {
				if req.TimeCutoff != nil {
					t.Errorf("TimeCutoff = %v, want nil", *req.TimeCutoff)
				}
			} else {
				if req.TimeCutoff == nil {
					t.Fatalf("TimeCutoff = nil, want ~%d days ago", *tt.wantDaysAgo)
				}
				parsed, err := time.Parse(time.RFC3339, *req.TimeCutoff)
				if err != nil {
					t.Fatalf("TimeCutoff %q is not RFC3339: %v", *req.TimeCutoff, err)
				}
				expected := time.Now().UTC().Add(-time.Duration(*tt.wantDaysAgo) * 24 * time.Hour)
				delta := parsed.Sub(expected)
				if delta < -10*time.Second || delta > 10*time.Second {
					t.Errorf("TimeCutoff = %v (off by %v), want ~%v", parsed, delta, expected)
				}
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

func TestToSearchOutput(t *testing.T) {
	intPtr := func(v int) *int { return &v }
	strPtr := func(v string) *string { return &v }

	resp := models.SearchResponse{
		Results: []models.SearchResult{
			{
				CitationID: intPtr(1),
				Title:      "Onboarding guide",
				Content:    "Full chunk text for doc A — multiple paragraphs.",
				Link:       strPtr("https://docs.example.com/a"),
				SourceType: "google_drive",
				UpdatedAt:  strPtr("2026-01-15T09:00:00Z"),
			},
			{
				// Defensive case: the API contract guarantees every result is
				// LLM-selected, but we still verify the projection handles
				// nullable fields (CitationID, Link, UpdatedAt) cleanly when
				// they happen to be nil.
				CitationID: nil,
				Title:      "Stale draft",
				Content:    "Blurb for doc B",
				Link:       nil,
				SourceType: "confluence",
				UpdatedAt:  nil,
			},
		},
	}

	out := toSearchOutput(resp)

	if len(out.Results) != 2 {
		t.Fatalf("Results length = %d, want 2", len(out.Results))
	}

	// Fully-populated result: every field should round-trip.
	selected := out.Results[0]
	if selected.Title != "Onboarding guide" {
		t.Errorf("Results[0].Title = %q, want %q", selected.Title, "Onboarding guide")
	}
	if selected.Content != "Full chunk text for doc A — multiple paragraphs." {
		t.Errorf("Results[0].Content = %q, want full chunk", selected.Content)
	}
	if selected.URL == nil || *selected.URL != "https://docs.example.com/a" {
		t.Errorf("Results[0].URL = %v, want https://docs.example.com/a", selected.URL)
	}
	if selected.SourceType != "google_drive" {
		t.Errorf("Results[0].SourceType = %q, want google_drive", selected.SourceType)
	}
	if selected.UpdatedAt == nil || *selected.UpdatedAt != "2026-01-15T09:00:00Z" {
		t.Errorf("Results[0].UpdatedAt = %v, want 2026-01-15T09:00:00Z", selected.UpdatedAt)
	}

	// Nullable fields should round-trip as nil without panic.
	withNils := out.Results[1]
	if withNils.Title != "Stale draft" {
		t.Errorf("Results[1].Title = %q, want Stale draft", withNils.Title)
	}
	if withNils.Content != "Blurb for doc B" {
		t.Errorf("Results[1].Content = %q, want %q", withNils.Content, "Blurb for doc B")
	}
	if withNils.URL != nil {
		t.Errorf("Results[1].URL = %v, want nil", withNils.URL)
	}
	if withNils.SourceType != "confluence" {
		t.Errorf("Results[1].SourceType = %q, want confluence", withNils.SourceType)
	}
	if withNils.UpdatedAt != nil {
		t.Errorf("Results[1].UpdatedAt = %v, want nil", withNils.UpdatedAt)
	}
}

// makeSearchResults builds n results with roughly equal-size content chunks.
func makeSearchResults(n int, contentSize int) []searchOutputResult {
	results := make([]searchOutputResult, 0, n)
	for i := 0; i < n; i++ {
		results = append(results, searchOutputResult{
			Title:      fmt.Sprintf("Doc %d", i),
			SourceType: "confluence",
			Content:    strings.Repeat("x", contentSize),
		})
	}
	return results
}

func TestWriteSearchJSON_UnderLimit(t *testing.T) {
	var out, errOut bytes.Buffer
	ios := &iostreams.IOStreams{Out: &out, ErrOut: &errOut}
	output := searchOutput{Results: makeSearchResults(2, 100)}

	if err := writeSearchJSON(ios, output, 50000); err != nil {
		t.Fatalf("writeSearchJSON failed: %v", err)
	}

	var parsed searchOutput
	if err := json.Unmarshal(out.Bytes(), &parsed); err != nil {
		t.Fatalf("stdout is not valid JSON: %v", err)
	}
	if parsed.Truncation != nil {
		t.Fatal("under-limit output should not carry truncation metadata")
	}
	if len(parsed.Results) != 2 {
		t.Fatalf("Results length = %d, want 2", len(parsed.Results))
	}
	if errOut.Len() != 0 {
		t.Fatalf("expected empty stderr, got %q", errOut.String())
	}
}

func TestWriteSearchJSON_OverLimitIsValidJSON(t *testing.T) {
	var out, errOut bytes.Buffer
	ios := &iostreams.IOStreams{Out: &out, ErrOut: &errOut}
	output := searchOutput{Results: makeSearchResults(20, 500)}

	fullData, err := json.MarshalIndent(output, "", "  ")
	if err != nil {
		t.Fatalf("marshal failed: %v", err)
	}
	limit := 3000
	if len(fullData) <= limit {
		t.Fatalf("test setup: payload (%d bytes) must exceed limit %d", len(fullData), limit)
	}

	if err := writeSearchJSON(ios, output, limit); err != nil {
		t.Fatalf("writeSearchJSON failed: %v", err)
	}

	var parsed searchOutput
	if err := json.Unmarshal(out.Bytes(), &parsed); err != nil {
		t.Fatalf("stdout is not valid JSON: %v\n%s", err, out.String())
	}
	if len(out.Bytes()) > limit+1 { // +1 for trailing newline
		t.Fatalf("stdout is %d bytes, want <= %d", out.Len(), limit+1)
	}

	tr := parsed.Truncation
	if tr == nil {
		t.Fatal("expected truncation metadata")
	}
	t.Cleanup(func() { _ = os.Remove(tr.FullResponsePath) })
	if !tr.Truncated {
		t.Error("Truncated = false, want true")
	}
	if tr.TotalResults != 20 {
		t.Errorf("TotalResults = %d, want 20", tr.TotalResults)
	}
	if tr.ShownResults != len(parsed.Results) {
		t.Errorf("ShownResults = %d, want %d", tr.ShownResults, len(parsed.Results))
	}
	if tr.ShownResults < 1 || tr.ShownResults >= 20 {
		t.Errorf("ShownResults = %d, want in [1, 19]", tr.ShownResults)
	}
	// Survivors must be the relevance-ordered prefix, not an arbitrary subset.
	for i, r := range parsed.Results {
		if want := fmt.Sprintf("Doc %d", i); r.Title != want {
			t.Errorf("Results[%d].Title = %q, want %q", i, r.Title, want)
		}
	}
	if tr.TotalBytes != len(fullData) {
		t.Errorf("TotalBytes = %d, want %d", tr.TotalBytes, len(fullData))
	}
	if tr.ContentTruncated {
		t.Error("ContentTruncated = true, want false when whole results fit")
	}
	if tr.Hint == "" {
		t.Error("Hint should not be empty")
	}

	// Temp file must hold the complete response.
	saved, err := os.ReadFile(tr.FullResponsePath)
	if err != nil {
		t.Fatalf("failed to read full response file: %v", err)
	}
	if !bytes.Equal(saved, fullData) {
		t.Error("full response file does not match the full payload")
	}

	// Human note goes to stderr, not stdout.
	if !strings.Contains(errOut.String(), "response truncated") {
		t.Errorf("stderr should mention truncation, got %q", errOut.String())
	}
}

func TestBuildTruncatedSearchOutput_SingleOversizedResult(t *testing.T) {
	// Multibyte runes verify the trim lands on a rune boundary.
	content := strings.Repeat("héllo→wörld ", 500)
	output := searchOutput{Results: []searchOutputResult{{
		Title:      "Big doc",
		SourceType: "slack",
		Content:    content,
	}}}

	limit := 2000
	data, err := buildTruncatedSearchOutput(output, limit, 99999, "/tmp/full.json")
	if err != nil {
		t.Fatalf("buildTruncatedSearchOutput failed: %v", err)
	}
	if len(data) > limit {
		t.Fatalf("envelope is %d bytes, want <= %d", len(data), limit)
	}

	var parsed searchOutput
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("envelope is not valid JSON: %v", err)
	}
	if parsed.Truncation == nil || !parsed.Truncation.ContentTruncated {
		t.Fatal("expected ContentTruncated = true")
	}
	if parsed.Truncation.ShownResults != 1 || len(parsed.Results) != 1 {
		t.Fatalf("expected exactly 1 shown result, got %d", len(parsed.Results))
	}
	got := parsed.Results[0].Content
	if !utf8.ValidString(got) {
		t.Error("trimmed content is not valid UTF-8")
	}
	if len(got) == 0 || len(got) >= len(content) {
		t.Errorf("trimmed content length = %d, want in (0, %d)", len(got), len(content))
	}
	if !strings.HasPrefix(content, got) {
		t.Error("trimmed content is not a prefix of the original")
	}
}

func TestBuildTruncatedSearchOutput_OversizedTitleFallsBackToZeroResults(t *testing.T) {
	// Content trimming can't help when the overflow lives in an untrimmed
	// field: even the empty-content render exceeds the limit, so the builder
	// must fall back to the zero-results envelope (which fits).
	output := searchOutput{Results: []searchOutputResult{{
		Title:      strings.Repeat("t", 5000),
		SourceType: "slack",
		Content:    strings.Repeat("c", 5000),
	}}}

	limit := 1000
	data, err := buildTruncatedSearchOutput(output, limit, 99999, "/tmp/full.json")
	if err != nil {
		t.Fatalf("buildTruncatedSearchOutput failed: %v", err)
	}
	if len(data) > limit {
		t.Fatalf("envelope is %d bytes, want <= %d", len(data), limit)
	}

	var parsed searchOutput
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("envelope is not valid JSON: %v", err)
	}
	if len(parsed.Results) != 0 {
		t.Fatalf("expected 0 results, got %d", len(parsed.Results))
	}
	if parsed.Truncation == nil || parsed.Truncation.ContentTruncated {
		t.Fatal("zero-results fallback must not claim content was trimmed")
	}
	if parsed.Truncation.TotalResults != 1 || parsed.Truncation.ShownResults != 0 {
		t.Fatalf(
			"TotalResults/ShownResults = %d/%d, want 1/0",
			parsed.Truncation.TotalResults, parsed.Truncation.ShownResults,
		)
	}
}

func TestBuildTruncatedSearchOutput_TinyLimitStillValidJSON(t *testing.T) {
	output := searchOutput{Results: makeSearchResults(3, 200)}

	// Limit smaller than the metadata itself: envelope may exceed the limit
	// but must remain valid JSON.
	data, err := buildTruncatedSearchOutput(output, 50, 1234, "/tmp/full.json")
	if err != nil {
		t.Fatalf("buildTruncatedSearchOutput failed: %v", err)
	}
	var parsed searchOutput
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("envelope is not valid JSON: %v", err)
	}
	if parsed.Truncation == nil || !parsed.Truncation.Truncated {
		t.Fatal("expected truncation metadata")
	}
	if len(parsed.Results) != 0 {
		t.Fatalf("expected 0 results when nothing fits, got %d", len(parsed.Results))
	}
	if parsed.Truncation.TotalResults != 3 {
		t.Errorf("TotalResults = %d, want 3", parsed.Truncation.TotalResults)
	}
}
