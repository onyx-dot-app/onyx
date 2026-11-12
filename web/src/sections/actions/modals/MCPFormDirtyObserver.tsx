import { useEffect } from "react";
import { useFormikContext } from "formik";

export default function MCPFormDirtyObserver({
  onDirtyChange,
  onValuesChange,
}: {
  onDirtyChange: (dirty: boolean) => void;
  onValuesChange?: () => void;
}) {
  const { dirty, values } = useFormikContext<unknown>();
  useEffect(() => onValuesChange?.(), [values, onValuesChange]);
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);
  return null;
}
