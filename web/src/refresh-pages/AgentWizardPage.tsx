"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Button as OpalButton } from "@opal/components";
import { Hoverable } from "@opal/core";
import { buildImgUrl } from "@/app/app/components/files/images/utils";
import { Formik, Form, useFormikContext } from "formik";
import * as Yup from "yup";
import { parseLlmDescriptor, structureValue } from "@/lib/llmConfig/utils";
import { useLLMProviders } from "@/hooks/useLLMProviders";
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
} from "@/app/app/components/tools/constants";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { useDocumentSets } from "@/app/admin/documents/sets/hooks";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { toast } from "@/hooks/useToast";
import UserFilesModal from "@/components/modals/UserFilesModal";
import {
  ProjectFile,
  UserFileStatus,
} from "@/app/app/projects/projectsService";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import Button from "@/refresh-components/buttons/Button";
import { SvgImage } from "@opal/icons";
import CustomAgentAvatar, {
  agentAvatarIconMap,
} from "@/refresh-components/avatars/CustomAgentAvatar";
import InputAvatar from "@/refresh-components/inputs/InputAvatar";
import SquareButton from "@/refresh-components/buttons/SquareButton";
import { useAgents } from "@/hooks/useAgents";
import {
  createPersona,
  PersonaUpsertParameters,
} from "@/app/admin/agents/lib";
import useMcpServersForAgentEditor from "@/hooks/useMcpServersForAgentEditor";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import { useAvailableTools } from "@/hooks/useAvailableTools";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { MCPTool } from "@/lib/tools/interfaces";
import { useAppRouter } from "@/hooks/appNavigation";
import { isDateInFuture } from "@/lib/dateUtils";
import ShareAgentModal from "@/sections/modals/ShareAgentModal";
import AgentFormBody from "@/components/agents/AgentFormBody";
import AgentBuilderChat from "@/components/agents/AgentBuilderChat";
import { ValidSources } from "@/lib/types";
import { useVectorDbEnabled } from "@/providers/SettingsProvider";
import { useUser } from "@/providers/UserProvider";

// ---------------------------------------------------------------------------
// Small sub-components (duplicated from AgentEditorPage)
// ---------------------------------------------------------------------------

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

