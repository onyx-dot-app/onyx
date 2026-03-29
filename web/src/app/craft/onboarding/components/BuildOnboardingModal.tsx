"use client";

import { useState, useEffect, useMemo } from "react";
import { track, AnalyticsEvent } from "@/lib/analytics";
import { SvgArrowRight, SvgArrowLeft } from "@opal/icons";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import {
  BuildUserInfo,
  OnboardingModalMode,
  OnboardingStep,
} from "@/app/craft/onboarding/types";
import {
  WorkArea,
  Level,
  WORK_AREAS_REQUIRING_LEVEL,
} from "@/app/craft/onboarding/constants";
import OnboardingInfoPages from "@/app/craft/onboarding/components/OnboardingInfoPages";
import OnboardingUserInfo from "@/app/craft/onboarding/components/OnboardingUserInfo";

interface InitialValues {
  firstName: string;
  lastName: string;
  workArea: WorkArea | undefined;
  level: Level | undefined;
}

interface BuildOnboardingModalProps {
  mode: OnboardingModalMode;
  initialValues: InitialValues;
  hasUserInfo: boolean;
  onComplete: (info: BuildUserInfo) => Promise<void>;
  onClose: () => void;
}

// Helper to compute steps for mode
function getStepsForMode(
  mode: OnboardingModalMode,
  hasUserInfo: boolean
): OnboardingStep[] {
  switch (mode.type) {
    case "initial-onboarding": {
      // Full flow: page1 → user-info
      const steps: OnboardingStep[] = ["page1"];

      if (!hasUserInfo) {
        steps.push("user-info");
      }

      return steps;
    }

    case "edit-persona":
      return ["user-info"];

    case "closed":
      return [];
  }
}

