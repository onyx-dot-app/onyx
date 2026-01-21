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
import { LineItemLayout } from "@/layouts/general-layouts";
import { IconProps } from "@opal/types";

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
    <Card variant="tertiary">
      <LineItemLayout
        icon={Icon}
        title={title}
        description={description}
        variant="tertiary-muted"
      />
    </Card>
  );
}
