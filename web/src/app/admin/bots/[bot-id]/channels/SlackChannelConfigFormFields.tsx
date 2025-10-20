"use client";

import React, { useState, useEffect, useMemo } from "react";
import { FieldArray, useFormikContext, ErrorMessage, Field } from "formik";
import { CCPairDescriptor, DocumentSetSummary } from "@/lib/types";
import {
  Label,
  SelectorFormField,
  SubLabel,
  TextArrayField,
  TextFormField,
} from "@/components/Field";
import Button from "@/refresh-components/buttons/Button";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { DocumentSetSelectable } from "@/components/documentSet/DocumentSetSelectable";
import CollapsibleSection from "@/app/admin/assistants/CollapsibleSection";
import { StandardAnswerCategoryResponse } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";
import { StandardAnswerCategoryDropdownField } from "@/components/standardAnswers/StandardAnswerCategoryDropdown";
import { RadioGroup } from "@/components/ui/radio-group";
import { RadioGroupItemField } from "@/components/ui/RadioGroupItemField";
import { AlertCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import { SourceIcon } from "@/components/SourceIcon";
import Link from "next/link";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { Badge } from "@/components/ui/badge";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Separator } from "@/components/ui/separator";

import { CheckFormField } from "@/components/ui/CheckField";

export interface SlackChannelConfigFormFieldsProps {
  isUpdate: boolean;
  isDefault: boolean;
  documentSets: DocumentSetSummary[];
  searchEnabledAssistants: MinimalPersonaSnapshot[];
  nonSearchAssistants: MinimalPersonaSnapshot[];
  standardAnswerCategoryResponse: StandardAnswerCategoryResponse;
  setPopup: (popup: {
    message: string;
    type: "error" | "success" | "warning";
  }) => void;
  slack_bot_id: number;
  formikProps: any;
}

