"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FeedbackType } from "@/app/chat/interfaces";
import { Modal } from "@/refresh-components/modals/NewModal";
import {
  ModalIds,
  useChatModal,
} from "@/refresh-components/contexts/ChatModalContext";
import SvgThumbsUp from "@/icons/thumbs-up";
import SvgThumbsDown from "@/icons/thumbs-down";
import Button from "@/refresh-components/buttons/Button";
import FieldInput from "@/refresh-components/inputs/FieldInput";
import LineItem from "@/refresh-components/buttons/LineItem";
import { useKeyPress } from "@/hooks/useKeyPress";

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

export const FeedbackModal = () => {
  const { isOpen, toggleModal, getModalData } = useChatModal();
  const data = getModalData<{
    feedbackType: FeedbackType;
    messageId: number;
    handleFeedbackChange?: (
      newFeedback: FeedbackType | null,
      feedbackText?: string,
      predefinedFeedback?: string
    ) => Promise<void>;
  }>();
  const [predefinedFeedback, setPredefinedFeedback] = useState<
    string | undefined
  >();
  const fieldInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isOpen(ModalIds.FeedbackModal)) {
      setPredefinedFeedback(undefined);
    }
  }, [isOpen(ModalIds.FeedbackModal)]);

  const handleSubmit = useCallback(async () => {
    if (!data) return;
    const { feedbackType, handleFeedbackChange } = data;

    if (
      (!predefinedFeedback || predefinedFeedback === "") &&
      (!fieldInputRef.current || fieldInputRef.current.value === "")
    )
      return;

    const feedbackText =
      fieldInputRef.current?.value || predefinedFeedback || "";

    if (!handleFeedbackChange) {
      console.error("handleFeedbackChange is required but not provided");
      return;
    }

    await handleFeedbackChange(feedbackType, feedbackText, predefinedFeedback);

    toggleModal(ModalIds.FeedbackModal, false);
  }, [data, predefinedFeedback, toggleModal]);

  useEffect(() => {
    if (predefinedFeedback) {
      handleSubmit();
    }
  }, [predefinedFeedback, handleSubmit]);

  useKeyPress(handleSubmit, "Enter");

  if (!data) return null;
  const { feedbackType } = data;

  const predefinedFeedbackOptions =
    feedbackType === "like"
      ? predefinedPositiveFeedbackOptions
      : predefinedNegativeFeedbackOptions;

  const icon = feedbackType === "like" ? SvgThumbsUp : SvgThumbsDown;
  const modalOpen = isOpen(ModalIds.FeedbackModal);

  const handleClose = () => {
    toggleModal(ModalIds.FeedbackModal, false);
  };

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      handleClose();
    }
  };

  return (
    <Modal open={modalOpen} onOpenChange={handleOpenChange}>
      <Modal.Content size="xs" onOpenAutoFocus={(e) => e.preventDefault()}>
        <Modal.CloseButton />

        <Modal.Header className="flex flex-col p-4 gap-1">
          <Modal.Icon icon={icon} />
          <Modal.Title>Provide Additional Feedback</Modal.Title>
        </Modal.Header>

        <Modal.Body className="flex flex-col">
          {predefinedFeedbackOptions.length > 0 && (
            <div className="flex flex-col px-4 pb-4 gap-1">
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
          <div className="flex flex-col p-4 bg-background-tint-01">
            <FieldInput
              label="Feedback"
              placeholder={`What did you ${feedbackType} about this response?`}
              className="!w-full"
              ref={fieldInputRef}
            />
          </div>
        </Modal.Body>

        <Modal.Footer className="flex flex-row p-4 items-center justify-end w-full gap-2">
          <Button onClick={handleClose} secondary>
            Cancel
          </Button>
          <Button onClick={handleSubmit}>Submit</Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
};