export default function BuildOnboardingModal({
  mode,
  initialValues,
  hasUserInfo,
  onComplete,
  onClose,
}: BuildOnboardingModalProps) {
  // Compute steps based on mode
  const steps = useMemo(
    () => getStepsForMode(mode, hasUserInfo),
    [mode, hasUserInfo]
  );

  // Determine initial step based on mode
  const initialStep = useMemo((): OnboardingStep => {
    return steps[0] || "user-info";
  }, [steps]);

  // Navigation state
  const [currentStep, setCurrentStep] = useState<OnboardingStep>(initialStep);

  // Reset step when mode changes
  useEffect(() => {
    if (mode.type !== "closed") {
      setCurrentStep(initialStep);
    }
  }, [mode.type, initialStep]);

  // User info state - pre-fill from initialValues
  const [firstName, setFirstName] = useState(initialValues.firstName);
  const [lastName, setLastName] = useState(initialValues.lastName);
  const [workArea, setWorkArea] = useState(initialValues.workArea);
  const [level, setLevel] = useState(initialValues.level);

  // Update form values when initialValues changes
  useEffect(() => {
    setFirstName(initialValues.firstName);
    setLastName(initialValues.lastName);
    setWorkArea(initialValues.workArea);
    setLevel(initialValues.level);
  }, [initialValues]);

  // Submission state
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const requiresLevel =
    workArea !== undefined && WORK_AREAS_REQUIRING_LEVEL.includes(workArea);
  const isUserInfoValid = workArea && (!requiresLevel || level);

  // Calculate step navigation
  const currentStepIndex = steps.indexOf(currentStep);
  const totalSteps = steps.length;

  const handleNext = () => {
    setErrorMessage("");
    const nextIndex = currentStepIndex + 1;
    if (nextIndex < steps.length) {
      setCurrentStep(steps[nextIndex]!);
    }
  };

  const handleBack = () => {
    setErrorMessage("");
    const prevIndex = currentStepIndex - 1;
    if (prevIndex >= 0) {
      setCurrentStep(steps[prevIndex]!);
    }
  };

  const handleSubmit = async () => {
    if (!isUserInfoValid) return;

    setIsSubmitting(true);

    try {
      // Validate workArea is provided before submission
      if (!workArea) {
        setErrorMessage("Please select a work area.");
        setIsSubmitting(false);
        return;
      }

      const requiresLevel = WORK_AREAS_REQUIRING_LEVEL.includes(workArea);

      // Validate level if required
      if (requiresLevel && !level) {
        setErrorMessage("Please select a level.");
        setIsSubmitting(false);
        return;
      }

      await onComplete({
        firstName: firstName.trim(),
        lastName: lastName.trim() || undefined,
        workArea,
        level: level || undefined,
      });

      track(AnalyticsEvent.COMPLETED_CRAFT_ONBOARDING);
      onClose();
    } catch (error) {
      console.error("Error completing onboarding:", error);
      setErrorMessage(
        "There was an issue completing onboarding. Please try again."
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  if (mode.type === "closed") return null;

  const canProceedUserInfo = isUserInfoValid;
  const isLastStep = currentStepIndex === steps.length - 1;
  const isFirstStep = currentStepIndex === 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-xl mx-4 bg-background-tint-01 rounded-16 shadow-lg border border-border-01">
        <div className="p-6 flex flex-col gap-6 min-h-[600px]">
          {/* User Info Step */}
          {currentStep === "user-info" && (
            <OnboardingUserInfo
              firstName={firstName}
              lastName={lastName}
              workArea={workArea}
              level={level}
              onFirstNameChange={setFirstName}
              onLastNameChange={setLastName}
              onWorkAreaChange={setWorkArea}
              onLevelChange={setLevel}
            />
          )}

          {/* Page 1 - What is PrivateGPT Craft? */}
          {currentStep === "page1" && (
            <OnboardingInfoPages
              step="page1"
              workArea={workArea}
              level={level}
            />
          )}

          {/* Navigation buttons */}
          <div className="relative flex justify-between items-center pt-2">
            {/* Back button */}
            <div>
              {!isFirstStep && (
                <button
                  type="button"
                  onClick={handleBack}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-12 border border-border-01 bg-background-tint-00 text-text-04 hover:bg-background-tint-02 transition-colors"
                >
                  <SvgArrowLeft className="w-4 h-4" />
                  <Text mainUiAction>Back</Text>
                </button>
              )}
            </div>

            {/* Step indicator */}
            {totalSteps > 1 && (
              <div className="absolute left-1/2 -translate-x-1/2 flex items-center justify-center gap-2">
                {Array.from({ length: totalSteps }).map((_, i) => (
                  <div
                    key={i}
                    className={cn(
                      "w-2 h-2 rounded-full transition-colors",
                      i === currentStepIndex
                        ? "bg-text-05"
                        : i < currentStepIndex
                          ? "bg-text-03"
                          : "bg-border-01"
                    )}
                  />
                ))}
              </div>
            )}

            {/* Action buttons */}
            {currentStep === "user-info" && (
              <button
                type="button"
                onClick={() => {
                  track(AnalyticsEvent.COMPLETED_CRAFT_USER_INFO, {
                    first_name: firstName.trim(),
                    last_name: lastName.trim() || undefined,
                    work_area: workArea,
                    level: level,
                  });
                  if (isLastStep) {
                    handleSubmit();
                  } else {
                    handleNext();
                  }
                }}
                disabled={!canProceedUserInfo || isSubmitting}
                className={cn(
                  "flex items-center gap-1.5 px-4 py-2 rounded-12 transition-colors",
                  canProceedUserInfo && !isSubmitting
                    ? "bg-black dark:bg-white text-white dark:text-black hover:opacity-90"
                    : "bg-background-neutral-01 text-text-02 cursor-not-allowed"
                )}
              >
                <Text
                  mainUiAction
                  className={cn(
                    canProceedUserInfo && !isSubmitting
                      ? "text-white dark:text-black"
                      : "text-text-02"
                  )}
                >
                  {isLastStep
                    ? isSubmitting
                      ? "Saving..."
                      : "Get Started!"
                    : "Continue"}
                </Text>
                {!isLastStep && (
                  <SvgArrowRight
                    className={cn(
                      "w-4 h-4",
                      canProceedUserInfo && !isSubmitting
                        ? "text-white dark:text-black"
                        : "text-text-02"
                    )}
                  />
                )}
              </button>
            )}

            {currentStep === "page1" && (
              <button
                type="button"
                onClick={handleNext}
                className="flex items-center gap-1.5 px-4 py-2 rounded-12 transition-colors bg-black dark:bg-white text-white dark:text-black hover:opacity-90"
              >
                <Text mainUiAction className="text-white dark:text-black">
                  Continue
                </Text>
                <SvgArrowRight className="w-4 h-4 text-white dark:text-black" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
