# AvatarButton

**Import:** `import { AvatarButton, type AvatarButtonProps } from "@opal/components";`

A round button around an avatar, for a control that edits the avatar. Hover and keyboard focus
show a gray overlay with a pencil. The overlay also shows while a menu it opens is open, and
always on touch screens. The avatar inside is decorative, so `aria-label` is required.

It takes the `<button>` attributes, spreads them and forwards its ref, so it can be a
`Dropdown.Trigger asChild`.

## Props

| Prop         | Type        | Default | Description                         |
| ------------ | ----------- | ------- | ----------------------------------- |
| `aria-label` | `string`    | —       | The button's accessible name        |
| `size`       | `number`    | —       | Diameter in pixels                  |
| `children`   | `ReactNode` | —       | The avatar, drawn at `size`         |
| `disabled`   | `boolean`   | `false` | Disables the button and its overlay |
| `busy`       | `boolean`   | `false` | Looks disabled and sets `aria-busy`, but keeps focus; the caller ignores clicks |

## Usage

```tsx
<AvatarButton aria-label="Upload a profile photo" size={40} onClick={pick}>
  <UserAvatar name={name} email={email} size={40} />
</AvatarButton>
```
