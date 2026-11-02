# KeyValue

**Import:** `import { KeyValue, type KeyValueProps } from "@opal/layouts";`

One read-only "label … value" row: the label on the start side, the value on the end side. Use it for details of a saved object, such as an account's fields or the app's version. Stack rows in a `Section` with `gap`.

## Props

| Prop    | Type                | Default        | Description                                              |
| ------- | ------------------- | -------------- | -------------------------------------------------------- |
| `label` | `string \| RichStr` | **(required)** | The name of the value                                    |
| `value` | `string \| RichStr` | **(required)** | The value                                                |
| `mono`  | `boolean`           | `false`        | Sets the value in the mono font, as for a secret or a commit |

## Usage

```tsx
<Section gap={2} alignItems="stretch">
  <KeyValue label="Authentication Type" value="API Key" />
  <KeyValue label="API Key" value="sk-…a1b2" mono />
</Section>
```

Each side is capped at `--block-width-form-input-column-max` (240px). A long label or value is cut to one line and shows in full on hover (`OverflowText`).
