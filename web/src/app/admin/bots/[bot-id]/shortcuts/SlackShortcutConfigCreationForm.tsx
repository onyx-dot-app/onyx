"use client";

import React, { useMemo } from "react";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { usePopup } from "@/components/admin/connectors/Popup";
import {
  DocumentSet,
  SlackShortcutConfig,
  SlackBotResponseType,
} from "@/lib/types";
import {
  createSlackShortcutConfig,
  isPersonaASlackBotPersona,
  updateSlackShortcutConfig,
} from "../shortcuts-lib";
import CardSection from "@/components/admin/CardSection";
import { useRouter } from "next/navigation";
import { Persona } from "@/app/admin/assistants/interfaces";
import { StandardAnswerCategoryResponse } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";
import { SEARCH_TOOL_ID } from "@/app/chat/tools/constants";
import { SlackShortcutConfigFormFields } from "./SlackShortcutConfigFormFields";

export const SlackShortcutConfigCreationForm = ({
  slack_bot_id,
  documentSets,
  personas,
  standardAnswerCategoryResponse,
  existingSlackShortcutConfig,
}: {
  slack_bot_id: number;
  documentSets: DocumentSet[];
  personas: Persona[];
  standardAnswerCategoryResponse: StandardAnswerCategoryResponse;
  existingSlackShortcutConfig?: SlackShortcutConfig;
}) => {
  const { popup, setPopup } = usePopup();
  const router = useRouter();
  const isUpdate = Boolean(existingSlackShortcutConfig);
  const isDefault = existingSlackShortcutConfig?.is_default || false;
  const existingSlackBotUsesPersona = existingSlackShortcutConfig?.persona
    ? !isPersonaASlackBotPersona(existingSlackShortcutConfig.persona)
    : false;
  const existingPersonaHasSearchTool = existingSlackShortcutConfig?.persona
    ? existingSlackShortcutConfig.persona.tools.some(
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
          shortcut_name: isDefault
            ? ""
            : existingSlackShortcutConfig?.shortcut_config.shortcut_name || "",
          default_message: isDefault
            ? ""
            : existingSlackShortcutConfig?.shortcut_config.default_message || "",
          response_type: "citations" as SlackBotResponseType,
          answer_validity_check_enabled: (
            existingSlackShortcutConfig?.shortcut_config?.answer_filters || []
          ).includes("well_answered_postfilter"),
          is_ephemeral:
            existingSlackShortcutConfig?.shortcut_config?.is_ephemeral || false,
          show_continue_in_web_ui:
            existingSlackShortcutConfig?.shortcut_config
              ?.show_continue_in_web_ui ?? !isUpdate,
          enable_auto_filters:
            existingSlackShortcutConfig?.enable_auto_filters || false,
          respond_member_group_list:
            existingSlackShortcutConfig?.shortcut_config
              ?.respond_member_group_list || [],
          still_need_help_enabled:
            existingSlackShortcutConfig?.shortcut_config?.follow_up_tags !==
            undefined,
          follow_up_tags:
            existingSlackShortcutConfig?.shortcut_config?.follow_up_tags ||
            undefined,
          document_sets:
            existingSlackShortcutConfig && existingSlackShortcutConfig.persona
              ? existingSlackShortcutConfig.persona.document_sets.map(
                  (documentSet) => documentSet.id
                )
              : ([] as number[]),
          persona_id:
            existingSlackShortcutConfig?.persona &&
            !isPersonaASlackBotPersona(existingSlackShortcutConfig.persona)
              ? existingSlackShortcutConfig.persona.id
              : null,
          standard_answer_categories:
            existingSlackShortcutConfig?.standard_answer_categories || [],
          knowledge_source: existingSlackBotUsesPersona
            ? existingPersonaHasSearchTool
              ? "assistant"
              : "non_search_assistant"
            : existingSlackShortcutConfig?.persona
              ? "document_sets"
              : "all_public",
          disabled:
            existingSlackShortcutConfig?.shortcut_config?.disabled ?? false,
        }}
        validationSchema={Yup.object().shape({
          slack_bot_id: Yup.number().required(),
          shortcut_name: isDefault
            ? Yup.string()
            : Yup.string().required("Shortcut Name is required"),
          default_message: Yup.string(),
          response_type: Yup.mixed<SlackBotResponseType>()
            .oneOf(["quotes", "citations"])
            .required(),
          answer_validity_check_enabled: Yup.boolean().required(),
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
            shortcut_name: values.shortcut_name,
            default_message: values.default_message,
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
            ? await updateSlackShortcutConfig(
                existingSlackShortcutConfig!.id,
                cleanedValues
              )
            : await createSlackShortcutConfig(cleanedValues);

          formikHelpers.setSubmitting(false);
          if (response.ok) {
            router.push(`/admin/bots/${slack_bot_id}`);
          } else {
            const responseJson = await response.json();
            const errorMsg = responseJson.detail || responseJson.message;
            setPopup({
              message: `Error ${
                isUpdate ? "updating" : "creating"
              } OnyxBot shortcut config - ${errorMsg}`,
              type: "error",
            });
          }
        }}
      >
        {({ isSubmitting, values, setFieldValue, ...formikProps }) => (
          <Form>
            <div className="pb-6 w-full">
              <SlackShortcutConfigFormFields
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