"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { SettingsLayouts } from "@opal/layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { Button, Card, Divider, MessageCard } from "@opal/components";
import { Hoverable, Disabled } from "@opal/core";
import { FullAgent } from "@/lib/agents/types";
import { buildAgentAvatarUrl } from "@/lib/agents/utils";
import { Formik, Form, FieldArray } from "formik";
import * as Yup from "yup";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInElementField from "@/refresh-components/form/InputTypeInElementField";
import InputDatePickerField from "@/refresh-components/form/InputDatePickerField";
import {
  Card as CardLayout,
  ContentAction,
  InputHorizontal,
  InputVertical,
} from "@opal/layouts";
import { useFormikContext } from "formik";
import LLMSelector from "@/components/llm/LLMSelector";
import { parseLlmDescriptor, structureValue } from "@/lib/languageModels/utils";
import { useLLMProviders } from "@/hooks/useLanguageModels";
import {
  STARTER_MESSAGES_EXAMPLES,
  MAX_CHARACTERS_STARTER_MESSAGE,
  MAX_CHARACTERS_AGENT_DESCRIPTION,
} from "@/lib/constants";
import {
  IMAGE_GENERATION_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
  PYTHON_TOOL_ID,
  SEARCH_TOOL_ID,
  OPEN_URL_TOOL_ID,
  CODING_AGENT_TOOL_ID,
} from "@/app/app/components/tools/constants";
import Text from "@/refresh-components/texts/Text";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import SwitchField from "@/refresh-components/form/SwitchField";
import { Tooltip } from "@opal/components";
import { useDocumentSets } from "@/app/admin/documents/sets/hooks";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { toast } from "@/hooks/useToast";
import UserFilesModal from "@/sections/modals/UserFilesModal";
import {
  ProjectFile,
  UserFileStatus,
} from "@/app/app/projects/projectsService";
import { Popover, PopoverMenu } from "@opal/components";
import LineItem from "@/refresh-components/buttons/LineItem";
import {
  SvgActions,
  SvgExpand,
  SvgFold,
  SvgImage,
  SvgLock,
  SvgSliders,
  SvgSparkle,
  SvgUsers,
  SvgTrash,
  SvgSimpleLoader,
} from "@opal/icons";
import CustomAgentAvatar, {
  agentAvatarIconMap,
} from "@/refresh-components/avatars/CustomAgentAvatar";
import InputAvatar from "@/refresh-components/inputs/InputAvatar";
import SquareButton from "@/refresh-components/buttons/SquareButton";
import { useAgents } from "@/lib/agents/hooks";
import { createAgent, updateAgent } from "@/lib/agents/svc";
import { AgentUpsertParameters } from "@/lib/agents/types";
import { useMcpServersForAgentEditor } from "@/lib/agents/hooks";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import { useAvailableTools } from "@/hooks/useAvailableTools";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { MCPServer, MCPTool, ToolSnapshot } from "@/lib/tools/interfaces";
import { InputTypeIn } from "@opal/components";
import useFilter from "@/hooks/useFilter";
import EnabledCount from "@/refresh-components/EnabledCount";
import { useAppRouter } from "@/hooks/appNavigation";
import { isDateInFuture } from "@/lib/dateUtils";
import {
  deleteAgent,
  updateAgentFeaturedStatus,
  updateAgentSharedStatus,
} from "@/lib/agents/svc";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import ShareAgentModal from "@/sections/modals/ShareAgentModal";
import AgentKnowledgePane from "@/sections/knowledge/AgentKnowledgePane";
import { ValidSources } from "@/lib/types";
import { useVectorDbEnabled } from "@/providers/SettingsProvider";
import { useUser } from "@/providers/UserProvider";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/interfaces/settings";

interface AgentIconEditorProps {
  existingAgent?: FullAgent | null;
}

function FormWarningsEffect() {
  const { values, setStatus } = useFormikContext<{
    web_search: boolean;
    open_url: boolean;
  }>();

  useEffect(() => {
    const warnings: Record<string, string> = {};
    if (values.web_search && !values.open_url) {
      warnings.open_url =
        "启用网页搜索但未启用打开链接，可能会显著降低网页结果质量。";
    }
    setStatus({ warnings });
  }, [values.web_search, values.open_url, setStatus]);

  return null;
}

function AgentIconEditor({ existingAgent }: AgentIconEditorProps) {
  const { values, setFieldValue } = useFormikContext<{
    name: string;
    icon_name: string | null;
    uploaded_image_id: string | null;
    remove_image: boolean | null;
  }>();
  const [uploadedImagePreview, setUploadedImagePreview] = useState<
    string | null
  >(null);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function handleImageUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    // Clear previous preview to free memory
    setUploadedImagePreview(null);

    // Clear selected icon and remove_image flag when uploading an image
    setFieldValue("icon_name", null);
    setFieldValue("remove_image", false);

    // Show preview immediately
    const reader = new FileReader();
    reader.onloadend = () => {
      setUploadedImagePreview(reader.result as string);
    };
    reader.readAsDataURL(file);

    // Upload the file
    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetch("/api/admin/persona/upload-image", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        console.error("Failed to upload image");
        setUploadedImagePreview(null);
        return;
      }

      const { file_id } = await response.json();
      setFieldValue("uploaded_image_id", file_id);
      setPopoverOpen(false);
    } catch (error) {
      console.error("Upload error:", error);
      setUploadedImagePreview(null);
    }
  }

  const imageSrc = uploadedImagePreview
    ? uploadedImagePreview
    : values.uploaded_image_id && existingAgent?.id != null
      ? buildAgentAvatarUrl(existingAgent.id)
      : values.icon_name
        ? undefined
        : values.remove_image
          ? undefined
          : existingAgent?.uploaded_image_id
            ? buildAgentAvatarUrl(existingAgent.id)
            : undefined;

  function handleIconClick(iconName: string | null) {
    setFieldValue("icon_name", iconName);
    setFieldValue("uploaded_image_id", null);
    setFieldValue("remove_image", true);
    setUploadedImagePreview(null);
    setPopoverOpen(false);

    // Reset the file input so the same file can be uploaded again later
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        onChange={handleImageUpload}
        className="hidden"
      />

      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <Popover.Trigger asChild>
          <Hoverable.Root group="inputAvatar" width="fit">
            <InputAvatar className="relative flex flex-col items-center justify-center h-30 w-30">
              {/* We take the `InputAvatar`'s height/width (in REM) and multiply it by 16 (the REM -> px conversion factor). */}
              <CustomAgentAvatar
                size={imageSrc ? 7.5 * 16 : 40}
                src={imageSrc}
                iconName={values.icon_name ?? undefined}
                name={values.name}
              />
              {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
              <div className="absolute bottom-0 left-1/2 -translate-x-1/2 mb-2">
                <Hoverable.Item group="inputAvatar" variant="appear-on-hover">
                  <Button prominence="secondary" size="md">
                    编辑
                  </Button>
                </Hoverable.Item>
              </div>
            </InputAvatar>
          </Hoverable.Root>
        </Popover.Trigger>
        <Popover.Content>
          <PopoverMenu>
            {[
              <LineItem
                key="upload-image"
                icon={SvgImage}
                onClick={() => fileInputRef.current?.click()}
                emphasized
              >
                上传图片
              </LineItem>,
              null,
              <div key="icon-grid" className="grid grid-cols-4 gap-1">
                <SquareButton
                  key="default-icon"
                  icon={() => (
                    <CustomAgentAvatar name={values.name} size={30} />
                  )}
                  onClick={() => handleIconClick(null)}
                  transient={!imageSrc && values.icon_name === null}
                />
                {Object.keys(agentAvatarIconMap).map((iconName) => (
                  <SquareButton
                    key={iconName}
                    onClick={() => handleIconClick(iconName)}
                    icon={() => (
                      <CustomAgentAvatar iconName={iconName} size={30} />
                    )}
                    transient={values.icon_name === iconName}
                  />
                ))}
              </div>,
            ]}
          </PopoverMenu>
        </Popover.Content>
      </Popover>
    </>
  );
}

