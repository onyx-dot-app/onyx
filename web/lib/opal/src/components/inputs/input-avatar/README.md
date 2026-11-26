# InputAvatar

**Import:** `import { InputAvatar } from "@opal/components";`

A circular avatar frame wearing the primary input chrome — a Radix `Avatar.Root` (`h-10 w-10`,
`rounded-full`) with the same border/hover/focus treatment as a primary input. Compose Radix
`Avatar.Image` / `Avatar.Fallback` inside. Accepts all `Avatar.Root` props.

`tooltip` (`string | RichStr`) shows on hover. Inside `InputHorizontal` or `InputVertical`, the row's
`disabledTooltip` replaces it while the row is disabled. The avatar has no disabled state of its own.
