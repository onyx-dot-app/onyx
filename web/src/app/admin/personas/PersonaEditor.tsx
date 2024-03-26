"use client";

import { DocumentSet, UserGroup } from "@/lib/types";
import { Button, Divider, Text } from "@tremor/react";
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

function Label({ children }: { children: string | JSX.Element }) {
  return (
    <div className="block font-medium text-base text-emphasis">{children}</div>
  );
}

function SubLabel({ children }: { children: string | JSX.Element }) {
  return <div className="text-sm text-subtle mb-2">{children}</div>;
}

export function PersonaEditor({
  existingPersona,
  documentSets,
  llmOverrideOptions,
  defaultLLM,
}: {
  existingPersona?: Persona | null;
  documentSets: DocumentSet[];
  llmOverrideOptions: string[];
  defaultLLM: string;
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
          disable_retrieval: (existingPersona?.num_chunks ?? 10) === 0,
          is_public: existingPersona?.is_public ?? true,
          document_set_ids:
            existingPersona?.document_sets?.map(
              (documentSet) => documentSet.id
            ) ?? ([] as number[]),
          num_chunks: existingPersona?.num_chunks ?? null,
          include_citations:
            existingPersona?.prompts[0]?.include_citations ?? true,
          llm_relevance_filter: existingPersona?.llm_relevance_filter ?? false,
          llm_model_version_override:
            existingPersona?.llm_model_version_override ?? null,
          starter_messages: existingPersona?.starter_messages ?? [],
          // EE Only
          groups: existingPersona?.groups ?? [],
        }}
        validationSchema={Yup.object()
          .shape({
            name: Yup.string().required("Must give the Persona a name!"),
            description: Yup.string().required(
              "Must give the Persona a description!"
            ),
            system_prompt: Yup.string(),
            task_prompt: Yup.string(),
            disable_retrieval: Yup.boolean().required(),
            is_public: Yup.boolean().required(),
            document_set_ids: Yup.array().of(Yup.number()),
            num_chunks: Yup.number().max(20).nullable(),
            include_citations: Yup.boolean().required(),
            llm_relevance_filter: Yup.boolean().required(),
            llm_model_version_override: Yup.string().nullable(),
            starter_messages: Yup.array().of(
              Yup.object().shape({
                name: Yup.string().required(),
                description: Yup.string().required(),
                message: Yup.string().required(),
              })
            ),
            // EE Only
            groups: Yup.array().of(Yup.number()),
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

          formikHelpers.setSubmitting(true);

          // if disable_retrieval is set, set num_chunks to 0
          // to tell the backend to not fetch any documents
          const numChunks = values.disable_retrieval
            ? 0
            : values.num_chunks || 10;

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
              groups,
            });
          } else {
            [promptResponse, personaResponse] = await createPersona({
              ...values,
              num_chunks: numChunks,
              groups,
            });
          }

          let error = null;
          if (!promptResponse.ok) {
            error = await promptResponse.text();
          }
          if (personaResponse && !personaResponse.ok) {
            error = await personaResponse.text();
          }

          if (error) {
            setPopup({
              type: "error",
              message: `Failed to create Persona - ${error}`,
            });
            formikHelpers.setSubmitting(false);
          } else {
            router.push(`/admin/personas?u=${Date.now()}`);
          }
        }}
      >
        {({ isSubmitting, values, setFieldValue }) => (
          <Form>
            <div className="pb-6">
              <HidableSection sectionTitle="Who am I?">
                <>
                  <TextFormField
                    name="name"
                    label="Name"
                    disabled={isUpdate}
                    subtext="Users will be able to select this Persona based on this name."
                  />

                  <TextFormField
                    name="description"
                    label="Description"
                    subtext="Provide a short descriptions which gives users a hint as to what they should use this Persona for."
                  />
                </>
              </HidableSection>

              <Divider />

              <HidableSection sectionTitle="Customize my response style">
                <>
                  <TextFormField
                    name="system_prompt"
                    label="System Prompt"
                    isTextArea={true}
                    subtext={
                      'Give general info about what the Persona is about. For example, "You are an assistant for On-Call engineers. Your goal is to read the provided context documents and give recommendations as to how to resolve the issue."'
                    }
                    onChange={(e) => {
                      setFieldValue("system_prompt", e.target.value);
                      triggerFinalPromptUpdate(
                        e.target.value,
                        values.task_prompt,
                        values.disable_retrieval
                      );
                    }}
                    error={finalPromptError}
                  />

                  <TextFormField
                    name="task_prompt"
                    label="Task Prompt"
                    isTextArea={true}
                    subtext={
                      'Give specific instructions as to what to do with the user query. For example, "Find any relevant sections from the provided documents that can help the user resolve their issue and explain how they are relevant."'
                    }
                    onChange={(e) => {
                      setFieldValue("task_prompt", e.target.value);
                      triggerFinalPromptUpdate(
                        values.system_prompt,
                        e.target.value,
                        values.disable_retrieval
                      );
                    }}
                    error={finalPromptError}
                  />

                  {!values.disable_retrieval && (
                    <BooleanFormField
                      name="include_citations"
                      label="Include Citations"
                      subtext={`
                        If set, the response will include bracket citations ([1], [2], etc.) 
                        for each document used by the LLM to help inform the response. This is 
                        the same technique used by the default Personas. In general, we recommend 
                        to leave this enabled in order to increase trust in the LLM answer.`}
                    />
                  )}

                  <BooleanFormField
                    name="disable_retrieval"
                    label="Disable Retrieval"
                    subtext={`
                      If set, the Persona will not fetch any context documents to aid in the response. 
                      Instead, it will only use the supplied system and task prompts plus the user 
                      query in order to generate a response`}
                    onChange={(e) => {
                      setFieldValue("disable_retrieval", e.target.checked);
                      triggerFinalPromptUpdate(
                        values.system_prompt,
                        values.task_prompt,
                        e.target.checked
                      );
                    }}
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

              {!values.disable_retrieval && (
                <>
                  <HidableSection sectionTitle="What data should I have access to?">
                    <>
                      <FieldArray
                        name="document_set_ids"
                        render={(arrayHelpers: ArrayHelpers) => (
                          <div>
                            <div>
                              <SubLabel>
                                <>
                                  Select which{" "}
                                  <Link
                                    href="/admin/documents/sets"
                                    className="text-blue-500"
                                    target="_blank"
                                  >
                                    Document Sets
                                  </Link>{" "}
                                  that this Persona should search through. If
                                  none are specified, the Persona will search
                                  through all available documents in order to
                                  try and response to queries.
                                </>
                              </SubLabel>
                            </div>
                            <div className="mb-3 mt-2 flex gap-2 flex-wrap text-sm">
                              {documentSets.map((documentSet) => {
                                const ind = values.document_set_ids.indexOf(
                                  documentSet.id
                                );
                                let isSelected = ind !== -1;
                                return (
                                  <div
                                    key={documentSet.id}
                                    className={
                                      `
                                      px-3 
                                      py-1
                                      rounded-lg 
                                      border
                                      border-border
                                      w-fit 
                                      flex 
                                      cursor-pointer ` +
                                      (isSelected
                                        ? " bg-hover"
                                        : " bg-background hover:bg-hover-light")
                                    }
                                    onClick={() => {
                                      if (isSelected) {
                                        arrayHelpers.remove(ind);
                                      } else {
                                        arrayHelpers.push(documentSet.id);
                                      }
                                    }}
                                  >
                                    <div className="my-auto">
                                      {documentSet.name}
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      />
                    </>
                  </HidableSection>

                  <Divider />
                </>
              )}

              {EE_ENABLED && userGroups && (
                <>
                  <HidableSection sectionTitle="Which groups should have access to this Persona?">
                    <>
                      <BooleanFormField
                        name="is_public"
                        label="Is Public?"
                        subtext="If set, this Persona will be available to all users. If not, only the specified User Groups will be able to access it."
                      />

                      {userGroups &&
                        userGroups.length > 0 &&
                        !values.is_public && (
                          <div>
                            <Text>
                              Select which User Groups should have access to
                              this Persona.
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

              {llmOverrideOptions.length > 0 && defaultLLM && (
                <>
                  <HidableSection sectionTitle="[Advanced] Model Selection">
                    <>
                      <Text>
                        Pick which LLM to use for this Persona. If left as
                        Default, will use <b className="italic">{defaultLLM}</b>
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

                      <div className="w-96">
                        <SelectorFormField
                          name="llm_model_version_override"
                          options={llmOverrideOptions.map((llmOption) => {
                            return {
                              name: llmOption,
                              value: llmOption,
                            };
                          })}
                          includeDefault={true}
                        />
                      </div>
                    </>
                  </HidableSection>

                  <Divider />
                </>
              )}

              {!values.disable_retrieval && (
                <>
                  <HidableSection sectionTitle="[Advanced] Retrieval Customization">
                    <>
                      <TextFormField
                        name="num_chunks"
                        label="Number of Chunks"
                        subtext={
                          <div>
                            How many chunks should we feed into the LLM when
                            generating the final response? Each chunk is ~400
                            words long. If you are using gpt-3.5-turbo or other
                            similar models, setting this to a value greater than
                            5 will result in errors at query time due to the
                            model&apos;s input length limit.
                            <br />
                            <br />
                            If unspecified, will use 10 chunks.
                          </div>
                        }
                        onChange={(e) => {
                          const value = e.target.value;
                          // Allow only integer values
                          if (value === "" || /^[0-9]+$/.test(value)) {
                            setFieldValue("num_chunks", value);
                          }
                        }}
                      />

                      <BooleanFormField
                        name="llm_relevance_filter"
                        label="Apply LLM Relevance Filter"
                        subtext={
                          "If enabled, the LLM will filter out chunks that are not relevant to the user query."
                        }
                      />
                    </>
                  </HidableSection>

                  <Divider />
                </>
              )}

              <HidableSection sectionTitle="[Advanced] Starter Messages">
                <>
                  <div className="mb-4">
                    <SubLabel>
                      Starter Messages help guide users to use this Persona.
                      They are shown to the user as clickable options when they
                      select this Persona. When selected, the specified message
                      is sent to the LLM as the initial user message.
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
