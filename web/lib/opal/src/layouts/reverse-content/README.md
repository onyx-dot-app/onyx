# ReverseContent

**Import:** `import { ReverseContent, type ReverseContentProps } from "@opal/layouts";`

A title followed by an icon, such as a status label with its status icon. For an icon before or
above the title, with a description and the other extras, use [`Content`](../content/README.md).

The icon box is one title line tall with 2px padding, as in `Content`, and `color` / `titleColor`
work the same way.

## Props

| Prop         | Type                            | Default            | Description                                   |
| ------------ | ------------------------------- | ------------------ | --------------------------------------------- |
| `font`       | `TextFont`                      | `"main-ui-action"` | The title's font; the icon is sized from it   |
| `icon`       | `IconFunctionComponent`         | **(required)**     | The icon after the title                      |
| `title`      | `string \| RichStr`             | **(required)**     | The title                                     |
| `color`      | `StatusColor \| "interactive"`  | `"default"`        | Title and icon colour, as in `Content`        |
| `titleColor` | `Exclude<TextColor, "inherit">` | per `color`        | Overrides the title colour only               |

## Usage

```tsx
import { ReverseContent } from "@opal/layouts";
import { SvgCheckCircle } from "@opal/icons";

<ReverseContent font="main-ui-body" icon={SvgCheckCircle} title="Connected" />
```
