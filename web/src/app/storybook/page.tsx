"use client";

import { AuxiliaryTag, Content } from "@opal/components";
import SvgSearch from "@opal/icons/search";
import SvgStar from "@opal/icons/star";

export default function StorybookPage() {
  return (
    <div style={{ padding: "2rem", maxWidth: 960, margin: "0 auto" }}>
      <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: "2rem" }}>
        Content — Storybook
      </h1>

      {/* ================================================================= */}
      {/*  AuxiliaryTag                                                      */}
      {/* ================================================================= */}

      <LayoutGroup label="AuxiliaryTag">
        <Section label="colors">
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <AuxiliaryTag title="Green" color="green" />
            <AuxiliaryTag title="Blue" color="blue" />
            <AuxiliaryTag title="Purple" color="purple" />
            <AuxiliaryTag title="Amber" color="amber" />
            <AuxiliaryTag title="Gray" color="gray" />
          </div>
        </Section>

        <Section label="with icon">
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <AuxiliaryTag icon={SvgStar} title="Green" color="green" />
            <AuxiliaryTag icon={SvgStar} title="Blue" color="blue" />
            <AuxiliaryTag icon={SvgStar} title="Purple" color="purple" />
            <AuxiliaryTag icon={SvgStar} title="Amber" color="amber" />
            <AuxiliaryTag icon={SvgStar} title="Gray" color="gray" />
          </div>
        </Section>

        <Section label="icon only">
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <AuxiliaryTag icon={SvgStar} title="" color="green" />
            <AuxiliaryTag icon={SvgStar} title="" color="blue" />
          </div>
        </Section>
      </LayoutGroup>

      {/* ================================================================= */}
      {/*  HeadingLayout                                                     */}
      {/* ================================================================= */}

      <LayoutGroup label="HeadingLayout">
        {/* ── headline + heading ── */}
        <Section label="headline / heading (icon top)">
          <Content
            icon={SvgSearch}
            sizePreset="headline"
            variant="heading"
            title="Headline Heading"
            description="Icon placed above the content"
          />
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

        {/* ── headline + section ── */}
        <Section label="headline / section (icon inline)">
          <Content
            icon={SvgSearch}
            sizePreset="headline"
            variant="section"
            title="Headline Section"
            description="Icon placed inline with the content"
          />
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

        {/* ── section + heading ── */}
        <Section label="section / heading (icon top)">
          <Content
            icon={SvgSearch}
            sizePreset="section"
            variant="heading"
            title="Section Heading"
            description="Smaller preset, icon placed above the content"
          />
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

        {/* ── section + section ── */}
        <Section label="section / section (icon inline)">
          <Content
            icon={SvgSearch}
            sizePreset="section"
            variant="section"
            title="Section Section"
            description="Smaller preset, icon placed inline"
          />
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

        {/* ── optional props ── */}
        <Section label="optional props">
          <Content
            sizePreset="headline"
            variant="heading"
            title="No icon"
            description="Only title and description"
          />
          <Content
            icon={SvgSearch}
            sizePreset="headline"
            variant="heading"
            title="No description"
          />
          <Content sizePreset="headline" variant="heading" title="Title only" />
        </Section>
      </LayoutGroup>

      {/* ================================================================= */}
      {/*  LabelLayout                                                       */}
      {/* ================================================================= */}

      <LayoutGroup label="LabelLayout">
        {/* ── main-content ── */}
        <Section label="main-content">
          <Content
            icon={SvgSearch}
            sizePreset="main-content"
            title="Main Content Label"
            description="font-main-content-emphasis title, stroke-text-04 icon"
          />
          <Content
            icon={SvgSearch}
            sizePreset="main-content"
            title="Click edit to rename"
            description="Editable main-content label"
            editable
            onTitleChange={(v) => console.log("title changed:", v)}
          />
        </Section>

        {/* ── main-ui ── */}
        <Section label="main-ui">
          <Content
            icon={SvgSearch}
            sizePreset="main-ui"
            title="Main UI Label"
            description="font-main-ui-action title, stroke-text-03 icon"
          />
          <Content
            icon={SvgSearch}
            sizePreset="main-ui"
            title="Click edit to rename"
            description="Editable main-ui label"
            editable
            onTitleChange={(v) => console.log("title changed:", v)}
          />
        </Section>

        {/* ── secondary ── */}
        <Section label="secondary">
          <Content
            icon={SvgSearch}
            sizePreset="secondary"
            title="Secondary Label"
            description="font-secondary-action title, stroke-text-04 icon"
          />
          <Content
            icon={SvgSearch}
            sizePreset="secondary"
            title="Click edit to rename"
            description="Editable secondary label"
            editable
            onTitleChange={(v) => console.log("title changed:", v)}
          />
        </Section>

        {/* ── optional indicator ── */}
        <Section label="optional indicator">
          <Content
            icon={SvgSearch}
            sizePreset="main-content"
            title="Main Content"
            description="With (Optional) indicator"
            optional
          />
          <Content
            icon={SvgSearch}
            sizePreset="main-ui"
            title="Main UI"
            description="With (Optional) indicator"
            optional
          />
          <Content
            icon={SvgSearch}
            sizePreset="secondary"
            title="Secondary"
            description="With (Optional) indicator"
            optional
          />
        </Section>

        {/* ── aux icon ── */}
        <Section label="aux icon">
          <Content
            icon={SvgSearch}
            sizePreset="main-ui"
            title="Info gray"
            description="Neutral informational icon"
            auxIcon="info-gray"
          />
          <Content
            icon={SvgSearch}
            sizePreset="main-ui"
            title="Info blue"
            description="Highlighted informational icon"
            auxIcon="info-blue"
          />
          <Content
            icon={SvgSearch}
            sizePreset="main-ui"
            title="Warning"
            description="Warning status icon"
            auxIcon="warning"
          />
          <Content
            icon={SvgSearch}
            sizePreset="main-ui"
            title="Error"
            description="Error status icon"
            auxIcon="error"
          />
        </Section>

        <Section label="aux icon + optional + editable">
          <Content
            icon={SvgSearch}
            sizePreset="main-content"
            title="All accessories"
            description="Optional + aux icon + editable"
            optional
            auxIcon="warning"
            editable
            onTitleChange={(v) => console.log("title changed:", v)}
          />
          <Content
            icon={SvgSearch}
            sizePreset="secondary"
            title="All accessories"
            description="Optional + aux icon + editable at secondary"
            optional
            auxIcon="error"
            editable
            onTitleChange={(v) => console.log("title changed:", v)}
          />
        </Section>

        {/* ── optional props ── */}
        <Section label="optional props">
          <Content
            sizePreset="main-ui"
            title="No icon"
            description="Only title and description"
          />
          <Content
            icon={SvgSearch}
            sizePreset="main-ui"
            title="No description"
          />
          <Content sizePreset="main-ui" title="Title only" />
        </Section>
      </LayoutGroup>

      {/* ================================================================= */}
      {/*  BodyLayout                                                        */}
      {/* ================================================================= */}

      <LayoutGroup label="BodyLayout">
        {/* ── main-content ── */}
        <Section label="main-content / inline">
          <Content
            icon={SvgSearch}
            sizePreset="main-content"
            variant="body"
            orientation="inline"
            title="Default inline"
          />
          <Content
            icon={SvgSearch}
            sizePreset="main-content"
            variant="body"
            orientation="inline"
            prominence="muted"
            title="Muted inline"
          />
        </Section>

        <Section label="main-content / vertical">
          <Content
            icon={SvgSearch}
            sizePreset="main-content"
            variant="body"
            orientation="vertical"
            title="Default vertical"
          />
          <Content
            icon={SvgSearch}
            sizePreset="main-content"
            variant="body"
            orientation="vertical"
            prominence="muted"
            title="Muted vertical"
          />
        </Section>

        <Section label="main-content / reverse">
          <Content
            icon={SvgSearch}
            sizePreset="main-content"
            variant="body"
            orientation="reverse"
            title="Default reverse"
          />
          <Content
            icon={SvgSearch}
            sizePreset="main-content"
            variant="body"
            orientation="reverse"
            prominence="muted"
            title="Muted reverse"
          />
        </Section>

        {/* ── main-ui ── */}
        <Section label="main-ui / inline">
          <Content
            icon={SvgSearch}
            sizePreset="main-ui"
            variant="body"
            orientation="inline"
            title="Default inline"
          />
          <Content
            icon={SvgSearch}
            sizePreset="main-ui"
            variant="body"
            orientation="inline"
            prominence="muted"
            title="Muted inline"
          />
        </Section>

        <Section label="main-ui / vertical">
          <Content
            icon={SvgSearch}
            sizePreset="main-ui"
            variant="body"
            orientation="vertical"
            title="Default vertical"
          />
          <Content
            icon={SvgSearch}
            sizePreset="main-ui"
            variant="body"
            orientation="vertical"
            prominence="muted"
            title="Muted vertical"
          />
        </Section>

        <Section label="main-ui / reverse">
          <Content
            icon={SvgSearch}
            sizePreset="main-ui"
            variant="body"
            orientation="reverse"
            title="Default reverse"
          />
          <Content
            icon={SvgSearch}
            sizePreset="main-ui"
            variant="body"
            orientation="reverse"
            prominence="muted"
            title="Muted reverse"
          />
        </Section>

        {/* ── secondary ── */}
        <Section label="secondary / inline">
          <Content
            icon={SvgSearch}
            sizePreset="secondary"
            variant="body"
            orientation="inline"
            title="Default inline"
          />
          <Content
            icon={SvgSearch}
            sizePreset="secondary"
            variant="body"
            orientation="inline"
            prominence="muted"
            title="Muted inline"
          />
        </Section>

        <Section label="secondary / vertical">
          <Content
            icon={SvgSearch}
            sizePreset="secondary"
            variant="body"
            orientation="vertical"
            title="Default vertical"
          />
          <Content
            icon={SvgSearch}
            sizePreset="secondary"
            variant="body"
            orientation="vertical"
            prominence="muted"
            title="Muted vertical"
          />
        </Section>

        <Section label="secondary / reverse">
          <Content
            icon={SvgSearch}
            sizePreset="secondary"
            variant="body"
            orientation="reverse"
            title="Default reverse"
          />
          <Content
            icon={SvgSearch}
            sizePreset="secondary"
            variant="body"
            orientation="reverse"
            prominence="muted"
            title="Muted reverse"
          />
        </Section>

        {/* ── no icon ── */}
        <Section label="no icon">
          <Content
            sizePreset="main-ui"
            variant="body"
            title="Title only (no icon)"
          />
          <Content
            sizePreset="main-ui"
            variant="body"
            prominence="muted"
            title="Title only muted (no icon)"
          />
        </Section>
      </LayoutGroup>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Storybook helpers
// ---------------------------------------------------------------------------

function LayoutGroup({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        border: "2px solid #ccc",
        borderRadius: 12,
        padding: "1.5rem",
        marginBottom: "2.5rem",
      }}
    >
      <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: "1.5rem" }}>
        {label}
      </h2>
      {children}
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
    <section style={{ marginBottom: "2rem" }}>
      <h3
        style={{
          fontSize: 13,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: 1,
          opacity: 0.5,
          marginBottom: "0.75rem",
        }}
      >
        {label}
      </h3>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "0.75rem",
          border: "1px solid #e0e0e0",
          borderRadius: 8,
          padding: "1rem",
        }}
      >
        {children}
      </div>
    </section>
  );
}
