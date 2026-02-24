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
import LineItem from "@/refresh-components/buttons/LineItem";
import * as GeneralLayouts from "@/layouts/general-layouts";

function DisconnectButton() {
  return <IconButton tertiary icon={SvgUnplug} />;
}

function RefreshButton() {
  return <IconButton tertiary icon={SvgRefreshCw} />;
}

function ConnectionStatus() {
  return (
    <Section flexDirection="row" gap={0.5} padding={0} justifyContent="end">
      <Text mainUiAction text03>
        Connected
      </Text>
      <SvgCheckCircle size={16} color="green" />
    </Section>
  );
}

function ActionButtons() {
  return (
    <GeneralLayouts.Section flexDirection="row" justifyContent="end" gap={0}>
      <DisconnectButton />
      <RefreshButton />
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
      />

      <SettingsLayouts.Body>
        <Card padding={1}>
          <Section flexDirection="row" alignItems="start" padding={0} gap={0}>
            <GeneralLayouts.LineItemLayout
              icon={SvgTerminal}
              title="Code Interpreter"
              description="Built-in Python runtime"
              variant="tertiary"
            />
            <GeneralLayouts.Section flexDirection="column" gap={0.5}>
              <ConnectionStatus />
              <ActionButtons />
            </GeneralLayouts.Section>
          </Section>
        </Card>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
