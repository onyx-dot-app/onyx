"use client";

import { markdown } from "@opal/utils";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Formik, Form } from "formik";
import useSWR, { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SettingsLayouts } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import { InputTypeIn } from "@opal/components";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import {
  SvgAddLines,
  SvgActions,
  SvgExpand,
  SvgFold,
  SvgExternalLink,
  SvgOrganization,
  SvgRefreshCw,
} from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  Card as CardLayout,
  Content,
  ContentAction,
  InputHorizontal,
  InputVertical,
} from "@opal/layouts";
import {
  useSettingsContext,
  useVectorDbEnabled,
} from "@/providers/SettingsProvider";
import useCCPairs from "@/hooks/useCCPairs";
import { getSourceMetadata } from "@/lib/sources";
import { QueryHistoryType, Settings } from "@/interfaces/settings";
import { toast } from "@/hooks/useToast";
import { useAvailableTools } from "@/hooks/useAvailableTools";
import {
  SEARCH_TOOL_ID,
  IMAGE_GENERATION_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
  PYTHON_TOOL_ID,
  OPEN_URL_TOOL_ID,
  CODING_AGENT_TOOL_ID,
} from "@/app/app/components/tools/constants";
import {
  EmptyMessageCard,
  Button,
  Divider,
  Text,
  Card,
  MessageCard,
  Tooltip,
} from "@opal/components";
import Modal from "@/refresh-components/Modal";
import { Switch } from "@opal/components";
import { useMcpServersForAgentEditor } from "@/lib/agents/hooks";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { Disabled, Hoverable } from "@opal/core";
import useFilter from "@/hooks/useFilter";
import { MCPServer } from "@/lib/tools/interfaces";
import type { IconProps } from "@opal/types";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/interfaces/settings";

const route = ADMIN_ROUTES.CHAT_PREFERENCES;

interface DefaultAgentConfiguration {
  tool_ids: number[];
  system_prompt: string | null;
  default_system_prompt: string;
}

interface MCPServerCardTool {
  id: number;
  icon: React.FunctionComponent<IconProps>;
  name: string;
  description: string;
}

interface MCPServerCardProps {
  server: MCPServer;
  tools: MCPServerCardTool[];
  isToolEnabled: (toolDbId: number) => boolean;
  onToggleTool: (toolDbId: number, enabled: boolean) => void;
  onToggleTools: (toolDbIds: number[], enabled: boolean) => void;
}

function MCPServerCard({
  server,
  tools,
  isToolEnabled,
  onToggleTool,
  onToggleTools,
}: MCPServerCardProps) {
  const [isFolded, setIsFolded] = useState(true);
  const {
    query,
    setQuery,
    filtered: filteredTools,
  } = useFilter(tools, (tool) => `${tool.name} ${tool.description}`);

  const allToolIds = tools.map((t) => t.id);
  const serverEnabled = tools.some((t) => isToolEnabled(t.id));
  const needsAuth = !server.is_authenticated;
  const authTooltip = needsAuth
    ? "请先认证此 MCP 服务，再启用它的工具。"
    : undefined;

  const expanded = !isFolded;
  const hasContent = tools.length > 0 && filteredTools.length > 0;

  return (
    <Card
      expandable
      expanded={expanded}
      border="solid"
      rounding="lg"
      padding="sm"
      expandedContent={
        hasContent ? (
          <Section gap={0.5} padding={0.5}>
            {filteredTools.map((tool) => (
              <Card key={tool.id} border="solid" rounding="md">
                <InputHorizontal
                  icon={tool.icon}
                  title={tool.name}
                  description={tool.description}
                  withLabel
                >
                  <Tooltip tooltip={authTooltip} side="top">
                    <Switch
                      checked={isToolEnabled(tool.id)}
                      onCheckedChange={(checked) =>
                        onToggleTool(tool.id, checked)
                      }
                      disabled={needsAuth}
                    />
                  </Tooltip>
                </InputHorizontal>
              </Card>
            ))}
          </Section>
        ) : undefined
      }
    >
      <CardLayout.Header
        bottomChildren={
          tools.length > 0 ? (
            <Section flexDirection="row" gap={0.5}>
              <InputTypeIn
                placeholder="搜索工具..."
                variant="internal"
                searchIcon
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <Button
                rightIcon={isFolded ? SvgExpand : SvgFold}
                onClick={() => setIsFolded((prev) => !prev)}
                prominence="internal"
                size="lg"
              >
                {isFolded ? "展开" : "收起"}
              </Button>
            </Section>
          ) : undefined
        }
      >
        <div className="p-2">
          <ContentAction
            icon={getActionIcon(server.server_url, server.name)}
            title={server.name}
            description={server.description}
            sizePreset="main-ui"
            variant="section"
            padding="fit"
            rightChildren={
              <Tooltip tooltip={authTooltip} side="top">
                <Switch
                  checked={serverEnabled}
                  onCheckedChange={(checked) =>
                    onToggleTools(allToolIds, checked)
                  }
                  disabled={needsAuth}
                />
              </Tooltip>
            }
          />
        </div>
      </CardLayout.Header>
    </Card>
  );
}

