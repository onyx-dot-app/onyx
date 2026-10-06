import { useState } from "react";

interface StableRowKeys {
  /** One React key per row, in row order. */
  keys: number[];
  /** Drops the key of the row at `index`. Call it with the row's removal. */
  removeKey: (index: number) => void;
}

/**
 * Stable per-row keys for a Formik array, so removing a middle row doesn't
 * shift native input state (focus, autofill) onto the row that takes its
 * index. Index keys would; content-derived keys would remount the row on
 * every keystroke. Rows added elsewhere get new keys on the next render.
 */
export function useStableRowKeys(rowCount: number): StableRowKeys {
  const [state, setState] = useState<{ keys: number[]; nextKey: number }>({
    keys: Array.from({ length: rowCount }, (_, index) => index),
    nextKey: rowCount,
  });

  if (state.keys.length < rowCount) {
    const keysToAdd = rowCount - state.keys.length;
    setState({
      keys: [
        ...state.keys,
        ...Array.from(
          { length: keysToAdd },
          (_, index) => state.nextKey + index
        ),
      ],
      nextKey: state.nextKey + keysToAdd,
    });
  } else if (state.keys.length > rowCount) {
    setState({ keys: state.keys.slice(0, rowCount), nextKey: state.nextKey });
  }

  function removeKey(index: number) {
    setState((prev) => ({
      keys: prev.keys.filter((_, i) => i !== index),
      nextKey: prev.nextKey,
    }));
  }

  return { keys: state.keys, removeKey };
}
