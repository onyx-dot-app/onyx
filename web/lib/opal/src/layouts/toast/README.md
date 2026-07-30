# Toast

**Import:** `import { ToastProvider, useToast } from "@opal/layouts";` (imperative API: `import { toast } from "@opal/layouts";`)

Bottom-right toast stack. Toasts render as `MessageCard`s driven by a module-level store, so `toast(...)` works from anywhere: components, hooks, or plain TypeScript. Long messages truncate at 150 characters and expand on click, which restarts auto-dismiss at 30s for auto-dismissing toasts. Persistent toasts stay persistent.

```tsx
// Once, at the app root:
<ToastProvider errorAppendix="Need help? Contact support.">
  <App />
</ToastProvider>

// Anywhere:
toast.success("Document saved");
toast.error("Indexing failed", { description: "Connector timed out." });
toast.warning("Reindexing", { duration: Infinity });
```

## API

| Export | Description |
|---|---|
| `ToastProvider` | Renders children plus the stack. `errorAppendix` is appended to every error toast's description (e.g. a support link). |
| `toast(options)` / `.success` / `.error` / `.warning` / `.info` | Fire a toast, returns its id. Options: `description`, `duration` (ms, `Infinity` = persistent, default 4000), `dismissible` (default true). |
| `toast.dismiss(id)` / `toast.clearAll()` / `toast.setAutoDismiss(id, ms)` | Imperative controls. |
| `useToast()` | Hook returning `{ toast, dismiss, clearAll }`, subscribes the caller to store changes. |
| `useToastFromQuery(messages)` | Fires a toast from a `?message=<key>` query param on mount and strips the param. |
| `MAX_VISIBLE_TOASTS` | Cap on simultaneously rendered toasts (3). |

At most 3 toasts render at once. Older ones remain in the store but their auto-dismiss timers keep running while hidden. Every toast also logs to the console at its level. Stacking sits at `--z-toast` (1100), below popovers and tooltips.
