"use client";

import { useState } from "react";
import { FeedbackType } from "../types";
import { Modal } from "@/components/Modal";
import { FilledLikeIcon } from "@/components/icons/icons";

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
  onClose: () => void;
  onSubmit: (feedbackDetails: {
    message: string;
    predefinedFeedback?: string;
  }) => void;
}

export const FeedbackModal = ({
  feedbackType,
  onClose,
  onSubmit,
}: FeedbackModalProps) => {
  const [message, setMessage] = useState("");
  const [predefinedFeedback, setPredefinedFeedback] = useState<
    string | undefined
  >();

  const handlePredefinedFeedback = (feedback: string) => {
    setPredefinedFeedback(feedback);
  };

  const handleSubmit = () => {
    onSubmit({ message, predefinedFeedback });
    onClose();
  };

  const predefinedFeedbackOptions =
    feedbackType === "like"
      ? predefinedPositiveFeedbackOptions
      : predefinedNegativeFeedbackOptions;

  return (
    <Modal onOutsideClick={onClose} width="w-full max-w-3xl">
      <>
        <h2 className="text-2xl text-text-darker font-bold mb-4 flex">
          <div className="mr-1 my-auto">
            {feedbackType === "like" ? (
              <FilledLikeIcon
                size={20}
                className="text-green-600 my-auto mr-2"
              />
            ) : (
              <FilledLikeIcon
                size={20}
                className="rotate-180 text-red-600 my-auto mr-2"
              />
            )}
          </div>
          Provide additional feedback
        </h2>

        <div className="mb-4 flex flex-wrap justify-start">
          {predefinedFeedbackOptions.map((feedback, index) => (
            <button
              key={index}
              className={`bg-background-dark hover:bg-accent-background-hovered text-default py-2 px-4 rounded m-1 
                ${predefinedFeedback === feedback && "ring-2 ring-accent/20"}`}
              onClick={() => handlePredefinedFeedback(feedback)}
            >
              {feedback}
            </button>
          ))}
        </div>

        <textarea
          autoFocus
          className={`
            w-full flex-grow 
            border border-border-strong rounded 
            outline-none placeholder-subtle 
            pl-4 pr-4 py-4 bg-background 
            overflow-hidden h-28 
            whitespace-normal resize-none 
            break-all overscroll-contain
          `}
          role="textarea"
          aria-multiline
          placeholder={
            feedbackType === "like"
              ? "(Optional) What did you like about this response?"
              : "(Optional) What was the issue with the response? How could it be improved?"
          }
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />

        <div className="flex mt-2">
          <button
            className="bg-agent text-white py-2 px-4 rounded hover:bg-agent/50 focus:outline-none mx-auto"
            onClick={handleSubmit}
          >
            Submit feedback
          </button>
        </div>
      </>
    </Modal>
  );
};
