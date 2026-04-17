"use client";

import { EmptyMessageCard } from "@opal/components";
import { SvgActions, SvgFileText, SvgServer, SvgUsers } from "@opal/icons";
import { Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";

function Label({ children }: { children: string }) {
  return (
    <Text font="secondary-action" color="text-03">
      {children}
    </Text>
  );
}

export default function DbgPage() {
  return (
    <div className="p-8 flex flex-col gap-6 max-w-[720px] mx-auto">
      <Text font="heading-h2" as="h2">
        EmptyMessageCard
      </Text>

      {/* ── sizePreset="secondary" (default) ── */}
      <Section gap={0.5}>
        <Label>secondary (default) — title only</Label>
        <EmptyMessageCard title="No items found." />
      </Section>

      <Section gap={0.5}>
        <Label>secondary — custom icon</Label>
        <EmptyMessageCard icon={SvgFileText} title="No documents available." />
      </Section>

      <Section gap={0.5}>
        <Label>
          secondary — description not allowed (type error if passed)
        </Label>
        <EmptyMessageCard title="No connectors set up." />
      </Section>

      {/* ── sizePreset="main-ui" ── */}
      <Section gap={0.5}>
        <Label>main-ui — title only</Label>
        <EmptyMessageCard sizePreset="main-ui" title="No Knowledge" />
      </Section>

      <Section gap={0.5}>
        <Label>main-ui — title + description</Label>
        <EmptyMessageCard
          sizePreset="main-ui"
          title="No Actions Found"
          icon={SvgActions}
          description="Provide OpenAPI schema to preview actions here."
        />
      </Section>

      <Section gap={0.5}>
        <Label>main-ui — title + description + custom icon</Label>
        <EmptyMessageCard
          sizePreset="main-ui"
          icon={SvgServer}
          title="No Discord servers configured yet"
          description="Create a server configuration to get started."
        />
      </Section>

      <Section gap={0.5}>
        <Label>main-ui — title + description (SvgUsers)</Label>
        <EmptyMessageCard
          sizePreset="main-ui"
          icon={SvgUsers}
          title="No users in this group"
          description="Add users to this group to grant them access."
        />
      </Section>

      {/* ── padding variants ── */}
      <Text font="heading-h2" as="h2">
        Padding Variants
      </Text>

      {(["xs", "sm", "md", "lg"] as const).map((p) => (
        <Section key={p} gap={0.5}>
          <Label>{`padding="${p}"`}</Label>
          <EmptyMessageCard
            sizePreset="main-ui"
            padding={p}
            icon={SvgFileText}
            title="No documents"
            description="Try a different filter."
          />
        </Section>
      ))}
    </div>
  );
}
