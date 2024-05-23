"use client";

import { CCPairBasicInfo, DocumentSet, User, UserGroup } from "@/lib/types";
import { Button, Divider, Italic, Text } from "@tremor/react";
import {
  ArrayHelpers,
  ErrorMessage,
  Field,
  FieldArray,
  Form,
  Formik,
} from "formik";

import * as Yup from "yup";
import { buildFinalPrompt, createPersona, updatePersona } from "./lib";
import { useRouter } from "next/navigation";
import { usePopup } from "@/components/admin/connectors/Popup";
import { Persona, StarterMessage } from "./interfaces";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  BooleanFormField,
  SelectorFormField,
  TextFormField,
} from "@/components/admin/connectors/Field";
import { HidableSection } from "./HidableSection";
import { FiPlus, FiX } from "react-icons/fi";
import { EE_ENABLED } from "@/lib/constants";
import { useUserGroups } from "@/lib/hooks";
import { Bubble } from "@/components/Bubble";
import { GroupsIcon } from "@/components/icons/icons";
import { SuccessfulPersonaUpdateRedirectType } from "./enums";
import { DocumentSetSelectable } from "@/components/documentSet/DocumentSetSelectable";
import { FullLLMProvider } from "../models/llm/interfaces";
import { Option } from "@/components/Dropdown";
import { ToolSnapshot } from "@/lib/tools/interfaces";

function findSearchTool(tools: ToolSnapshot[]) {
  return tools.find((tool) => tool.in_code_tool_id === "SearchTool");
}

function findImageGenerationTool(tools: ToolSnapshot[]) {
  return tools.find((tool) => tool.in_code_tool_id === "ImageGenerationTool");
}

function checkLLMSupportsImageGeneration(provider: string, model: string) {
  console.log(provider);
  console.log(model);
  return provider === "openai" && model === "gpt-4-turbo";
}

