# InputPasswordTypeIn

**Import:** `import { InputPasswordTypeIn } from "@opal/components";`

A native password field on `InputTypeIn` with a reveal/hide toggle. The native `type="password"` (toggled to `"text"` when revealed) is what lets browsers and password managers recognize the field for autofill and save-password. Defaults `autoComplete` to `"new-password"` so managers do not autofill saved logins into secret fields (connector credentials, API keys). Login forms should override with `"current-password"`.

```tsx
<InputPasswordTypeIn
  value={secret}
  onChange={(e) => setSecret(e.target.value)}
  placeholder="Your long-term API key"
/>
```

## Behavior

- The reveal toggle is always visible. Revealed shows the `action` icon style, hidden shows the muted style.
- `isNonRevealable` disables the toggle for stored backend values that cannot be revealed. A value of all bullet characters (the backend's stored-secret placeholder) is treated as non-revealable automatically. The field stays editable for typing a replacement.
- `existingValue` marks a stored value from the backend, already masked. While `value` equals it, the field shows it as a medium blue `Tag` with the key icon, the input itself stays empty, and the reveal toggle is disabled. Backspace or Delete clears it, and typing or pasting replaces it with the new text. After the first edit, the field behaves as usual. To keep the stored value, compare the submitted value with `existingValue`.
- The hidden value shows as the browser's own dots at the field's normal text size, so the caret and dots never change size on reveal.
- `disabled` and `error` map onto the `InputTypeIn` chrome variants. All other `InputTypeIn` props pass through except `type`, `searchIcon`, `variant`, and `clearButton`; the component owns the first three and has no clear button. `rightChildren` renders after the reveal toggle, at the field's end (for example a dropdown chevron).
- Fields carry the `ph-no-capture` class (posthog-js's native replay blockClass), keeping masked and revealed secrets out of session replay, plus `data-ph-no-capture` for selector-configured tooling.
