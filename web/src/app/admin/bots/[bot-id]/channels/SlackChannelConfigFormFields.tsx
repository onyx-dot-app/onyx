"use client";

import React, { useState, useEffect, useMemo } from "react";
import { FieldArray, Form, useFormikContext, ErrorMessage } from "formik";
import { CCPairDescriptor, DocumentSet } from "@/lib/types";
import {
  BooleanFormField,
  Label,
  SelectorFormField,
  SubLabel,
  TextArrayField,
  TextFormField,
} from "@/components/admin/connectors/Field";
import { Button } from "@/components/ui/button";
import { Persona } from "@/app/admin/assistants/interfaces";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import { DocumentSetSelectable } from "@/components/documentSet/DocumentSetSelectable";
import CollapsibleSection from "@/app/admin/assistants/CollapsibleSection";
import { StandardAnswerCategoryResponse } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";
import { StandardAnswerCategoryDropdownField } from "@/components/standardAnswers/StandardAnswerCategoryDropdown";
import { RadioGroup } from "@/components/ui/radio-group";
import { RadioGroupItemField } from "@/components/ui/RadioGroupItemField";
import { AlertCircle, View } from "lucide-react";
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

interface SlackChannelConfigFormFieldsProps {
  isUpdate: boolean;
  documentSets: DocumentSet[];
  searchEnabledAssistants: Persona[];
  standardAnswerCategoryResponse: StandardAnswerCategoryResponse;
  setPopup: (popup: {
    message: string;
    type: "error" | "success" | "warning";
  }) => void;
}

export function SlackChannelConfigFormFields({
  isUpdate,
  documentSets,
  searchEnabledAssistants,
  standardAnswerCategoryResponse,
  setPopup,
}: SlackChannelConfigFormFieldsProps) {
  const router = useRouter();
  const { values, setFieldValue } = useFormikContext<any>();
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);
  const [viewUnselectableSets, setViewUnselectableSets] = useState(false);
  const [viewSyncEnabledAssistants, setViewSyncEnabledAssistants] =
    useState(false);

  const documentSetContainsSync = (documentSet: DocumentSet) =>
    documentSet.cc_pair_descriptors.some(
      (descriptor) => descriptor.access_type === "sync"
    );

  const [syncEnabledAssistants, availableAssistants] = useMemo(() => {
    const sync: Persona[] = [];
    const available: Persona[] = [];

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
    return documentSets.filter((ds) =>
      ds.cc_pair_descriptors.some(
        (descriptor) => descriptor.access_type === "sync"
      )
    );
  }, [documentSets]);
  const memoizedPrivateConnectors = useMemo(() => {
    const uniqueDescriptors = new Map();
    documentSets.forEach((ds) => {
      ds.cc_pair_descriptors.forEach((descriptor) => {
        if (
          descriptor.access_type === "private" &&
          !uniqueDescriptors.has(descriptor.id)
        ) {
          uniqueDescriptors.set(descriptor.id, descriptor);
        }
      });
    });
    return Array.from(uniqueDescriptors.values());
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

  const documentSetContainsPrivate = (documentSet: DocumentSet) => {
    return documentSet.cc_pair_descriptors.some(
      (descriptor) => descriptor.access_type === "private"
    );
  };

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

  const selectableSets = useMemo(() => {
    return documentSets.filter(
      (ds) =>
        !ds.cc_pair_descriptors.some(
          (descriptor) => descriptor.access_type === "sync"
        )
    );
  }, [documentSets]);

  return (
    <Form className="px-6 max-w-4xl">
      <div className="pt-4 w-full">
        <TextFormField name="channel_name" label="Slack Channel Name:" />

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
              sublabel="Let OnyxBot respond based on information from all public connectors "
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
              label="Specific Assistant"
              sublabel="Control both the documents and the prompt to use for answering questions"
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
                  {syncEnabledAssistants.map((persona: Persona) => (
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
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="mt-2">
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
                      The Slack users / groups we should tag if the user clicks
                      the &quot;Still need help?&quot; button. If no emails are
                      provided, we will not tag anyone and will just react with
                      a 🆘 emoji to the original message.
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
              tooltip="If set, OnyxBot will only respond to messages that contain a question mark"
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
            standardAnswerCategoryResponse={standardAnswerCategoryResponse}
            categories={values.standard_answer_categories}
            setCategories={(categories: any) =>
              setFieldValue("standard_answer_categories", categories)
            }
          />
        </div>
      )}

      <div className="flex mt-2 gap-x-2 w-full justify-end flex">
        {shouldShowPrivacyAlert && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex hover:bg-background-150 cursor-pointer p-2 rounded-lg items-center">
                  <AlertCircle className="h-5 w-5 text-alert" />
                </div>
              </TooltipTrigger>
              <TooltipContent side="top" className="bg-white p-4 w-80">
                <Label className="text-text mb-2 font-semibold">
                  Privacy Alert
                </Label>
                <p className="text-sm text-text-darker mb-4">
                  Please note that at least one of the documents accessible by
                  your OnyxBot is marked as private and may contain sensitive
                  information. These documents will be accessible to all users
                  of this OnyxBot. Ensure this aligns with your intended
                  document sharing policy.
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
                          className="flex items-center p-2 rounded-md hover:bg-gray-100 transition-colors"
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
        <Button onClick={() => {}} type="submit">
          {isUpdate ? "Update" : "Create"}
        </Button>
        <Button type="button" variant="outline" onClick={() => router.back()}>
          Cancel
        </Button>
      </div>
    </Form>
  );
}
