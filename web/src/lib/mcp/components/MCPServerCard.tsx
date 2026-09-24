"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useFormikContext } from "formik";
import { Button, Card, InputTypeIn, ShadowDiv } from "@opal/components";
import { Disabled } from "@opal/core";
import { Card as CardLayout, InputHorizontal, Section } from "@opal/layouts";
import { SvgExpand, SvgFold, SvgSimpleLoader, SvgSliders } from "@opal/icons";
import SwitchField from "@/refresh-components/form/SwitchField";
import useFilter from "@/hooks/useFilter";
import EnabledCount from "@/lib/tools/components/EnabledCount";
import { getActionIcon } from "@/lib/tools/utils";
import type {
  AgentEditorMCPServer,
  MCPServersFormValues,
  MCPTool,
} from "@/lib/mcp/types";

export interface MCPServerCardProps {
  server: AgentEditorMCPServer;
  tools: MCPTool[];
  isLoading: boolean;
}

/**
 * One MCP server in the agent editor: a switch for the server, and a
 * searchable, foldable list of its tools with a switch each. Every row is a
 * label for its switch, so clicking the title toggles it.
 */
export default function MCPServerCard({
  server,
  tools: enabledTools,
  isLoading,
}: MCPServerCardProps) {
  const t = useTranslations("agents");
  const [isFolded, setIsFolded] = useState(false);
  const { values, setFieldValue } = useFormikContext<MCPServersFormValues>();
  const serverFieldName = `mcp_server_${server.id}` as const;
  const serverEnabledField = `${serverFieldName}.enabled`;
  const isServerEnabled = values[serverFieldName]?.enabled ?? false;
  const {
    query,
    setQuery,
    filtered: filteredTools,
  } = useFilter(enabledTools, (tool) => `${tool.name} ${tool.description}`);

  const isToolEnabled = (tool: MCPTool) =>
    values[serverFieldName]?.[`tool_${tool.id}`] === true;
  const enabledCount = enabledTools.filter(isToolEnabled).length;
  const hasTools = enabledTools.length > 0 && filteredTools.length > 0;

  let cardContent: React.ReactNode | undefined;
  if (isLoading) {
    cardContent = (
      <Section padding={4}>
        <SvgSimpleLoader />
      </Section>
    );
  } else if (hasTools) {
    cardContent = (
      <ShadowDiv className="max-h-[20rem]" shadowHeight={2}>
        <Section gap={2} padding={2} alignItems="stretch">
          {filteredTools.map((tool) => {
            const toolFieldName = `${serverFieldName}.tool_${tool.id}`;
            return (
              <Disabled
                key={tool.id}
                disabled={!tool.isAvailable || !isServerEnabled}
              >
                <Card
                  border="solid"
                  rounding={3}
                  padding={2}
                  color={
                    isToolEnabled(tool) ? "background-tint-00" : "transparent"
                  }
                >
                  <InputHorizontal
                    withLabel={toolFieldName}
                    icon={tool.icon ?? SvgSliders}
                    title={tool.name}
                    description={tool.description}
                  >
                    <SwitchField
                      name={toolFieldName}
                      disabled={!isServerEnabled}
                    />
                  </InputHorizontal>
                </Card>
              </Disabled>
            );
          })}
        </Section>
      </ShadowDiv>
    );
  }

  return (
    <Disabled
      disabled={!server.can_attach}
      tooltip={t("editor.mcp.noAccess.tooltip")}
    >
      <Card
        expandable
        expanded={!isFolded}
        border="solid"
        rounding={4}
        padding={2}
        expandedContent={cardContent}
      >
        <CardLayout.Header
          bottomChildren={
            <Section flexDirection="row" gap={2}>
              <InputTypeIn
                placeholder={t("editor.mcp.searchTools.placeholder")}
                variant="internal"
                searchIcon
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                // Searching only makes sense against a visible list.
                onFocus={() => setIsFolded(false)}
              />
              {enabledTools.length > 0 && (
                <Button
                  prominence="internal"
                  rightIcon={isFolded ? SvgExpand : SvgFold}
                  aria-expanded={!isFolded}
                  onClick={() => setIsFolded((prev) => !prev)}
                >
                  {isFolded
                    ? t("modals.viewer.mcpCard.expand.label")
                    : t("modals.viewer.mcpCard.fold.label")}
                </Button>
              )}
            </Section>
          }
        >
          <Section padding={2} alignItems="stretch">
            <InputHorizontal
              withLabel={serverEnabledField}
              icon={getActionIcon(server.server_url, server.name)}
              title={server.name}
              description={server.description}
            >
              <Section flexDirection="row" gap={2} alignItems="start">
                <EnabledCount
                  enabledCount={enabledCount}
                  totalCount={enabledTools.length}
                />
                <SwitchField
                  name={serverEnabledField}
                  onCheckedChange={(checked) => {
                    enabledTools.forEach((tool) => {
                      setFieldValue(
                        `${serverFieldName}.tool_${tool.id}`,
                        checked
                      );
                    });
                    if (!checked) return;
                    setIsFolded(false);
                  }}
                />
              </Section>
            </InputHorizontal>
          </Section>
        </CardLayout.Header>
      </Card>
    </Disabled>
  );
}
