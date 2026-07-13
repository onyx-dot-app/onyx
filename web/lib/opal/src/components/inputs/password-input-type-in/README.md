# PasswordInputTypeIn

**Import:** `import { PasswordInputTypeIn } from "@opal/components";`

A native password field on `InputTypeIn` with a reveal/hide toggle. The native `type="password"` (toggled to `"text"` when revealed) is what lets browsers and password managers recognize the field for autofill and save-password. Defaults `autoComplete` to `"new-password"` so managers do not autofill saved logins into secret fields (connector credentials, API keys). Login forms should override with `"current-password"`.

```tsx
<PasswordInputTypeIn
  value={secret}
  onChange={(e) => setSecret(e.target.value)}
  placeholder="Your long-term API key"
/>
```

## Behavior

- The reveal toggle appears while the field has a value or focus. Revealed shows the `action` icon style, hidden shows the muted style.
- `isNonRevealable` disables the toggle for stored backend values that cannot be revealed. A value of all bullet characters (the backend's stored-secret placeholder) is treated as non-revealable automatically. The field stays editable for typing a replacement.
- While masked, the field shrinks the native mask dots for tighter spacing. `shrinkPlaceholder` opts the placeholder into the same size. Intended only for masked-style all-bullet placeholders, text placeholders stay legible at full size.
- `disabled` and `error` map onto the `InputTypeIn` chrome variants. All other `InputTypeIn` props pass through except `type`, `rightChildren`, `searchIcon`, `variant`, and `clearButton`, which the component owns.
- Fields carry the `ph-no-capture` class (posthog-js's native replay blockClass), keeping masked and revealed secrets out of session replay, plus `data-ph-no-capture` for selector-configured tooling.
