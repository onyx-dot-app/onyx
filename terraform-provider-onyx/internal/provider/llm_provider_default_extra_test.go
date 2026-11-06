package provider

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/types"

	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

// defaultsServer records every "METHOD /path" call and answers each with {}.
func defaultsServer(t *testing.T) (*client.Client, func() []string) {
	t.Helper()
	var mu sync.Mutex
	var calls []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		_, route, _ := strings.Cut(r.URL.Path, "/admin/")
		calls = append(calls, r.Method+" /admin/"+route)
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{}`))
	}))
	t.Cleanup(server.Close)
	recorded := func() []string {
		mu.Lock()
		defer mu.Unlock()
		return append([]string(nil), calls...)
	}
	return client.NewClient(client.Config{ServerURL: server.URL, APIKey: "on_test_key"}), recorded
}

func textDefaultOnly() llmProviderDefaultResourceModel {
	return llmProviderDefaultResourceModel{
		ProviderID:                types.StringValue("1"),
		ModelName:                 types.StringValue("gpt-6-luna"),
		VisionProviderID:          types.StringNull(),
		VisionModelName:           types.StringNull(),
		ChatNamingProviderID:      types.StringNull(),
		ChatNamingModelName:       types.StringNull(),
		CraftProviderID:           types.StringNull(),
		CraftModelName:            types.StringNull(),
		SearchSelectionProviderID: types.StringNull(),
		SearchSelectionModelName:  types.StringNull(),
	}
}

func equalCalls(got, want []string) bool {
	if len(got) != len(want) {
		return false
	}
	for i := range got {
		if got[i] != want[i] {
			return false
		}
	}
	return true
}

func TestLLMProviderDefaultSetsCraftAndSearchSelection(t *testing.T) {
	c, calls := defaultsServer(t)
	r := &llmProviderDefaultResource{client: c}
	plan := textDefaultOnly()
	plan.CraftProviderID, plan.CraftModelName = types.StringValue("2"), types.StringValue("gpt-6-sol")
	plan.SearchSelectionProviderID, plan.SearchSelectionModelName = types.StringValue("2"), types.StringValue("gpt-6-sol")

	var diags diag.Diagnostics
	got, wrote := r.apply(context.Background(), plan, llmProviderDefaultResourceModel{}, &diags)
	if diags.HasError() || !wrote {
		t.Fatalf("apply: wrote=%v diags=%v", wrote, diags)
	}
	want := []string{
		"POST /admin/llm/default",
		"POST /admin/llm/default-craft",
		"POST /admin/llm/default-search-selection",
	}
	if !equalCalls(calls(), want) {
		t.Errorf("calls = %v, want %v", calls(), want)
	}
	if !got.CraftModelName.Equal(types.StringValue("gpt-6-sol")) ||
		!got.SearchSelectionModelName.Equal(types.StringValue("gpt-6-sol")) {
		t.Errorf("state must hold the written pairs: %+v", got)
	}
}

// A pair that was never configured is not managed, so apply makes no call
// for it. A managed pair that leaves configuration is cleared.
func TestLLMProviderDefaultClearsOnlyRemovedManagedPairs(t *testing.T) {
	c, calls := defaultsServer(t)
	r := &llmProviderDefaultResource{client: c}
	state := textDefaultOnly()
	state.CraftProviderID, state.CraftModelName = types.StringValue("2"), types.StringValue("gpt-6-sol")

	var diags diag.Diagnostics
	got, _ := r.apply(context.Background(), textDefaultOnly(), state, &diags)
	if diags.HasError() {
		t.Fatal(diags)
	}
	want := []string{"POST /admin/llm/default", "DELETE /admin/llm/default-craft"}
	if !equalCalls(calls(), want) {
		t.Errorf("calls = %v, want %v", calls(), want)
	}
	if !got.CraftProviderID.IsNull() || !got.CraftModelName.IsNull() {
		t.Errorf("the cleared pair must be null in state: %+v", got)
	}
}