interface OpenApiToolCardProps {
  tool: ToolSnapshot;
}

function OpenApiToolCard({ tool }: OpenApiToolCardProps) {
  const toolFieldName = `openapi_tool_${tool.id}`;

  return (
    <Card border="solid" rounding="lg">
      <InputHorizontal
        icon={SvgActions}
        title={tool.display_name || tool.name}
        description={tool.description}
        withLabel={toolFieldName}
      >
        <SwitchField name={toolFieldName} />
      </InputHorizontal>
    </Card>
  );
}

interface MCPServerCardProps {
  server: MCPServer;
  tools: MCPTool[];
  isLoading: boolean;
}

function MCPServerCard({
  server,
  tools: enabledTools,
  isLoading,
}: MCPServerCardProps) {
  const [isFolded, setIsFolded] = useState(false);
  const { values, setFieldValue, getFieldMeta } = useFormikContext<any>();
  const serverFieldName = `mcp_server_${server.id}`;
  const isServerEnabled = values[serverFieldName]?.enabled ?? false;
  const {
    query,
    setQuery,
    filtered: filteredTools,
  } = useFilter(enabledTools, (tool) => `${tool.name} ${tool.description}`);

  // Calculate enabled and total tool counts
  const enabledCount = enabledTools.filter((tool) => {
    const toolFieldValue = values[serverFieldName]?.[`tool_${tool.id}`];
    return toolFieldValue === true;
  }).length;

  const hasTools = enabledTools.length > 0 && filteredTools.length > 0;

  let cardContent: React.ReactNode | undefined;
  if (isLoading) {
    cardContent = (
      <div className="flex flex-col gap-2 p-2">
        <GeneralLayouts.Section padding={1}>
          <SvgSimpleLoader />
        </GeneralLayouts.Section>
      </div>
    );
  } else if (hasTools) {
    cardContent = (
      <GeneralLayouts.Section gap={0.5} padding={0.5}>
        {filteredTools.map((tool) => {
          const toolDisabled =
            !tool.isAvailable ||
            !getFieldMeta<boolean>(`${serverFieldName}.enabled`).value;
          return (
            <Disabled key={tool.id} disabled={toolDisabled}>
              <Card border="solid" rounding="md" padding="sm">
                <ContentAction
                  icon={tool.icon ?? SvgSliders}
                  title={tool.name}
                  description={tool.description}
                  sizePreset="main-ui"
                  variant="section"
                  padding="fit"
                  rightChildren={
                    <SwitchField
                      name={`${serverFieldName}.tool_${tool.id}`}
                      disabled={!isServerEnabled}
                    />
                  }
                />
              </Card>
            </Disabled>
          );
        })}
      </GeneralLayouts.Section>
    );
  }

  return (
    <Card
      expandable
      expanded={!isFolded}
      border="solid"
      rounding="lg"
      padding="sm"
      expandedContent={cardContent}
    >
      <CardLayout.Header
        bottomChildren={
          <GeneralLayouts.Section flexDirection="row" gap={0.5}>
            <InputTypeIn
              placeholder="搜索工具..."
              variant="internal"
              searchIcon
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {enabledTools.length > 0 && (
              <Button
                prominence="internal"
                rightIcon={isFolded ? SvgExpand : SvgFold}
                onClick={() => setIsFolded((prev) => !prev)}
              >
                {isFolded ? "展开" : "收起"}
              </Button>
            )}
          </GeneralLayouts.Section>
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
              <GeneralLayouts.Section
                flexDirection="row"
                gap={0.5}
                alignItems="start"
              >
                <EnabledCount
                  enabledCount={enabledCount}
                  totalCount={enabledTools.length}
                />
                <SwitchField
                  name={`${serverFieldName}.enabled`}
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
              </GeneralLayouts.Section>
            }
          />
        </div>
      </CardLayout.Header>
    </Card>
  );
}

function AgentStarterMessages() {
  const max_starters = STARTER_MESSAGES_EXAMPLES.length;

  const { values } = useFormikContext<{
    starter_messages: string[];
  }>();

  const starters = values.starter_messages || [];

  // Count how many non-empty starters we have
  const filledStarters = starters.filter((s) => s).length;
  const canAddMore = filledStarters < max_starters;

  // Show at least 1, or all filled ones, or filled + 1 empty (up to max)
  const visibleCount = Math.min(
    max_starters,
    Math.max(
      1,
      filledStarters === 0 ? 1 : filledStarters + (canAddMore ? 1 : 0)
    )
  );

  return (
    <FieldArray name="starter_messages">
      {(arrayHelpers) => (
        <GeneralLayouts.Section gap={0.5}>
          {Array.from({ length: visibleCount }, (_, i) => (
            <InputTypeInElementField
              key={`starter_messages.${i}`}
              name={`starter_messages.${i}`}
              placeholder={
                STARTER_MESSAGES_EXAMPLES[i] ||
                "输入一条开场问题..."
              }
              onRemove={() => arrayHelpers.remove(i)}
            />
          ))}
        </GeneralLayouts.Section>
      )}
    </FieldArray>
  );
}

