# IconContainer

**Import:** `import { IconContainer, type IconContainerProps } from "@opal/components";`

Fixed-size icon slot, the Figma Icon Container. One primitive covers the bare glyph, the user avatar (dark circle with an initial), the icon-in-circle badge (light circle), and logo slots.

## Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `size` | `IconContainerSize` | `"main-ui"` | Box keyed to the line-height scale: secondary 16, main-ui 20, main-content 24, section 28, sub-headline 32 |
| `type` | `"default" \| "entity" \| "action"` | `"default"` | Reading prominence. `entity` renders `text-04` at every size, `action` emits `data-type="action"` as a styling hook and currently renders like `default` |
| `icon` | `IconFunctionComponent` | — | Glyph for the bare content, required with `avatar="icon"`. Logos from `@opal/logos` work here too |
| `avatar` | `"user" \| "icon"` | — | Round avatar: `user` is the dark circle with the initial of `name`, `icon` is the light circle around `icon`. The content union makes an avatar without its content a type error |
| `name` | `string` | — | Required with `avatar="user"`: initial source (first character after trim, uppercased, `?` fallback for empty strings) |

Glyph sizes follow the spec (12 at secondary, 16 at main-ui and main-content, 24 at section and sub-headline, with entity bumping main-ui to 18). The avatar circle fills the box up to 24px.

## Usage

```tsx
// Bare glyph beside main-ui text
<IconContainer icon={SvgSearch} />

// User avatar
<IconContainer size="section" avatar="user" name={user.displayName} />

// Icon badge
<IconContainer avatar="icon" icon={SvgSlack} />
```

Default glyph color ascends with the size preset (`text-02` at secondary, `text-03` at main-ui and main-content, `text-04` at section and sub-headline). Uploaded-image avatars are not in the Figma spec and are out of scope. The avatar renders an initial or an icon only.