type FileLimitFieldName =
  | "user_file_max_upload_size_mb"
  | "file_token_count_threshold_k";

interface NumericLimitFieldProps {
  name: FileLimitFieldName;
  initialValue: string;
  defaultValue: string;
  saveSettings: (updates: Partial<Settings>) => Promise<void>;
  maxValue?: number;
  allowZero?: boolean;
}

function NumericLimitField({
  name,
  initialValue: initialValueProp,
  defaultValue,
  saveSettings,
  maxValue,
  allowZero = false,
}: NumericLimitFieldProps) {
  const [value, setValue] = useState(initialValueProp);
  const savedValue = useRef(initialValueProp);
  const restoringRef = useRef(false);

  const parsed = parseInt(value, 10);
  const isOverMax =
    maxValue !== undefined && !isNaN(parsed) && parsed > maxValue;

  const handleRestore = () => {
    restoringRef.current = true;
    savedValue.current = defaultValue;
    setValue(defaultValue);
    void saveSettings({ [name]: parseInt(defaultValue, 10) });
  };

  const handleBlur = () => {
    // The restore button triggers a blur — skip since handleRestore already saved.
    if (restoringRef.current) {
      restoringRef.current = false;
      return;
    }

    const parsed = parseInt(value, 10);
    const isValid = !isNaN(parsed) && (allowZero ? parsed >= 0 : parsed > 0);

    // Revert invalid input (empty, NaN, negative).
    if (!isValid) {
      if (allowZero) {
        // Empty/invalid means "no limit" — persist 0 and clear the field.
        setValue("");
        void saveSettings({ [name]: 0 });
        savedValue.current = "";
      } else {
        setValue(savedValue.current);
      }
      return;
    }

    // Block save when the value exceeds the hard ceiling.
    if (maxValue !== undefined && parsed > maxValue) {
      return;
    }

    // For allowZero fields, 0 means "no limit" — clear the display
    // so the "No limit" placeholder is visible, but still persist 0.
    if (allowZero && parsed === 0) {
      setValue("");
      if (savedValue.current !== "") {
        void saveSettings({ [name]: 0 });
        savedValue.current = "";
      }
      return;
    }

    const normalizedDisplay = String(parsed);

    // Update the display to the canonical form (e.g. strip leading zeros).
    if (value !== normalizedDisplay) {
      setValue(normalizedDisplay);
    }

    // Persist only when the value actually changed.
    if (normalizedDisplay !== savedValue.current) {
      void saveSettings({ [name]: parsed });
      savedValue.current = normalizedDisplay;
    }
  };

  return (
    <Hoverable.Root group="numericLimit" width="full">
      <InputTypeIn
        inputMode="numeric"
        pattern="[0-9]*"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={allowZero ? "不限制" : `默认：${defaultValue}`}
        variant={isOverMax ? "error" : undefined}
        rightChildren={
          (value || "") !== defaultValue ? (
            <Hoverable.Item group="numericLimit" variant="appear-on-hover">
              <Button
                icon={SvgRefreshCw}
                tooltip="恢复默认值"
                prominence="internal"
                onClick={handleRestore}
              />
            </Hoverable.Item>
          ) : undefined
        }
        onBlur={handleBlur}
      />
    </Hoverable.Root>
  );
}

interface FileSizeLimitFieldsProps {
  saveSettings: (updates: Partial<Settings>) => Promise<void>;
  initialUploadSizeMb: string;
  defaultUploadSizeMb: string;
  initialTokenThresholdK: string;
  defaultTokenThresholdK: string;
  maxAllowedUploadSizeMb?: number;
}

