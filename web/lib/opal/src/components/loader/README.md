# Loader

**Import:** `import { IconLoader, OnyxLoader } from "@opal/components";`

Two loaders: a generic `IconLoader` that spins any icon, and the Onyx-branded `OnyxLoader`. Both take a `color` token (default `border-02`) and hold still under `prefers-reduced-motion`.

## IconLoader

The generic loader. Spins the `icon` you pass, or the default `SvgLoader` spinner. Use it when you want a loader with your own icon and no Onyx branding.

```tsx
import { IconLoader } from "@opal/components";
import SvgSettings from "@opal/icons/settings";

<IconLoader />                          // default spinner
<IconLoader icon={SvgSettings} />       // any icon
<IconLoader size={32} color="status-error-05" />
```

Props: `icon` (`IconFunctionComponent`, default `SvgLoader`), `size` (px, default 24), `color` (`LoaderColor`, default `border-02`).

## OnyxLoader

The Onyx-branded mark: the octagon outline and diamond logo crossfade while rotating a full turn on a 2s loop. Use it for Onyx-branded loading states.

```tsx
<OnyxLoader />
<OnyxLoader size={24} color="text-04" />
```

Props: `size` (px, default 64 with a ~2.5px stroke that scales), `color` (`LoaderColor`, default `border-02`). The mark geometry matches the `@opal/icons` `onyx-octagon` and `onyx-logo` paths. The stroke is defined locally rather than reusing those icon components so its weight can be tuned.

For a full-page loading state with a centered label, use `PageLoader` from `@opal/layouts`.
