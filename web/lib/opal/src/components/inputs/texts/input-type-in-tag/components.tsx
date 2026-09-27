"use client";

import {
  TagField,
  type TagFieldBaseProps,
  type TagItem,
} from "@opal/components/inputs/texts/input-type-in-tag/TagField";

interface InputTypeInTagProps extends TagFieldBaseProps {
  /** Called with the trimmed input text on Enter (no-op when empty). */
  onAdd: (value: string) => void;
}

/**
 * Free tagging, the Figma `Input/Tags` component: editable `Tag`s inline
 * with a text input on the `.opal-input` chrome. Enter commits the typed
 * text through `onAdd`. There is nothing to select from; a field that
 * offers a set is `InputMultiSelect`.
 */
function InputTypeInTag({ onAdd, ...props }: InputTypeInTagProps) {
  return <TagField {...props} onEnter={onAdd} />;
}

export { InputTypeInTag, type InputTypeInTagProps, type TagItem };
