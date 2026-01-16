/**
 * EmptyMessage - A component for displaying empty state messages
 *
 * Displays a translucent card with an icon and message text to indicate
 * when no data or content is available.
 *
 * Features:
 * - Translucent card background with dashed border
 * - Horizontal layout with icon on left, text on right
 * - 0.5rem gap between icon and text
 * - Accepts string children for the message text
 * - Customizable icon
 *
 * @example
 * ```tsx
 * import EmptyMessage from "@/refresh-components/EmptyMessage";
 * import { SvgActivity } from "@opal/icons";
 *
 * // Basic usage
 * <EmptyMessage icon={SvgActivity}>
 *   No connectors set up for your organization.
 * </EmptyMessage>
 *
 * // With different icon
 * <EmptyMessage icon={SvgFileText}>
 *   No documents available.
 * </EmptyMessage>
 * ```
 */

import { SvgEmpty } from "@opal/icons";
import Card from "@/refresh-components/cards/Card";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { IconProps } from "@opal/types";
import { cn } from "@/lib/utils";

export interface EmptyMessageProps {
  icon?: React.FunctionComponent<IconProps>;
  title: string;
  description?: string;
}

export default function EmptyMessage({
  icon: Icon = SvgEmpty,
  title,
  description,
}: EmptyMessageProps) {
  return (
    <Card translucent>
      <Section
        flexDirection="row"
        justifyContent="start"
        alignItems={!!description ? "start" : "center"}
        gap={0.5}
      >
        <div className={cn(description && "mt-0.5")}>
          <Icon size={16} className="stroke-text-03" />
        </div>
        <Section alignItems="start" gap={0}>
          <Text text03>{title}</Text>
          {description && (
            <Text text03 secondaryBody>
              {description}
            </Text>
          )}
        </Section>
      </Section>
    </Card>
  );
}
