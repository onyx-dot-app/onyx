"use client";
import i18n from "i18next";
import k from "./../../../../../i18n/keys";

import React, { useMemo } from "react";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { usePopup } from "@/components/admin/connectors/Popup";
import {
  DocumentSet,
  SlackChannelConfig,
  SlackBotResponseType,
} from "@/lib/types";
import {
  createSlackChannelConfig,
  isPersonaASlackBotPersona,
  updateSlackChannelConfig,
} from "../lib";
import CardSection from "@/components/admin/CardSection";
import { useRouter } from "next/navigation";
import { Persona } from "@/app/admin/assistants/interfaces";
import { StandardAnswerCategoryResponse } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";
import { SEARCH_TOOL_ID } from "@/app/chat/tools/constants";
import { SlackChannelConfigFormFields } from "./SlackChannelConfigFormFields";

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
  const { popup, setPopup } = usePopup();
  const router = useRouter();
  const isUpdate = Boolean(existingSlackChannelConfig);
  const isDefault = existingSlackChannelConfig?.is_default || false;
  const existingSlackBotUsesPersona = existingSlackChannelConfig?.persona
    ? !isPersonaASlackBotPersona(existingSlackChannelConfig.persona)
    : false;
  const existingPersonaHasSearchTool = existingSlackChannelConfig?.persona
    ? existingSlackChannelConfig.persona.tools.some(
        (tool) => tool.in_code_tool_id === SEARCH_TOOL_ID
      )
    : false;

  const [searchEnabledAssistants, nonSearchAssistants] = useMemo(() => {
    return personas.reduce(
      (acc, persona) => {
        if (
          persona.tools.some((tool) => tool.in_code_tool_id === SEARCH_TOOL_ID)
        ) {
          acc[0].push(persona);
        } else {
          acc[1].push(persona);
        }
        return acc;
      },
      [[], []] as [Persona[], Persona[]]
    );
  }, [personas]);

  return (
    <CardSection className="!px-12 max-w-4xl">
      {popup}

      <Formik
        initialValues={{
          slack_bot_id: slack_bot_id,
          channel_name: isDefault
            ? ""
            : existingSlackChannelConfig?.channel_config.channel_name || "",
          response_type: "citations" as SlackBotResponseType,
          answer_validity_check_enabled: (
            existingSlackChannelConfig?.channel_config?.answer_filters || []
          ).includes("well_answered_postfilter"),
          questionmark_prefilter_enabled: (
            existingSlackChannelConfig?.channel_config?.answer_filters || []
          ).includes("questionmark_prefilter"),
          respond_tag_only:
            existingSlackChannelConfig?.channel_config?.respond_tag_only ||
            false,
          is_ephemeral:
            existingSlackChannelConfig?.channel_config?.is_ephemeral || false,
          respond_to_bots:
            existingSlackChannelConfig?.channel_config?.respond_to_bots ||
            false,
          show_continue_in_web_ui:
            existingSlackChannelConfig?.channel_config
              ?.show_continue_in_web_ui ?? !isUpdate,
          enable_auto_filters:
            existingSlackChannelConfig?.enable_auto_filters || false,
          respond_member_group_list:
            existingSlackChannelConfig?.channel_config
              ?.respond_member_group_list || [],
          still_need_help_enabled:
            existingSlackChannelConfig?.channel_config?.follow_up_tags !==
            undefined,
          follow_up_tags:
            existingSlackChannelConfig?.channel_config?.follow_up_tags ||
            undefined,
          document_sets:
            existingSlackChannelConfig && existingSlackChannelConfig.persona
              ? existingSlackChannelConfig.persona.document_sets.map(
                  (documentSet) => documentSet.id
                )
              : ([] as number[]),
          persona_id:
            existingSlackChannelConfig?.persona &&
            !isPersonaASlackBotPersona(existingSlackChannelConfig.persona)
              ? existingSlackChannelConfig.persona.id
              : null,
          standard_answer_categories:
            existingSlackChannelConfig?.standard_answer_categories || [],
          knowledge_source: existingSlackBotUsesPersona
            ? existingPersonaHasSearchTool
              ? i18n.t(k.ASSISTANT1)
              : i18n.t(k.NON_SEARCH_ASSISTANT)
            : existingSlackChannelConfig?.persona
            ? i18n.t(k.DOCUMENT_SETS1)
            : i18n.t(k.ALL_PUBLIC),

          disabled:
            existingSlackChannelConfig?.channel_config?.disabled ?? false,
        }}
        validationSchema={Yup.object().shape({
          slack_bot_id: Yup.number().required(),
          channel_name: isDefault
            ? Yup.string()
            : Yup.string().required(i18n.t(k.CHANNEL_NAME_IS_REQUIRED)),
          response_type: Yup.mixed<SlackBotResponseType>()
            .oneOf(["quotes", "citations"])
            .required(),
          answer_validity_check_enabled: Yup.boolean().required(),
          questionmark_prefilter_enabled: Yup.boolean().required(),
          respond_tag_only: Yup.boolean().required(),
          respond_to_bots: Yup.boolean().required(),
          is_ephemeral: Yup.boolean().required(),
          show_continue_in_web_ui: Yup.boolean().required(),
          enable_auto_filters: Yup.boolean().required(),
          respond_member_group_list: Yup.array().of(Yup.string()).required(),
          still_need_help_enabled: Yup.boolean().required(),
          follow_up_tags: Yup.array().of(Yup.string()),
          document_sets: Yup.array()
            .of(Yup.number())
            .when("knowledge_source", {
              is: i18n.t(k.DOCUMENT_SETS1),
              then: (schema) =>
                schema.min(
                  1,
                  "At least one Document Set is required when using the 'Document Sets' knowledge source"
                ),
            }),
          persona_id: Yup.number()
            .nullable()
            .when("knowledge_source", {
              is: i18n.t(k.ASSISTANT1),
              then: (schema) =>
                schema.required(
                  "A persona is required when using the'Assistant' knowledge source"
                ),
            }),
          standard_answer_categories: Yup.array(),
          knowledge_source: Yup.string()
            .oneOf([
              "all_public",
              "document_sets",
              "assistant",
              "non_search_assistant",
            ])
            .required(),
          disabled: Yup.boolean().optional().default(false),
        })}
        onSubmit={async (values, formikHelpers) => {
          formikHelpers.setSubmitting(true);

          const cleanedValues = {
            ...values,
            slack_bot_id,
            channel_name: values.channel_name,
            respond_member_group_list: values.respond_member_group_list,
            usePersona:
              values.knowledge_source === "assistant" ||
              values.knowledge_source === "non_search_assistant",
            document_sets:
              values.knowledge_source === i18n.t(k.DOCUMENT_SETS1)
                ? values.document_sets
                : [],
            persona_id:
              values.knowledge_source === i18n.t(k.ASSISTANT1) ||
              values.knowledge_source === i18n.t(k.NON_SEARCH_ASSISTANT)
                ? values.persona_id
                : null,
            standard_answer_categories: values.standard_answer_categories.map(
              (category: any) => category.id
            ),
            response_type: values.response_type as SlackBotResponseType,
            disabled: values.disabled ?? false,
          };

          if (!cleanedValues.still_need_help_enabled) {
            cleanedValues.follow_up_tags = undefined;
          } else {
            if (!cleanedValues.follow_up_tags) {
              cleanedValues.follow_up_tags = [];
            }
          }

          const response = isUpdate
            ? await updateSlackChannelConfig(
                existingSlackChannelConfig!.id,
                cleanedValues
              )
            : await createSlackChannelConfig(cleanedValues);

          formikHelpers.setSubmitting(false);
          if (response.ok) {
            router.push(`${i18n.t(k.ADMIN_BOTS)}${slack_bot_id}`);
          } else {
            const responseJson = await response.json();
            const errorMsg = responseJson.detail || responseJson.message;
            setPopup({
              message: `${i18n.t(k.ERROR2)} ${
                isUpdate ? i18n.t(k.UPDATING1) : i18n.t(k.CREATING1)
              } ${i18n.t(k.ONYXBOT_CONFIG)} ${errorMsg}`,
              type: "error",
            });
          }
        }}
      >
        {({ isSubmitting, values, setFieldValue, ...formikProps }) => (
          <Form>
            <div className="pb-6 w-full">
              <SlackChannelConfigFormFields
                {...values}
                isUpdate={isUpdate}
                isDefault={isDefault}
                documentSets={documentSets}
                searchEnabledAssistants={searchEnabledAssistants}
                nonSearchAssistants={nonSearchAssistants}
                standardAnswerCategoryResponse={standardAnswerCategoryResponse}
                setPopup={setPopup}
                slack_bot_id={slack_bot_id}
                formikProps={formikProps}
              />
            </div>
          </Form>
        )}
      </Formik>
    </CardSection>
  );
};
