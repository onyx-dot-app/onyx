"use client";

import { Content } from "@opal/components";
import SvgSearch from "@opal/icons/search";

export default function StorybookPage() {
  return (
    <div style={{ padding: "2rem", maxWidth: 960, margin: "0 auto" }}>
      <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: "2rem" }}>
        Content — Storybook
      </h1>

      {/* ── headline + heading (icon top) ── */}
      <Section label='sizePreset="headline" variant="heading" (icon top)'>
        <Content
          icon={SvgSearch}
          sizePreset="headline"
          variant="heading"
          title="Headline Heading"
          description="Icon placed above the content"
        />
      </Section>

      <Section label='sizePreset="headline" variant="heading" + editable'>
        <Content
          icon={SvgSearch}
          sizePreset="headline"
          variant="heading"
          title="Click edit to rename"
          description="Editable headline with icon on top"
          editable
          onTitleChange={(v) => console.log("title changed:", v)}
        />
      </Section>

      {/* ── headline + section (icon inline) ── */}
      <Section label='sizePreset="headline" variant="section" (icon inline)'>
        <Content
          icon={SvgSearch}
          sizePreset="headline"
          variant="section"
          title="Headline Section"
          description="Icon placed inline with the content"
        />
      </Section>

      <Section label='sizePreset="headline" variant="section" + editable'>
        <Content
          icon={SvgSearch}
          sizePreset="headline"
          variant="section"
          title="Click edit to rename"
          description="Editable headline with icon inline"
          editable
          onTitleChange={(v) => console.log("title changed:", v)}
        />
      </Section>

      {/* ── section + heading (icon top) ── */}
      <Section label='sizePreset="section" variant="heading" (icon top)'>
        <Content
          icon={SvgSearch}
          sizePreset="section"
          variant="heading"
          title="Section Heading"
          description="Smaller preset, icon placed above the content"
        />
      </Section>

      <Section label='sizePreset="section" variant="heading" + editable'>
        <Content
          icon={SvgSearch}
          sizePreset="section"
          variant="heading"
          title="Click edit to rename"
          description="Editable section with icon on top"
          editable
          onTitleChange={(v) => console.log("title changed:", v)}
        />
      </Section>

      {/* ── section + section (icon inline) ── */}
      <Section label='sizePreset="section" variant="section" (icon inline)'>
        <Content
          icon={SvgSearch}
          sizePreset="section"
          variant="section"
          title="Section Section"
          description="Smaller preset, icon placed inline"
        />
      </Section>

      <Section label='sizePreset="section" variant="section" + editable'>
        <Content
          icon={SvgSearch}
          sizePreset="section"
          variant="section"
          title="Click edit to rename"
          description="Editable section with icon inline"
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
