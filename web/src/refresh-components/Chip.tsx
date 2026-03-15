import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { SvgX } from "@opal/icons";
import { Button } from "@opal/components";
import type { IconProps } from "@opal/types";

export interface ChipProps {
  children?: string;
  icon?: React.FunctionComponent<IconProps>;
  /** Icon rendered after the label (e.g. a warning indicator) */
  rightIcon?: React.FunctionComponent<IconProps>;
  onRemove?: () => void;
  smallLabel?: boolean;
  /** When true, applies error styling (red tint background + red right icon). */
  error?: boolean;
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
  rightIcon: RightIcon,
  onRemove,
  smallLabel = true,
  error = false,
}: ChipProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-1 px-1.5 py-0.5 rounded-08",
        "bg-background-tint-02"
      )}
    >
      {Icon && <Icon size={12} className="text-text-03" />}
      {children && (
        <Text figureSmallLabel={smallLabel} text03>
          {children}
        </Text>
      )}
      {RightIcon && (
        <RightIcon
          size={14}
          className={cn(error ? "text-status-warning-05" : "text-text-03")}
        />
      )}
      {onRemove && (
        <Button
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          prominence="tertiary"
          icon={SvgX}
          size="xs"
        />
      )}
    </div>
  );
}
