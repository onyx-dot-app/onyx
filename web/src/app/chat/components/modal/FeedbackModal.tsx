"use client";

import { useEffect, useRef, useState } from "react";
import { FeedbackType } from "@/app/chat/interfaces";
import ModalContent from "@/refresh-components/modals/ModalContent";
import { handleChatFeedback } from "../../services/lib";
import SvgThumbsUp from "@/icons/thumbs-up";
import SvgThumbsDown from "@/icons/thumbs-down";
import Button from "@/refresh-components/buttons/Button";
import FieldInput from "@/refresh-components/inputs/FieldInput";
import LineItem from "@/refresh-components/buttons/LineItem";
import { useKeyPress } from "@/hooks/useKeyPress";
import { useModal } from "@/refresh-components/contexts/ModalContext";

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

interface FeedbackModalProps {
  feedbackType: FeedbackType;
  messageId: number;
  setPopup: (popup: { message: string; type: "success" | "error" }) => void;
}

export const FeedbackModal = ({
  feedbackType,
  messageId,
  setPopup,
}: FeedbackModalProps) => {
  const { toggle } = useModal();
  const [predefinedFeedback, setPredefinedFeedback] = useState<
    string | undefined
  >();
  const fieldInputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = async () => {
    if (
      (!predefinedFeedback || predefinedFeedback === "") &&
      (!fieldInputRef.current || fieldInputRef.current.value === "")
    )
      return;

    try {
      const response = await handleChatFeedback(
        messageId,
        feedbackType,
        fieldInputRef.current?.value ?? predefinedFeedback!,
        predefinedFeedback
      );

      if (response.ok) {
        setPopup({
          message: "Thanks for your feedback!",
          type: "success",
        });
      } else {
        const responseJson = await response.json();
        const errorMsg = responseJson.detail || responseJson.message;
        setPopup({
          message: `Failed to submit feedback - ${errorMsg}`,
          type: "error",
        });
      }
    } catch (error) {
      setPopup({
        message: "Failed to submit feedback - network error",
        type: "error",
      });
    }

    toggle(false);
  };

  useEffect(() => {
    handleSubmit();
  }, [predefinedFeedback]);

  useKeyPress(handleSubmit, "Enter");

  const predefinedFeedbackOptions =
    feedbackType === "like"
      ? predefinedPositiveFeedbackOptions
      : predefinedNegativeFeedbackOptions;

  const icon = feedbackType === "like" ? SvgThumbsUp : SvgThumbsDown;

  return (
    <ModalContent title="Provide Additional Feedback" icon={icon}>
      {predefinedFeedbackOptions.length > 0 && (
        <div className="flex flex-col p-spacing-paragraph gap-spacing-inline">
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
      <div className="flex flex-col p-spacing-paragraph items-center justify-center bg-background-tint-01">
        <FieldInput
          label="Feedback"
          placeholder={`What did you ${feedbackType} about this response?`}
          className="!w-full"
          ref={fieldInputRef}
        />
      </div>
      <div className="flex flex-row p-spacing-paragraph items-center justify-end w-full gap-spacing-interline">
        <Button onClick={() => toggle(false)} secondary>
          Cancel
        </Button>
        <Button onClick={handleSubmit}>Submit</Button>
      </div>
    </ModalContent>
  );
};
