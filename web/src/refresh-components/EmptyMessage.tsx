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
import * as GeneralLayouts from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";

export interface EmptyMessageProps {
  children: string;
}

export default function EmptyMessage({ children }: EmptyMessageProps) {
  return (
    <Card translucent>
      <GeneralLayouts.Section
        flexDirection="row"
        justifyContent="start"
        gap={0.5}
      >
        <SvgEmpty size={16} className="stroke-text-03" />
        <Text text03>{children}</Text>
      </GeneralLayouts.Section>
    </Card>
  );
}
