package provider

import (
	"context"
	"fmt"
	"regexp"
	"testing"

	"github.com/hashicorp/terraform-plugin-testing/helper/resource"
	"github.com/hashicorp/terraform-plugin-testing/terraform"
	"github.com/hashicorp/terraform-plugin-testing/tfversion"
)

var (
	regexpInvalidAttributeCombination = regexp.MustCompile(`(?s)Invalid Attribute Combination`)
	regexpExactlyOneRequired          = regexp.MustCompile(`(?s)Exactly one of these attributes must be configured`)
	regexpAPITokenOnPerUserServer     = regexp.MustCompile(`(?s)api_token set on a per-user server`)
	regexpConflictingAuth             = regexp.MustCompile(`(?s)Conflicting authentication settings`)
)

// Write-only attributes reached Terraform in 1.11. Older CLIs reject a
// configuration that sets one, so every case here skips below that.
var writeOnlyVersionChecks = []tfversion.TerraformVersionCheck{
	tfversion.SkipBelow(tfversion.Version1_11_0),
}

func TestAccLLMProviderWriteOnlyAPIKey(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		TerraformVersionChecks:   writeOnlyVersionChecks,
		CheckDestroy:             testAccCheckLLMProviderDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_llm_provider" "wo" {
  name               = "tf-acc-openai-wo"
  provider_type      = "openai"
  api_key_wo         = "sk-tf-acc-write-only"
  api_key_wo_version = 1

  model_configurations = [
    { name = "gpt-5-mini" },
  ]
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttrSet("onyx_llm_provider.wo", "id"),
					// The point of the feature: neither the write-only value nor
					// the stored twin is in state.
					resource.TestCheckNoResourceAttr("onyx_llm_provider.wo", "api_key"),
					resource.TestCheckNoResourceAttr("onyx_llm_provider.wo", "api_key_wo"),
					// The rotation counter is stored, which is what makes a
					// diff possible at all.
					resource.TestCheckResourceAttr("onyx_llm_provider.wo", "api_key_wo_version", "1"),
				),
			},
			{
				// A new secret with the counter left alone plans nothing. This
				// is the documented cost of a value Terraform never stores.
				Config: `
resource "onyx_llm_provider" "wo" {
  name               = "tf-acc-openai-wo"
  provider_type      = "openai"
  api_key_wo         = "sk-tf-acc-write-only-rotated"
  api_key_wo_version = 1

  model_configurations = [
    { name = "gpt-5-mini" },
  ]
}
`,
				PlanOnly: true,
			},
			{
				// Raising the counter is what sends it.
				Config: `
resource "onyx_llm_provider" "wo" {
  name               = "tf-acc-openai-wo"
  provider_type      = "openai"
  api_key_wo         = "sk-tf-acc-write-only-rotated"
  api_key_wo_version = 2

  model_configurations = [
    { name = "gpt-5-mini" },
  ]
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_llm_provider.wo", "api_key_wo_version", "2"),
					resource.TestCheckNoResourceAttr("onyx_llm_provider.wo", "api_key"),
				),
			},
		},
	})
}

func TestAccLLMProviderRejectsBothAPIKeyForms(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		TerraformVersionChecks:   writeOnlyVersionChecks,
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_llm_provider" "conflict" {
  name          = "tf-acc-openai-conflict"
  provider_type = "openai"
  api_key       = "sk-stored"
  api_key_wo    = "sk-write-only"

  model_configurations = [
    { name = "gpt-5-mini" },
  ]
}
`,
				ExpectError: regexpInvalidAttributeCombination,
			},
		},
	})
}

func TestAccEmbeddingProviderWriteOnlyAPIKey(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		TerraformVersionChecks:   writeOnlyVersionChecks,
		CheckDestroy:             testAccCheckEmbeddingProviderDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_embedding_provider" "wo" {
  provider_type      = "voyage"
  api_key_wo         = "pa-tf-acc-write-only"
  api_key_wo_version = 1
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_embedding_provider.wo", "id", "voyage"),
					resource.TestCheckNoResourceAttr("onyx_embedding_provider.wo", "api_key"),
					resource.TestCheckNoResourceAttr("onyx_embedding_provider.wo", "api_key_wo"),
				),
			},
		},
	})
}

