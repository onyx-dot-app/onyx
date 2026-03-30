"use client";

import { ModalCreationInterface } from "@/refresh-components/contexts/ModalContext";
import { ImageProvider } from "./constants";
import { LLMProviderView } from "@/interfaces/llm";
import { ImageGenerationConfigView } from "./svc";
import { getImageGenForm } from "./forms";

interface Props {
  modal: ModalCreationInterface;
  imageProvider: ImageProvider;
  existingProviders: LLMProviderView[];
  existingConfig?: ImageGenerationConfigView;
  onSuccess: () => void;
}

/**
 * Modal for creating/editing image generation configurations.
 * Routes to provider-specific forms based on imageProvider.provider_name.
 */
export default function ImageGenerationConnectionModal(props: Props) {
  return <>{getImageGenForm(props)}</>;
}
