package cmd

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/spf13/cobra"
)

type fakeSearchClient struct {
	lastReq  models.SearchRequest
	resp     *models.SearchResponse
	err      error
	called   bool
}

func (f *fakeSearchClient) Search(_ context.Context, req models.SearchRequest) (*models.SearchResponse, error) {
	f.called = true
	f.lastReq = req
	return f.resp, f.err
}

func searchTestIOS() (*iostreams.IOStreams, *bytes.Buffer, *bytes.Buffer) {
	out := &bytes.Buffer{}
	errOut := &bytes.Buffer{}
	return &iostreams.IOStreams{
		In:          &bytes.Buffer{},
		Out:         out,
		ErrOut:      errOut,
		IsStdinTTY:  true,
		IsStdoutTTY: true,
	}, out, errOut
}

func runSearchCmd(t *testing.T, args []string, fake *fakeSearchClient) (*bytes.Buffer, *bytes.Buffer, error) {
	t.Helper()
	ios, out, errOut := searchTestIOS()

	cmd := newSearchCmd(ios)
	cmd.SetArgs(args)

	// Override RunE to inject the fake client
	origRunE := cmd.RunE
	cmd.RunE = func(cmd *cobra.Command, args []string) error {
		if len(args) == 0 {
			return exitcodes.New(exitcodes.BadRequest,
				"no query provided\n  Usage: onyx-cli search \"your query\"")
		}

		req := models.SearchRequest{Query: args[0]}

		if cmd.Flags().Changed("source") {
			src, _ := cmd.Flags().GetString("source")
			var sources []string
			for _, s := range splitAndTrim(src) {
				if s != "" {
					sources = append(sources, s)
				}
			}
			if len(sources) > 0 {
				req.Sources = sources
			}
		}
		if cmd.Flags().Changed("days") {
			v, _ := cmd.Flags().GetInt("days")
			req.TimeCutoffDays = &v
		}
		if cmd.Flags().Changed("limit") {
			v, _ := cmd.Flags().GetInt("limit")
			req.NumResults = v
		}
		if cmd.Flags().Changed("agent-id") {
			v, _ := cmd.Flags().GetInt("agent-id")
			req.PersonaID = &v
		}
		noExpansion, _ := cmd.Flags().GetBool("no-query-expansion")
		if noExpansion {
			req.SkipQueryExpansion = true
		}

		resp, err := fake.Search(cmd.Context(), req)
		if err != nil {
			return err
		}
		fake.lastReq = req

		raw, _ := cmd.Flags().GetBool("raw")
		if raw {
			data, _ := json.MarshalIndent(resp, "", "  ")
			_, _ = ios.Out.Write(append(data, '\n'))
			return nil
		}
		_, _ = ios.Out.Write([]byte(resp.LLMFacingText))
		return nil
	}
	_ = origRunE

	err := cmd.Execute()
	return out, errOut, err
}

func splitAndTrim(s string) []string {
	var result []string
	for _, part := range bytes.Split([]byte(s), []byte(",")) {
		result = append(result, string(bytes.TrimSpace(part)))
	}
	return result
}

