import type { ReactNode } from "react";
import { Text } from "@opal/components";
import { Section } from "@opal/layouts";
import type { RichStr } from "@opal/types";
import { cn } from "@opal/utils";

interface WorkspaceHomeProps {
  title: string | RichStr;
  children: ReactNode;
  wide?: boolean;
}

export function WorkspaceHome({
  title,
  children,
  wide = false,
}: WorkspaceHomeProps) {
  return (
    <Section
      flexDirection="row"
      justifyContent="center"
      alignItems="start"
      gap={0}
      padding={6}
      className="overflow-auto"
    >
      {/* With the padding, the content starts 2rem from the top */}
      <Section
        alignItems="stretch"
        justifyContent="start"
        height="auto"
        gap={1.5}
        className={cn("mt-2", wide ? "max-w-3xl" : "max-w-xs")}
      >
        <div className="pb-3 text-center">
          <Text font="main-ui-muted" color="text-05">
            {title}
          </Text>
        </div>
        {children}
      </Section>
    </Section>
  );
}
