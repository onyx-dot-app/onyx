"use client";

import { ArrayHelpers, FieldArray, Form, Formik } from "formik";
import * as Yup from "yup";
import { usePopup } from "@/components/admin/connectors/Popup";
import { DocumentSet, SlackBotConfig } from "@/lib/types";
import {
  BooleanFormField,
  SectionHeader,
  SelectorFormField,
  SubLabel,
  TextArrayField,
  TextFormField,
} from "@/components/admin/connectors/Field";
import {
  createSlackBotConfig,
  isPersonaASlackBotPersona,
  updateSlackBotConfig,
} from "./lib";
import {
  Button,
  Card,
  Divider,
  Tab,
  TabGroup,
  TabList,
  TabPanel,
  TabPanels,
  Text,
} from "@tremor/react";
import { useRouter } from "next/navigation";
import { Persona } from "../assistants/interfaces";
import { useState } from "react";
import { BookmarkIcon, RobotIcon } from "@/components/icons/icons";
import { SourceIcon } from "@/components/SourceIcon";
import { getSourceMetadata } from "@/lib/sources";

export const SlackBotCreationForm = ({
  documentSets,
  personas,
  existingSlackBotConfig,
}: {
  documentSets: DocumentSet[];
  personas: Persona[];
  existingSlackBotConfig?: SlackBotConfig;
}) => {
  const isUpdate = existingSlackBotConfig !== undefined;
  const { popup, setPopup } = usePopup();
  const router = useRouter();

  const existingSlackBotUsesPersona = existingSlackBotConfig?.persona
    ? !isPersonaASlackBotPersona(existingSlackBotConfig.persona)
    : false;
  const [usingPersonas, setUsingPersonas] = useState(
    existingSlackBotUsesPersona
  );

  // Get unique sources from document sets
  const availableSources = Array.from(
    new Set(
      documentSets.flatMap((docSet) =>
        docSet.cc_pair_descriptors.map((desc) => desc.connector.source)
      )
    )
  );

  return (
    <div>
      <Card>
        {popup}
        <Formik
          initialValues={{
            channel_names: existingSlackBotConfig
              ? existingSlackBotConfig.channel_config.channel_names
              : ([] as string[]),
            answer_validity_check_enabled: (
              existingSlackBotConfig?.channel_config?.answer_filters || []
            ).includes("well_answered_postfilter"),
            questionmark_prefilter_enabled: (
              existingSlackBotConfig?.channel_config?.answer_filters || []
            ).includes("questionmark_prefilter"),
            respond_tag_only:
              existingSlackBotConfig?.channel_config?.respond_tag_only || false,
            respond_to_bots:
              existingSlackBotConfig?.channel_config?.respond_to_bots || false,
            respond_member_group_list: (
              existingSlackBotConfig?.channel_config
                ?.respond_team_member_list ?? []
            ).concat(
              existingSlackBotConfig?.channel_config
                ?.respond_slack_group_list ?? []
            ),
            still_need_help_enabled:
              existingSlackBotConfig?.channel_config?.follow_up_tags !==
              undefined,
            follow_up_tags:
              existingSlackBotConfig?.channel_config?.follow_up_tags,
            opsgenie_schedule:
              existingSlackBotConfig?.channel_config?.opsgenie_schedule || "",
            document_sets:
              existingSlackBotConfig && existingSlackBotConfig.persona
                ? existingSlackBotConfig.persona.document_sets.map(
                    (documentSet) => documentSet.id
                  )
                : ([] as number[]),
            persona_id:
              existingSlackBotConfig?.persona &&
              !isPersonaASlackBotPersona(existingSlackBotConfig.persona)
                ? existingSlackBotConfig.persona.id
                : null,
            response_type: existingSlackBotConfig?.response_type || "citations",
            prioritized_sources:
              existingSlackBotConfig?.channel_config?.prioritized_sources || [],
            jira_config: existingSlackBotConfig?.channel_config
              ?.jira_config || {
              enable_jira_integration: false,
              project_key: "",
              issue_type: "",
              component: "",
            },
            jira_title_filter:
              existingSlackBotConfig?.channel_config?.jira_title_filter || [],
          }}
          validationSchema={Yup.object().shape({
            channel_names: Yup.array().of(Yup.string()),
            response_type: Yup.string()
              .oneOf(["quotes", "citations"])
              .required(),
            answer_validity_check_enabled: Yup.boolean().required(),
            questionmark_prefilter_enabled: Yup.boolean().required(),
            respond_tag_only: Yup.boolean().required(),
            respond_to_bots: Yup.boolean().required(),
            respond_member_group_list: Yup.array().of(Yup.string()).required(),
            still_need_help_enabled: Yup.boolean().required(),
            follow_up_tags: Yup.array().of(Yup.string()),
            opsgenie_schedule: Yup.string(),
            document_sets: Yup.array().of(Yup.number()),
            persona_id: Yup.number().nullable(),
            prioritized_sources: Yup.array().of(Yup.string()),
            jira_config: Yup.object().shape({
              enable_jira_integration: Yup.boolean().required(),
              project_key: Yup.string().when("enable_jira_integration", {
                is: true,
                then: (schema) =>
                  schema.required(
                    "Project key is required when JIRA integration is enabled"
                  ),
                otherwise: (schema) => schema.notRequired(),
              }),
              issue_type: Yup.string().when("enable_jira_integration", {
                is: true,
                then: (schema) =>
                  schema.required(
                    "Issue type is required when JIRA integration is enabled"
                  ),
                otherwise: (schema) => schema.notRequired(),
              }),
              component: Yup.string().notRequired(),
            }),
            jira_title_filter: Yup.array()
              .of(Yup.string().required("Title filter cannot be empty"))
              .when(["jira_config.enable_jira_integration"], {
                is: (enableJira: boolean) => enableJira,
                then: (schema) =>
                  schema
                    .min(
                      1,
                      "At least one title filter is required when JIRA integration is enabled"
                    )
                    .test(
                      "non-empty-strings",
                      "Title filters cannot be empty",
                      (value) => {
                        if (!value || !Array.isArray(value)) return false;
                        return value.every(
                          (title) =>
                            title &&
                            typeof title === "string" &&
                            title.trim().length > 0
                        );
                      }
                    ),
                otherwise: (schema) => schema.notRequired(),
              }),
          })}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            // remove empty channel names
            const cleanedValues = {
              ...values,
              channel_names: values.channel_names.filter(
                (channelName) => channelName !== ""
              ),
              respond_team_member_list: values.respond_member_group_list.filter(
                (teamMemberEmail) =>
                  /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(teamMemberEmail)
              ),
              respond_slack_group_list: values.respond_member_group_list.filter(
                (slackGroupName) =>
                  !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(slackGroupName)
              ),
              usePersona: usingPersonas,
              opsgenie_schedule: values.opsgenie_schedule || undefined,
              jira_config: {
                enable_jira_integration:
                  values.jira_config.enable_jira_integration ?? false,
                project_key: values.jira_config.project_key ?? "",
                issue_type: values.jira_config.issue_type ?? "",
                component: values.jira_config.component?.trim() || undefined,
              },
              jira_title_filter: values.jira_title_filter ?? [],
            };
            if (!cleanedValues.still_need_help_enabled) {
              cleanedValues.follow_up_tags = undefined;
            } else {
              if (!cleanedValues.follow_up_tags) {
                cleanedValues.follow_up_tags = [];
              }
            }

            let response;
            if (isUpdate) {
              response = await updateSlackBotConfig(
                existingSlackBotConfig.id,
                cleanedValues
              );
            } else {
              response = await createSlackBotConfig(cleanedValues);
            }
            formikHelpers.setSubmitting(false);
            if (response.ok) {
              router.push(`/admin/bot?u=${Date.now()}`);
            } else {
              const responseJson = await response.json();
              const errorMsg = responseJson.detail || responseJson.message;
              setPopup({
                message: isUpdate
                  ? `Error updating Darwin config - ${errorMsg}`
                  : `Error creating Darwin config - ${errorMsg}`,
                type: "error",
              });
            }
          }}
        >
          {({ isSubmitting, values, setFieldValue }) => (
            <Form>
              <div className="px-6 pb-6">
                <SectionHeader>The Basics</SectionHeader>

                <TextArrayField
                  name="channel_names"
                  label="Channel Names"
                  values={values}
                  subtext={
                    <div>
                      The names of the Slack channels you want this
                      configuration to apply to. For example,
                      &apos;#darwin-feedback&apos;.
                      <br />
                      <br />
                      <i>NOTE</i>: you still need to add Darwin to the
                      channel(s) in Slack itself. Setting this config will not
                      auto-add the bot to the channel.
                    </div>
                  }
                />

                <TextFormField
                  name="opsgenie_schedule"
                  label="OpsGenie Schedule"
                  subtext="The name of the OpsGenie schedule to use for getting the DRI on call when someone requests more help"
                />

                <SelectorFormField
                  name="response_type"
                  label="Response Format"
                  subtext={
                    <>
                      If set to Citations, Darwin will respond with a direct
                      answer with inline citations. It will also provide links
                      to these cited documents below the answer. When in doubt,
                      choose this option.
                      <br />
                      <br />
                      If set to Quotes, Darwin will respond with a direct answer
                      as well as with quotes pulled from the context documents
                      to support that answer. Darwin will also give a list of
                      relevant documents. Choose this option if you want a very
                      detailed response AND/OR a list of relevant documents
                      would be useful just in case the LLM missed anything.
                    </>
                  }
                  options={[
                    { name: "Citations", value: "citations" },
                    { name: "Quotes", value: "quotes" },
                  ]}
                />

                <Divider />

                <SectionHeader>When should Darwin respond?</SectionHeader>

                <BooleanFormField
                  name="answer_validity_check_enabled"
                  label="Hide Non-Answers"
                  subtext="If set, will only answer questions that the model determines it can answer"
                />
                <BooleanFormField
                  name="questionmark_prefilter_enabled"
                  label="Only respond to questions"
                  subtext="If set, will only respond to messages that contain a question mark"
                />
                <BooleanFormField
                  name="respond_tag_only"
                  label="Respond to @Darwin Only"
                  subtext="If set, Darwin will only respond when directly tagged"
                />
                <BooleanFormField
                  name="respond_to_bots"
                  label="Responds to Bot messages"
                  subtext="If not set, Darwin will always ignore messages from Bots"
                />
                <TextArrayField
                  name="respond_member_group_list"
                  label="Team Member Emails Or Slack Group Names"
                  subtext={`If specified, Darwin responses will only be 
                  visible to the members or groups in this list. This is
                  useful if you want Darwin to operate in an
                  "assistant" mode, where it helps the team members find
                  answers, but let's them build on top of Darwin's response / throw 
                  out the occasional incorrect answer. Group names are case sensitive.`}
                  values={values}
                />
                <Divider />

                <SectionHeader>Post Response Behavior</SectionHeader>

                <BooleanFormField
                  name="still_need_help_enabled"
                  label="Should Darwin give a “Still need help?” button?"
                  subtext={`If specified, Darwin's response will include a button at the bottom 
                  of the response that asks the user if they still need help.`}
                />
                {values.still_need_help_enabled && (
                  <TextArrayField
                    name="follow_up_tags"
                    label="Users to Tag"
                    values={values}
                    subtext={
                      <div>
                        The full email addresses of the Slack users we should
                        tag if the user clicks the &quot;Still need help?&quot;
                        button. For example, &apos;mark@acme.com&apos;.
                        <br />
                        Or provide a user group by either the name or the
                        handle. For example, &apos;Darwin Team&apos; or
                        &apos;darwin-team&apos;.
                        <br />
                        <br />
                        If no emails are provided, we will not tag anyone and
                        will just react with a 🆘 emoji to the original message.
                      </div>
                    }
                  />
                )}

                <Divider />

                <div>
                  <SectionHeader>
                    [Optional] Data Sources and Prompts
                  </SectionHeader>
                  <Text>
                    Use either a Persona <b>or</b> Document Sets to control how
                    Darwin answers.
                  </Text>
                  <div className="mt-2">
                    <ul className="list-disc ml-4">
                      <li>
                        You should use a Persona if you also want to customize
                        the prompt and retrieval settings.
                      </li>
                      <li>
                        You should use Document Sets if you just want to control
                        which documents Darwin uses as references.
                      </li>
                    </ul>
                  </div>
                  <Text className="mt-2">
                    <b>NOTE:</b> whichever tab you are when you submit the form
                    will be the one that is used. For example, if you are on the
                    &quot;Personas&quot; tab, then the Persona will be used,
                    even if you have Document Sets selected.
                  </Text>
                </div>

                <TabGroup
                  index={usingPersonas ? 1 : 0}
                  onIndexChange={(index) => setUsingPersonas(index === 1)}
                >
                  <TabList className="mt-3 mb-4">
                    <Tab icon={BookmarkIcon}>Document Sets</Tab>
                    <Tab icon={RobotIcon}>Personas</Tab>
                  </TabList>
                  <TabPanels>
                    <TabPanel>
                      <FieldArray
                        name="document_sets"
                        render={(arrayHelpers: ArrayHelpers) => (
                          <div>
                            <div>
                              <SubLabel>
                                The document sets that Darwin should search
                                through. If left blank, Darwin will search
                                through all documents.
                              </SubLabel>
                            </div>
                            <div className="mb-3 mt-2 flex gap-2 flex-wrap text-sm">
                              {documentSets.map((documentSet) => {
                                const ind = values.document_sets.indexOf(
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
                    </TabPanel>
                    <TabPanel>
                      <SelectorFormField
                        name="persona_id"
                        subtext={`
                            The persona to use when responding to queries. The Default persona acts
                            as a question-answering assistant and has access to all documents indexed by non-private connectors.
                          `}
                        options={personas.map((persona) => {
                          return {
                            name: persona.name,
                            value: persona.id,
                          };
                        })}
                      />
                    </TabPanel>
                  </TabPanels>
                </TabGroup>

                <Divider />

                <SectionHeader>JIRA Integration</SectionHeader>

                <BooleanFormField
                  name="jira_config.enable_jira_integration"
                  label="Enable JIRA Integration"
                  subtext="If enabled, creates JIRA tickets for messages from users with specific titles"
                />

                {values.jira_config.enable_jira_integration && (
                  <>
                    <TextArrayField
                      name="jira_title_filter"
                      label="User Titles to Create JIRA Tickets For"
                      values={values}
                      subtext={
                        <div>
                          List of user titles that should trigger JIRA ticket
                          creation. For example, &apos;Senior Software
                          Engineer&apos;, &apos;Software Engineer II&apos;, etc.
                          <br />
                          <br />
                          When a user with any of these titles sends a message,
                          a JIRA ticket will be created with the message content
                          and a link to the Slack message.
                        </div>
                      }
                    />

                    <TextFormField
                      name="jira_config.project_key"
                      label="JIRA Project Key"
                      subtext="The key of the JIRA project where tickets will be created"
                    />

                    <TextFormField
                      name="jira_config.issue_type"
                      label="JIRA Issue Type"
                      subtext="The type of issue to create (e.g. Bug, Task, Story)"
                    />

                    <TextFormField
                      name="jira_config.component"
                      label="JIRA Component"
                      subtext="The component to assign the issue to"
                    />
                  </>
                )}

                <Divider />

                <SectionHeader>Source Selection</SectionHeader>
                <Text className="mb-2">
                  Select the sources to emphasize in your search. Sources not
                  selected will still be included, but fewer results from them
                  may appear. If no sources are selected, Web and Salesforce KB
                  articles are taken as default.
                </Text>
                <div className="mb-3 mt-2 flex gap-2 flex-wrap text-sm">
                  {availableSources.map((source) => {
                    const isSelected =
                      values.prioritized_sources.includes(source);
                    return (
                      <div
                        key={source}
                        className={
                          `
                          px-3 
                          py-1
                          rounded-lg 
                          border
                          border-border 
                          w-fit 
                          flex 
                          items-center
                          gap-2
                          cursor-pointer ` +
                          (isSelected
                            ? " bg-hover"
                            : " bg-background hover:bg-hover-light")
                        }
                        onClick={() => {
                          const newSources = isSelected
                            ? values.prioritized_sources.filter(
                                (s) => s !== source
                              )
                            : [...values.prioritized_sources, source];
                          setFieldValue("prioritized_sources", newSources);
                        }}
                      >
                        <SourceIcon sourceType={source} iconSize={16} />
                        <span>{getSourceMetadata(source).displayName}</span>
                      </div>
                    );
                  })}
                </div>

                <Divider />

                <div className="flex">
                  <Button
                    type="submit"
                    disabled={isSubmitting}
                    className="mx-auto w-64"
                  >
                    {isUpdate ? "Update!" : "Create!"}
                  </Button>
                </div>
              </div>
            </Form>
          )}
        </Formik>
      </Card>
    </div>
  );
};
