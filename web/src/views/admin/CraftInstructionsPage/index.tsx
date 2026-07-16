"use client";

import { useEffect, useState } from "react";
import useSWR, { mutate } from "swr";
import { Button, Card, Text } from "@opal/components";
import {
  IllustrationContent,
  InputVertical,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { SvgArrowUpRight, SvgRefreshCw, SvgSimpleLoader } from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import { Section } from "@/layouts/general-layouts";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useSettings } from "@/lib/settings/hooks";
import { toSettings } from "@/lib/settings/types";
import { updateAdminSettings } from "@/lib/settings/svc";

const MAX_INSTRUCTIONS_LENGTH = 4000;

function BaseInstructionsPreview() {
  const { data, error } = useSWR<{ content: string }>(
    SWR_KEYS.buildBaseInstructions,
    errorHandlingFetcher
  );

  if (error) {
    return (
      <Text font="secondary-body" color="text-03">
        Failed to load the base instructions.
      </Text>
    );
  }
  if (!data) {
    return (
      <div className="flex justify-center py-4">
        <SvgSimpleLoader className="h-5 w-5" />
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-border-01 p-3 overflow-y-auto overflow-x-hidden bg-background-neutral-00 max-h-96">
      <pre className="m-0 whitespace-pre-wrap wrap-break-word font-mono text-xs leading-5 text-text-04">
        {data.content}
      </pre>
    </div>
  );
}

export default function CraftInstructionsPage() {
  const settings = useSettings();
  const craftAvailable = settings?.onyx_craft_available === true;
  const savedInstructions = settings?.craft_instructions ?? "";

  const [draft, setDraft] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [resetConfirmOpen, setResetConfirmOpen] = useState(false);

  // null until the user edits — render the saved value until then.
  const value = draft ?? savedInstructions;
  const isDirty = value !== savedInstructions;

  useEffect(() => {
    if (!isDirty) return;
    function warn(event: BeforeUnloadEvent) {
      event.preventDefault();
    }
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [isDirty]);

  async function save(instructions: string): Promise<boolean> {
    if (!settings) return false;
    setIsSaving(true);
    try {
      await updateAdminSettings({
        ...toSettings(settings),
        craft_instructions: instructions.trim() || null,
      });
      await mutate(SWR_KEYS.settings);
      setDraft(null);
      toast.success("Craft instructions saved");
      return true;
    } catch (err) {
      console.error("Failed to save Craft instructions", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to save instructions"
      );
      return false;
    } finally {
      setIsSaving(false);
    }
  }

  const header = (
    <SettingsLayouts.Header
      icon={ADMIN_ROUTES.CRAFT_INSTRUCTIONS.icon}
      title={ADMIN_ROUTES.CRAFT_INSTRUCTIONS.title}
      description="Workspace-wide instructions every Craft agent follows, on top of Craft's built-in behavior."
      rightChildren={
        craftAvailable && !settings.isLoading && !settings.error ? (
          <div className="flex items-start gap-2">
            <Button
              href="/craft"
              prominence="secondary"
              rightIcon={SvgArrowUpRight}
            >
              Try in Craft
            </Button>
            <Button disabled={!isDirty || isSaving} onClick={() => save(value)}>
              {isSaving ? "Saving…" : "Save"}
            </Button>
          </div>
        ) : undefined
      }
      divider
    />
  );

  // useSettings returns a default object while loading (and on error), which
  // lacks onyx_craft_available — don't misreport Craft as unavailable.
  if (settings.isLoading || settings.error) {
    return (
      <SettingsLayouts.Root>
        {header}
        <SettingsLayouts.Body>
          {settings.error ? (
            <Text as="p" font="secondary-body" color="text-03">
              Failed to load settings. Please try refreshing the page.
            </Text>
          ) : (
            <div className="flex justify-center py-12">
              <SvgSimpleLoader className="h-6 w-6" />
            </div>
          )}
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  if (!craftAvailable) {
    return (
      <SettingsLayouts.Root>
        {header}
        <SettingsLayouts.Body>
          <IllustrationContent
            illustration={SvgNoResult}
            title="Craft isn't available on this deployment"
            description="Craft is enabled per deployment by Onyx. Contact your Onyx representative to get access."
          />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  return (
    <SettingsLayouts.Root>
      {header}
      <SettingsLayouts.Body>
        <Card border="solid" rounding="lg">
          <Section alignItems="stretch" gap={0.25}>
            <InputVertical
              title="Workspace instructions"
              topRight={`${value.length.toLocaleString()} / ${MAX_INSTRUCTIONS_LENGTH.toLocaleString()}`}
              withLabel
            >
              <InputTextArea
                value={value}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="e.g. Always follow our brand guidelines and prefer concise, formal copy."
                rows={8}
                autoResize
                maxRows={24}
                maxLength={MAX_INSTRUCTIONS_LENGTH}
              />
              <div className="w-full flex items-center justify-between gap-4">
                <Text font="secondary-body" color="text-03">
                  Changes apply when a session starts or is restored — they
                  don&apos;t reach into sessions mid-run.
                </Text>
                {savedInstructions && (
                  <Button
                    icon={SvgRefreshCw}
                    variant="danger"
                    prominence="tertiary"
                    size="sm"
                    disabled={isSaving}
                    onClick={() => setResetConfirmOpen(true)}
                  >
                    Reset to default
                  </Button>
                )}
              </div>
            </InputVertical>
          </Section>
        </Card>

        <SimpleCollapsible defaultOpen={false}>
          <SimpleCollapsible.Header
            title="View base instructions"
            description="The built-in prompt your instructions are appended to. Dynamic sections are filled in per session."
          />
          <SimpleCollapsible.Content>
            <BaseInstructionsPreview />
          </SimpleCollapsible.Content>
        </SimpleCollapsible>
      </SettingsLayouts.Body>

      {resetConfirmOpen && (
        <ConfirmationModalLayout
          icon={ADMIN_ROUTES.CRAFT_INSTRUCTIONS.icon}
          title="Reset Craft instructions?"
          onClose={isSaving ? undefined : () => setResetConfirmOpen(false)}
          submit={
            <Button
              variant="danger"
              disabled={isSaving}
              onClick={async () => {
                if (await save("")) {
                  setResetConfirmOpen(false);
                }
              }}
            >
              {isSaving ? "Resetting…" : "Reset"}
            </Button>
          }
        >
          New Craft sessions will run with only the built-in instructions. This
          removes your workspace instructions for everyone.
        </ConfirmationModalLayout>
      )}
    </SettingsLayouts.Root>
  );
}
