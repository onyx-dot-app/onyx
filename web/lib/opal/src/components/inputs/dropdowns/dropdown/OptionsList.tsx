import React from "react";
import { useOpalStrings } from "@opal/strings";
import { OptionItem } from "./OptionItem";
import type { SelectOption } from "../types";
import type { OptionGroup } from "../shared";
import { Divider } from "@opal/components/divider/components";
import { Text } from "@opal/components/text/components";
import { clickOnKeyDown } from "@opal/utils";
import { SvgPlus } from "@opal/icons";
import { sanitizeOptionId } from "./aria";

interface OptionsListProps {
  /** Post-filter, non-empty groups in render order. */
  sections: OptionGroup[];
  /** The supplied set itself is empty (options={[]}), not merely filtered out. */
  emptySet?: boolean;
  value: string;
  /** Multi-select: the chosen values. Overrides single-value selection. */
  selectedValues?: ReadonlySet<string>;
  /**
   * Paint every isExactMatch hit (multi marks all selected rows); without
   * it only the first hit paints, single-select's one-value semantics.
   */
  markAllMatches?: boolean;
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
  /** A click on a foldable group's title. */
  onToggleGroup?: (group: OptionGroup) => void;
}

/**
 * Renders the grouped option list: a titled Divider above each divider
 * group, plain rows for loose options, and the create row pinned first in
 * open mode.
 */
export const OptionsList: React.FC<OptionsListProps> = ({
  sections,
  emptySet,
  value,
  selectedValues,
  markAllMatches = false,
  highlightedIndex,
  fieldId,
  onSelect,
  onMouseEnter,
  onMouseMove,
  isExactMatch,
  inputValue,
  allowCreate,
  showCreateOption,
  onToggleGroup,
}) => {
  const strings = useOpalStrings();
  // Index offset for other options when create option is shown
  const indexOffset = showCreateOption ? 1 : 0;

  const totalOptions = sections.reduce(
    (count, section) => count + section.options.length,
    0
  );
  // A folded group withholds its rows but still shows its title, so a
  // list of folded groups is not empty.
  const hasFoldedGroups = sections.some((section) => section.folded);

  if (totalOptions === 0 && !showCreateOption && !hasFoldedGroups) {
    // An empty SET gets the icon'd empty state; a filter that matched
    // nothing keeps the lightweight text row.
    if (emptySet) {
      return (
        <div className="opal-select-empty-set">
          <Text as="p" color="text-03" font="secondary-body">
            {strings.selectEmptySet}
          </Text>
        </div>
      );
    }
    return (
      <div className="opal-select-no-match">{strings.comboBoxNoOptions}</div>
    );
  }

  // Free-form text commits trimmed: every match check trims the input side,
  // so an untrimmed value would never match itself on reopen.
  const createText = inputValue.trim();

  return (
    <>
      {/* Create New Option */}
      {showCreateOption && (
        <div
          id={`${fieldId}-option-${sanitizeOptionId(createText)}`}
          data-index={0}
          role="option"
          tabIndex={-1}
          aria-selected={false}
          aria-label={strings.comboBoxCreateOption(
            strings.comboBoxCreate,
            createText
          )}
          onClick={(e) => {
            e.stopPropagation();
            onSelect({ value: createText, title: createText });
          }}
          onKeyDown={clickOnKeyDown(() =>
            onSelect({ value: createText, title: createText })
          )}
          onMouseDown={(e) => {
            e.preventDefault();
          }}
          onMouseEnter={() => onMouseEnter(0)}
          onMouseMove={onMouseMove}
          className="opal-select-create"
          data-highlighted={highlightedIndex === 0 || undefined}
        >
          <span className="opal-select-create-label">{createText}</span>
          <SvgPlus className="opal-select-create-icon" />
        </div>
      )}

      {/* A line separates consecutive groups; it carries the group's title
          when it has one. A titled first group keeps its title line. */}
      {(() => {
        let globalIndex = indexOffset;
        let exactSeen = false;
        return sections.map((group, groupIdx) => {
          const isFoldable = group.foldable && group.title !== undefined;
          // The title claims its stop before the rows claim theirs.
          const headerIndex = isFoldable ? globalIndex++ : -1;
          const rows = group.options.map((option) => {
            const index = globalIndex++;
            const isExact =
              (markAllMatches || !exactSeen) && isExactMatch(option);
            if (isExact) exactSeen = true;
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
          });
          // A foldable group's title is its fold control and a keyboard stop
          // of its own; its rows are its children, withheld while folded.
          if (isFoldable && group.title !== undefined) {
            const index = headerIndex;
            return (
              <div
                key={groupIdx}
                id={`${fieldId}-group-${sanitizeOptionId(group.title)}`}
                role="presentation"
                className="opal-select-group"
                data-index={index}
                data-highlighted={index === highlightedIndex || undefined}
                onMouseEnter={() => onMouseEnter(index)}
                onMouseMove={onMouseMove}
              >
                <Divider
                  title={group.title}
                  foldable
                  open={!group.folded}
                  onOpenChange={() => onToggleGroup?.(group)}
                >
                  {rows}
                </Divider>
              </div>
            );
          }
          return (
            <React.Fragment key={groupIdx}>
              {group.title !== undefined ? (
                <Divider title={group.title} />
              ) : (
                groupIdx > 0 && <Divider />
              )}
              {rows}
            </React.Fragment>
          );
        });
      })()}
    </>
  );
};
