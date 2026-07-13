# Loader

**Import:** `import { OnyxLoader, PageLoader } from "@opal/components";`

Onyx-branded loading states. Animation timing and geometry follow the Onyx UI Library design.

- **`OnyxLoader`** renders the animated mark alone: the Onyx octagon outline and diamond logo crossfade while rotating a full turn on a 2s loop. Both layers use `currentColor` (default `border-02`), so the mark adapts to the surrounding theme. `size` prop in pixels, default 64 with a ~2.5px stroke that scales. Respects `prefers-reduced-motion` by holding the static outline.
- **`PageLoader`** is the full-page loading state: the mark centered with a label beneath (`text` prop, `string | RichStr` for `markdown()` opt-in, default "Loading …"). Use for page and route-level loading. For an inline or section-level loader without a label, use `OnyxLoader` directly.

```tsx
// Route-level
if (isLoading) return <PageLoader />;

// Inline
<OnyxLoader size={24} />
```

The mark geometry matches the `@opal/icons` `onyx-octagon` and `onyx-logo` paths. The stroke is defined locally rather than reusing those icon components so its weight can be tuned (Figma `Weight/Icon/Headline` at the default size).
