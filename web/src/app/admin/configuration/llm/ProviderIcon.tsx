import { defaultTailwindCSS, IconProps } from "@/components/icons/icons";
import { getModelIcon } from "@/lib/llmConfig/providers";

export interface ProviderIconProps extends IconProps {
  provider: string;
  modelName?: string;
}

export const ProviderIcon = ({
  provider,
  modelName,
  size = 16,
  className = defaultTailwindCSS,
}: ProviderIconProps) => {
  const Icon = getModelIcon(provider, modelName);
  return <Icon size={size} className={className} />;
};
