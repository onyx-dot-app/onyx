# States

**Import:** `import { ErrorState } from "@opal/layouts";`

`ErrorState`: content that failed to load, in place of a page body or a list. The broken-plug illustration with a title and a description, built on [`IllustrationContent`](../illustration-content/README.md) and centred both ways with [`PageCenter`](../page-center/README.md), as the page loader is. `SettingsLayouts.Body` renders it for `Root`'s `error`.

The app's list states, `NoResults` and `NoItems`, live in `web/src/lib/common/components.tsx`. For loading, use `PageLoader` from `@opal/loaders` (or `SettingsLayouts.Root loading`).

## Props

| Prop          | Type                | Default                                  | Description               |
| ------------- | ------------------- | ---------------------------------------- | ------------------------- |
| `title`       | `string \| RichStr` | **(required)**                           | What failed, e.g. "Agents failed to load" |
| `description` | `string \| RichStr` | `OpalStrings.errorStateDescription`      | Replaces the generic "Something went wrong" description |

## Usage

```tsx
<ErrorState title="Agents failed to load" />
```
