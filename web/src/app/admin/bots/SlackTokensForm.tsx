"use client";

import { TextFormField } from "@/components/Field";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { createSlackBot, updateSlackBot } from "./new/lib";
import { Button } from "@opal/components";
import Separator from "@/refresh-components/Separator";
import { useEffect } from "react";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { toast } from "@/hooks/useToast";
import { useTranslations } from "next-intl";

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
  useEffect(() => {
    if (onValuesChange) {
      onValuesChange(initialValues);
    }
  }, [initialValues, onValuesChange]);

  const t = useTranslations("admin.slackBots");
  const tc = useTranslations("common");

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
              ? t("updatedSuccessfully")
              : t("createdSuccessfully")
          );
          router.push(`/admin/bots/${encodeURIComponent(botId)}`);
        } else {
          const responseJson = await response.json();
          let errorMsg = responseJson.detail || responseJson.message;

          if (errorMsg.includes("Invalid bot token:")) {
            errorMsg = t("botTokenInvalid");
          } else if (errorMsg.includes("Invalid app token:")) {
            errorMsg = t("appTokenInvalid");
          }
          toast.error(
            isUpdate
              ? `${t("errorUpdating")} - ${errorMsg}`
              : `${t("errorCreating")} - ${errorMsg}`
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
                label={t("nameThisBot")}
                type="text"
              />
            </div>
          )}

          {!isUpdate && (
            <div className="mt-4">
              <Separator />
              {t("referGuide")}{" "}
              <a
                className="text-blue-500 hover:underline"
                href={`${DOCS_ADMINS_PATH}/getting_started/slack_bot_setup`}
                target="_blank"
                rel="noopener noreferrer"
              >
                guide
              </a>{" "}
              if you are not sure how to get these tokens!
            </div>
          )}
          <TextFormField
            name="bot_token"
            label={t("botToken")}
            type="password"
          />
          <TextFormField
            name="app_token"
            label={t("appToken")}
            type="password"
          />
          <TextFormField
            name="user_token"
            label={t("userToken")}
            type="password"
            subtext={t("userTokenSubtext")}
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
              {isUpdate ? tc("update") : tc("create")}
            </Button>
          </div>
        </Form>
      )}
    </Formik>
  );
};
