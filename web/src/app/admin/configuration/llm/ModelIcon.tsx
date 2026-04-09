import { defaultTailwindCSS } from "@/components/icons/icons";
import { getModelIcon } from "@/lib/llmConfig/providers";
import { IconProps } from "@opal/types";

export interface ModelIconProps extends IconProps {
  provider: string;
  modelName?: string;
}

export default function ModelIcon({
  provider,
  modelName,
  size = 16,
  className = defaultTailwindCSS,
}: ModelIconProps) {
  const Icon = getModelIcon(provider, modelName);
  return <Icon size={size} className={className} />;
}
