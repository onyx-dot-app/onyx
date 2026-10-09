# Loader

**Import:** `import { OnyxLoader } from "@opal/components";`

The Onyx-branded mark: the octagon outline and diamond logo crossfade while rotating a full turn on a 2s loop. It takes a `color` token (default `border-02`) and holds still under `prefers-reduced-motion`.

```tsx
<OnyxLoader />
<OnyxLoader size={24} color="text-04" />
```

Props: `size` (px, default 64 with a ~2.5px stroke that scales), `color` (`LoaderColor`, default `border-02`). The mark geometry matches the `@opal/icons` `onyx-octagon` and `onyx-logo` paths. The stroke is defined locally rather than reusing those icon components so its weight can be tuned.

The loaders for app use (`PageLoader`, `IconLoader`, `CardLoader`, `LineLoader`, `TextLoader`) live in `@opal/loaders`.
