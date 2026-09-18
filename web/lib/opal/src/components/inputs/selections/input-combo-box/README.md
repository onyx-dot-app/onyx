# InputComboBox

**Import:** `import { InputComboBox, type InputComboBoxProps, type ComboBoxOption } from "@opal/components";`

A filterable input/select hybrid: with no options it behaves as a plain input; with options it
filters as you type, supports keyboard navigation, strict/non-strict modes, and an optional
create-new affordance. Integrates with the `@opal/form` field context for ids and error display.
Labels come from `OpalStrings` (`comboBox*`).
