"use client";

import { SvgBookOpen } from "@opal/icons";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import Text from "@/refresh-components/texts/Text";

import TutorTable from "./TutorTable";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function TutorPage() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        title="Virtual Tutors"
        description="Manage AI tutors that help students learn using your course materials."
        icon={SvgBookOpen}
      />
      <SettingsLayouts.Body>
        <div className="rounded-12 border border-border-01 bg-background-tint-01 p-4">
          <Text as="p" mainUiAction text05>
            To create a new tutor, launch the Onyx tool from Canvas
          </Text>
          <Text as="p" secondaryBody text03>
            Tutors are bound to a Canvas course at creation, so new tutors can
            only be created from inside a Canvas LTI launch. This page lists
            every tutor across all courses for editing.
          </Text>
        </div>
        <TutorTable />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
