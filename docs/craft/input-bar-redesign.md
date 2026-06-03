# Craft Input Bar Redesign

Redesign of the Craft chat composer:

1. **Entry chips above the textarea.** Active skills and apps render as removable chips in a strip above the input (alongside file attachments) instead of inline tiles inside the contentEditable.
2. **`+` menu.** The paperclip is replaced by a `+` button that opens downward with a Files action plus Skills and Apps **flyout panels** (open to the right on hover, Anthropic-style).
3. **`BaseInputBar` abstraction.** The shell shared by Craft and the main app chat is extracted into a slot-based component so each surface only supplies what's unique to it.
4. **Drag-and-drop.** Files dropped anywhere in the chat panel upload (react-dropzone, mirroring the main app).

## Components

| Component | Path | Responsibility |
|---|---|---|
| `BaseInputBar` | `web/src/sections/input/BaseInputBar.tsx` | Shared shell: container, contentEditable textarea (`useContentEditable`), submit/queue/interrupt logic, paste-tile popover. Exposes slots `topSlot` / `bottomLeftSlot` / `bottomRightSlot`, extension hooks (`onPasteText`, `onPasteFiles`, `onInputCallback`, `onSelectionChange`), and an imperative handle (`focus`, `setMessage`, `getTextBeforeCursor`, `getCaretRect`, `deleteBeforeToken`). |
| `InputChipStrip` | `web/src/sections/input/InputChipStrip.tsx` | Single flush-left row of chips (skills/apps lead, files follow), all using one `InputChip` primitive. Animates height on first/last chip and chip enter/exit (respects `prefers-reduced-motion`). |
| `PlusMenuButton` | `web/src/sections/input/PlusMenuButton.tsx` | Domain-agnostic `+` popover: a generic `items` array of action rows (`onSelect`) and flyout rows (`flyoutItems`), `null` entries as dividers. Flyouts open to the right on hover. |
| `EntryPickerPopover` / `EntryInfoPopover` | `web/src/sections/input/` | The `/` picker (Skills + Apps sections) and the read-only info popover shown when a chip is clicked. |
| `CraftInputBar` | `web/src/app/craft/components/CraftInputBar.tsx` | Composes `BaseInputBar`. Owns `activeEntries` state; wires `useSlashPicker` and `buildEntryMenuItems`. |
| `useSlashPicker` | `web/src/hooks/useSlashPicker.ts` | Drives the `/`-triggered picker (session/anchor + input/selection/select handlers) over a `BaseInputBar`, surfacing the chosen `PickerEntry`. |
| `buildEntryMenuItems` | `web/src/app/craft/components/buildEntryMenuItems.tsx` | Pure mapping of picker sections → `PlusMenuItem[]`. |

## Entry selection flow

Selecting an entry via the `/` picker **or** the `+` menu appends it to `CraftInputBar`'s `activeEntries` (deduped by slug) — no inline DOM tile is created. On submit, active entries are serialized as `/<slug>` prefixes on the message, then cleared. Clicking a chip opens the read-only `EntryInfoPopover`.

## Scope

- Only Craft is affected. The main-app composer (`web/src/sections/input/AppInputBar.tsx`) is untouched.
- `BaseInputBar`'s three slots (`topSlot` = files row, `bottomLeftSlot` = left controls, `bottomRightSlot` = mic) cover `AppInputBar`'s layout, so migrating it onto `BaseInputBar` (voice, deep research, multi-model, tab reading) is a follow-up PR.
