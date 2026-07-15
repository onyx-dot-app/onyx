// terraform-provider-onyx manages Onyx application configuration (LLM
// providers, API keys, workspace settings, ...) declaratively via the Onyx
// admin API. It provisions what runs *inside* an Onyx deployment — for the
// infrastructure that runs Onyx itself, see deployment/terraform.
package main

import (
	"context"
	"flag"
	"log"

	"github.com/hashicorp/terraform-plugin-framework/providerserver"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/provider"
)

// Docs are generated from schema descriptions + examples/ into docs/.
// Requires the terraform CLI on PATH.
//go:generate go run github.com/hashicorp/terraform-plugin-docs/cmd/tfplugindocs@latest generate

// version is set via ldflags on release builds.
var version = "dev"

func main() {
	var debug bool
	flag.BoolVar(&debug, "debug", false, "run the provider with support for debuggers like delve")
	flag.Parse()

	err := providerserver.Serve(context.Background(), provider.New(version), providerserver.ServeOpts{
		Address: "registry.terraform.io/onyx-dot-app/onyx",
		Debug:   debug,
	})
	if err != nil {
		log.Fatal(err)
	}
}
