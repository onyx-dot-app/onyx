"use client";

import React from "react";
import { Option } from "@/components/Dropdown";
import { generateRandomIconShape } from "@/lib/assistantIconUtils";
import {
  CCPairBasicInfo,
  DocumentSetSummary,
  User,
  UserGroup,
  UserRole,
} from "@/lib/types";
import { Separator } from "@/components/ui/separator";
import Button from "@/refresh-components/buttons/Button";
import {
  ArrayHelpers,
  FieldArray,
  Form,
  Formik,
  FormikProps,
  FastField,
} from "formik";

import { BooleanFormField, Label, TextFormField } from "@/components/Field";
import { MemoizedToolList } from "@/components/admin/assistants/MemoizedToolCheckboxes";
import {
  NameField,
  DescriptionField,
  SystemPromptField,
  TaskPromptField,
  MCPServerSection,
} from "@/components/admin/assistants/FormSections";

import { usePopup } from "@/components/admin/connectors/Popup";
import { getDisplayNameForModel, useLabels } from "@/lib/hooks";
import { DocumentSetSelectable } from "@/components/documentSet/DocumentSetSelectable";
import { addAssistantToList } from "@/lib/assistants/updateAssistantPreferences";
import {
  parseLlmDescriptor,
  modelSupportsImageInput,
  structureValue,
} from "@/lib/llm/utils";
import { ToolSnapshot, MCPServer } from "@/lib/tools/interfaces";
import { checkUserIsNoAuthUser } from "@/lib/user";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import * as Yup from "yup";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import {
  FullPersona,
  PersonaLabel,
  StarterMessage,
} from "@/app/admin/assistants/interfaces";
import {
  PersonaUpsertParameters,
  createPersona,
  updatePersona,
  deletePersona,
} from "@/app/admin/assistants/lib";
import {
  CameraIcon,
  GroupsIconSkeleton,
  SwapIcon,
  TrashIcon,
} from "@/components/icons/icons";
import { buildImgUrl } from "@/app/chat/components/files/images/utils";
import { debounce, values } from "lodash";
import { LLMProviderView } from "@/app/admin/configuration/llm/interfaces";
import StarterMessagesList from "@/app/admin/assistants/StarterMessageList";

import { SwitchField } from "@/components/ui/switch";
import { generateIdenticon } from "@/components/assistants/AssistantIcon";
import { BackButton } from "@/components/BackButton";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import { MinimalUserSnapshot } from "@/lib/types";
import { useUserGroups } from "@/lib/hooks";
import {
  SearchMultiSelectDropdown,
  Option as DropdownOption,
} from "@/components/Dropdown";
import { SourceChip } from "@/app/chat/components/input/ChatInputBar";
import { FileCard } from "@/app/chat/components/projects/ProjectContextPanel";
import CoreModal from "@/refresh-components/modals/CoreModal";
import UserFilesModalContent from "@/components/modals/UserFilesModalContent";
import { TagIcon, UserIcon, FileIcon, InfoIcon, BookIcon } from "lucide-react";
import { LLMSelector } from "@/components/llm/LLMSelector";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";

import {
  IMAGE_GENERATION_TOOL_ID,
  SEARCH_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
} from "@/app/chat/components/tools/constants";
import TextView from "@/components/chat/TextView";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { MAX_CHARACTERS_PERSONA_DESCRIPTION } from "@/lib/constants";
import { FormErrorFocus } from "@/components/FormErrorHelpers";
import { ProjectFile } from "@/app/chat/projects/projectsService";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import FilePicker from "@/app/chat/components/files/FilePicker";
import SvgTrash from "@/icons/trash";
import SvgEditBig from "@/icons/edit-big";
import LineItem from "@/refresh-components/buttons/LineItem";
import SvgPlusCircle from "@/icons/plus-circle";
import SvgFiles from "@/icons/files";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import Text from "@/refresh-components/texts/Text";
import CreateButton from "@/refresh-components/buttons/CreateButton";

function findSearchTool(tools: ToolSnapshot[]) {
  return tools.find((tool) => tool.in_code_tool_id === SEARCH_TOOL_ID);
}

function findImageGenerationTool(tools: ToolSnapshot[]) {
  return tools.find(
    (tool) => tool.in_code_tool_id === IMAGE_GENERATION_TOOL_ID
  );
}

function findWebSearchTool(tools: ToolSnapshot[]) {
  return tools.find((tool) => tool.in_code_tool_id === WEB_SEARCH_TOOL_ID);
}

function SubLabel({ children }: { children: string | JSX.Element }) {
  return (
    <div
      className="text-sm text-description font-description mb-2"
      style={{ color: "rgb(113, 114, 121)" }}
    >
      {children}
    </div>
  );
}

