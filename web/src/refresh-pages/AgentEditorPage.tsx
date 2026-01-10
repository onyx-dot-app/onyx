"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import Button from "@/refresh-components/buttons/Button";
import { FullPersona } from "@/app/admin/assistants/interfaces";
import { buildImgUrl } from "@/app/chat/components/files/images/utils";
import { Formik, Form, FieldArray } from "formik";
import * as Yup from "yup";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInElementField from "@/refresh-components/form/InputTypeInElementField";
import InputDatePickerField from "@/refresh-components/form/InputDatePickerField";
import Separator from "@/refresh-components/Separator";
import * as InputLayouts from "@/layouts/input-layouts";
import { useFormikContext } from "formik";
import LLMSelector from "@/components/llm/LLMSelector";
import { parseLlmDescriptor, structureValue } from "@/lib/llm/utils";
import { useLLMProviders } from "@/lib/hooks/useLLMProviders";
import {
  STARTER_MESSAGES_EXAMPLES,
  MAX_CHARACTERS_STARTER_MESSAGE,
  MAX_CHARACTERS_AGENT_DESCRIPTION,
  MAX_CHUNKS_FED_TO_CHAT,
} from "@/lib/constants";
import {
  IMAGE_GENERATION_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
  PYTHON_TOOL_ID,
  SEARCH_TOOL_ID,
  OPEN_URL_TOOL_ID,
} from "@/app/chat/components/tools/constants";
import Text from "@/refresh-components/texts/Text";
import { Card } from "@/refresh-components/cards";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import SwitchField from "@/refresh-components/form/SwitchField";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { useDocumentSets } from "@/app/admin/documents/sets/hooks";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { usePopup } from "@/components/admin/connectors/Popup";
import { DocumentSetSelectable } from "@/components/documentSet/DocumentSetSelectable";
import FilePickerPopover from "@/refresh-components/popovers/FilePickerPopover";
import { FileCard } from "@/app/chat/components/input/FileCard";
import UserFilesModal from "@/components/modals/UserFilesModal";
import {
  ProjectFile,
  UserFileStatus,
} from "@/app/chat/projects/projectsService";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
  PopoverMenu,
} from "@/components/ui/popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import {
  SvgActions,
  SvgExpand,
  SvgFold,
  SvgImage,
  SvgOnyxOctagon,
  SvgSliders,
} from "@opal/icons";
import CustomAgentAvatar, {
  agentAvatarIconMap,
} from "@/refresh-components/avatars/CustomAgentAvatar";
import InputAvatar from "@/refresh-components/inputs/InputAvatar";
import SquareButton from "@/refresh-components/buttons/SquareButton";
import { useAgents } from "@/hooks/useAgents";
import {
  createPersona,
  updatePersona,
  PersonaUpsertParameters,
} from "@/app/admin/assistants/lib";
import useMcpServers from "@/hooks/useMcpServers";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import { useAvailableTools } from "@/hooks/useAvailableTools";
import * as ActionsLayouts from "@/layouts/actions-layouts";
import { useActionsLayout } from "@/layouts/actions-layouts";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { MCPServer, MCPTool, ToolSnapshot } from "@/lib/tools/interfaces";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import useFilter from "@/hooks/useFilter";
import EnabledCount from "@/refresh-components/EnabledCount";
import useOnMount from "@/hooks/useOnMount";
import { useAppRouter } from "@/hooks/appNavigation";

