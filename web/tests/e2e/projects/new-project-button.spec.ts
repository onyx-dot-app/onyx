import { test, expect } from "@chromatic-com/playwright";
import { loginAsRandomUser } from "../utils/auth";

test.describe("New Project Button in WelcomeMessage", () => {
  test("should display New Project button in welcome message", async ({
    page,
  }) => {
    // Clear cookies and login as a random user
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    // Navigate to the chat page (should show WelcomeMessage with no project selected)
    await page.goto("http://localhost:3000/chat");
    await page.waitForLoadState("networkidle");

    // Verify WelcomeMessage is visible
    const welcomeMessage = page.getByTestId("chat-intro");
    await expect(welcomeMessage).toBeVisible();

    // Verify the Onyx logo is displayed (default agent)
    const onyxLogo = page.getByTestId("onyx-logo");
    await expect(onyxLogo).toBeVisible();

    // Verify the New Project button exists and is visible
    const newProjectButton = page.getByTestId("new-project-button");
    await expect(newProjectButton).toBeVisible();

    // Verify button has correct text
    await expect(newProjectButton).toContainText("New Project");
  });

  test("should open CreateProjectModal when New Project button is clicked", async ({
    page,
  }) => {
    // Clear cookies and login
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    // Navigate to chat page
    await page.goto("http://localhost:3000/chat");
    await page.waitForLoadState("networkidle");

    // Click the New Project button
    const newProjectButton = page.getByTestId("new-project-button");
    await newProjectButton.click();

    // Wait for modal to appear
    await page.waitForTimeout(500);

    // Verify CreateProjectModal is visible
    // The modal should have a title "Create New Project"
    const modalTitle = page.getByText("Create New Project");
    await expect(modalTitle).toBeVisible();

    // Verify the input field for project name is visible
    const projectNameInput = page.getByPlaceholder("What are you working on?");
    await expect(projectNameInput).toBeVisible();
  });

  test("should create a new project from welcome screen", async ({ page }) => {
    // Clear cookies and login
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    // Navigate to chat page
    await page.goto("http://localhost:3000/chat");
    await page.waitForLoadState("networkidle");

    // Click the New Project button
    const newProjectButton = page.getByTestId("new-project-button");
    await newProjectButton.click();

    // Wait for modal to appear
    await page.waitForTimeout(500);

    // Enter project name
    const projectName = `E2E Test Project ${Date.now()}`;
    const projectNameInput = page.getByPlaceholder("What are you working on?");
    await projectNameInput.fill(projectName);

    // Submit the form (press Enter or click submit button)
    await projectNameInput.press("Enter");

    // Wait for navigation to the new project
    await page.waitForTimeout(1000);

    // Verify URL contains projectid parameter
    expect(page.url()).toContain("projectid=");

    // Verify WelcomeMessage is no longer visible
    const welcomeMessage = page.getByTestId("chat-intro");
    await expect(welcomeMessage).not.toBeVisible();

    // Verify project name appears on the page (in the ProjectContextPanel)
    await expect(page.getByText(projectName)).toBeVisible();

    // Verify Files section is visible in ProjectContextPanel
    await expect(page.getByText("Files")).toBeVisible();
    await expect(
      page.getByText("Chats in this project can access these files.")
    ).toBeVisible();
  });

  test("should not show WelcomeMessage when project is selected", async ({
    page,
  }) => {
    // Clear cookies and login
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    // Navigate to chat page
    await page.goto("http://localhost:3000/chat");
    await page.waitForLoadState("networkidle");

    // Create a project using the sidebar button first
    const newProjectButton = page.getByTestId("new-project-button");
    await newProjectButton.click();
    await page.waitForTimeout(500);

    const projectName = `E2E Test Project ${Date.now()}`;
    const projectNameInput = page.getByPlaceholder("What are you working on?");
    await projectNameInput.fill(projectName);
    await projectNameInput.press("Enter");

    // Wait for project to be created
    await page.waitForTimeout(1000);

    // Verify WelcomeMessage is not visible (ProjectContextPanel should be shown instead)
    const welcomeMessage = page.getByTestId("chat-intro");
    await expect(welcomeMessage).not.toBeVisible();

    // Verify New Project button from welcome message is not visible
    const welcomeNewProjectButton = page.getByTestId("new-project-button");
    await expect(welcomeNewProjectButton).not.toBeVisible();
  });

  test("should show WelcomeMessage again when returning to chat without project", async ({
    page,
  }) => {
    // Clear cookies and login
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    // Create a project first
    await page.goto("http://localhost:3000/chat");
    await page.waitForLoadState("networkidle");

    const newProjectButton = page.getByTestId("new-project-button");
    await newProjectButton.click();
    await page.waitForTimeout(500);

    const projectName = `E2E Test Project ${Date.now()}`;
    const projectNameInput = page.getByPlaceholder("What are you working on?");
    await projectNameInput.fill(projectName);
    await projectNameInput.press("Enter");
    await page.waitForTimeout(1000);

    // Navigate back to chat page without project
    await page.goto("http://localhost:3000/chat");
    await page.waitForLoadState("networkidle");

    // Verify WelcomeMessage is visible again
    const welcomeMessage = page.getByTestId("chat-intro");
    await expect(welcomeMessage).toBeVisible();

    // Verify New Project button is visible
    const welcomeNewProjectButton = page.getByTestId("new-project-button");
    await expect(welcomeNewProjectButton).toBeVisible();
  });
});