function Label({ children }: { children: string | JSX.Element }) {
  return (
    <div className="block font-medium text-base text-emphasis">{children}</div>
  );
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
}: {
  existingPersona?: Persona | null;
  ccPairs: CCPairBasicInfo[];
  documentSets: DocumentSet[];
  user: User | null;
  defaultPublic: boolean;
  redirectType: SuccessfulPersonaUpdateRedirectType;
  llmProviders: FullLLMProvider[];
  tools: ToolSnapshot[];
}) {
  const router = useRouter();
  const { popup, setPopup } = usePopup();

  // EE only
  const { data: userGroups, isLoading: userGroupsIsLoading } = useUserGroups();

  const [finalPrompt, setFinalPrompt] = useState<string | null>("");
  const [finalPromptError, setFinalPromptError] = useState<string>("");

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
        name: modelName,
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

  return (
    <div>
      {popup}
      <Formik
        enableReinitialize={true}
        initialValues={{
          name: existingPersona?.name ?? "",
          description: existingPersona?.description ?? "",
          system_prompt: existingPrompt?.system_prompt ?? "",
          task_prompt: existingPrompt?.task_prompt ?? "",
          is_public: existingPersona?.is_public ?? defaultPublic,
          document_set_ids:
            existingPersona?.document_sets?.map(
              (documentSet) => documentSet.id
            ) ?? ([] as number[]),
          num_chunks: existingPersona?.num_chunks ?? null,
          include_citations:
            existingPersona?.prompts[0]?.include_citations ?? true,
          llm_relevance_filter: existingPersona?.llm_relevance_filter ?? false,
          llm_model_provider_override:
            existingPersona?.llm_model_provider_override ?? null,
          llm_model_version_override:
            existingPersona?.llm_model_version_override ?? null,
          starter_messages: existingPersona?.starter_messages ?? [],
          // EE Only
          groups: existingPersona?.groups ?? [],
          search_tool_enabled: existingPersona
            ? personaCurrentToolIds.includes(searchTool!.id)
            : ccPairs.length > 0,
          image_generation_tool_enabled: imageGenerationTool
            ? personaCurrentToolIds.includes(imageGenerationTool.id)
            : false,
        }}
        validationSchema={Yup.object()
          .shape({
            name: Yup.string().required("Must give the Assistant a name!"),
            description: Yup.string().required(
              "Must give the Assistant a description!"
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
            // EE Only
            groups: Yup.array().of(Yup.number()),
            search_tool_enabled: Yup.boolean().required(),
            image_generation_tool_enabled: Yup.boolean().required(),
          })
          .test(
            "system-prompt-or-task-prompt",
            "Must provide at least one of System Prompt or Task Prompt",
            (values) => {
              const systemPromptSpecified = values.system_prompt
                ? values.system_prompt.length > 0
                : false;
              const taskPromptSpecified = values.task_prompt
                ? values.task_prompt.length > 0
                : false;
              if (systemPromptSpecified || taskPromptSpecified) {
                setFinalPromptError("");
                return true;
              } // Return true if at least one field has a value

              setFinalPromptError(
                "Must provide at least one of System Prompt or Task Prompt"
              );
            }
          )}
        onSubmit={async (values, formikHelpers) => {
          if (finalPromptError) {
            setPopup({
              type: "error",
              message: "Cannot submit while there are errors in the form!",
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

          const tools = [];
          if (values.search_tool_enabled && ccPairs.length > 0) {
            tools.push(searchTool!.id);
          }
          if (
            values.image_generation_tool_enabled &&
            imageGenerationTool &&
            checkLLMSupportsImageGeneration(
              providerDisplayNameToProviderName.get(
                values.llm_model_provider_override || ""
              ) ||
                defaultProviderName ||
                "",
              values.llm_model_version_override || defaultModelName || ""
            )
          ) {
            tools.push(imageGenerationTool.id);
          }

          // if disable_retrieval is set, set num_chunks to 0
          // to tell the backend to not fetch any documents
          const numChunks = values.search_tool_enabled
            ? values.num_chunks || 10
            : 0;

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
              users: user ? [user.id] : undefined,
              groups,
              tool_ids: tools,
            });
          } else {
            [promptResponse, personaResponse] = await createPersona({
              ...values,
              num_chunks: numChunks,
              users: user ? [user.id] : undefined,
              groups,
              tool_ids: tools,
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
            router.push(
              redirectType === SuccessfulPersonaUpdateRedirectType.ADMIN
                ? `/admin/assistants?u=${Date.now()}`
                : `/chat?assistantId=${
                    ((await personaResponse.json()) as Persona).id
                  }`
            );
          }
        }}
      >
        {({ isSubmitting, values, setFieldValue }) => (
          <Form>
            <div className="pb-6">
              <HidableSection sectionTitle="Basics">
                <>
                  <TextFormField
                    name="name"
                    label="Name"
                    disabled={isUpdate}
                    subtext="Users will be able to select this Assistant based on this name."
                  />

                  <TextFormField
                    name="description"
                    label="Description"
                    subtext="Provide a short descriptions which gives users a hint as to what they should use this Assistant for."
                  />

                  <TextFormField
                    name="system_prompt"
                    label="System Prompt"
                    isTextArea={true}
                    subtext={
                      'Give general info about what the Assistant is about. For example, "You are an assistant for On-Call engineers. Your goal is to read the provided context documents and give recommendations as to how to resolve the issue."'
                    }
                    onChange={(e) => {
                      setFieldValue("system_prompt", e.target.value);
                      triggerFinalPromptUpdate(
                        e.target.value,
                        values.task_prompt,
                        values.search_tool_enabled
                      );
                    }}
                    error={finalPromptError}
                  />

                  <TextFormField
                    name="task_prompt"
                    label="Task Prompt (Optional)"
                    isTextArea={true}
                    subtext={`Give specific instructions as to what to do with the user query. 
                      For example, "Find any relevant sections from the provided documents that can 
                      help the user resolve their issue and explain how they are relevant."`}
                    onChange={(e) => {
                      setFieldValue("task_prompt", e.target.value);
                      triggerFinalPromptUpdate(
                        values.system_prompt,
                        e.target.value,
                        values.search_tool_enabled
                      );
                    }}
                    error={finalPromptError}
                  />

                  <Label>Final Prompt</Label>

                  {finalPrompt ? (
                    <pre className="text-sm mt-2 whitespace-pre-wrap">
                      {finalPrompt}
                    </pre>
                  ) : (
                    "-"
                  )}
                </>
              </HidableSection>

              <Divider />

              <HidableSection sectionTitle="Tools">
                <>
                  {ccPairs.length > 0 && (
                    <>
                      <BooleanFormField
                        name="search_tool_enabled"
                        label="Search Tool"
                        subtext={`The Search Tool allows the Assistant to search through connected knowledge to help build an answer.`}
                        onChange={(e) => {
                          setFieldValue("num_chunks", null);
                          setFieldValue(
                            "search_tool_enabled",
                            e.target.checked
                          );
                        }}
                      />

                      {values.search_tool_enabled && (
                        <div className="pl-4 border-l-2 ml-4 border-border">
                          {ccPairs.length > 0 && (
                            <>
                              <Label>Document Sets</Label>

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
                                    that this Assistant should search through.
                                    If none are specified, the Assistant will
                                    search through all available documents in
                                    order to try and respond to queries.
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
                                      reach out to the administrators of Danswer
                                      for assistance.
                                    </>
                                  )}
                                </Italic>
                              )}

                              <>
                                <TextFormField
                                  name="num_chunks"
                                  label="Number of Chunks"
                                  placeholder="If unspecified, will use 10 chunks."
                                  subtext={
                                    <div>
                                      How many chunks should we feed into the
                                      LLM when generating the final response?
                                      Each chunk is ~400 words long.
                                    </div>
                                  }
                                  onChange={(e) => {
                                    const value = e.target.value;
                                    // Allow only integer values
                                    if (
                                      value === "" ||
                                      /^[0-9]+$/.test(value)
                                    ) {
                                      setFieldValue("num_chunks", value);
                                    }
                                  }}
                                />

                                <Label>Misc</Label>

                                <BooleanFormField
                                  name="llm_relevance_filter"
                                  label="Apply LLM Relevance Filter"
                                  subtext={
                                    "If enabled, the LLM will filter out chunks that are not relevant to the user query."
                                  }
                                />

                                <BooleanFormField
                                  name="include_citations"
                                  label="Include Citations"
                                  subtext={`
                                If set, the response will include bracket citations ([1], [2], etc.) 
                                for each document used by the LLM to help inform the response. This is 
                                the same technique used by the default Assistants. In general, we recommend 
                                to leave this enabled in order to increase trust in the LLM answer.`}
                                />
                              </>
                            </>
                          )}
                        </div>
                      )}
                    </>
                  )}

                  {imageGenerationTool &&
                    checkLLMSupportsImageGeneration(
                      providerDisplayNameToProviderName.get(
                        values.llm_model_provider_override || ""
                      ) ||
                        defaultProviderName ||
                        "",
                      values.llm_model_version_override ||
                        defaultModelName ||
                        ""
                    ) && (
                      <BooleanFormField
                        name="image_generation_tool_enabled"
                        label="Image Generation Tool"
                        subtext="The Image Generation Tool allows the assistant to use DALL-E 3 to generate images. The tool will be used when the user asks the assistant to generate an image."
                        onChange={(e) => {
                          setFieldValue(
                            "image_generation_tool_enabled",
                            e.target.checked
                          );
                        }}
                      />
                    )}
                </>
              </HidableSection>

              <Divider />

              {llmProviders.length > 0 && (
                <>
                  <HidableSection
                    sectionTitle="[Advanced] Model Selection"
                    defaultHidden
                  >
                    <>
                      <Text>
                        Pick which LLM to use for this Assistant. If left as
                        Default, will use{" "}
                        <b className="italic">{defaultModelName}</b>
                        .
                        <br />
                        <br />
                        For more information on the different LLMs, checkout the{" "}
                        <a
                          href="https://platform.openai.com/docs/models"
                          target="_blank"
                          className="text-blue-500"
                        >
                          OpenAI docs
                        </a>
                        .
                      </Text>

                      <div className="flex mt-6">
                        <div className="w-96">
                          <SubLabel>LLM Provider</SubLabel>
                          <SelectorFormField
                            name="llm_model_provider_override"
                            options={llmProviders.map((llmProvider) => ({
                              name: llmProvider.name,
                              value: llmProvider.name,
                            }))}
                            includeDefault={true}
                            onSelect={(selected) => {
                              if (
                                selected !== values.llm_model_provider_override
                              ) {
                                setFieldValue(
                                  "llm_model_version_override",
                                  null
                                );
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
                            <SubLabel>Model</SubLabel>
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
                    </>
                  </HidableSection>

                  <Divider />
                </>
              )}

              <HidableSection
                sectionTitle="[Advanced] Starter Messages"
                defaultHidden
              >
                <>
                  <div className="mb-4">
                    <SubLabel>
                      Starter Messages help guide users to use this Assistant.
                      They are shown to the user as clickable options when they
                      select this Assistant. When selected, the specified
                      message is sent to the LLM as the initial user message.
                    </SubLabel>
                  </div>

                  <FieldArray
                    name="starter_messages"
                    render={(arrayHelpers: ArrayHelpers<StarterMessage[]>) => (
                      <div>
                        {values.starter_messages &&
                          values.starter_messages.length > 0 &&
                          values.starter_messages.map((_, index) => {
                            return (
                              <div
                                key={index}
                                className={index === 0 ? "mt-2" : "mt-6"}
                              >
                                <div className="flex">
                                  <div className="w-full mr-6 border border-border p-3 rounded">
                                    <div>
                                      <Label>Name</Label>
                                      <SubLabel>
                                        Shows up as the &quot;title&quot; for
                                        this Starter Message. For example,
                                        &quot;Write an email&quot;.
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
                                      <Label>Description</Label>
                                      <SubLabel>
                                        A description which tells the user what
                                        they might want to use this Starter
                                        Message for. For example &quot;to a
                                        client about a new feature&quot;
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
                                      <Label>Message</Label>
                                      <SubLabel>
                                        The actual message to be sent as the
                                        initial user message if a user selects
                                        this starter prompt. For example,
                                        &quot;Write me an email to a client
                                        about a new billing feature we just
                                        released.&quot;
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
                                      onClick={() => arrayHelpers.remove(index)}
                                    />
                                  </div>
                                </div>
                              </div>
                            );
                          })}

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
                </>
              </HidableSection>

              <Divider />

              {EE_ENABLED && userGroups && (!user || user.role === "admin") && (
                <>
                  <HidableSection sectionTitle="Access">
                    <>
                      <BooleanFormField
                        name="is_public"
                        label="Is Public?"
                        subtext="If set, this Assistant will be available to all users. If not, only the specified User Groups will be able to access it."
                      />

                      {userGroups &&
                        userGroups.length > 0 &&
                        !values.is_public && (
                          <div>
                            <Text>
                              Select which User Groups should have access to
                              this Assistant.
                            </Text>
                            <div className="flex flex-wrap gap-2 mt-2">
                              {userGroups.map((userGroup) => {
                                const isSelected = values.groups.includes(
                                  userGroup.id
                                );
                                return (
                                  <Bubble
                                    key={userGroup.id}
                                    isSelected={isSelected}
                                    onClick={() => {
                                      if (isSelected) {
                                        setFieldValue(
                                          "groups",
                                          values.groups.filter(
                                            (id) => id !== userGroup.id
                                          )
                                        );
                                      } else {
                                        setFieldValue("groups", [
                                          ...values.groups,
                                          userGroup.id,
                                        ]);
                                      }
                                    }}
                                  >
                                    <div className="flex">
                                      <GroupsIcon />
                                      <div className="ml-1">
                                        {userGroup.name}
                                      </div>
                                    </div>
                                  </Bubble>
                                );
                              })}
                            </div>
                          </div>
                        )}
                    </>
                  </HidableSection>
                  <Divider />
                </>
              )}

              <div className="flex">
                <Button
                  className="mx-auto"
                  color="green"
                  size="md"
                  type="submit"
                  disabled={isSubmitting}
                >
                  {isUpdate ? "Update!" : "Create!"}
                </Button>
              </div>
            </div>
          </Form>
        )}
      </Formik>
    </div>
  );
}
