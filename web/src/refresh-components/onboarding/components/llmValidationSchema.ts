import * as Yup from "yup";

export const getValidationSchema = (
  providerName: string | undefined,
  activeTab: string
) => {
  if (!providerName) {
    return Yup.object().shape({});
  }

  const baseSchema: Record<string, any> = {
    default_model_name: Yup.string().required("Model name is required"),
  };

  // Handle custom provider validation
  if (providerName === "custom") {
    return Yup.object().shape({
      provider: Yup.string().required("Provider is required"),
      api_key: Yup.string(),
      api_base: Yup.string(),
      api_version: Yup.string(),
      model_configurations: Yup.array()
        .of(
          Yup.object({
            name: Yup.string().required("Model name is required"),
            is_visible: Yup.boolean().required("Visibility is required"),
            max_input_tokens: Yup.number()
              .transform((value, originalValue) =>
                originalValue === "" ||
                originalValue === undefined ||
                originalValue === null
                  ? null
                  : value
              )
              .nullable()
              .optional(),
          })
        )
        .min(1, "At least one model configuration is required"),
      default_model_name: Yup.string().required("Default model is required"),
      fast_default_model_name: Yup.string().nullable(),
      custom_config: Yup.object(),
    });
  }

  switch (providerName) {
    case "openai":
      return Yup.object().shape({
        ...baseSchema,
        api_key: Yup.string().required("API Key is required"),
      });

    case "ollama_chat":
      if (activeTab === "self-hosted") {
        return Yup.object().shape({
          ...baseSchema,
          api_base: Yup.string().required("API Base is required"),
        });
      } else if (activeTab === "cloud") {
        return Yup.object().shape({
          ...baseSchema,
          custom_config: Yup.object().shape({
            OLLAMA_API_KEY: Yup.string().required("API Key is required"),
          }),
        });
      }
      // Fallback for other tabs
      return Yup.object().shape(baseSchema);

    case "anthropic":
      return Yup.object().shape({
        ...baseSchema,
        api_key: Yup.string().required("API Key is required"),
      });

    case "azure":
      return Yup.object().shape({
        ...baseSchema,
        api_key: Yup.string().required("API Key is required"),
        target_uri: Yup.string()
          .required("Target URI is required")
          .test(
            "valid-target-uri",
            "Target URI must be a valid URL with api-version query parameter and either a deployment name in the path (/openai/deployments/{name}/...) or /openai/responses for realtime",
            (value) => {
              if (!value) return false;
              try {
                const url = new URL(value);
                const hasApiVersion = !!url.searchParams
                  .get("api-version")
                  ?.trim();

                // Check if the path contains a valid Azure OpenAI endpoint:
                // 1. /openai/deployments/{deployment-name}/... (standard pattern)
                // 2. /openai/responses (realtime/streaming responses)
                const pathMatch = url.pathname.match(
                  /\/openai\/(deployments\/[^\/]+|responses)/
                );
                const hasDeploymentName =
                  pathMatch && pathMatch[1]?.startsWith("deployments/");
                const isResponsesPath =
                  pathMatch && pathMatch[1] === "responses";
                const hasValidPath = hasDeploymentName || isResponsesPath;

                return hasApiVersion && hasValidPath;
              } catch (error) {
                console.error("URL parsing error:", error);
                return false;
              }
            }
          ),
      });

    case "vertex_ai":
      return Yup.object().shape({
        ...baseSchema,
        custom_config: Yup.object().shape({
          vertex_credentials: Yup.string().required(
            "Credentials File is required"
          ),
        }),
      });

    case "openrouter":
      return Yup.object().shape({
        ...baseSchema,
        api_base: Yup.string().required("API Base is required"),
        api_key: Yup.string().required("API Key is required"),
      });

    case "bedrock":
      return Yup.object().shape({
        ...baseSchema,
        custom_config: Yup.object().shape({
          AWS_REGION_NAME: Yup.string().required("AWS Region Name is required"),
          AWS_ACCESS_KEY_ID: Yup.string().when("BEDROCK_AUTH_METHOD", {
            is: "access_key",
            then: (schema) => schema.required("AWS Access Key ID is required"),
            otherwise: (schema) => schema,
          }),
          AWS_SECRET_ACCESS_KEY: Yup.string().when("BEDROCK_AUTH_METHOD", {
            is: "access_key",
            then: (schema) =>
              schema.required("AWS Secret Access Key is required"),
            otherwise: (schema) => schema,
          }),
          AWS_BEARER_TOKEN_BEDROCK: Yup.string().when("BEDROCK_AUTH_METHOD", {
            is: "long_term_api_key",
            then: (schema) => schema.required("Long-term API Key is required"),
            otherwise: (schema) => schema,
          }),
        }),
      });

    default:
      // Fallback for any other providers
      return Yup.object().shape(baseSchema);
  }
};
