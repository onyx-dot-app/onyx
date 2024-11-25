"use client";

import { ArrayHelpers, FieldArray, Form, Formik } from "formik";
import * as Yup from "yup";
import { usePopup } from "@/components/admin/connectors/Popup";
import { DocumentSet, SlackBotConfig } from "@/lib/types";
import {
  BooleanFormField,
  Label,
  SelectorFormField,
  SubLabel,
  TextArrayField,
} from "@/components/admin/connectors/Field";
import {
  createSlackBotConfig,
  isPersonaASlackBotPersona,
  updateSlackBotConfig,
} from "./lib";
import { Separator } from "@/components/ui/separator";
import CardSection from "@/components/admin/CardSection";
import { Button } from "@/components/ui/button";
import { useRouter } from "next/navigation";
import { Persona } from "../assistants/interfaces";
import { useState } from "react";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import { DocumentSetSelectable } from "@/components/documentSet/DocumentSetSelectable";
import CollapsibleSection from "../assistants/CollapsibleSection";
import { StandardAnswerCategoryResponse } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";
import { StandardAnswerCategoryDropdownField } from "@/components/standardAnswers/StandardAnswerCategoryDropdown";

export const SlackBotCreationForm = ({
  documentSets,
  personas,
  standardAnswerCategoryResponse,
  existingSlackBotConfig,
}: {
  documentSets: DocumentSet[];
  personas: Persona[];
  standardAnswerCategoryResponse: StandardAnswerCategoryResponse;
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
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  const knowledgePersona = personas.find((persona) => persona.id === 0);

  return (
    <div>
      <CardSection>
        {popup}
        <Formik
          initialValues={{
            channel_names: existingSlackBotConfig
              ? existingSlackBotConfig.channel_config.channel_names
              : ([""] as string[]),
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
            // prettier-ignore
            persona_id:
              existingSlackBotConfig?.persona &&
              !isPersonaASlackBotPersona(existingSlackBotConfig.persona)
                ? existingSlackBotConfig.persona.id
                : knowledgePersona?.id ?? null,
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
              <div className="px-6 pb-6 pt-4 w-full">
                <TextArrayField
                  name="channel_names"
                  label="Channel Names"
                  values={values}
                  subtext="The names of the Slack channels you want this configuration to apply to. 
                  For example, #ask-danswer."
                  minFields={1}
                  placeholder="Enter channel name..."
                />

                <div className="mt-6">
                  <Label>Knowledge Sources</Label>

                  <SubLabel>
                    Controls which information DanswerBot will pull from when
                    answering questions.
                  </SubLabel>

                  <div className="flex mt-4">
                    <button
                      type="button"
                      onClick={() => setUsingPersonas(false)}
                      className={`p-2 font-bold text-xs mr-3 ${
                        !usingPersonas
                          ? "rounded bg-background-900 text-text-100 underline"
                          : "hover:underline bg-background-100"
                      }`}
                    >
                      Document Sets
                    </button>

                    <button
                      type="button"
                      onClick={() => setUsingPersonas(true)}
                      className={`p-2 font-bold text-xs  ${
                        usingPersonas
                          ? "rounded bg-background-900 text-text-100 underline"
                          : "hover:underline bg-background-100"
                      }`}
                    >
                      Assistants
                    </button>
                  </div>

                  <div className="mt-4">
                    {/* TODO: make this look nicer */}
                    {usingPersonas ? (
                      <SelectorFormField
                        name="persona_id"
                        options={personas.map((persona) => {
                          return {
                            name: persona.name,
                            value: persona.id,
                          };
                        })}
                      />
                    ) : (
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
                            <div>
                              <SubLabel>
                                Note: If left blank, DanswerBot will search
                                through all connected documents.
                              </SubLabel>
                            </div>
                          </div>
                        )}
                      />
                    )}
                  </div>
                </div>

                <Separator />

                <AdvancedOptionsToggle
                  showAdvancedOptions={showAdvancedOptions}
                  setShowAdvancedOptions={setShowAdvancedOptions}
                />

                {showAdvancedOptions && (
                  <div className="mt-4">
                    <div className="w-64 mb-4">
                      <SelectorFormField
                        name="response_type"
                        label="Answer Type"
                        tooltip="Controls the format of DanswerBot's responses."
                        options={[
                          { name: "Standard", value: "citations" },
                          { name: "Detailed", value: "quotes" },
                        ]}
                      />
                    </div>

                    <div className="flex flex-col space-y-3 mt-2">
                      <BooleanFormField
                        name="still_need_help_enabled"
                        removeIndent
                        label={'Give a "Still need help?" button'}
                        tooltip={`DanswerBot's response will include a button at the bottom 
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
                        label="Hide Non-Answers"
                        tooltip="If set, will only answer questions that the model determines it can answer"
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
                        label="Respond to @DanswerBot Only"
                        tooltip="If set, DanswerBot will only respond when directly tagged"
                      />
                      <BooleanFormField
                        name="respond_to_bots"
                        removeIndent
                        label="Respond to Bot messages"
                        tooltip="If not set, DanswerBot will always ignore messages from Bots"
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
                            "If specified, DanswerBot responses will only " +
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
      </CardSection>
    </div>
  );
};