function FileSizeLimitFields({
  saveSettings,
  initialUploadSizeMb,
  defaultUploadSizeMb,
  initialTokenThresholdK,
  defaultTokenThresholdK,
  maxAllowedUploadSizeMb,
}: FileSizeLimitFieldsProps) {
  return (
    <div className="flex gap-4 w-full items-start pt-2">
      <div className="flex-1">
        <InputVertical
          title="文件大小限制"
          suffix="(MB)"
          subDescription={
            maxAllowedUploadSizeMb
              ? `最大：${maxAllowedUploadSizeMb} MB`
              : undefined
          }
          withLabel
        >
          <NumericLimitField
            name="user_file_max_upload_size_mb"
            initialValue={initialUploadSizeMb}
            defaultValue={defaultUploadSizeMb}
            saveSettings={saveSettings}
            maxValue={maxAllowedUploadSizeMb}
          />
        </InputVertical>
      </div>
      <div className="flex-1">
        <InputVertical
          title="文件 Token 限制"
          withLabel
          suffix="（千 token）"
        >
          <NumericLimitField
            name="file_token_count_threshold_k"
            initialValue={initialTokenThresholdK}
            defaultValue={defaultTokenThresholdK}
            saveSettings={saveSettings}
            allowZero
          />
        </InputVertical>
      </div>
    </div>
  );
}

