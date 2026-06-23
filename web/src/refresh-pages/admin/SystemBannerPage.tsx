"use client";

import { useEffect, useState } from "react";
import useSWR, { mutate } from "swr";

import { Button, Card, Text } from "@opal/components";
import { InputVertical, Section, SettingsLayouts } from "@opal/layouts";

import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { toast } from "@/hooks/useToast";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";

const MAX_TITLE_LEN = 200;
const MAX_CONTENT_LEN = 2000;
const route = ADMIN_ROUTES.SYSTEM_BANNER;

interface AdminBanner {
  title: string;
  content: string | null;
  created_at: string | null;
}

export default function SystemBannerPage() {
  const { data, isLoading } = useSWR<AdminBanner | null>(
    SWR_KEYS.adminBanner,
    errorHandlingFetcher
  );

  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [hasTouched, setHasTouched] = useState(false);

  useEffect(() => {
    if (data === undefined) {
      return;
    }
    if (data === null) {
      if (!hasTouched) {
        setTitle("");
        setContent("");
      }
      return;
    }
    if (!hasTouched) {
      setTitle(data.title);
      setContent(data.content ?? "");
    }
  }, [data, hasTouched]);

  const trimmedTitle = title.trim();
  const trimmedContent = content.trim();
  const isActive = data !== null && data !== undefined;
  const isDirty = isActive
    ? trimmedTitle !== data.title || (trimmedContent || null) !== data.content
    : trimmedTitle.length > 0;

  async function handleSave() {
    if (!trimmedTitle) {
      toast.error("Title is required");
      return;
    }
    setSaving(true);
    try {
      const response = await fetch("/api/admin/banner", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: trimmedTitle,
          content: trimmedContent || null,
        }),
      });
      if (!response.ok) {
        const detail = (await response.json().catch(() => ({}))).detail;
        throw new Error(detail || "Failed to save banner");
      }
      setTitle(trimmedTitle);
      setContent(trimmedContent);
      setHasTouched(false);
      await Promise.all([
        mutate(SWR_KEYS.adminBanner),
        mutate(SWR_KEYS.notifications),
      ]);
      toast.success("Banner published to all users");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to save banner";
      toast.error(message);
    } finally {
      setSaving(false);
    }
  }

  async function handleClear() {
    setClearing(true);
    try {
      const response = await fetch("/api/admin/banner", { method: "DELETE" });
      if (!response.ok) {
        throw new Error("Failed to clear banner");
      }
      setTitle("");
      setContent("");
      setHasTouched(false);
      await Promise.all([
        mutate(SWR_KEYS.adminBanner),
        mutate(SWR_KEYS.notifications),
      ]);
      toast.success("Banner cleared");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to clear banner";
      toast.error(message);
    } finally {
      setClearing(false);
    }
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description="Show a dismissible notice at the top of the app for every user. Use to communicate outages, maintenance windows, or upstream provider issues."
        divider
      />

      <SettingsLayouts.Body>
        <Card border="solid" rounding="lg">
          <Section gap={1}>
            <InputVertical
              title="Title"
              subDescription={`Shown in bold at the top of the banner. Max ${MAX_TITLE_LEN} characters.`}
              withLabel
            >
              <InputTypeIn
                value={title}
                onChange={(e) => {
                  setHasTouched(true);
                  setTitle(e.target.value.slice(0, MAX_TITLE_LEN));
                }}
                placeholder="e.g. Bedrock degraded - responses may be slow"
                variant={isLoading ? "disabled" : "primary"}
              />
            </InputVertical>

            <InputVertical
              title="Details"
              suffix="optional"
              subDescription={`Additional context shown next to the title. Max ${MAX_CONTENT_LEN} characters.`}
              withLabel
            >
              <InputTextArea
                value={content}
                onChange={(e) => {
                  setHasTouched(true);
                  setContent(e.target.value.slice(0, MAX_CONTENT_LEN));
                }}
                placeholder="We're aware and tracking with AWS. No action needed."
                rows={4}
                variant={isLoading ? "disabled" : "primary"}
              />
            </InputVertical>

            <Section flexDirection="row" justifyContent="end" gap={0.5}>
              {isActive ? (
                <Button
                  variant="danger"
                  prominence="secondary"
                  disabled={saving || clearing || isLoading}
                  onClick={handleClear}
                >
                  Clear banner
                </Button>
              ) : null}
              <Button
                prominence="primary"
                disabled={
                  saving || clearing || isLoading || !trimmedTitle || !isDirty
                }
                onClick={handleSave}
              >
                {isActive ? "Update banner" : "Publish banner"}
              </Button>
            </Section>

            {isActive && data?.created_at ? (
              <Text font="secondary-body" color="text-03">
                {`Banner active since ${new Date(
                  data.created_at
                ).toLocaleString()}.`}
              </Text>
            ) : null}
          </Section>
        </Card>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
