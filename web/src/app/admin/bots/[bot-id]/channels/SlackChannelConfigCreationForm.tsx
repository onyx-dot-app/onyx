"use client";

import React, { useMemo } from "react";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { usePopup } from "@/components/admin/connectors/Popup";
import {
  DocumentSetSummary,
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
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { StandardAnswerCategoryResponse } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";
import { SEARCH_TOOL_ID } from "@/app/chat/components/tools/constants";
import { SlackChannelConfigFormFields } from "./SlackChannelConfigFormFields";

export const SlackChannelConfigCreationForm = ({
  slack_bot_id,
  documentSets,
  personas,
  standardAnswerCategoryResponse,
  existingSlackChannelConfig,
}: {
  slack_bot_id: number;
  documentSets: DocumentSetSummary[];
  personas: MinimalPersonaSnapshot[];
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
      [[], []] as [MinimalPersonaSnapshot[], MinimalPersonaSnapshot[]]
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
              ? "assistant"
              : "non_search_assistant"
            : existingSlackChannelConfig?.persona
              ? "document_sets"
              : "all_public",
          disabled:
            existingSlackChannelConfig?.channel_config?.disabled ?? false,
        }}
        validationSchema={Yup.object().shape({
          slack_bot_id: Yup.number().required(),
          channel_name: isDefault
            ? Yup.string()
            : Yup.string().required("Channel Name is required"),
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
              is: "document_sets",
              then: (schema) =>
                schema.min(
                  1,
                  "At least one Document Set is required when using the 'Document Sets' knowledge source"
                ),
            }),
          persona_id: Yup.number()
            .nullable()
            .when("knowledge_source", {
              is: "assistant",
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
              values.knowledge_source === "document_sets"
                ? values.document_sets
                : [],
            persona_id:
              values.knowledge_source === "assistant" ||
              values.knowledge_source === "non_search_assistant"
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
            router.push(`/admin/bots/${slack_bot_id}`);
          } else {
            const responseJson = await response.json();
            const errorMsg = responseJson.detail || responseJson.message;
            setPopup({
              message: `Error ${
                isUpdate ? "updating" : "creating"
              } OnyxBot config - ${errorMsg}`,
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
