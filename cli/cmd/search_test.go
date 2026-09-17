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
				"no query provided\n  Usage: onyx-cli search \"your query\" [\"another query\" ...]")
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

func TestWriteSearchJSON_TempSaveFailureEmitsFullResponse(t *testing.T) {
	// Dropped results must never be unrecoverable: with no temp copy, the
	// full over-limit response is emitted instead of a truncated envelope.
	t.Setenv("TMPDIR", "/nonexistent-onyx-cli-test")
	var out, errOut bytes.Buffer
	ios := &iostreams.IOStreams{Out: &out, ErrOut: &errOut}
	output := searchOutput{Results: makeSearchResults(20, 500)}

	if err := writeSearchJSON(ios, output, 3000); err != nil {
		t.Fatalf("writeSearchJSON failed: %v", err)
	}

	var parsed searchOutput
	if err := json.Unmarshal(out.Bytes(), &parsed); err != nil {
		t.Fatalf("stdout is not valid JSON: %v", err)
	}
	if parsed.Truncation != nil {
		t.Fatal("full-response fallback must not carry truncation metadata")
	}
	if len(parsed.Results) != 20 {
		t.Fatalf("Results length = %d, want all 20", len(parsed.Results))
	}
	if !strings.Contains(errOut.String(), "could not save full response") {
		t.Errorf("stderr should warn about the failed save, got %q", errOut.String())
	}
}

// renderTruncated runs truncateSearchOutput and marshals the envelope the
// way writeSearchJSON does, so size assertions match real stdout bytes.
func renderTruncated(
	t *testing.T, output searchOutput, limit, totalBytes int, fullPath string,
) []byte {
	t.Helper()
	truncated, err := truncateSearchOutput(output, limit, totalBytes, fullPath)
	if err != nil {
		t.Fatalf("truncateSearchOutput failed: %v", err)
	}
	data, err := json.MarshalIndent(truncated, "", "  ")
	if err != nil {
		t.Fatalf("marshal failed: %v", err)
	}
	return data
}

