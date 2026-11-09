import { JSX } from "react";
import { useTranslations } from "next-intl";
import { FiChevronDown, FiXCircle } from "react-icons/fi";
import { SvgCheck } from "@opal/icons";
import { Dropdown, type DropdownMenuItem } from "@opal/components";
import { cn } from "@opal/utils";

interface Option {
  key: string;
  display: string | JSX.Element;
  displayName?: string;
  icon?: JSX.Element;
}

/**
 * A multi-select filter over options the caller renders. The rows are
 * custom, since an option's display is a node; the list filters by `key`.
 */
export function FilterDropdown({
  options,
  selected,
  handleSelect,
  icon,
  defaultDisplay,
  width = "w-64",
  resetValues,
  backgroundColor,
}: {
  options: Option[];
  selected: string[];
  handleSelect: (option: Option) => void;
  icon: JSX.Element;
  defaultDisplay: string | JSX.Element;
  width?: string;
  resetValues?: () => void;
  backgroundColor?: string;
}) {
  const t = useTranslations("common.filters");
  const items: DropdownMenuItem[] = options.map((option) => {
    const isSelected = selected.includes(option.key);
    return {
      kind: "custom",
      id: option.key,
      keywords: [option.displayName ?? option.key],
      keepOpen: true,
      onActivate: () => handleSelect(option),
      render: ({ highlighted, props }) => (
        <div
          {...props}
          className={cn(
            "flex w-full cursor-pointer select-none items-center gap-x-1 rounded-08 px-3 py-2.5 text-sm text-text-darker",
            highlighted && "bg-accent-background-hovered"
          )}
        >
          {option.icon}
          {option.display}
          {isSelected && (
            <div className="ms-auto my-auto me-1">
              <SvgCheck size={16} />
            </div>
          )}
        </div>
      ),
    };
  });

  return (
    <Dropdown>
      <Dropdown.Trigger asChild>
        {/* A focusable trigger; the clear control inside is its own button. */}
        <div
          role="button"
          tabIndex={0}
          className={`
            flex
            ${width}
            text-sm
            px-3
            py-1.5
            rounded-lg 
            border 
            gap-x-2
            border-border
            cursor-pointer 
            ${backgroundColor || "bg-background"}
            hover:bg-accent-background`}
        >
          <div className="flex-none my-auto">{icon}</div>
          {selected.length === 0 || resetValues ? (
            defaultDisplay
          ) : (
            <p className="line-clamp-1">{selected.join(", ")}</p>
          )}
          {resetValues && selected.length !== 0 ? (
            <button
              type="button"
              aria-label={t("clearButton.ariaLabel")}
              className="my-auto ms-auto p-0.5 rounded-full w-fit"
              onClick={(e) => {
                resetValues();
                e.stopPropagation();
              }}
            >
              <FiXCircle />
            </button>
          ) : (
            <FiChevronDown className="my-auto ms-auto" />
          )}
        </div>
      </Dropdown.Trigger>
      <Dropdown.Data
        label={typeof defaultDisplay === "string" ? defaultDisplay : ""}
        items={items}
      />
    </Dropdown>
  );
}
