# IconContainer

**Import:** `import { IconContainer, type IconContainerProps } from "@opal/components";`

Fixed-size icon slot, the Figma Icon Container. One primitive covers the bare glyph, the user avatar (photo, else initials on a dark circle), the icon-in-circle badge (light circle), and logo slots.

## Props

| Prop     | Type                                | Default     | Description                                                                                                                                                                      |
| -------- | ----------------------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `size`   | `IconContainerSize`                 | `"main-ui"` | Box keyed to the line-height scale: secondary 16, main-ui 20, main-content 24, section 28, sub-headline 32                                                                       |
| `type`   | `"default" \| "entity" \| "action"` | `"default"` | Reading prominence. `entity` renders `text-04` at every size, `action` emits `data-type="action"` as a styling hook and currently renders like `default`                         |
| `icon`   | `IconFunctionComponent`             | —           | Glyph for the bare content, required with `avatar="icon"`. Logos from `@opal/logos` work here too                                                                                |
| `avatar` | `"user" \| "icon"`                  | —           | Round avatar: `user` is the photo, else the initials, else a person glyph, `icon` is the light circle around `icon`. The content union makes an avatar without its content a type error |
| `initials` | `string \| null`                | —           | Required with `avatar="user"`: up to two letters on the dark circle (the app derives them with `getUserInitials`). `null` shows a person glyph on a light circle. Both scale with the circle |
| `src`    | `string \| null`                    | —           | Optional with `avatar="user"`: photo URL shown in the circle. The initials show when it is missing or fails to load                                                              |
| `diameter` | `number`                        | —           | Optional with `avatar="user"`: circle diameter in pixels for avatars outside the presets, such as a 40px profile photo. It renders in rem, and the box matches it |

Glyph sizes follow the spec (12 at secondary, 16 at main-ui and main-content, 24 at section and sub-headline, with entity bumping main-ui to 18). The avatar circle fills the box up to 24px, or matches `diameter` when it is set.

## Usage

```tsx
// Bare glyph beside main-ui text
<IconContainer icon={SvgSearch} />

// User avatar, with an optional photo
<IconContainer size="section" avatar="user" initials={getUserInitials(name, email)} src={photoUrl} />

// Icon badge
<IconContainer avatar="icon" icon={SvgSlack} />
```

Default glyph color ascends with the size preset (`text-02` at secondary, `text-03` at main-ui and main-content, `text-04` at section and sub-headline). A user avatar shows its `src` photo when set. Otherwise it shows `initials`, or a person glyph when they are `null`.

## Tinted icons

`tintedIcon(Icon, tint)` returns `Icon` drawn in a quiet theme colour: one of `ICON_TINTS` (`blue`,
`green`, `purple`, `amber`, `cyan`, `magenta`, `orange`, `sky`), half mixed with the neutral icon
colour. Pass the result anywhere an icon component goes, such as `Content` or `LineItemButton`.

```tsx
<Content icon={tintedIcon(SvgServer, "cyan")} title="sql-helper" />
```
