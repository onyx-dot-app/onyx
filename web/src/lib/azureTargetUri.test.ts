import {
  buildTargetUri,
  isValidAzureTargetUri,
  parseAzureTargetUri,
} from "@/lib/azureTargetUri";
import { LLMProviderView } from "@/lib/languageModels/types";

const baseProvider: LLMProviderView = {
  id: 1,
  name: "azure",
  provider: "azure",
  api_key: "sk-test",
  api_base: "https://my-resource.openai.azure.com",
  api_version: "2025-01-01-preview",
  custom_config: null,
  is_public: true,
  is_auto_mode: true,
  groups: [],
  personas: [],
  deployment_name: null,
  model_configurations: [],
};

describe("buildTargetUri", () => {
  it("returns an empty string when api_base or api_version is missing", () => {
    expect(buildTargetUri(undefined)).toBe("");
    expect(buildTargetUri({ ...baseProvider, api_base: null })).toBe("");
    expect(buildTargetUri({ ...baseProvider, api_version: null })).toBe("");
  });

  it("does not fabricate a deployment for per-model-routing providers (#13590)", () => {
    // A provider created with deployment_name === null routes each model to a
    // deployment named after the model. Editing it must NOT invent a
    // provider-level deployment, which previously produced the placeholder
    // "your-deployment" and broke every model with Azure DeploymentNotFound.
    const uri = buildTargetUri(baseProvider);

    expect(uri).not.toContain("your-deployment");
    expect(uri).not.toContain("/openai/deployments/");
    expect(isValidAzureTargetUri(uri)).toBe(true);

    // The reconstructed URI round-trips back to an empty deployment, so on save
    // `processValues` keeps deployment_name null rather than fabricating one.
    const parsed = parseAzureTargetUri(uri);
    expect(parsed.deploymentName).toBe("");
    expect(parsed.apiVersion).toBe("2025-01-01-preview");
    expect(parsed.url.origin).toBe("https://my-resource.openai.azure.com");
  });

  it("round-trips a provider that has an explicit deployment_name", () => {
    const provider: LLMProviderView = {
      ...baseProvider,
      deployment_name: "gpt-4o",
    };
    const uri = buildTargetUri(provider);

    expect(uri).toContain("/openai/deployments/gpt-4o/chat/completions");
    expect(isValidAzureTargetUri(uri)).toBe(true);

    const parsed = parseAzureTargetUri(uri);
    expect(parsed.deploymentName).toBe("gpt-4o");
    expect(parsed.apiVersion).toBe("2025-01-01-preview");
    expect(parsed.url.origin).toBe("https://my-resource.openai.azure.com");
  });
});