func TestAccCredentialWriteOnlyPayload(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		TerraformVersionChecks:   writeOnlyVersionChecks,
		CheckDestroy:             testAccCheckCredentialDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_credential" "wo" {
  source = "confluence"
  name   = "tf-acc-credential-wo"
  credential_json_wo = jsonencode({
    confluence_username     = "tf-acc@example.com"
    confluence_access_token = "tf-acc-write-only-token"
  })
  credential_json_wo_version = 1
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_credential.wo", "name", "tf-acc-credential-wo"),
					resource.TestCheckNoResourceAttr("onyx_credential.wo", "credential_json"),
					resource.TestCheckNoResourceAttr("onyx_credential.wo", "credential_json_wo"),
				),
			},
			{
				// Renaming leaves the payload alone; the counter did not move.
				Config: `
resource "onyx_credential" "wo" {
  source = "confluence"
  name   = "tf-acc-credential-wo-renamed"
  credential_json_wo = jsonencode({
    confluence_username     = "tf-acc@example.com"
    confluence_access_token = "tf-acc-write-only-token"
  })
  credential_json_wo_version = 1
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_credential.wo", "name", "tf-acc-credential-wo-renamed"),
					resource.TestCheckNoResourceAttr("onyx_credential.wo", "credential_json"),
				),
			},
			{
				// Rotating the payload needs the counter.
				Config: `
resource "onyx_credential" "wo" {
  source = "confluence"
  name   = "tf-acc-credential-wo-renamed"
  credential_json_wo = jsonencode({
    confluence_username     = "tf-acc@example.com"
    confluence_access_token = "tf-acc-write-only-token-rotated"
  })
  credential_json_wo_version = 2
}
`,
				Check: resource.TestCheckResourceAttr("onyx_credential.wo", "credential_json_wo_version", "2"),
			},
		},
	})
}

// The payload is still mandatory now that it can arrive two ways, and the two
// ways stay mutually exclusive.
func TestAccCredentialRequiresExactlyOnePayloadForm(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_credential" "missing" {
  source = "confluence"
  name   = "tf-acc-credential-missing-payload"
}
`,
				ExpectError: regexpExactlyOneRequired,
			},
		},
	})
}

func TestAccCredentialRejectsBothPayloadForms(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		TerraformVersionChecks:   writeOnlyVersionChecks,
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_credential" "both" {
  source             = "confluence"
  name               = "tf-acc-credential-both-payloads"
  credential_json    = jsonencode({ confluence_access_token = "stored" })
  credential_json_wo = jsonencode({ confluence_access_token = "write-only" })
}
`,
				ExpectError: regexpInvalidAttributeCombination,
			},
		},
	})
}

func TestAccMCPServerWriteOnlyAPIToken(t *testing.T) {
	name := "tf-acc-mcp-write-only"
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		TerraformVersionChecks:   writeOnlyVersionChecks,
		CheckDestroy:             testAccCheckMCPServerDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: fmt.Sprintf(`
resource "onyx_mcp_server" "wo" {
  name                 = %q
  server_url           = %q
  auth_type            = "API_TOKEN"
  auth_performer       = "ADMIN"
  api_token_wo         = "tf-acc-write-only-token"
  api_token_wo_version = 1
}
`, name, mcpServerURL),
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckResourceAttr("onyx_mcp_server.wo", "name", name),
					resource.TestCheckResourceAttr("onyx_mcp_server.wo", "auth_type", "API_TOKEN"),
					resource.TestCheckNoResourceAttr("onyx_mcp_server.wo", "api_token"),
					resource.TestCheckNoResourceAttr("onyx_mcp_server.wo", "api_token_wo"),
				),
			},
		},
	})
}

// The authentication checks read configuration, so a write-only token is just
// as visible to them as a stored one — including where it is not allowed.
func TestAccMCPServerRejectsWriteOnlyTokenOnPerUserServer(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		TerraformVersionChecks:   writeOnlyVersionChecks,
		Steps: []resource.TestStep{
			{
				Config: fmt.Sprintf(`
