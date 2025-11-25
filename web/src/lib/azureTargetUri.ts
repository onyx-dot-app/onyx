const getApiVersionParam = (url: URL): string => {
  const directApiVersion = url.searchParams.get("api-version");
  if (directApiVersion?.trim()) {
    return directApiVersion.trim();
  }

  for (const [key, value] of url.searchParams.entries()) {
    if (key.toLowerCase() === "api-version" && value?.trim()) {
      return value.trim();
    }
  }

  return "";
};

const getDeploymentNameParam = (url: URL): string => {
  const match = url.pathname.match(/\/openai\/deployments\/([^/]+)/i);
  return match?.[1] ?? "";
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
