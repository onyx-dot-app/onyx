"use client";
import i18n from "@/i18n/init";
import k from "./../../../../../i18n/keys";

import React, { useState, useEffect, useMemo } from "react";
import { FieldArray, useFormikContext, ErrorMessage, Field } from "formik";
import { CCPairDescriptor, DocumentSet } from "@/lib/types";
import {
  Label,
  SelectorFormField,
  SubLabel,
  TextArrayField,
  TextFormField,
} from "@/components/admin/connectors/Field";
import { Button } from "@/components/ui/button";
import { Persona } from "@/app/admin/assistants/interfaces";
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
import { SearchMultiSelectDropdown } from "@/components/Dropdown";
import { fetchSlackChannels } from "../lib";
import { Badge } from "@/components/ui/badge";
import useSWR from "swr";
import { ThreeDotsLoader } from "@/components/Loading";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Separator } from "@/components/ui/separator";

import { CheckFormField } from "@/components/ui/CheckField";
import { Input } from "@/components/ui/input";

export interface SlackChannelConfigFormFieldsProps {
  isUpdate: boolean;
  isDefault: boolean;
  documentSets: DocumentSet[];
  searchEnabledAssistants: Persona[];
  nonSearchAssistants: Persona[];
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
        message: i18n.t(k.WE_REMOVED_ONE_OR_MORE_DOCUMEN),

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

