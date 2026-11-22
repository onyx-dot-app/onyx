import type { ReactNode } from "react";
import { Section } from "@opal/layouts";

interface OutputPanelLayoutProps {
  // The header row: the panel's tab strip
  tabStrip: ReactNode;
  // The row below it, such as the URL bar
  toolbar?: ReactNode;
  // Messages between the toolbar and the content
  notices?: ReactNode;
  // Room at the header's end for controls that the host places over it
  headerControlWidth?: number;
  "data-testid"?: string;
  children: ReactNode;
}

/**
 * The frame of an output panel: Craft's workspace panel and the chat's right
 * panel. A tab strip header, a toolbar, then the active tab's content.
 */
export function OutputPanelLayout({
  tabStrip,
  toolbar,
  notices,
  headerControlWidth = 0,
  "data-testid": testId,
  children,
}: OutputPanelLayoutProps) {
  return (
    <Section
      gap={0}
      justifyContent="start"
      alignItems="stretch"
      className="min-w-0"
      data-testid={testId}
    >
      <Section
        flexDirection="row"
        justifyContent="start"
        gap={0}
        height={3.25}
        className="shrink-0"
      >
        <div
          className="min-w-0 flex-1 ps-3"
          style={{ paddingInlineEnd: headerControlWidth }}
        >
          {tabStrip}
        </div>
      </Section>
      {toolbar}
      {notices}
      <div className="relative min-h-0 flex-1 overflow-hidden">{children}</div>
    </Section>
  );
}
