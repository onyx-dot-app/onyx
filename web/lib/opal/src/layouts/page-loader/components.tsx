import type { RichStr } from "@opal/types";
import { OnyxLoader, Text } from "@opal/components";

// ---------------------------------------------------------------------------
// PageLoader
// ---------------------------------------------------------------------------

interface PageLoaderProps {
  /** Label beneath the mark, markdown() opt-in. @default "Loading …" */
  text?: string | RichStr;
}

/**
 * Full-page loading state: the animated Onyx mark with a label, centered in
 * the available space. Use for page/route-level loading. For an inline or
 * section-level loader without a label, use `OnyxLoader` directly.
 */
function PageLoader({ text = "Loading …" }: PageLoaderProps) {
  return (
    <div className="flex h-full min-h-[60vh] w-full flex-col items-center justify-center gap-3 p-5">
      <OnyxLoader />
      <Text font="main-ui-muted" color="text-03">
        {text}
      </Text>
    </div>
  );
}

export { PageLoader, type PageLoaderProps };
