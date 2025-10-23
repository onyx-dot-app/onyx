"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FeedbackType } from "@/app/chat/interfaces";
import Modal from "@/refresh-components/modals/Modal";
import { FilledLikeIcon } from "@/components/icons/icons";
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

  return (
    <Modal
      id={ModalIds.FeedbackModal}
      title="Provide Additional Feedback"
      icon={icon}
      xs
    >
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
      <div className="flex flex-col p-4 items-center justify-center bg-background-tint-01">
        <FieldInput
          label="Feedback"
          placeholder={`What did you ${feedbackType} about this response?`}
          className="!w-full"
          ref={fieldInputRef}
        />
      </div>
      <div className="flex flex-row p-4 items-center justify-end w-full gap-2">
        <Button
          onClick={() => toggleModal(ModalIds.FeedbackModal, false)}
          secondary
        >
          Cancel
        </Button>
        <Button onClick={handleSubmit}>Submit</Button>
      </div>
    </Modal>
  );
};