resource "onyx_mcp_server" "per_user" {
  name           = "tf-acc-mcp-wo-rejected"
  server_url     = %q
  auth_type      = "API_TOKEN"
  auth_performer = "PER_USER"
  api_token_wo   = "tf-acc-write-only-token"

  auth_template_headers = {
    "Authorization" = "Bearer {token}"
  }
  admin_credentials = {
    "token" = "tf-acc-token"
  }
}
`, mcpServerURL),
				ExpectError: regexpAPITokenOnPerUserServer,
			},
		},
	})
}

func TestAccCustomToolWriteOnlyHeaders(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		TerraformVersionChecks:   writeOnlyVersionChecks,
		CheckDestroy:             testAccCheckCustomToolDestroyed(t),
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_custom_tool" "wo" {
  name        = "tf-acc-action-write-only"
  description = "Write-only headers"
  definition  = ` + customToolDefinition + `

  custom_headers_wo = {
    "X-Api-Key" = "tf-acc-write-only-header"
  }
  custom_headers_wo_version = 1
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckNoResourceAttr("onyx_custom_tool.wo", "custom_headers"),
					resource.TestCheckNoResourceAttr("onyx_custom_tool.wo", "custom_headers_wo"),
					// Onyx hands header values back in full, so this is a real
					// end-to-end check that the secret arrived.
					testAccCheckCustomToolHeader(t, "onyx_custom_tool.wo", "X-Api-Key", "tf-acc-write-only-header"),
				),
			},
			{
				// The refresh is where a write-only header map could leak:
				// Onyx returns the value, and without the private-state marker
				// it would land in custom_headers.
				RefreshState: true,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckNoResourceAttr("onyx_custom_tool.wo", "custom_headers"),
					testAccCheckCustomToolHeader(t, "onyx_custom_tool.wo", "X-Api-Key", "tf-acc-write-only-header"),
				),
			},
			{
				// Rotation, and proof the new value reaches the server.
				Config: `
resource "onyx_custom_tool" "wo" {
  name        = "tf-acc-action-write-only"
  description = "Write-only headers"
  definition  = ` + customToolDefinition + `

  custom_headers_wo = {
    "X-Api-Key" = "tf-acc-write-only-header-rotated"
  }
  custom_headers_wo_version = 2
}
`,
				Check: resource.ComposeAggregateTestCheckFunc(
					resource.TestCheckNoResourceAttr("onyx_custom_tool.wo", "custom_headers"),
					testAccCheckCustomToolHeader(t, "onyx_custom_tool.wo", "X-Api-Key", "tf-acc-write-only-header-rotated"),
				),
			},
		},
	})
}

// The Authorization-header check has to see a write-only header map too.
func TestAccCustomToolWriteOnlyHeadersRejectConflictingAuth(t *testing.T) {
	resource.Test(t, resource.TestCase{
		PreCheck:                 func() { testAccPreCheck(t) },
		ProtoV6ProviderFactories: testAccProtoV6ProviderFactories,
		TerraformVersionChecks:   writeOnlyVersionChecks,
		Steps: []resource.TestStep{
			{
				Config: `
resource "onyx_custom_tool" "conflict_wo" {
  name             = "tf-acc-conflicting-auth-wo"
  definition       = ` + customToolDefinition + `
  passthrough_auth = true

  custom_headers_wo = {
    "Authorization" = "Bearer nope"
  }
}
`,
				ExpectError: regexpConflictingAuth,
			},
		},
	})
}

// testAccCheckCustomToolHeader reads the header back from Onyx, which returns
// action headers in full rather than masked.
func testAccCheckCustomToolHeader(t *testing.T, name, headerKey, want string) resource.TestCheckFunc {
	return func(state *terraform.State) error {
		rs, ok := state.RootModule().Resources[name]
		if !ok {
			return fmt.Errorf("%s not found in state", name)
		}
		id, err := parseIDString(rs.Primary.ID)
		if err != nil {
			return err
		}
		remote, err := testAccClient(t).GetCustomTool(context.Background(), id)
		if err != nil {
			return fmt.Errorf("reading %s back: %w", name, err)
		}
		for _, header := range remote.CustomHeaders {
			if header.Key != headerKey {
				continue
			}
			if header.Value != want {
				return fmt.Errorf("header %q is %q on the server, want %q", headerKey, header.Value, want)
			}
			return nil
		}
		return fmt.Errorf("header %q is missing from %s on the server", headerKey, name)
	}
}
