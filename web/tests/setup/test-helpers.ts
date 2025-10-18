/**
 * Reusable Test Helper Utilities
 *
 * This file provides helper functions for common test operations.
 * Import these utilities to make your tests more readable and maintainable.
 */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/**
 * Fill out a form with multiple fields
 *
 * @example
 * ```typescript
 * await fillForm(user, {
 *   "Email": "test@example.com",
 *   "Password": "password123",
 * });
 * ```
 */
export async function fillForm(
  user: ReturnType<typeof userEvent.setup>,
  fields: Record<string, string>
): Promise<void> {
  for (const [label, value] of Object.entries(fields)) {
    const input = screen.getByLabelText(new RegExp(label, "i"));
    await user.type(input, value);
  }
}

/**
 * Fill out a form by placeholder text
 *
 * @example
 * ```typescript
 * await fillFormByPlaceholder(user, {
 *   "Enter email": "test@example.com",
 *   "Enter password": "password123",
 * });
 * ```
 */
export async function fillFormByPlaceholder(
  user: ReturnType<typeof userEvent.setup>,
  fields: Record<string, string>
): Promise<void> {
  for (const [placeholder, value] of Object.entries(fields)) {
    const input = screen.getByPlaceholderText(new RegExp(placeholder, "i"));
    await user.type(input, value);
  }
}

/**
 * Click a button by its accessible name
 *
 * @example
 * ```typescript
 * await clickButton(user, "Submit");
 * await clickButton(user, /log in/i);
 * ```
 */
export async function clickButton(
  user: ReturnType<typeof userEvent.setup>,
  name: string | RegExp
): Promise<void> {
  const button = screen.getByRole("button", {
    name: typeof name === "string" ? new RegExp(name, "i") : name,
  });
  await user.click(button);
}

/**
 * Wait for an element to appear and assert it's visible
 *
 * @example
 * ```typescript
 * await waitForText("Welcome");
 * await waitForText(/success/i);
 * ```
 */
export async function waitForText(
  text: string | RegExp,
  options?: { timeout?: number }
): Promise<void> {
  await waitFor(
    () => {
      expect(screen.getByText(text)).toBeInTheDocument();
    },
    { timeout: options?.timeout }
  );
}

/**
 * Wait for an element to disappear
 *
 * @example
 * ```typescript
 * await waitForTextToDisappear("Loading...");
 * ```
 */
export async function waitForTextToDisappear(
  text: string | RegExp,
  options?: { timeout?: number }
): Promise<void> {
  await waitFor(
    () => {
      expect(screen.queryByText(text)).not.toBeInTheDocument();
    },
    { timeout: options?.timeout }
  );
}

/**
 * Wait for loading state to complete
 *
 * @example
 * ```typescript
 * await waitForLoadingToComplete();
 * ```
 */
export async function waitForLoadingToComplete(
  loadingText: string | RegExp = /loading/i,
  options?: { timeout?: number }
): Promise<void> {
  await waitForTextToDisappear(loadingText, options);
}

/**
 * Check if an element exists without throwing
 *
 * @example
 * ```typescript
 * expect(elementExists("Submit")).toBe(true);
 * ```
 */
export function elementExists(text: string | RegExp, role?: string): boolean {
  if (role) {
    return screen.queryByRole(role, { name: text }) !== null;
  }
  return screen.queryByText(text) !== null;
}

/**
 * Find element within a container
 *
 * @example
 * ```typescript
 * const card = screen.getByText("Item 1").closest("div");
 * const button = findWithin(card, "button", /edit/i);
 * ```
 */
export function findWithin(
  container: HTMLElement | null,
  role: string,
  name: string | RegExp
) {
  if (!container) {
    throw new Error("Container element not found");
  }
  return within(container).getByRole(role, { name });
}

/**
 * Submit a form (find submit button and click it)
 *
 * @example
 * ```typescript
 * await submitForm(user);
 * await submitForm(user, "Create Account");
 * ```
 */
export async function submitForm(
  user: ReturnType<typeof userEvent.setup>,
  buttonText: string | RegExp = /submit/i
): Promise<void> {
  await clickButton(user, buttonText);
}

/**
 * Clear and type into an input field
 *
 * @example
 * ```typescript
 * await clearAndType(user, screen.getByLabelText(/email/i), "new@example.com");
 * ```
 */
export async function clearAndType(
  user: ReturnType<typeof userEvent.setup>,
  element: HTMLElement,
  text: string
): Promise<void> {
  await user.clear(element);
  await user.type(element, text);
}

/**
 * Wait for element to have focus
 *
 * @example
 * ```typescript
 * await waitForFocus(screen.getByLabelText(/email/i));
 * ```
 */
export async function waitForFocus(
  element: HTMLElement,
  options?: { timeout?: number }
): Promise<void> {
  await waitFor(
    () => {
      expect(element).toHaveFocus();
    },
    { timeout: options?.timeout }
  );
}

/**
 * Wait for button to be enabled/disabled
 *
 * @example
 * ```typescript
 * await waitForButtonState("Submit", "enabled");
 * await waitForButtonState("Submit", "disabled");
 * ```
 */
export async function waitForButtonState(
  buttonName: string | RegExp,
  state: "enabled" | "disabled",
  options?: { timeout?: number }
): Promise<void> {
  await waitFor(
    () => {
      const button = screen.getByRole("button", { name: buttonName });
      if (state === "enabled") {
        expect(button).not.toBeDisabled();
      } else {
        expect(button).toBeDisabled();
      }
    },
    { timeout: options?.timeout }
  );
}

/**
 * Get all items in a list
 *
 * @example
 * ```typescript
 * const items = getAllListItems();
 * expect(items).toHaveLength(3);
 * ```
 */