export default function ChatPreferencesPage() {
  const router = useRouter();
  const settings = useSettingsContext();
  const s = settings.settings;
  // Search Mode toggle is Business+; Chat Retention is Enterprise-only.
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const enterpriseTier = useTierAtLeast(Tier.ENTERPRISE);

  // Local state for text fields (save-on-blur)
  const [companyName, setCompanyName] = useState(s.company_name ?? "");
  const [companyDescription, setCompanyDescription] = useState(
    s.company_description ?? ""
  );
  const savedCompanyName = useRef(companyName);
  const savedCompanyDescription = useRef(companyDescription);

  // Re-sync local state when settings change externally (e.g. another admin),
  // but only when there's no in-progress edit (local matches last-saved value).
  useEffect(() => {
    const incoming = s.company_name ?? "";
    if (companyName === savedCompanyName.current && incoming !== companyName) {
      setCompanyName(incoming);
      savedCompanyName.current = incoming;
    }
  }, [s.company_name]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const incoming = s.company_description ?? "";
    if (
      companyDescription === savedCompanyDescription.current &&
      incoming !== companyDescription
    ) {
      setCompanyDescription(incoming);
      savedCompanyDescription.current = incoming;
    }
  }, [s.company_description]); // eslint-disable-line react-hooks/exhaustive-deps

  // Tools availability
  const { tools: availableTools } = useAvailableTools();
  const vectorDbEnabled = useVectorDbEnabled();

  const searchTool = availableTools.find(
    (t) => t.in_code_tool_id === SEARCH_TOOL_ID
  );
  const imageGenTool = availableTools.find(
    (t) => t.in_code_tool_id === IMAGE_GENERATION_TOOL_ID
  );
  const webSearchTool = availableTools.find(
    (t) => t.in_code_tool_id === WEB_SEARCH_TOOL_ID
  );
  const openURLTool = availableTools.find(
    (t) => t.in_code_tool_id === OPEN_URL_TOOL_ID
  );
  const codeInterpreterTool = availableTools.find(
    (t) => t.in_code_tool_id === PYTHON_TOOL_ID
  );
  const codingAgentTool = availableTools.find(
    (t) => t.in_code_tool_id === CODING_AGENT_TOOL_ID
  );

  // Connectors
  const { ccPairs } = useCCPairs();
  const uniqueSources = Array.from(new Set(ccPairs.map((p) => p.source)));

  // MCP servers and OpenAPI tools
  const { mcpData } = useMcpServersForAgentEditor();
  const { openApiTools: openApiToolsRaw } = useOpenApiTools();
  const mcpServers = mcpData?.mcp_servers ?? [];
  const openApiTools = openApiToolsRaw ?? [];

  const mcpServersWithTools = mcpServers.map((server) => ({
    server,
    tools: availableTools
      .filter((tool) => tool.mcp_server_id === server.id)
      .map((tool) => ({
        id: tool.id,
        icon: getActionIcon(server.server_url, server.name),
        name: tool.display_name || tool.name,
        description: tool.description,
      })),
  }));

  // Default agent configuration (system prompt)
  const { data: defaultAgentConfig, mutate: mutateDefaultAgent } =
    useSWR<DefaultAgentConfiguration>(
      SWR_KEYS.defaultAssistantConfig,
      errorHandlingFetcher
    );

  const enabledToolIds = defaultAgentConfig?.tool_ids ?? [];

  const isToolEnabled = useCallback(
    (toolDbId: number) => enabledToolIds.includes(toolDbId),
    [enabledToolIds]
  );

  const saveToolIds = useCallback(
    async (newToolIds: number[]) => {
      // Optimistic update so subsequent toggles read fresh state
      const optimisticData = defaultAgentConfig
        ? { ...defaultAgentConfig, tool_ids: newToolIds }
        : undefined;
      try {
        await mutateDefaultAgent(
          async () => {
            const response = await fetch("/api/admin/default-assistant", {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ tool_ids: newToolIds }),
            });
            if (!response.ok) {
              const errorMsg = (await response.json()).detail;
              throw new Error(errorMsg);
            }
            return optimisticData;
          },
          { optimisticData, revalidate: true }
        );
        toast.success("工具已更新");
      } catch {
        toast.error("工具更新失败");
      }
    },
    [defaultAgentConfig, mutateDefaultAgent]
  );

  const toggleTool = useCallback(
    (toolDbId: number, enabled: boolean) => {
      const newToolIds = enabled
        ? [...enabledToolIds, toolDbId]
        : enabledToolIds.filter((id) => id !== toolDbId);
      void saveToolIds(newToolIds);
    },
    [enabledToolIds, saveToolIds]
  );

  const toggleTools = useCallback(
    (toolDbIds: number[], enabled: boolean) => {
      const idsSet = new Set(toolDbIds);
      const withoutIds = enabledToolIds.filter((id) => !idsSet.has(id));
      const newToolIds = enabled ? [...withoutIds, ...toolDbIds] : withoutIds;
      void saveToolIds(newToolIds);
    },
    [enabledToolIds, saveToolIds]
  );

  // System prompt modal state
  const [systemPromptModalOpen, setSystemPromptModalOpen] = useState(false);

  const saveSettings = useCallback(
    async (updates: Partial<Settings>) => {
      const currentSettings = settings?.settings;
      if (!currentSettings) return;

      const newSettings = { ...currentSettings, ...updates };

      try {
        const response = await fetch("/api/admin/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(newSettings),
        });

        if (!response.ok) {
          const errorMsg = (await response.json()).detail;
          throw new Error(errorMsg);
        }

        router.refresh();
        await mutate(SWR_KEYS.settings);
        toast.success("设置已更新");
      } catch (error) {
        toast.error("设置更新失败");
      }
    },
    [settings, router]
  );

  return (
    <>
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description="组织级聊天设置和默认值。部分设置可由用户在个人设置中覆盖。"
          divider
        />

        <SettingsLayouts.Body>
          {/* Features */}
          <Card border="solid" rounding="lg">
            <Section>
              <Disabled
                disabled={!businessTier || uniqueSources.length === 0}
                allowClick={businessTier}
                tooltip={
                  !businessTier
                    ? "搜索模式需要商业版或企业版套餐。"
                    : "请先设置连接器以使用搜索模式"
                }
              >
                <InputHorizontal
                  title="搜索模式"
                  tag={
                    !businessTier
                      ? {
                          title: "商业版套餐",
                          color: "amber",
                          icon: SvgOrganization,
                        }
                      : { title: "beta", color: "blue" }
                  }
                  description="用于在组织文档中快速搜索的界面模式。"
                  disabled={!businessTier || uniqueSources.length === 0}
                  withLabel
                >
                  <Switch
                    checked={
                      businessTier ? (s.search_ui_enabled ?? true) : false
                    }
                    onCheckedChange={(checked) => {
                      void saveSettings({ search_ui_enabled: checked });
                    }}
                    disabled={!businessTier || uniqueSources.length === 0}
                  />
                </InputHorizontal>
              </Disabled>
              <InputHorizontal
                title="多模型生成"
                tag={{ title: "beta", color: "blue" }}
                description="允许多个模型在聊天中并行生成回复。"
                withLabel
              >
                <Switch
                  checked={s.multi_model_chat_enabled ?? true}
                  onCheckedChange={(checked) => {
                    void saveSettings({ multi_model_chat_enabled: checked });
                  }}
                />
              </InputHorizontal>
              <InputHorizontal
                title="深度研究"
                description="可跨网页和已连接数据源工作的智能研究系统。每次查询会消耗更多 token。"
                withLabel
              >
                <Switch
                  checked={s.deep_research_enabled ?? true}
                  onCheckedChange={(checked) => {
                    void saveSettings({ deep_research_enabled: checked });
                  }}
                />
              </InputHorizontal>
              <InputHorizontal
                title="聊天自动滚动"
                description="生成回复时自动滚动到最新内容。用户可在个人设置中覆盖此项。"
                withLabel
              >
                <Switch
                  checked={s.auto_scroll ?? false}
                  onCheckedChange={(checked) => {
                    void saveSettings({ auto_scroll: checked });
                  }}
                />
              </InputHorizontal>
            </Section>
          </Card>

          <Divider paddingParallel="fit" paddingPerpendicular="fit" />

          {/* Team Context */}
          <Section gap={1}>
            <InputVertical
              title="团队名称"
              subDescription="此信息会作为额外上下文加入全部聊天会话，提供更丰富、个性化的体验。"
              withLabel
            >
              <InputTypeIn
                placeholder="输入团队名称"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                onBlur={() => {
                  if (companyName !== savedCompanyName.current) {
                    void saveSettings({
                      company_name: companyName || null,
                    });
                    savedCompanyName.current = companyName;
                  }
                }}
              />
            </InputVertical>

            <InputVertical
              title="团队上下文"
              subDescription="用户也可以在个人设置中提供额外的个人上下文。"
              withLabel
            >
              <InputTextArea
                placeholder="描述你的团队，以及希望 Glomi AI 如何回应。"
                rows={4}
                maxRows={10}
                autoResize
                value={companyDescription}
                onChange={(e) => setCompanyDescription(e.target.value)}
                onBlur={() => {
                  if (companyDescription !== savedCompanyDescription.current) {
                    void saveSettings({
                      company_description: companyDescription || null,
                    });
                    savedCompanyDescription.current = companyDescription;
                  }
                }}
              />
            </InputVertical>
          </Section>

          <InputHorizontal
            title="系统提示词"
            description="适用于全部聊天、智能体和项目的基础提示词。请谨慎修改，较大的变更可能降低回复质量。"
          >
            <Button
              prominence="tertiary"
              icon={SvgAddLines}
              onClick={() => setSystemPromptModalOpen(true)}
            >
              修改提示词
            </Button>
          </InputHorizontal>

          <Divider paddingParallel="fit" paddingPerpendicular="fit" />

          <Disabled disabled={s.disable_default_assistant ?? false}>
            <div>
              <Section gap={1.5}>
                {/* Connectors */}
                <Section gap={0.75}>
                  <Content
                    title="Connectors"
                    sizePreset="main-content"
                    variant="section"
                  />

                  <Section
                    flexDirection="row"
                    justifyContent="between"
                    alignItems="center"
                    gap={0.25}
                  >
                    {uniqueSources.length === 0 ? (
                      <EmptyMessageCard
                        sizePreset="main-ui"
                        title="尚未设置连接器"
                      />
                    ) : (
                      <>
                        <Section
                          flexDirection="row"
                          justifyContent="start"
                          alignItems="center"
                          gap={0.25}
                        >
                          {uniqueSources.slice(0, 3).map((source) => {
                            const meta = getSourceMetadata(source);
                            return (
                              <div key={source} className="w-40">
                                <Card padding="sm" border="solid">
                                  <Content
                                    icon={meta.icon}
                                    title={meta.displayName}
                                    sizePreset="main-ui"
                                  />
                                </Card>
                              </div>
                            );
                          })}
                        </Section>

                        <Button
                          href="/admin/indexing/status"
                          prominence="tertiary"
                          rightIcon={SvgExternalLink}
                        >
                          全部管理
                        </Button>
                      </>
                    )}
                  </Section>
                </Section>

                {/* Actions & Tools */}
                <SimpleCollapsible>
                  <SimpleCollapsible.Header
                    title="操作与工具"
                    description="可供聊天使用的工具和能力。此设置不适用于智能体。"
                  />
                  <SimpleCollapsible.Content>
                    <Section gap={0.5}>
                      {vectorDbEnabled && searchTool && (
                        <Card border="solid" rounding="lg">
                          <InputHorizontal
                            title="内部搜索"
                            description="搜索组织已连接的知识库和文档。"
                            withLabel
                          >
                            <Switch
                              checked={isToolEnabled(searchTool.id)}
                              onCheckedChange={(checked) =>
                                void toggleTool(searchTool.id, checked)
                              }
                            />
                          </InputHorizontal>
                        </Card>
                      )}

                      <Disabled
                        disabled={!imageGenTool}
                        tooltip="图像生成需要先配置模型。请前往“配置 > 图像生成”设置，或联系管理员。"
                      >
                        <Card border="solid" rounding="lg">
                          <InputHorizontal
                            title="图像生成"
                            description="使用 AI 工具生成和编辑图像。"
                            disabled={!imageGenTool}
                            withLabel
                          >
                            <Switch
                              checked={
                                imageGenTool
                                  ? isToolEnabled(imageGenTool.id)
                                  : false
                              }
                              onCheckedChange={(checked) =>
                                imageGenTool &&
                                void toggleTool(imageGenTool.id, checked)
                              }
                              disabled={!imageGenTool}
                            />
                          </InputHorizontal>
                        </Card>
                      </Disabled>

                      <Disabled disabled={!webSearchTool}>
                        <Card border="solid" rounding="lg">
                          <InputHorizontal
                            title="网页搜索"
                            description="搜索网页以获取实时信息和最新结果。"
                            disabled={!webSearchTool}
                            withLabel
                          >
                            <Switch
                              checked={
                                webSearchTool
                                  ? isToolEnabled(webSearchTool.id)
                                  : false
                              }
                              onCheckedChange={(checked) =>
                                webSearchTool &&
                                void toggleTool(webSearchTool.id, checked)
                              }
                              disabled={!webSearchTool}
                            />
                          </InputHorizontal>
                        </Card>
                      </Disabled>

                      <Disabled disabled={!openURLTool}>
                        <Card border="solid" rounding="lg">
                          <InputHorizontal
                            title="打开 URL"
                            description="获取并读取网页 URL 内容。"
                            disabled={!openURLTool}
                            withLabel
                          >
                            <Switch
                              checked={
                                openURLTool
                                  ? isToolEnabled(openURLTool.id)
                                  : false
                              }
                              onCheckedChange={(checked) =>
                                openURLTool &&
                                void toggleTool(openURLTool.id, checked)
                              }
                              disabled={!openURLTool}
                            />
                          </InputHorizontal>
                        </Card>
                      </Disabled>

                      <Disabled disabled={!codeInterpreterTool}>
                        <Card border="solid" rounding="lg">
                          <InputHorizontal
                            title="代码解释器"
                            description="生成并运行代码。"
                            disabled={!codeInterpreterTool}
                            withLabel
                          >
                            <Switch
                              checked={
                                codeInterpreterTool
                                  ? isToolEnabled(codeInterpreterTool.id)
                                  : false
                              }
                              onCheckedChange={(checked) =>
                                codeInterpreterTool &&
                                void toggleTool(codeInterpreterTool.id, checked)
                              }
                              disabled={!codeInterpreterTool}
                            />
                          </InputHorizontal>
                        </Card>
                      </Disabled>

                      <Disabled disabled={!codingAgentTool}>
                        <Card border="solid" rounding="lg">
                          <InputHorizontal
                            title="代码智能体"
                            description="分析 GitHub 仓库并回答代码相关问题。"
                            disabled={!codingAgentTool}
                            withLabel
                          >
                            <Switch
                              checked={
                                codingAgentTool
                                  ? isToolEnabled(codingAgentTool.id)
                                  : false
                              }
                              onCheckedChange={(checked) =>
                                codingAgentTool &&
                                void toggleTool(codingAgentTool.id, checked)
                              }
                              disabled={!codingAgentTool}
                            />
                          </InputHorizontal>
                        </Card>
                      </Disabled>
                    </Section>

                    {/* Separator between built-in tools and MCP/OpenAPI tools */}
                    {(mcpServersWithTools.length > 0 ||
                      openApiTools.length > 0) && (
                      <Divider
                        paddingPerpendicular="sm"
                        paddingParallel="fit"
                      />
                    )}

                    {/* MCP Servers & OpenAPI Tools */}
                    <Section gap={0.5}>
                      {mcpServersWithTools.map(({ server, tools }) => (
                        <MCPServerCard
                          key={server.id}
                          server={server}
                          tools={tools}
                          isToolEnabled={isToolEnabled}
                          onToggleTool={toggleTool}
                          onToggleTools={toggleTools}
                        />
                      ))}
                      {openApiTools.map((tool) => (
                        <Card key={tool.id} border="solid" rounding="lg">
                          <InputHorizontal
                            icon={SvgActions}
                            title={tool.display_name || tool.name}
                            description={tool.description}
                            withLabel
                          >
                            <Switch
                              checked={isToolEnabled(tool.id)}
                              onCheckedChange={(checked) =>
                                toggleTool(tool.id, checked)
                              }
                            />
                          </InputHorizontal>
                        </Card>
                      ))}
                    </Section>
                  </SimpleCollapsible.Content>
                </SimpleCollapsible>
              </Section>
            </div>
          </Disabled>

          <Divider paddingParallel="fit" paddingPerpendicular="fit" />

          {/* Advanced Options */}
          <SimpleCollapsible defaultOpen={false}>
            <SimpleCollapsible.Header title="高级选项" />
            <SimpleCollapsible.Content>
              <Section gap={1}>
                <Card border="solid" rounding="lg">
                  <Section>
                    <Disabled
                      disabled={!enterpriseTier}
                      tooltip="聊天历史保留是企业版套餐功能。"
                    >
                      <InputHorizontal
                        title="保留聊天历史"
                        description="指定 Glomi AI 在组织内保留聊天记录的时长。"
                        tag={
                          !enterpriseTier
                            ? {
                                title: "企业版套餐",
                                color: "amber",
                                icon: SvgOrganization,
                              }
                            : undefined
                        }
                        disabled={!enterpriseTier}
                        withLabel
                      >
                        <InputSelect
                          value={
                            s.maximum_chat_retention_days?.toString() ??
                            "forever"
                          }
                          onValueChange={(value) => {
                            void saveSettings({
                              maximum_chat_retention_days:
                                value === "forever"
                                  ? null
                                  : parseInt(value, 10),
                            });
                          }}
                          disabled={!enterpriseTier}
                        >
                          <InputSelect.Trigger />
                          <InputSelect.Content>
                            <InputSelect.Item value="forever">
                              永久
                            </InputSelect.Item>
                            <InputSelect.Item value="7">
                              7 天
                            </InputSelect.Item>
                            <InputSelect.Item value="30">
                              30 天
                            </InputSelect.Item>
                            <InputSelect.Item value="90">
                              90 天
                            </InputSelect.Item>
                            <InputSelect.Item value="365">
                              365 天
                            </InputSelect.Item>
                          </InputSelect.Content>
                        </InputSelect>
                      </InputHorizontal>
                    </Disabled>

                    <InputHorizontal
                      title="查询历史可见性"
                      description="控制组织完整聊天历史在管理面板中的显示方式。"
                      withLabel
                    >
                      <InputSelect
                        value={s.query_history_type ?? QueryHistoryType.NORMAL}
                        onValueChange={(value) => {
                          void saveSettings({
                            query_history_type: value as QueryHistoryType,
                          });
                        }}
                      >
                        <InputSelect.Trigger />
                        <InputSelect.Content>
                          <InputSelect.Item
                            value={QueryHistoryType.NORMAL}
                            description="管理员可查看全部查询，并可关联到具体用户。"
                          >
                            显示用户信息
                          </InputSelect.Item>
                          <InputSelect.Item
                            value={QueryHistoryType.ANONYMIZED}
                            description="管理员可查看查询，但移除用户身份信息。"
                          >
                            匿名化
                          </InputSelect.Item>
                          <InputSelect.Item
                            value={QueryHistoryType.DISABLED}
                            description="禁用查询历史报告。"
                          >
                            隐藏
                          </InputSelect.Item>
                        </InputSelect.Content>
                      </InputSelect>
                    </InputHorizontal>
                  </Section>
                </Card>

                <Card border="solid" rounding="lg">
                  <InputVertical
                    title="文件附件大小限制"
                    description="聊天和项目中的附件必须同时满足两个限制才会被接受。较大的文件会增加延迟、内存占用和 token 成本。"
                    withLabel
                  >
                    <FileSizeLimitFields
                      saveSettings={saveSettings}
                      initialUploadSizeMb={
                        (s.user_file_max_upload_size_mb ?? 0) <= 0
                          ? (s.default_user_file_max_upload_size_mb?.toString() ??
                            "100")
                          : s.user_file_max_upload_size_mb!.toString()
                      }
                      defaultUploadSizeMb={
                        s.default_user_file_max_upload_size_mb?.toString() ??
                        "100"
                      }
                      initialTokenThresholdK={
                        s.file_token_count_threshold_k == null
                          ? (s.default_file_token_count_threshold_k?.toString() ??
                            "200")
                          : s.file_token_count_threshold_k === 0
                            ? ""
                            : s.file_token_count_threshold_k.toString()
                      }
                      defaultTokenThresholdK={
                        s.default_file_token_count_threshold_k?.toString() ??
                        "200"
                      }
                      maxAllowedUploadSizeMb={s.max_allowed_upload_size_mb}
                    />
                  </InputVertical>
                </Card>

                <Card border="solid" rounding="lg">
                  <Section>
                    <InputHorizontal
                      title="允许匿名用户"
                      description="允许任何人在不登录的情况下开始对话。他们无法看到其他对话，也不能创建智能体或更新设置。"
                      withLabel
                    >
                      <Switch
                        checked={s.anonymous_user_enabled ?? false}
                        onCheckedChange={(checked) => {
                          void saveSettings({
                            anonymous_user_enabled: checked,
                          });
                        }}
                      />
                    </InputHorizontal>

                    <InputHorizontal
                      title="始终从智能体开始"
                      description="这会移除默认对话。用户始终会从某个智能体开始，新对话会在其最近使用的智能体中创建。设置精选智能体可帮助新用户开始使用。"
                      withLabel
                    >
                      <Switch
                        id="disable_default_assistant"
                        checked={s.disable_default_assistant ?? false}
                        onCheckedChange={(checked) => {
                          void saveSettings({
                            disable_default_assistant: checked,
                          });
                        }}
                      />
                    </InputHorizontal>
                  </Section>
                </Card>
              </Section>
            </SimpleCollapsible.Content>
          </SimpleCollapsible>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      <Modal
        open={systemPromptModalOpen}
        onOpenChange={setSystemPromptModalOpen}
      >
        <Modal.Content width="xl" height="fit">
          <Formik
            initialValues={{
              system_prompt:
                defaultAgentConfig?.system_prompt ??
                defaultAgentConfig?.default_system_prompt ??
                "",
            }}
            onSubmit={async ({ system_prompt }) => {
              try {
                const response = await fetch("/api/admin/default-assistant", {
                  method: "PATCH",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ system_prompt }),
                });
                if (!response.ok) {
                  const errorMsg = (await response.json()).detail;
                  throw new Error(errorMsg);
                }
                await mutateDefaultAgent();
                setSystemPromptModalOpen(false);
                toast.success("系统提示词已更新");
              } catch {
                toast.error("系统提示词更新失败");
              }
            }}
          >
            {({ dirty, isSubmitting, submitForm, setFieldValue }) => {
              const defaultPrompt =
                defaultAgentConfig?.default_system_prompt ?? "";

              const handleRestore = () => {
                void setFieldValue("system_prompt", defaultPrompt);
              };

              return (
                <Form>
                  <Modal.Header
                    icon={SvgAddLines}
                    title="系统提示词"
                    description="此基础提示词会添加到全部聊天、智能体和项目之前。"
                    onClose={() => setSystemPromptModalOpen(false)}
                  />
                  <Modal.Body>
                    <Section gap={0.25} alignItems="start">
                      <Hoverable.Root group="systemPromptRestore" width="full">
                        <InputTextAreaField
                          name="system_prompt"
                          placeholder="输入系统提示词..."
                          rows={8}
                          maxRows={20}
                          autoResize
                          rightSection={
                            <Hoverable.Item
                              group="systemPromptRestore"
                              variant="appear-on-hover"
                            >
                              <Button
                                icon={SvgRefreshCw}
                                tooltip="恢复默认值"
                                prominence="internal"
                                onClick={handleRestore}
                              />
                            </Hoverable.Item>
                          }
                        />
                      </Hoverable.Root>
                      <Text font="secondary-body" color="text-03">
                        {markdown(
                          "你可以在提示词中使用以下占位符：\n`{{CURRENT_DATETIME}}` - 以易读格式插入当前日期和星期。\n`{{CITATION_GUIDANCE}}` - 当事实来自搜索工具时，用于提供引用的说明。仅在使用搜索工具时包含。\n`{{REMINDER_TAG_DESCRIPTION}}` - 用于解释用户消息中系统提醒的说明。"
                        )}
                      </Text>
                    </Section>
                    <MessageCard
                      title="请谨慎修改。"
                      description="系统提示词会影响全部聊天、智能体和项目。较大的变更可能降低回复质量。"
                      padding="xs"
                    />
                  </Modal.Body>
                  <Modal.Footer>
                    <Button
                      prominence="secondary"
                      onClick={() => setSystemPromptModalOpen(false)}
                    >
                      取消
                    </Button>
                    <Button
                      prominence="primary"
                      onClick={submitForm}
                      disabled={!dirty || isSubmitting}
                    >
                      保存
                    </Button>
                  </Modal.Footer>
                </Form>
              );
            }}
          </Formik>
        </Modal.Content>
      </Modal>
    </>
  );
}