interface AgentIconEditorProps {
  existingAgent?: FullPersona | null;
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
        "Web Search without the ability to open URLs can lead to significantly worse web based results.";
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
    : values.uploaded_image_id
      ? buildImgUrl(values.uploaded_image_id)
      : values.icon_name
        ? undefined
        : values.remove_image
          ? undefined
          : existingAgent?.uploaded_image_id
            ? buildImgUrl(existingAgent.uploaded_image_id)
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
        <PopoverTrigger asChild>
          <InputAvatar className="group/InputAvatar relative flex flex-col items-center justify-center h-[7.5rem] w-[7.5rem]">
            {/* We take the `InputAvatar`'s height/width (in REM) and multiply it by 16 (the REM -> px conversion factor). */}
            <CustomAgentAvatar
              size={imageSrc ? 7.5 * 16 : 40}
              src={imageSrc}
              iconName={values.icon_name ?? undefined}
              name={values.name}
            />
            <Button
              className="absolute bottom-0 left-1/2 -translate-x-1/2 h-[1.75rem] mb-2 invisible group-hover/InputAvatar:visible"
              secondary
            >
              Edit
            </Button>
          </InputAvatar>
        </PopoverTrigger>
        <PopoverContent>
          <PopoverMenu medium>
            {[
              <LineItem
                key="upload-image"
                icon={SvgImage}
                onClick={() => fileInputRef.current?.click()}
                emphasized
              >
                Upload Image
              </LineItem>,
              null,
              <div className="grid grid-cols-4 gap-1">
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
        </PopoverContent>
      </Popover>
    </>
  );
}

interface OpenApiToolCardProps {
  tool: ToolSnapshot;
}

function OpenApiToolCard({ tool }: OpenApiToolCardProps) {
  const toolFieldName = `openapi_tool_${tool.id}`;
  const actionsLayouts = useActionsLayout();

  useOnMount(() => actionsLayouts.setIsFolded(true));

  return (
    <actionsLayouts.Provider>
      <ActionsLayouts.Root>
        <ActionsLayouts.Header
          title={tool.display_name || tool.name}
          description={tool.description}
          icon={SvgActions}
          rightChildren={<SwitchField name={toolFieldName} />}
        />
      </ActionsLayouts.Root>
    </actionsLayouts.Provider>
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
  const actionsLayouts = useActionsLayout();
  const { values, setFieldValue } = useFormikContext<any>();
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

  return (
    <actionsLayouts.Provider>
      <ActionsLayouts.Root>
        <ActionsLayouts.Header
          title={server.name}
          description={server.description ?? server.server_url}
          icon={getActionIcon(server.server_url, server.name)}
          rightChildren={
            <GeneralLayouts.Section flexDirection="row" gap={0.5}>
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
                  actionsLayouts.setIsFolded(false);
                }}
              />
            </GeneralLayouts.Section>
          }
        >
          <GeneralLayouts.Section flexDirection="row" gap={0.5}>
            <InputTypeIn
              placeholder="Search tools..."
              internal
              leftSearchIcon
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <Button
              internal
              rightIcon={actionsLayouts.isFolded ? SvgExpand : SvgFold}
              onClick={() => actionsLayouts.setIsFolded((prev) => !prev)}
            >
              {actionsLayouts.isFolded ? "Expand" : "Fold"}
            </Button>
          </GeneralLayouts.Section>
        </ActionsLayouts.Header>
        <ActionsLayouts.Content>
          {isLoading ? (
            <ActionsLayouts.ToolSkeleton />
          ) : filteredTools.length === 0 ? (
            <ActionsLayouts.NoToolsFound />
          ) : (
            filteredTools.map((tool) => (
              <ActionsLayouts.Tool
                key={tool.id}
                name={`${serverFieldName}.tool_${tool.id}`}
                title={tool.name}
                description={tool.description}
                icon={tool.icon ?? SvgSliders}
                disabled={!tool.isAvailable}
                rightChildren={
                  <SwitchField
                    name={`${serverFieldName}.tool_${tool.id}`}
                    disabled={!isServerEnabled}
                  />
                }
              />
            ))
          )}
        </ActionsLayouts.Content>
      </ActionsLayouts.Root>
    </actionsLayouts.Provider>
  );
}

function StarterMessages() {
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
                "Enter a conversation starter..."
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
  agent?: FullPersona;
  refreshAgent?: () => void;
}

