"use client";

import {
  createContext,
  useContext,
  type FunctionComponent,
  type ReactNode,
} from "react";

/**
 * Stands for "no provider above this consumer".
 *
 * A symbol rather than `undefined` or `null`, so a hook is free to return
 * either as a real value without tripping the check.
 */
const NO_PROVIDER = Symbol("createSharedHook.noProvider");

/**
 * Shares one instance of a hook across a subtree.
 *
 * Every component calling a hook gets its own state. Wrapping the hook here
 * gives the subtree a single instance instead — what a component needs when its
 * children read and write the same state, and threading a prop would mean
 * passing it through components that never look at it.
 *
 *     // module scope, never inside a component
 *     const [ThemeProvider, useSharedTheme] = createSharedHook(useTheme, "Theme");
 *
 *     <ThemeProvider>...</ThemeProvider>   // one instance for everything inside
 *     const theme = useSharedTheme();      // reads it, anywhere below
 *
 * Call this at module scope. `createContext` returns a new object each call, so
 * calling it while rendering builds a new provider type on every pass, which
 * remounts the subtree and discards the state it was holding.
 *
 * The provider is the unit of sharing, so two of them hold two independent
 * instances — what you want when one tree must not disturb another, such as a
 * modal over the page that opened it. The hook stays callable on its own, so
 * anything wanting its own state simply skips the provider.
 *
 * Reading with no provider above throws rather than returning a default: the
 * alternative is a component quietly operating on state nobody else can see.
 *
 * Consumers re-render whenever the shared value changes identity, so `useValue`
 * should return a memoized object. This cannot be done here — `T` is opaque, so
 * there is nothing correct to key a `useMemo` on.
 *
 * @param useValue the hook to share. Runs once per provider, on every render of
 *   that provider. Anything it needs at runtime arrives through provider props,
 *   which is why its own props cannot declare `children` — the provider owns
 *   that one. A hook that declares it is rejected here, at the call, rather
 *   than at every `<Provider>` that then could not accept a subtree.
 * @param name names the provider in React DevTools and in the error thrown when
 *   a consumer has no provider above it
 */
export default function createSharedHook<
  T,
  P extends object & { children?: never } = object,
>(
  useValue: (props: P) => T,
  name: string
): readonly [FunctionComponent<P & { children: ReactNode }>, () => T] {
  const SharedHookContext = createContext<T | typeof NO_PROVIDER>(NO_PROVIDER);

  // Props go to `useValue` whole rather than with `children` split off first:
  // `P & { children }` already satisfies `P`, while the rest of a destructure
  // does not narrow back to an unresolved `P` without an assertion. The hook
  // reads the arguments it declares and ignores the extra key.
  function SharedHookProvider(props: P & { children: ReactNode }) {
    return (
      <SharedHookContext.Provider value={useValue(props)}>
        {props.children}
      </SharedHookContext.Provider>
    );
  }
  SharedHookProvider.displayName = `${name}Provider`;

  function useSharedHook(): T {
    const value = useContext(SharedHookContext);
    if (value === NO_PROVIDER) {
      throw new Error(`use${name} must be used within ${name}Provider`);
    }
    return value;
  }

  return [SharedHookProvider, useSharedHook] as const;
}
