"use client";

import { useRef, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Dropdown,
  InputPasswordTypeIn,
  SelectChevron,
  Tag,
  type DropdownItem,
} from "@opal/components";
import { SvgKey } from "@opal/icons";
import { markdown } from "@opal/utils";
import { EMPTY_API_TOKEN_VALUE } from "@/lib/api-tokens/constants";
import { useApiTokens } from "@/lib/api-tokens/hooks";
import { getApiTokenPlatformLabel } from "@/lib/api-tokens/utils";
import type {
  ApiTokenPlatform,
  ApiTokenUsageKind,
  ApiTokenValue,
  ApiTokenView,
} from "@/lib/api-tokens/types";

/** What a saved key shows when its masked text is unknown. */
const FALLBACK_MASK = "••••••••••••";

const USAGE_KEYS = {
  llm_provider: "usage.llmProvider",
  image_generation: "usage.imageGeneration",
  voice_provider: "usage.voiceProvider",
  embedding_provider: "usage.embeddingProvider",
  web_search_provider: "usage.webSearchProvider",
  web_content_provider: "usage.webContentProvider",
  tracing_provider: "usage.tracingProvider",
  hook: "usage.hook",
  unstructured: "usage.unstructured",
} as const satisfies Record<ApiTokenUsageKind, string>;

export interface ApiTokenInputProps {
  /** The service the key is for. The list offers only that platform's saved keys. */
  platform: ApiTokenPlatform;
  value: ApiTokenValue;
  onChange: (value: ApiTokenValue) => void;
  onBlur?: (event: React.FocusEvent<HTMLInputElement>) => void;
  /**
   * The masked text of the key the row already uses, for when the list does
   * not hold it (a viewer who cannot list keys, or an Onyx-owned key).
   */
  savedMaskedValue?: string;
  id?: string;
  name?: string;
  disabled?: boolean;
  error?: boolean;
}

/**
 * An API key field: type a new key, or pick a saved key for the same
 * platform from the list under it. Typed text never filters the list or
 * shows in it, so a secret stays in the password field.
 */
export function ApiTokenInput({
  platform,
  value,
  onChange,
  onBlur,
  savedMaskedValue,
  id,
  name,
  disabled = false,
  error = false,
}: ApiTokenInputProps) {
  const t = useTranslations("common.apiTokens");
  const format = useFormatter();
  const platformLabel = getApiTokenPlatformLabel(platform);
  const { tokens, error: listError, isLoading } = useApiTokens(platform);
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  // Only full admins can list saved keys. For anyone else, and until the
  // keys have loaded, the list stays shut rather than claiming there are none.
  const canList = listError === undefined && !isLoading;

  const picked =
    value.type === "existing"
      ? tokens.find((token) => token.id === value.id)
      : undefined;
  const maskedText =
    value.type === "existing"
      ? (picked?.masked_value ?? savedMaskedValue ?? FALLBACK_MASK)
      : "";

  function usageDescription(token: ApiTokenView) {
    if (token.usages.length === 0) return undefined;
    const usages = format.list(
      token.usages.map((usage) =>
        t(USAGE_KEYS[usage.kind], { name: usage.name })
      ),
      { type: "conjunction" }
    );
    return markdown(t("usedFor", { usages }));
  }

  const items: DropdownItem[] = [
    {
      kind: "group",
      title: t("reuse.title", { platform: platformLabel }),
      items: tokens.map((token) => ({
        kind: "option",
        value: String(token.id),
        title: token.masked_value,
        description: usageDescription(token),
      })),
    },
  ];

  return (
    <Dropdown
      open={open && canList}
      onOpenChange={setOpen}
      disabled={disabled || !canList}
      tabKey="leave"
    >
      {/* Toggle, not open: a click on the field's label reaches the input,
          and it should close an open list like the chevron does. */}
      <Dropdown.Trigger asChild typeIn behavior="toggle">
        <InputPasswordTypeIn
          ref={inputRef}
          id={id}
          name={name}
          // A chosen key shows as a tag; the text box stays empty, so typing
          // starts a new key and Backspace drops the tag.
          value={value.type === "existing" ? "" : value.value}
          // Typing means a new key, so the saved-key list gets out of the way.
          onChange={(event) => {
            setOpen(false);
            onChange({ type: "new", value: event.target.value });
          }}
          onKeyDown={(event) => {
            if (value.type === "existing" && event.key === "Backspace") {
              onChange(EMPTY_API_TOKEN_VALUE);
            }
          }}
          onBlur={onBlur}
          placeholder={
            value.type === "existing" ? undefined : t("input.placeholder")
          }
          leftChildren={
            value.type === "existing" ? (
              <Tag color="blue" size="md" icon={SvgKey} title={maskedText} />
            ) : undefined
          }
          isNonRevealable={value.type === "existing"}
          // The browser's own dots, focused or not: no idle ✱ overlay.
          mask="native"
          disabled={disabled}
          error={error}
          rightChildren={
            canList ? (
              <SelectChevron
                isOpen={open}
                disabled={disabled}
                onToggle={() => {
                  setOpen((previous) => !previous);
                  inputRef.current?.focus();
                }}
              />
            ) : undefined
          }
        />
      </Dropdown.Trigger>
      <Dropdown.Data
        label={t("input.listLabel", { platform: platformLabel })}
        items={items}
        value={value.type === "existing" ? String(value.id) : ""}
        // Re-picking the selected key unselects it, like Opal's selects.
        onSelect={(option) => {
          const id = Number(option.value);
          onChange(
            value.type === "existing" && value.id === id
              ? EMPTY_API_TOKEN_VALUE
              : { type: "existing", id }
          );
        }}
      />
    </Dropdown>
  );
}
