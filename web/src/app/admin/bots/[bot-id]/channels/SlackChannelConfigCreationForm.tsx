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
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

import React from "react";
import { SEARCH_TOOL_NAME } from "@/app/chat/tools/constants";
import { AlertCircle } from "lucide-react";

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
  const [selectedOption, setSelectedOption] = useState<
    "all_public" | "document_sets" | "assistant"
  >(
    existingSlackBotUsesPersona
      ? "assistant"
      : existingSlackChannelConfig?.persona
        ? "document_sets"
        : "all_public"
  );
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  const knowledgePersona = personas.find((persona) => persona.id === 0);
  const [personaId, setPersonaId] = useState<number | null>(null);
  const documentSetContainsSync = (documentSet: DocumentSet) => {
    return documentSet.cc_pair_descriptors.some(
      (descriptor) => descriptor.access_type === "sync"
    );
  };
  const documentSetContainsPrivate = (documentSet: DocumentSet) => {
    return documentSet.cc_pair_descriptors.some(
      (descriptor) => descriptor.access_type === "private"
    );
  };
  const searchEnabledAssistants = personas.filter(
    (persona) =>
      persona.tools.some((tool) => (tool.name = SEARCH_TOOL_NAME)) &&
      !persona.document_sets.some((ds) => documentSetContainsSync(ds))
  );
  const [document_sets, setDocumentSets] = useState<number[]>([]);

  const shouldShowPrivacyAlert = React.useMemo(() => {
    console.log("Recalculating shouldShowPrivacyAlert");
    console.log("Current selectedOption:", selectedOption);
    console.log("Current documentSets:", documentSets);
    console.log("Current personaId:", personaId);
    console.log("Current searchEnabledAssistants:", searchEnabledAssistants);

    if (selectedOption === "document_sets") {
      console.log("Checking privacy for document_sets option");
      const hasPrivateDocuments = documentSets
        .filter((ds) => document_sets.includes(ds.id))
        .some((ds) => documentSetContainsPrivate(ds));
      console.log("Has private documents:", hasPrivateDocuments);
      return hasPrivateDocuments;
    } else if (selectedOption === "assistant") {
      console.log("Checking privacy for assistant option");
      console.log(searchEnabledAssistants);
      console.log(personaId);
      const selectedAssistant = searchEnabledAssistants.find(
        (persona) => persona.id == personaId
      );
      console.log("Selected assistant:", selectedAssistant);
      const assistantHasPrivateDocuments =
        selectedAssistant?.document_sets.some((ds) =>
          documentSetContainsPrivate(ds)
        );
      console.log(
        "Assistant has private documents:",
        assistantHasPrivateDocuments
      );
      return assistantHasPrivateDocuments;
    }
    console.log("No privacy alert needed for current option");
    return false;
  }, [selectedOption, documentSets, personaId, searchEnabledAssistants]);

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
            knowledge_source: selectedOption,
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
            knowledge_source: Yup.string()
              .oneOf(["all_public", "document_sets", "assistant"])
              .required(),
          })}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            const cleanedValues = {
              ...values,
              slack_bot_id: slack_bot_id,
              channel_name: values.channel_name!,
              respond_member_group_list: values.respond_member_group_list,
              usePersona: values.knowledge_source === "assistant",
              document_sets:
                values.knowledge_source === "document_sets"
                  ? values.document_sets
                  : [],
              persona_id:
                values.knowledge_source === "assistant"
                  ? values.persona_id
                  : null,
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
          {({ isSubmitting, values, setFieldValue }) => {
            React.useEffect(() => {
              setSelectedOption(
                values.knowledge_source as
                  | "all_public"
                  | "document_sets"
                  | "assistant"
              );
            }, [values.knowledge_source]);

            React.useEffect(() => {
              setPersonaId(values.persona_id);
            }, [values.persona_id]);

            React.useEffect(() => {
              setDocumentSets(values.document_sets);
            }, [values.document_sets]);

            return (
              <Form>
                <div className="px-6 max-w-4xl pb-6 pt-4 w-full">
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

                    <RadioGroup
                      name="knowledge_source"
                      value={values.knowledge_source}
                      onValueChange={(value) => {
                        setFieldValue("knowledge_source", value);
                      }}
                      className="mt-4 gap-y-0"
                    >
                      <div className="flex items-center space-x-2">
                        <RadioGroupItem value="all_public" id="all_public" />
                        <Label small>
                          <span className="cursor-pointer">
                            All public knowledge within Onyx
                          </span>
                        </Label>
                      </div>
                      <SubLabel>
                        <span className="ml-6 mb-2 block">
                          OnyxBot will search through all connected documents.
                        </span>
                      </SubLabel>

                      {documentSets && documentSets.length > 0 && (
                        <>
                          <div className="flex items-center space-x-2">
                            <RadioGroupItem
                              value="document_sets"
                              id="document_sets"
                            />
                            <Label small>
                              <span className="cursor-pointer">
                                Document sets
                              </span>
                            </Label>
                          </div>
                          <SubLabel>
                            <span className="ml-6 mb-2 block">
                              Select specific document sets for OnyxBot to use.
                            </span>
                          </SubLabel>
                        </>
                      )}

                      <div className="flex items-center space-x-2">
                        <RadioGroupItem value="assistant" id="assistant" />
                        <Label small>
                          <span className="cursor-pointer">Assistant</span>
                        </Label>
                      </div>
                      <SubLabel>
                        <span className="ml-6 mb-2 block">
                          Use a pre-configured assistant with its own knowledge
                          and prompt.
                        </span>
                      </SubLabel>
                    </RadioGroup>

                    {values.knowledge_source === "document_sets" &&
                      documentSets &&
                      documentSets.length > 0 && (
                        <div className="mt-2">
                          <SubLabel>
                            Select the document sets OnyxBot will use while
                            answering questions in Slack.
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
                                      <>
                                        <DocumentSetSelectable
                                          disabled={documentSetContainsSync(
                                            documentSet
                                          )}
                                          disabledTooltip={
                                            "This document set contains auto-synced documents, which cannot be added to an OnyxBot"
                                          }
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
                                      </>
                                    );
                                  })}
                                </div>
                              </div>
                            )}
                          />
                        </div>
                      )}

                    {values.knowledge_source === "assistant" && (
                      <div className="mt-2">
                        <SubLabel>
                          Select the search-enabled assistant OnyxBot will use
                          while answering questions in Slack.
                        </SubLabel>
                        <SelectorFormField
                          name="persona_id"
                          options={searchEnabledAssistants.map((persona) => ({
                            name: persona.name,
                            value: persona.id,
                          }))}
                        />
                      </div>
                    )}
                  </div>

                  {shouldShowPrivacyAlert && (
                    <Alert className="mt-2">
                      <AlertCircle className="h-4 w-4" />
                      <AlertTitle>Connector Privacy</AlertTitle>
                      <AlertDescription>
                        Please note that at least one of the documents
                        accessible by your Onyxbot is marked as private and may
                        contain sensitive information. These documents will be
                        accessible to all users of this Onyxbot. Ensure this
                        aligns with your intended document sharing policy.
                      </AlertDescription>
                    </Alert>
                  )}

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
                          setFieldValue(
                            "standard_answer_categories",
                            categories
                          )
                        }
                      />
                    </div>
                  )}
                  <div className="flex mt-2">
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
            );
          }}
        </Formik>
      </CardSection>
    </div>
  );
};
