"use client";

import { ArrayHelpers, FieldArray, Form, Formik } from "formik";
import * as Yup from "yup";
import { usePopup } from "@/components/admin/connectors/Popup";
import { DocumentSet, SlackChannelConfig } from "@/lib/types";
import {
  BooleanFormField,
  Label,
  SelectorFormField,
  SubLabel,
  TextArrayField,
  TextFormField,
} from "@/components/admin/connectors/Field";
import {
  createSlackChannelConfig,
  isPersonaASlackBotPersona,
  updateSlackChannelConfig,
} from "../lib";
import CardSection from "@/components/admin/CardSection";
import { Button } from "@/components/ui/button";
import { useRouter } from "next/navigation";
import { Persona } from "@/app/admin/assistants/interfaces";
import { useState } from "react";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import { DocumentSetSelectable } from "@/components/documentSet/DocumentSetSelectable";
import CollapsibleSection from "@/app/admin/assistants/CollapsibleSection";
import { StandardAnswerCategoryResponse } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";
import { StandardAnswerCategoryDropdownField } from "@/components/standardAnswers/StandardAnswerCategoryDropdown";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/fully_wrapped_tabs";

export const SlackChannelConfigCreationForm = ({
  slack_bot_id,
  documentSets,
  personas,
  standardAnswerCategoryResponse,
  existingSlackChannelConfig,
}: {
  slack_bot_id: number;
  documentSets: DocumentSet[];
  personas: Persona[];
  standardAnswerCategoryResponse: StandardAnswerCategoryResponse;
  existingSlackChannelConfig?: SlackChannelConfig;
}) => {
  const isUpdate = existingSlackChannelConfig !== undefined;
  const { popup, setPopup } = usePopup();
  const router = useRouter();
  const existingSlackBotUsesPersona = existingSlackChannelConfig?.persona
    ? !isPersonaASlackBotPersona(existingSlackChannelConfig.persona)
    : false;
  const [usingPersonas, setUsingPersonas] = useState(
    existingSlackBotUsesPersona
  );
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  const knowledgePersona = personas.find((persona) => persona.id === 0);

  return (
    <div>
      <CardSection>
        {popup}
        <Formik
          initialValues={{
            slack_bot_id: slack_bot_id,
            channel_name:
              existingSlackChannelConfig?.channel_config.channel_name,
            answer_validity_check_enabled: (
              existingSlackChannelConfig?.channel_config?.answer_filters || []
            ).includes("well_answered_postfilter"),
            questionmark_prefilter_enabled: (
              existingSlackChannelConfig?.channel_config?.answer_filters || []
            ).includes("questionmark_prefilter"),
            respond_tag_only:
              existingSlackChannelConfig?.channel_config?.respond_tag_only ||
              false,
            respond_to_bots:
              existingSlackChannelConfig?.channel_config?.respond_to_bots ||
              false,
            show_continue_in_web_ui:
              // If we're updating, we want to keep the existing value
              // Otherwise, we want to default to true
              existingSlackChannelConfig?.channel_config
                ?.show_continue_in_web_ui ?? !isUpdate,
            enable_auto_filters:
              existingSlackChannelConfig?.enable_auto_filters || false,
            respond_member_group_list:
              existingSlackChannelConfig?.channel_config
                ?.respond_member_group_list ?? [],
            still_need_help_enabled:
              existingSlackChannelConfig?.channel_config?.follow_up_tags !==
              undefined,
            follow_up_tags:
              existingSlackChannelConfig?.channel_config?.follow_up_tags,
            document_sets:
              existingSlackChannelConfig && existingSlackChannelConfig.persona
                ? existingSlackChannelConfig.persona.document_sets.map(
                    (documentSet) => documentSet.id
                  )
                : ([] as number[]),
            // prettier-ignore
            persona_id:
              existingSlackChannelConfig?.persona &&
              !isPersonaASlackBotPersona(existingSlackChannelConfig.persona)
                ? existingSlackChannelConfig.persona.id
                : knowledgePersona?.id ?? null,
            response_type:
              existingSlackChannelConfig?.response_type || "citations",
            standard_answer_categories: existingSlackChannelConfig
              ? existingSlackChannelConfig.standard_answer_categories
              : [],
          }}
          validationSchema={Yup.object().shape({
            slack_bot_id: Yup.number().required(),
            channel_name: Yup.string(),
            response_type: Yup.string()
              .oneOf(["quotes", "citations"])
              .required(),
            answer_validity_check_enabled: Yup.boolean().required(),
            questionmark_prefilter_enabled: Yup.boolean().required(),
            respond_tag_only: Yup.boolean().required(),
            respond_to_bots: Yup.boolean().required(),
            show_continue_in_web_ui: Yup.boolean().required(),
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

            const cleanedValues = {
              ...values,
              slack_bot_id: slack_bot_id,
              channel_name: values.channel_name!,
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
              response = await updateSlackChannelConfig(
                existingSlackChannelConfig.id,
                cleanedValues
              );
            } else {
              response = await createSlackChannelConfig(cleanedValues);
            }
            formikHelpers.setSubmitting(false);
            if (response.ok) {
              router.push(`/admin/bots/${slack_bot_id}`);
            } else {
              const responseJson = await response.json();
              const errorMsg = responseJson.detail || responseJson.message;
              setPopup({
                message: isUpdate
                  ? `Error updating OnyxBot config - ${errorMsg}`
                  : `Error creating OnyxBot config - ${errorMsg}`,
                type: "error",
              });
            }
          }}
        >
          {({ isSubmitting, values, setFieldValue }) => (
            <Form>
              <div className="px-6 pb-6 pt-4 w-full">
                <TextFormField
                  name="channel_name"
                  label="Slack Channel Name:"
                />

                <div className="mt-6">
                  <Label>Knowledge Sources</Label>
                  <SubLabel>
                    Controls which information OnyxBot will pull from when
                    answering questions.
                  </SubLabel>

                  <Tabs
                    defaultValue="document_sets"
                    className="w-full mt-4"
                    value={usingPersonas ? "assistants" : "document_sets"}
                    onValueChange={(value) =>
                      setUsingPersonas(value === "assistants")
                    }
                  >
                    <TabsList>
                      <TabsTrigger value="document_sets">
                        Document Sets
                      </TabsTrigger>
                      <TabsTrigger value="assistants">Assistants</TabsTrigger>
                    </TabsList>

                    <TabsContent value="assistants">
                      <SubLabel>
                        Select the assistant OnyxBot will use while answering
                        questions in Slack.
                      </SubLabel>
                      <SelectorFormField
                        name="persona_id"
                        options={personas.map((persona) => {
                          return {
                            name: persona.name,
                            value: persona.id,
                          };
                        })}
                      />
                    </TabsContent>

                    <TabsContent value="document_sets">
                      <SubLabel>
                        Select the document sets OnyxBot will use while
                        answering questions in Slack.
                      </SubLabel>
                      <SubLabel>
                        Note: If No Document Sets are selected, OnyxBot will
                        search through all connected documents.
                      </SubLabel>
                      <FieldArray
                        name="document_sets"
                        render={(arrayHelpers: ArrayHelpers) => (
                          <div>
                            <div className="mb-3 mt-2 flex gap-2 flex-wrap text-sm">
                              {documentSets.map((documentSet) => {
                                const ind = values.document_sets.indexOf(
                                  documentSet.id
                                );
                                const isSelected = ind !== -1;

                                return (
                                  <DocumentSetSelectable
                                    key={documentSet.id}
                                    documentSet={documentSet}
                                    isSelected={isSelected}
                                    onSelect={() => {
                                      if (isSelected) {
                                        arrayHelpers.remove(ind);
                                      } else {
                                        arrayHelpers.push(documentSet.id);
                                      }
                                    }}
                                  />
                                );
                              })}
                            </div>
                            <div></div>
                          </div>
                        )}
                      />
                    </TabsContent>
                  </Tabs>
                </div>

                <div className="mt-6">
                  <AdvancedOptionsToggle
                    showAdvancedOptions={showAdvancedOptions}
                    setShowAdvancedOptions={setShowAdvancedOptions}
                  />
                </div>

                {showAdvancedOptions && (
                  <div className="mt-4">
                    <div className="w-64 mb-4">
                      <SelectorFormField
                        name="response_type"
                        label="Answer Type"
                        tooltip="Controls the format of OnyxBot's responses."
                        options={[
                          { name: "Standard", value: "citations" },
                          { name: "Detailed", value: "quotes" },
                        ]}
                      />
                    </div>

                    <BooleanFormField
                      name="show_continue_in_web_ui"
                      removeIndent
                      label="Show Continue in Web UI button"
                      tooltip="If set, will show a button at the bottom of the response that allows the user to continue the conversation in the Onyx Web UI"
                    />
                    <div className="flex flex-col space-y-3 mt-2">
                      <BooleanFormField
                        name="still_need_help_enabled"
                        removeIndent
                        label={'Give a "Still need help?" button'}
                        tooltip={`OnyxBot's response will include a button at the bottom 
                      of the response that asks the user if they still need help.`}
                      />
                      {values.still_need_help_enabled && (
                        <CollapsibleSection prompt="Configure Still Need Help Button">
                          <TextArrayField
                            name="follow_up_tags"
                            label="(Optional) Users / Groups to Tag"
                            values={values}
                            subtext={
                              <div>
                                The Slack users / groups we should tag if the
                                user clicks the &quot;Still need help?&quot;
                                button. If no emails are provided, we will not
                                tag anyone and will just react with a 🆘 emoji
                                to the original message.
                              </div>
                            }
                            placeholder="User email or user group name..."
                          />
                        </CollapsibleSection>
                      )}

                      <BooleanFormField
                        name="answer_validity_check_enabled"
                        removeIndent
                        label="Only respond if citations found"
                        tooltip="If set, will only answer questions where the model successfully produces citations"
                      />
                      <BooleanFormField
                        name="questionmark_prefilter_enabled"
                        removeIndent
                        label="Only respond to questions"
                        tooltip="If set, will only respond to messages that contain a question mark"
                      />
                      <BooleanFormField
                        name="respond_tag_only"
                        removeIndent
                        label="Respond to @OnyxBot Only"
                        tooltip="If set, OnyxBot will only respond when directly tagged"
                      />
                      <BooleanFormField
                        name="respond_to_bots"
                        removeIndent
                        label="Respond to Bot messages"
                        tooltip="If not set, OnyxBot will always ignore messages from Bots"
                      />
                      <BooleanFormField
                        name="enable_auto_filters"
                        removeIndent
                        label="Enable LLM Autofiltering"
                        tooltip="If set, the LLM will generate source and time filters based on the user's query"
                      />

                      <div className="mt-12">
                        <TextArrayField
                          name="respond_member_group_list"
                          label="(Optional) Respond to Certain Users / Groups"
                          subtext={
                            "If specified, OnyxBot responses will only " +
                            "be visible to the members or groups in this list."
                          }
                          values={values}
                          placeholder="User email or user group name..."
                        />
                      </div>
                    </div>

                    <StandardAnswerCategoryDropdownField
                      standardAnswerCategoryResponse={
                        standardAnswerCategoryResponse
                      }
                      categories={values.standard_answer_categories}
                      setCategories={(categories) =>
                        setFieldValue("standard_answer_categories", categories)
                      }
                    />
                  </div>
                )}

                <div className="flex">
                  <Button
                    type="submit"
                    variant="submit"
                    disabled={isSubmitting || !values.channel_name}
                    className="mx-auto w-64"
                  >
                    {isUpdate ? "Update!" : "Create!"}
                  </Button>
                </div>
              </div>
            </Form>
          )}
        </Formik>
      </CardSection>
    </div>
  );
};
