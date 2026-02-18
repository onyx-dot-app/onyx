"use client";

import { LineItemLayout } from "@opal/components";
import SvgSearch from "@opal/icons/search";

export default function StorybookPage() {
  return (
    <div style={{ padding: "2rem", maxWidth: 960, margin: "0 auto" }}>
      <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: "2rem" }}>
        LineItemLayout — Storybook
      </h1>

      {/* ── left + not editable ── */}
      <Section label='iconPlacement="left" (default)'>
        <LineItemLayout
          icon={SvgSearch}
          title="Headline with Icon"
          description="Icon placed to the left of the content"
        />
      </Section>

      {/* ── left + editable ── */}
      <Section label='iconPlacement="left" + editable'>
        <LineItemLayout
          icon={SvgSearch}
          title="Click edit to rename"
          description="Editable headline with icon on the left"
          editable
          onTitleChange={(v) => console.log("title changed:", v)}
        />
      </Section>

      {/* ── top + not editable ── */}
      <Section label='iconPlacement="top"'>
        <LineItemLayout
          icon={SvgSearch}
          iconPlacement="top"
          title="Headline with Icon"
          description="Icon stacked above the content"
        />
      </Section>

      {/* ── top + editable ── */}
      <Section label='iconPlacement="top" + editable'>
        <LineItemLayout
          icon={SvgSearch}
          iconPlacement="top"
          title="Click edit to rename"
          description="Editable headline with icon on top"
          editable
          onTitleChange={(v) => console.log("title changed:", v)}
        />
      </Section>
    </div>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <section style={{ marginBottom: "3rem" }}>
      <h2
        style={{
          fontSize: 14,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: 1,
          opacity: 0.5,
          marginBottom: "1rem",
        }}
      >
        {label}
      </h2>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "1rem",
          border: "1px solid #e0e0e0",
          borderRadius: 8,
          padding: "1.5rem",
        }}
      >
        {children}
      </div>
    </section>
  );
}