  const {
    data: channelOptions,
    error,
    isLoading,
  } = useSWR(
    `/api/manage/admin/slack-app/bots/${slack_bot_id}/channels`,
    async () => {
      const channels = await fetchSlackChannels(slack_bot_id);
      return channels.map((channel: any) => ({
        name: channel.name,
        value: channel.id,
      }));
    },
    {
      shouldRetryOnError: false, // don't spam the Slack API
      dedupingInterval: 60000, // Limit re-fetching to once per minute
    }
  );

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  return (
    <>
      <div className="w-full">
        {isDefault && (
          <>
            <Badge variant="agent" className="bg-blue-100 text-blue-800">
              {i18n.t(k.DEFAULT_CONFIGURATION)}
            </Badge>
            <p className="mt-2 text-sm text-neutral-600">
              {i18n.t(k.THIS_DEFAULT_CONFIGURATION_WIL)}
            </p>
            <div className="mt-4 p-4 bg-neutral-100 rounded-md border border-neutral-300">
              <CheckFormField
                name="disabled"
                label="Disable Default Configuration"
              />

              <p className="mt-2 text-sm text-neutral-600 italic">
                {i18n.t(k.WARNING_DISABLING_THE_DEFAULT)}
              </p>
            </div>
          </>
        )}
        {!isDefault && (
          <>
            <label
              htmlFor="channel_name"
              className="block  text-text font-medium text-base mb-2"
            >
              {i18n.t(k.SELECT_A_SLACK_CHANNEL)}
            </label>{" "}
            {error ? (
              <div>
                <div className="text-red-600 text-sm mb-4">
                  {error.message || i18n.t(k.UNABLE_TO_FETCH_SLACK_CHANNELS)}
                  {i18n.t(k.PLEASE_ENTER_THE_CHANNEL_NAME)}
                </div>
                <TextFormField
                  name="channel_name"
                  label="Название канала"
                  placeholder="Введите название канала"
                />
              </div>
            ) : (
              <>
                <Field name="channel_name">
                  {({ field, form }: { field: any; form: any }) => (
                    <SearchMultiSelectDropdown
                      options={channelOptions || []}
                      onSelect={(selected) => {
                        form.setFieldValue("channel_name", selected.name);
                      }}
                      initialSearchTerm={field.value}
                      onSearchTermChange={(term) => {
                        form.setFieldValue("channel_name", term);
                      }}
                      allowCustomValues={true}
                    />
                  )}
                </Field>
                <p className="mt-2 text-sm dark:text-neutral-400 text-neutral-600">
                  {i18n.t(k.NOTE_THIS_LIST_SHOWS_EXISTING)}
                </p>
              </>
            )}
          </>
        )}
        <div className="space-y-2 mt-4">
          <Label>{i18n.t(k.KNOWLEDGE_SOURCE)}</Label>
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
              label="Все общедоступные знания"
              sublabel="Позвольте OnyxBot реагировать на основе информации со всех публичных коннекторов"
            />

            {selectableSets.length + unselectableSets.length > 0 && (
              <RadioGroupItemField
                value="document_sets"
                id="document_sets"
                label="Конкретные наборы документов"
                sublabel="Контролируйте, какие документы использовать для ответов на вопросы"
              />
            )}
            <RadioGroupItemField
              value="assistant"
              id="assistant"
              label="Помощник по поиску"
              sublabel="Контролируйте как документы, так и подсказки, используемые для ответа на вопросы"
            />

            <RadioGroupItemField
              value="non_search_assistant"
              id="non_search_assistant"
              label="Помощник без поиска"
              sublabel="Чат с помощником, который не использует документы"
            />
          </RadioGroup>
        </div>
        {values.knowledge_source === "document_sets" &&
          documentSets.length > 0 && (
            <div className="mt-4">
              <SubLabel>
                <>
                  {i18n.t(k.SELECT_THE_DOCUMENT_SETS_ONYXB)}

                  <br />
                  {unselectableSets.length > 0 ? (
                    <span>
                      {i18n.t(k.SOME_INCOMPATIBLE_DOCUMENT_SET)}{" "}
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
                          ? i18n.t(k.HIDE_UN_SELECTABLE)
                          : i18n.t(k.VIEW_ALL)}
                        {i18n.t(k.DOCUMENT_SETS2)}
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
                          {i18n.t(k.THESE_DOCUMENT_SETS_CANNOT_BE)}
                        </p>
                        <div className="mb-3 mt-2 flex gap-2 flex-wrap text-sm">
                          {unselectableSets.map((documentSet) => (
                            <DocumentSetSelectable
                              key={documentSet.id}
                              documentSet={documentSet}
                              disabled
                              disabledTooltip="Невозможно использовать этот набор документов, поскольку он содержит коннектор с разрешениями автосинхронизации. Ответы OnyxBot в этом канале видны всем пользователям Slack, поэтому зеркалирование разрешений спрашивающего может непреднамеренно раскрыть личную информацию."
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
                {i18n.t(k.SELECT_THE_SEARCH_ENABLED_ASSI)}

                {syncEnabledAssistants.length > 0 && (
                  <>
                    <br />
                    <span className="text-sm text-text-dark/80">
                      {i18n.t(k.NOTE_SOME_OF_YOUR_ASSISTANTS)}{" "}
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
                          ? i18n.t(k.HIDE_UN_SELECTABLE)
                          : i18n.t(k.VIEW_ALL)}
                        {i18n.t(k.ASSISTANTS)}
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
                  {i18n.t(k.UN_SELECTABLE_ASSISTANTS)}
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
        {values.knowledge_source === "non_search_assistant" && (
          <div className="mt-4">
            <SubLabel>
              <>
                {i18n.t(k.SELECT_THE_NON_SEARCH_ASSISTAN)}

                {syncEnabledAssistants.length > 0 && (
                  <>
                    <br />
                    <span className="text-sm text-text-dark/80">
                      {i18n.t(k.NOTE_SOME_OF_YOUR_ASSISTANTS)}{" "}
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
                          ? i18n.t(k.HIDE_UN_SELECTABLE)
                          : i18n.t(k.VIEW_ALL)}
                        {i18n.t(k.ASSISTANTS)}
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
      <Accordion type="multiple" className=" gap-y-2 w-full">
        {values.knowledge_source !== "non_search_assistant" && (
          <AccordionItem value="search-options">
            <AccordionTrigger className="text-text">
              {i18n.t(k.SEARCH_CONFIGURATION)}
            </AccordionTrigger>
            <AccordionContent>
              <div className="space-y-4">
                <div className="w-64">
                  <SelectorFormField
                    name="response_type"
                    label="Тип ответа"
                    tooltip="Управляет форматом ответов OnyxBot."
                    options={[
                      { name: i18n.t(k.STANDARD1), value: "citations" },
                      { name: i18n.t(k.DETAILED), value: "quotes" },
                    ]}
                  />
                </div>
                <CheckFormField
                  name="enable_auto_filters"
                  label="Включить автофильтрацию LLM"
                  tooltip="Если установлено, LLM будет генерировать фильтры источника и времени на основе запроса пользователя."
                />

                <CheckFormField
                  name="answer_validity_check_enabled"
                  label="Отвечайте только в том случае, если найдены цитаты"
                  tooltip="Если установлено, будут отвечать только на те вопросы, где модель успешно производит цитаты"
                />
              </div>
            </AccordionContent>
          </AccordionItem>
        )}

        <AccordionItem className="mt-4" value="general-options">
          <AccordionTrigger>{i18n.t(k.GENERAL_CONFIGURATION)}</AccordionTrigger>
          <AccordionContent>
            <div className="space-y-4">
              <CheckFormField
                name="show_continue_in_web_ui"
                label="Показать кнопку «Продолжить» в веб-интерфейсе"
                tooltip="Если установлено, в нижней части ответа будет отображаться кнопка, позволяющая пользователю продолжить разговор в веб-интерфейсе Onyx."
              />

              <CheckFormField
                name="still_need_help_enabled"
                onChange={(checked: boolean) => {
                  setFieldValue("still_need_help_enabled", checked);
                  if (!checked) {
                    setFieldValue("follow_up_tags", []);
                  }
                }}
                label={"Дайте кнопку «Все еще нужна помощь?»"}
                tooltip={`${i18n.t(k.ONYXBOT_S_RESPONSE_WILL_INCLUD)}`}
              />

              {values.still_need_help_enabled && (
                <CollapsibleSection prompt="Настроить кнопку «Все еще нужна помощь»">
                  <TextArrayField
                    name="follow_up_tags"
                    label="(Необязательно) Пользователи/Группы для тегирования"
                    values={values}
                    subtext={
                      <div>{i18n.t(k.THE_SLACK_USERS_GROUPS_WE_SH)}</div>
                    }
                    placeholder="Адрес электронной почты пользователя или имя группы пользователей..."
                  />
                </CollapsibleSection>
              )}

              <CheckFormField
                name="questionmark_prefilter_enabled"
                label="Отвечайте только на вопросы"
                tooltip="Если установлено, OnyxBot будет отвечать только на сообщения, содержащие вопросительный знак."
              />

              <CheckFormField
                name="respond_tag_only"
                label="Отвечайте только @OnyxBot"
                tooltip="Если установлено, OnyxBot будет реагировать только при прямой пометке"
              />

              <CheckFormField
                name="respond_to_bots"
                label="Отвечайте на сообщения бота"
                tooltip="Если не установлено, OnyxBot всегда будет игнорировать сообщения от ботов."
              />

              <CheckFormField
                name="is_ephemeral"
                label="Ответить пользователю в личном (кратковременном) сообщении"
                tooltip="Если установлено, OnyxBot будет отвечать только пользователю в личном (эфемерном) сообщении. Если вы также выбрали помощника «Поиск» выше, выбор этого параметра сделает документы, которые являются личными для пользователя, доступными для его запросов."
              />

              <TextArrayField
                name="respond_member_group_list"
                label="(Необязательно) Ответить определенным пользователям/группам"
                subtext={
                  "Если указано, ответы OnyxBot будут видны только " +
                  "участникам или группам в этом списке."
                }
                values={values}
                placeholder="Адрес электронной почты пользователя или имя группы пользователей..."
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
              <TooltipContent side="top" className="bg-white p-4 w-80">
                <Label className="text-text mb-2 font-semibold">
                  {i18n.t(k.PRIVACY_ALERT)}
                </Label>
                <p className="text-sm text-text-darker mb-4">
                  {i18n.t(k.PLEASE_NOTE_THAT_IF_THE_PRIVAT)}
                </p>
                <div className="space-y-2">
                  <h4 className="text-sm text-text font-medium">
                    {i18n.t(k.RELEVANT_CONNECTORS)}
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
        <Button type="submit">
          {isUpdate ? i18n.t(k.UPDATE) : i18n.t(k.CREATE1)}
        </Button>
        <Button type="button" variant="outline" onClick={() => router.back()}>
          {i18n.t(k.CANCEL)}
        </Button>
      </div>
    </>
  );
}
