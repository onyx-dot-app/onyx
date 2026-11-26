/** An image generation config: a model that can generate images. */
export interface ImageGenerationConfigView {
  image_provider_id: string;
  model_configuration_id: number;
  model_name: string;
  llm_provider_id: number;
  llm_provider_name: string | null;
  llm_provider_type: string;
  llm_provider_owned: boolean;
  is_default: boolean;
}

/** An image model an LLM provider can serve; connected when it has an
 *  `image_provider_id`. */
export interface ImageGenerationProviderModel {
  name: string;
  display_name: string | null;
  is_recommended: boolean;
  image_provider_id: string | null;
}

/** An LLM provider with the image models it can serve. */
export interface ImageGenerationLLMProvider {
  llm_provider_id: number;
  llm_provider_name: string | null;
  provider: string;
  is_public: boolean;
  models: ImageGenerationProviderModel[];
}
