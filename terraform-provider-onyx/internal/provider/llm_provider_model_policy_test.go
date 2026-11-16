package provider

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/hashicorp/terraform-plugin-framework/attr"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/types"

	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

func modelConfigSet(t *testing.T, models ...modelConfigurationModel) types.Set {
	t.Helper()
	set, diags := types.SetValueFrom(context.Background(), types.ObjectType{AttrTypes: modelConfigurationAttrTypes}, models)
	if diags.HasError() {
		t.Fatal(diags)
	}
	return set
}

func nullModelConfig(name string) modelConfigurationModel {
	return modelConfigurationModel{
		Name:                   types.StringValue(name),
		IsVisible:              types.BoolValue(true),
		MaxInputTokens:         types.Int64Null(),
		SupportsImageInput:     types.BoolNull(),
		SupportsReasoning:      types.BoolNull(),
		DisplayName:            types.StringNull(),
		CustomDisplayName:      types.StringNull(),
		ReasoningEffortMax:     types.StringNull(),
		ReasoningEffortDefault: types.StringNull(),
		TemperatureDefault:     types.Float64Null(),
	}
}

// Onyx keeps the stored policy for an omitted field, so unset fields must
// not be sent as null.
func TestLLMProviderUpsertSendsModelPolicyOnlyWhenSet(t *testing.T) {
	managed := nullModelConfig("gpt-6-sol")
	managed.ReasoningEffortMax = types.StringValue("high")
	managed.ReasoningEffortDefault = types.StringValue("low")
	managed.TemperatureDefault = types.Float64Value(0.5)

	empty := types.SetValueMust(types.Int64Type, []attr.Value{})
	plan := llmProviderResourceModel{
		ProviderType:        types.StringValue("openai"),
		Groups:              empty,
		Agents:              empty,
		ModelConfigurations: modelConfigSet(t, managed, nullModelConfig("gpt-6-luna")),
	}
	var diags diag.Diagnostics
	upsert := (&llmProviderResource{}).buildUpsertRequest(context.Background(), plan, nil, llmProviderSecrets{}, false, false, &diags)
	if diags.HasError() {
		t.Fatal(diags)
	}
	raw, err := json.Marshal(upsert)
	if err != nil {
		t.Fatal(err)
	}
	var body struct {
		ModelConfigurations []map[string]any `json:"model_configurations"`
	}
	if err := json.Unmarshal(raw, &body); err != nil {
		t.Fatal(err)
	}

	byName := map[string]map[string]any{}
	for _, mc := range body.ModelConfigurations {
		byName[mc["name"].(string)] = mc
	}
	sol := byName["gpt-6-sol"]
	if sol["reasoning_effort_max"] != "high" || sol["reasoning_effort_default"] != "low" || sol["temperature_default"] != 0.5 {
		t.Errorf("configured policy not sent: %v", sol)
	}
	for _, field := range []string{"reasoning_effort_max", "reasoning_effort_default", "temperature_default"} {
		if _, ok := byName["gpt-6-luna"][field]; ok {
			t.Errorf("unset %s must not be sent", field)
		}
	}
}

func TestLLMProviderReadRefreshesOnlyManagedModelPolicy(t *testing.T) {
	managed := nullModelConfig("gpt-6-sol")
	managed.ReasoningEffortMax = types.StringValue("high")
	managed.TemperatureDefault = types.Float64Value(0.5)
	prior := modelConfigSet(t, managed, nullModelConfig("gpt-6-luna"))

	medium, low, temperature := "medium", "low", 1.0
	remote := []client.ModelConfigurationView{
		{Name: "gpt-6-sol", IsVisible: true, ReasoningEffortMax: &medium, TemperatureDefault: &temperature},
		{Name: "gpt-6-luna", IsVisible: true, ReasoningEffortMax: &low, TemperatureDefault: &temperature},
	}

	var diags diag.Diagnostics
	got := (&llmProviderResource{}).reconcileModelConfigurations(context.Background(), prior, remote, &diags)
	if diags.HasError() {
		t.Fatal(diags)
	}
	var models []modelConfigurationModel
	if d := got.ElementsAs(context.Background(), &models, false); d.HasError() {
		t.Fatal(d)
	}
	for _, mc := range models {
		switch mc.Name.ValueString() {
		case "gpt-6-sol":
			if !mc.ReasoningEffortMax.Equal(types.StringValue("medium")) ||
				!mc.TemperatureDefault.Equal(types.Float64Value(1.0)) {
				t.Errorf("managed policy must show drift: %+v", mc)
			}
			if !mc.ReasoningEffortDefault.IsNull() {
				t.Errorf("unmanaged reasoning_effort_default must stay null: %+v", mc)
			}
		case "gpt-6-luna":
			if !mc.ReasoningEffortMax.IsNull() || !mc.TemperatureDefault.IsNull() {
				t.Errorf("unmanaged policy must stay null: %+v", mc)
			}
		}
	}
}
