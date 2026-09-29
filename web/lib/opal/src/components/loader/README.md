# Loader

**Import:** `import { OnyxLoader } from "@opal/components";`

The Onyx-branded loader. Takes a `color` token (default `border-02`) and holds still under `prefers-reduced-motion`.

## OnyxLoader

The Onyx-branded mark: the octagon outline and diamond logo crossfade while rotating a full turn on a 2s loop. Use it for Onyx-branded loading states.

```tsx
<OnyxLoader />
<OnyxLoader size={24} color="text-04" />
```

Props: `size` (px, default 64 with a ~2.5px stroke that scales), `color` (`LoaderColor`, default `border-02`). The mark geometry matches the `@opal/icons` `onyx-octagon` and `onyx-logo` paths. The stroke is defined locally rather than reusing those icon components so its weight can be tuned.

For a full-page loading state with a centered label, use `PageLoader` from `@opal/layouts`.
