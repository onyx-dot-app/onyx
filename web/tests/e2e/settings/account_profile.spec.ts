import { expect, test } from "@playwright/test";
import { CHECKERED_PNG } from "@tests/e2e/fixtures/images";
import { AppSidebarPage } from "@tests/e2e/pages/AppSidebarPage";
import { SettingsAccountPage } from "@tests/e2e/pages/SettingsAccountPage";
import { loginAsRandomUser } from "@tests/e2e/utils/auth";

const PHOTO = { name: "me.png", mimeType: "image/png", buffer: CHECKERED_PNG };

test.describe("Account settings profile", () => {
  test("saves the photo, preferred name and work role", async ({ page }) => {
    await page.context().clearCookies();
    await loginAsRandomUser(page);
    const account = new SettingsAccountPage(page);
    const sidebar = new AppSidebarPage(page);
    await account.load();

    await account.uploadPhoto(PHOTO);
    // The account menu shows the new photo without a page load.
    await expect(sidebar.accountAvatarPhoto).toBeVisible();

    await account.setPreferredName("Sam");
    await account.setOtherWorkRole("Field research");

    await account.reloadBeforeProfileLoads();
    await expect(account.preferredNameInput).toHaveValue("Sam");
    // A stored role outside the list shows as "Other" with its text.
    await expect(account.workRoleSelect).toHaveValue("Other");
    await expect(account.otherWorkRoleInput).toHaveValue("Field research");
    await expect(sidebar.accountAvatarPhoto).toBeVisible();
    await account.expectOrganizationRole("Basic User");
  });

  test("crops, replaces and removes the photo", async ({ page }) => {
    await page.context().clearCookies();
    await loginAsRandomUser(page);
    const account = new SettingsAccountPage(page);
    await account.load();
    const uploads = account.recordPhotoUploads();

    // Without a photo the avatar shows the initials; focus shows the pencil.
    await account.focusPhotoButtonWithKeyboard();
    await expect(account.uploadPhotoButton).toBeFocused();

    await account.choosePhoto(PHOTO);
    await account.cancelCrop();
    expect(uploads).toHaveLength(0);
    await expect(account.uploadPhotoButton).toBeVisible();
    await expect(account.uploadPhotoButtonImage).toHaveCount(0);

    await account.choosePhoto(PHOTO);
    await account.saveCrop();
    await expect(account.avatarPhoto).toBeVisible();

    await account.replacePhoto(PHOTO);
    await account.cancelCrop();
    await expect(account.avatarPhoto).toBeVisible();

    await account.removePhoto();
    // The avatar button keeps focus while its photo changes.
    await expect(account.uploadPhotoButton).toBeFocused();
    await expect(account.uploadPhotoButtonImage).toHaveCount(0);
    expect(uploads).toHaveLength(1);
  });
});
