import Text from "@/refresh-components/texts/Text";
import { SvgX } from "@opal/icons";
import type { IconProps } from "@opal/types";

export interface ChipProps {
  children?: string;
  icon?: React.FunctionComponent<IconProps>;
  onRemove?: () => void;
  smallLabel?: boolean;
}

/**
 * A simple chip/tag component for displaying metadata.
 * Supports an optional remove button via the `onRemove` prop.
 *
 * @example
 * ```tsx
 * <Chip>Tag Name</Chip>
 * <Chip icon={SvgUser}>John Doe</Chip>
 * <Chip onRemove={() => removeTag(id)}>Removable</Chip>
 * ```
 */
export default function Chip({
  children,
  icon: Icon,
  onRemove,
  smallLabel = true,
}: ChipProps) {
  return (
    <div className="flex items-center gap-1 px-1.5 py-0.5 rounded-08 bg-background-tint-02">
      {Icon && <Icon size={12} className="text-text-03" />}
      {children && (
        <Text figureSmallLabel={smallLabel} text03>
          {children}
        </Text>
      )}
      {onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="flex items-center justify-center shrink-0 rounded-full hover:bg-background-tint-04 transition-colors"
        >
          <SvgX size={12} className="text-text-03" />
        </button>
      )}
    </div>
  );
}
