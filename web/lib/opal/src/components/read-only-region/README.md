# ReadOnlyRegion

**Import:** `import { ReadOnlyRegion } from "@opal/components";`

A region of the page the user can see but not use: a whole settings page on a plan that does not
include it, or a form while a request is pending. The children render as they are, dimmed, and
nothing inside can be clicked, focused or typed into.

Built on the `Disabled` primitive, which dims the region, blocks the pointer and disables the form
controls inside. On top of that the region is `inert`, so the browser also skips elements that are
focusable without being form controls, such as cards and rows with a key handler. Nothing inside can
take focus, so no popup or editor can open from it.

Use `ReadOnlyRegion` for a region of the page. For one control, use that control's own `disabled`
prop.

## Props

| Prop       | Type                | Default | Description                                                              |
| ---------- | ------------------- | ------- | ------------------------------------------------------------------------ |
| `readOnly` | `boolean`           | `true`  | Shown but unusable when `true`; renders the children as they are when `false` |
| `tooltip`  | `string \| RichStr` | —       | Why the region is read-only, shown on hover. Supports `markdown()`.      |

## Usage

```tsx
// A page the current plan does not include
<ReadOnlyRegion readOnly={!planIncludesIt} tooltip="Available on the Enterprise plan">
  <SettingsPage />
</ReadOnlyRegion>

// A form while its request is pending
<ReadOnlyRegion readOnly={isSaving}>
  <Form />
</ReadOnlyRegion>
```
