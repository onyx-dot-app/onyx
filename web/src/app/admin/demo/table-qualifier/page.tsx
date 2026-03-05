"use client";

import { useState } from "react";
import Text from "@/refresh-components/texts/Text";
import TableQualifier from "@/refresh-components/table/TableQualifier";
import { TableSizeProvider } from "@/refresh-components/table/TableSizeContext";
import type { TableSize } from "@/refresh-components/table/TableSizeContext";
import type { QualifierContentType } from "@/refresh-components/table/types";
import { SvgCheckCircle } from "@opal/icons";

// ---------------------------------------------------------------------------
// Content type configurations
// ---------------------------------------------------------------------------

interface ContentConfig {
  label: string;
  content: QualifierContentType;
  extraProps: Record<string, unknown>;
}

const CONTENT_TYPES: ContentConfig[] = [
  {
    label: "Simple",
    content: "simple",
    extraProps: {},
  },
  {
    label: "Icon",
    content: "icon",
    extraProps: { icon: SvgCheckCircle },
  },
  {
    label: "Image",
    content: "image",
    extraProps: {
      imageSrc: "https://picsum.photos/36",
      imageAlt: "Placeholder",
    },
  },
  {
    label: "Avatar Icon",
    content: "avatar-icon",
    extraProps: {},
  },
  {
    label: "Avatar User",
    content: "avatar-user",
    extraProps: { initials: "AJ" },
  },
];

// ---------------------------------------------------------------------------
// Row of qualifier states for a single content type
// ---------------------------------------------------------------------------

interface QualifierRowProps {
  config: ContentConfig;
}

function QualifierRow({ config }: QualifierRowProps) {
  const [selectableSelected, setSelectableSelected] = useState(false);
  const [permanentSelected, setPermanentSelected] = useState(true);

  return (
    <div className="space-y-2">
      <Text mainUiAction text02>
        {config.label}
      </Text>

      <div className="flex items-start gap-8">
        {/* Default */}
        <div className="flex w-20 flex-col items-center gap-2">
          <TableQualifier
            content={config.content}
            selectable={false}
            selected={false}
            disabled={false}
            {...config.extraProps}
          />
          <Text secondaryBody text04>
            Default
          </Text>
        </div>

        {/* Selectable (hover to reveal checkbox) */}
        <div className="flex w-20 flex-col items-center gap-2">
          <TableQualifier
            content={config.content}
            selectable={true}
            selected={selectableSelected}
            disabled={false}
            onSelectChange={setSelectableSelected}
            {...config.extraProps}
          />
          <Text secondaryBody text04>
            Selectable
          </Text>
        </div>

        {/* Selected */}
        <div className="flex w-20 flex-col items-center gap-2">
          <TableQualifier
            content={config.content}
            selectable={true}
            selected={permanentSelected}
            disabled={false}
            onSelectChange={setPermanentSelected}
            {...config.extraProps}
          />
          <Text secondaryBody text04>
            Selected
          </Text>
        </div>

        {/* Disabled (unselected) */}
        <div className="flex w-20 flex-col items-center gap-2">
          <TableQualifier
            content={config.content}
            selectable={true}
            selected={false}
            disabled={true}
            {...config.extraProps}
          />
          <Text secondaryBody text04>
            Disabled
          </Text>
        </div>

        {/* Disabled (selected) */}
        <div className="flex w-20 flex-col items-center gap-2">
          <TableQualifier
            content={config.content}
            selectable={true}
            selected={true}
            disabled={true}
            {...config.extraProps}
          />
          <Text secondaryBody text04>
            Disabled+Sel
          </Text>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Size section — all content types at a given size
// ---------------------------------------------------------------------------

interface SizeSectionProps {
  size: TableSize;
  title: string;
}

function SizeSection({ size, title }: SizeSectionProps) {
  return (
    <div className="space-y-6">
      <Text headingH3>{title}</Text>
      <TableSizeProvider size={size}>
        <div className="flex flex-col gap-8">
          {CONTENT_TYPES.map((config) => (
            <QualifierRow key={`${size}-${config.content}`} config={config} />
          ))}
        </div>
      </TableSizeProvider>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function TableQualifierDemoPage() {
  return (
    <div className="p-6 space-y-10">
      <div className="space-y-4">
        <Text headingH2>TableQualifier Demo</Text>
        <Text mainContentMuted text03>
          All content types, sizes, and interactive states. Hover selectable
          variants to reveal the checkbox; click to toggle.
        </Text>
      </div>

      <SizeSection size="regular" title="Regular (36px)" />
      <SizeSection size="small" title="Small (28px)" />
    </div>
  );
}
