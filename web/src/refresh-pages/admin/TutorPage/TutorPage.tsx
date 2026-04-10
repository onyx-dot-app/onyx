"use client";

import { SvgBookOpen, SvgPlus } from "@opal/icons";
import { Button } from "@opal/components";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import Link from "next/link";

import TutorTable from "./TutorTable";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function TutorPage() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        title="Virtual Tutors"
        description="Create AI tutors that help students learn using your course materials."
        icon={SvgBookOpen}
        rightChildren={
          <Link href="/admin/tutor/create">
            <Button icon={SvgPlus}>New Tutor</Button>
          </Link>
        }
      />
      <SettingsLayouts.Body>
        <TutorTable />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
