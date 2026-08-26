"use client";

import { useState, useEffect, useMemo } from "react";
import { useTranslations } from "next-intl";
import { FieldArray, useFormikContext, ErrorMessage } from "formik";
import { DocumentSetSummary } from "@/lib/types";
import { toast } from "@opal/layouts";
import {
  Label,
  SelectorFormField,
  SubLabel,
  TextArrayField,
  TextFormField,
} from "@/components/Field";
import { Button, Divider } from "@opal/components";
import { MinimalAgent } from "@/lib/agents/types";
import DocumentSetCard from "@/sections/cards/DocumentSetCard";
import CollapsibleSection from "@/app/admin/agents/CollapsibleSection";
import { StandardAnswerCategoryResponse } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";
import { StandardAnswerCategoryDropdownField } from "@/components/standardAnswers/StandardAnswerCategoryDropdown";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import { RadioGroup } from "@/components/ui/radio-group";
import { RadioGroupItemField } from "@/components/ui/RadioGroupItemField";
import { AlertCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { Tooltip } from "@opal/components";
import { SourceIcon } from "@/components/SourceIcon";
import Link from "next/link";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { Badge } from "@/components/ui/badge";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { CheckboxField } from "@/refresh-components/form/LabeledCheckboxField";

export interface SlackChannelConfigFormFieldsProps {
  isUpdate: boolean;
  isDefault: boolean;
  documentSets: DocumentSetSummary[];
  searchEnabledAgents: MinimalAgent[];
  nonSearchAgents: MinimalAgent[];
  standardAnswerCategoryResponse: StandardAnswerCategoryResponse;
  slack_bot_id: number;
  formikProps: any;
}

export function SlackChannelConfigFormFields({
  isUpdate,
  isDefault,
  documentSets,
  searchEnabledAgents,
  nonSearchAgents,
  standardAnswerCategoryResponse,
  slack_bot_id,
  formikProps,
}: SlackChannelConfigFormFieldsProps) {
  const t = useTranslations("admin.slackBots");
  const router = useRouter();
  const { values, setFieldValue } = useFormikContext<any>();
  const [viewUnselectableSets, setViewUnselectableSets] = useState(false);
  const [viewSyncEnabledAgents, setViewSyncEnabledAgents] = useState(false);

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

  const [syncEnabledAgents, availableAgents] = useMemo(() => {
    const sync: MinimalAgent[] = [];
    const available: MinimalAgent[] = [];

    searchEnabledAgents.forEach((persona) => {
      const hasSyncSet = persona.document_sets.some(documentSetContainsSync);
      if (hasSyncSet) {
        sync.push(persona);
      } else {
        available.push(persona);
      }
    });

    return [sync, available];
  }, [searchEnabledAgents]);

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

  const searchAgentOptions = useMemo(
    () =>
      availableAgents.map((persona) => ({
        label: persona.name,
        value: String(persona.id),
      })),
    [availableAgents]
  );

  const nonSearchAgentOptions = useMemo(
    () =>
      nonSearchAgents.map((persona) => ({
        label: persona.name,
        value: String(persona.id),
      })),
    [nonSearchAgents]
  );

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
      toast.warning(t("form.removedDocumentSets.toast"));
    }
  }, [unselectableSets, values.document_sets, setFieldValue, t]);

  const shouldShowPrivacyAlert = useMemo(() => {
    if (values.knowledge_source === "document_sets") {
      const selectedSets = documentSets.filter((ds) =>
        values.document_sets.includes(ds.id)
      );
      return selectedSets.some((ds) => documentSetContainsPrivate(ds));
    } else if (values.knowledge_source === "assistant") {
      const chosenAgent = searchEnabledAgents.find(
        (p) => p.id == values.persona_id
      );
      return chosenAgent?.document_sets.some((ds) =>
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
              {t("form.defaultConfig.badge")}
            </Badge>
            <p className="mt-2 text-sm">
              {t("form.defaultConfig.description")}
            </p>
            <div className="mt-4 p-4 bg-background rounded-md border border-neutral-300">
              <CheckboxField
                name="disabled"
                label={t("form.disableDefault.label")}
                labelClassName="text-text"
              />
              <p className="mt-2 text-sm italic">
                {t("form.disableDefault.warning")}
              </p>
            </div>
          </>
        )}
        {!isDefault && (
          <>
            <TextFormField
              name="channel_name"
              label={t("form.channelName.label")}
              placeholder={t("form.channelName.placeholder")}
              subtext={t("form.channelName.subtext")}
            />
          </>
        )}
        <div className="space-y-2 mt-4">
          <Label>{t("form.knowledgeSource.label")}</Label>
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
              label={t("form.knowledgeSource.allPublic.label")}
              sublabel={t("form.knowledgeSource.allPublic.sublabel")}
            />
            {selectableSets.length + unselectableSets.length > 0 && (
              <RadioGroupItemField
                value="document_sets"
                id="document_sets"
                label={t("form.knowledgeSource.documentSets.label")}
                sublabel={t("form.knowledgeSource.documentSets.sublabel")}
              />
            )}
            <RadioGroupItemField
              value="assistant"
              id="assistant"
              label={t("form.knowledgeSource.searchAgent.label")}
              sublabel={t("form.knowledgeSource.searchAgent.sublabel")}
            />
            <RadioGroupItemField
              value="non_search_agent"
              id="non_search_agent"
              label={t("form.knowledgeSource.nonSearchAgent.label")}
              sublabel={t("form.knowledgeSource.nonSearchAgent.sublabel")}
            />
          </RadioGroup>
        </div>
        {values.knowledge_source === "document_sets" &&
          documentSets.length > 0 && (
            <div className="mt-4">
              <SubLabel>
                <>
                  {t("form.documentSets.description")}
                  <br />
                  {unselectableSets.length > 0 ? (
                    <span>
                      {viewUnselectableSets
                        ? t("form.documentSets.incompatibleVisible.text")
                        : t("form.documentSets.incompatibleHidden.text")}{" "}
                      <button
                        type="button"
                        onClick={() =>
                          setViewUnselectableSets(
                            (viewUnselectableSets) => !viewUnselectableSets
                          )
                        }
                        className="text-sm text-action-selection-05"
                      >
                        {viewUnselectableSets
                          ? t("form.documentSets.hideUnselectableButton.label")
                          : t("form.documentSets.viewAllButton.label")}
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
                            <DocumentSetCard
                              key={documentSet.id}
                              documentSet={documentSet}
                              isSelected={isSelected}
                              onSelectToggle={(selected) => {
                                if (selected) arrayHelpers.push(documentSet.id);
                                else arrayHelpers.remove(selectedIndex);
                              }}
                            />
                          );
                        })}
                      </div>
                    )}

                    {viewUnselectableSets && unselectableSets.length > 0 && (
                      <div className="mt-4">
                        <p className="text-sm text-text-dark/80">
                          {t("form.documentSets.autoSyncedNote.text")}
                        </p>
                        <div className="mb-3 mt-2 flex gap-2 flex-wrap text-sm">
                          {unselectableSets.map((documentSet) => (
                            <DocumentSetCard
                              key={documentSet.id}
                              documentSet={documentSet}
                              disabled
                              disabledTooltip={t(
                                "form.documentSets.autoSyncedDisabled.tooltip"
                              )}
                              isSelected={false}
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
                {t("form.searchAgent.description")}
                {syncEnabledAgents.length > 0 && (
                  <>
                    <br />
                    <span className="text-sm text-text-dark/80">
                      {t("form.syncEnabledAgents.note")}{" "}
                      <button
                        type="button"
                        onClick={() =>
                          setViewSyncEnabledAgents(
                            (viewSyncEnabledAgents) => !viewSyncEnabledAgents
                          )
                        }
                        className="text-sm text-action-selection-05"
                      >
                        {viewSyncEnabledAgents
                          ? t("form.syncEnabledAgents.hideButton.label")
                          : t("form.syncEnabledAgents.viewAllButton.label")}
                      </button>
                    </span>
                  </>
                )}
              </>
            </SubLabel>

            <InputComboBox
              placeholder={t("form.agent.placeholder")}
              value={String(values.persona_id ?? "")}
              onValueChange={(val) =>
                setFieldValue("persona_id", val ? Number(val) : null)
              }
              options={searchAgentOptions}
              strict
            />
            {viewSyncEnabledAgents && syncEnabledAgents.length > 0 && (
              <div className="mt-4">
                <p className="text-sm text-text-dark/80">
                  {t("form.syncEnabledAgents.listLabel")}
                </p>
                <div className="mb-3 mt-2 flex gap-2 flex-wrap text-sm">
                  {syncEnabledAgents.map((persona: MinimalAgent) => (
                    <button
                      type="button"
                      onClick={() =>
                        router.push(`/app/agents/edit/${persona.id}` as Route)
                      }
                      key={persona.id}
                      className="p-2 bg-background-100 cursor-pointer rounded-md flex items-center gap-2"
                    >
                      <AgentAvatar agent={persona} size={16} />
                      {persona.name}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        {values.knowledge_source === "non_search_agent" && (
          <div className="mt-4">
            <SubLabel>
              <>
                {t("form.nonSearchAgent.description")}
                {syncEnabledAgents.length > 0 && (
                  <>
                    <br />
                    <span className="text-sm text-text-dark/80">
                      {t("form.syncEnabledAgents.note")}{" "}
                      <button
                        type="button"
                        onClick={() =>
                          setViewSyncEnabledAgents(
                            (viewSyncEnabledAgents) => !viewSyncEnabledAgents
                          )
                        }
                        className="text-sm text-action-selection-05"
                      >
                        {viewSyncEnabledAgents
                          ? t("form.syncEnabledAgents.hideButton.label")
                          : t("form.syncEnabledAgents.viewAllButton.label")}
                      </button>
                    </span>
                  </>
                )}
              </>
            </SubLabel>

            <InputComboBox
              placeholder={t("form.agent.placeholder")}
              value={String(values.persona_id ?? "")}
              onValueChange={(val) =>
                setFieldValue("persona_id", val ? Number(val) : null)
              }
              options={nonSearchAgentOptions}
              strict
            />
          </div>
        )}
      </div>
      <Divider />
      <Accordion type="multiple" className="gap-y-2 w-full">
        {values.knowledge_source !== "non_search_agent" && (
          <AccordionItem value="search-options">
            <AccordionTrigger className="text-text">
              {t("form.searchConfig.section.title")}
            </AccordionTrigger>
            <AccordionContent>
              <div className="space-y-4 pb-3">
                <div className="w-64">
                  <SelectorFormField
                    name="response_type"
                    label={t("form.responseType.label")}
                    tooltip={t("form.responseType.tooltip")}
                    options={[
                      {
                        name: t("form.responseType.standard.label"),
                        value: "citations",
                      },
                      {
                        name: t("form.responseType.detailed.label"),
                        value: "quotes",
                      },
                    ]}
                  />
                </div>
                <CheckboxField
                  name="answer_validity_check_enabled"
                  label={t("form.answerValidity.label")}
                  tooltip={t("form.answerValidity.tooltip")}
                />
              </div>
            </AccordionContent>
          </AccordionItem>
        )}

        <AccordionItem className="mt-4" value="general-options">
          <AccordionTrigger>
            {t("form.generalConfig.section.title")}
          </AccordionTrigger>
          <AccordionContent className="overflow-visible">
            <div className="space-y-4">
              <CheckboxField
                name="show_continue_in_web_ui"
                label={t("form.showContinueInWebUi.label")}
                tooltip={t("form.showContinueInWebUi.tooltip")}
              />

              <CheckboxField
                name="still_need_help_enabled"
                onChange={(checked: boolean) => {
                  setFieldValue("still_need_help_enabled", checked);
                  if (!checked) {
                    setFieldValue("follow_up_tags", []);
                  }
                }}
                label={t("form.stillNeedHelp.label")}
                tooltip={t("form.stillNeedHelp.tooltip")}
              />
              {values.still_need_help_enabled && (
                <CollapsibleSection
                  prompt={t("form.stillNeedHelp.section.prompt")}
                >
                  <TextArrayField
                    name="follow_up_tags"
                    label={t("form.followUpTags.label")}
                    values={values}
                    subtext={<div>{t("form.followUpTags.subtext")}</div>}
                    placeholder={t("form.userOrGroup.placeholder")}
                  />
                </CollapsibleSection>
              )}

              <CheckboxField
                name="questionmark_prefilter_enabled"
                label={t("form.questionmarkPrefilter.label")}
                tooltip={t("form.questionmarkPrefilter.tooltip")}
              />
              <CheckboxField
                name="respond_tag_only"
                label={t("form.respondTagOnly.label")}
                tooltip={t("form.respondTagOnly.tooltip")}
              />
              <CheckboxField
                name="respond_to_bots"
                label={t("form.respondToBots.label")}
                tooltip={t("form.respondToBots.tooltip")}
              />
              <CheckboxField
                name="is_ephemeral"
                label={t("form.isEphemeral.label")}
                tooltip={t("form.isEphemeral.tooltip")}
              />

              <TextArrayField
                name="respond_member_group_list"
                label={t("form.respondMemberGroupList.label")}
                subtext={t("form.respondMemberGroupList.subtext")}
                values={values}
                placeholder={t("form.userOrGroup.placeholder")}
                disabled={values.is_ephemeral}
                tooltip={
                  values.is_ephemeral
                    ? t("form.respondMemberGroupList.disabled.tooltip")
                    : undefined
                }
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
          <Tooltip
            side="top"
            tooltip={
              <div className="space-y-2">
                <Label className="text-text mb-2 font-semibold">
                  {t("form.privacyAlert.title")}
                </Label>
                <p className="text-sm text-text-darker mb-4">
                  {t("form.privacyAlert.description")}
                </p>
                <div className="space-y-2">
                  <h4 className="text-sm text-text font-medium">
                    {t("form.privacyAlert.connectors.title")}
                  </h4>
                  <div className="max-h-40 overflow-y-auto border-t border-text-subtle flex-col gap-y-2">
                    {memoizedPrivateConnectors.map((ccpairinfo: any) => (
                      <Link
                        key={ccpairinfo.id}
                        href={`/admin/connector/${ccpairinfo.id}`}
                        className="flex items-center p-2 rounded-md hover:bg-background-100 transition-colors"
                      >
                        <div className="mr-2">
                          <SourceIcon
                            iconSize={16}
                            sourceType={ccpairinfo.source}
                          />
                        </div>
                        <span className="text-sm text-text-darker font-medium">
                          {ccpairinfo.name}
                        </span>
                      </Link>
                    ))}
                  </div>
                </div>
              </div>
            }
          >
            <div className="flex hover:bg-background-150 cursor-pointer p-2 rounded-lg items-center">
              <AlertCircle className="h-5 w-5 text-alert" />
            </div>
          </Tooltip>
        )}
        <Button type="submit">
          {isUpdate
            ? t("form.updateButton.label")
            : t("form.createButton.label")}
        </Button>
        <Button prominence="secondary" onClick={() => router.back()}>
          {t("form.cancelButton.label")}
        </Button>
      </div>
    </>
  );
}
