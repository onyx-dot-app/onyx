"use client";

import { ModalCreationInterface } from "@/refresh-components/contexts/ModalContext";
import { ImageProvider } from "@/app/admin/configuration/image-generation/constants";
import { LLMProviderView } from "@/app/admin/configuration/llm/interfaces";
import { ImageGenerationConfigView } from "@/lib/configuration/imageConfigurationService";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { getImageGenForm } from "./forms";

interface Props {
  modal: ModalCreationInterface;
  imageProvider: ImageProvider;
  existingProviders: LLMProviderView[];
  existingConfig?: ImageGenerationConfigView;
  onSuccess: () => void;
  setPopup: (popup: PopupSpec | null) => void;
}

/**
 * Modal for creating/editing image generation configurations.
 * Routes to provider-specific forms based on imageProvider.provider_name.
 */
export default function ImageGenerationConnectionModal(props: Props) {
  return <>{getImageGenForm(props)}</>;
}
