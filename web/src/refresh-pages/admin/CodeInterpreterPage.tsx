"use client";

import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Card } from "@/refresh-components/cards";
import {
  SvgCheckCircle,
  SvgRefreshCw,
  SvgTerminal,
  SvgUnplug,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";
import * as GeneralLayouts from "@/layouts/general-layouts";

function ConnectionStatus() {
  return (
    <Section
      flexDirection="row"
      gap={0.4}
      padding={0}
      justifyContent="end"
      alignItems="center"
    >
      <Text mainUiAction text03>
        Connected
      </Text>
      <SvgCheckCircle size={16} className="text-status-success-05" />
    </Section>
  );
}

function ActionButtons() {
  return (
    <GeneralLayouts.Section
      flexDirection="row"
      justifyContent="end"
      gap={0.2}
      padding={0}
    >
      <IconButton tertiary icon={SvgUnplug} tooltip="Disconnect" />
      <IconButton tertiary icon={SvgRefreshCw} tooltip="Refresh" />
    </GeneralLayouts.Section>
  );
}

export default function CodeInterpreterPage() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgTerminal}
        title="Code Interpreter"
        description="Safe and sandboxed Python runtime available to your LLM. See docs for more details."
        separator
      />

      <SettingsLayouts.Body>
        <Card>
          <Section flexDirection="row" alignItems="start" padding={0} gap={0}>
            <GeneralLayouts.LineItemLayout
              icon={SvgTerminal}
              title="Code Interpreter"
              description="Built-in Python runtime"
              variant="tertiary"
            />
            <GeneralLayouts.Section flexDirection="column" gap={0.2}>
              <ConnectionStatus />
              <ActionButtons />
            </GeneralLayouts.Section>
          </Section>
        </Card>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
