import { forwardRef, useCallback, type Ref } from "react";
import {
  BottomSheetModal,
  BottomSheetBackdrop,
  type BottomSheetModalProps,
  type BottomSheetBackdropProps,
} from "@gorhom/bottom-sheet";
import type { BottomSheetModalMethods } from "@gorhom/bottom-sheet/lib/typescript/types";

import { useThemeColors } from "@/theme/ThemeProvider";

// ---------------------------------------------------------------------------
// BottomSheet — a thin themed wrapper over @gorhom/bottom-sheet's
// BottomSheetModal.
//
//   const ref = useRef<BottomSheetModal>(null);
//   ...
//   <BottomSheet ref={ref} snapPoints={["50%"]}>
//     <View>...content...</View>
//   </BottomSheet>
//   // open:  ref.current?.present()
//   // close: ref.current?.dismiss()
//
// The handle indicator + sheet background + backdrop scrim are theme tokens
// (resolved via useThemeColors, applied through `style` — never a dynamic
// className).
//
// ⚠️ A <BottomSheetModalProvider> (from @gorhom/bottom-sheet) MUST wrap the app
// for the modal variant to work.
// ---------------------------------------------------------------------------

/**
 * Imperative handle for the sheet — `present()` / `dismiss()` / `snapToIndex()`
 * etc. (the methods exposed by the underlying BottomSheetModal). Use this as
 * the type for your `useRef`.
 */
type BottomSheetRef = BottomSheetModalMethods;

interface BottomSheetProps extends BottomSheetModalProps {
  /** Show a dimmed, tap-to-dismiss backdrop. Default: true. */
  withBackdrop?: boolean;
}

/**
 * Themed BottomSheetModal. Callers drive it imperatively via the forwarded ref
 * (`present()` / `dismiss()`). All BottomSheetModal props pass through, so
 * `snapPoints`, `onDismiss`, `enablePanDownToClose`, etc. work as usual; the
 * background/handle/backdrop styling is overridable by the caller.
 */
const BottomSheet = forwardRef<BottomSheetRef, BottomSheetProps>(function BottomSheet(
  {
    withBackdrop = true,
    backgroundStyle,
    handleIndicatorStyle,
    backdropComponent,
    children,
    ...rest
  },
  ref,
) {
  const colors = useThemeColors();

  const renderBackdrop = useCallback(
    (props: BottomSheetBackdropProps) => (
      <BottomSheetBackdrop
        {...props}
        appearsOnIndex={0}
        disappearsOnIndex={-1}
        opacity={0.5}
        pressBehavior="close"
      />
    ),
    [],
  );

  return (
    <BottomSheetModal
      // The component is generic (<T = never>) while our public ref alias uses
      // the concrete methods interface; bridge the two with a cast here.
      ref={ref as Ref<BottomSheetModalMethods<never>>}
      enablePanDownToClose
      backgroundStyle={[
        { backgroundColor: colors["background-neutral-00"] },
        backgroundStyle,
      ]}
      handleIndicatorStyle={[
        { backgroundColor: colors["border-03"] },
        handleIndicatorStyle,
      ]}
      backdropComponent={
        backdropComponent ?? (withBackdrop ? renderBackdrop : undefined)
      }
      {...rest}
    >
      {children}
    </BottomSheetModal>
  );
});

export { BottomSheet, type BottomSheetProps, type BottomSheetRef };
