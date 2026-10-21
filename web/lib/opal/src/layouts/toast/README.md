# Toast

**Import:** `import { ToastProvider, useToast } from "@opal/layouts";` (imperative API: `import { toast } from "@opal/layouts";`)

Top-centre toast stack, 0.5rem from the top. Toasts render as `MessageCard`s driven by a module-level store, so `toast(...)` works from anywhere: components, hooks, or plain TypeScript. A title stays on one line; when that line cuts it off, a chevron beside the close button shows and hides the full message, and expanding restarts auto-dismiss at 30s for auto-dismissing toasts. Persistent toasts stay persistent.

```tsx
// Once, at the app root:
<ToastProvider errorAppendix="Need help? Contact support.">
  <App />
</ToastProvider>;

// Anywhere:
toast.success("Document saved");
toast.error("Indexing failed", { description: "Connector timed out." });
toast.warning("Reindexing", { duration: Infinity });
```

## API

| Export                                                                    | Description                                                                                                                                 |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `ToastProvider`                                                           | Renders children plus the stack. `errorAppendix` is appended to every error toast's description (e.g. a support link).                      |
| `toast(options)` / `.success` / `.error` / `.warning` / `.info`           | Fire a toast, returns its id. Options: `description`, `duration` (ms, `Infinity` = persistent, default 4000), `dismissible` (default true), `id` (a live toast with the same id is replaced in place), `action` (`{ icon, label, onClick }`: an icon button left of the close button, `label` as its tooltip; a click runs it and the toast stays, so an action that should close it calls `toast.dismiss(id)`). |
| `toast.dismiss(id)` / `toast.clearAll()` / `toast.setAutoDismiss(id, ms)` | Imperative controls. `dismiss` animates the toast out, as the close button and a timeout do; `clearAll` removes every toast at once. |
| `useToast()`                                                              | Hook returning `{ toast, dismiss, clearAll }`, subscribes the caller to store changes.                                                      |
| `useToastFromQuery(messages)`                                             | Fires a toast from a `?message=<key>` query param on mount and strips the param.                                                            |
| `useErrorToast(error, { id, message, retry })`                            | For a failed fetch: a persistent error toast while `error` is set, with an optional retry button (`retry: { label, onRetry }`). A new error updates it in place, with no replayed animation; it goes only when the error clears or the caller unmounts. Callers sharing an `id` share one toast. |
| `MAX_VISIBLE_TOASTS`                                                      | Cap on simultaneously rendered toasts (3).                                                                                                  |

Toasts stack like a phone's notifications. The newest slides in at the top and pushes the others down. Past 3, the oldest tuck into a pile below the stack: their edges peek out as layered cards, with a "+N more" button that expands the pile into a scrolling list (Escape or "Show less" closes it). A toast counts down only while on show: a piled toast keeps its time left and resumes when it rises back into a slot, and an open pile pauses every timer. A leaving toast slides off toward the end side (right in LTR, left in RTL) and fades, then its space closes and the toasts below move up. Every toast also logs to the console at its level. Stacking sits at `--z-toast` (1100), below popovers and tooltips.
