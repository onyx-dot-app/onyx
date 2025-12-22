package cmd

import (
	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/openapi"
)

// Default paths relative to git root
const (
	DefaultSchemaPath = "backend/generated/openapi.json"
	DefaultClientDir  = "backend/generated/onyx_openapi_client"
)

// OpenAPIOptions holds options for the openapi command.
type OpenAPIOptions struct {
	OutputPath      string
	SchemaPath      string
	ClientOutputDir string
}

// NewOpenAPICommand creates the parent openapi command.
func NewOpenAPICommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "openapi",
		Short: "OpenAPI schema and client generation",
		Long: `OpenAPI schema and client generation commands.

Generate the OpenAPI schema from the Onyx API without starting the server,
and optionally generate a Python client from the schema.

Requirements:
  - Python with onyx[backend] installed (use the project venv)
  - For client generation: openapi-generator-cli (installed with ods)

Examples:
  ods openapi schema                    # Generate openapi.json
  ods openapi schema -o api.json        # Generate to custom path
  ods openapi client                    # Generate Python client
  ods openapi all                       # Generate schema and client`,
	}

	// Add subcommands
	cmd.AddCommand(NewOpenAPISchemaCommand())
	cmd.AddCommand(NewOpenAPIClientCommand())
	cmd.AddCommand(NewOpenAPIAllCommand())

	return cmd
}

// NewOpenAPISchemaCommand creates the openapi schema command.
func NewOpenAPISchemaCommand() *cobra.Command {
	opts := &OpenAPIOptions{}

	cmd := &cobra.Command{
		Use:   "schema",
		Short: "Generate OpenAPI schema JSON",
		Long: `Generate the OpenAPI schema JSON file from the Onyx API.

This extracts the API schema without starting the full API server.
The schema can be used for documentation, client generation, and API validation.

Requirements:
  - Must be run from within the onyx repository
  - Python with onyx[backend] installed (use the project venv)

Examples:
  ods openapi schema                         # Generate to backend/generated/openapi.json
  ods openapi schema -o ./api.json           # Generate to custom path (relative to cwd)
  ods openapi schema -o /tmp/openapi.json    # Generate to absolute path`,
		Run: func(cmd *cobra.Command, args []string) {
			runOpenAPISchema(opts)
		},
	}

	cmd.Flags().StringVarP(&opts.OutputPath, "output", "o", "", "Output path for the OpenAPI schema (default: backend/generated/openapi.json)")

	return cmd
}

func runOpenAPISchema(opts *OpenAPIOptions) {
	outputPath, err := openapi.ResolvePath(opts.OutputPath, DefaultSchemaPath)
	if err != nil {
		log.Fatalf("Failed to resolve output path: %v", err)
	}

	log.Infof("Generating OpenAPI schema to: %s", outputPath)

	if err := openapi.GenerateSchema(outputPath); err != nil {
		log.Fatalf("Failed to generate OpenAPI schema: %v", err)
	}

	log.Info("Schema generation completed successfully")
}

// NewOpenAPIClientCommand creates the openapi client command.
func NewOpenAPIClientCommand() *cobra.Command {
	opts := &OpenAPIOptions{}

	cmd := &cobra.Command{
		Use:   "client",
		Short: "Generate Python client from OpenAPI schema",
		Long: `Generate a Python client from an OpenAPI schema JSON file.

Uses openapi-generator to create a fully typed Python client package
from the OpenAPI schema. This client can be used for integration testing
and API interactions.

Requirements:
  - openapi-generator-cli (installed with ods dependencies)
  - An existing OpenAPI schema JSON file

Examples:
  ods openapi client                              # Use defaults for schema and output
  ods openapi client -i ./api.json                # Use custom schema path
  ods openapi client -o ./my_client               # Generate to custom directory`,
		Run: func(cmd *cobra.Command, args []string) {
			runOpenAPIClient(opts)
		},
	}

	cmd.Flags().StringVarP(&opts.SchemaPath, "input", "i", "", "Path to the OpenAPI schema JSON file (default: backend/generated/openapi.json)")
	cmd.Flags().StringVarP(&opts.ClientOutputDir, "output", "o", "", "Output directory for the generated client (default: backend/generated/onyx_openapi_client)")

	return cmd
}

func runOpenAPIClient(opts *OpenAPIOptions) {
	schemaPath, err := openapi.ResolvePath(opts.SchemaPath, DefaultSchemaPath)
	if err != nil {
		log.Fatalf("Failed to resolve schema path: %v", err)
	}

	clientDir, err := openapi.ResolvePath(opts.ClientOutputDir, DefaultClientDir)
	if err != nil {
		log.Fatalf("Failed to resolve client output path: %v", err)
	}

	log.Infof("Generating Python client from: %s", schemaPath)
	log.Infof("Output directory: %s", clientDir)

	if err := openapi.GenerateClient(schemaPath, clientDir); err != nil {
		log.Fatalf("Failed to generate Python client: %v", err)
	}

	log.Info("Client generation completed successfully")
}

// NewOpenAPIAllCommand creates the openapi all command.
func NewOpenAPIAllCommand() *cobra.Command {
	opts := &OpenAPIOptions{}

	cmd := &cobra.Command{
		Use:   "all",
		Short: "Generate both OpenAPI schema and Python client",
		Long: `Generate both the OpenAPI schema and Python client in one command.

This is equivalent to running 'ods openapi schema' followed by 'ods openapi client',
but in a single operation.

Requirements:
  - Must be run from within the onyx repository
  - Python with onyx[backend] installed (use the project venv)
  - openapi-generator-cli (installed with ods dependencies)

Examples:
  ods openapi all                                 # Generate schema and client to defaults
  ods openapi all -o ./api.json                   # Use custom schema path
  ods openapi all --client-output ./my_client     # Custom client directory`,
		Run: func(cmd *cobra.Command, args []string) {
			runOpenAPIAll(opts)
		},
	}

	cmd.Flags().StringVarP(&opts.OutputPath, "output", "o", "", "Output path for the OpenAPI schema (default: backend/generated/openapi.json)")
	cmd.Flags().StringVar(&opts.ClientOutputDir, "client-output", "", "Output directory for the generated client (default: backend/generated/onyx_openapi_client)")

	return cmd
}

func runOpenAPIAll(opts *OpenAPIOptions) {
	schemaPath, err := openapi.ResolvePath(opts.OutputPath, DefaultSchemaPath)
	if err != nil {
		log.Fatalf("Failed to resolve schema path: %v", err)
	}

	clientDir, err := openapi.ResolvePath(opts.ClientOutputDir, DefaultClientDir)
	if err != nil {
		log.Fatalf("Failed to resolve client output path: %v", err)
	}

	log.Infof("Generating OpenAPI schema and Python client")
	log.Infof("Schema output: %s", schemaPath)
	log.Infof("Client output: %s", clientDir)

	if err := openapi.GenerateAll(schemaPath, clientDir); err != nil {
		log.Fatalf("Failed to generate OpenAPI schema and client: %v", err)
	}

	log.Info("Generation completed successfully")
}
