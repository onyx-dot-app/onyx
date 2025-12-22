"use client";

import { useState } from "react";
import Text from "@/refresh-components/texts/Text";
import { Select } from "@/refresh-components/card";
import { IMAGE_PROVIDER_GROUPS, ImageProvider } from "./constants";

export default function ImageGenerationContent() {
  // Mock state - will be replaced with backend integration later
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(
    "gpt-image-1"
  );
  const [connectedProviders] = useState<Set<string>>(
    new Set(["gpt-image-1", "dall-e-3"])
  );

  const getStatus = (
    provider: ImageProvider
  ): "disconnected" | "connected" | "selected" => {
    if (selectedProviderId === provider.id) return "selected";
    if (connectedProviders.has(provider.id)) return "connected";
    return "disconnected";
  };

  const handleConnect = (id: string) => {
    // TODO: Open connection modal
    console.log("Connect:", id);
  };

  const handleSelect = (id: string) => {
    setSelectedProviderId(id);
  };

  const handleDeselect = () => {
    setSelectedProviderId(null);
  };

  const handleEdit = (id: string) => {
    // TODO: Open edit modal
    console.log("Edit:", id);
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Section Header */}
      <div className="flex flex-col gap-0.5">
        <Text mainContentEmphasis text05>
          Image Generation Model
        </Text>
        <Text secondaryBody text03>
          Select a model to generate images in chat.
        </Text>
      </div>

      {/* Provider Groups */}
      {IMAGE_PROVIDER_GROUPS.map((group) => (
        <div key={group.name} className="flex flex-col gap-2">
          <Text secondaryBody text03>
            {group.name}
          </Text>
          <div className="flex flex-col gap-2">
            {group.providers.map((provider) => (
              <Select
                key={provider.id}
                icon={provider.icon}
                title={provider.title}
                description={provider.description}
                status={getStatus(provider)}
                onConnect={() => handleConnect(provider.id)}
                onSelect={() => handleSelect(provider.id)}
                onDeselect={() => handleDeselect()}
                onEdit={() => handleEdit(provider.id)}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
