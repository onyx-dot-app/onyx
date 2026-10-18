import { useEffect } from "react";
import { useFormikContext } from "formik";

export default function MCPFormDirtyObserver({
  onDirtyChange,
}: {
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { dirty } = useFormikContext<unknown>();
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);
  return null;
}
