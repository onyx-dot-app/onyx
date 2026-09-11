import React from "react";
import { useOpalStrings } from "@opal/strings";
import { OptionItem } from "./OptionItem";
import { SelectOption, SelectSection } from "../types";
import { Divider } from "@opal/components/divider/components";
import { cn, clickOnKeyDown } from "@opal/utils";
import { SvgPlus } from "@opal/icons";
import { sanitizeOptionId } from "./aria";

interface OptionsListProps {
  /** Post-filter, non-empty sections in render order. */
  sections: SelectSection[];
  value: string;
  /** Multi-select: the chosen values. Overrides single-value selection. */
  selectedValues?: ReadonlySet<string>;
  highlightedIndex: number;
  fieldId: string;
  onSelect: (option: SelectOption) => void;
  onMouseEnter: (index: number) => void;
  onMouseMove: () => void;
  isExactMatch: (option: SelectOption) => boolean;
  /** Current input value for creating new option */
  inputValue: string;
  /** Whether to show create option when no exact match */
  allowCreate: boolean;
  /** Whether to show create option (pre-computed by parent) */
  showCreateOption: boolean;
  /** Prefix shown before the typed value in the create option (e.g., "Use", "Add") */
  createPrefix?: string;
}

/**
 * Renders the sectioned option list: a Divider between sections, an optional
 * muted heading per section, and the create row pinned first in open mode.
 */
export const OptionsList: React.FC<OptionsListProps> = ({
  sections,
  value,
  selectedValues,
  highlightedIndex,
  fieldId,
  onSelect,
  onMouseEnter,
  onMouseMove,
  isExactMatch,
  inputValue,
  allowCreate,
  showCreateOption,
  createPrefix,
}) => {
  const strings = useOpalStrings();
  // Index offset for other options when create option is shown
  const indexOffset = showCreateOption ? 1 : 0;

  const totalOptions = sections.reduce(
    (count, section) => count + section.options.length,
    0
  );

  if (totalOptions === 0 && !showCreateOption) {
    return (
      <div className="px-3 py-2 text-text-02 font-secondary-body">
        {strings.comboBoxNoOptions}
      </div>
    );
  }

  return (
    <>
      {/* Create New Option */}
      {showCreateOption && (
        <div
          id={`${fieldId}-option-${sanitizeOptionId(inputValue)}`}
          data-index={0}
          role="option"
          tabIndex={-1}
          aria-selected={false}
          aria-label={strings.comboBoxCreateOption(
            createPrefix ?? strings.comboBoxCreate,
            inputValue
          )}
          onClick={(e) => {
            e.stopPropagation();
            onSelect({ value: inputValue, label: inputValue });
          }}
          onKeyDown={clickOnKeyDown(() =>
            onSelect({ value: inputValue, label: inputValue })
          )}
          onMouseDown={(e) => {
            e.preventDefault();
          }}
          onMouseEnter={() => onMouseEnter(0)}
          onMouseMove={onMouseMove}
          className={cn(
            "cursor-pointer transition-colors",
            "flex items-center justify-between rounded-08",
            highlightedIndex === 0 && "bg-background-tint-02",
            "hover:bg-background-tint-02",
            createPrefix ? "px-1.5 py-1.5" : "px-3 py-2"
          )}
        >
          <span
            className={cn(
              "font-main-ui-action truncate min-w-0",
              createPrefix ? "px-1" : ""
            )}
          >
            {createPrefix ? (
              <>
                <span className="text-text-03">{createPrefix}</span>
                <span className="text-text-04">{` ${inputValue}`}</span>
              </>
            ) : (
              <span className="text-text-04">{inputValue}</span>
            )}
          </span>
          <SvgPlus
            className={cn(
              "w-4 h-4 shrink-0",
              createPrefix ? "text-text-04 mx-1" : "text-text-03 ms-2"
            )}
          />
        </div>
      )}

      {/* Sections: a Divider between each, an optional heading per section */}
      {(() => {
        let globalIndex = indexOffset;
        return sections.map((section, sectionIdx) => {
          const rows = (
            <React.Fragment key={section.label ?? `section-${sectionIdx}`}>
              {section.label ? (
                <Divider title={section.label} />
              ) : (
                sectionIdx > 0 && (
                  <Divider paddingParallel={0} paddingPerpendicular={0} />
                )
              )}
              {section.options.map((option) => {
                const index = globalIndex++;
                const isExact = isExactMatch(option);
                return (
                  <OptionItem
                    key={option.value}
                    option={option}
                    index={index}
                    fieldId={fieldId}
                    isHighlighted={index === highlightedIndex}
                    isSelected={
                      selectedValues
                        ? selectedValues.has(option.value)
                        : value === option.value
                    }
                    isExact={isExact}
                    onSelect={onSelect}
                    onMouseEnter={onMouseEnter}
                    onMouseMove={onMouseMove}
                    searchTerm={inputValue}
                  />
                );
              })}
            </React.Fragment>
          );
          return rows;
        });
      })()}
    </>
  );
};