function AgentIconEditor() {
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

    setUploadedImagePreview(null);
    setFieldValue("icon_name", null);
    setFieldValue("remove_image", false);

    const reader = new FileReader();
    reader.onloadend = () => {
      setUploadedImagePreview(reader.result as string);
    };
    reader.readAsDataURL(file);

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
      : undefined;

  function handleIconClick(iconName: string | null) {
    setFieldValue("icon_name", iconName);
    setFieldValue("uploaded_image_id", null);
    setFieldValue("remove_image", true);
    setUploadedImagePreview(null);
    setPopoverOpen(false);

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
          <Hoverable.Root group="inputAvatar" widthVariant="fit">
            <InputAvatar className="relative flex flex-col items-center justify-center h-[7.5rem] w-[7.5rem]">
              <CustomAgentAvatar
                size={imageSrc ? 7.5 * 16 : 40}
                src={imageSrc}
                iconName={values.icon_name ?? undefined}
                name={values.name}
              />
              <div className="absolute bottom-0 left-1/2 -translate-x-1/2 mb-2">
                <Hoverable.Item group="inputAvatar" variant="opacity-on-hover">
                  <Button className="h-[1.75rem]" secondary>
                    Edit
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
                Upload Image
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

// ---------------------------------------------------------------------------
// AgentWizardPage
// ---------------------------------------------------------------------------

export default function AgentWizardPage() {
  const router = useRouter();
  const appRouter = useAppRouter();
  const { refresh: refreshAgents } = useAgents();
  const shareAgentModal = useCreateModal();
  const { isAdmin, isCurator } = useUser();
  const canUpdateFeaturedStatus = isAdmin || isCurator;
  const vectorDbEnabled = useVectorDbEnabled();

  // Highlighted fields state — populated by chat, cleared after 2 seconds
  const [highlightedFields, setHighlightedFields] = useState<Set<string>>(
    new Set()
  );
  const highlightTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleFieldsUpdated = useCallback((fieldNames: string[]) => {
    setHighlightedFields(new Set(fieldNames));
    if (highlightTimerRef.current) {
      clearTimeout(highlightTimerRef.current);
    }
    highlightTimerRef.current = setTimeout(() => {
      setHighlightedFields(new Set());
    }, 2000);
  }, []);

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (highlightTimerRef.current) {
        clearTimeout(highlightTimerRef.current);
      }
    };
  }, []);

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

  const { mcpData, isLoading: isMcpLoading } = useMcpServersForAgentEditor();
  const { openApiTools: openApiToolsRaw, isLoading: isOpenApiLoading } =
    useOpenApiTools();
  const { llmProviders } = useLLMProviders();
  const mcpServers = mcpData?.mcp_servers ?? [];
  const openApiTools = openApiToolsRaw ?? [];

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

  // -- Initial values (create path only, no existingAgent) --
  const initialValues = {
    icon_name: null as string | null,
    uploaded_image_id: null as string | null,
    remove_image: false,
    name: "",
    description: "",
    instructions: "",
    starter_messages: Array.from(
      { length: STARTER_MESSAGES_EXAMPLES.length },
      () => ""
    ),
    enable_knowledge: false,
    document_set_ids: [] as number[],
    document_ids: [] as string[],
    hierarchy_node_ids: [] as number[],
    user_file_ids: [] as string[],
    selected_sources: [] as ValidSources[],
    llm_model_provider_override: null as string | null,
    llm_model_version_override: null as string | null,
    knowledge_cutoff_date: null as Date | null,
    replace_base_system_prompt: false,
    reminders: "",
    image_generation: false,
    web_search: false,
    open_url: false,
    code_interpreter: false,
    // MCP servers
    ...Object.fromEntries(
      mcpServersWithTools.map(({ server, tools }) => {
        const toolFields: Record<string, boolean> = {};
        tools.forEach((tool) => {
          toolFields[`tool_${tool.id}`] = false;
        });
        return [
          `mcp_server_${server.id}`,
          { enabled: false, ...toolFields },
        ];
      })
    ),
    // OpenAPI tools
    ...Object.fromEntries(
      openApiTools.map((openApiTool) => [
        `openapi_tool_${openApiTool.id}`,
        false,
      ])
    ),
    // Sharing
    shared_user_ids: [] as string[],
    shared_group_ids: [] as number[],
    is_public: false,
    label_ids: [] as number[],
    is_featured: false,
  };

  const validationSchema = Yup.object().shape({
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
    instructions: Yup.string().optional(),
    starter_messages: Yup.array().of(
      Yup.string().max(
        MAX_CHARACTERS_STARTER_MESSAGE,
        `Conversation starter must be ${MAX_CHARACTERS_STARTER_MESSAGE} characters or less`
      )
    ),
    enable_knowledge: Yup.boolean(),
    document_set_ids: Yup.array().of(Yup.number()),
    document_ids: Yup.array().of(Yup.string()),
    hierarchy_node_ids: Yup.array().of(Yup.number()),
    user_file_ids: Yup.array().of(Yup.string()),
    selected_sources: Yup.array().of(Yup.string()),
    llm_model_provider_override: Yup.string().nullable().optional(),
    llm_model_version_override: Yup.string().nullable().optional(),
    knowledge_cutoff_date: Yup.date()
      .nullable()
      .optional()
      .test(
        "knowledge-cutoff-date-not-in-future",
        "Knowledge cutoff date must be today or earlier.",
        (value) => !value || !isDateInFuture(value)
      ),
    replace_base_system_prompt: Yup.boolean(),
    reminders: Yup.string().optional(),
    ...Object.fromEntries(
      mcpServers.map((server) => [
        `mcp_server_${server.id}`,
        Yup.object(),
      ])
    ),
    ...Object.fromEntries(
      openApiTools.map((openApiTool) => [
        `openapi_tool_${openApiTool.id}`,
        Yup.boolean(),
      ])
    ),
  });

  async function handleSubmit(values: typeof initialValues) {
    try {
      const starterMessages = values.starter_messages
        .filter((message: string) => message.trim() !== "")
        .map((message: string) => ({
          message: message,
          name: message,
        }));

      const finalStarterMessages =
        starterMessages.length > 0 ? starterMessages : null;

      const toolIds: number[] = [];
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

      // Collect enabled MCP tool IDs
      mcpServers.forEach((server) => {
        const serverFieldName = `mcp_server_${server.id}`;
        const serverData = (values as any)[serverFieldName];

        if (
          serverData &&
          typeof serverData === "object" &&
          serverData.enabled
        ) {
          Object.keys(serverData).forEach((key) => {
            if (key.startsWith("tool_") && serverData[key] === true) {
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

      const submissionData: PersonaUpsertParameters = {
        name: values.name,
        description: values.description,
        document_set_ids: values.enable_knowledge
          ? values.document_set_ids
          : [],
        is_public: values.is_public,
        llm_model_provider_override: values.llm_model_provider_override || null,
        llm_model_version_override: values.llm_model_version_override || null,
        starter_messages: finalStarterMessages,
        users: values.shared_user_ids,
        groups: values.shared_group_ids,
        tool_ids: toolIds,
        remove_image: values.remove_image ?? false,
        uploaded_image_id: values.uploaded_image_id,
        icon_name: values.icon_name,
        search_start_date: values.knowledge_cutoff_date || null,
        label_ids: values.label_ids,
        is_featured: values.is_featured,
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

      const personaResponse = await createPersona(submissionData);

      if (!personaResponse || !personaResponse.ok) {
        const error = personaResponse
          ? await personaResponse.text()
          : "No response received";
        toast.error(`Failed to create agent - ${error}`);
        return;
      }

      const agent = await personaResponse.json();
      toast.success(`Agent "${agent.name}" created successfully`);

      await refreshAgents();
      appRouter({ agentId: agent.id });
    } catch (error) {
      console.error("Submit error:", error);
      toast.error(`An error occurred: ${error}`);
    }
  }

  // FilePickerPopover callbacks for Knowledge section
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

  // Wait for async tool data before rendering
  if (isToolsLoading || isMcpLoading || isOpenApiLoading) {
    return null;
  }

  return (
    <div className="h-full w-full overflow-hidden">
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
                      values.user_file_ids.filter(
                        (id: string) => id !== file.id
                      )
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
                    // New agent: just set form values, no API call needed
                    setFieldValue("shared_user_ids", userIds);
                    setFieldValue("shared_group_ids", groupIds);
                    setFieldValue("is_public", isPublic);
                    setFieldValue("is_featured", isFeatured);
                    setFieldValue("label_ids", labelIds);
                    shareAgentModal.toggle(false);
                  }}
                />
              </shareAgentModal.Provider>

              <Form className="flex flex-row h-full w-full overflow-hidden">
                {/* Left panel: Chat — fixed width, scrolls internally */}
                <div className="flex flex-col border-r border-border-01 flex-shrink-0 w-[380px] min-w-[320px] overflow-hidden">
                  <AgentBuilderChat
                    onFieldsUpdated={handleFieldsUpdated}
                  />
                </div>

                {/* Right panel: Form — takes remaining space */}
                <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
                  {/* Sticky header */}
                  <div className="flex items-center justify-between px-5 py-3 border-b border-border-01 flex-shrink-0">
                    <div className="text-[13px] font-semibold text-text-04">
                      Configure Agent
                    </div>
                    <div className="flex gap-2">
                      <OpalButton
                        prominence="secondary"
                        type="button"
                        onClick={() => router.back()}
                      >
                        Cancel
                      </OpalButton>
                      <SimpleTooltip
                        tooltip={
                          isSubmitting
                            ? "Creating agent..."
                            : !isValid
                              ? "Please fix the errors in the form before creating."
                              : hasUploadingFiles
                                ? "Please wait for files to finish uploading."
                                : undefined
                        }
                        side="bottom"
                      >
                        <OpalButton
                          disabled={
                            isSubmitting || !isValid || hasUploadingFiles
                          }
                          type="submit"
                        >
                          Create Agent
                        </OpalButton>
                      </SimpleTooltip>
                    </div>
                  </div>

                  {/* Scrollable form body — no max-width constraint */}
                  <div className="flex-1 overflow-y-auto">
                    <div className="px-5 py-5 flex flex-col gap-5">
                      <AgentFormBody
                        avatarEditor={<AgentIconEditor />}
                        allRecentFiles={allRecentFiles}
                        documentSets={documentSets ?? []}
                        onFileClick={handleFileClick}
                        onUploadChange={(e) =>
                          handleUploadChange(
                            e,
                            values.user_file_ids,
                            setFieldValue
                          )
                        }
                        hasProcessingFiles={hasProcessingFiles}
                        vectorDbEnabled={vectorDbEnabled}
                        mcpServersWithTools={mcpServersWithTools}
                        mcpServers={mcpServers}
                        openApiTools={openApiTools}
                        isImageGenerationAvailable={isImageGenerationAvailable}
                        imageGenerationDisabledTooltip={
                          imageGenerationDisabledTooltip
                        }
                        webSearchTool={webSearchTool}
                        openURLTool={openURLTool}
                        codeInterpreterTool={codeInterpreterTool}
                        llmProviders={llmProviders ?? []}
                        getCurrentLlm={getCurrentLlm}
                        onLlmSelect={onLlmSelect}
                        canUpdateFeaturedStatus={canUpdateFeaturedStatus}
                        onShareClick={() => shareAgentModal.toggle(true)}
                        onDeleteClick={() => {
                          /* No delete for create mode */
                        }}
                        highlightedFields={highlightedFields}
                      />
                    </div>
                  </div>
                </div>
              </Form>
            </>
          );
        }}
      </Formik>
    </div>
  );
}
