/**
 * The entry point for Opal's hooks.
 *
 * Each hook is declared as a default export in its own file; this names them
 * so callers outside Opal import from `@opal/hooks` rather than reaching for
 * the file. Opal's own files keep importing each other directly — a sibling
 * reaching back through the barrel is a cycle.
 */

export { default as useContainerCenter } from "@opal/hooks/useContainerCenter";
export { default as useFocusOnMount } from "@opal/hooks/useFocusOnMount";
export { default as useOnMount } from "@opal/hooks/useOnMount";
export {
  default as useScreenSize,
  type ScreenSize,
} from "@opal/hooks/useScreenSize";