export function AssistantEditor({
  existingPersona,
  ccPairs,
  documentSets,
  user,
  defaultPublic,
  llmProviders,
  tools,
  shouldAddAssistantToUserPreferences,
}: {
  existingPersona?: FullPersona | null;
  ccPairs: CCPairBasicInfo[];
  documentSets: DocumentSetSummary[];
  user: User | null;
  defaultPublic: boolean;
  llmProviders: LLMProviderView[];
  tools: ToolSnapshot[];
  shouldAddAssistantToUserPreferences?: boolean;
}) {
  // NOTE: assistants = agents
  // TODO: rename everything to agents
  const { refreshAgents } = useAgentsContext();

  const router = useRouter();
  const searchParams = useSearchParams();
  const isAdminPage = searchParams?.get("admin") === "true";

  const { popup, setPopup } = usePopup();
  const { labels, refreshLabels, createLabel, deleteLabel } = useLabels();
  const settings = useContext(SettingsContext);

  const colorOptions = [
    "#FF6FBF",
    "#6FB1FF",
    "#B76FFF",
    "#FFB56F",
    "#6FFF8D",
    "#FF6F6F",
    "#6FFFFF",
  ];

  const [presentingDocument, setPresentingDocument] =
    useState<MinimalOnyxDocument | null>(null);
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);
  const [showAllUserFiles, setShowAllUserFiles] = useState(false);

  // both `defautIconColor` and `defaultIconShape` are state so that they
  // persist across formik reformatting
  const [defautIconColor, _setDeafultIconColor] = useState(
    colorOptions[Math.floor(Math.random() * colorOptions.length)]
  );
  const [defaultIconShape] = useState<any>(
    () => generateRandomIconShape().encodedGrid
  );
  const [isRefreshing, setIsRefreshing] = useState(false);

  const [removePersonaImage, setRemovePersonaImage] = useState(false);
  const [uploadedImagePreview, setUploadedImagePreview] = useState<
    string | null
  >(null);

  const autoStarterMessageEnabled = useMemo(
    () => llmProviders.length > 0,
    [llmProviders.length]
  );
  const isUpdate = existingPersona !== undefined && existingPersona !== null;
  const defaultProvider = llmProviders.find(
    (llmProvider) => llmProvider.is_default_provider
  );
  const defaultModelName = defaultProvider?.default_model_name;
  const providerDisplayNameToProviderName = new Map<string, string>();
  llmProviders.forEach((llmProvider) => {
    providerDisplayNameToProviderName.set(
      llmProvider.name,
      llmProvider.provider
    );
  });

  const modelOptionsByProvider = new Map<string, Option<string>[]>();
  llmProviders.forEach((llmProvider) => {
    const providerOptions = llmProvider.model_configurations.map(
      (modelConfiguration) => ({
        name: getDisplayNameForModel(modelConfiguration.name),
        value: modelConfiguration.name,
      })
    );
    modelOptionsByProvider.set(llmProvider.name, providerOptions);
  });

  const personaCurrentToolIds =
    existingPersona?.tools.map((tool) => tool.id) || [];

  const searchTool = findSearchTool(tools);
  const imageGenerationTool = findImageGenerationTool(tools);
  const webSearchTool = findWebSearchTool(tools);

  // Separate MCP tools from regular custom tools - memoize to prevent re-renders
  const { mcpTools, customTools, mcpToolsByServer } = useMemo(() => {
    const allCustom = tools.filter(
      (tool) =>
        tool.in_code_tool_id !== searchTool?.in_code_tool_id &&
        tool.in_code_tool_id !== imageGenerationTool?.in_code_tool_id &&
        tool.in_code_tool_id !== webSearchTool?.in_code_tool_id
    );

    const mcp = allCustom.filter((tool) => tool.mcp_server_id);
    const custom = allCustom.filter((tool) => !tool.mcp_server_id);

    // Group MCP tools by server
    const groups: { [serverId: number]: ToolSnapshot[] } = {};
    mcp.forEach((tool) => {
      if (tool.mcp_server_id) {
        if (!groups[tool.mcp_server_id]) {
          groups[tool.mcp_server_id] = [];
        }
        groups[tool.mcp_server_id]!.push(tool);
      }
    });

    return {
      mcpTools: mcp,
      customTools: custom,
      mcpToolsByServer: groups,
    };
  }, [
    tools,
    searchTool?.in_code_tool_id,
    imageGenerationTool?.in_code_tool_id,
    webSearchTool?.in_code_tool_id,
  ]);

  // Helper functions for MCP server checkbox state - memoize to prevent re-renders
  const getMCPServerCheckboxState = useCallback(
    (serverId: number, enabledToolsMap: { [key: number]: boolean }) => {
      const serverTools = mcpToolsByServer[serverId] || [];
      const enabledCount = serverTools.filter(
        (tool) => enabledToolsMap[tool.id]
      ).length;

      if (enabledCount === 0) return false; // unchecked
      if (enabledCount === serverTools.length) return true; // checked
      return "indeterminate"; // partially checked
    },
    [mcpToolsByServer]
  );

  const toggleMCPServerTools = useCallback(
    (
      serverId: number,
      enabledToolsMap: { [key: number]: boolean },
      setFieldValue: any
    ) => {
      const serverTools = mcpToolsByServer[serverId] || [];
      const currentState = getMCPServerCheckboxState(serverId, enabledToolsMap);
      const shouldEnable = currentState !== true; // enable if not fully checked

      const updatedMap = { ...enabledToolsMap };
      serverTools.forEach((tool) => {
        updatedMap[tool.id] = shouldEnable;
      });

      setFieldValue("enabled_tools_map", updatedMap);
    },
    [mcpToolsByServer, getMCPServerCheckboxState]
  );

  const toggleServerCollapse = useCallback((serverId: number) => {
    setCollapsedServers((prev) => {
      const newCollapsed = new Set(prev);
      if (newCollapsed.has(serverId)) {
        newCollapsed.delete(serverId);
      } else {
        newCollapsed.add(serverId);
      }
      return newCollapsed;
    });
  }, []);

  const availableTools = [
    ...customTools,
    ...mcpTools, // Include MCP tools for form logic
    ...(searchTool ? [searchTool] : []),
    ...(imageGenerationTool ? [imageGenerationTool] : []),
    ...(webSearchTool ? [webSearchTool] : []),
  ];
  const enabledToolsMap: { [key: number]: boolean } = {};
  availableTools.forEach((tool) => {
    enabledToolsMap[tool.id] = personaCurrentToolIds.includes(tool.id);
  });

  const { allRecentFiles, beginUpload } = useProjectsContext();

  const [showVisibilityWarning, setShowVisibilityWarning] = useState(false);

  const connectorsExist = ccPairs.length > 0;

  const canShowKnowledgeSource =
    connectorsExist &&
    searchTool &&
    !(user?.role === UserRole.BASIC && documentSets.length === 0);

  const userKnowledgeEnabled =
    settings?.settings?.user_knowledge_enabled ?? true;

  const initialValues = {
    name: existingPersona?.name ?? "",
    description: existingPersona?.description ?? "",
    datetime_aware: existingPersona?.datetime_aware ?? false,
    system_prompt: existingPersona?.system_prompt ?? "",
    task_prompt: existingPersona?.task_prompt ?? "",
    is_public: existingPersona?.is_public ?? defaultPublic,
    document_set_ids:
      existingPersona?.document_sets?.map((documentSet) => documentSet.id) ??
      ([] as number[]),
    num_chunks: existingPersona?.num_chunks ?? null,
    search_start_date: existingPersona?.search_start_date
      ? existingPersona?.search_start_date.toString().split("T")[0]
      : null,
    llm_relevance_filter: existingPersona?.llm_relevance_filter ?? false,
    llm_model_provider_override:
      existingPersona?.llm_model_provider_override ?? null,
    llm_model_version_override:
      existingPersona?.llm_model_version_override ?? null,
    starter_messages: existingPersona?.starter_messages?.length
      ? existingPersona.starter_messages
      : [{ message: "", name: "" }],
    enabled_tools_map: enabledToolsMap,
    icon_color: existingPersona?.icon_color ?? defautIconColor,
    icon_shape: existingPersona?.icon_shape ?? defaultIconShape,
    uploaded_image: null,
    labels: existingPersona?.labels ?? null,

    // EE Only
    label_ids: existingPersona?.labels?.map((label) => label.id) ?? [],
    selectedUsers:
      existingPersona?.users?.filter(
        (u) => u.id !== existingPersona.owner?.id
      ) ?? [],
    selectedGroups: existingPersona?.groups ?? [],
    user_file_ids: existingPersona?.user_file_ids ?? [],
    knowledge_source: !canShowKnowledgeSource
      ? "user_files"
      : !userKnowledgeEnabled
        ? "team_knowledge"
        : (existingPersona?.user_file_ids?.length ?? 0) > 0
          ? "user_files"
          : "team_knowledge",
    is_default_persona: existingPersona?.is_default_persona ?? false,
  };

  interface AssistantPrompt {
    message: string;
    name: string;
  }

  const debouncedRefreshPrompts = debounce(
    async (formValues: any, setFieldValue: any) => {
      if (!autoStarterMessageEnabled) {
        return;
      }
      setIsRefreshing(true);
      try {
        const response = await fetch("/api/persona/assistant-prompt-refresh", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            name: formValues.name || "",
            description: formValues.description || "",
            document_set_ids: formValues.document_set_ids || [],
            instructions:
              formValues.system_prompt || formValues.task_prompt || "",
            generation_count:
              4 -
              formValues.starter_messages.filter(
                (message: StarterMessage) => message.message.trim() !== ""
              ).length,
          }),
        });

        const data: AssistantPrompt[] = await response.json();
        if (response.ok) {
          const filteredStarterMessages = formValues.starter_messages.filter(
            (message: StarterMessage) => message.message.trim() !== ""
          );
          setFieldValue("starter_messages", [
            ...filteredStarterMessages,
            ...data,
          ]);
        }
      } catch (error) {
        console.error("Failed to refresh prompts:", error);
      } finally {
        setIsRefreshing(false);
      }
    },
    1000
  );

  const [labelToDelete, setLabelToDelete] = useState<PersonaLabel | null>(null);
  const [isRequestSuccessful, setIsRequestSuccessful] = useState(false);
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const [collapsedServers, setCollapsedServers] = useState<Set<number>>(
    () => new Set(Object.keys(mcpToolsByServer).map((id) => parseInt(id, 10)))
  );
  const seenServerIdsRef = useRef<Set<number>>(
    new Set(Object.keys(mcpToolsByServer).map((id) => parseInt(id, 10)))
  );

  useEffect(() => {
    const serverIds = Object.keys(mcpToolsByServer).map((id) =>
      parseInt(id, 10)
    );

    const unseenIds = serverIds.filter(
      (id) => !seenServerIdsRef.current.has(id)
    );

    if (unseenIds.length === 0) {
      return;
    }

    const updatedSeen = new Set(seenServerIdsRef.current);
    unseenIds.forEach((id) => updatedSeen.add(id));
    seenServerIdsRef.current = updatedSeen;

    setCollapsedServers((prev) => {
      const next = new Set(prev);
      unseenIds.forEach((id) => next.add(id));
      return next;
    });
  }, [mcpToolsByServer]);

  const { data: userGroups } = useUserGroups();

  const { data: users } = useSWR<MinimalUserSnapshot[]>(
    "/api/users",
    errorHandlingFetcher
  );

  const [deleteModalOpen, setDeleteModalOpen] = useState(false);

  useEffect(() => {
    return () => {
      if (uploadedImagePreview) {
        URL.revokeObjectURL(uploadedImagePreview);
      }
    };
  }, [uploadedImagePreview]);

  // Fetch MCP servers for URL display
  useEffect(() => {
    const fetchMcpServers = async () => {
      const response = await fetch("/api/admin/mcp/servers");
      if (response.ok) {
        const data = await response.json();
        setMcpServers(data.mcp_servers || []);
      }
    };

    fetchMcpServers();
  }, []);

  if (!labels) {
    return <></>;
  }

  const openDeleteModal = () => {
    setDeleteModalOpen(true);
  };

  const closeDeleteModal = () => {
    setDeleteModalOpen(false);
  };

  const handleDeletePersona = async () => {
    if (existingPersona) {
      const response = await deletePersona(existingPersona.id);
      if (response.ok) {
        await refreshAgents();
        router.push(
          isAdminPage ? `/admin/assistants?u=${Date.now()}` : `/chat`
        );
      } else {
        setPopup({
          type: "error",
          message: `Failed to delete persona - ${await response.text()}`,
        });
      }
    }
  };

  // Removed invalid helper; replacement happens inline in the upload handler using the beginUpload onSuccess callback

  return (
    <div className="mx-auto max-w-4xl">
      <style>
        {`
          .assistant-editor input::placeholder,
          .assistant-editor textarea::placeholder {
            opacity: 0.5;
          }
        `}
      </style>
      <div className="absolute top-4 left-4">
        <BackButton />
      </div>
      {presentingDocument && (
        <TextView
          presentingDocument={presentingDocument}
          onClose={() => setPresentingDocument(null)}
        />
      )}
      {labelToDelete && (
        <ConfirmEntityModal
          entityType="label"
          entityName={labelToDelete.name}
          onClose={() => setLabelToDelete(null)}
          onSubmit={async () => {
            const response = await deleteLabel(labelToDelete.id);
            if (response?.ok) {
              setPopup({
                message: `Label deleted successfully`,
                type: "success",
              });
              await refreshLabels();
            } else {
              setPopup({
                message: `Failed to delete label - ${await response.text()}`,
                type: "error",
              });
            }
            setLabelToDelete(null);
          }}
        />
      )}
      {deleteModalOpen && existingPersona && (
        <ConfirmEntityModal
          entityType="Persona"
          entityName={existingPersona.name}
          onClose={closeDeleteModal}
          onSubmit={handleDeletePersona}
        />
      )}
      {popup}
      <Formik
        // enableReinitialize={true}
        initialValues={initialValues}
        validateOnChange={false}
        validateOnBlur={false}
        validationSchema={Yup.object()
          .shape({
            name: Yup.string().required("Must provide a name for the Agent"),
            description: Yup.string().required(
              "Must provide a description for the Agent"
            ),
            system_prompt: Yup.string().max(
              MAX_CHARACTERS_PERSONA_DESCRIPTION,
              "Instructions must be less than 5000000 characters"
            ),
            task_prompt: Yup.string().max(
              MAX_CHARACTERS_PERSONA_DESCRIPTION,
              "Reminders must be less than 5000000 characters"
            ),
            is_public: Yup.boolean().required(),
            document_set_ids: Yup.array().of(Yup.number()),
            num_chunks: Yup.number().nullable(),
            llm_relevance_filter: Yup.boolean().required(),
            llm_model_version_override: Yup.string().nullable(),
            llm_model_provider_override: Yup.string().nullable(),
            starter_messages: Yup.array().of(
              Yup.object().shape({
                message: Yup.string(),
              })
            ),
            search_start_date: Yup.date().nullable(),
            icon_color: Yup.string(),
            icon_shape: Yup.number(),
            uploaded_image: Yup.mixed().nullable(),
            // EE Only
            label_ids: Yup.array().of(Yup.number()),
            selectedUsers: Yup.array().of(Yup.object()),
            selectedGroups: Yup.array().of(Yup.number()),
            knowledge_source: Yup.string().required(),
            is_default_persona: Yup.boolean().required(),
          })
          .test(
            "system-prompt-or-task-prompt",
            "Must provide either Instructions or Reminders (Advanced)",
            function (values) {
              const systemPromptSpecified =
                values.system_prompt && values.system_prompt.trim().length > 0;
              const taskPromptSpecified =
                values.task_prompt && values.task_prompt.trim().length > 0;

              if (systemPromptSpecified || taskPromptSpecified) {
                return true;
              }

              return this.createError({
                path: "system_prompt",
                message:
                  "Must provide either Instructions or Reminders (Advanced)",
              });
            }
          )
          .test(
            "default-persona-public",
            "Default persona must be public",
            function (values) {
              if (values.is_default_persona && !values.is_public) {
                return this.createError({
                  path: "is_public",
                  message: "Default persona must be public",
                });
              }
              return true;
            }
          )}
        onSubmit={async (values, formikHelpers) => {
          if (
            values.llm_model_provider_override &&
            !values.llm_model_version_override
          ) {
            setPopup({
              type: "error",
              message:
                "Must select a model if a non-default LLM provider is chosen.",
            });
            return;
          }

          formikHelpers.setSubmitting(true);
          let enabledTools = Object.keys(values.enabled_tools_map)
            .map((toolId) => Number(toolId))
            .filter((toolId) => values.enabled_tools_map[toolId]);

          if (webSearchTool && enabledTools.includes(webSearchTool.id)) {
            // Internet searches should generally be datetime-aware
            formikHelpers.setFieldValue("datetime_aware", true);
          }

          const searchToolEnabled = searchTool
            ? enabledTools.includes(searchTool.id)
            : false;

          // if disable_retrieval is set, set num_chunks to 0
          // to tell the backend to not fetch any documents
          const numChunks = searchToolEnabled ? values.num_chunks || 25 : 0;
          const starterMessages = values.starter_messages
            .filter((message: StarterMessage) => message.message.trim() !== "")
            .map((message: StarterMessage) => ({
              message: message.message,
              name: message.message,
            }));

          // don't set groups if marked as public
          const groups = values.is_public ? [] : values.selectedGroups;
          const teamKnowledge = values.knowledge_source === "team_knowledge";

          const submissionData: PersonaUpsertParameters = {
            ...values,
            icon_color: values.icon_color ?? null,
            starter_messages: starterMessages,
            groups: groups,
            users: values.is_public
              ? undefined
              : [
                  ...(user && !checkUserIsNoAuthUser(user.id) ? [user.id] : []),
                  ...values.selectedUsers.map((u: MinimalUserSnapshot) => u.id),
                ],
            tool_ids: enabledTools,
            remove_image: removePersonaImage,
            search_start_date: values.search_start_date
              ? new Date(values.search_start_date)
              : null,
            num_chunks: numChunks,
            document_set_ids: teamKnowledge ? values.document_set_ids : [],
            user_file_ids: teamKnowledge ? [] : values.user_file_ids,
          };

          let personaResponse;

          if (isUpdate) {
            personaResponse = await updatePersona(
              existingPersona.id,
              submissionData
            );
          } else {
            personaResponse = await createPersona(submissionData);
          }

          let error = null;

          if (!personaResponse) {
            error = "Failed to create Agent - no response received";
          } else if (!personaResponse.ok) {
            error = await personaResponse.text();
          }

          if (error || !personaResponse) {
            setPopup({
              type: "error",
              message: `Failed to create Agent - ${error}`,
            });
            formikHelpers.setSubmitting(false);
          } else {
            const assistant = await personaResponse.json();
            const assistantId = assistant.id;
            // TODO: re-enable this once we figure out a way to better
            // handle the `undefined` pinned_assistants case. `undefined` pinned assistants
            // means the default ordering (admin specified)
            // if (!isUpdate) {
            //   const currentPinnedIds =
            //     user?.preferences?.pinned_assistants || [];
            //   await toggleAssistantPinnedStatus(
            //     currentPinnedIds,
            //     assistantId,
            //     true
            //   );
            // }
            if (
              shouldAddAssistantToUserPreferences &&
              user?.preferences?.chosen_assistants
            ) {
              const success = await addAssistantToList(assistantId);
              if (success) {
                setPopup({
                  message: `"${assistant.name}" has been added to your list.`,
                  type: "success",
                });
                await refreshAgents();
              } else {
                setPopup({
                  message: `"${assistant.name}" could not be added to your list.`,
                  type: "error",
                });
              }
            }

            await refreshAgents();

            router.push(
              isAdminPage
                ? `/admin/assistants?u=${Date.now()}`
                : `/chat?assistantId=${assistantId}`
            );
            setIsRequestSuccessful(true);
          }
        }}
      >
        {({ isSubmitting, values, setFieldValue }: FormikProps<any>) => {
          function toggleToolInValues(toolId: number) {
            const updatedEnabledToolsMap = {
              ...values.enabled_tools_map,
              [toolId]: !values.enabled_tools_map[toolId],
            };
            setFieldValue("enabled_tools_map", updatedEnabledToolsMap);
          }

          // model must support image input for image generation
          // to work
          const currentLLMSupportsImageOutput = modelSupportsImageInput(
            llmProviders,
            values.llm_model_version_override || defaultModelName || ""
          );

          const iconElement = (() => {
            if (uploadedImagePreview) {
              return (
                <img
                  src={uploadedImagePreview}
                  alt="Uploaded agent icon"
                  className="w-12 h-12 rounded-full object-cover"
                />
              );
            }

            if (existingPersona?.uploaded_image_id && !removePersonaImage) {
              return (
                <img
                  src={buildImgUrl(existingPersona?.uploaded_image_id)}
                  alt="Uploaded agent icon"
                  className="w-12 h-12 rounded-full object-cover"
                />
              );
            }

            return generateIdenticon((values.icon_shape || 0).toString(), 36);
          })();

          return (
            <>
              <Form className="w-full text-text-950 assistant-editor">
                <FormErrorFocus />
                {/* Refresh starter messages when name or description changes */}
                <p className="text-base font-normal text-2xl">
                  {existingPersona ? (
                    <>
                      Edit Agent <b>{existingPersona.name}</b>
                    </>
                  ) : (
                    "Create an Agent"
                  )}
                </p>
                <div className="max-w-4xl w-full">
                  <Separator />
                  <div className="flex gap-x-2 items-center">
                    <div className="block font-medium text-sm">Agent Icon</div>
                  </div>
                  <SubLabel>
                    The icon that will visually represent your Agent
                  </SubLabel>
                  <div className="flex gap-x-2 items-center">
                    <div
                      className="p-4 cursor-pointer  rounded-full flex  "
                      style={{
                        borderStyle: "dashed",
                        borderWidth: "1.5px",
                        borderSpacing: "4px",
                      }}
                    >
                      {iconElement}
                    </div>

                    <div className="flex flex-col gap-2">
                      <Button
                        secondary
                        type="button"
                        onClick={() => {
                          const fileInput = document.createElement("input");
                          fileInput.type = "file";
                          fileInput.accept = "image/*";
                          fileInput.onchange = (e) => {
                            const file = (e.target as HTMLInputElement)
                              .files?.[0];
                            if (file) {
                              const previewUrl = URL.createObjectURL(file);
                              setUploadedImagePreview(previewUrl);
                              setFieldValue("uploaded_image", file);
                            }
                          };
                          fileInput.click();
                        }}
                        leftIcon={() => <CameraIcon size={14} />}
                      >
                        {`Upload ${values.uploaded_image ? "New " : ""}Image`}
                      </Button>

                      {values.uploaded_image && (
                        <Button
                          secondary
                          type="button"
                          onClick={() => {
                            setUploadedImagePreview(null);
                            setFieldValue("uploaded_image", null);
                            setRemovePersonaImage(false);
                          }}
                          leftIcon={SvgTrash}
                        >
                          {`${
                            removePersonaImage
                              ? "Revert to Previous "
                              : "Remove "
                          } Image`}
                        </Button>
                      )}

                      {!values.uploaded_image &&
                        (!existingPersona?.uploaded_image_id ||
                          removePersonaImage) && (
                          <Button
                            secondary
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              const newShape = generateRandomIconShape();
                              const randomColor =
                                colorOptions[
                                  Math.floor(
                                    Math.random() * colorOptions.length
                                  )
                                ];
                              setFieldValue("icon_shape", newShape.encodedGrid);
                              setFieldValue("icon_color", randomColor);
                            }}
                            leftIcon={SvgEditBig}
                          >
                            Generate Icon
                          </Button>
                        )}

                      {existingPersona?.uploaded_image_id &&
                        removePersonaImage &&
                        !values.uploaded_image && (
                          <Button
                            secondary
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setRemovePersonaImage(false);
                              setUploadedImagePreview(null);
                              setFieldValue("uploaded_image", null);
                            }}
                            leftIcon={() => <SwapIcon className="h-3 w-3" />}
                          >
                            Revert to Previous Image
                          </Button>
                        )}

                      {existingPersona?.uploaded_image_id &&
                        !removePersonaImage &&
                        !values.uploaded_image && (
                          <Button
                            secondary
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setRemovePersonaImage(true);
                            }}
                            leftIcon={SvgTrash}
                          >
                            Remove Image
                          </Button>
                        )}
                    </div>
                  </div>
                </div>

                <NameField />

                <DescriptionField />

                <Separator />

                <SystemPromptField />

                <div className="w-full max-w-4xl">
                  <div className="flex flex-col">
                    {searchTool && (
                      <>
                        <Separator />
                        <div className="flex gap-x-2 py-2 flex justify-start">
                          <div>
                            <div className="flex items-start gap-x-2">
                              <p className="block font-medium text-sm">
                                Knowledge
                              </p>
                              <div className="flex items-center">
                                <TooltipProvider>
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      <div
                                        className={`${
                                          !connectorsExist
                                            ? "opacity-70 cursor-not-allowed"
                                            : ""
                                        }`}
                                      >
                                        <FastField
                                          name={`enabled_tools_map.${searchTool.id}`}
                                        >
                                          {({ form }: any) => (
                                            <SwitchField
                                              size="sm"
                                              onCheckedChange={(
                                                checked: boolean
                                              ) => {
                                                form.setFieldValue(
                                                  "num_chunks",
                                                  null
                                                );
                                                toggleToolInValues(
                                                  searchTool.id
                                                );
                                              }}
                                              name={`enabled_tools_map.${searchTool.id}`}
                                              disabled={!connectorsExist}
                                            />
                                          )}
                                        </FastField>
                                      </div>
                                    </TooltipTrigger>

                                    {!connectorsExist && (
                                      <TooltipContent side="top" align="center">
                                        <Text inverted>
                                          To use Knowledge, you need to have at
                                          least one Connector configured. You
                                          can still upload user files to the
                                          agent below.
                                        </Text>
                                      </TooltipContent>
                                    )}
                                  </Tooltip>
                                </TooltipProvider>
                              </div>
                            </div>
                          </div>
                        </div>
                      </>
                    )}

                    {((searchTool && values.enabled_tools_map[searchTool.id]) ||
                      !connectorsExist) && (
                      <div>
                        {canShowKnowledgeSource && (
                          <>
                            <div className="mt-1.5 mb-2.5">
                              <div className="flex gap-2.5">
                                <div
                                  className={`w-[150px] h-[110px] rounded-lg border flex flex-col items-center justify-center cursor-pointer transition-all ${
                                    values.knowledge_source === "team_knowledge"
                                      ? "border-2 border-blue-500 bg-blue-50 dark:bg-blue-950/20"
                                      : "border-gray-200 hover:border-gray-300 dark:border-gray-700 dark:hover:border-gray-600"
                                  }`}
                                  onClick={() =>
                                    setFieldValue(
                                      "knowledge_source",
                                      "team_knowledge"
                                    )
                                  }
                                >
                                  <div className="text-blue-500 mb-2">
                                    <BookIcon size={24} />
                                  </div>
                                  <p className="font-medium text-xs">
                                    Team Knowledge
                                  </p>
                                </div>

                                {userKnowledgeEnabled && (
                                  <div
                                    className={`w-[150px] h-[110px] rounded-lg border flex flex-col items-center justify-center cursor-pointer transition-all ${
                                      values.knowledge_source === "user_files"
                                        ? "border-2 border-blue-500 bg-blue-50 dark:bg-blue-950/20"
                                        : "border-gray-200 hover:border-gray-300 dark:border-gray-700 dark:hover:border-gray-600"
                                    }`}
                                    onClick={() =>
                                      setFieldValue(
                                        "knowledge_source",
                                        "user_files"
                                      )
                                    }
                                  >
                                    <div className="text-blue-500 mb-2">
                                      <FileIcon size={24} />
                                    </div>
                                    <p className="font-medium text-xs">
                                      User Knowledge
                                    </p>
                                  </div>
                                )}
                              </div>
                            </div>
                          </>
                        )}

                        {values.knowledge_source === "user_files" &&
                          !existingPersona?.is_default_persona && (
                            <div className="text-sm flex flex-col items-start">
                              <SubLabel>Click below to add files</SubLabel>
                              {values.user_file_ids.length > 0 && (
                                <div className="flex gap-spacing-inline">
                                  {values.user_file_ids
                                    .slice(0, 4)
                                    .map((userFileId: string) => {
                                      const rf = allRecentFiles.find(
                                        (f) => f.id === userFileId
                                      );

                                      const fileData = rf || {
                                        id: userFileId,
                                        name: `File ${userFileId.slice(0, 8)}`,
                                        status: "completed" as const,
                                      };
                                      return (
                                        <div key={userFileId} className="w-40">
                                          <FileCard
                                            file={fileData as ProjectFile}
                                            hideProcessingState
                                            removeFile={() => {
                                              setFieldValue(
                                                "user_file_ids",
                                                values.user_file_ids.filter(
                                                  (id: string) =>
                                                    id !== userFileId
                                                )
                                              );
                                            }}
                                          />
                                        </div>
                                      );
                                    })}
                                  {values.user_file_ids.length > 4 && (
                                    <button
                                      type="button"
                                      className="rounded-xl px-3 py-1 text-left transition-colors hover:bg-background-tint-02"
                                      onClick={() => setShowAllUserFiles(true)}
                                    >
                                      <div className="flex flex-col overflow-hidden h-12 p-1">
                                        <div className="flex items-center justify-between gap-2 w-full">
                                          <Text text04 secondaryAction>
                                            View All
                                          </Text>
                                          <SvgFiles className="h-5 w-5 stroke-text-02" />
                                        </div>
                                        <Text text03 secondaryBody>
                                          {values.user_file_ids.length} files
                                        </Text>
                                      </div>
                                    </button>
                                  )}
                                </div>
                              )}
                              <FilePicker
                                trigger={
                                  <CreateButton>Add User Files</CreateButton>
                                }
                                recentFiles={allRecentFiles}
                                onFileClick={(file: ProjectFile) => {
                                  setPresentingDocument({
                                    document_id: `project_file__${file.file_id}`,
                                    semantic_identifier: file.name,
                                  });
                                }}
                                onPickRecent={(file: ProjectFile) => {
                                  if (!values.user_file_ids.includes(file.id)) {
                                    setFieldValue("user_file_ids", [
                                      ...values.user_file_ids,
                                      file.id,
                                    ]);
                                  }
                                }}
                                onUnpickRecent={(file: ProjectFile) => {
                                  if (values.user_file_ids.includes(file.id)) {
                                    setFieldValue(
                                      "user_file_ids",
                                      values.user_file_ids.filter(
                                        (id: string) => id !== file.id
                                      )
                                    );
                                  }
                                }}
                                handleUploadChange={async (
                                  e: React.ChangeEvent<HTMLInputElement>
                                ) => {
                                  const files = e.target.files;
                                  if (!files || files.length === 0) return;
                                  try {
                                    // Use a local tracker to avoid stale closures inside onSuccess
                                    let selectedIds = [
                                      ...(values.user_file_ids || []),
                                    ];
                                    const optimistic = await beginUpload(
                                      Array.from(files),
                                      null,
                                      setPopup,
                                      (result) => {
                                        const uploadedFiles =
                                          result.user_files || [];
                                        if (uploadedFiles.length === 0) return;
                                        const tempToFinal = new Map(
                                          uploadedFiles
                                            .filter((f) => f.temp_id)
                                            .map((f) => [
                                              f.temp_id as string,
                                              f.id,
                                            ])
                                        );
                                        const replaced = (
                                          selectedIds || []
                                        ).map(
                                          (id: string) =>
                                            tempToFinal.get(id) ?? id
                                        );
                                        const deduped = Array.from(
                                          new Set(replaced)
                                        );
                                        setFieldValue("user_file_ids", deduped);
                                        selectedIds = deduped;
                                      },
                                      (failedTempIds) => {
                                        if (
                                          !failedTempIds ||
                                          failedTempIds.length === 0
                                        )
                                          return;
                                        const filtered = (
                                          selectedIds || []
                                        ).filter(
                                          (id: string) =>
                                            !failedTempIds.includes(id)
                                        );
                                        setFieldValue(
                                          "user_file_ids",
                                          filtered
                                        );
                                        selectedIds = filtered;
                                      }
                                    );
                                    const optimisticIds = optimistic.map(
                                      (f) => f.id
                                    );
                                    const merged = Array.from(
                                      new Set([
                                        ...(selectedIds || []),
                                        ...optimisticIds,
                                      ])
                                    );
                                    setFieldValue("user_file_ids", merged);
                                    selectedIds = merged;
                                  } finally {
                                    e.target.value = "";
                                  }
                                }}
                                selectedFileIds={values.user_file_ids}
                              />
                            </div>
                          )}

                        {values.knowledge_source === "team_knowledge" &&
                          connectorsExist && (
                            <>
                              {canShowKnowledgeSource && (
                                <div className="mt-4">
                                  <div>
                                    <SubLabel>
                                      <>
                                        Select which{" "}
                                        {!user ||
                                        user.role !== UserRole.BASIC ? (
                                          <Link
                                            href="/admin/documents/sets"
                                            className="font-semibold underline hover:underline text-text"
                                            target="_blank"
                                          >
                                            Document Sets
                                          </Link>
                                        ) : (
                                          "Team Document Sets"
                                        )}{" "}
                                        this Agent should use to inform its
                                        responses. If none are specified, the
                                        Agent will reference all available
                                        documents.
                                      </>
                                    </SubLabel>
                                  </div>
                                </div>
                              )}
                              {documentSets.length > 0 ? (
                                <FieldArray
                                  name="document_set_ids"
                                  render={(arrayHelpers: ArrayHelpers) => (
                                    <div>
                                      <div className="mb-3 mt-2 flex gap-2 flex-wrap text-sm">
                                        {documentSets.map((documentSet) => (
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
                                                arrayHelpers.remove(index);
                                              } else {
                                                arrayHelpers.push(
                                                  documentSet.id
                                                );
                                              }
                                            }}
                                          />
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                />
                              ) : (
                                <p className="text-sm">
                                  <Link
                                    href="/admin/documents/sets/new"
                                    className="text-primary hover:underline"
                                  >
                                    + Create Document Set
                                  </Link>
                                </p>
                              )}
                            </>
                          )}
                      </div>
                    )}

                    <Separator />
                    <div className="py-2">
                      <p className="block font-medium text-sm mb-2">Actions</p>

                      {imageGenerationTool && (
                        <>
                          <div className="flex items-center content-start mb-2">
                            <FastField
                              name={`enabled_tools_map.${imageGenerationTool.id}`}
                            >
                              {() => (
                                <BooleanFormField
                                  name={`enabled_tools_map.${imageGenerationTool.id}`}
                                  label={imageGenerationTool.display_name}
                                  subtext="Generate and manipulate images using AI-powered tools"
                                  disabled={!currentLLMSupportsImageOutput}
                                  disabledTooltip={
                                    !currentLLMSupportsImageOutput
                                      ? "To use Image Generation, select GPT-4 or another image compatible model as the default model for this Agent."
                                      : "Image Generation requires an OpenAI or Azure Dall-E configuration."
                                  }
                                />
                              )}
                            </FastField>
                          </div>
                        </>
                      )}

                      {webSearchTool && (
                        <>
                          <FastField
                            name={`enabled_tools_map.${webSearchTool.id}`}
                          >
                            {() => (
                              <BooleanFormField
                                name={`enabled_tools_map.${webSearchTool.id}`}
                                label={webSearchTool.display_name}
                                subtext="Access real-time information and search the web for up-to-date results"
                              />
                            )}
                          </FastField>
                        </>
                      )}

                      {/* Regular Custom Tools */}
                      {customTools.length > 0 && (
                        <MemoizedToolList tools={customTools} />
                      )}

                      {/* MCP Server Tools - Hierarchical Structure */}
                      {Object.keys(mcpToolsByServer).length > 0 &&
                        Object.entries(mcpToolsByServer).map(
                          ([serverId, serverTools]) => {
                            const serverIdNum = parseInt(serverId);
                            const serverInfo =
                              mcpServers.find(
                                (server) => server.id === serverIdNum
                              ) || null;
                            const isCollapsed =
                              collapsedServers.has(serverIdNum) ||
                              !seenServerIdsRef.current.has(serverIdNum);

                            // Extract server name from tool name (format: "server_name_tool_name")
                            const firstTool = serverTools[0];
                            const serverName =
                              serverInfo?.name ||
                              firstTool?.name
                                ?.split("_")
                                .slice(0, -1)
                                .join("_") ||
                              `MCP Server ${serverId}`;

                            const serverUrl =
                              serverInfo?.server_url || "Unknown URL";

                            return (
                              <MCPServerSection
                                key={`mcp-server-${serverId}`}
                                serverId={serverIdNum}
                                serverTools={serverTools}
                                serverName={serverName}
                                serverUrl={serverUrl}
                                isCollapsed={isCollapsed}
                                onToggleCollapse={toggleServerCollapse}
                                onToggleServerTools={() => {
                                  toggleMCPServerTools(
                                    serverIdNum,
                                    values.enabled_tools_map,
                                    setFieldValue
                                  );
                                }}
                              />
                            );
                          }
                        )}
                    </div>
                  </div>
                </div>
                <Separator className="max-w-4xl mt-0" />

                <div className="-mt-2">
                  <div className="flex gap-x-2 mb-2 items-center">
                    <div className="block font-medium text-sm">
                      Default Model
                    </div>
                  </div>
                  <LLMSelector
                    llmProviders={llmProviders}
                    currentLlm={
                      values.llm_model_version_override
                        ? structureValue(
                            values.llm_model_provider_override,
                            "",
                            values.llm_model_version_override
                          )
                        : null
                    }
                    requiresImageGeneration={
                      imageGenerationTool
                        ? values.enabled_tools_map[imageGenerationTool.id]
                        : false
                    }
                    onSelect={(selected) => {
                      if (selected === null) {
                        setFieldValue("llm_model_version_override", null);
                        setFieldValue("llm_model_provider_override", null);
                      } else {
                        const { modelName, provider, name } =
                          parseLlmDescriptor(selected);
                        if (modelName && name) {
                          setFieldValue(
                            "llm_model_version_override",
                            modelName
                          );
                          setFieldValue("llm_model_provider_override", name);
                        }
                      }
                    }}
                  />
                </div>

                <Separator />
                <AdvancedOptionsToggle
                  showAdvancedOptions={showAdvancedOptions}
                  setShowAdvancedOptions={setShowAdvancedOptions}
                />
                {showAdvancedOptions && (
                  <>
                    <div className="max-w-4xl w-full">
                      {user?.role === UserRole.ADMIN && (
                        <BooleanFormField
                          onChange={(checked) => {
                            if (checked) {
                              setFieldValue("is_public", true);
                              setFieldValue("is_default_persona", true);
                            }
                          }}
                          name="is_default_persona"
                          label="Featured Agent"
                          subtext="If set, this agent will be pinned for all new users and appear in the Featured list in the agent explorer. This also makes the agent public."
                        />
                      )}

                      <Separator />

                      <div className="flex gap-x-2 items-center ">
                        <div className="block font-medium text-sm">Access</div>
                      </div>
                      <SubLabel>
                        Control who can access and use this agent
                      </SubLabel>

                      <div className="min-h-[100px]">
                        <div className="flex items-center mb-2">
                          <TooltipProvider>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <div>
                                  <SwitchField
                                    name="is_public"
                                    size="md"
                                    onCheckedChange={(checked) => {
                                      if (
                                        values.is_default_persona &&
                                        !checked
                                      ) {
                                        setShowVisibilityWarning(true);
                                      } else {
                                        setFieldValue("is_public", checked);
                                        if (!checked) {
                                          // Even though this code path should not be possible,
                                          // we set the default persona to false to be safe
                                          setFieldValue(
                                            "is_default_persona",
                                            false
                                          );
                                        }
                                        if (checked) {
                                          setFieldValue("selectedUsers", []);
                                          setFieldValue("selectedGroups", []);
                                        }
                                      }
                                    }}
                                    disabled={values.is_default_persona}
                                  />
                                </div>
                              </TooltipTrigger>
                              {values.is_default_persona && (
                                <TooltipContent side="top" align="center">
                                  Default persona must be public. Set
                                  &quot;Default Persona&quot; to false to change
                                  visibility.
                                </TooltipContent>
                              )}
                            </Tooltip>
                          </TooltipProvider>
                          <span className="text-sm ml-2">
                            Organization Public
                          </span>
                        </div>

                        {showVisibilityWarning && (
                          <div className="flex items-center text-warning mt-2">
                            <InfoIcon size={16} className="mr-2" />
                            <span className="text-sm">
                              Default persona must be public. Visibility has
                              been automatically set to organization public.
                            </span>
                          </div>
                        )}

                        {values.is_public ? (
                          <p className="text-sm text-text-dark">
                            This agent will be available to everyone in your
                            organization
                          </p>
                        ) : (
                          <>
                            <p className="text-sm text-text-dark mb-2">
                              This agent will only be available to specific
                              users and groups
                            </p>
                            <div className="mt-2">
                              <Label className="mb-2" small>
                                Share with Users and Groups
                              </Label>

                              <SearchMultiSelectDropdown
                                options={[
                                  ...(Array.isArray(users) ? users : [])
                                    .filter(
                                      (u: MinimalUserSnapshot) =>
                                        !values.selectedUsers.some(
                                          (su: MinimalUserSnapshot) =>
                                            su.id === u.id
                                        ) && u.id !== user?.id
                                    )
                                    .map((u: MinimalUserSnapshot) => ({
                                      name: u.email,
                                      value: u.id,
                                      type: "user",
                                    })),
                                  ...(userGroups || [])
                                    .filter(
                                      (g: UserGroup) =>
                                        !values.selectedGroups.includes(g.id)
                                    )
                                    .map((g: UserGroup) => ({
                                      name: g.name,
                                      value: g.id,
                                      type: "group",
                                    })),
                                ]}
                                onSelect={(
                                  selected: DropdownOption<string | number>
                                ) => {
                                  const option = selected as {
                                    name: string;
                                    value: string | number;
                                    type: "user" | "group";
                                  };
                                  if (option.type === "user") {
                                    setFieldValue("selectedUsers", [
                                      ...values.selectedUsers,
                                      { id: option.value, email: option.name },
                                    ]);
                                  } else {
                                    setFieldValue("selectedGroups", [
                                      ...values.selectedGroups,
                                      option.value,
                                    ]);
                                  }
                                }}
                              />
                            </div>
                            <div className="flex flex-wrap gap-2 mt-2">
                              {values.selectedUsers.map(
                                (user: MinimalUserSnapshot) => (
                                  <SourceChip
                                    key={user.id}
                                    onRemove={() => {
                                      setFieldValue(
                                        "selectedUsers",
                                        values.selectedUsers.filter(
                                          (u: MinimalUserSnapshot) =>
                                            u.id !== user.id
                                        )
                                      );
                                    }}
                                    title={user.email}
                                    icon={<UserIcon size={12} />}
                                  />
                                )
                              )}
                              {values.selectedGroups.map((groupId: number) => {
                                const group = (userGroups || []).find(
                                  (g: UserGroup) => g.id === groupId
                                );
                                return group ? (
                                  <SourceChip
                                    key={group.id}
                                    title={group.name}
                                    onRemove={() => {
                                      setFieldValue(
                                        "selectedGroups",
                                        values.selectedGroups.filter(
                                          (id: number) => id !== group.id
                                        )
                                      );
                                    }}
                                    icon={<GroupsIconSkeleton size={12} />}
                                  />
                                ) : null;
                              })}
                            </div>
                          </>
                        )}
                      </div>
                    </div>

                    <Separator />

                    <div className="w-full flex flex-col">
                      <div className="flex gap-x-2 items-center">
                        <div className="block font-medium text-sm">
                          [Optional] Starter Messages
                        </div>
                      </div>

                      <SubLabel>
                        Sample messages that help users understand what this
                        agent can do and how to interact with it effectively.
                        New input fields will appear automatically as you type.
                      </SubLabel>

                      <div className="w-full">
                        <FieldArray
                          name="starter_messages"
                          render={(arrayHelpers: ArrayHelpers) => (
                            <StarterMessagesList
                              debouncedRefreshPrompts={() =>
                                debouncedRefreshPrompts(values, setFieldValue)
                              }
                              autoStarterMessageEnabled={
                                autoStarterMessageEnabled
                              }
                              isRefreshing={isRefreshing}
                              values={values.starter_messages}
                              arrayHelpers={arrayHelpers}
                              setFieldValue={setFieldValue}
                            />
                          )}
                        />
                      </div>
                    </div>

                    <div className=" w-full max-w-4xl">
                      <Separator />
                      <div className="flex gap-x-2 items-center mt-4 ">
                        <div className="block font-medium text-sm">Labels</div>
                      </div>
                      <p
                        className="text-sm text-subtle"
                        style={{ color: "rgb(113, 114, 121)" }}
                      >
                        Select labels to categorize this agent
                      </p>
                      <div className="mt-3">
                        <SearchMultiSelectDropdown
                          onCreate={async (name: string) => {
                            await createLabel(name);
                            const currentLabels = await refreshLabels();

                            setTimeout(() => {
                              const newLabelId = currentLabels.find(
                                (l: { name: string }) => l.name === name
                              )?.id;
                              const updatedLabelIds = [
                                ...values.label_ids,
                                newLabelId as number,
                              ];
                              setFieldValue("label_ids", updatedLabelIds);
                            }, 300);
                          }}
                          options={Array.from(
                            new Set(labels.map((label) => label.name))
                          ).map((name) => ({
                            name,
                            value: name,
                          }))}
                          onSelect={(selected) => {
                            const newLabelIds = [
                              ...values.label_ids,
                              labels.find((l) => l.name === selected.value)
                                ?.id as number,
                            ];
                            setFieldValue("label_ids", newLabelIds);
                          }}
                          itemComponent={({ option }) => (
                            <div className="flex items-center justify-between px-4 py-3 text-sm hover:bg-accent-background-hovered cursor-pointer border-b border-border last:border-b-0">
                              <div
                                className="flex-grow"
                                onClick={() => {
                                  const label = labels.find(
                                    (l) => l.name === option.value
                                  );
                                  if (label) {
                                    const isSelected =
                                      values.label_ids.includes(label.id);
                                    const newLabelIds = isSelected
                                      ? values.label_ids.filter(
                                          (id: number) => id !== label.id
                                        )
                                      : [...values.label_ids, label.id];
                                    setFieldValue("label_ids", newLabelIds);
                                  }
                                }}
                              >
                                <span className="font-normal leading-none">
                                  {option.name}
                                </span>
                              </div>
                              {user?.role === UserRole.ADMIN && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    const label = labels.find(
                                      (l) => l.name === option.value
                                    );
                                    if (label) {
                                      deleteLabel(label.id);
                                    }
                                  }}
                                  className="ml-2 p-1 hover:bg-background-hover rounded"
                                >
                                  <TrashIcon size={16} />
                                </button>
                              )}
                            </div>
                          )}
                        />
                        <div className="mt-2 flex flex-wrap gap-2">
                          {values.label_ids.map((labelId: number) => {
                            const label = labels.find((l) => l.id === labelId);
                            return label ? (
                              <SourceChip
                                key={label.id}
                                onRemove={() => {
                                  setFieldValue(
                                    "label_ids",
                                    values.label_ids.filter(
                                      (id: number) => id !== label.id
                                    )
                                  );
                                }}
                                title={label.name}
                                icon={<TagIcon size={12} />}
                              />
                            ) : null;
                          })}
                        </div>
                      </div>
                    </div>
                    <Separator />

                    <div className="flex flex-col gap-y-4">
                      <div className="flex flex-col gap-y-4">
                        <h3 className="font-medium text-sm">
                          Knowledge Options
                        </h3>
                        <div className="flex flex-col gap-y-4 ml-4">
                          <TextFormField
                            small={true}
                            name="num_chunks"
                            label="[Optional] Number of Context Documents"
                            placeholder="Default 10"
                            onChange={(e) => {
                              const value = e.target.value;
                              if (value === "" || /^[0-9]+$/.test(value)) {
                                setFieldValue("num_chunks", value);
                              }
                            }}
                          />

                          <TextFormField
                            width="max-w-xl"
                            type="date"
                            small
                            subtext="Documents prior to this date will be ignored."
                            label="[Optional] Knowledge Cutoff Date"
                            name="search_start_date"
                          />

                          <BooleanFormField
                            small
                            removeIndent
                            name="llm_relevance_filter"
                            label="AI Relevance Filter"
                            subtext="If enabled, the LLM will filter out documents that are not useful for answering the user query prior to generating a response. This typically improves the quality of the response but incurs slightly higher cost."
                          />
                        </div>
                      </div>
                    </div>
                    <Separator />

                    <BooleanFormField
                      small
                      removeIndent
                      name="datetime_aware"
                      label="Date and Time Aware"
                      subtext='Toggle this option to let the agent know the current date and time (formatted like: "Thursday Jan 1, 1970 00:01"). To inject it in a specific place in the prompt, use the pattern [[CURRENT_DATETIME]]'
                    />

                    <Separator />

                    <TaskPromptField />
                  </>
                )}

                <div className="mt-12 w-full flex justify-between items-center">
                  <div>
                    {existingPersona && (
                      <Button danger onClick={openDeleteModal}>
                        Delete
                      </Button>
                    )}
                  </div>
                  <div className="flex gap-x-2 items-center">
                    <Button
                      disabled={
                        isSubmitting ||
                        isRequestSuccessful ||
                        (values.user_file_ids || []).some(
                          (id: string) =>
                            id.startsWith("temp_") || id.includes("temp_")
                        )
                      }
                      type="submit"
                    >
                      {isUpdate ? "Update" : "Create"}
                    </Button>
                    <Button secondary onClick={() => router.back()}>
                      Cancel
                    </Button>
                  </div>
                </div>
              </Form>
              {showAllUserFiles && (
                <CoreModal
                  className="w-full max-w-lg"
                  onClickOutside={() => setShowAllUserFiles(false)}
                >
                  <UserFilesModalContent
                    title="User Files"
                    description="All files selected for this assistant"
                    icon={SvgFiles}
                    recentFiles={values.user_file_ids.map(
                      (userFileId: string) => {
                        const rf = allRecentFiles.find(
                          (f) => f.id === userFileId
                        );
                        return (
                          rf || {
                            id: userFileId,
                            name: `File ${userFileId.slice(0, 8)}`,
                            status: "completed" as const,
                          }
                        );
                      }
                    )}
                    showRemove
                    onRemove={(file) => {
                      setFieldValue(
                        "user_file_ids",
                        values.user_file_ids.filter(
                          (id: string) => id !== file.id
                        )
                      );
                    }}
                    onClose={() => setShowAllUserFiles(false)}
                  />
                </CoreModal>
              )}
            </>
          );
        }}
      </Formik>
    </div>
  );
}
