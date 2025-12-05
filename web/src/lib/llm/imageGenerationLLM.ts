import { ImageGenerationProvider } from "@/app/admin/configuration/llm/interfaces";

// TODO: This returns all models for all providers that have any image generation models.
// This is not ideal as it returns all models for all providers that have any image generation models.
// We should return a minimal list of providers that have any image generation models.

export async function fetchImageGenerationProviders(): Promise<
  ImageGenerationProvider[]
> {
  const response = await fetch("/api/admin/llm/image-generation-providers", {
    headers: {
      "Content-Type": "application/json",
    },
  });
  if (!response.ok) {
    throw new Error(
      `Failed to fetch image generation providers: ${await response.text()}`
    );
  }
  return response.json();
}
