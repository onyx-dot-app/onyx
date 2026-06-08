import { forwardRef, useCallback, type Ref } from "react";
import {
  BottomSheetModal,
  BottomSheetBackdrop,
  type BottomSheetModalProps,
  type BottomSheetBackdropProps,
} from "@gorhom/bottom-sheet";
import type { BottomSheetModalMethods } from "@gorhom/bottom-sheet/lib/typescript/types";

import { useThemeColors } from "@/theme/ThemeProvider";

// Requires a <BottomSheetModalProvider> (from @gorhom/bottom-sheet) wrapping the app.

type BottomSheetRef = BottomSheetModalMethods;

interface BottomSheetProps extends BottomSheetModalProps {
  withBackdrop?: boolean;
}

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
      // Component is generic (<T = never>); our ref alias is the concrete methods interface — bridge with a cast.
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
