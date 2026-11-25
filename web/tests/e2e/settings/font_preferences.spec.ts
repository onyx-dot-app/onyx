import { expect, test } from "@playwright/test";
import { loginAsRandomUser } from "@tests/e2e/utils/auth";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import { mockLlmNonce } from "@tests/e2e/utils/mockLlm";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { SettingsAppearancePage } from "@tests/e2e/pages/SettingsAppearancePage";

// next/font registers each family under a name derived from its loader.
const OPENDYSLEXIC_FAMILY = /openDyslexic/i;
const HANKEN_GROTESK_FAMILY = /Hanken.Grotesk/i;
const DM_MONO_FAMILY = /DM.Mono/i;
// Computed letter-spacing of 14px preset text: the default font keeps the
// preset's spacing, OpenDyslexic tightens it by 0.06em.
const DEFAULT_LETTER_SPACING = "normal";
const OPENDYSLEXIC_LETTER_SPACING = "-0.84px";
// OpenDyslexic glyphs are wider than the default font's; the size and spacing
// adjustments keep the same text within this width ratio.
const MAX_OPENDYSLEXIC_WIDTH_RATIO = 1.25;

// Each test uses a fresh random user: the fonts apply to every page the user
// opens, so changing them on a shared user would leak into concurrent specs.
test("interface font applies at once and renders from the server after a reload", async ({
  page,
}) => {
  await loginAsRandomUser(page);

  const settingsPage = new SettingsAppearancePage(page);
  await settingsPage.goto();
  await settingsPage.expectInterfaceLetterSpacing(DEFAULT_LETTER_SPACING);
  const defaultWidth = await settingsPage.interfaceFontTitleWidth();
  const defaultMonospace = await settingsPage.monospaceSpacing();
  for (const { fontFamily } of defaultMonospace) {
    expect(fontFamily).toMatch(DM_MONO_FAMILY);
  }

  await settingsPage.chooseAppearanceOption(
    settingsPage.interfaceFontSelect,
    "OpenDyslexic"
  );
  await settingsPage.expectInterfaceFont("opendyslexic", OPENDYSLEXIC_FAMILY);
  await settingsPage.expectInterfaceLetterSpacing(OPENDYSLEXIC_LETTER_SPACING);
  const widthRatio =
    (await settingsPage.interfaceFontTitleWidth()) / defaultWidth;
  expect(widthRatio).toBeGreaterThan(1);
  expect(widthRatio).toBeLessThan(MAX_OPENDYSLEXIC_WIDTH_RATIO);
  // Monospace text keeps its spacing, so code stays aligned.
  expect(await settingsPage.monospaceSpacing()).toEqual(defaultMonospace);

  // The save refreshed the appearance cookie, so the server layout renders
  // the font on first paint.
  await settingsPage.expectServerRenderedAppearance(
    "data-interface-font",
    "opendyslexic"
  );
  await settingsPage.reload();
  await settingsPage.expectInterfaceFont("opendyslexic", OPENDYSLEXIC_FAMILY);
});

test("the response font applies to answers in a chat", async ({ page }) => {
  await loginAsRandomUser(page);

  const settingsPage = new SettingsAppearancePage(page);
  await settingsPage.goto();
  await settingsPage.chooseAppearanceOption(
    settingsPage.interfaceFontSelect,
    "OpenDyslexic"
  );
  await settingsPage.chooseAppearanceOption(
    settingsPage.responseFontSelect,
    "Default"
  );

  const chatPage = new ChatPage(page);
  await chatPage.goto();
  await sendMessage(page, `Answer in the response font. ${mockLlmNonce()}`);

  // The interface keeps the chosen font; only the answer uses the default.
  await settingsPage.expectInterfaceFont("opendyslexic", OPENDYSLEXIC_FAMILY);
  await chatPage.expectAnswerFont(HANKEN_GROTESK_FAMILY);
  await chatPage.expectAnswerLetterSpacing(DEFAULT_LETTER_SPACING);
});
