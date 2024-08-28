"use client";

import { generateRandomIconShape, createSVG } from "@/lib/assistantIconUtils";

import { CCPairBasicInfo, DocumentSet, User } from "@/lib/types";
import { Button, Divider, Italic, Text } from "@tremor/react";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";
import {
  ArrayHelpers,
  ErrorMessage,
  Field,
  FieldArray,
  Form,
  Formik,
  FormikProps,
} from "formik";

import {
  BooleanFormField,
  Label,
  SelectorFormField,
  TextFormField,
} from "@/components/admin/connectors/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import { getDisplayNameForModel } from "@/lib/hooks";
import { DocumentSetSelectable } from "@/components/documentSet/DocumentSetSelectable";
import { Option } from "@/components/Dropdown";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { addAssistantToList } from "@/lib/assistants/updateAssistantPreferences";
import { useUserGroups } from "@/lib/hooks";
import { checkLLMSupportsImageInput, destructureValue } from "@/lib/llm/utils";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { checkUserIsNoAuthUser } from "@/lib/user";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@radix-ui/react-tooltip";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { FiInfo, FiPlus, FiX } from "react-icons/fi";
import * as Yup from "yup";
import { FullLLMProvider } from "../configuration/llm/interfaces";
import CollapsibleSection from "./CollapsibleSection";
import { SuccessfulPersonaUpdateRedirectType } from "./enums";
import { Persona, StarterMessage } from "./interfaces";
import { buildFinalPrompt, createPersona, updatePersona } from "./lib";
import { IconImageSelection } from "@/components/assistants/AssistantIconCreation";

function findSearchTool(tools: ToolSnapshot[]) {
  return tools.find((tool) => tool.in_code_tool_id === "SearchTool");
}

function findImageGenerationTool(tools: ToolSnapshot[]) {
  return tools.find((tool) => tool.in_code_tool_id === "ImageGenerationTool");
}

function findInternetSearchTool(tools: ToolSnapshot[]) {
  return tools.find((tool) => tool.in_code_tool_id === "InternetSearchTool");
}

function SubLabel({ children }: { children: string | JSX.Element }) {
  return <div className="text-sm text-subtle mb-2">{children}</div>;
}

