"use client";

import { TextFormField } from "@/components/Field";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { createSlackBot, updateSlackBot } from "./new/lib";
import Button from "@/refresh-components/buttons/Button";
import { Separator } from "@/components/ui/separator";
import { useEffect } from "react";

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
          setPopup({
            message: isUpdate
              ? "Successfully updated Slack Bot!"
              : "Successfully created Slack Bot!",
            type: "success",
          });
          router.push(`/admin/bots/${encodeURIComponent(botId)}`);
        } else {
          const responseJson = await response.json();
          let errorMsg = responseJson.detail || responseJson.message;

          if (errorMsg.includes("Invalid bot token:")) {
            errorMsg = "Slack Bot Token is invalid";
          } else if (errorMsg.includes("Invalid app token:")) {
            errorMsg = "Slack App Token is invalid";
          }
          setPopup({
            message: isUpdate
              ? `Error updating Slack Bot - ${errorMsg}`
              : `Error creating Slack Bot - ${errorMsg}`,
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
                label="Name This Slack Bot:"
                type="text"
              />
            </div>
          )}

          {!isUpdate && (
            <div className="mt-4">
              <Separator />
              Please refer to our{" "}
              <a
                className="text-blue-500 hover:underline"
                href="https://docs.onyx.app/admin/getting_started/slack_bot_setup"
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
            label="Slack Bot Token"
            type="password"
          />
          <TextFormField
            name="app_token"
            label="Slack App Token"
            type="password"
          />
          <TextFormField
            name="user_token"
            label="Slack User Token (Optional)"
            type="password"
            subtext="Optional: User OAuth token for enhanced private channel access"
          />
          <div className="flex justify-end w-full mt-4">
            <Button
              disabled={
                isSubmitting ||
                !values.bot_token ||
                !values.app_token ||
                !values.name
              }
            >
              {isUpdate ? "Update" : "Create"}
            </Button>
          </div>
        </Form>
      )}
    </Formik>
  );
};
