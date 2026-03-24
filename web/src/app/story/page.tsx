"use client";

import SvgOnyxLogo from "@opal/icons/onyx-logo";
import SvgOnyxTyped from "@opal/icons/onyx-typed";
import SvgOnyxLogoTyped from "@opal/icons/onyx-logo-typed";
import Text from "@/refresh-components/texts/Text";

const SIZES = [16, 24, 32, 48, 64];

function IconRow({
  label,
  children,
}: {
  label: string;
  children: (size: number) => React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4">
      <Text mainContentBody text02>
        {label}
      </Text>
      <div className="flex flex-row items-end gap-6">
        {SIZES.map((size) => (
          <div key={size} className="flex flex-col items-center gap-2">
            {children(size)}
            <Text secondaryBody text03>
              {size}px
            </Text>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function StoryPage() {
  return (
    <div className="flex flex-col gap-12 p-12">
      <Text headingH3>Onyx Icons</Text>

      <IconRow label="SvgOnyxLogo">
        {(size) => <SvgOnyxLogo size={size} />}
      </IconRow>

      <IconRow label="SvgOnyxTyped">
        {(size) => <SvgOnyxTyped size={size} />}
      </IconRow>

      <IconRow label="SvgOnyxLogoTyped">
        {(size) => <SvgOnyxLogoTyped size={size} />}
      </IconRow>

      <div className="flex flex-col gap-4">
        <Text mainContentBody text02>
          Dark background
        </Text>
        <div className="flex flex-row items-center gap-8 bg-background-inverted-neutral-01 p-6 rounded-08">
          <SvgOnyxLogo size={32} />
          <SvgOnyxTyped size={32} />
          <SvgOnyxLogoTyped size={32} />
        </div>
      </div>
    </div>
  );
}