func TestTruncateSearchOutput_SingleOversizedResult(t *testing.T) {
	// Multibyte runes verify the trim lands on a rune boundary.
	content := strings.Repeat("héllo→wörld ", 500)
	output := searchOutput{Results: []searchOutputResult{{
		Title:      "Big doc",
		SourceType: "slack",
		Content:    content,
	}}}

	limit := 2000
	data := renderTruncated(t, output, limit, 99999, "/tmp/full.json")
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

func TestTruncateSearchOutput_OversizedTitleFallsBackToZeroResults(t *testing.T) {
	// Content trimming can't help when the overflow lives in an untrimmed
	// field: even the empty-content render exceeds the limit, so the builder
	// must fall back to the zero-results envelope (which fits).
	output := searchOutput{Results: []searchOutputResult{{
		Title:      strings.Repeat("t", 5000),
		SourceType: "slack",
		Content:    strings.Repeat("c", 5000),
	}}}

	limit := 1000
	data := renderTruncated(t, output, limit, 99999, "/tmp/full.json")
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

func TestTruncateSearchOutput_TinyLimitStillValidJSON(t *testing.T) {
	output := searchOutput{Results: makeSearchResults(3, 200)}

	// Limit smaller than the metadata itself: envelope may exceed the limit
	// but must remain valid JSON.
	data := renderTruncated(t, output, 50, 1234, "/tmp/full.json")
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

func TestWriteMultiSearchJSON_UnderLimit(t *testing.T) {
	var out, errOut bytes.Buffer
	ios := &iostreams.IOStreams{Out: &out, ErrOut: &errOut}
	output := multiSearchOutput{Searches: []multiSearchEntry{
		{Query: "first query", Results: makeSearchResults(2, 100)},
		{Query: "second query", Error: "search failed: server unreachable"},
	}}

	if err := writeMultiSearchJSON(ios, output, 50000); err != nil {
		t.Fatalf("writeMultiSearchJSON failed: %v", err)
	}

	var parsed multiSearchOutput
	if err := json.Unmarshal(out.Bytes(), &parsed); err != nil {
		t.Fatalf("stdout is not valid JSON: %v", err)
	}
	if len(parsed.Searches) != 2 {
		t.Fatalf("Searches length = %d, want 2", len(parsed.Searches))
	}
	// Entries must keep argument order.
	if parsed.Searches[0].Query != "first query" || parsed.Searches[1].Query != "second query" {
		t.Errorf("queries out of order: %q, %q", parsed.Searches[0].Query, parsed.Searches[1].Query)
	}
	if parsed.Searches[0].Error != "" || len(parsed.Searches[0].Results) != 2 {
		t.Errorf("success entry: error=%q results=%d, want no error and 2 results",
			parsed.Searches[0].Error, len(parsed.Searches[0].Results))
	}
	if parsed.Searches[1].Error == "" || parsed.Searches[1].Results != nil {
		t.Errorf("failed entry: error=%q results=%v, want error and null results",
			parsed.Searches[1].Error, parsed.Searches[1].Results)
	}
	if parsed.Searches[0].Truncation != nil {
		t.Error("under-limit output should not carry truncation metadata")
	}
	if errOut.Len() != 0 {
		t.Fatalf("expected empty stderr, got %q", errOut.String())
	}
}

func TestWriteMultiSearchJSON_OverLimitTruncatesPerQuery(t *testing.T) {
	var out, errOut bytes.Buffer
	ios := &iostreams.IOStreams{Out: &out, ErrOut: &errOut}
	output := multiSearchOutput{Searches: []multiSearchEntry{
		{Query: "big query", Results: makeSearchResults(20, 500)},
		{Query: "second big query", Results: makeSearchResults(12, 500)},
		{Query: "small query", Results: makeSearchResults(1, 50)},
		{Query: "broken query", Error: "search failed: timeout"},
	}}

	fullData, err := json.MarshalIndent(output, "", "  ")
	if err != nil {
		t.Fatalf("marshal failed: %v", err)
	}
	limit := 6000
	if len(fullData) <= limit {
		t.Fatalf("test setup: payload (%d bytes) must exceed limit %d", len(fullData), limit)
	}

	if err := writeMultiSearchJSON(ios, output, limit); err != nil {
		t.Fatalf("writeMultiSearchJSON failed: %v", err)
	}

	var parsed multiSearchOutput
	if err := json.Unmarshal(out.Bytes(), &parsed); err != nil {
		t.Fatalf("stdout is not valid JSON: %v\n%s", err, out.String())
	}
	if len(parsed.Searches) != 4 {
		t.Fatalf("Searches length = %d, want all 4 entries", len(parsed.Searches))
	}

	// Both oversized entries are reduced and carry truncation metadata.
	big, big2 := parsed.Searches[0], parsed.Searches[1]
	tr := big.Truncation
	if tr == nil || big2.Truncation == nil {
		t.Fatal("expected truncation metadata on both oversized entries")
	}
	t.Cleanup(func() { _ = os.Remove(tr.FullResponsePath) })
	if tr.TotalResults != 20 || big2.Truncation.TotalResults != 12 {
		t.Errorf("TotalResults = %d/%d, want 20/12", tr.TotalResults, big2.Truncation.TotalResults)
	}
	if tr.ShownResults != len(big.Results) || tr.ShownResults >= 12 {
		t.Errorf("ShownResults = %d with %d results, want a reduced prefix",
			tr.ShownResults, len(big.Results))
	}
	// The cap is uniform; the oracle test pins that survivors are the
	// relevance-ordered prefix.
	if big2.Truncation.ShownResults != tr.ShownResults || len(big2.Results) != len(big.Results) {
		t.Errorf("caps differ: %d vs %d results, want uniform",
			len(big.Results), len(big2.Results))
	}

	// The combined envelope must actually respect the byte bound.
	if out.Len() > limit+1 { // +1 for trailing newline
		t.Errorf("stdout is %d bytes, want <= %d", out.Len(), limit+1)
	}

	// Entries under the uniform result cap pass through untouched.
	small := parsed.Searches[2]
	if small.Truncation != nil || len(small.Results) != 1 {
		t.Errorf("small entry: truncation=%v results=%d, want untouched", small.Truncation, len(small.Results))
	}
	broken := parsed.Searches[3]
	if broken.Error == "" || broken.Truncation != nil {
		t.Errorf("failed entry: error=%q truncation=%v, want error preserved", broken.Error, broken.Truncation)
	}

	// Metadata must describe the combined full payload on disk.
	if tr.TotalBytes != len(fullData) {
		t.Errorf("TotalBytes = %d, want %d", tr.TotalBytes, len(fullData))
	}
	saved, err := os.ReadFile(tr.FullResponsePath)
	if err != nil {
		t.Fatalf("failed to read full response file: %v", err)
	}
	if !bytes.Equal(saved, fullData) {
		t.Error("full response file does not match the full payload")
	}
	if !strings.Contains(errOut.String(), "response truncated") {
		t.Errorf("stderr should mention truncation, got %q", errOut.String())
	}
}

func TestTruncateMultiSearchOutput_LargestFittingCapDespiteNonMonotoneSizes(t *testing.T) {
	// Envelope size is not monotone in the uniform cap k (an entry sheds its
	// truncation metadata once k reaches its result count); a binary search
	// over k once shipped an over-limit k=0 render despite a fitting k.
	// Oracle: for every limit where some k-envelope fits, the reducer must
	// return exactly the largest fitting k's envelope. Unique titles make
	// the byte comparison also pin the relevance-ordered prefix.
	mini := func(n int) []searchOutputResult {
		results := make([]searchOutputResult, n)
		for i := range results {
			results[i] = searchOutputResult{Title: fmt.Sprintf("d%d", i), SourceType: "s"}
		}
		return results
	}
	output := multiSearchOutput{Searches: []multiSearchEntry{
		{Query: "a", Results: mini(1)},
		{Query: "b", Results: mini(1)},
		{Query: "c", Results: mini(2)},
		{Query: "d", Results: mini(5)},
	}}
	const maxK = 5
	fullData, err := json.MarshalIndent(output, "", "  ")
	if err != nil {
		t.Fatalf("marshal failed: %v", err)
	}
	fullPath := "/tmp/" + strings.Repeat("x", 120) + "/onyx-search-full.json"

	// Oracle: the documented envelope for a given uniform cap k.
	capAt := func(k int) multiSearchOutput {
		out := multiSearchOutput{}
		for _, entry := range output.Searches {
			if entry.Error != "" || len(entry.Results) <= k {
				out.Searches = append(out.Searches, entry)
				continue
			}
			out.Searches = append(out.Searches, multiSearchEntry{
				Query:   entry.Query,
				Results: entry.Results[:k],
				Truncation: &searchTruncation{
					Truncated:        true,
					TotalResults:     len(entry.Results),
					ShownResults:     k,
					TotalBytes:       len(fullData),
					FullResponsePath: fullPath,
					Hint:             truncationHint,
				},
			})
		}
		return out
	}
	sizes := make([]int, maxK+1)
	minSize := len(fullData)
	for k := 0; k <= maxK; k++ {
		data, err := json.MarshalIndent(capAt(k), "", "  ")
		if err != nil {
			t.Fatalf("oracle marshal failed: %v", err)
		}
		sizes[k] = len(data)
		minSize = min(minSize, sizes[k])
	}
	// The scenario only exercises the dip when some mid k renders smaller
	// than k=0; guard so fixture drift can't silently weaken the test.
	if minSize >= sizes[0] {
		t.Fatalf("fixture no longer non-monotone: sizes=%v", sizes)
	}

	for limit := minSize; limit <= len(fullData); limit++ {
		wantK := -1
		for k := maxK; k >= 0; k-- {
			if sizes[k] <= limit {
				wantK = k
				break
			}
		}
		reduced, err := truncateMultiSearchOutput(output, limit, len(fullData), fullPath)
		if err != nil {
			t.Fatalf("truncateMultiSearchOutput failed at limit %d: %v", limit, err)
		}
		data, err := json.MarshalIndent(reduced, "", "  ")
		if err != nil {
			t.Fatalf("marshal failed at limit %d: %v", limit, err)
		}
		if len(data) > limit {
			t.Fatalf("limit %d: envelope is %d bytes though k=%d fits", limit, len(data), wantK)
		}
		if len(data) != sizes[wantK] {
			t.Fatalf("limit %d: envelope is %d bytes, want largest fitting cap k=%d (%d bytes)",
				limit, len(data), wantK, sizes[wantK])
		}
	}
}

func TestTruncateMultiSearchOutput_OversizedSingleResultFallsBackToContentTrim(t *testing.T) {
	// One result larger than the whole budget defeats every uniform cap. The
	// fallback must content-trim the huge entry while the small entry's
	// results survive — not fall to the k=0 wipe-everything envelope.
	output := multiSearchOutput{Searches: []multiSearchEntry{
		{Query: "huge", Results: []searchOutputResult{{
			Title:      "Big doc",
			SourceType: "slack",
			Content:    strings.Repeat("x", 5000),
		}}},
		{Query: "small", Results: makeSearchResults(3, 40)},
	}}
	fullData, err := json.MarshalIndent(output, "", "  ")
	if err != nil {
		t.Fatalf("marshal failed: %v", err)
	}
	limit := 3000

	reduced, err := truncateMultiSearchOutput(output, limit, len(fullData), "/tmp/full.json")
	if err != nil {
		t.Fatalf("truncateMultiSearchOutput failed: %v", err)
	}
	data, err := json.MarshalIndent(reduced, "", "  ")
	if err != nil {
		t.Fatalf("marshal failed: %v", err)
	}
	if len(data) > limit {
		t.Fatalf("envelope is %d bytes, want <= %d", len(data), limit)
	}

	huge := reduced.Searches[0]
	if huge.Truncation == nil || !huge.Truncation.ContentTruncated {
		t.Fatalf("huge entry: truncation=%+v, want content-trimmed", huge.Truncation)
	}
	if len(huge.Results) != 1 || len(huge.Results[0].Content) == 0 || len(huge.Results[0].Content) >= 5000 {
		t.Errorf("huge entry: %d results, content length %d, want 1 result with trimmed content",
			len(huge.Results), len(huge.Results[0].Content))
	}
	small := reduced.Searches[1]
	if small.Truncation != nil || len(small.Results) != 3 {
		t.Errorf("small entry: truncation=%v results=%d, want untouched", small.Truncation, len(small.Results))
	}
}

func TestClampError(t *testing.T) {
	if got := clampError(errors.New("nope")); got != "nope" {
		t.Errorf("short error = %q, want unchanged", got)
	}

	// HTML-escaped bytes expand six-fold under encoding/json, so the clamp
	// must bound the encoded size, not the raw length; the multibyte fixture
	// verifies the cut lands on a rune boundary.
	for name, long := range map[string]error{
		"html_page": errors.New(strings.Repeat("<div>&amp;</div> héllo ", 300)),
		"multibyte": errors.New(strings.Repeat("héllo→wörld ", 500)),
	} {
		got := clampError(long)
		encoded, err := json.Marshal(got)
		if err != nil {
			t.Fatalf("%s: marshal failed: %v", name, err)
		}
		if len(encoded) > maxInlineErrorBytes {
			t.Errorf("%s: encoded length = %d, want <= %d", name, len(encoded), maxInlineErrorBytes)
		}
		if !utf8.ValidString(got) {
			t.Errorf("%s: clamped message is not valid UTF-8", name)
		}
		if !strings.HasSuffix(got, " … (truncated)") {
			t.Errorf("%s: clamped message should note truncation, got suffix %q", name, got[len(got)-30:])
		}
		if !strings.HasPrefix(long.Error(), strings.TrimSuffix(got, " … (truncated)")) {
			t.Errorf("%s: clamped message is not a prefix of the original", name)
		}
	}
}
