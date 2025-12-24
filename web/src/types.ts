/**
 * Utility type that removes style override properties from a component's props.
 *
 * This type omits `className` and `style` properties from type `T`, preventing
 * external style customization. Useful for enforcing consistent design system
 * styling and preventing arbitrary style overrides.
 *
 * @template T - The base type to remove style properties from
 *
 * @example
 * ```tsx
 * // Create a button that doesn't allow style overrides
 * interface ButtonProps extends WithoutStyles<React.ComponentProps<"button">> {
 *   variant: "primary" | "secondary";
 * }
 *
 * function Button({ variant, ...props }: ButtonProps) {
 *   // Users cannot pass className or style props
 *   return <button {...props} className={getVariantClass(variant)} />;
 * }
 *
 * // ✅ Valid
 * <Button variant="primary" onClick={handleClick} />
 *
 * // ❌ TypeScript error - className not allowed
 * <Button variant="primary" className="custom-class" />
 * ```
 */
export type WithoutStyles<T> = Omit<T, "className" | "style">;