export default function AgentEditorPage({
  agent: existingAgent,
  refreshAgent,
}: AgentEditorPageProps) {
  const router = useRouter();
  const appRouter = useAppRouter();
  const { popup, setPopup } = usePopup();
  const { refresh: refreshAgents } = useAgents();

  // LLM Model Selection
  const getCurrentLlm = useCallback(
    (values: any, llmProviders: any) =>
      values.llm_model_version_override && values.llm_model_provider_override
        ? (() => {
            const provider = llmProviders?.find(
              (p: any) => p.name === values.llm_model_provider_override
            );
            return structureValue(
              values.llm_model_provider_override,
              provider?.provider || "",
              values.llm_model_version_override
            );
          })()
        : null,
    []
  );

  const onLlmSelect = useCallback(
    (selected: string | null, setFieldValue: any) => {
      if (selected === null) {
        setFieldValue("llm_model_version_override", null);
        setFieldValue("llm_model_provider_override", null);
      } else {
        const { modelName, name } = parseLlmDescriptor(selected);
        if (modelName && name) {
          setFieldValue("llm_model_version_override", modelName);
          setFieldValue("llm_model_provider_override", name);
        }
      }
    },
    []
  );

  // Hooks for Knowledge section
  const { allRecentFiles, beginUpload } = useProjectsContext();
  const { data: documentSets } = useDocumentSets();
  const userFilesModal = useCreateModal();
  const [presentingDocument, setPresentingDocument] = useState<{
    document_id: string;
    semantic_identifier: string;
  } | null>(null);

  const { mcpData } = useMcpServers();
  const { openApiTools: openApiToolsRaw } = useOpenApiTools();
  const { llmProviders } = useLLMProviders(existingAgent?.id);
  const mcpServers = mcpData?.mcp_servers ?? [];
  const openApiTools = openApiToolsRaw ?? [];

  // Check if the *BUILT-IN* tools are available.
  // The built-in tools are:
  // - image-gen
  // - web-search
  // - code-interpreter
  const { tools: availableTools } = useAvailableTools();
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
  const isImageGenerationAvailable = !!imageGenTool;
  const imageGenerationDisabledTooltip = isImageGenerationAvailable
    ? undefined
    : "Image generation requires a configured model. If you have access, set one up under Settings > Image Generation, or ask an admin.";

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

    // Knowledge - enabled if num_chunks is greater than 0
    // (num_chunks of 0 or null means knowledge is disabled)
    enable_knowledge: (existingAgent?.num_chunks ?? 0) > 0,
    knowledge_source:
      existingAgent?.user_file_ids && existingAgent.user_file_ids.length > 0
        ? "user_knowledge"
        : ("team_knowledge" as "team_knowledge" | "user_knowledge"),
    document_set_ids: existingAgent?.document_sets?.map((ds) => ds.id) ?? [],
    user_file_ids: existingAgent?.user_file_ids ?? [],

    // Advanced
    llm_model_provider_override:
      existingAgent?.llm_model_provider_override ?? null,
    llm_model_version_override:
      existingAgent?.llm_model_version_override ?? null,
    knowledge_cutoff_date: existingAgent?.search_start_date
      ? new Date(existingAgent.search_start_date)
      : null,
    replace_base_system_prompt:
      existingAgent?.replace_base_system_prompt ?? false,
    reminders: existingAgent?.task_prompt ?? "",
    image_generation:
      (!!imageGenTool &&
        existingAgent?.tools?.some(
          (tool) => tool.in_code_tool_id === IMAGE_GENERATION_TOOL_ID
        )) ??
      true,
    web_search:
      (!!webSearchTool &&
        existingAgent?.tools?.some(
          (tool) => tool.in_code_tool_id === WEB_SEARCH_TOOL_ID
        )) ??
      true,
    open_url:
      (!!openURLTool &&
        existingAgent?.tools?.some(
          (tool) => tool.in_code_tool_id === OPEN_URL_TOOL_ID
        )) ??
      true,
    code_interpreter:
      (!!codeInterpreterTool &&
        existingAgent?.tools?.some(
          (tool) => tool.in_code_tool_id === PYTHON_TOOL_ID
        )) ??
      true,

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
  };

  const validationSchema = Yup.object().shape({
    // General
    icon_name: Yup.string().nullable(),
    remove_image: Yup.boolean().optional(),
    uploaded_image_id: Yup.string().nullable(),
    name: Yup.string().required("Agent name is required."),
    description: Yup.string()
      .max(
        MAX_CHARACTERS_AGENT_DESCRIPTION,
        `Description must be ${MAX_CHARACTERS_AGENT_DESCRIPTION} characters or less`
      )
      .optional(),

    // Prompts
    instructions: Yup.string().optional(),
    starter_messages: Yup.array().of(
      Yup.string().max(
        MAX_CHARACTERS_STARTER_MESSAGE,
        `Conversation starter must be ${MAX_CHARACTERS_STARTER_MESSAGE} characters or less`
      )
    ),

    // Knowledge
    enable_knowledge: Yup.boolean(),
    knowledge_source: Yup.string().oneOf(["team_knowledge", "user_knowledge"]),
    document_set_ids: Yup.array().of(Yup.number()),
    user_file_ids: Yup.array().of(Yup.string()),
    num_chunks: Yup.number()
      .nullable()
      .transform((value, originalValue) =>
        originalValue === "" || originalValue === null ? null : value
      )
      .test(
        "is-non-negative-integer",
        "The number of chunks must be a non-negative integer (0, 1, 2, etc.)",
        (value) =>
          value === null ||
          value === undefined ||
          (Number.isInteger(value) && value >= 0)
      ),

    // Advanced
    llm_model_provider_override: Yup.string().nullable().optional(),
    llm_model_version_override: Yup.string().nullable().optional(),
    knowledge_cutoff_date: Yup.date().nullable().optional(),
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
      const finalStarterMessages =
        starterMessages.length > 0 ? starterMessages : null;

      // Determine knowledge settings
      const teamKnowledge = values.knowledge_source === "team_knowledge";
      const numChunks = values.enable_knowledge ? MAX_CHUNKS_FED_TO_CHAT : 0;

      // Always look up tools in availableTools to ensure we can find all tools

      const toolIds = [];
      if (values.enable_knowledge && searchTool) {
        toolIds.push(searchTool.id);
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
      const submissionData: PersonaUpsertParameters = {
        name: values.name,
        description: values.description,
        document_set_ids:
          values.enable_knowledge && teamKnowledge
            ? values.document_set_ids
            : [],
        num_chunks: numChunks,
        is_public: existingAgent?.is_public ?? true,
        // recency_bias: ...,
        // llm_filter_extraction: ...,
        llm_relevance_filter: false,
        llm_model_provider_override: values.llm_model_provider_override || null,
        llm_model_version_override: values.llm_model_version_override || null,
        starter_messages: finalStarterMessages,
        users: undefined, // TODO: Handle restricted access users
        groups: [], // TODO: Handle groups
        tool_ids: toolIds,
        // uploaded_image: null, // Already uploaded separately
        remove_image: values.remove_image ?? false,
        uploaded_image_id: values.uploaded_image_id,
        icon_name: values.icon_name,
        search_start_date: values.knowledge_cutoff_date || null,
        label_ids: null,
        is_default_persona: false,
        // display_priority: ...,

        user_file_ids:
          values.enable_knowledge && !teamKnowledge ? values.user_file_ids : [],

        system_prompt: values.instructions,
        replace_base_system_prompt: values.replace_base_system_prompt,
        task_prompt: values.reminders || "",
        datetime_aware: false,
      };

      // Call API
      let personaResponse;
      if (!!existingAgent) {
        personaResponse = await updatePersona(existingAgent.id, submissionData);
      } else {
        personaResponse = await createPersona(submissionData);
      }

      // Handle response
      if (!personaResponse || !personaResponse.ok) {
        const error = personaResponse
          ? await personaResponse.text()
          : "No response received";
        setPopup({
          type: "error",
          message: `Failed to ${
            existingAgent ? "update" : "create"
          } agent - ${error}`,
        });
        return;
      }

      // Success
      const agent = await personaResponse.json();
      setPopup({
        type: "success",
        message: `Agent "${agent.name}" ${
          existingAgent ? "updated" : "created"
        } successfully`,
      });

      // Refresh agents list and the specific agent
      await refreshAgents();
      if (refreshAgent) {
        refreshAgent();
      }

      // Immediately start a chat with this agent.
      appRouter({ agentId: agent.id });
    } catch (error) {
      console.error("Submit error:", error);
      setPopup({
        type: "error",
        message: `An error occurred: ${error}`,
      });
    }
  }

  // FilePickerPopover callbacks - defined outside render to avoid inline functions
  function handlePickRecentFile(
    file: ProjectFile,
    currentFileIds: string[],
    setFieldValue: (field: string, value: any) => void
  ) {
    if (!currentFileIds.includes(file.id)) {
      setFieldValue("user_file_ids", [...currentFileIds, file.id]);
    }
  }

  function handleUnpickRecentFile(
    file: ProjectFile,
    currentFileIds: string[],
    setFieldValue: (field: string, value: any) => void
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
    setFieldValue: (field: string, value: any) => void
  ) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    try {
      let selectedIds = [...(currentFileIds || [])];
      const optimistic = await beginUpload(
        Array.from(files),
        null,
        setPopup,
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

  return (
    <>
      {popup}

      <div
        data-testid="AgentsEditorPage/container"
        aria-label="Agents Editor Page"
        className="h-full w-full"
      >
        <Formik
          initialValues={initialValues}
          validationSchema={validationSchema}
          onSubmit={handleSubmit}
          validateOnChange
          validateOnBlur
          validateOnMount
          initialStatus={{ warnings: {} }}
        >
          {({ isSubmitting, isValid, dirty, values, setFieldValue }) => {
            return (
              <>
                <FormWarningsEffect />
                <userFilesModal.Provider>
                  <UserFilesModal
                    title="User Files"
                    description="All files selected for this agent"
                    recentFiles={values.user_file_ids
                      .map((userFileId: string) => {
                        const rf = allRecentFiles.find(
                          (f) => f.id === userFileId
                        );
                        if (rf) return rf;
                        return {
                          id: userFileId,
                          name: `File ${userFileId.slice(0, 8)}`,
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

                <Form className="h-full w-full">
                  <SettingsLayouts.Root>
                    <SettingsLayouts.Header
                      icon={SvgOnyxOctagon}
                      title={existingAgent ? "Edit Agent" : "Create Agent"}
                      rightChildren={
                        <div className="flex gap-2">
                          <Button
                            type="button"
                            secondary
                            onClick={() => router.back()}
                          >
                            Cancel
                          </Button>
                          <Button
                            type="submit"
                            disabled={isSubmitting || !isValid || !dirty}
                          >
                            {existingAgent ? "Save" : "Create"}
                          </Button>
                        </div>
                      }
                      backButton
                      separator
                    />

                    {/* Agent Form Content */}
                    <SettingsLayouts.Body>
                      <GeneralLayouts.Section
                        flexDirection="row"
                        gap={2.5}
                        alignItems="start"
                      >
                        <GeneralLayouts.Section>
                          <InputLayouts.Vertical name="name" label="Name">
                            <InputTypeInField
                              name="name"
                              placeholder="Name your agent"
                            />
                          </InputLayouts.Vertical>

                          <InputLayouts.Vertical
                            name="description"
                            label="Description"
                            optional
                          >
                            <InputTextAreaField
                              name="description"
                              placeholder="What does this agent do?"
                            />
                          </InputLayouts.Vertical>
                        </GeneralLayouts.Section>

                        <GeneralLayouts.Section fit>
                          <InputLayouts.Vertical
                            name="agent_avatar"
                            label="Agent Avatar"
                            center
                          >
                            <AgentIconEditor existingAgent={existingAgent} />
                          </InputLayouts.Vertical>
                        </GeneralLayouts.Section>
                      </GeneralLayouts.Section>

                      <Separator noPadding />

                      <GeneralLayouts.Section>
                        <InputLayouts.Vertical
                          name="instructions"
                          label="Instructions"
                          optional
                          description="Add instructions to tailor the response for this agent."
                        >
                          <InputTextAreaField
                            name="instructions"
                            placeholder="Think step by step and show reasoning for complex problems. Use specific examples. Emphasize action items, and leave blanks for the human to fill in when you have unknown. Use a polite enthusiastic tone."
                          />
                        </InputLayouts.Vertical>

                        <InputLayouts.Vertical
                          name="starter_messages"
                          label="Conversation Starters"
                          description="Example messages that help users understand what this agent can do and how to interact with it effectively."
                          optional
                        >
                          <StarterMessages />
                        </InputLayouts.Vertical>
                      </GeneralLayouts.Section>

                      <Separator noPadding />

                      <GeneralLayouts.Section>
                        <GeneralLayouts.Section gap={1}>
                          <InputLayouts.Label
                            name="knowledge"
                            label="Knowledge"
                            description="Add specific connectors and documents for this agent to use to inform its responses."
                          />

                          <Card>
                            <InputLayouts.Horizontal
                              name="enable_knowledge"
                              label="Enable Knowledge"
                              center
                            >
                              <SwitchField name="enable_knowledge" />
                            </InputLayouts.Horizontal>

                            {values.enable_knowledge && (
                              <InputLayouts.Horizontal
                                name="knowledge_source"
                                label="Knowledge Source"
                                description="Choose the sources of truth this agent refers to."
                                center
                              >
                                <InputSelectField
                                  name="knowledge_source"
                                  className="w-full"
                                >
                                  <InputSelect.Trigger />
                                  <InputSelect.Content>
                                    <InputSelect.Item value="team_knowledge">
                                      Team Knowledge
                                    </InputSelect.Item>
                                    <InputSelect.Item value="user_knowledge">
                                      User Knowledge
                                    </InputSelect.Item>
                                  </InputSelect.Content>
                                </InputSelectField>
                              </InputLayouts.Horizontal>
                            )}

                            {values.enable_knowledge &&
                              values.knowledge_source === "team_knowledge" &&
                              ((documentSets?.length ?? 0) > 0 ? (
                                <GeneralLayouts.Section gap={0.5}>
                                  {documentSets!.map((documentSet) => (
                                    <DocumentSetSelectable
                                      key={documentSet.id}
                                      documentSet={documentSet}
                                      isSelected={values.document_set_ids.includes(
                                        documentSet.id
                                      )}
                                      onSelect={() => {
                                        const index =
                                          values.document_set_ids.indexOf(
                                            documentSet.id
                                          );
                                        if (index !== -1) {
                                          const newIds = [
                                            ...values.document_set_ids,
                                          ];
                                          newIds.splice(index, 1);
                                          setFieldValue(
                                            "document_set_ids",
                                            newIds
                                          );
                                        } else {
                                          setFieldValue("document_set_ids", [
                                            ...values.document_set_ids,
                                            documentSet.id,
                                          ]);
                                        }
                                      }}
                                    />
                                  ))}
                                </GeneralLayouts.Section>
                              ) : (
                                <CreateButton href="/admin/documents/sets/new">
                                  Create a Document Set
                                </CreateButton>
                              ))}

                            {values.enable_knowledge &&
                              values.knowledge_source === "user_knowledge" && (
                                <GeneralLayouts.Section gap={0.5}>
                                  <FilePickerPopover
                                    trigger={(open) => (
                                      <CreateButton transient={open}>
                                        Add User Files
                                      </CreateButton>
                                    )}
                                    selectedFileIds={values.user_file_ids}
                                    onPickRecent={(file) =>
                                      handlePickRecentFile(
                                        file,
                                        values.user_file_ids,
                                        setFieldValue
                                      )
                                    }
                                    onUnpickRecent={(file) =>
                                      handleUnpickRecentFile(
                                        file,
                                        values.user_file_ids,
                                        setFieldValue
                                      )
                                    }
                                    onFileClick={handleFileClick}
                                    handleUploadChange={(e) =>
                                      handleUploadChange(
                                        e,
                                        values.user_file_ids,
                                        setFieldValue
                                      )
                                    }
                                  />

                                  {values.user_file_ids.length > 0 && (
                                    <GeneralLayouts.Section
                                      flexDirection="row"
                                      wrap
                                      gap={0.5}
                                    >
                                      {values.user_file_ids.map((fileId) => {
                                        const file = allRecentFiles.find(
                                          (f) => f.id === fileId
                                        );
                                        if (!file) return null;

                                        return (
                                          <FileCard
                                            key={fileId}
                                            file={file}
                                            removeFile={(id: string) => {
                                              setFieldValue(
                                                "user_file_ids",
                                                values.user_file_ids.filter(
                                                  (fid) => fid !== id
                                                )
                                              );
                                            }}
                                            onFileClick={(f: ProjectFile) => {
                                              setPresentingDocument({
                                                document_id: `project_file__${f.file_id}`,
                                                semantic_identifier: f.name,
                                              });
                                            }}
                                          />
                                        );
                                      })}
                                    </GeneralLayouts.Section>
                                  )}
                                </GeneralLayouts.Section>
                              )}
                          </Card>
                        </GeneralLayouts.Section>
                      </GeneralLayouts.Section>

                      <Separator noPadding />

                      <SimpleCollapsible
                        trigger={
                          <SimpleCollapsible.Header
                            title="Actions"
                            description="Tools and capabilities available for this agent to use."
                          />
                        }
                      >
                        <GeneralLayouts.Section gap={0.5}>
                          <SimpleTooltip
                            tooltip={imageGenerationDisabledTooltip}
                            side="top"
                          >
                            <Card disabled={!isImageGenerationAvailable}>
                              <InputLayouts.Horizontal
                                name="image_generation"
                                label="Image Generation"
                                description="Generate and manipulate images using AI-powered tools."
                              >
                                <SwitchField
                                  name="image_generation"
                                  disabled={!isImageGenerationAvailable}
                                />
                              </InputLayouts.Horizontal>
                            </Card>
                          </SimpleTooltip>

                          <Card>
                            <InputLayouts.Horizontal
                              name="web_search"
                              label="Web Search"
                              description="Search the web for real-time information and up-to-date results."
                            >
                              <SwitchField
                                name="web_search"
                                disabled={!webSearchTool}
                              />
                            </InputLayouts.Horizontal>
                          </Card>

                          <Card>
                            <InputLayouts.Horizontal
                              name="open_url"
                              label="Open URL"
                              description="Fetch and read content from web URLs."
                            >
                              <SwitchField
                                name="open_url"
                                disabled={!openURLTool}
                              />
                            </InputLayouts.Horizontal>
                          </Card>

                          <Card disabled={!codeInterpreterTool}>
                            <InputLayouts.Horizontal
                              name="code_interpreter"
                              label="Code Interpreter"
                              description="Generate and run code."
                            >
                              <SwitchField
                                name="code_interpreter"
                                disabled={!codeInterpreterTool}
                              />
                            </InputLayouts.Horizontal>
                          </Card>

                          {/* Tools */}
                          <>
                            {/* render the separator if there is at least one mcp-server or open-api-tool */}
                            {(mcpServers.length > 0 ||
                              openApiTools.length > 0) && (
                              <Separator noPadding className="py-1" />
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
                                  <OpenApiToolCard key={tool.id} tool={tool} />
                                ))}
                              </GeneralLayouts.Section>
                            )}
                          </>
                        </GeneralLayouts.Section>
                      </SimpleCollapsible>

                      <Separator noPadding />

                      <SimpleCollapsible
                        trigger={
                          <SimpleCollapsible.Header
                            title="Advanced Options"
                            description="Fine-tune agent prompts and knowledge."
                          />
                        }
                      >
                        <GeneralLayouts.Section>
                          <Card>
                            <InputLayouts.Horizontal
                              name="llm_model"
                              label="Default Model"
                              description="Select the LLM model to use for this agent. If not set, the user's default model will be used."
                              center
                            >
                              <LLMSelector
                                llmProviders={llmProviders ?? []}
                                currentLlm={getCurrentLlm(values, llmProviders)}
                                onSelect={(selected) =>
                                  onLlmSelect(selected, setFieldValue)
                                }
                              />
                            </InputLayouts.Horizontal>
                            <InputLayouts.Horizontal
                              name="knowledge_cutoff_date"
                              label="Knowledge Cutoff Date"
                              description="Set the knowledge cutoff date for this agent. The agent will only use information up to this date."
                              center
                            >
                              <InputDatePickerField name="knowledge_cutoff_date" />
                            </InputLayouts.Horizontal>
                            <InputLayouts.Horizontal
                              name="replace_base_system_prompt"
                              label="Overwrite System Prompt"
                              description='Completely replace the base system prompt. This might affect response quality since it will also overwrite useful system instructions (e.g. "You (the LLM) can provide markdown and it will be rendered").'
                            >
                              <SwitchField name="replace_base_system_prompt" />
                            </InputLayouts.Horizontal>
                          </Card>

                          <GeneralLayouts.Section gap={0.25}>
                            <InputLayouts.Vertical
                              name="reminders"
                              label="Reminders"
                            >
                              <InputTextAreaField
                                name="reminders"
                                placeholder="Remember, I want you to always format your response as a numbered list."
                              />
                            </InputLayouts.Vertical>
                            <Text text03 secondaryBody>
                              Append a brief reminder to the prompt messages.
                              Use this to remind the agent if you find that it
                              tends to forget certain instructions as the chat
                              progresses. This should be brief and not interfere
                              with the user messages.
                            </Text>
                          </GeneralLayouts.Section>
                        </GeneralLayouts.Section>
                      </SimpleCollapsible>
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
