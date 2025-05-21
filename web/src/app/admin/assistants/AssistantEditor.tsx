"use client";

import React from "react";
import { Option } from "@/components/Dropdown";
import { generateRandomIconShape } from "@/lib/assistantIconUtils";
import {
  CCPairBasicInfo,
  DocumentSet,
  User,
  UserGroup,
  UserRole,
} from "@/lib/types";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { ArrayHelpers, FieldArray, Form, Formik, FormikProps } from "formik";

import {
  BooleanFormField,
  Label,
  TextFormField,
} from "@/components/admin/connectors/Field";

import { usePopup } from "@/components/admin/connectors/Popup";
import { getDisplayNameForModel, useLabels } from "@/lib/hooks";
import { DocumentSetSelectable } from "@/components/documentSet/DocumentSetSelectable";
import { addAssistantToList } from "@/lib/assistants/updateAssistantPreferences";
import {
  parseLlmDescriptor,
  modelSupportsImageInput,
  structureValue,
} from "@/lib/llm/utils";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { checkUserIsNoAuthUser } from "@/lib/user";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import * as Yup from "yup";
import { FullPersona, PersonaLabel, StarterMessage } from "./interfaces";
import {
  PersonaUpsertParameters,
  createPersona,
  updatePersona,
  deletePersona,
} from "./lib";
import {
  CameraIcon,
  GroupsIconSkeleton,
  NewChatIcon,
  SwapIcon,
  TrashIcon,
} from "@/components/icons/icons";
import { buildImgUrl } from "@/app/chat/files/images/utils";
import { useAssistants } from "@/components/context/AssistantsContext";
import { debounce } from "lodash";
import { LLMProviderView } from "../configuration/llm/interfaces";
import StarterMessagesList from "./StarterMessageList";

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
import { SourceChip } from "@/app/chat/input/ChatInputBar";
import {
  TagIcon,
  UserIcon,
  FileIcon,
  FolderIcon,
  InfoIcon,
  BookIcon,
} from "lucide-react";
import { LLMSelector } from "@/components/llm/LLMSelector";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";

import { FilePickerModal } from "@/app/chat/my-documents/components/FilePicker";
import { useDocumentsContext } from "@/app/chat/my-documents/DocumentsContext";

import { SEARCH_TOOL_ID } from "@/app/chat/tools/constants";
import TextView from "@/components/chat/TextView";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { MAX_CHARACTERS_PERSONA_DESCRIPTION } from "@/lib/constants";

function findSearchTool(tools: ToolSnapshot[]) {
  return tools.find((tool) => tool.in_code_tool_id === SEARCH_TOOL_ID);
}

function findImageGenerationTool(tools: ToolSnapshot[]) {
  return tools.find((tool) => tool.in_code_tool_id === "ImageGenerationTool");
}

