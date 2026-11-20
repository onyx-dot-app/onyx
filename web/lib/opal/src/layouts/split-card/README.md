# SplitCard

**Import:** `import { SplitCard, type SplitCardProps } from "@opal/layouts";`

A bordered card in two panes: a narrow aside (14rem, 10rem on small screens) beside a main pane that
takes the rest. Use it for a list beside a viewer of the selected item, such as the files of a skill.

## Props

| Prop        | Type        | Default | Description                                  |
| ----------- | ----------- | ------- | -------------------------------------------- |
| `aside`     | `ReactNode` | —       | The narrow pane at the start                 |
| `children`  | `ReactNode` | —       | The main pane                                |
| `minHeight` | `number`    | —       | Minimum height of the card, in rem           |

## Usage

```tsx
<SplitCard minHeight={32} aside={<FileList />}>
  <FileViewer />
</SplitCard>
```
