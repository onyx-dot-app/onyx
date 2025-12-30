import { defaultTailwindCSS, IconProps } from "@/components/icons/icons";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";

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
  const Icon = getProviderIcon(provider, modelName);
  return <Icon size={size} className={className} />;
};
