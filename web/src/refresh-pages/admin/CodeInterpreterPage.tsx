"use client";

import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Card } from "@/refresh-components/cards";
import { SvgRefreshCw, SvgTerminal, SvgUnplug } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";

function DisconnectButton() {
  return <IconButton tertiary icon={SvgUnplug} />;
}

function RefreshButton() {
  return <IconButton tertiary icon={SvgRefreshCw} />;
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
          <Section
            flexDirection="row"
            padding={0}
            gap={0}
            justifyContent="between"
            alignItems="center"
          >
            <Section flexDirection="row" padding={0} gap={0} alignItems="start">
              <SvgTerminal size={18} />
              <Section flexDirection="column" padding={0} gap={0}>
                <Text mainContentBody>Code Interpreter</Text>
                <Text secondaryBody text03>
                  Built-in Python runtime
                </Text>
              </Section>
            </Section>
            <Section
              flexDirection="column"
              padding={0}
              gap={0.5}
              alignItems="end"
            >
              <Text>Connected</Text>
              <Section flexDirection="row" padding={0} gap={0}>
                <DisconnectButton />
                <RefreshButton />
              </Section>
            </Section>
          </Section>
        </Card>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
