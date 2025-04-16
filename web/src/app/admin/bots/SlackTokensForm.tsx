"use client";
import i18n from "i18next";
import k from "./../../../i18n/keys";

import { TextFormField } from "@/components/admin/connectors/Field";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { createSlackBot, updateSlackBot } from "./new/lib";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useEffect } from "react";
import { Switch } from "@/components/ui/switch";

export const SlackTokensForm = ({
  isUpdate,
  initialValues,
  existingSlackBotId,
  refreshSlackBot,
  setPopup,
  router,
  onValuesChange,
}: {
  isUpdate: boolean;
  initialValues: any;
  existingSlackBotId?: number;
  refreshSlackBot?: () => void;
  setPopup: (popup: { message: string; type: "error" | "success" }) => void;
  router: any;
  onValuesChange?: (values: any) => void;
}) => {
  useEffect(() => {
    if (onValuesChange) {
      onValuesChange(initialValues);
    }
  }, [initialValues]);

  return (
    <Formik
      initialValues={{
        ...initialValues,
      }}
      validationSchema={Yup.object().shape({
        bot_token: Yup.string().required(),
        app_token: Yup.string().required(),
        name: Yup.string().required(),
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
          setPopup({
            message: isUpdate
              ? i18n.t(k.SUCCESSFULLY_UPDATED_SLACK_BOT)
              : i18n.t(k.SUCCESSFULLY_CREATED_SLACK_BOT),

            type: "success",
          });
          router.push(`/admin/bots/${encodeURIComponent(botId)}`);
        } else {
          const responseJson = await response.json();
          let errorMsg = responseJson.detail || responseJson.message;

          if (errorMsg.includes("Invalid bot token:")) {
            errorMsg = i18n.t(k.SLACK_BOT_TOKEN_IS_INVALID);
          } else if (errorMsg.includes("Invalid app token:")) {
            errorMsg = i18n.t(k.SLACK_APP_TOKEN_IS_INVALID);
          }
          setPopup({
            message: isUpdate
              ? `${i18n.t(k.ERROR_UPDATING_SLACK_BOT)} ${errorMsg}`
              : `${i18n.t(k.ERROR_CREATING_SLACK_BOT)} ${errorMsg}`,
            type: "error",
          });
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
                label="Назовите этого бота Slack:"
                type="text"
              />
            </div>
          )}

          {!isUpdate && (
            <div className="mt-4">
              <Separator />
              {i18n.t(k.PLEASE_REFER_TO_OUR)}{" "}
              <a
                className="text-blue-500 hover:underline"
                href="https://docs.onyx.app/slack_bot_setup"
                target="_blank"
                rel="noopener noreferrer"
              >
                {i18n.t(k.GUIDE)}
              </a>{" "}
              {i18n.t(k.IF_YOU_ARE_NOT_SURE_HOW_TO_GET)}
            </div>
          )}
          <TextFormField
            name="bot_token"
            label="Токен бота Slack"
            type="password"
          />

          <TextFormField
            name="app_token"
            label="Токен приложения Slack"
            type="password"
          />

          <div className="flex justify-end w-full mt-4">
            <Button
              type="submit"
              disabled={
                isSubmitting ||
                !values.bot_token ||
                !values.app_token ||
                !values.name
              }
              variant="submit"
              size="default"
            >
              {isUpdate ? i18n.t(k.UPDATE1) : i18n.t(k.CREATE)}
            </Button>
          </div>
        </Form>
      )}
    </Formik>
  );
};
