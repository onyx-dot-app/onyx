import { Form, Formik } from "formik";
import * as Yup from "yup";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { SlackBotTokens } from "@/lib/types";
import { TextFormField } from "@/components/admin/connectors/Field";
import { setSlackBotTokens } from "./lib";
import CardSection from "@/components/admin/CardSection";
import { Button } from "@/components/ui/button";

interface SlackBotTokensFormProps {
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  existingTokens?: SlackBotTokens;
}

export const SlackBotTokensForm = ({
  onClose,
  setPopup,
  existingTokens,
}: SlackBotTokensFormProps) => {
  return (
    <CardSection>
      <Formik
        initialValues={existingTokens || { app_token: "", bot_token: "" }}
        validationSchema={Yup.object().shape({
          channel_names: Yup.array().of(Yup.string().required()),
          document_sets: Yup.array().of(Yup.number()),
        })}
        onSubmit={async (values, formikHelpers) => {
          formikHelpers.setSubmitting(true);
          const response = await setSlackBotTokens(values);
          formikHelpers.setSubmitting(false);
          if (response.ok) {
            setPopup({
              message: "Successfully set Slack tokens!",
              type: "success",
            });
            onClose();
          } else {
            const errorMsg = await response.text();
            setPopup({
              message: `Error setting Slack tokens - ${errorMsg}`,
              type: "error",
            });
          }
        }}
      >
        {({ isSubmitting }) => (
          <Form>
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
            <div className="flex">
              <Button type="submit" disabled={isSubmitting} variant="submit">
                Set Tokens
              </Button>
            </div>
          </Form>
        )}
      </Formik>
    </CardSection>
  );
};