export function SlackChannelConfigFormFields({
  isUpdate,
  isDefault,
  documentSets,
  searchEnabledAssistants,
  nonSearchAssistants,
  standardAnswerCategoryResponse,
  setPopup,
  slack_bot_id,
  formikProps,
}: SlackChannelConfigFormFieldsProps) {
  const router = useRouter();
  const { values, setFieldValue } = useFormikContext<any>();
  const [viewUnselectableSets, setViewUnselectableSets] = useState(false);
  const [viewSyncEnabledAssistants, setViewSyncEnabledAssistants] =
    useState(false);

  // Helper function to check if a document set contains sync connectors
  const documentSetContainsSync = (documentSet: DocumentSetSummary) => {
    return documentSet.cc_pair_summaries.some(
      (summary) => summary.access_type === "sync"
    );
  };

  // Helper function to check if a document set contains private connectors
  const documentSetContainsPrivate = (documentSet: DocumentSetSummary) => {
    return documentSet.cc_pair_summaries.some(
      (summary) => summary.access_type === "private"
    );
  };

  // Helper function to get cc_pair_summaries from DocumentSetSummary
  const getCcPairSummaries = (documentSet: DocumentSetSummary) => {
    return documentSet.cc_pair_summaries;
  };

  const [syncEnabledAssistants, availableAssistants] = useMemo(() => {
    const sync: MinimalPersonaSnapshot[] = [];
    const available: MinimalPersonaSnapshot[] = [];

    searchEnabledAssistants.forEach((persona) => {
      const hasSyncSet = persona.document_sets.some(documentSetContainsSync);
      if (hasSyncSet) {
        sync.push(persona);
      } else {
        available.push(persona);
      }
    });

    return [sync, available];
  }, [searchEnabledAssistants]);

  const unselectableSets = useMemo(() => {
    return documentSets.filter(documentSetContainsSync);
  }, [documentSets]);

  const memoizedPrivateConnectors = useMemo(() => {
    const uniqueDescriptors = new Map();
    documentSets.forEach((ds: DocumentSetSummary) => {
      const ccPairSummaries = getCcPairSummaries(ds);
      ccPairSummaries.forEach((summary: any) => {
        if (
          summary.access_type === "private" &&
          !uniqueDescriptors.has(summary.id)
        ) {
          uniqueDescriptors.set(summary.id, summary);
        }
      });
    });
    return Array.from(uniqueDescriptors.values());
  }, [documentSets]);

  const selectableSets = useMemo(() => {
    return documentSets.filter((ds) => !documentSetContainsSync(ds));
  }, [documentSets]);

  useEffect(() => {
    const invalidSelected = values.document_sets.filter((dsId: number) =>
      unselectableSets.some((us) => us.id === dsId)
    );
    if (invalidSelected.length > 0) {
      setFieldValue(
        "document_sets",
        values.document_sets.filter(
          (dsId: number) => !invalidSelected.includes(dsId)
        )
      );
      setPopup({
        message:
          "We removed one or more document sets from your selection because they are no longer valid. Please review and update your configuration.",
        type: "warning",
      });
    }
  }, [unselectableSets, values.document_sets, setFieldValue, setPopup]);

  const shouldShowPrivacyAlert = useMemo(() => {
    if (values.knowledge_source === "document_sets") {
      const selectedSets = documentSets.filter((ds) =>
        values.document_sets.includes(ds.id)
      );
      return selectedSets.some((ds) => documentSetContainsPrivate(ds));
    } else if (values.knowledge_source === "assistant") {
      const chosenAssistant = searchEnabledAssistants.find(
        (p) => p.id == values.persona_id
      );
      return chosenAssistant?.document_sets.some((ds) =>
        documentSetContainsPrivate(ds)
      );
    }
    return false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values.knowledge_source, values.document_sets, values.persona_id]);

  return (
    <>
      <div className="w-full">
        {isDefault && (
          <>
            <Badge variant="agent" className="bg-blue-100 text-blue-800">
              Default Configuration
            </Badge>
            <p className="mt-2 text-sm">
              This default configuration will apply to all channels and direct
              messages (DMs) in your Slack workspace.
            </p>
            <div className="mt-4 p-4 bg-background rounded-md border border-neutral-300">
              <CheckFormField
                name="disabled"
                label="Disable Default Configuration"
                labelClassName="text-text"
              />
              <p className="mt-2 text-sm italic">
                Warning: Disabling the default configuration means OnyxBot
                won&apos;t respond in Slack channels unless they are explicitly
                configured. Additionally, OnyxBot will not respond to DMs.
              </p>
            </div>
          </>
        )}
        {!isDefault && (
          <>
            <TextFormField
              name="channel_name"
              label="Slack Channel Name"
              placeholder="Enter channel name (e.g., general, support)"
              subtext="Enter the name of the Slack channel (without the # symbol)"
            />
          </>
        )}
        <div className="space-y-2 mt-4">
          <Label>Knowledge Source</Label>
          <RadioGroup
            className="flex flex-col gap-y-4"
            value={values.knowledge_source}
            onValueChange={(value: string) => {
              setFieldValue("knowledge_source", value);
            }}
          >
            <RadioGroupItemField
              value="all_public"
              id="all_public"
              label="All Public Knowledge"
              sublabel="Let OnyxBot respond based on information from all public connectors"
            />
            {selectableSets.length + unselectableSets.length > 0 && (
              <RadioGroupItemField
                value="document_sets"
                id="document_sets"
                label="Specific Document Sets"
                sublabel="Control which documents to use for answering questions"
              />
            )}
            <RadioGroupItemField
              value="assistant"
              id="assistant"
              label="Search Assistant"
              sublabel="Control both the documents and the prompt to use for answering questions"
            />
            <RadioGroupItemField
              value="non_search_assistant"
              id="non_search_assistant"
              label="Non-Search Assistant"
              sublabel="Chat with an assistant that does not use documents"
            />
          </RadioGroup>
        </div>
        {values.knowledge_source === "document_sets" &&
          documentSets.length > 0 && (
            <div className="mt-4">
              <SubLabel>
                <>
                  Select the document sets OnyxBot will use while answering
                  questions in Slack.
                  <br />
                  {unselectableSets.length > 0 ? (
                    <span>
                      Some incompatible document sets are{" "}
                      {viewUnselectableSets ? "visible" : "hidden"}.{" "}
                      <button
                        type="button"
                        onClick={() =>
                          setViewUnselectableSets(
                            (viewUnselectableSets) => !viewUnselectableSets
                          )
                        }
                        className="text-sm text-link"
                      >
                        {viewUnselectableSets
                          ? "Hide un-selectable "
                          : "View all "}
                        document sets
                      </button>
                    </span>
                  ) : (
                    ""
                  )}
                </>
              </SubLabel>
              <FieldArray
                name="document_sets"
                render={(arrayHelpers) => (
                  <>
                    {selectableSets.length > 0 && (
                      <div className="mb-3 mt-2 flex gap-2 flex-wrap text-sm">
                        {selectableSets.map((documentSet) => {
                          const selectedIndex = values.document_sets.indexOf(
                            documentSet.id
                          );
                          const isSelected = selectedIndex !== -1;

                          return (
                            <DocumentSetSelectable
                              key={documentSet.id}
                              documentSet={documentSet}
                              isSelected={isSelected}
                              onSelect={() => {
                                if (isSelected) {
                                  arrayHelpers.remove(selectedIndex);
                                } else {
                                  arrayHelpers.push(documentSet.id);
                                }
                              }}
                            />
                          );
                        })}
                      </div>
                    )}

                    {viewUnselectableSets && unselectableSets.length > 0 && (
                      <div className="mt-4">
                        <p className="text-sm text-text-dark/80">
                          These document sets cannot be attached as they have
                          auto-synced docs:
                        </p>
                        <div className="mb-3 mt-2 flex gap-2 flex-wrap text-sm">
                          {unselectableSets.map((documentSet) => (
                            <DocumentSetSelectable
                              key={documentSet.id}
                              documentSet={documentSet}
                              disabled
                              disabledTooltip="Unable to use this document set because it contains a connector with auto-sync permissions. OnyxBot's responses in this channel are visible to all Slack users, so mirroring the asker's permissions could inadvertently expose private information."
                              isSelected={false}
                              onSelect={() => {}}
                            />
                          ))}
                        </div>
                      </div>
                    )}
                    <ErrorMessage
                      className="text-red-500 text-sm mt-1"
                      name="document_sets"
                      component="div"
                    />
                  </>
                )}
              />
            </div>
          )}
        {values.knowledge_source === "assistant" && (
          <div className="mt-4">
            <SubLabel>
              <>
                Select the search-enabled assistant OnyxBot will use while
                answering questions in Slack.
                {syncEnabledAssistants.length > 0 && (
                  <>
                    <br />
                    <span className="text-sm text-text-dark/80">
                      Note: Some of your assistants have auto-synced connectors
                      in their document sets. You cannot select these assistants
                      as they will not be able to answer questions in Slack.{" "}
                      <button
                        type="button"
                        onClick={() =>
                          setViewSyncEnabledAssistants(
                            (viewSyncEnabledAssistants) =>
                              !viewSyncEnabledAssistants
                          )
                        }
                        className="text-sm text-link"
                      >
                        {viewSyncEnabledAssistants
                          ? "Hide un-selectable "
                          : "View all "}
                        assistants
                      </button>
                    </span>
                  </>
                )}
              </>
            </SubLabel>

            <SelectorFormField
              name="persona_id"
              options={availableAssistants.map((persona) => ({
                name: persona.name,
                value: persona.id,
              }))}
            />
            {viewSyncEnabledAssistants && syncEnabledAssistants.length > 0 && (
              <div className="mt-4">
                <p className="text-sm text-text-dark/80">
                  Un-selectable assistants:
                </p>
                <div className="mb-3 mt-2 flex gap-2 flex-wrap text-sm">
                  {syncEnabledAssistants.map(
                    (persona: MinimalPersonaSnapshot) => (
                      <button
                        type="button"
                        onClick={() =>
                          router.push(`/admin/assistants/${persona.id}`)
                        }
                        key={persona.id}
                        className="p-2 bg-background-100 cursor-pointer rounded-md flex items-center gap-2"
                      >
                        <AssistantIcon
                          assistant={persona}
                          size={16}
                          className="flex-none"
                        />
                        {persona.name}
                      </button>
                    )
                  )}
                </div>
              </div>
            )}
          </div>
        )}
        {values.knowledge_source === "non_search_assistant" && (
          <div className="mt-4">
            <SubLabel>
              <>
                Select the non-search assistant OnyxBot will use while answering
                questions in Slack.
                {syncEnabledAssistants.length > 0 && (
                  <>
                    <br />
                    <span className="text-sm text-text-dark/80">
                      Note: Some of your assistants have auto-synced connectors
                      in their document sets. You cannot select these assistants
                      as they will not be able to answer questions in Slack.{" "}
                      <button
                        type="button"
                        onClick={() =>
                          setViewSyncEnabledAssistants(
                            (viewSyncEnabledAssistants) =>
                              !viewSyncEnabledAssistants
                          )
                        }
                        className="text-sm text-link"
                      >
                        {viewSyncEnabledAssistants
                          ? "Hide un-selectable "
                          : "View all "}
                        assistants
                      </button>
                    </span>
                  </>
                )}
              </>
            </SubLabel>

            <SelectorFormField
              name="persona_id"
              options={nonSearchAssistants.map((persona) => ({
                name: persona.name,
                value: persona.id,
              }))}
            />
          </div>
        )}
      </div>
      <Separator className="my-4" />
      <Accordion type="multiple" className="gap-y-2 w-full">
        {values.knowledge_source !== "non_search_assistant" && (
          <AccordionItem value="search-options">
            <AccordionTrigger className="text-text">
              Search Configuration
            </AccordionTrigger>
            <AccordionContent>
              <div className="space-y-4">
                <div className="w-64">
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
                <CheckFormField
                  name="enable_auto_filters"
                  label="Enable LLM Autofiltering"
                  tooltip="If set, the LLM will generate source and time filters based on the user's query"
                />

                <CheckFormField
                  name="answer_validity_check_enabled"
                  label="Only respond if citations found"
                  tooltip="If set, will only answer questions where the model successfully produces citations"
                />
              </div>
            </AccordionContent>
          </AccordionItem>
        )}

        <AccordionItem className="mt-4" value="general-options">
          <AccordionTrigger>General Configuration</AccordionTrigger>
          <AccordionContent className="overflow-visible">
            <div className="space-y-4">
              <CheckFormField
                name="show_continue_in_web_ui"
                label="Show Continue in Web UI button"
                tooltip="If set, will show a button at the bottom of the response that allows the user to continue the conversation in the Onyx Web UI"
              />

              <CheckFormField
                name="still_need_help_enabled"
                onChange={(checked: boolean) => {
                  setFieldValue("still_need_help_enabled", checked);
                  if (!checked) {
                    setFieldValue("follow_up_tags", []);
                  }
                }}
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
                        The Slack users / groups we should tag if the user
                        clicks the &quot;Still need help?&quot; button. If no
                        emails are provided, we will not tag anyone and will
                        just react with a 🆘 emoji to the original message.
                      </div>
                    }
                    placeholder="User email or user group name..."
                  />
                </CollapsibleSection>
              )}

              <CheckFormField
                name="questionmark_prefilter_enabled"
                label="Only respond to questions"
                tooltip="If set, OnyxBot will only respond to messages that contain a question mark"
              />
              <CheckFormField
                name="respond_tag_only"
                label="Respond to @OnyxBot Only"
                tooltip="If set, OnyxBot will only respond when directly tagged"
              />
              <CheckFormField
                name="respond_to_bots"
                label="Respond to Bot messages"
                tooltip="If not set, OnyxBot will always ignore messages from Bots"
              />
              <CheckFormField
                name="is_ephemeral"
                label="Respond to user in a private (ephemeral) message"
                tooltip="If set, OnyxBot will respond only to the user in a private (ephemeral) message. If you also 
                chose 'Search' Assistant above, selecting this option will make documents that are private to the user 
                available for their queries."
              />

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

              <StandardAnswerCategoryDropdownField
                standardAnswerCategoryResponse={standardAnswerCategoryResponse}
                categories={values.standard_answer_categories}
                setCategories={(categories: any) =>
                  setFieldValue("standard_answer_categories", categories)
                }
              />
            </div>
          </AccordionContent>
        </AccordionItem>
      </Accordion>

      <div className="flex mt-8 gap-x-2 w-full justify-end">
        {shouldShowPrivacyAlert && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex hover:bg-background-150 cursor-pointer p-2 rounded-lg items-center">
                  <AlertCircle className="h-5 w-5 text-alert" />
                </div>
              </TooltipTrigger>
              <TooltipContent side="top" className="bg-background p-4 w-80">
                <Label className="text-text mb-2 font-semibold">
                  Privacy Alert
                </Label>
                <p className="text-sm text-text-darker mb-4">
                  Please note that if the private (ephemeral) response is *not
                  selected*, only public documents within the selected document
                  sets will be accessible for user queries. If the private
                  (ephemeral) response *is selected*, user quries can also
                  leverage documents that the user has already been granted
                  access to. Note that users will be able to share the response
                  with others in the channel, so please ensure that this is
                  aligned with your company sharing policies.
                </p>
                <div className="space-y-2">
                  <h4 className="text-sm text-text font-medium">
                    Relevant Connectors:
                  </h4>
                  <div className="max-h-40 overflow-y-auto border-t border-text-subtle flex-col gap-y-2">
                    {memoizedPrivateConnectors.map(
                      (ccpairinfo: CCPairDescriptor<any, any>) => (
                        <Link
                          key={ccpairinfo.id}
                          href={`/admin/connector/${ccpairinfo.id}`}
                          className="flex items-center p-2 rounded-md hover:bg-background-100 transition-colors"
                        >
                          <div className="mr-2">
                            <SourceIcon
                              iconSize={16}
                              sourceType={ccpairinfo.connector.source}
                            />
                          </div>
                          <span className="text-sm text-text-darker font-medium">
                            {ccpairinfo.name}
                          </span>
                        </Link>
                      )
                    )}
                  </div>
                </div>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
        <Button type="submit">{isUpdate ? "Update" : "Create"}</Button>
        <Button type="button" secondary onClick={() => router.back()}>
          Cancel
        </Button>
      </div>
    </>
  );
}
