"use client";

import { TextFormField } from "@/components/Field";
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
          <TextFormField
            name="bot_token"
            label={t("tokensForm.botToken.label")}
            type="password"
          />
          <TextFormField
            name="app_token"
            label={t("tokensForm.appToken.label")}
            type="password"
          />
          <TextFormField
            name="user_token"
            label={t("tokensForm.userToken.label")}
            type="password"
            subtext={t("tokensForm.userToken.subtext")}
          />
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
