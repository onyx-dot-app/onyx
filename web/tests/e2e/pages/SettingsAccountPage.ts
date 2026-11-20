/**
 * Page Object Model for the Account settings tab (/app/settings/account).
 *
 * Covers the profile photo with its crop dialog and menu, the preferred name,
 * the work role select with its "Other" text field, and the Organization role.
 * Loads the tab, also from an old settings path that redirects here.
 */

import { type Page, type Locator, expect } from "@playwright/test";

const ACCOUNT_PATH = "/app/settings/account";
const PROFILE_API = "/api/user/personalization";
const PROFILE_IMAGE_API = "/api/user/profile-image";
// The crop dialog saves a square of this size; test photos are smaller.
const CROPPED_PHOTO_SIZE_PX = 512;

export interface PhotoFile {
  name: string;
  mimeType: string;
  buffer: Buffer;
}

export class SettingsAccountPage {
  readonly page: Page;
  readonly photoInput: Locator;
  /** The avatar button while there is no photo: a click picks one. */
  readonly uploadPhotoButton: Locator;
  /** The avatar button while there is a photo: a click opens the menu. */
  readonly editPhotoButton: Locator;
  readonly photoMenu: Locator;
  readonly cropDialog: Locator;
  readonly fullNameInput: Locator;
  readonly preferredNameInput: Locator;
  readonly workRoleSelect: Locator;
  readonly otherWorkRoleInput: Locator;

  constructor(page: Page) {
    this.page = page;
    // The photo control is the only file input on the tab.
    this.photoInput = page.locator('input[type="file"]');
    this.uploadPhotoButton = page.getByRole("button", {
      name: "Upload a profile photo",
    });
    this.editPhotoButton = page.getByRole("button", {
      name: "Change profile photo",
    });
    this.photoMenu = page.getByRole("menu", { name: "Profile photo options" });
    this.cropDialog = page.getByRole("dialog", { name: "Crop photo" });
    // The row's label also holds its description.
    this.fullNameInput = page.getByRole("textbox", { name: /^Full Name/ });
    this.preferredNameInput = page.getByLabel(/call you\?/i);
    this.workRoleSelect = page.getByRole("combobox", {
      name: "What Best Describes Your Work?",
    });
    this.otherWorkRoleInput = page.getByRole("textbox", {
      name: "Your Work",
      exact: true,
    });
  }

  /**
   * Load `path` with a page load and wait until it shows this tab. Pass an
   * old settings path to follow its redirect.
   */
  async load(path: string = ACCOUNT_PATH): Promise<void> {
    await this.page.goto(path);
    await expect(this.page).toHaveURL(new RegExp(`${ACCOUNT_PATH}$`));
    await expect(this.fullNameInput).toBeVisible();
  }

  /**
   * Reload the tab, holding the user's profile until the tab has rendered,
   * so the tab must show the saved values once they arrive.
   */
  async reloadBeforeProfileLoads(): Promise<void> {
    let releaseProfile = () => {};
    const profileHeld = new Promise<void>((resolve) => {
      releaseProfile = resolve;
    });
    await this.page.route("**/api/me", async (route) => {
      await profileHeld;
      await route.continue();
    });
    await this.page.reload();
    await expect(this.workRoleSelect).toBeVisible();
    // Later requests pass through the route at once.
    releaseProfile();
  }

  /** Any image in the upload button. It has none: it shows the initials. */
  get uploadPhotoButtonImage(): Locator {
    return this.uploadPhotoButton.locator("img");
  }

  /** The photo the avatar shows, once there is one. */
  get avatarPhoto(): Locator {
    return this.editPhotoButton.locator("img[src*='/profile-image']");
  }

  /** Pick a file; the crop dialog opens for it. */
  async choosePhoto(file: PhotoFile): Promise<void> {
    await this.photoInput.setInputFiles(file);
    await expect(this.cropDialog).toBeVisible();
  }

  /**
   * Save the crop and wait for the upload to succeed. The stored photo is the
   * square crop at its output size, not the chosen file.
   */
  async saveCrop(): Promise<void> {
    const uploaded = this.page.waitForResponse(
      (response) =>
        response.url().includes(PROFILE_IMAGE_API) &&
        response.request().method() === "POST"
    );
    await this.cropDialog.getByRole("button", { name: "Save" }).click();
    const response = await uploaded;
    expect(response.ok()).toBe(true);
    await expect(this.cropDialog).toBeHidden();

    const me = await this.page.request.get("/api/me");
    const { id } = (await me.json()) as { id: string };
    const size = await this.page.evaluate(async (userId) => {
      const photo = await fetch(`/api/user/${userId}/profile-image`);
      const bitmap = await createImageBitmap(await photo.blob());
      return { width: bitmap.width, height: bitmap.height };
    }, id);
    expect(size).toEqual({
      width: CROPPED_PHOTO_SIZE_PX,
      height: CROPPED_PHOTO_SIZE_PX,
    });
  }