export interface AgentEditorPageProps {
  agent?: FullAgent;
  refreshAgent?: () => void;
}

export default function AgentEditorPage({
  agent: existingAgent,
  refreshAgent,
}: AgentEditorPageProps) {
  const router = useRouter();
  const appRouter = useAppRouter();
  const { refresh: refreshAgents } = useAgents();
  const shareAgentModal = useCreateModal();
  const deleteAgentModal = useCreateModal();
  const { isAdmin, isCurator } = useUser();
  const canUpdateFeaturedStatus = isAdmin || isCurator;
  const vectorDbEnabled = useVectorDbEnabled();
  const businessTier = useTierAtLeast(Tier.BUSINESS);

  // Hooks for Knowledge section
  const { allRecentFiles, beginUpload } = useProjectsContext();
  const { data: documentSets } = useDocumentSets();
  const userFilesModal = useCreateModal();
  const [presentingDocument, setPresentingDocument] = useState<{
    document_id: string;
    semantic_identifier: string;
  } | null>(null);

  const { mcpData, isLoading: isMcpLoading } = useMcpServersForAgentEditor();
  const { openApiTools: openApiToolsRaw, isLoading: isOpenApiLoading } =
    useOpenApiTools();
  const { llmProviders } = useLLMProviders(existingAgent?.id);

  // LLM Model Selection — placed after llmProviders so the callbacks can close over it
  const getCurrentLlm = useCallback((values: any, providers: any) => {
    // Canonical path: resolve from model configuration ID.
    if (values.default_model_configuration_id != null) {
      for (const p of providers ?? []) {
        const mc = p.model_configurations?.find(
          (m: any) => m.id === values.default_model_configuration_id
        );
        if (mc) {
          return structureValue(p.name ?? String(p.id), p.provider, mc.name);
        }
      }
    }
    return null;
  }, []);

  const onLlmSelect = useCallback(
    (selected: string | null, setFieldValue: any) => {
      if (selected === null) {
        setFieldValue("default_model_configuration_id", null);
      } else {
        const { modelName, name } = parseLlmDescriptor(selected);
        if (modelName) {
          // `name` is either the display name or String(provider.id) for nameless
          // providers, so we match by both.
          const provider = llmProviders?.find(
            (p: any) => p.name === name || String(p.id) === name
          );
          const modelConfig = provider?.model_configurations?.find(
            (mc: any) => mc.name === modelName
          );
          setFieldValue(
            "default_model_configuration_id",
            modelConfig?.id ?? null
          );
        }
      }
    },
    [llmProviders]
  );

  const mcpServers = mcpData?.mcp_servers ?? [];
  const openApiTools = openApiToolsRaw ?? [];

  // Check if the *BUILT-IN* tools are available.
  // The built-in tools are:
  // - image-gen
  // - web-search
  // - code-interpreter
  const { tools: availableTools, isLoading: isToolsLoading } =
    useAvailableTools();
  const searchTool = availableTools?.find(
    (t) => t.in_code_tool_id === SEARCH_TOOL_ID
  );
  const imageGenTool = availableTools?.find(
    (t) => t.in_code_tool_id === IMAGE_GENERATION_TOOL_ID
  );
  const webSearchTool = availableTools?.find(
    (t) => t.in_code_tool_id === WEB_SEARCH_TOOL_ID
  );
  const openURLTool = availableTools?.find(
    (t) => t.in_code_tool_id === OPEN_URL_TOOL_ID
  );
  const codeInterpreterTool = availableTools?.find(
    (t) => t.in_code_tool_id === PYTHON_TOOL_ID
  );
  const codingAgentTool = availableTools?.find(
    (t) => t.in_code_tool_id === CODING_AGENT_TOOL_ID
  );
  const isImageGenerationAvailable = !!imageGenTool;
  const imageGenerationDisabledTooltip = isImageGenerationAvailable
    ? undefined
    : "图片生成需要先配置模型。如果你有权限，请在“设置 > 图片生成”中配置，或联系管理员。";

  // Group MCP server tools from availableTools by server ID
  const mcpServersWithTools = mcpServers.map((server) => {
    const serverTools: MCPTool[] = (availableTools || [])
      .filter((tool) => tool.mcp_server_id === server.id)
      .map((tool) => ({
        id: tool.id.toString(),
        icon: getActionIcon(server.server_url, server.name),
        name: tool.display_name || tool.name,
        description: tool.description,
        isAvailable: true,
        isEnabled: tool.enabled,
      }));

    return { server, tools: serverTools, isLoading: false };
  });

  const initialValues = {
    // General
    icon_name: existingAgent?.icon_name ?? null,
    uploaded_image_id: existingAgent?.uploaded_image_id ?? null,
    remove_image: false,
    name: existingAgent?.name ?? "",
    description: existingAgent?.description ?? "",

    // Prompts
    instructions: existingAgent?.system_prompt ?? "",
    starter_messages: Array.from(
      { length: STARTER_MESSAGES_EXAMPLES.length },
      (_, i) => existingAgent?.starter_messages?.[i]?.message ?? ""
    ),

    // Knowledge - enabled if the agent has the internal search tool attached
    // or any knowledge sources attached.
    enable_knowledge:
      (existingAgent?.tools?.some(
        (tool) => tool.in_code_tool_id === SEARCH_TOOL_ID
      ) ??
        false) ||
      (existingAgent?.document_sets?.length ?? 0) > 0 ||
      (existingAgent?.hierarchy_nodes?.length ?? 0) > 0 ||
      (existingAgent?.attached_documents?.length ?? 0) > 0 ||
      (existingAgent?.user_file_ids?.length ?? 0) > 0,
    document_set_ids: existingAgent?.document_sets?.map((ds) => ds.id) ?? [],
    // Individual document IDs from hierarchy browsing
    document_ids: existingAgent?.attached_documents?.map((doc) => doc.id) ?? [],
    // Hierarchy node IDs (folders/spaces/channels) for scoped search
    hierarchy_node_ids:
      existingAgent?.hierarchy_nodes?.map((node) => node.id) ?? [],
    user_file_ids: existingAgent?.user_file_ids ?? [],
    // Selected sources for the new knowledge UI - derived from document sets
    selected_sources: [] as ValidSources[],

    // Advanced
    default_model_configuration_id:
      existingAgent?.default_model_configuration_id ?? null,
    knowledge_cutoff_date: existingAgent?.search_start_date
      ? new Date(existingAgent.search_start_date)
      : null,
    replace_base_system_prompt:
      existingAgent?.replace_base_system_prompt ?? false,
    reminders: existingAgent?.task_prompt ?? "",
    // For new agents, default to false for optional tools to avoid
    // "Tool not available" errors when the tool isn't configured.
    // For existing agents, preserve the current tool configuration.
    image_generation:
      !!imageGenTool &&
      (existingAgent?.tools?.some(
        (tool) => tool.in_code_tool_id === IMAGE_GENERATION_TOOL_ID
      ) ??
        false),
    web_search:
      !!webSearchTool &&
      (existingAgent?.tools?.some(
        (tool) => tool.in_code_tool_id === WEB_SEARCH_TOOL_ID
      ) ??
        false),
    open_url:
      !!openURLTool &&
      (existingAgent?.tools?.some(
        (tool) => tool.in_code_tool_id === OPEN_URL_TOOL_ID
      ) ??
        false),
    code_interpreter:
      !!codeInterpreterTool &&
      (existingAgent?.tools?.some(
        (tool) => tool.in_code_tool_id === PYTHON_TOOL_ID
      ) ??
        false),
    coding_agent:
      !!codingAgentTool &&
      (existingAgent?.tools?.some(
        (tool) => tool.in_code_tool_id === CODING_AGENT_TOOL_ID
      ) ??
        false),
    // MCP servers - dynamically add fields for each server with nested tool fields
    ...Object.fromEntries(
      mcpServersWithTools.map(({ server, tools }) => {
        // Find all tools from existingAgent that belong to this MCP server
        const serverToolsFromAgent =
          existingAgent?.tools?.filter(
            (tool) => tool.mcp_server_id === server.id
          ) ?? [];

        // Build the tool field object with tool_{id} for ALL available tools
        const toolFields: Record<string, boolean> = {};
        tools.forEach((tool) => {
          // Set to true if this tool was enabled in existingAgent, false otherwise
          toolFields[`tool_${tool.id}`] = serverToolsFromAgent.some(
            (t) => t.id === Number(tool.id)
          );
        });

        return [
          `mcp_server_${server.id}`,
          {
            enabled: serverToolsFromAgent.length > 0, // Server is enabled if it has any tools
            ...toolFields, // Add individual tool states for ALL tools
          },
        ];
      })
    ),

    // OpenAPI tools - add a boolean field for each tool
    ...Object.fromEntries(
      openApiTools.map((openApiTool) => [
        `openapi_tool_${openApiTool.id}`,
        existingAgent?.tools?.some((t) => t.id === openApiTool.id) ?? false,
      ])
    ),

    // Sharing
    shared_user_ids: existingAgent?.users?.map((user) => user.id) ?? [],
    shared_group_ids: existingAgent?.groups ?? [],
    is_public: existingAgent?.is_public ?? false,
    label_ids: existingAgent?.labels?.map((l) => l.id) ?? [],
    is_featured: existingAgent?.is_featured ?? false,
  };

  const validationSchema = Yup.object().shape({
    // General
    icon_name: Yup.string().nullable(),
    remove_image: Yup.boolean().optional(),
    uploaded_image_id: Yup.string().nullable(),
    name: Yup.string().required("请输入智能体名称。"),
    description: Yup.string()
      .max(
        MAX_CHARACTERS_AGENT_DESCRIPTION,
        `描述不能超过 ${MAX_CHARACTERS_AGENT_DESCRIPTION} 个字符`
      )
      .optional(),

    // Prompts
    instructions: Yup.string().optional(),
    starter_messages: Yup.array().of(
      Yup.string().max(
        MAX_CHARACTERS_STARTER_MESSAGE,
        `开场问题不能超过 ${MAX_CHARACTERS_STARTER_MESSAGE} 个字符`
      )
    ),

    // Knowledge
    enable_knowledge: Yup.boolean(),
    document_set_ids: Yup.array().of(Yup.number()),
    document_ids: Yup.array().of(Yup.string()),
    hierarchy_node_ids: Yup.array().of(Yup.number()),
    user_file_ids: Yup.array().of(Yup.string()),
    selected_sources: Yup.array().of(Yup.string()),

    // Advanced
    default_model_configuration_id: Yup.number().nullable().optional(),
    knowledge_cutoff_date: Yup.date()
      .nullable()
      .optional()
      .test(
        "knowledge-cutoff-date-not-in-future",
        "知识截止日期不能晚于今天。",
        (value) => !value || !isDateInFuture(value)
      ),
    replace_base_system_prompt: Yup.boolean(),
    reminders: Yup.string().optional(),

    // MCP servers - dynamically add validation for each server with nested tool validation
    ...Object.fromEntries(
      mcpServers.map((server) => [
        `mcp_server_${server.id}`,
        Yup.object(), // Allow any nested tool fields as booleans
      ])
    ),

    // OpenAPI tools - add boolean validation for each tool
    ...Object.fromEntries(
      openApiTools.map((openApiTool) => [
        `openapi_tool_${openApiTool.id}`,
        Yup.boolean(),
      ])
    ),
  });

  async function handleSubmit(values: typeof initialValues) {
    try {
      // Map conversation starters
      const starterMessages = values.starter_messages
        .filter((message: string) => message.trim() !== "")
        .map((message: string) => ({
          message: message,
          name: message,
        }));

      // Send null instead of empty array if no starter messages
      const finalAgentStarterMessages =
        starterMessages.length > 0 ? starterMessages : null;

      // Always look up tools in availableTools to ensure we can find all tools

      const toolIds = [];
      if (values.enable_knowledge) {
        if (vectorDbEnabled && searchTool) {
          toolIds.push(searchTool.id);
        }
      }
      if (values.image_generation && imageGenTool) {
        toolIds.push(imageGenTool.id);
      }
      if (values.web_search && webSearchTool) {
        toolIds.push(webSearchTool.id);
      }
      if (values.open_url && openURLTool) {
        toolIds.push(openURLTool.id);
      }
      if (values.code_interpreter && codeInterpreterTool) {
        toolIds.push(codeInterpreterTool.id);
      }
      if (values.coding_agent && codingAgentTool) {
        toolIds.push(codingAgentTool.id);
      }

      // Collect enabled MCP tool IDs
      mcpServers.forEach((server) => {
        const serverFieldName = `mcp_server_${server.id}`;
        const serverData = (values as any)[serverFieldName];

        if (
          serverData &&
          typeof serverData === "object" &&
          serverData.enabled
        ) {
          // Server is enabled, collect all enabled tools
          Object.keys(serverData).forEach((key) => {
            if (key.startsWith("tool_") && serverData[key] === true) {
              // Extract tool ID from key (e.g., "tool_123" -> 123)
              const toolId = parseInt(key.replace("tool_", ""), 10);
              if (!isNaN(toolId)) {
                toolIds.push(toolId);
              }
            }
          });
        }
      });

      // Collect enabled OpenAPI tool IDs
      openApiTools.forEach((openApiTool) => {
        const toolFieldName = `openapi_tool_${openApiTool.id}`;
        if ((values as any)[toolFieldName] === true) {
          toolIds.push(openApiTool.id);
        }
      });

      // Build submission data
      const submissionData: AgentUpsertParameters = {
        name: values.name,
        description: values.description,
        document_set_ids: values.enable_knowledge
          ? values.document_set_ids
          : [],
        is_public: values.is_public,
        default_model_configuration_id:
          (values as any).default_model_configuration_id ?? null,
        starter_messages: finalAgentStarterMessages,
        users: values.shared_user_ids,
        groups: values.shared_group_ids,
        tool_ids: toolIds,
        // uploaded_image: null, // Already uploaded separately
        remove_image: values.remove_image ?? false,
        uploaded_image_id: values.uploaded_image_id,
        icon_name: values.icon_name,
        search_start_date: values.knowledge_cutoff_date || null,
        label_ids: values.label_ids,
        is_featured: values.is_featured,
        // display_priority: ...,

        user_file_ids: values.enable_knowledge ? values.user_file_ids : [],
        hierarchy_node_ids: values.enable_knowledge
          ? values.hierarchy_node_ids
          : [],
        document_ids: values.enable_knowledge ? values.document_ids : [],

        system_prompt: values.instructions,
        replace_base_system_prompt: values.replace_base_system_prompt,
        task_prompt: values.reminders || "",
        datetime_aware: false,
      };

      // Call API
      let personaResponse;
      if (existingAgent) {
        personaResponse = await updateAgent(existingAgent.id, submissionData);
      } else {
        personaResponse = await createAgent(submissionData);
      }

      // Handle response
      if (!personaResponse || !personaResponse.ok) {
        const error = personaResponse
          ? await personaResponse.text()
          : "未收到响应";
        toast.error(
          `${existingAgent ? "更新" : "创建"}智能体失败 - ${error}`
        );
        return;
      }

      // Success
      const agent = await personaResponse.json();
      toast.success(
        `智能体“${agent.name}”已成功${existingAgent ? "更新" : "创建"}`
      );

      // Refresh agents list and the specific agent
      await refreshAgents();
      if (refreshAgent) {
        refreshAgent();
      }

      // Immediately start a chat with this agent.
      appRouter({ agentId: agent.id });
    } catch (error) {
      console.error("Submit error:", error);
      toast.error(`发生错误：${error}`);
    }
  }

  // Delete agent handler
  async function handleDeleteAgent() {
    if (!existingAgent) return;

    try {
      await deleteAgent(existingAgent.id);
      toast.success("智能体已删除");
      deleteAgentModal.toggle(false);
      await refreshAgents();
      router.push("/app/agents");
    } catch (e) {
      console.error("Delete agent error:", e);
      toast.error(
        `Failed to delete agent: ${
          e instanceof Error ? e.message : "未知错误"
        }`
      );
    }
  }

  // FilePickerPopover callbacks for Knowledge section
  function handlePickRecentFile(
    file: ProjectFile,
    currentFileIds: string[],
    setFieldValue: (field: string, value: unknown) => void
  ) {
    if (!currentFileIds.includes(file.id)) {
      setFieldValue("user_file_ids", [...currentFileIds, file.id]);
    }
  }

  function handleUnpickRecentFile(
    file: ProjectFile,
    currentFileIds: string[],
    setFieldValue: (field: string, value: unknown) => void
  ) {
    setFieldValue(
      "user_file_ids",
      currentFileIds.filter((id) => id !== file.id)
    );
  }

  function handleFileClick(file: ProjectFile) {
    setPresentingDocument({
      document_id: `project_file__${file.file_id}`,
      semantic_identifier: file.name,
    });
  }

  async function handleUploadChange(
    e: React.ChangeEvent<HTMLInputElement>,
    currentFileIds: string[],
    setFieldValue: (field: string, value: unknown) => void
  ) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    try {
      let selectedIds = [...(currentFileIds || [])];
      const optimistic = await beginUpload(
        Array.from(files),
        null,
        (result) => {
          const uploadedFiles = result.user_files || [];
          if (uploadedFiles.length === 0) return;
          const tempToFinal = new Map(
            uploadedFiles
              .filter((f) => f.temp_id)
              .map((f) => [f.temp_id as string, f.id])
          );
          const replaced = (selectedIds || []).map(
            (id: string) => tempToFinal.get(id) ?? id
          );
          selectedIds = replaced;
          setFieldValue("user_file_ids", replaced);
        }
      );
      if (optimistic) {
        const optimisticIds = optimistic.map((f) => f.id);
        selectedIds = [...selectedIds, ...optimisticIds];
        setFieldValue("user_file_ids", selectedIds);
      }
    } catch (error) {
      console.error("Upload error:", error);
    }
  }

  // Wait for async tool data before rendering the form. Formik captures
  // initialValues on mount — if tools haven't loaded yet, the initial values
  // won't include MCP tool fields. Later, toggling those fields would make
  // the form permanently dirty since they have no baseline to compare against.
  if (isToolsLoading || isMcpLoading || isOpenApiLoading) {
    return null;
  }

  return (
    <>
      <div
        data-testid="AgentsEditorPage/container"
        aria-label="智能体编辑页"
        className="h-full w-full"
      >
        <Formik
          initialValues={initialValues}
          validationSchema={validationSchema}
          onSubmit={handleSubmit}
          validateOnChange
          validateOnBlur
          validateOnMount
          initialTouched={{
            description:
              initialValues.description.length >
              MAX_CHARACTERS_AGENT_DESCRIPTION,
            starter_messages: initialValues.starter_messages.map(
              (msg) => msg.length > MAX_CHARACTERS_STARTER_MESSAGE
            ) as unknown as boolean,
          }}
          initialStatus={{ warnings: {} }}
        >
          {({ isSubmitting, isValid, dirty, values, setFieldValue }) => {
            const fileStatusMap = new Map(
              allRecentFiles.map((f) => [f.id, f.status])
            );

            const hasUploadingFiles = values.user_file_ids.some(
              (fileId: string) => {
                const status = fileStatusMap.get(fileId);
                if (status === undefined) {
                  return fileId.startsWith("temp_");
                }
                return status === UserFileStatus.UPLOADING;
              }
            );

            const hasProcessingFiles = values.user_file_ids.some(
              (fileId: string) =>
                fileStatusMap.get(fileId) === UserFileStatus.PROCESSING
            );
            const isShared =
              values.is_public ||
              values.shared_user_ids.length > 0 ||
              values.shared_group_ids.length > 0;

            return (
              <>
                <FormWarningsEffect />

                <userFilesModal.Provider>
                  <UserFilesModal
                    title="用户文件"
                    description="此智能体已选择的全部文件"
                    recentFiles={values.user_file_ids
                      .map((userFileId: string) => {
                        const rf = allRecentFiles.find(
                          (f) => f.id === userFileId
                        );
                        if (rf) return rf;
                        return {
                          id: userFileId,
                          name: `文件 ${userFileId.slice(0, 8)}`,
                          status: UserFileStatus.COMPLETED,
                          file_id: userFileId,
                          created_at: new Date().toISOString(),
                          project_id: null,
                          user_id: null,
                          file_type: "",
                          last_accessed_at: new Date().toISOString(),
                          chat_file_type: "file" as const,
                        } as unknown as ProjectFile;
                      })
                      .filter((f): f is ProjectFile => f !== null)}
                    selectedFileIds={values.user_file_ids}
                    onPickRecent={(file: ProjectFile) => {
                      if (!values.user_file_ids.includes(file.id)) {
                        setFieldValue("user_file_ids", [
                          ...values.user_file_ids,
                          file.id,
                        ]);
                      }
                    }}
                    onUnpickRecent={(file: ProjectFile) => {
                      setFieldValue(
                        "user_file_ids",
                        values.user_file_ids.filter((id) => id !== file.id)
                      );
                    }}
                    onView={(file: ProjectFile) => {
                      setPresentingDocument({
                        document_id: `project_file__${file.file_id}`,
                        semantic_identifier: file.name,
                      });
                    }}
                  />
                </userFilesModal.Provider>

                <shareAgentModal.Provider>
                  <ShareAgentModal
                    agentId={existingAgent?.id}
                    userIds={values.shared_user_ids}
                    groupIds={values.shared_group_ids}
                    isPublic={values.is_public}
                    isFeatured={values.is_featured}
                    labelIds={values.label_ids}
                    onShare={async (
                      userIds,
                      groupIds,
                      isPublic,
                      isFeatured,
                      labelIds
                    ) => {
                      if (!existingAgent) {
                        // New agents are not persisted until the main Create action.
                        setFieldValue("shared_user_ids", userIds);
                        setFieldValue("shared_group_ids", groupIds);
                        setFieldValue("is_public", isPublic);
                        setFieldValue("is_featured", isFeatured);
                        setFieldValue("label_ids", labelIds);
                        shareAgentModal.toggle(false);
                        return;
                      }

                      const applySharingFields = () => {
                        setFieldValue("shared_user_ids", userIds);
                        setFieldValue("shared_group_ids", groupIds);
                        setFieldValue("is_public", isPublic);
                        setFieldValue("label_ids", labelIds);
                      };

                      const refreshSharedUi = async () => {
                        try {
                          await refreshAgents();
                          refreshAgent?.();
                        } catch (error) {
                          console.error(
                            "Refresh failed after successful share:",
                            error
                          );
                          toast.error(
                            "智能体共享设置已保存，但刷新失败。请重新加载页面。"
                          );
                        }
                      };

                      let shareError: string | null;
                      try {
                        shareError = await updateAgentSharedStatus(
                          existingAgent.id,
                          userIds,
                          groupIds,
                          isPublic,
                          businessTier,
                          labelIds
                        );
                      } catch (error) {
                        console.error(
                          "Share agent mutation failed unexpectedly:",
                          error
                        );
                        toast.error("共享智能体失败，请重试。");
                        return;
                      }

                      if (shareError) {
                        toast.error(`共享智能体失败：${shareError}`);
                        return;
                      }

                      if (canUpdateFeaturedStatus) {
                        let featuredError: string | null;
                        try {
                          featuredError = await updateAgentFeaturedStatus(
                            existingAgent.id,
                            isFeatured
                          );
                        } catch (error) {
                          console.error(
                            "Featured mutation failed unexpectedly:",
                            error
                          );
                          // Share succeeded; sync form and UI before returning.
                          applySharingFields();
                          await refreshSharedUi();
                          toast.error(
                            "更新精选状态失败，请重试。"
                          );
                          return;
                        }

                        if (featuredError) {
                          // Share succeeded, featured failed: keep modal open for retry.
                          applySharingFields();
                          await refreshSharedUi();
                          toast.error(
                            `更新精选状态失败：${featuredError}`
                          );
                          return;
                        }

                        applySharingFields();
                        setFieldValue("is_featured", isFeatured);
                        shareAgentModal.toggle(false);
                        await refreshSharedUi();
                        return;
                      }

                      applySharingFields();
                      shareAgentModal.toggle(false);
                      await refreshSharedUi();
                    }}
                  />
                </shareAgentModal.Provider>
                <deleteAgentModal.Provider>
                  {deleteAgentModal.isOpen && (
                    <ConfirmationModalLayout
                      icon={SvgTrash}
                      title="删除智能体"
                      submit={
                        <Button variant="danger" onClick={handleDeleteAgent}>
                          删除智能体
                        </Button>
                      }
                      onClose={() => deleteAgentModal.toggle(false)}
                    >
                      <GeneralLayouts.Section alignItems="start" gap={0.5}>
                        <Text>
                          正在使用此智能体的用户将无法再访问它。删除后无法撤销。
                        </Text>
                        <Text>确定要删除这个智能体吗？</Text>
                      </GeneralLayouts.Section>
                    </ConfirmationModalLayout>
                  )}
                </deleteAgentModal.Provider>

                <Form className="h-full w-full">
                  <SettingsLayouts.Root>
                    <SettingsLayouts.Header
                      icon={SvgSparkle}
                      title={existingAgent ? "编辑智能体" : "创建智能体"}
                      rightChildren={
                        <div className="flex gap-2">
                          <Button
                            prominence="secondary"
                            type="button"
                            onClick={() => router.back()}
                          >
                            取消
                          </Button>
                          <Tooltip
                            tooltip={
                              isSubmitting
                                ? "正在保存更改..."
                                : !isValid
                                  ? "请先修正表单错误再保存。"
                                  : !dirty
                                    ? "尚未进行任何更改。"
                                    : hasUploadingFiles
                                      ? "请等待文件上传完成。"
                                      : undefined
                            }
                            side="bottom"
                          >
                            <Button
                              disabled={
                                isSubmitting ||
                                !isValid ||
                                !dirty ||
                                hasUploadingFiles
                              }
                              type="submit"
                            >
                              {existingAgent ? "保存" : "创建"}
                            </Button>
                          </Tooltip>
                        </div>
                      }
                      backButton
                      divider
                    />

                    {/* Agent Form Content */}
                    <SettingsLayouts.Body>
                      <GeneralLayouts.Section
                        flexDirection="row"
                        gap={2.5}
                        alignItems="start"
                      >
                        <GeneralLayouts.Section>
                          <InputVertical withLabel="name" title="名称">
                            <InputTypeInField
                              name="name"
                              placeholder="为智能体命名"
                            />
                          </InputVertical>

                          <InputVertical
                            withLabel="description"
                            title="描述"
                            suffix="可选"
                          >
                            <InputTextAreaField
                              name="description"
                              placeholder="这个智能体能做什么？"
                            />
                          </InputVertical>
                        </GeneralLayouts.Section>

                        <GeneralLayouts.Section width="fit">
                          <InputVertical
                            withLabel="agent_avatar"
                            title="智能体头像"
                          >
                            <AgentIconEditor existingAgent={existingAgent} />
                          </InputVertical>
                        </GeneralLayouts.Section>
                      </GeneralLayouts.Section>

                      <Divider
                        paddingParallel="fit"
                        paddingPerpendicular="fit"
                      />

                      <GeneralLayouts.Section>
                        <InputVertical
                          withLabel="instructions"
                          title="指令"
                          suffix="可选"
                          description="添加指令，用来定制这个智能体的回答方式。"
                        >
                          <InputTextAreaField
                            name="instructions"
                            placeholder="请逐步思考，并在复杂问题中展示推理过程。使用具体示例，突出行动项；遇到未知信息时为用户留出待补充位置。语气礼貌且积极。"
                          />
                        </InputVertical>

                        <InputVertical
                          withLabel="starter_messages"
                          title="开场问题"
                          description="示例问题可帮助用户了解这个智能体能做什么，以及如何更有效地与它互动。"
                          suffix="可选"
                        >
                          <AgentStarterMessages />
                        </InputVertical>
                      </GeneralLayouts.Section>

                      <Divider
                        paddingParallel="fit"
                        paddingPerpendicular="fit"
                      />

                      <AgentKnowledgePane
                        enableKnowledge={values.enable_knowledge}
                        onEnableKnowledgeChange={(enabled) =>
                          setFieldValue("enable_knowledge", enabled)
                        }
                        selectedSources={values.selected_sources}
                        onSourcesChange={(sources) =>
                          setFieldValue("selected_sources", sources)
                        }
                        documentSets={documentSets ?? []}
                        selectedDocumentSetIds={values.document_set_ids}
                        onDocumentSetIdsChange={(ids) =>
                          setFieldValue("document_set_ids", ids)
                        }
                        selectedDocumentIds={values.document_ids}
                        onDocumentIdsChange={(ids) =>
                          setFieldValue("document_ids", ids)
                        }
                        selectedFolderIds={values.hierarchy_node_ids}
                        onFolderIdsChange={(ids) =>
                          setFieldValue("hierarchy_node_ids", ids)
                        }
                        selectedFileIds={values.user_file_ids}
                        onFileIdsChange={(ids) =>
                          setFieldValue("user_file_ids", ids)
                        }
                        allRecentFiles={allRecentFiles}
                        onFileClick={handleFileClick}
                        onUploadChange={(e) =>
                          handleUploadChange(
                            e,
                            values.user_file_ids,
                            setFieldValue
                          )
                        }
                        hasProcessingFiles={hasProcessingFiles}
                        initialAttachedDocuments={
                          existingAgent?.attached_documents
                        }
                        initialHierarchyNodes={existingAgent?.hierarchy_nodes}
                        vectorDbEnabled={vectorDbEnabled}
                      />

                      <Divider
                        paddingParallel="fit"
                        paddingPerpendicular="fit"
                      />

                      <SimpleCollapsible>
                        <SimpleCollapsible.Header
                          title="工具与能力"
                          description="此智能体可使用的工具和能力。"
                        />
                        <SimpleCollapsible.Content>
                          <GeneralLayouts.Section gap={0.5}>
                            <Disabled
                              disabled={!isImageGenerationAvailable}
                              tooltip={imageGenerationDisabledTooltip}
                            >
                              <Card border="solid" rounding="lg">
                                <InputHorizontal
                                  withLabel="image_generation"
                                  title="图片生成"
                                  description="使用 AI 工具生成和编辑图片。"
                                  disabled={!isImageGenerationAvailable}
                                >
                                  <SwitchField
                                    name="image_generation"
                                    disabled={!isImageGenerationAvailable}
                                  />
                                </InputHorizontal>
                              </Card>
                            </Disabled>

                            <Disabled disabled={!webSearchTool}>
                              <Card border="solid" rounding="lg">
                                <InputHorizontal
                                  withLabel="web_search"
                                  title="网页搜索"
                                  description="搜索网页，获取实时信息和最新结果。"
                                  disabled={!webSearchTool}
                                >
                                  <SwitchField
                                    name="web_search"
                                    disabled={!webSearchTool}
                                  />
                                </InputHorizontal>
                              </Card>
                            </Disabled>

                            <Disabled disabled={!openURLTool}>
                              <Card border="solid" rounding="lg">
                                <InputHorizontal
                                  withLabel="open_url"
                                  title="打开链接"
                                  description="获取并读取网页链接中的内容。"
                                  disabled={!openURLTool}
                                >
                                  <SwitchField
                                    name="open_url"
                                    disabled={!openURLTool}
                                  />
                                </InputHorizontal>
                              </Card>
                            </Disabled>

                            <Disabled disabled={!codeInterpreterTool}>
                              <Card border="solid" rounding="lg">
                                <InputHorizontal
                                  withLabel="code_interpreter"
                                  title="代码解释器"
                                  description="生成并运行代码。"
                                  disabled={!codeInterpreterTool}
                                >
                                  <SwitchField
                                    name="code_interpreter"
                                    disabled={!codeInterpreterTool}
                                  />
                                </InputHorizontal>
                              </Card>
                            </Disabled>

                            <Disabled disabled={!codingAgentTool}>
                              <Card border="solid" rounding="lg">
                                <InputHorizontal
                                  withLabel="coding_agent"
                                  title="代码智能体"
                                  description="分析 GitHub 仓库，并回答与代码相关的问题。"
                                  disabled={!codingAgentTool}
                                >
                                  <SwitchField
                                    name="coding_agent"
                                    disabled={!codingAgentTool}
                                  />
                                </InputHorizontal>
                              </Card>
                            </Disabled>

                            {/* Tools */}
                            <>
                              {/* render the divider if there is at least one mcp-server or open-api-tool */}
                              {(mcpServers.length > 0 ||
                                openApiTools.length > 0) && (
                                <Divider
                                  paddingPerpendicular="xs"
                                  paddingParallel="fit"
                                />
                              )}

                              {/* MCP tools */}
                              {mcpServersWithTools.length > 0 && (
                                <GeneralLayouts.Section gap={0.5}>
                                  {mcpServersWithTools.map(
                                    ({ server, tools, isLoading }) => (
                                      <MCPServerCard
                                        key={server.id}
                                        server={server}
                                        tools={tools}
                                        isLoading={isLoading}
                                      />
                                    )
                                  )}
                                </GeneralLayouts.Section>
                              )}

                              {/* OpenAPI tools */}
                              {openApiTools.length > 0 && (
                                <GeneralLayouts.Section gap={0.5}>
                                  {openApiTools.map((tool) => (
                                    <OpenApiToolCard
                                      key={tool.id}
                                      tool={tool}
                                    />
                                  ))}
                                </GeneralLayouts.Section>
                              )}
                            </>
                          </GeneralLayouts.Section>
                        </SimpleCollapsible.Content>
                      </SimpleCollapsible>

                      <Divider
                        paddingParallel="fit"
                        paddingPerpendicular="fit"
                      />

                      <SimpleCollapsible>
                        <SimpleCollapsible.Header
                          title="高级选项"
                          description="微调智能体提示词和知识设置。"
                        />
                        <SimpleCollapsible.Content>
                          <GeneralLayouts.Section>
                            <Card border="solid" rounding="lg">
                              <GeneralLayouts.Section>
                                <InputHorizontal
                                  title="共享此智能体"
                                  description="与其他用户、用户组或组织内所有人共享。"
                                  center
                                >
                                  <Button
                                    prominence="secondary"
                                    icon={isShared ? SvgUsers : SvgLock}
                                    onClick={() => shareAgentModal.toggle(true)}
                                  >
                                    共享
                                  </Button>
                                </InputHorizontal>
                                {canUpdateFeaturedStatus && (
                                  <>
                                    <InputHorizontal
                                      withLabel="is_featured"
                                      title="设为精选智能体"
                                      description="将此智能体显示在探索智能体列表顶部，并为有访问权限的新用户自动固定到侧边栏。"
                                    >
                                      <SwitchField name="is_featured" />
                                    </InputHorizontal>
                                    {values.is_featured && !isShared && (
                                      <MessageCard title="此智能体目前仅你可见，因此只会对你自己显示为精选。" />
                                    )}
                                  </>
                                )}
                              </GeneralLayouts.Section>
                            </Card>

                            <Card border="solid" rounding="lg">
                              <GeneralLayouts.Section>
                                <InputHorizontal
                                  withLabel="llm_model"
                                  title="默认模型"
                                  description="Glomi AI 会默认在你的对话中使用此模型。"
                                >
                                  <LLMSelector
                                    name="llm_model"
                                    llmProviders={llmProviders ?? []}
                                    currentLlm={getCurrentLlm(
                                      values,
                                      llmProviders
                                    )}
                                    onSelect={(selected) =>
                                      onLlmSelect(selected, setFieldValue)
                                    }
                                  />
                                </InputHorizontal>
                                <InputHorizontal
                                  withLabel="knowledge_cutoff_date"
                                  title="知识截止日期"
                                  suffix="可选"
                                  description="最后更新时间早于此日期的文档将被忽略。"
                                >
                                  <InputDatePickerField
                                    name="knowledge_cutoff_date"
                                    maxDate={new Date()}
                                  />
                                </InputHorizontal>
                                <InputHorizontal
                                  withLabel="replace_base_system_prompt"
                                  title="覆盖系统提示词"
                                  suffix="（不推荐）"
                                  description="移除基础系统提示词，其中包含有用指令（例如“你可以使用 Markdown 表格”）。这可能会影响回答质量。"
                                >
                                  <SwitchField name="replace_base_system_prompt" />
                                </InputHorizontal>
                              </GeneralLayouts.Section>
                            </Card>

                            <GeneralLayouts.Section gap={0.25}>
                              <InputVertical
                                withLabel="reminders"
                                title="提醒"
                                suffix="可选"
                              >
                                <InputTextAreaField
                                  name="reminders"
                                  placeholder="请记住，我希望你始终使用编号列表来组织回答。"
                                />
                              </InputVertical>
                              <Text text03 secondaryBody>
                                在提示词消息末尾追加一段简短提醒。如果你发现智能体在对话推进时容易忘记某些指令，可以用它来提醒。内容应保持简短，并避免干扰用户消息。
                              </Text>
                            </GeneralLayouts.Section>
                          </GeneralLayouts.Section>
                        </SimpleCollapsible.Content>
                      </SimpleCollapsible>

                      {existingAgent && (
                        <>
                          <Divider
                            paddingParallel="fit"
                            paddingPerpendicular="fit"
                          />

                          <Card border="solid" rounding="lg">
                            <InputHorizontal
                              title="删除此智能体"
                              description="正在使用此智能体的用户将无法再访问它。"
                              center
                            >
                              <Button
                                variant="danger"
                                prominence="secondary"
                                onClick={() => deleteAgentModal.toggle(true)}
                              >
                                删除智能体
                              </Button>
                            </InputHorizontal>
                          </Card>
                        </>
                      )}
                    </SettingsLayouts.Body>
                  </SettingsLayouts.Root>
                </Form>
              </>
            );
          }}
        </Formik>
      </div>
    </>
  );
}
