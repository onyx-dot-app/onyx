"use client";

import { FieldLabel, TextFormField } from "@/components/Field";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import { useTranslations } from "next-intl";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { createSlackBot, updateSlackBot } from "./new/lib";
import { Button, Divider } from "@opal/components";
import { useEffect } from "react";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { toast } from "@opal/layouts";

export const SlackTokensForm = ({
  isUpdate,
  initialValues,
  existingSlackBotId,
  refreshSlackBot,
  router,
  onValuesChange,
}: {
  isUpdate: boolean;
  initialValues: any;
  existingSlackBotId?: number;
  refreshSlackBot?: () => void;
  router: any;
  onValuesChange?: (values: any) => void;
}) => {
  const t = useTranslations("admin.slackBots");

  useEffect(() => {
    if (onValuesChange) {
      onValuesChange(initialValues);
    }
  }, [initialValues, onValuesChange]);

  return (
    <Formik
      initialValues={{
        ...initialValues,
      }}
      validationSchema={Yup.object().shape({
        bot_token: Yup.string().required(),
        app_token: Yup.string().required(),
        name: Yup.string().required(),
        user_token: Yup.string().optional(),
      })}
      onSubmit={async (values, formikHelpers) => {
        formikHelpers.setSubmitting(true);

        let response;
        if (isUpdate) {
          response = await updateSlackBot(existingSlackBotId!, values);
        } else {
          response = await createSlackBot(values);
        }
        formikHelpers.setSubmitting(false);
        if (response.ok) {
          if (refreshSlackBot) {
            refreshSlackBot();
          }
          const responseJson = await response.json();
          const botId = isUpdate ? existingSlackBotId : responseJson.id;
          toast.success(
            isUpdate
              ? t("tokensForm.updated.toast")
              : t("tokensForm.created.toast")
          );
          router.push(`/admin/bots/${encodeURIComponent(botId)}`);
        } else {
          const responseJson = await response.json();
          let errorMsg = responseJson.detail || responseJson.message;

          if (errorMsg.includes("Invalid bot token:")) {
            errorMsg = t("tokensForm.invalidBotToken.message");
          } else if (errorMsg.includes("Invalid app token:")) {
            errorMsg = t("tokensForm.invalidAppToken.message");
          }
          toast.error(
            isUpdate
              ? t("tokensForm.updateError.toast", { error: errorMsg })
              : t("tokensForm.createError.toast", { error: errorMsg })
          );
        }
      }}
      enableReinitialize={true}
    >
      {({ isSubmitting, setFieldValue, values }) => (
        <Form className="w-full">
          {!isUpdate && (
            <div className="">
              <TextFormField
                name="name"
                label={t("tokensForm.name.label")}
                type="text"
              />
            </div>
          )}

          {!isUpdate && (
            <div className="mt-4">
              <Divider />
              {t.rich("tokensForm.docsPrompt.text", {
                link: (chunks) => (
                  <a
                    className="text-blue-500 hover:underline"
                    href={`${DOCS_ADMINS_PATH}/getting_started/slack_bot_setup`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {chunks}
                  </a>
                ),
              })}
            </div>
          )}
          {/* On update, the tokens arrive masked from the backend. */}
          <div className="w-full">
            <FieldLabel
              name="bot_token"
              label={t("tokensForm.botToken.label")}
            />
            <div className="mt-1">
              <PasswordInputTypeInField
                name="bot_token"
                existingValue={
                  isUpdate ? (initialValues.bot_token ?? undefined) : undefined
                }
              />
            </div>
          </div>
          <div className="w-full">
            <FieldLabel
              name="app_token"
              label={t("tokensForm.appToken.label")}
            />
            <div className="mt-1">
              <PasswordInputTypeInField
                name="app_token"
                existingValue={
                  isUpdate ? (initialValues.app_token ?? undefined) : undefined
                }
              />
            </div>
          </div>
          <div className="w-full">
            <FieldLabel
              name="user_token"
              label={t("tokensForm.userToken.label")}
              subtext={t("tokensForm.userToken.subtext")}
            />
            <div className="mt-1">
              <PasswordInputTypeInField
                name="user_token"
                existingValue={
                  isUpdate ? (initialValues.user_token ?? undefined) : undefined
                }
              />
            </div>
          </div>
          <div className="flex justify-end w-full mt-4">
            <Button
              disabled={
                isSubmitting ||
                !values.bot_token ||
                !values.app_token ||
                !values.name
              }
              type="submit"
            >
              {isUpdate
                ? t("tokensForm.updateButton.label")
                : t("tokensForm.createButton.label")}
            </Button>
          </div>
        </Form>
      )}
    </Formik>
  );
};
