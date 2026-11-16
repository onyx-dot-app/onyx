# LogLine

**Import:** `import { LogLine } from "@opal/components";`

One line of a log or report: a [`Line`](../line/README.md) whose content is a
title column and centre content. A list of checks, the steps of a job, or the
entries of an audit trail are each a column of `LogLine`s, and the columns line
up from line to line.

## Props

Every [`Line`](../line/README.md) prop except `title` and `children`, plus:

| Prop             | Type                | Default | Description                                                                  |
| ---------------- | ------------------- | ------- | ---------------------------------------------------------------------------- |
| `title`          | `string \| RichStr` | —       | `secondary-action` in `text-03`, one line, in a 10rem column                 |
| `centerChildren` | `ReactNode`         | —       | Fills the rest of the row from its start; the caller sets its colour and fit |

Trailing content (a tag, actions, a fold chevron) goes in `Line`'s
`rightChildren`.

## Layout

The title column is exactly 10rem, and 1rem separates it from the centre
content. A title too long for its column is cut with an ellipsis and shows in
full in a tooltip. `centerChildren` handles its own overflow.

## Usage

```tsx
<LogLine
  variant="error-heavy"
  icon={SvgXCircle}
  title="Check attachment access"
  centerChildren={
    <Text font="main-ui-body" color="status-error-05" maxLines={1}>
      Attachment download timed out
    </Text>
  }
  rightChildren={<Tag title="Required" color="gray" />}
/>
```
