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

Toasts stack like a phone's notifications. The newest slides in at the top and pushes the others down. Past 3, the oldest tuck into a pile below the stack: the two newest piled toasts peek out as layered edges behind the stack, and a "+N more" count sits under them. A toast counts down only while on show: a piled toast keeps its time left and resumes when it rises back into a slot. A leaving toast slides off toward the end side (right in LTR, left in RTL) and fades while it holds its slot; then its space closes and the next piled toast rises into the freed slot, in one motion. Toasts layer by their place in the stack, top highest. Every toast also logs to the console at its level.

The stack sits at `--z-toast` (1250): above modals, popovers and banners, so a notification is never hidden behind an open menu, and below only tooltips, so a toast's own button tooltip (its retry action) still shows.

## Design decisions

### The pile does not expand

Piled toasts cannot be expanded into a list. To reach an older toast, dismiss the newer ones until it rises into a slot. The "+N more" count is the only cue, and it is not a control.

Why: these are toasts. More than 10 at once is very unlikely, and an expandable list needs a capped, scrolling box that looks poor when the cap is reached. A repeating toast should pass an `id` instead, so it updates one toast rather than piling up (see `useErrorToast`).

To bring expansion back (it existed in commit `91bebe6661` on `feat/toast-overflow`):

1. In `ToastContainer`, hold `pileOpen` state. While open, pass `pileDepth={undefined}` to every `ToastCard`, so all toasts render in full.
2. Pause every timer while open: add a `timersPaused` flag to the store that makes `syncTimers` treat no toast as shown, and expose a `setTimersPaused(paused)` on `toastStore`, set from an effect on `pileOpen`.
3. Close the pile when it empties (`pileCount === 0`) and on Escape.
4. Make "+N more" a `Button` (`prominence="secondary"`, `aria-expanded`) that toggles `pileOpen`, labelled "Show less" while open. Add a `toastShowLess` string to `OpalStrings`, the bridge and every locale.
5. Give the open stack (`.opal-toast-stack[data-open]`) a `max-height` with `overflow-y: auto` and `overflow-x: hidden`, padding with a matching negative margin and extra width so the cards' shadows are not clipped, and hidden scrollbars.

