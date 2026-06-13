"use client";

import { useState, useEffect, useMemo } from "react";
import { FieldArray, useFormikContext, ErrorMessage } from "formik";
import { DocumentSetSummary } from "@/lib/types";
import { toast } from "@/hooks/useToast";
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
      toast.warning(
        "已从你的选择中移除一个或多个不再有效的文档集。请检查并更新配置。"
      );
    }
  }, [unselectableSets, values.document_sets, setFieldValue]);

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
              默认配置
            </Badge>
            <p className="mt-2 text-sm">
              此默认配置会应用到 Slack 工作区中的所有频道和私信（DM）。
            </p>
            <div className="mt-4 p-4 bg-background rounded-md border border-neutral-300">
              <CheckboxField
                name="disabled"
                label="禁用默认配置"
                labelClassName="text-text"
              />
              <p className="mt-2 text-sm italic">
                警告：禁用默认配置后，除非单独配置频道，否则 Glomi Bot
                不会在 Slack 频道中回复。此外，Glomi Bot 也不会回复私信。
              </p>
            </div>
          </>
        )}
        {!isDefault && (
          <>
            <TextFormField
              name="channel_name"
              label="Slack 频道名称"
              placeholder="输入频道名称（例如 general、support）"
              subtext="输入 Slack 频道名称（不包含 # 符号）"
            />
          </>
        )}
        <div className="space-y-2 mt-4">
          <Label>知识来源</Label>
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
              label="全部公开知识"
              sublabel="让 Glomi Bot 基于所有公开连接器中的信息回答"
            />
            {selectableSets.length + unselectableSets.length > 0 && (
              <RadioGroupItemField
                value="document_sets"
                id="document_sets"
                label="指定文档集"
                sublabel="控制回答问题时可使用的文档"
              />
            )}
            <RadioGroupItemField
              value="assistant"
              id="assistant"
              label="搜索智能体"
              sublabel="同时控制回答问题时使用的文档和提示词"
            />
            <RadioGroupItemField
              value="non_search_agent"
              id="non_search_agent"
              label="非搜索智能体"
              sublabel="与不使用文档的智能体对话"
            />
          </RadioGroup>
        </div>
        {values.knowledge_source === "document_sets" &&
          documentSets.length > 0 && (
            <div className="mt-4">
              <SubLabel>
                <>
                  选择 Glomi Bot 在 Slack 中回答问题时使用的文档集。
                  <br />
                  {unselectableSets.length > 0 ? (
                    <span>
                      部分不兼容的文档集当前
                      {viewUnselectableSets ? "已显示" : "已隐藏"}。{" "}
                      <button
                        type="button"
                        onClick={() =>
                          setViewUnselectableSets(
                            (viewUnselectableSets) => !viewUnselectableSets
                          )
                        }
                        className="text-sm text-action-link-05"
                      >
                        {viewUnselectableSets
                          ? "隐藏不可选择的"
                          : "查看全部"}
                        文档集
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
                          以下文档集包含自动同步文档，无法附加：
                        </p>
                        <div className="mb-3 mt-2 flex gap-2 flex-wrap text-sm">
                          {unselectableSets.map((documentSet) => (
                            <DocumentSetCard
                              key={documentSet.id}
                              documentSet={documentSet}
                              disabled
                              disabledTooltip="无法使用此文档集，因为它包含启用了自动同步权限的连接器。Glomi Bot 在此频道中的回答对所有 Slack 用户可见，镜像提问者权限可能会意外暴露私密信息。"
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
                选择 Glomi Bot 在 Slack 中回答问题时使用的搜索智能体。
                {syncEnabledAgents.length > 0 && (
                  <>
                    <br />
                    <span className="text-sm text-text-dark/80">
                      注意：部分智能体的文档集中包含自动同步连接器，因此无法选择；这些智能体无法在 Slack 中回答问题。{" "}
                      <button
                        type="button"
                        onClick={() =>
                          setViewSyncEnabledAgents(
                            (viewSyncEnabledAgents) => !viewSyncEnabledAgents
                          )
                        }
                        className="text-sm text-action-link-05"
                      >
                        {viewSyncEnabledAgents
                          ? "隐藏不可选择的"
                          : "查看全部"}
                        智能体
                      </button>
                    </span>
                  </>
                )}
              </>
            </SubLabel>

            <InputComboBox
              placeholder="搜索智能体..."
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
                  不可选择的智能体：
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
                选择 Glomi Bot 在 Slack 中回答问题时使用的非搜索智能体。
                {syncEnabledAgents.length > 0 && (
                  <>
                    <br />
                    <span className="text-sm text-text-dark/80">
                      注意：部分智能体的文档集中包含自动同步连接器，因此无法选择；这些智能体无法在 Slack 中回答问题。{" "}
                      <button
                        type="button"
                        onClick={() =>
                          setViewSyncEnabledAgents(
                            (viewSyncEnabledAgents) => !viewSyncEnabledAgents
                          )
                        }
                        className="text-sm text-action-link-05"
                      >
                        {viewSyncEnabledAgents
                          ? "隐藏不可选择的"
                          : "查看全部"}
                        智能体
                      </button>
                    </span>
                  </>
                )}
              </>
            </SubLabel>

            <InputComboBox
              placeholder="搜索智能体..."
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
              搜索配置
            </AccordionTrigger>
            <AccordionContent>
              <div className="space-y-4 pb-3">
                <div className="w-64">
                  <SelectorFormField
                    name="response_type"
                    label="回答类型"
                    tooltip="控制 Glomi Bot 回答的格式。"
                    options={[
                      { name: "标准", value: "citations" },
                      { name: "详细", value: "quotes" },
                    ]}
                  />
                </div>
                <CheckboxField
                  name="answer_validity_check_enabled"
                  label="仅在找到引用时回复"
                  tooltip="启用后，仅当模型成功生成引用时才回答问题"
                />
              </div>
            </AccordionContent>
          </AccordionItem>
        )}

        <AccordionItem className="mt-4" value="general-options">
          <AccordionTrigger>通用配置</AccordionTrigger>
          <AccordionContent className="overflow-visible">
            <div className="space-y-4">
              <CheckboxField
                name="show_continue_in_web_ui"
                label="显示“在网页端继续”按钮"
                tooltip="启用后，会在回答底部显示按钮，允许用户在 Glomi AI 网页端继续对话"
              />

              <CheckboxField
                name="still_need_help_enabled"
                onChange={(checked: boolean) => {
                  setFieldValue("still_need_help_enabled", checked);
                  if (!checked) {
                    setFieldValue("follow_up_tags", []);
                  }
                }}
                label={'提供“仍需帮助？”按钮'}
                tooltip="启用后，Glomi Bot 的回答底部会包含一个按钮，询问用户是否仍需帮助。"
              />
              {values.still_need_help_enabled && (
                <CollapsibleSection prompt="配置“仍需帮助？”按钮">
                  <TextArrayField
                    name="follow_up_tags"
                    label="（可选）要标记的用户 / 用户组"
                    values={values}
                    subtext={
                      <div>
                        用户点击“仍需帮助？”按钮时需要标记的 Slack 用户 / 用户组。
                        如果未提供邮箱，我们不会标记任何人，只会用 🆘 表情回应原消息。
                      </div>
                    }
                    placeholder="用户邮箱或用户组名称..."
                  />
                </CollapsibleSection>
              )}

              <CheckboxField
                name="questionmark_prefilter_enabled"
                label="仅回复问题"
                tooltip="启用后，Glomi Bot 只会回复包含问号的消息"
              />
              <CheckboxField
                name="respond_tag_only"
                label="仅在 @Glomi Bot 时回复"
                tooltip="启用后，Glomi Bot 只会在被直接提及时回复"
              />
              <CheckboxField
                name="respond_to_bots"
                label="回复机器人消息"
                tooltip="未启用时，Glomi Bot 会始终忽略来自机器人的消息"
              />
              <CheckboxField
                name="is_ephemeral"
                label="用私密（临时）消息回复用户"
                tooltip="启用后，Glomi Bot 只会通过私密（临时）消息回复该用户。如果上方选择了“搜索智能体”，启用此项会让该用户有权访问的私有文档也可用于查询。"
              />

              <TextArrayField
                name="respond_member_group_list"
                label="（可选）仅回复特定用户 / 用户组"
                subtext={
                  "指定后，只有这些用户 / 用户组可以在此频道中调用 Glomi Bot，且回答仅对他们可见。"
                }
                values={values}
                placeholder="用户邮箱或用户组名称..."
                disabled={values.is_ephemeral}
                tooltip={
                  values.is_ephemeral
                    ? "启用“用私密（临时）消息回复用户”时不可用，因为临时回复只面向单个用户。"
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
                  隐私提醒
                </Label>
                <p className="text-sm text-text-darker mb-4">
                  请注意：如果未选择私密（临时）回复，用户查询只能访问所选文档集中的公开文档。
                  如果选择了私密（临时）回复，用户查询也可以使用该用户已获授权访问的文档。
                  用户仍可将回答分享给频道中的其他人，请确保这符合你公司的共享政策。
                </p>
                <div className="space-y-2">
                  <h4 className="text-sm text-text font-medium">
                    相关连接器：
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
        <Button type="submit">{isUpdate ? "更新" : "创建"}</Button>
        <Button prominence="secondary" onClick={() => router.back()}>
          取消
        </Button>
      </div>
    </>
  );
}
