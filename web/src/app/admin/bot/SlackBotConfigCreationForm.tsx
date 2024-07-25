"use client";

import { ArrayHelpers, FieldArray, Form, Formik } from "formik";
import * as Yup from "yup";
import { usePopup } from "@/components/admin/connectors/Popup";
import {
  DocumentSet,
  SlackBotConfig,
  StandardAnswerCategory,
} from "@/lib/types";
import {
  BooleanFormField,
  SectionHeader,
  SelectorFormField,
  SubLabel,
  TextArrayField,
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
import MultiSelectDropdown from "@/components/MultiSelectDropdown";

export const SlackBotCreationForm = ({
  documentSets,
  personas,
  standardAnswerCategories,
  existingSlackBotConfig,
}: {
  documentSets: DocumentSet[];
  personas: Persona[];
  standardAnswerCategories: StandardAnswerCategory[];
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
            enable_auto_filters:
              existingSlackBotConfig?.enable_auto_filters || false,
            respond_member_group_list:
              existingSlackBotConfig?.channel_config
                ?.respond_member_group_list ?? [],
            still_need_help_enabled:
              existingSlackBotConfig?.channel_config?.follow_up_tags !==
              undefined,
            follow_up_tags:
              existingSlackBotConfig?.channel_config?.follow_up_tags,
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
            standard_answer_categories: existingSlackBotConfig
              ? existingSlackBotConfig.standard_answer_categories
              : [],
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
            enable_auto_filters: Yup.boolean().required(),
            respond_member_group_list: Yup.array().of(Yup.string()).required(),
            still_need_help_enabled: Yup.boolean().required(),
            follow_up_tags: Yup.array().of(Yup.string()),
            document_sets: Yup.array().of(Yup.number()),
            persona_id: Yup.number().nullable(),
            standard_answer_categories: Yup.array(),
          })}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            // remove empty channel names
            const cleanedValues = {
              ...values,
              channel_names: values.channel_names.filter(
                (channelName) => channelName !== ""
              ),
              respond_member_group_list: values.respond_member_group_list,
              usePersona: usingPersonas,
              standard_answer_categories: values.standard_answer_categories.map(
                (category) => category.id
              ),
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
                  ? `Error updating DanswerBot config - ${errorMsg}`
                  : `Error creating DanswerBot config - ${errorMsg}`,
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
                      &apos;#ask-danswer&apos;.
                      <br />
                      <br />
                      <i>NOTE</i>: you still need to add DanswerBot to the
                      channel(s) in Slack itself. Setting this config will not
                      auto-add the bot to the channel.
                    </div>
                  }
                />

                <SelectorFormField
                  name="response_type"
                  label="Response Format"
                  subtext={
                    <>
                      If set to Citations, DanswerBot will respond with a direct
                      answer with inline citations. It will also provide links
                      to these cited documents below the answer. When in doubt,
                      choose this option.
                      <br />
                      <br />
                      If set to Quotes, DanswerBot will respond with a direct
                      answer as well as with quotes pulled from the context
                      documents to support that answer. DanswerBot will also
                      give a list of relevant documents. Choose this option if
                      you want a very detailed response AND/OR a list of
                      relevant documents would be useful just in case the LLM
                      missed anything.
                    </>
                  }
                  options={[
                    { name: "Citations", value: "citations" },
                    { name: "Quotes", value: "quotes" },
                  ]}
                />

                <Divider />

                <SectionHeader>When should DanswerBot respond?</SectionHeader>

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
                  label="Respond to @DanswerBot Only"
                  subtext="If set, DanswerBot will only respond when directly tagged"
                />
                <BooleanFormField
                  name="respond_to_bots"
                  label="Responds to Bot messages"
                  subtext="If not set, DanswerBot will always ignore messages from Bots"
                />
                <BooleanFormField
                  name="enable_auto_filters"
                  label="Enable LLM Autofiltering"
                  subtext="If set, the LLM will generate source and time filters based on the user's query"
                />
                <TextArrayField
                  name="respond_member_group_list"
                  label="Team Member Emails Or Slack Group Names/Handles"
                  subtext={`If specified, DanswerBot responses will only be 
                  visible to the members or groups in this list. This is
                  useful if you want DanswerBot to operate in an
                  "assistant" mode, where it helps the team members find
                  answers, but let's them build on top of DanswerBot's response / throw 
                  out the occasional incorrect answer. Group names and handles are case sensitive.`}
                  values={values}
                />
                <Divider />

                <SectionHeader>Post Response Behavior</SectionHeader>

                <BooleanFormField
                  name="still_need_help_enabled"
                  label="Should Danswer give a “Still need help?” button?"
                  subtext={`If specified, DanswerBot's response will include a button at the bottom 
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
                        handle. For example, &apos;Danswer Team&apos; or
                        &apos;danswer-team&apos;.
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
                    DanswerBot answers.
                  </Text>
                  <Text>
                    <ul className="list-disc mt-2 ml-4">
                      <li>
                        You should use a Persona if you also want to customize
                        the prompt and retrieval settings.
                      </li>
                      <li>
                        You should use Document Sets if you just want to control
                        which documents DanswerBot uses as references.
                      </li>
                    </ul>
                  </Text>
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
                                The document sets that DanswerBot should search
                                through. If left blank, DanswerBot will search
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

                <div>
                  <SectionHeader>
                    [Optional] Standard Answer Categories
                  </SectionHeader>
                  <div className="w-4/12">
                    <MultiSelectDropdown
                      name="standard_answer_categories"
                      label=""
                      onChange={(selected_options) => {
                        const selected_categories = selected_options.map(
                          (option) => {
                            return {
                              id: Number(option.value),
                              name: option.label,
                            };
                          }
                        );
                        setFieldValue(
                          "standard_answer_categories",
                          selected_categories
                        );
                      }}
                      creatable={false}
                      options={standardAnswerCategories.map((category) => ({
                        label: category.name,
                        value: category.id.toString(),
                      }))}
                      initialSelectedOptions={values.standard_answer_categories.map(
                        (category) => ({
                          label: category.name,
                          value: category.id.toString(),
                        })
                      )}
                    />
                  </div>
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
