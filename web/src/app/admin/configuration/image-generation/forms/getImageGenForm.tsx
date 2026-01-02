import React from "react";
import { ImageGenFormBaseProps } from "./types";
import { OpenAIImageGenForm } from "./OpenAIImageGenForm";
import { AzureImageGenForm } from "./AzureImageGenForm";

/**
 * Factory function that routes to the correct provider-specific form
 * based on the imageProvider.provider_name.
 */
export function getImageGenForm(props: ImageGenFormBaseProps): React.ReactNode {
  const providerName = props.imageProvider.provider_name;

  switch (providerName) {
    case "openai":
      return <OpenAIImageGenForm {...props} />;
    case "azure":
      return <AzureImageGenForm {...props} />;
    default:
      // Fallback to OpenAI form for unknown providers
      console.warn(
        `Unknown image provider: ${providerName}, falling back to OpenAI form`
      );
      return <OpenAIImageGenForm {...props} />;
  }
}