export function AssistantEditor({
  existingPersona,
  ccPairs,
  documentSets,
  user,
  defaultPublic,
  redirectType,
  llmProviders,
  tools,
  shouldAddAssistantToUserPreferences,
}: {
  existingPersona?: Persona | null;
  ccPairs: CCPairBasicInfo[];
  documentSets: DocumentSet[];
  user: User | null;
  defaultPublic: boolean;
  redirectType: SuccessfulPersonaUpdateRedirectType;
  llmProviders: FullLLMProvider[];
  tools: ToolSnapshot[];
  shouldAddAssistantToUserPreferences?: boolean;
}) {
  const router = useRouter();
  const { popup, setPopup } = usePopup();

  const colorOptions = [
    "#FF6FBF",
    "#6FB1FF",
    "#B76FFF",
    "#FFB56F",
    "#6FFF8D",
    "#FF6F6F",
    "#6FFFFF",
  ];

  // state to persist across formik reformatting
  const [defautIconColor, _setDeafultIconColor] = useState(
    colorOptions[Math.floor(Math.random() * colorOptions.length)]
  );
  const [defaultIconShape, _setDeafultIconShape] = useState(
    generateRandomIconShape().encodedGrid
  );

  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  // EE only
  const { data: userGroups, isLoading: userGroupsIsLoading } = useUserGroups();

  const [finalPrompt, setFinalPrompt] = useState<string | null>("");
  const [finalPromptError, setFinalPromptError] = useState<string>("");
  const [removePersonaImage, setRemovePersonaImage] = useState(false);

  const triggerFinalPromptUpdate = async (
    systemPrompt: string,
    taskPrompt: string,
    retrievalDisabled: boolean
  ) => {
    const response = await buildFinalPrompt(
      systemPrompt,
      taskPrompt,
      retrievalDisabled
    );
    if (response.ok) {
      setFinalPrompt((await response.json()).final_prompt_template);
    }
  };

  const isUpdate = existingPersona !== undefined && existingPersona !== null;
  const existingPrompt = existingPersona?.prompts[0] ?? null;

  useEffect(() => {
    if (isUpdate && existingPrompt) {
      triggerFinalPromptUpdate(
        existingPrompt.system_prompt,
        existingPrompt.task_prompt,
        existingPersona.num_chunks === 0
      );
    }
  }, []);

  const defaultProvider = llmProviders.find(
    (llmProvider) => llmProvider.is_default_provider
  );
  const defaultProviderName = defaultProvider?.provider;
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
    const providerOptions = llmProvider.model_names.map((modelName) => {
      return {
        name: getDisplayNameForModel(modelName),
        value: modelName,
      };
    });
    modelOptionsByProvider.set(llmProvider.name, providerOptions);
  });
  const providerSupportingImageGenerationExists = llmProviders.some(
    (provider) => provider.provider === "openai"
  );

  const personaCurrentToolIds =
    existingPersona?.tools.map((tool) => tool.id) || [];
  const searchTool = findSearchTool(tools);
  const imageGenerationTool = providerSupportingImageGenerationExists
    ? findImageGenerationTool(tools)
    : undefined;
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

  const initialValues = {
    name: existingPersona?.name ?? "",
    description: existingPersona?.description ?? "",
    system_prompt: existingPrompt?.system_prompt ?? "",
    task_prompt: existingPrompt?.task_prompt ?? "",
    is_public: existingPersona?.is_public ?? defaultPublic,
    document_set_ids:
      existingPersona?.document_sets?.map((documentSet) => documentSet.id) ??
      ([] as number[]),
    num_chunks: existingPersona?.num_chunks ?? null,
    include_citations: existingPersona?.prompts[0]?.include_citations ?? true,
    llm_relevance_filter: existingPersona?.llm_relevance_filter ?? false,
    llm_model_provider_override:
      existingPersona?.llm_model_provider_override ?? null,
    llm_model_version_override:
      existingPersona?.llm_model_version_override ?? null,
    starter_messages: existingPersona?.starter_messages ?? [],
    enabled_tools_map: enabledToolsMap,
    icon_color: existingPersona?.icon_color ?? defautIconColor,
    icon_shape: existingPersona?.icon_shape ?? defaultIconShape,
    uploaded_image: null,

    //   search_tool_enabled: existingPersona
    //   ? personaCurrentToolIds.includes(searchTool!.id)
    //   : ccPairs.length > 0,
    // image_generation_tool_enabled: imageGenerationTool
    //   ? personaCurrentToolIds.includes(imageGenerationTool.id)
    //   : false,
    // EE Only
    groups: existingPersona?.groups ?? [],
  };

  const [existingPersonaImageId, setExistingPersonaImageId] = useState<
    string | null
  >(existingPersona?.uploaded_image_id || null);

  const [isRequestSuccessful, setIsRequestSuccessful] = useState(false);

  return (
    <div>
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
            system_prompt: Yup.string(),
            task_prompt: Yup.string(),
            is_public: Yup.boolean().required(),
            document_set_ids: Yup.array().of(Yup.number()),
            num_chunks: Yup.number().nullable(),
            include_citations: Yup.boolean().required(),
            llm_relevance_filter: Yup.boolean().required(),
            llm_model_version_override: Yup.string().nullable(),
            llm_model_provider_override: Yup.string().nullable(),
            starter_messages: Yup.array().of(
              Yup.object().shape({
                name: Yup.string().required(),
                description: Yup.string().required(),
                message: Yup.string().required(),
              })
            ),
            icon_color: Yup.string(),
            icon_shape: Yup.number(),
            uploaded_image: Yup.mixed().nullable(),
            // EE Only
            groups: Yup.array().of(Yup.number()),
          })
          .test(
            "system-prompt-or-task-prompt",
            "Must provide either System Prompt or Additional Instructions",
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
                  "Must provide either System Prompt or Additional Instructions",
              });
            }
          )}
        onSubmit={async (values, formikHelpers) => {
          if (finalPromptError) {
            setPopup({
              type: "error",
              message: "Cannot submit while there are errors in the form",
            });
            return;
          }

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
          const imageGenerationToolEnabled = imageGenerationTool
            ? enabledTools.includes(imageGenerationTool.id)
            : false;

          if (imageGenerationToolEnabled) {
            if (
              !checkLLMSupportsImageInput(
                providerDisplayNameToProviderName.get(
                  values.llm_model_provider_override || ""
                ) ||
                  defaultProviderName ||
                  "",
                values.llm_model_version_override || defaultModelName || ""
              )
            ) {
              enabledTools = enabledTools.filter(
                (toolId) => toolId !== imageGenerationTool!.id
              );
            }
          }

          // if disable_retrieval is set, set num_chunks to 0
          // to tell the backend to not fetch any documents
          const numChunks = searchToolEnabled ? values.num_chunks || 10 : 0;

          // don't set groups if marked as public
          const groups = values.is_public ? [] : values.groups;

          let promptResponse;
          let personaResponse;
          if (isUpdate) {
            [promptResponse, personaResponse] = await updatePersona({
              id: existingPersona.id,
              existingPromptId: existingPrompt?.id,
              ...values,
              num_chunks: numChunks,
              users:
                user && !checkUserIsNoAuthUser(user.id) ? [user.id] : undefined,
              groups,
              tool_ids: enabledTools,
              remove_image: removePersonaImage,
            });
          } else {
            [promptResponse, personaResponse] = await createPersona({
              ...values,
              num_chunks: numChunks,
              users:
                user && !checkUserIsNoAuthUser(user.id) ? [user.id] : undefined,
              groups,
              tool_ids: enabledTools,
            });
          }

          let error = null;
          if (!promptResponse.ok) {
            error = await promptResponse.text();
          }
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
              const success = await addAssistantToList(
                assistantId,
                user.preferences.chosen_assistants
              );
              if (success) {
                setPopup({
                  message: `"${assistant.name}" has been added to your list.`,
                  type: "success",
                });
                router.refresh();
              } else {
                setPopup({
                  message: `"${assistant.name}" could not be added to your list.`,
                  type: "error",
                });
              }
            }
            router.push(
              redirectType === SuccessfulPersonaUpdateRedirectType.ADMIN
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
          ...formikProps
        }: FormikProps<any>) => {
          function toggleToolInValues(toolId: number) {
            const updatedEnabledToolsMap = {
              ...values.enabled_tools_map,
              [toolId]: !values.enabled_tools_map[toolId],
            };
            setFieldValue("enabled_tools_map", updatedEnabledToolsMap);
          }

          function searchToolEnabled() {
            return searchTool && values.enabled_tools_map[searchTool.id]
              ? true
              : false;
          }

          return (
            <Form className="w-full">
              <div className="pb-6">
                <TextFormField
                  name="name"
                  tooltip="Used to identify the Assistant in the UI."
                  label="Name"
                  placeholder="e.g. 'Email Assistant'"
                />
                <div className="mb-6 ">
                  <div className="flex gap-x-2 items-center">
                    <div className="block font-medium text-base">
                      Assistant Icon{" "}
                    </div>
                    <TooltipProvider delayDuration={50}>
                      <Tooltip>
                        <TooltipTrigger>
                          <FiInfo size={12} />
                        </TooltipTrigger>
                        <TooltipContent side="top" align="center">
                          <p className="bg-background-900 max-w-[200px] mb-1 text-sm rounded-lg p-1.5 text-white">
                            Choose an icon to visually represent your Assistant
                            (optional)
                          </p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>

                  <div className="flex -mb-2 mt-2 items-center space-x-2">
                    {createSVG(
                      {
                        encodedGrid: values.icon_shape,
                        filledSquares: 0,
                      },
                      values.icon_color
                    )}

                    <div className="mb-2 flex gap-x-2 items-center">
                      <Button
                        onClick={() => {
                          const newShape = generateRandomIconShape();
                          setFieldValue("icon_shape", newShape.encodedGrid);
                          const randomColor =
                            colorOptions[
                              Math.floor(Math.random() * colorOptions.length)
                            ];
                          setFieldValue("icon_color", randomColor);
                        }}
                        color="blue"
                        size="xs"
                        type="button"
                        className="h-full"
                      >
                        Regenerate
                      </Button>
                    </div>
                  </div>

                  <IconImageSelection
                    setFieldValue={setFieldValue}
                    existingPersonaImageId={existingPersonaImageId!}
                    setExistingPersonaImageId={setExistingPersonaImageId}
                    setRemovePersonaImage={setRemovePersonaImage}
                  />
                </div>

                <TextFormField
                  tooltip="Used for identifying assistants and their use cases."
                  name="description"
                  label="Description"
                  placeholder="e.g. 'Use this Assistant to help draft professional emails'"
                />

                <TextFormField
                  tooltip="Gives your assistant a prime directive"
                  name="system_prompt"
                  label="System Prompt"
                  isTextArea={true}
                  placeholder="e.g. 'You are a professional email writing assistant that always uses a polite enthusiastic tone, emphasizes action items, and leaves blanks for the human to fill in when you have unknowns'"
                  //
                  onChange={(e) => {
                    setFieldValue("system_prompt", e.target.value);
                    triggerFinalPromptUpdate(
                      e.target.value,
                      values.task_prompt,
                      searchToolEnabled()
                    );
                  }}
                  error={finalPromptError}
                />

                <div className="mb-6">
                  <div className="flex gap-x-2 items-center">
                    <div className="block font-medium text-base">
                      LLM Override{" "}
                    </div>
                    <TooltipProvider delayDuration={50}>
                      <Tooltip>
                        <TooltipTrigger>
                          <FiInfo size={12} />
                        </TooltipTrigger>
                        <TooltipContent side="top" align="center">
                          <p className="bg-background-900 max-w-[200px] mb-1 text-sm rounded-lg p-1.5 text-white">
                            Select a Large Language Model (Generative AI model)
                            to power this Assistant
                          </p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                  <p className="my-1 text-text-600">
                    Your assistant will use the user&apos;s set default unless
                    otherwise specified below.
                    {user?.preferences.default_model &&
                      `  Your current (user-specific) default model is ${getDisplayNameForModel(destructureValue(user?.preferences?.default_model!).modelName)}`}
                  </p>
                  <div className="mb-2 flex items-starts">
                    <div className="w-96">
                      <SelectorFormField
                        defaultValue={`User default`}
                        name="llm_model_provider_override"
                        options={llmProviders.map((llmProvider) => ({
                          name: llmProvider.name,
                          value: llmProvider.name,
                          icon: llmProvider.icon,
                        }))}
                        includeDefault={true}
                        onSelect={(selected) => {
                          if (selected !== values.llm_model_provider_override) {
                            setFieldValue("llm_model_version_override", null);
                          }
                          setFieldValue(
                            "llm_model_provider_override",
                            selected
                          );
                        }}
                      />
                    </div>

                    {values.llm_model_provider_override && (
                      <div className="w-96 ml-4">
                        <SelectorFormField
                          name="llm_model_version_override"
                          options={
                            modelOptionsByProvider.get(
                              values.llm_model_provider_override
                            ) || []
                          }
                          maxHeight="max-h-72"
                        />
                      </div>
                    )}
                  </div>
                </div>
                <div className="mb-6">
                  <div className="flex gap-x-2 items-center">
                    <div className="block font-medium text-base">
                      Capabilities{" "}
                    </div>
                    <TooltipProvider delayDuration={50}>
                      <Tooltip>
                        <TooltipTrigger>
                          <FiInfo size={12} />
                        </TooltipTrigger>
                        <TooltipContent side="top" align="center">
                          <p className="bg-background-900 max-w-[200px] mb-1 text-sm rounded-lg p-1.5 text-white">
                            You can give your assistant advanced capabilities
                            like image generation
                          </p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                    <div className="block text-sm font-medium text-subtle">
                      Advanced
                    </div>
                  </div>

                  <div className="mt-2 flex flex-col  ml-1">
                    {imageGenerationTool && (
                      <TooltipProvider delayDuration={50}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <div
                              className={`w-fit ${
                                !checkLLMSupportsImageInput(
                                  providerDisplayNameToProviderName.get(
                                    values.llm_model_provider_override || ""
                                  ) || "",
                                  values.llm_model_version_override || ""
                                )
                                  ? "opacity-50 cursor-not-allowed"
                                  : ""
                              }`}
                            >
                              <BooleanFormField
                                noPadding
                                name={`enabled_tools_map.${imageGenerationTool.id}`}
                                label="Image Generation Tool"
                                onChange={() => {
                                  toggleToolInValues(imageGenerationTool.id);
                                }}
                                disabled={
                                  !checkLLMSupportsImageInput(
                                    providerDisplayNameToProviderName.get(
                                      values.llm_model_provider_override || ""
                                    ) || "",
                                    values.llm_model_version_override || ""
                                  )
                                }
                              />
                            </div>
                          </TooltipTrigger>
                          {!checkLLMSupportsImageInput(
                            providerDisplayNameToProviderName.get(
                              values.llm_model_provider_override || ""
                            ) || "",
                            values.llm_model_version_override || ""
                          ) && (
                            <TooltipContent side="top" align="center">
                              <p className="bg-background-900 max-w-[200px] mb-1 text-sm rounded-lg p-1.5 text-white">
                                To use Image Generation, select GPT-4o as the
                                default model for this Assistant.
                              </p>
                            </TooltipContent>
                          )}
                        </Tooltip>
                      </TooltipProvider>
                    )}

                    {searchTool && (
                      <TooltipProvider delayDuration={50}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <div
                              className={`w-fit ${
                                ccPairs.length === 0
                                  ? "opacity-50 cursor-not-allowed"
                                  : ""
                              }`}
                            >
                              <BooleanFormField
                                name={`enabled_tools_map.${searchTool.id}`}
                                label="Search Tool"
                                noPadding
                                onChange={() => {
                                  setFieldValue("num_chunks", null);
                                  toggleToolInValues(searchTool.id);
                                }}
                                disabled={ccPairs.length === 0}
                              />
                            </div>
                          </TooltipTrigger>
                          {ccPairs.length === 0 && (
                            <TooltipContent side="top" align="center">
                              <p className="bg-background-900 max-w-[200px] mb-1 text-sm rounded-lg p-1.5 text-white">
                                To use the Search Tool, you need to have at
                                least one Connector-Credential pair configured.
                              </p>
                            </TooltipContent>
                          )}
                        </Tooltip>
                      </TooltipProvider>
                    )}

                    {ccPairs.length > 0 && searchTool && (
                      <>
                        {searchToolEnabled() && (
                          <CollapsibleSection prompt="Configure Search">
                            <div>
                              {ccPairs.length > 0 && (
                                <>
                                  <Label small>Document Sets</Label>
                                  <div>
                                    <SubLabel>
                                      <>
                                        Select which{" "}
                                        {!user || user.role === "admin" ? (
                                          <Link
                                            href="/admin/documents/sets"
                                            className="text-blue-500"
                                            target="_blank"
                                          >
                                            Document Sets
                                          </Link>
                                        ) : (
                                          "Document Sets"
                                        )}{" "}
                                        that this Assistant should search
                                        through. If none are specified, the
                                        Assistant will search through all
                                        available documents in order to try and
                                        respond to queries.
                                      </>
                                    </SubLabel>
                                  </div>

                                  {documentSets.length > 0 ? (
                                    <FieldArray
                                      name="document_set_ids"
                                      render={(arrayHelpers: ArrayHelpers) => (
                                        <div>
                                          <div className="mb-3 mt-2 flex gap-2 flex-wrap text-sm">
                                            {documentSets.map((documentSet) => {
                                              const ind =
                                                values.document_set_ids.indexOf(
                                                  documentSet.id
                                                );
                                              let isSelected = ind !== -1;
                                              return (
                                                <DocumentSetSelectable
                                                  key={documentSet.id}
                                                  documentSet={documentSet}
                                                  isSelected={isSelected}
                                                  onSelect={() => {
                                                    if (isSelected) {
                                                      arrayHelpers.remove(ind);
                                                    } else {
                                                      arrayHelpers.push(
                                                        documentSet.id
                                                      );
                                                    }
                                                  }}
                                                />
                                              );
                                            })}
                                          </div>
                                        </div>
                                      )}
                                    />
                                  ) : (
                                    <Italic className="text-sm">
                                      No Document Sets available.{" "}
                                      {user?.role !== "admin" && (
                                        <>
                                          If this functionality would be useful,
                                          reach out to the administrators of
                                          Danswer for assistance.
                                        </>
                                      )}
                                    </Italic>
                                  )}

                                  <div className="mt-6">
                                    <TextFormField
                                      small={true}
                                      name="num_chunks"
                                      label="Number of Chunks"
                                      tooltip="How many chunks to feed the LLM"
                                      placeholder="Defaults to 10 chunks."
                                      onChange={(e) => {
                                        const value = e.target.value;
                                        if (
                                          value === "" ||
                                          /^[0-9]+$/.test(value)
                                        ) {
                                          setFieldValue("num_chunks", value);
                                        }
                                      }}
                                    />

                                    <BooleanFormField
                                      small
                                      noPadding
                                      alignTop
                                      name="llm_relevance_filter"
                                      label="Apply LLM Relevance Filter"
                                      subtext={
                                        "If enabled, the LLM will filter out chunks that are not relevant to the user query."
                                      }
                                    />

                                    <BooleanFormField
                                      small
                                      noPadding
                                      alignTop
                                      name="include_citations"
                                      label="Include Citations"
                                      subtext={`
                                      If set, the response will include bracket citations ([1], [2], etc.) 
                                      for each document used by the LLM to help inform the response. This is 
                                      the same technique used by the default Assistants. In general, we recommend 
                                      to leave this enabled in order to increase trust in the LLM answer.`}
                                    />
                                  </div>
                                </>
                              )}
                            </div>
                          </CollapsibleSection>
                        )}
                      </>
                    )}

                    {internetSearchTool && (
                      <BooleanFormField
                        noPadding
                        name={`enabled_tools_map.${internetSearchTool.id}`}
                        label={internetSearchTool.display_name}
                        onChange={() => {
                          toggleToolInValues(internetSearchTool.id);
                        }}
                      />
                    )}

                    {customTools.length > 0 && (
                      <>
                        {customTools.map((tool) => (
                          <BooleanFormField
                            noPadding
                            alignTop={tool.description != null}
                            key={tool.id}
                            name={`enabled_tools_map.${tool.id}`}
                            label={tool.name}
                            subtext={tool.description}
                            onChange={() => {
                              toggleToolInValues(tool.id);
                            }}
                          />
                        ))}
                      </>
                    )}
                  </div>

                  {llmProviders.length > 0 && (
                    <>
                      <Divider />

                      <TextFormField
                        name="task_prompt"
                        label="Additional instructions (Optional)"
                        isTextArea={true}
                        placeholder="e.g. 'Remember to reference all of the points mentioned in my message to you and focus on identifying action items that can move things forward'"
                        onChange={(e) => {
                          setFieldValue("task_prompt", e.target.value);
                          triggerFinalPromptUpdate(
                            values.system_prompt,
                            e.target.value,
                            searchToolEnabled()
                          );
                        }}
                        explanationText="Learn about prompting in our docs!"
                        explanationLink="https://docs.danswer.dev/guides/assistants"
                      />
                    </>
                  )}
                  <div className="mb-6">
                    <div className="flex gap-x-2 items-center">
                      <div className="block font-medium text-base">
                        Add Starter Messages (Optional){" "}
                      </div>
                    </div>
                    <FieldArray
                      name="starter_messages"
                      render={(
                        arrayHelpers: ArrayHelpers<StarterMessage[]>
                      ) => (
                        <div>
                          {values.starter_messages &&
                            values.starter_messages.length > 0 &&
                            values.starter_messages.map(
                              (
                                starterMessage: StarterMessage,
                                index: number
                              ) => {
                                return (
                                  <div
                                    key={index}
                                    className={index === 0 ? "mt-2" : "mt-6"}
                                  >
                                    <div className="flex">
                                      <div className="w-full mr-6 border border-border p-3 rounded">
                                        <div>
                                          <Label small>Name</Label>
                                          <SubLabel>
                                            Shows up as the &quot;title&quot;
                                            for this Starter Message. For
                                            example, &quot;Write an email&quot;.
                                          </SubLabel>
                                          <Field
                                            name={`starter_messages[${index}].name`}
                                            className={`
                                        border 
                                        border-border 
                                        bg-background 
                                        rounded 
                                        w-full 
                                        py-2 
                                        px-3 
                                        mr-4
                                      `}
                                            autoComplete="off"
                                          />
                                          <ErrorMessage
                                            name={`starter_messages[${index}].name`}
                                            component="div"
                                            className="text-error text-sm mt-1"
                                          />
                                        </div>

                                        <div className="mt-3">
                                          <Label small>Description</Label>
                                          <SubLabel>
                                            A description which tells the user
                                            what they might want to use this
                                            Starter Message for. For example
                                            &quot;to a client about a new
                                            feature&quot;
                                          </SubLabel>
                                          <Field
                                            name={`starter_messages.${index}.description`}
                                            className={`
                                        border 
                                        border-border 
                                        bg-background 
                                        rounded 
                                        w-full 
                                        py-2 
                                        px-3 
                                        mr-4
                                      `}
                                            autoComplete="off"
                                          />
                                          <ErrorMessage
                                            name={`starter_messages[${index}].description`}
                                            component="div"
                                            className="text-error text-sm mt-1"
                                          />
                                        </div>

                                        <div className="mt-3">
                                          <Label small>Message</Label>
                                          <SubLabel>
                                            The actual message to be sent as the
                                            initial user message if a user
                                            selects this starter prompt. For
                                            example, &quot;Write me an email to
                                            a client about a new billing feature
                                            we just released.&quot;
                                          </SubLabel>
                                          <Field
                                            name={`starter_messages[${index}].message`}
                                            className={`
                                          border 
                                          border-border 
                                          bg-background 
                                          rounded 
                                          w-full 
                                          py-2 
                                          px-3 
                                          mr-4
                                      `}
                                            as="textarea"
                                            autoComplete="off"
                                          />
                                          <ErrorMessage
                                            name={`starter_messages[${index}].message`}
                                            component="div"
                                            className="text-error text-sm mt-1"
                                          />
                                        </div>
                                      </div>
                                      <div className="my-auto">
                                        <FiX
                                          className="my-auto w-10 h-10 cursor-pointer hover:bg-hover rounded p-2"
                                          onClick={() =>
                                            arrayHelpers.remove(index)
                                          }
                                        />
                                      </div>
                                    </div>
                                  </div>
                                );
                              }
                            )}

                          <Button
                            onClick={() => {
                              arrayHelpers.push({
                                name: "",
                                description: "",
                                message: "",
                              });
                            }}
                            className="mt-3"
                            color="green"
                            size="xs"
                            type="button"
                            icon={FiPlus}
                          >
                            Add New
                          </Button>
                        </div>
                      )}
                    />
                  </div>

                  {isPaidEnterpriseFeaturesEnabled &&
                    userGroups &&
                    userGroups.length > 0 && (
                      <IsPublicGroupSelector
                        formikProps={{
                          values,
                          isSubmitting,
                          setFieldValue,
                          ...formikProps,
                        }}
                        objectName="assistant"
                        enforceGroupSelection={false}
                      />
                    )}

                  <div className="flex">
                    <Button
                      className="mx-auto"
                      color="green"
                      size="md"
                      type="submit"
                      disabled={isSubmitting || isRequestSuccessful}
                    >
                      {isUpdate ? "Update!" : "Create!"}
                    </Button>
                  </div>
                </div>
              </div>
            </Form>
          );
        }}
      </Formik>
    </div>
  );
}
