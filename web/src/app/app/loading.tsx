/**
 * The /app pages' loading boundary. A navigation between them commits here
 * first, with the new URL, before Next has the page's own loading state; it
 * shows the loader for that URL, so a page with one never flashes blank.
 * With it, Next also prefetches each page's shell. The chat view shows its
 * own skeleton.
 */
export { AppChromeLoader as default } from "@/layouts/chromes";
