"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FeedbackType } from "@/app/chat/interfaces";
import Button from "@/refresh-components/buttons/Button";
import FieldInput from "@/refresh-components/inputs/FieldInput";
import LineItem from "@/refresh-components/buttons/LineItem";
import { useKeyPress } from "@/hooks/useKeyPress";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useFeedbackController } from "../../hooks/useFeedbackController";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { SvgThumbsDown, SvgThumbsUp } from "@opal/icons";
import Modal from "@/refresh-components/Modal";

const predefinedPositiveFeedbackOptions = process.env
  .NEXT_PUBLIC_POSITIVE_PREDEFINED_FEEDBACK_OPTIONS
  ? process.env.NEXT_PUBLIC_POSITIVE_PREDEFINED_FEEDBACK_OPTIONS.split(",")
  : [];

const predefinedNegativeFeedbackOptions = process.env
  .NEXT_PUBLIC_NEGATIVE_PREDEFINED_FEEDBACK_OPTIONS
  ? process.env.NEXT_PUBLIC_NEGATIVE_PREDEFINED_FEEDBACK_OPTIONS.split(",")
  : [
      "Retrieved documents were not relevant",
      "AI misread the documents",
      "Cited source had incorrect information",
    ];

export interface FeedbackModalProps {
  feedbackType: FeedbackType;
  messageId: number;
}

export default function FeedbackModal({
  feedbackType,
  messageId,
}: FeedbackModalProps) {
  const modal = useModal();
  // const { isOpen, toggleModal, getModalData } = useChatModal();
  const [predefinedFeedback, setPredefinedFeedback] = useState<
    string | undefined
  >();
  const { popup, setPopup } = usePopup();
  const { handleFeedbackChange } = useFeedbackController({ setPopup });
  const fieldInputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = useCallback(async () => {
    if (
      (!predefinedFeedback || predefinedFeedback === "") &&
      (!fieldInputRef.current || fieldInputRef.current.value === "")
    )
      return;

    const feedbackText =
      fieldInputRef.current?.value || predefinedFeedback || "";

    const success = await handleFeedbackChange(
      messageId,
      feedbackType,
      feedbackText,
      predefinedFeedback
    );

    // Only close modal if submission was successful
    if (success) {
      modal.toggle(false);
    }
  }, [
    predefinedFeedback,
    feedbackType,
    handleFeedbackChange,
    messageId,
    modal.toggle,
  ]);

  useEffect(() => {
    if (predefinedFeedback) {
      handleSubmit();
    }
  }, [predefinedFeedback, handleSubmit]);

  useKeyPress(handleSubmit, "Enter");

  const predefinedFeedbackOptions =
    feedbackType === "like"
      ? predefinedPositiveFeedbackOptions
      : predefinedNegativeFeedbackOptions;

  const icon = feedbackType === "like" ? SvgThumbsUp : SvgThumbsDown;

  return (
    <>
      {popup}

      <Modal open={modal.isOpen} onOpenChange={modal.toggle}>
        <Modal.Content mini>
          <Modal.Header
            icon={icon}
            title="Provide Additional Feedback"
            onClose={() => modal.toggle(false)}
          />
          {predefinedFeedbackOptions.length > 0 && (
            <div className="flex flex-col p-4 gap-1">
              {predefinedFeedbackOptions.map((feedback, index) => (
                <LineItem
                  key={index}
                  onClick={() => setPredefinedFeedback(feedback)}
                >
                  {feedback}
                </LineItem>
              ))}
            </div>
          )}
          <Modal.Body>
            <FieldInput
              label="Feedback"
              placeholder={`What did you ${feedbackType} about this response?`}
              className="!w-full"
              ref={fieldInputRef}
            />
          </Modal.Body>
          <Modal.Footer>
            <Button onClick={() => modal.toggle(false)} secondary>
              Cancel
            </Button>
            <Button onClick={handleSubmit}>Submit</Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </>
  );
}
