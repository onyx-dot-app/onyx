"use client";

import { FeedbackType } from "@/app/app/interfaces";
import { Button } from "@opal/components";
import useFeedbackController from "@/hooks/useFeedbackController";
import { useModal } from "@opal/components";
import { SvgThumbsDown, SvgThumbsUp } from "@opal/icons";
import { Modal } from "@opal/components";
import { Formik } from "formik";
import * as Yup from "yup";
import { InputVertical } from "@opal/layouts";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import { useTranslations } from "next-intl";

export interface FeedbackModalProps {
  feedbackType: FeedbackType;
  messageId: number;
}

interface FeedbackFormValues {
  additional_feedback: string;
}

export default function FeedbackModal({
  feedbackType,
  messageId,
}: FeedbackModalProps) {
  const t = useTranslations("chat.modals.feedback");
  const modal = useModal();
  const { handleFeedbackChange } = useFeedbackController();

  const initialValues: FeedbackFormValues = {
    additional_feedback: "",
  };

  const validationSchema = Yup.object({
    additional_feedback:
      feedbackType === "dislike"
        ? Yup.string().trim().required("Feedback is required")
        : Yup.string().trim(),
  });

  async function handleSubmit(values: FeedbackFormValues) {
    const feedbackText = values.additional_feedback;

    const success = await handleFeedbackChange(
      messageId,
      feedbackType,
      feedbackText,
      undefined
    );

    // Only close modal if submission was successful
    if (success) {
      modal.toggle(false);
    }
  }

  return (
    <>
      <Modal open={modal.isOpen} onOpenChange={modal.toggle}>
        <Modal.Content width="sm">
          <Modal.Header
            icon={feedbackType === "like" ? SvgThumbsUp : SvgThumbsDown}
            title={t("header.title")}
            onClose={() => modal.toggle(false)}
          />
          <Formik
            initialValues={initialValues}
            validationSchema={validationSchema}
            onSubmit={handleSubmit}
          >
            {({
              isSubmitting,
              handleSubmit: formikHandleSubmit,
              dirty,
              isValid,
            }) => (
              <>
                <Modal.Body>
                  <InputVertical
                    withLabel="additional_feedback"
                    title={t("additionalDetails.label")}
                    suffix={feedbackType === "like" ? "optional" : undefined}
                  >
                    <InputTextAreaField
                      name="additional_feedback"
                      placeholder={
                        feedbackType === "like"
                          ? t("additionalDetails.likePlaceholder")
                          : t("additionalDetails.dislikePlaceholder")
                      }
                    />
                  </InputVertical>
                </Modal.Body>

                <Modal.Footer>
                  <Button
                    prominence="secondary"
                    onClick={() => modal.toggle(false)}
                    type="button"
                  >
                    {t("cancelButton.label")}
                  </Button>
                  <Button
                    disabled={
                      isSubmitting ||
                      (feedbackType === "dislike" && (!dirty || !isValid))
                    }
                    onClick={() => formikHandleSubmit()}
                  >
                    {isSubmitting
                      ? t("submitButton.loadingLabel")
                      : t("submitButton.label")}
                  </Button>
                </Modal.Footer>
              </>
            )}
          </Formik>
        </Modal.Content>
      </Modal>
    </>
  );
}
