"use client";

import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";

/**
 * Displayed when a student reaches /tutor but no tutor (assistant)
 * is configured for the course — either the assistantId URL param
 * is missing or references an agent the student can't access.
 */
export default function TutorNoAgent() {
  return (
    <div className="h-full w-full flex items-center justify-center p-8">
      <IllustrationContent
        illustration={SvgNoResult}
        title="Tutor not available"
        description="Your instructor hasn't set up the AI tutor for this course yet. Please check back later or contact your instructor."
      />
    </div>
  );
}
