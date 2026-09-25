import { defaultTailwindCSS } from "@/components/icons/icons";
import { getModelIcon } from "@/lib/languageModels";
import type { IconProps } from "@opal/types";

export interface ModelIconProps extends IconProps {
  provider: string;
  modelName?: string;
}

export function ModelIcon({
  provider,
  modelName,
  size = 16,
  className = defaultTailwindCSS,
}: ModelIconProps) {
  const Icon = getModelIcon(provider, modelName);
  return <Icon size={size} className={className} />;
}
