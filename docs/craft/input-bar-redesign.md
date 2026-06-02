# Craft Input Bar Redesign

Redesign of the Craft chat composer with three goals:

1. **Skill/app chips above the textarea.** Active skills and apps render as removable chips in a strip above the input (alongside file attachments) instead of inline tiles inside the contentEditable.
2. **`+` menu.** The paperclip is replaced by a `+` button that opens a popover with a Files action plus Skills and Apps **flyout panels** (anchored to the right, Anthropic-style).
3. **`BaseInputBar` abstraction.** The shell shared by Craft and the main app chat is extracted into a slot-based component so each surface only supplies what's unique to it.

## Components

| Component | Path | Responsibility |
|---|---|---|
| `BaseInputBar` | `web/src/sections/input/BaseInputBar.tsx` | Shared shell: container, contentEditable textarea (`useContentEditable`), submit/queue/interrupt logic, paste-tile popover. Exposes `topSlot` / `bottomLeftSlot` / `bottomRightSlot` plus extension hooks (`onBeforeKeyDown`, `onPasteText`, `onPasteFiles`, `onInputCallback`) and an imperative handle (`focus`, `setMessage`, `getTextBeforeCursor`, `getCaretRect`, `deleteBeforeToken`). |
| `SkillChipStrip` | `web/src/sections/input/SkillChipStrip.tsx` | Single flush-left row of chips. Skills/apps lead, files follow. Both use one `InputChip` primitive so sizing matches. |
| `PlusMenuButton` | `web/src/sections/input/PlusMenuButton.tsx` | `+` popover. Files is a direct action; Skills and Apps are nested Popovers opening to the right. |
| `CraftInputBar` | `web/src/app/craft/components/CraftInputBar.tsx` | Composes `BaseInputBar`. Owns `activeSkills` state, the `/` skill picker, and the skill-info popover. |

## Skill selection flow

Selecting a skill via the `/` picker **or** the `+` menu appends it to `CraftInputBar`'s `activeSkills` state (deduped by slug) — no inline DOM tile is created. On submit, active skills are serialized as `/<slug>` prefixes on the message, then cleared. Clicking a chip opens the read-only `SkillInfoPopover`.

## Scope

- Only Craft is affected. The main-app composer (`web/src/sections/input/AppInputBar.tsx`) is untouched.
- `BaseInputBar` is built as the shared shell intended for both surfaces, but migrating `AppInputBar` onto it (voice, deep research, multi-model, tab reading) is a follow-up.