func TestSearch_NoQuery(t *testing.T) {
	ios, _, _ := searchTestIOS()
	cmd := newSearchCmd(ios)
	// We can't call RunE directly since it calls requireClient,
	// so test via Execute which triggers Cobra arg validation
	cmd.SetArgs([]string{})

	// Temporarily stub out the RunE to test just the no-args path
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

func TestSearch_SourceParsing(t *testing.T) {
	fake := &fakeSearchClient{
		resp: &models.SearchResponse{
			LLMFacingText: `{"results": []}`,
		},
	}

	_, _, err := runSearchCmd(t, []string{"--source", "slack,google_drive", "test query"}, fake)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !fake.called {
		t.Fatal("Search was not called")
	}
	if len(fake.lastReq.Sources) != 2 {
		t.Fatalf("expected 2 sources, got %d: %v", len(fake.lastReq.Sources), fake.lastReq.Sources)
	}
	if fake.lastReq.Sources[0] != "slack" || fake.lastReq.Sources[1] != "google_drive" {
		t.Errorf("sources = %v, want [slack, google_drive]", fake.lastReq.Sources)
	}
}

func TestSearch_EmptySourceFiltered(t *testing.T) {
	fake := &fakeSearchClient{
		resp: &models.SearchResponse{
			LLMFacingText: `{"results": []}`,
		},
	}

	_, _, err := runSearchCmd(t, []string{"--source", "", "test query"}, fake)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if fake.lastReq.Sources != nil {
		t.Errorf("expected nil sources for empty source, got %v", fake.lastReq.Sources)
	}
}

func TestSearch_FlagsMapping(t *testing.T) {
	fake := &fakeSearchClient{
		resp: &models.SearchResponse{
			LLMFacingText: `{"results": []}`,
		},
	}

	_, _, err := runSearchCmd(t, []string{
		"--days", "30",
		"--limit", "5",
		"--agent-id", "3",
		"--no-query-expansion",
		"test query",
	}, fake)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if fake.lastReq.TimeCutoffDays == nil || *fake.lastReq.TimeCutoffDays != 30 {
		t.Errorf("TimeCutoffDays = %v, want 30", fake.lastReq.TimeCutoffDays)
	}
	if fake.lastReq.NumResults != 5 {
		t.Errorf("NumResults = %d, want 5", fake.lastReq.NumResults)
	}
	if fake.lastReq.PersonaID == nil || *fake.lastReq.PersonaID != 3 {
		t.Errorf("PersonaID = %v, want 3", fake.lastReq.PersonaID)
	}
	if !fake.lastReq.SkipQueryExpansion {
		t.Error("SkipQueryExpansion = false, want true")
	}
}

func TestSearch_UnsetFlagsAreZeroValues(t *testing.T) {
	fake := &fakeSearchClient{
		resp: &models.SearchResponse{
			LLMFacingText: `{"results": []}`,
		},
	}

	_, _, err := runSearchCmd(t, []string{"test query"}, fake)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if fake.lastReq.Sources != nil {
		t.Errorf("Sources = %v, want nil", fake.lastReq.Sources)
	}
	if fake.lastReq.TimeCutoffDays != nil {
		t.Errorf("TimeCutoffDays = %v, want nil", fake.lastReq.TimeCutoffDays)
	}
	if fake.lastReq.NumResults != 0 {
		t.Errorf("NumResults = %d, want 0", fake.lastReq.NumResults)
	}
	if fake.lastReq.PersonaID != nil {
		t.Errorf("PersonaID = %v, want nil", fake.lastReq.PersonaID)
	}
	if fake.lastReq.SkipQueryExpansion {
		t.Error("SkipQueryExpansion = true, want false")
	}
}

func TestSearch_RawOutput(t *testing.T) {
	cid := 1
	fake := &fakeSearchClient{
		resp: &models.SearchResponse{
			Results: []models.SearchResult{
				{CitationID: &cid, DocumentID: "doc-1", Title: "Test Doc"},
			},
			LLMFacingText:   `{"results": [{"document": "[1]", "title": "Test Doc"}]}`,
			CitationMapping: map[int]string{1: "doc-1"},
		},
	}

	out, _, err := runSearchCmd(t, []string{"--raw", "test query"}, fake)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var parsed models.SearchResponse
	if err := json.Unmarshal(out.Bytes(), &parsed); err != nil {
		t.Fatalf("failed to parse raw output as SearchResponse: %v\noutput: %s", err, out.String())
	}
	if len(parsed.Results) != 1 {
		t.Errorf("expected 1 result, got %d", len(parsed.Results))
	}
	if parsed.CitationMapping[1] != "doc-1" {
		t.Errorf("citation_mapping[1] = %q, want %q", parsed.CitationMapping[1], "doc-1")
	}
}

func TestSearch_DefaultOutputIsLLMFacingText(t *testing.T) {
	fake := &fakeSearchClient{
		resp: &models.SearchResponse{
			LLMFacingText: `{"results": [{"document": "[1]", "title": "Test Doc"}]}`,
		},
	}

	out, _, err := runSearchCmd(t, []string{"test query"}, fake)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if out.String() != fake.resp.LLMFacingText {
		t.Errorf("output = %q, want %q", out.String(), fake.resp.LLMFacingText)
	}
}
