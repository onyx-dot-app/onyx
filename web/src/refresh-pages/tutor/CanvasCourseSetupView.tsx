"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import {
  SvgArrowRight,
  SvgBookOpen,
  SvgCheckCircle,
  SvgExternalLink,
  SvgKey,
} from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import Text from "@/refresh-components/texts/Text";

interface LtiCourseConnectorSetup {
  can_setup: boolean;
  canvas_token_url: string | null;
  course_label: string | null;
  course_title: string | null;
}

export interface LtiCourseConnectorStatus {
  course_id: string;
  has_connector: boolean;
  cc_pair_id: number | null;
  connector_id: number | null;
  credential_id: number | null;
  cc_pair_status: string | null;
  indexing_status: string | null;
  indexing_trigger: string | null;
  total_docs_indexed: number;
  has_indexed_documents: boolean;
  last_successful_index_time: string | null;
  setup?: LtiCourseConnectorSetup;
}

interface CanvasCourseSetupViewProps {
  courseId: string;
  status: LtiCourseConnectorStatus;
  onReady: () => void;
}

type SetupStep = "welcome" | "token" | "confirm";

function getErrorDetail(payload: unknown): string {
  if (
    payload &&
    typeof payload === "object" &&
    "detail" in payload &&
    typeof payload.detail === "string"
  ) {
    return payload.detail;
  }
  return "Canvas could not be connected. Check the token and try again.";
}

async function fetchConnectorStatus(
  courseId: string
): Promise<LtiCourseConnectorStatus> {
  const response = await fetch(
    `/api/auth/lti/course/${encodeURIComponent(courseId)}/connector-status`
  );
  if (!response.ok) {
    throw new Error("Unable to check Canvas connector status");
  }
  return response.json();
}

export function CanvasCoursePreparingView({
  status,
}: {
  status: LtiCourseConnectorStatus;
}) {
  const title = "Course content is being prepared";
  const description = status.has_connector
    ? "Canvas content is indexing for this course. The tutor will be available once the first documents are ready."
    : "Canvas content has not been connected for this course yet. The tutor will be available after setup starts.";

  return (
    <div className="h-full w-full flex items-center justify-center p-8">
      <div className="flex flex-col items-center gap-4 text-center max-w-[28rem]">
        <SimpleLoader className="h-6 w-6" />
        <IllustrationContent
          illustration={SvgNoResult}
          title={title}
          description={description}
        />
      </div>
    </div>
  );
}

export default function CanvasCourseSetupView({
  courseId,
  status,
  onReady,
}: CanvasCourseSetupViewProps) {
  const [step, setStep] = useState<SetupStep>("welcome");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const courseName = useMemo(() => {
    return (
      status.setup?.course_title ||
      status.setup?.course_label ||
      "this Canvas course"
    );
  }, [status.setup?.course_label, status.setup?.course_title]);

  const pollForReady = useCallback(async () => {
    const latestStatus = await fetchConnectorStatus(courseId);
    if (latestStatus.has_indexed_documents) {
      onReady();
    }
  }, [courseId, onReady]);

  useEffect(() => {
    if (step !== "confirm") return;

    const interval = window.setInterval(() => {
      pollForReady().catch(() => undefined);
    }, 5000);

    pollForReady().catch(() => undefined);
    return () => window.clearInterval(interval);
  }, [pollForReady, step]);

  const submitToken = useCallback(async () => {
    const trimmedToken = token.trim();
    if (!trimmedToken) {
      setError("Paste a Canvas access token to continue.");
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/auth/lti/course/${encodeURIComponent(courseId)}/setup-connector`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ canvas_access_token: trimmedToken }),
        }
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(getErrorDetail(payload));
      }
      setStep("confirm");
    } catch (e) {
      setError(e instanceof Error ? e.message : getErrorDetail(null));
    } finally {
      setIsSubmitting(false);
    }
  }, [courseId, token]);

  return (
    <div className="h-full w-full overflow-auto bg-background-neutral-00">
      <main className="min-h-full flex items-center justify-center px-4 py-8">
        <section className="w-full max-w-[34rem] rounded-08 border border-border-01 bg-background-neutral-00 p-6 shadow-sm">
          {step === "welcome" && (
            <div className="flex flex-col gap-5">
              <div className="flex flex-col gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-08 bg-background-neutral-03">
                  <SvgBookOpen size={20} />
                </div>
                <div className="flex flex-col gap-1">
                  <Text as="p" mainUiAction text05>
                    Set up course content
                  </Text>
                  <Text as="p" secondaryBody text03>
                    Connect Canvas content for {courseName}. Onyx will index
                    pages, assignments, files, announcements, modules, quizzes,
                    discussions, and the syllabus for this course only.
                  </Text>
                </div>
              </div>
              <Button
                icon={SvgArrowRight}
                onClick={() => setStep("token")}
                width="full"
              >
                Continue
              </Button>
            </div>
          )}

          {step === "token" && (
            <div className="flex flex-col gap-5">
              <div className="flex flex-col gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-08 bg-background-neutral-03">
                  <SvgKey size={20} />
                </div>
                <div className="flex flex-col gap-1">
                  <Text as="p" mainUiAction text05>
                    Connect Canvas
                  </Text>
                  <Text as="p" secondaryBody text03>
                    Generate a Canvas access token, then paste it here. The
                    token is checked against Canvas before indexing starts.
                  </Text>
                </div>
              </div>

              <ol className="flex flex-col gap-2 text-sm text-text-02 list-decimal pl-5">
                <li>Open Canvas account settings in a new tab.</li>
                <li>Create a new access token.</li>
                <li>Paste the token into Onyx.</li>
              </ol>

              {status.setup?.canvas_token_url && (
                <Button
                  href={status.setup.canvas_token_url}
                  target="_blank"
                  rel="noreferrer"
                  icon={SvgExternalLink}
                  prominence="secondary"
                  width="full"
                >
                  Generate token in Canvas
                </Button>
              )}

              <form
                className="flex flex-col gap-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  void submitToken();
                }}
              >
                <InputTypeIn
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  type="password"
                  placeholder="Canvas access token"
                  autoComplete="off"
                  showClearButton={false}
                />
                {error && (
                  <Text as="p" secondaryBody text03 className="text-error">
                    {error}
                  </Text>
                )}
                <div className="flex flex-col-reverse sm:flex-row gap-2 sm:justify-end">
                  <Button
                    prominence="tertiary"
                    onClick={() => setStep("welcome")}
                    disabled={isSubmitting}
                  >
                    Back
                  </Button>
                  <Button
                    type="submit"
                    icon={SvgCheckCircle}
                    disabled={isSubmitting}
                  >
                    {isSubmitting ? "Connecting" : "Start indexing"}
                  </Button>
                </div>
              </form>
            </div>
          )}

          {step === "confirm" && (
            <div className="flex flex-col items-center gap-4 text-center py-3">
              <SimpleLoader className="h-6 w-6" />
              <IllustrationContent
                illustration={SvgNoResult}
                title="Indexing started"
                description="Canvas content is being prepared for this course. The tutor will open when the first documents are ready."
              />
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
