"use client";

// oxlint-disable i18n/no-raw-jsx-text -- throwaway debug gallery, never committed

import { useState } from "react";
import {
  InputComboBox,
  InputSelect,
  InputTags,
  Text,
  type TagItem,
} from "@opal/components";
import { SvgUsers } from "@opal/icons";

const OPTIONS = [
  { value: "1", label: "Engineering", description: "14 members" },
  { value: "2", label: "Design", description: "5 members" },
  { value: "3", label: "Sales", description: "9 members" },
  { value: "4", label: "Support", description: "7 members" },
  { value: "5", label: "Leadership", description: "3 members" },
];

function Block({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Text font="secondary-body" color="text-03">
        {label}
      </Text>
      {children}
    </div>
  );
}

function InputTagsDemo() {
  const [tags, setTags] = useState<TagItem[]>([
    { id: "1", label: "engineering" },
    { id: "2", label: "design" },
    { id: "3", label: "broken-tag", error: true },
  ]);
  const [text, setText] = useState("");

  return (
    <InputTags
      tags={tags}
      value={text}
      onChange={setText}
      placeholder="Type and press Enter…"
      onAdd={(value) => {
        setTags((prev) => [...prev, { id: String(Date.now()), label: value }]);
        setText("");
      }}
      onRemoveTag={(id) => {
        setTags((prev) => prev.filter((tag) => tag.id !== id));
      }}
      onClear={() => {
        setTags([]);
        setText("");
      }}
    />
  );
}

function InputSelectDemo() {
  const [value, setValue] = useState<string>("");

  return (
    <InputSelect value={value} onValueChange={setValue}>
      <InputSelect.Trigger placeholder="Choose a group" />
      <InputSelect.Content>
        {OPTIONS.map((opt) => (
          <InputSelect.Item
            key={opt.value}
            value={opt.value}
            icon={SvgUsers}
            description={opt.description}
          >
            {opt.label}
          </InputSelect.Item>
        ))}
      </InputSelect.Content>
    </InputSelect>
  );
}

function InputComboBoxDemo({ strict }: { strict: boolean }) {
  const [value, setValue] = useState("");

  return (
    <InputComboBox
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onValueChange={setValue}
      options={OPTIONS}
      strict={strict}
      placeholder={strict ? "Strict: options only" : "Loose: type anything"}
      searchIcon
    />
  );
}

export default function DbgPage() {
  return (
    <div className="mx-auto flex w-[32rem] flex-col gap-8 p-8 bg-background-tint-00 min-h-screen">
      <Block label="InputTags — free-text chips inline in the input (multi, open set)">
        <InputTagsDemo />
      </Block>

      <Block label="InputSelect — Radix dropdown, pick exactly one (single, closed set)">
        <InputSelectDemo />
      </Block>

      <Block label="InputComboBox strict — filter + pick from options (single, closed set)">
        <InputComboBoxDemo strict />
      </Block>

      <Block label="InputComboBox loose — options as suggestions, free text allowed (single, open set)">
        <InputComboBoxDemo strict={false} />
      </Block>

      <div className="flex flex-col gap-1">
        <Text font="secondary-body" color="text-03">
          The grid: InputSelect = single/closed · InputComboBox = single, closed
          (strict) or open (loose) · InputTags = multi/open. The empty cell is
          multi/closed — what the revamp adds to InputTags.
        </Text>
      </div>
    </div>
  );
}
