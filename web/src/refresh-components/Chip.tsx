import Text from "@/refresh-components/texts/Text";
import type { IconProps } from "@opal/types";

export interface ChipProps {
  children?: string;
  icon?: React.FunctionComponent<IconProps>;
}

/**
 * A simple chip/tag component for displaying metadata.
 *
 * @example
 * ```tsx
 * <Chip>Tag Name</Chip>
 * <Chip icon={SvgUser}>John Doe</Chip>
 * ```
 */
export default function Chip({ children, icon: Icon }: ChipProps) {
  return (
    <div className="flex items-center gap-1 px-1.5 py-0.5 rounded-08 bg-background-tint-02">
      {Icon && <Icon size={12} className="text-text-03" />}
      {children && (
        <Text figureSmallLabel text03>
          {children}
        </Text>
      )}
    </div>
  );
}