export function getAllListItems(): HTMLElement[] {
  return screen.queryAllByRole("listitem");
}

/**
 * Navigate through form with Tab key
 *
 * @example
 * ```typescript
 * await tabThroughForm(user, [
 *   { label: /email/i, value: "test@example.com" },
 *   { label: /password/i, value: "password123" },
 * ]);
 * ```
 */
export async function tabThroughForm(
  user: ReturnType<typeof userEvent.setup>,
  fields: Array<{ label: string | RegExp; value: string }>
): Promise<void> {
  for (const field of fields) {
    await user.tab();
    const input = screen.getByLabelText(field.label);
    expect(input).toHaveFocus();
    await user.keyboard(field.value);
  }
}

/**
 * Check if error message is displayed
 *
 * @example
 * ```typescript
 * expect(hasErrorMessage("Invalid email")).toBe(true);
 * ```
 */
export function hasErrorMessage(message: string | RegExp): boolean {
  return elementExists(message);
}

/**
 * Wait for success message
 *
 * @example
 * ```typescript
 * await waitForSuccessMessage("Account created");
 * ```
 */
export async function waitForSuccessMessage(
  message: string | RegExp,
  options?: { timeout?: number }
): Promise<void> {
  await waitForText(message, options);
}

/**
 * Wait for error message
 *
 * @example
 * ```typescript
 * await waitForErrorMessage("Invalid credentials");
 * ```
 */
export async function waitForErrorMessage(
  message: string | RegExp,
  options?: { timeout?: number }
): Promise<void> {
  await waitForText(message, options);
}

/**
 * Select option from dropdown
 *
 * @example
 * ```typescript
 * await selectDropdownOption(user, "Country", "United States");
 * ```
 */
export async function selectDropdownOption(
  user: ReturnType<typeof userEvent.setup>,
  dropdownLabel: string | RegExp,
  optionText: string | RegExp
): Promise<void> {
  const dropdown = screen.getByLabelText(dropdownLabel);
  await user.click(dropdown);
  const option = screen.getByRole("option", { name: optionText });
  await user.click(option);
}

/**
 * Upload file to input
 *
 * @example
 * ```typescript
 * const file = createTestFile("test.pdf", "application/pdf");
 * await uploadFile(user, "Upload document", file);
 * ```
 */
export async function uploadFile(
  user: ReturnType<typeof userEvent.setup>,
  inputLabel: string | RegExp,
  file: File
): Promise<void> {
  const input = screen.getByLabelText(inputLabel);
  await user.upload(input, file);
}

/**
 * Create a test file for upload tests
 *
 * @example
 * ```typescript
 * const file = createTestFile("document.pdf", "application/pdf", "PDF content");
 * ```
 */
export function createTestFile(
  name: string,
  type: string,
  content: string = "test content"
): File {
  return new File([content], name, { type });
}

/**
 * Debug helper: Print current screen content
 *
 * @example
 * ```typescript
 * debugScreen(); // Prints entire DOM
 * debugScreen(container); // Prints specific element
 * ```
 */
export function debugScreen(element?: HTMLElement): void {
  if (element) {
    screen.debug(element);
  } else {
    screen.debug();
  }
}

/**
 * Get query parameter from URL
 *
 * @example
 * ```typescript
 * const searchQuery = getQueryParam("/api/search?q=test", "q");
 * expect(searchQuery).toBe("test");
 * ```
 */
export function getQueryParam(url: string, param: string): string | null {
  const urlObj = new URL(url, "http://localhost");
  return urlObj.searchParams.get(param);
}

/**
 * Assert form field has specific value
 *
 * @example
 * ```typescript
 * expectFieldValue(/email/i, "test@example.com");
 * ```
 */
export function expectFieldValue(label: string | RegExp, value: string): void {
  const input = screen.getByLabelText(label) as HTMLInputElement;
  expect(input.value).toBe(value);
}

/**
 * Assert form field is empty
 *
 * @example
 * ```typescript
 * expectFieldEmpty(/email/i);
 * ```
 */
export function expectFieldEmpty(label: string | RegExp): void {
  const input = screen.getByLabelText(label) as HTMLInputElement;
  expect(input.value).toBe("");
}

/**
 * Simulate keyboard shortcut
 *
 * @example
 * ```typescript
 * await pressKeyboardShortcut(user, "{Control>}s{/Control}"); // Ctrl+S
 * await pressKeyboardShortcut(user, "{Escape}");
 * ```
 */
export async function pressKeyboardShortcut(
  user: ReturnType<typeof userEvent.setup>,
  shortcut: string
): Promise<void> {
  await user.keyboard(shortcut);
}

/**
 * Wait for modal/dialog to appear
 *
 * @example
 * ```typescript
 * await waitForModal("Confirm Delete");
 * ```
 */
export async function waitForModal(
  title: string | RegExp,
  options?: { timeout?: number }
): Promise<void> {
  await waitFor(
    () => {
      const dialog = screen.getByRole("dialog");
      expect(dialog).toBeInTheDocument();
      expect(within(dialog).getByText(title)).toBeInTheDocument();
    },
    { timeout: options?.timeout }
  );
}

/**
 * Close modal by clicking outside or pressing Escape
 *
 * @example
 * ```typescript
 * await closeModal(user);
 * ```
 */
export async function closeModal(
  user: ReturnType<typeof userEvent.setup>,
  method: "escape" | "button" = "escape"
): Promise<void> {
  if (method === "escape") {
    await user.keyboard("{Escape}");
  } else {
    const closeButton = screen.getByRole("button", { name: /close/i });
    await user.click(closeButton);
  }
}
