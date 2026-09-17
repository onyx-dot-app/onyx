import { LLMProviderView } from "@/lib/languageModels/types";

const getApiVersionParam = (url: URL): string => {
  const directApiVersion = url.searchParams.get("api-version");
  if (directApiVersion?.trim()) {
    return directApiVersion.trim();
  }

  let normalized: string | null = null;
  url.searchParams.forEach((value, key) => {
    if (normalized) {
      return;
    }
    if (key.toLowerCase() === "api-version" && value?.trim()) {
      normalized = value.trim();
    }
  });

  return normalized ?? "";
};

const getDeploymentNameParam = (url: URL): string => {
  const match = url.pathname.match(/\/openai\/deployments\/([^/]+)/i);
  const deployment = match?.[1] ?? "";
  return deployment ? deployment.toLowerCase() : "";
};

const isResponsesPath = (url: URL): boolean =>
  /\/openai\/responses/i.test(url.pathname);

export const parseAzureTargetUri = (
  rawUri: string
): {
  url: URL;
  apiVersion: string;
  deploymentName: string;
  isResponsesPath: boolean;
} => {
  const url = new URL(rawUri);
  return {
    url,
    apiVersion: getApiVersionParam(url),
    deploymentName: getDeploymentNameParam(url),
    isResponsesPath: isResponsesPath(url),
  };
};

export const isValidAzureTargetUri = (rawUri: string): boolean => {
  try {
    const { apiVersion, deploymentName, isResponsesPath } =
      parseAzureTargetUri(rawUri);

    return Boolean(apiVersion) && (Boolean(deploymentName) || isResponsesPath);
  } catch {
    return false;
  }
};

/**
 * Reconstructs the Azure "target URI" that pre-fills the edit form for an
 * existing provider.
 *
 * When the provider routes per-model (no provider-level `deployment_name`), we
 * emit the deployment-less `/openai/responses` form instead of injecting a
 * placeholder deployment. Fabricating a deployment here caused
 * `parseAzureTargetUri` to persist that bogus value on save, routing every
 * model to a non-existent deployment and breaking the provider with Azure
 * `DeploymentNotFound` (issue #13590). The path is discarded on save
 * (`processValues` keeps only `url.origin`); it exists solely so the parsed URI
 * round-trips back to the same `api_base`, `api_version`, and deployment.
 */
export const buildTargetUri = (
  existingLlmProvider?: LLMProviderView
): string => {
  if (!existingLlmProvider?.api_base || !existingLlmProvider?.api_version) {
    return "";
  }

  const { api_base, api_version, deployment_name } = existingLlmProvider;

  if (!deployment_name) {
    return `${api_base}/openai/responses?api-version=${api_version}`;
  }

  return `${api_base}/openai/deployments/${deployment_name}/chat/completions?api-version=${api_version}`;
};
