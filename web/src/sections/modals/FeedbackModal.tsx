"use client";

import { FeedbackType } from "@/app/chat/interfaces";
import Button from "@/refresh-components/buttons/Button";
import { usePopup } from "@/components/admin/connectors/Popup";
import useFeedbackController from "@/hooks/useFeedbackController";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { SvgThumbsDown, SvgThumbsUp } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import { Formik } from "formik";
import * as Yup from "yup";
import * as InputLayouts from "@/layouts/input-layouts";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";

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
  const modal = useModal();
  const { popup, setPopup } = usePopup();
  const { handleFeedbackChange } = useFeedbackController({ setPopup });

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
      {popup}

      <Modal open={modal.isOpen} onOpenChange={modal.toggle}>
        <Modal.Content mini>
          <Modal.Header
            icon={feedbackType === "like" ? SvgThumbsUp : SvgThumbsDown}
            title="Feedback"
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
                  <InputLayouts.Vertical
                    name="additional_feedback"
                    label="Provide Additional Details"
                    optional={feedbackType === "like"}
                  >
                    <InputTextAreaField
                      name="additional_feedback"
                      placeholder={`What did you ${feedbackType} about this response?`}
                    />
                  </InputLayouts.Vertical>
                </Modal.Body>

                <Modal.Footer>
                  <Button
                    onClick={() => modal.toggle(false)}
                    secondary
                    type="button"
                  >
                    Cancel
                  </Button>
                  <Button
                    onClick={() => formikHandleSubmit()}
                    disabled={
                      isSubmitting ||
                      (feedbackType === "dislike" && (!dirty || !isValid))
                    }
                  >
                    {isSubmitting ? "Submitting..." : "Submit"}
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
