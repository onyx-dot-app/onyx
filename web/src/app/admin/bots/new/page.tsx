"use client";

import { NewSlackBotForm } from "@/app/admin/bots/SlackBotCreationForm";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { SvgSlack } from "@opal/icons";

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgSlack}
        title="New Slack Bot"
        backButton
        separator
      />
      <SettingsLayouts.Body>
        <NewSlackBotForm />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
