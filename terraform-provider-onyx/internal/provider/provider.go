// Package provider implements the Terraform provider for Onyx application
// configuration.
package provider

import (
	"context"
	"fmt"
	"os"

	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/provider"
	"github.com/hashicorp/terraform-plugin-framework/provider/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var _ provider.Provider = (*onyxProvider)(nil)

type onyxProvider struct {
	version string
}

// New returns a provider factory, as expected by providerserver.Serve and the
// acceptance-test harness.
func New(version string) func() provider.Provider {
	return func() provider.Provider {
		return &onyxProvider{version: version}
	}
}

type onyxProviderModel struct {
	Endpoint  types.String `tfsdk:"endpoint"`
	APIKey    types.String `tfsdk:"api_key"`
	APIPrefix types.String `tfsdk:"api_prefix"`
}

func (p *onyxProvider) Metadata(_ context.Context, _ provider.MetadataRequest, resp *provider.MetadataResponse) {
	resp.TypeName = "onyx"
	resp.Version = p.version
}

func (p *onyxProvider) Schema(_ context.Context, _ provider.SchemaRequest, resp *provider.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "Manage Onyx application configuration (LLM providers, API keys, " +
			"workspace settings, ...) declaratively via the Onyx admin API.",
		Attributes: map[string]schema.Attribute{
			"endpoint": schema.StringAttribute{
				Optional: true,
				MarkdownDescription: "Onyx server origin, e.g. `https://cloud.onyx.app` or `http://localhost:3000`. " +
					"May also be set via the `ONYX_SERVER_URL` environment variable.",
			},
			"api_key": schema.StringAttribute{
				Optional:  true,
				Sensitive: true,
				MarkdownDescription: "Admin-role Onyx API key (`on_...`) or unrestricted personal access token " +
					"(`onyx_pat_...`). May also be set via the `ONYX_API_KEY` environment variable.",
			},
			"api_prefix": schema.StringAttribute{
				Optional: true,
				MarkdownDescription: "Path prefix the API is served under, defaults to `/api` (the web proxy). " +
					"Set to `\"\"` when talking directly to the backend (e.g. `http://localhost:8080`). " +
					"May also be set via the `ONYX_API_PREFIX` environment variable.",
			},
		},
	}
}

func (p *onyxProvider) Configure(ctx context.Context, req provider.ConfigureRequest, resp *provider.ConfigureResponse) {
	var config onyxProviderModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &config)...)
	if resp.Diagnostics.HasError() {
		return
	}

	endpoint := os.Getenv("ONYX_SERVER_URL")
	if !config.Endpoint.IsNull() {
		endpoint = config.Endpoint.ValueString()
	}
	apiKey := os.Getenv("ONYX_API_KEY")
	if !config.APIKey.IsNull() {
		apiKey = config.APIKey.ValueString()
	}
	apiPrefix := "/api"
	if v, ok := os.LookupEnv("ONYX_API_PREFIX"); ok {
		apiPrefix = v
	}
	if !config.APIPrefix.IsNull() {
		apiPrefix = config.APIPrefix.ValueString()
	}

	if endpoint == "" {
		resp.Diagnostics.AddError(
			"Missing Onyx endpoint",
			"Set the provider's endpoint attribute or the ONYX_SERVER_URL environment variable.",
		)
	}
	if apiKey == "" {
		resp.Diagnostics.AddError(
			"Missing Onyx API key",
			"Set the provider's api_key attribute or the ONYX_API_KEY environment variable. "+
				"Create an admin-role API key in the Onyx admin panel (or via POST /admin/api-key).",
		)
	}
	if resp.Diagnostics.HasError() {
		return
	}

	c := client.NewClient(endpoint, apiPrefix, apiKey)
	resp.ResourceData = c
	resp.DataSourceData = c
}

func (p *onyxProvider) Resources(_ context.Context) []func() resource.Resource {
	return []func() resource.Resource{
		NewAPIKeyResource,
		NewLLMProviderResource,
		NewLLMProviderDefaultResource,
		NewSettingsResource,
		NewEmbeddingProviderResource,
	}
}

func (p *onyxProvider) DataSources(_ context.Context) []func() datasource.DataSource {
	return []func() datasource.DataSource{
		NewLLMProvidersDataSource,
		NewEmbeddingProvidersDataSource,
		NewSettingsDataSource,
	}
}

// clientFromResourceConfigure extracts the shared *client.Client in a
// resource's Configure, adding a diagnostic on type mismatch.
func clientFromResourceConfigure(req resource.ConfigureRequest, resp *resource.ConfigureResponse) *client.Client {
	if req.ProviderData == nil {
		return nil // Configure is called before provider Configure during validation.
	}
	c, ok := req.ProviderData.(*client.Client)
	if !ok {
		resp.Diagnostics.AddError(
			"Unexpected resource configure type",
			fmt.Sprintf("Expected *client.Client, got %T. This is a bug in the provider.", req.ProviderData),
		)
		return nil
	}
	return c
}

// clientFromDataSourceConfigure is clientFromResourceConfigure for data sources.
func clientFromDataSourceConfigure(req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) *client.Client {
	if req.ProviderData == nil {
		return nil
	}
	c, ok := req.ProviderData.(*client.Client)
	if !ok {
		resp.Diagnostics.AddError(
			"Unexpected data source configure type",
			fmt.Sprintf("Expected *client.Client, got %T. This is a bug in the provider.", req.ProviderData),
		)
		return nil
	}
	return c
}
