import { Card } from "@opal/components";
import { ContentAction, Section } from "@opal/layouts";
import type { RichStr } from "@opal/types";

interface SettingsSectionProps {
  title: string | RichStr;
  description?: string | RichStr;
  /** Shown at the right of the title, e.g. a link to a guide. */
  rightChildren?: React.ReactNode;
  children: React.ReactNode;
}

/** A titled card of setting rows on a user settings tab. */
export default function SettingsSection({
  title,
  description,
  rightChildren,
  children,
}: SettingsSectionProps) {
  return (
    <Section gap={3}>
      <ContentAction
        font="main-content-emphasis"
        title={title}
        description={description}
        rightChildren={rightChildren}
        width="full"
        padding={0}
        center
      />
      <Card border="solid" rounding={4}>
        <Section alignItems="start" height="fit">
          {children}
        </Section>
      </Card>
    </Section>
  );
}