function findInternetSearchTool(tools: ToolSnapshot[]) {
  return tools.find((tool) => tool.in_code_tool_id === "InternetSearchTool");
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
  admin,
}: {
  existingPersona?: FullPersona | null;
  ccPairs: CCPairBasicInfo[];
  documentSets: DocumentSet[];
  user: User | null;
  defaultPublic: boolean;
  llmProviders: LLMProviderView[];
  tools: ToolSnapshot[];
  shouldAddAssistantToUserPreferences?: boolean;
  admin?: boolean;
}) {
  const { refreshAssistants, isImageGenerationAvailable } = useAssistants();

  const router = useRouter();
  const searchParams = useSearchParams();
  const isAdminPage = searchParams?.get("admin") === "true";

  const { popup, setPopup } = usePopup();
  const { labels, refreshLabels, createLabel, updateLabel, deleteLabel } =
    useLabels();

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
  const [filePickerModalOpen, setFilePickerModalOpen] = useState(false);
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  // state to persist across formik reformatting
  const [defautIconColor, _setDeafultIconColor] = useState(
    colorOptions[Math.floor(Math.random() * colorOptions.length)]
  );
  const [isRefreshing, setIsRefreshing] = useState(false);

  const [defaultIconShape, setDefaultIconShape] = useState<any>(null);

  useEffect(() => {
    if (defaultIconShape === null) {
      setDefaultIconShape(generateRandomIconShape().encodedGrid);
    }
  }, [defaultIconShape]);

  const [removePersonaImage, setRemovePersonaImage] = useState(false);

  const autoStarterMessageEnabled = useMemo(
    () => llmProviders.length > 0,
    [llmProviders.length]
  );
  const isUpdate = existingPersona !== undefined && existingPersona !== null;
  const existingPrompt = existingPersona?.prompts[0] ?? null;
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
  const internetSearchTool = findInternetSearchTool(tools);

  const customTools = tools.filter(
    (tool) =>
      tool.in_code_tool_id !== searchTool?.in_code_tool_id &&
      tool.in_code_tool_id !== imageGenerationTool?.in_code_tool_id &&
      tool.in_code_tool_id !== internetSearchTool?.in_code_tool_id
  );

  const availableTools = [
    ...customTools,
    ...(searchTool ? [searchTool] : []),
    ...(imageGenerationTool ? [imageGenerationTool] : []),
    ...(internetSearchTool ? [internetSearchTool] : []),
  ];
  const enabledToolsMap: { [key: number]: boolean } = {};
  availableTools.forEach((tool) => {
    enabledToolsMap[tool.id] = personaCurrentToolIds.includes(tool.id);
  });

  const { files, folders, refreshFolders } = useDocumentsContext();

  const [showVisibilityWarning, setShowVisibilityWarning] = useState(false);

  const initialValues = {
    name: existingPersona?.name ?? "",
    description: existingPersona?.description ?? "",
    datetime_aware: existingPrompt?.datetime_aware ?? false,
    system_prompt: existingPrompt?.system_prompt ?? "",
    task_prompt: existingPrompt?.task_prompt ?? "",
    is_public: existingPersona?.is_public ?? defaultPublic,
    document_set_ids:
      existingPersona?.document_sets?.map((documentSet) => documentSet.id) ??
      ([] as number[]),
    num_chunks: existingPersona?.num_chunks ?? null,
    search_start_date: existingPersona?.search_start_date
      ? existingPersona?.search_start_date.toString().split("T")[0]
      : null,
    include_citations: existingPersona?.prompts[0]?.include_citations ?? true,
    llm_relevance_filter: existingPersona?.llm_relevance_filter ?? false,
    llm_model_provider_override:
      existingPersona?.llm_model_provider_override ?? null,
    llm_model_version_override:
      existingPersona?.llm_model_version_override ?? null,
    starter_messages: existingPersona?.starter_messages?.length
      ? existingPersona.starter_messages
      : [{ message: "" }],
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
    user_folder_ids: existingPersona?.user_folder_ids ?? [],
    knowledge_source:
      (existingPersona?.user_file_ids?.length ?? 0) > 0 ||
      (existingPersona?.user_folder_ids?.length ?? 0) > 0
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

  const { data: userGroups } = useUserGroups();

  const { data: users } = useSWR<MinimalUserSnapshot[]>(
    "/api/users",
    errorHandlingFetcher
  );

  const [deleteModalOpen, setDeleteModalOpen] = useState(false);

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
        await refreshAssistants();
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

  const canShowKnowledgeSource =
    ccPairs.length > 0 &&
    searchTool &&
    !(user?.role != "admin" && documentSets.length === 0);

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
      {!admin && (
        <div className="absolute top-4 left-4">
          <BackButton />
        </div>
      )}

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
        enableReinitialize={true}
        initialValues={initialValues}
        validationSchema={Yup.object()
          .shape({
            name: Yup.string().required(
              "Must provide a name for the Assistant"
            ),
            description: Yup.string().required(
              "Must provide a description for the Assistant"
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
            include_citations: Yup.boolean().required(),
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

          const searchToolEnabled = searchTool
            ? enabledTools.includes(searchTool.id)
            : false;

          // if disable_retrieval is set, set num_chunks to 0
          // to tell the backend to not fetch any documents
          const numChunks = searchToolEnabled ? values.num_chunks || 25 : 0;
          const starterMessages = values.starter_messages
            .filter(
              (message: { message: string }) => message.message.trim() !== ""
            )
            .map((message: { message: string; name?: string }) => ({
              message: message.message,
              name: message.message,
            }));

          // don't set groups if marked as public
          const groups = values.is_public ? [] : values.selectedGroups;
          const teamKnowledge = values.knowledge_source === "team_knowledge";

          const submissionData: PersonaUpsertParameters = {
            ...values,
            icon_color: values.icon_color ?? null,
            existing_prompt_id: existingPrompt?.id ?? null,
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
            user_folder_ids: teamKnowledge ? [] : values.user_folder_ids,
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
            error = "Failed to create Assistant - no response received";
          } else if (!personaResponse.ok) {
            error = await personaResponse.text();
          }

          if (error || !personaResponse) {
            setPopup({
              type: "error",
              message: `Failed to create Assistant - ${error}`,
            });
            formikHelpers.setSubmitting(false);
          } else {
            const assistant = await personaResponse.json();
            const assistantId = assistant.id;
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
                await refreshAssistants();
              } else {
                setPopup({
                  message: `"${assistant.name}" could not be added to your list.`,
                  type: "error",
                });
              }
            }

            await refreshAssistants();
            await refreshFolders();

            router.push(
              isAdminPage
                ? `/admin/assistants?u=${Date.now()}`
                : `/chat?assistantId=${assistantId}`
            );
            setIsRequestSuccessful(true);
          }
        }}
      >
        {({
          isSubmitting,
          values,
          setFieldValue,
          errors,
          ...formikProps
        }: FormikProps<any>) => {
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

          // TODO: memoize this / make more efficient
          const selectedFiles = files.filter((file) =>
            values.user_file_ids.includes(file.id)
          );

          const selectedFolders = folders.filter((folder) =>
            values.user_folder_ids.includes(folder.id)
          );

          return (
            <>
              {filePickerModalOpen && (
                <FilePickerModal
                  setPresentingDocument={setPresentingDocument}
                  isOpen={filePickerModalOpen}
                  onClose={() => {
                    setFilePickerModalOpen(false);
                  }}
                  onSave={(selectedFiles, selectedFolders) => {
                    setFieldValue(
                      "user_file_ids",
                      selectedFiles.map((file) => file.id)
                    );
                    setFieldValue(
                      "user_folder_ids",
                      selectedFolders.map((folder) => folder.id)
                    );
                    setFilePickerModalOpen(false);
                  }}
                  buttonContent="Add to Assistant"
                />
              )}
              <Form className="w-full text-text-950 assistant-editor">
                {/* Refresh starter messages when name or description changes */}
                <p className="text-base font-normal text-2xl">
                  {existingPersona ? (
                    <>
                      Edit assistant <b>{existingPersona.name}</b>
                    </>
                  ) : (
                    "Create an Assistant"
                  )}
                </p>
                <div className="max-w-4xl w-full">
                  <Separator />
                  <div className="flex gap-x-2 items-center">
                    <div className="block font-medium text-sm">
                      Assistant Icon
                    </div>
                  </div>
                  <SubLabel>
                    The icon that will visually represent your Assistant
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
                      {values.uploaded_image ? (
                        <img
                          src={URL.createObjectURL(values.uploaded_image)}
                          alt="Uploaded assistant icon"
                          className="w-12 h-12 rounded-full object-cover"
                        />
                      ) : existingPersona?.uploaded_image_id &&
                        !removePersonaImage ? (
                        <img
                          src={buildImgUrl(existingPersona?.uploaded_image_id)}
                          alt="Uploaded assistant icon"
                          className="w-12 h-12 rounded-full object-cover"
                        />
                      ) : (
                        generateIdenticon(
                          (values.icon_shape || 0).toString(),
                          36
                        )
                      )}
                    </div>

                    <div className="flex flex-col gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="text-xs flex justify-start gap-x-2"
                        onClick={() => {
                          const fileInput = document.createElement("input");
                          fileInput.type = "file";
                          fileInput.accept = "image/*";
                          fileInput.onchange = (e) => {
                            const file = (e.target as HTMLInputElement)
                              .files?.[0];
                            if (file) {
                              setFieldValue("uploaded_image", file);
                            }
                          };
                          fileInput.click();
                        }}
                      >
                        <CameraIcon size={14} />
                        Upload {values.uploaded_image && "New "}Image
                      </Button>

                      {values.uploaded_image && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="flex justify-start gap-x-2 text-xs"
                          onClick={() => {
                            setFieldValue("uploaded_image", null);
                            setRemovePersonaImage(false);
                          }}
                        >
                          <TrashIcon className="h-3 w-3" />
                          {removePersonaImage
                            ? "Revert to Previous "
                            : "Remove "}
                          Image
                        </Button>
                      )}

                      {!values.uploaded_image &&
                        (!existingPersona?.uploaded_image_id ||
                          removePersonaImage) && (
                          <Button
                            type="button"
                            className="text-xs"
                            variant="outline"
                            size="sm"
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
                          >
                            <NewChatIcon size={14} />
                            Generate Icon
                          </Button>
                        )}

                      {existingPersona?.uploaded_image_id &&
                        removePersonaImage &&
                        !values.uploaded_image && (
                          <Button
                            type="button"
                            variant="outline"
                            className="text-xs"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              setRemovePersonaImage(false);
                              setFieldValue("uploaded_image", null);
                            }}
                          >
                            <SwapIcon className="h-3 w-3" />
                            Revert to Previous Image
                          </Button>
                        )}

                      {existingPersona?.uploaded_image_id &&
                        !removePersonaImage &&
                        !values.uploaded_image && (
                          <Button
                            type="button"
                            variant="outline"
                            className="text-xs"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              setRemovePersonaImage(true);
                            }}
                          >
                            <TrashIcon className="h-3 w-3" />
                            Remove Image
                          </Button>
                        )}
                    </div>
                  </div>
                </div>

                <TextFormField
                  maxWidth="max-w-lg"
                  name="name"
                  label="Name"
                  placeholder="Email Assistant"
                  aria-label="assistant-name-input"
                  className="[&_input]:placeholder:text-text-muted/50"
                />

                <TextFormField
                  maxWidth="max-w-lg"
                  name="description"
                  label="Description"
                  placeholder="Use this Assistant to help draft professional emails"
                  className="[&_input]:placeholder:text-text-muted/50"
                />

                <Separator />

                <TextFormField
                  maxWidth="max-w-4xl"
                  name="system_prompt"
                  label="Instructions"
                  isTextArea={true}
                  placeholder="You are a professional email writing assistant that always uses a polite enthusiastic tone, emphasizes action items, and leaves blanks for the human to fill in when you have unknowns"
                  data-testid="assistant-instructions-input"
                  className="[&_textarea]:placeholder:text-text-muted/50"
                />

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
                                <TooltipProvider delayDuration={0}>
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      <div
                                        className={`${
                                          ccPairs.length === 0
                                            ? "opacity-70 cursor-not-allowed"
                                            : ""
                                        }`}
                                      >
                                        <SwitchField
                                          size="sm"
                                          onCheckedChange={(checked) => {
                                            setFieldValue("num_chunks", null);
                                            toggleToolInValues(searchTool.id);
                                          }}
                                          name={`enabled_tools_map.${searchTool.id}`}
                                          disabled={ccPairs.length === 0}
                                        />
                                      </div>
                                    </TooltipTrigger>

                                    {ccPairs.length === 0 && (
                                      <TooltipContent side="top" align="center">
                                        <p className="bg-background-900 max-w-[200px] text-sm rounded-lg p-1.5 text-white">
                                          To use the Knowledge Action, you need
                                          to have at least one Connector
                                          configured.
                                        </p>
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

                    {searchTool && values.enabled_tools_map[searchTool.id] && (
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
                              </div>
                            </div>
                          </>
                        )}

                        {values.knowledge_source === "user_files" &&
                          !existingPersona?.is_default_persona &&
                          !admin && (
                            <div className="text-sm flex flex-col items-start">
                              <SubLabel>
                                Click below to add documents or folders from the
                                My Document feature
                              </SubLabel>
                              {(values.user_file_ids.length > 0 ||
                                values.user_folder_ids.length > 0) && (
                                <div className="flex flex-wrap mb-2 max-w-sm gap-2">
                                  {selectedFiles.map((file) => (
                                    <SourceChip
                                      key={file.id}
                                      onRemove={() => {}}
                                      title={file.name}
                                      icon={<FileIcon size={16} />}
                                    />
                                  ))}
                                  {selectedFolders.map((folder) => (
                                    <SourceChip
                                      key={folder.id}
                                      onRemove={() => {}}
                                      title={folder.name}
                                      icon={<FolderIcon size={16} />}
                                    />
                                  ))}
                                </div>
                              )}
                              <button
                                type="button"
                                onClick={() => setFilePickerModalOpen(true)}
                                className="text-primary hover:underline"
                              >
                                + Add User Files
                              </button>
                            </div>
                          )}

                        {values.knowledge_source === "team_knowledge" &&
                          ccPairs.length > 0 && (
                            <div className="mt-4">
                              <div>
                                <SubLabel>
                                  <>
                                    Select which{" "}
                                    {!user || user.role === "admin" ? (
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
                                    this Assistant should use to inform its
                                    responses. If none are specified, the
                                    Assistant will reference all available
                                    documents.
                                  </>
                                </SubLabel>
                              </div>

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
                            </div>
                          )}
                      </div>
                    )}

                    <Separator />
                    <div className="py-2">
                      <p className="block font-medium text-sm mb-2">Actions</p>

                      {imageGenerationTool && (
                        <>
                          <div className="flex items-center content-start mb-2">
                            <BooleanFormField
                              name={`enabled_tools_map.${imageGenerationTool.id}`}
                              label={imageGenerationTool.display_name}
                              subtext="Generate and manipulate images using AI-powered tools"
                              disabled={
                                !currentLLMSupportsImageOutput ||
                                !isImageGenerationAvailable
                              }
                              disabledTooltip={
                                !currentLLMSupportsImageOutput
                                  ? "To use Image Generation, select GPT-4 or another image compatible model as the default model for this Assistant."
                                  : "Image Generation requires an OpenAI or Azure Dall-E configuration."
                              }
                            />
                          </div>
                        </>
                      )}

                      {internetSearchTool && (
                        <>
                          <BooleanFormField
                            name={`enabled_tools_map.${internetSearchTool.id}`}
                            label={internetSearchTool.display_name}
                            subtext="Access real-time information and search the web for up-to-date results"
                          />
                        </>
                      )}

                      {customTools.length > 0 &&
                        customTools.map((tool) => (
                          <BooleanFormField
                            key={tool.id}
                            name={`enabled_tools_map.${tool.id}`}
                            label={tool.display_name}
                            subtext={tool.description}
                          />
                        ))}
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
                      {user?.role == UserRole.ADMIN && (
                        <BooleanFormField
                          onChange={(checked) => {
                            if (checked) {
                              setFieldValue("is_public", true);
                              setFieldValue("is_default_persona", true);
                            }
                          }}
                          name="is_default_persona"
                          label="Featured Assistant"
                          subtext="If set, this assistant will be pinned for all new users and appear in the Featured list in the assistant explorer. This also makes the assistant public."
                        />
                      )}

                      <Separator />

                      <div className="flex gap-x-2 items-center ">
                        <div className="block font-medium text-sm">Access</div>
                      </div>
                      <SubLabel>
                        Control who can access and use this assistant
                      </SubLabel>

                      <div className="min-h-[100px]">
                        <div className="flex items-center mb-2">
                          <TooltipProvider delayDuration={0}>
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
                            This assistant will be available to everyone in your
                            organization
                          </p>
                        ) : (
                          <>
                            <p className="text-sm text-text-dark mb-2">
                              This assistant will only be available to specific
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
                        assistant can do and how to interact with it
                        effectively. New input fields will appear automatically
                        as you type.
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
                        Select labels to categorize this assistant
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
                              {admin && (
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

                          <BooleanFormField
                            small
                            removeIndent
                            name="include_citations"
                            label="Citations"
                            subtext="Response will include citations ([1], [2], etc.) for documents referenced by the LLM. In general, we recommend to leave this enabled in order to increase trust in the LLM answer."
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
                      subtext='Toggle this option to let the assistant know the current date and time (formatted like: "Thursday Jan 1, 1970 00:01"). To inject it in a specific place in the prompt, use the pattern [[CURRENT_DATETIME]]'
                    />

                    <Separator />

                    <TextFormField
                      maxWidth="max-w-4xl"
                      name="task_prompt"
                      label="[Optional] Reminders"
                      isTextArea={true}
                      placeholder="Remember to reference all of the points mentioned in my message to you and focus on identifying action items that can move things forward"
                      onChange={(e) => {
                        setFieldValue("task_prompt", e.target.value);
                      }}
                      explanationText="Learn about prompting in our docs!"
                      explanationLink="https://docs.onyx.app/guides/assistants"
                      className="[&_textarea]:placeholder:text-text-muted/50"
                    />
                  </>
                )}

                <div className="mt-12 gap-x-2 w-full justify-end flex">
                  <Button
                    type="submit"
                    disabled={isSubmitting || isRequestSuccessful}
                  >
                    {isUpdate ? "Update" : "Create"}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => router.back()}
                  >
                    Cancel
                  </Button>
                </div>

                <div className="flex justify-end">
                  {existingPersona && (
                    <Button
                      variant="destructive"
                      onClick={openDeleteModal}
                      type="button"
                    >
                      Delete
                    </Button>
                  )}
                </div>
              </Form>
            </>
          );
        }}
      </Formik>
    </div>
  );
}