  async cancelCrop(): Promise<void> {
    await this.cropDialog.getByRole("button", { name: "Cancel" }).click();
    await expect(this.cropDialog).toBeHidden();
  }

  async uploadPhoto(file: PhotoFile): Promise<void> {
    await this.choosePhoto(file);
    await this.saveCrop();
  }

  /** Collects every photo upload request the page sends from now on. */
  recordPhotoUploads(): string[] {
    const uploads: string[] = [];
    this.page.on("request", (request) => {
      if (
        request.url().includes(PROFILE_IMAGE_API) &&
        request.method() === "POST"
      ) {
        uploads.push(request.url());
      }
    });
    return uploads;
  }

  /** The pencil overlay of the avatar button that is on show. */
  get photoEditOverlay(): Locator {
    return this.page
      .getByRole("button", { name: /profile photo/ })
      .locator(".opal-avatar-button-overlay");
  }

  /**
   * Hover the avatar: the pencil overlay, hidden before, shows. Then open the
   * photo menu.
   */
  async openPhotoMenu(): Promise<void> {
    await this.page.mouse.move(0, 0);
    await expect(this.photoEditOverlay).toHaveCSS("opacity", "0");
    await this.editPhotoButton.hover();
    await expect(this.photoEditOverlay).toHaveCSS("opacity", "1");
    await this.editPhotoButton.click();
    await expect(this.photoMenu).toBeVisible();
  }

  /** Choose "Replace photo" and pick `file`; the crop dialog opens for it. */
  async replacePhoto(file: PhotoFile): Promise<void> {
    await this.openPhotoMenu();
    const chooser = this.page.waitForEvent("filechooser");
    await this.photoMenu
      .getByRole("menuitem", { name: "Replace photo" })
      .click();
    await (await chooser).setFiles(file);
    await expect(this.cropDialog).toBeVisible();
  }

  /**
   * Tab back from the full name field to the avatar button: the pencil
   * overlay, hidden before, shows.
   */
  async focusPhotoButtonWithKeyboard(): Promise<void> {
    await this.page.mouse.move(0, 0);
    await this.fullNameInput.focus();
    await expect(this.photoEditOverlay).toHaveCSS("opacity", "0");
    await this.page.keyboard.press("Shift+Tab");
    await expect(this.photoEditOverlay).toHaveCSS("opacity", "1");
  }

  /** Remove the photo from the menu, opened with the keyboard. */
  async removePhoto(): Promise<void> {
    await this.focusPhotoButtonWithKeyboard();
    await expect(this.editPhotoButton).toBeFocused();
    await this.page.keyboard.press("Enter");
    await expect(this.photoMenu).toBeVisible();
    const removed = this.page.waitForResponse(
      (response) =>
        response.url().includes(PROFILE_IMAGE_API) &&
        response.request().method() === "DELETE"
    );
    await this.photoMenu.getByRole("menuitem", { name: "Remove" }).click();
    expect((await removed).ok()).toBe(true);
  }

  async setPreferredName(name: string): Promise<void> {
    const saved = this.page.waitForResponse((response) =>
      response.url().includes(PROFILE_API)
    );
    await this.preferredNameInput.fill(name);
    await this.preferredNameInput.press("Enter");
    expect((await saved).ok()).toBe(true);
  }

  /** Choose "Other" and save `text` as the work role. */
  async setOtherWorkRole(text: string): Promise<void> {
    await this.workRoleSelect.click();
    await this.page.getByRole("option", { name: "Other", exact: true }).click();
    const saved = this.page.waitForResponse((response) =>
      response.url().includes(PROFILE_API)
    );
    await this.otherWorkRoleInput.fill(text);
    await this.otherWorkRoleInput.press("Enter");
    expect((await saved).ok()).toBe(true);
  }

  async expectOrganizationRole(label: string): Promise<void> {
    await expect(this.page.getByText(label, { exact: true })).toBeVisible();
  }
}
