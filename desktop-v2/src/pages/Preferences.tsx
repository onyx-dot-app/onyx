import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button, Card, InputSwitch, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { mount } from "@/lib/mount";
import { IS_MAC } from "@/lib/platform";
import { ErrorText, Field, WindowFrame } from "@/lib/WindowFrame";
import {
  changeServer,
  errorMessage,
  getPrefs,
  setHotkey,
  setLaunchAtLogin,
  setNotifyAnswers,
  signOut,
  type Prefs,
} from "@/lib/ipc";

interface PrefSectionProps {
  title: string;
  children: ReactNode;
}

function PrefSection({ title, children }: PrefSectionProps) {
  return (
    <Card padding={4}>
      <Section gap={3} alignItems="stretch" height="fit">
        <Text font="main-ui-action" color="text-05">
          {title}
        </Text>
        {children}
      </Section>
    </Card>
  );
}

function ManagedNote() {
  return (
    <Text font="secondary-body" color="text-03">
      Managed by your organization
    </Text>
  );
}

// Keys the global shortcut can use, by KeyboardEvent.code. Letters, digits and
// F-keys are mapped by pattern below.
const NAMED_KEYS: Record<string, string> = {
  Space: "Space",
  ArrowUp: "Up",
  ArrowDown: "Down",
  ArrowLeft: "Left",
  ArrowRight: "Right",
  Minus: "Minus",
  Equal: "Equal",
  Comma: "Comma",
  Period: "Period",
  Slash: "Slash",
  Semicolon: "Semicolon",
  Quote: "Quote",
  BracketLeft: "BracketLeft",
  BracketRight: "BracketRight",
  Backslash: "Backslash",
  Backquote: "Backquote",
};

// The accelerator for a key press, or null for a press that cannot be a
// shortcut: only modifiers, or no Command, Control or Option.
interface KeyPress {
  code: string;
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
}

function acceleratorFor(event: KeyPress): string | null {
  const code = event.code;
  const key =
    NAMED_KEYS[code] ??
    (/^Key[A-Z]$/.test(code) ? code.slice(3) : null) ??
    (/^Digit[0-9]$/.test(code) ? code.slice(5) : null) ??
    (/^F([1-9]|1[0-9]|2[0-4])$/.test(code) ? code : null);
  if (!key || !(event.metaKey || event.ctrlKey || event.altKey)) return null;
  const parts: string[] = [];
  // CommandOrControl is Control on Windows and Linux; the Windows key is Super.
  if (event.metaKey) parts.push(IS_MAC ? "CommandOrControl" : "Super");
  if (event.ctrlKey) parts.push("Control");
  if (event.altKey) parts.push("Alt");
  if (event.shiftKey) parts.push("Shift");
  parts.push(key);
  return parts.join("+");
}

const SYMBOLS: Record<string, string> = {
  CommandOrControl: "⌘",
  CmdOrCtrl: "⌘",
  Command: "⌘",
  Cmd: "⌘",
  Super: "⌘",
  Control: "⌃",
  Ctrl: "⌃",
  Alt: "⌥",
  Option: "⌥",
  Shift: "⇧",
  Up: "↑",
  Down: "↓",
  Left: "←",
  Right: "→",
};

const OTHER_LABELS: Record<string, string> = {
  CommandOrControl: "Ctrl",
  CmdOrCtrl: "Ctrl",
  Control: "Ctrl",
};

// "CommandOrControl+Shift+Space" as macOS shows it: "⌘⇧Space". Windows and
// Linux show "Ctrl+Shift+Space".
function displayShortcut(accelerator: string): string {
  if (!IS_MAC) {
    return accelerator
      .split("+")
      .map((part) => OTHER_LABELS[part] ?? part)
      .join("+");
  }
  return accelerator
    .split("+")
    .map((part) => SYMBOLS[part] ?? part)
    .join("");
}

interface ShortcutRecorderProps {
  value: string | null;
  disabled: boolean;
  onRecord: (accelerator: string) => void;
}

// Click, then press the new keys.
function ShortcutRecorder({ value, disabled, onRecord }: ShortcutRecorderProps) {
  const [recording, setRecording] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // WebKit on macOS does not focus a button on click, so its own key handler
  // never runs: listen on the window while recording.
  useEffect(() => {
    if (!recording) return;
    function onKeyDown(event: globalThis.KeyboardEvent) {
      event.preventDefault();
      event.stopPropagation();
      if (event.key === "Escape") {
        setRecording(false);
        return;
      }
      const accelerator = acceleratorFor(event);
      if (accelerator) {
        setRecording(false);
        onRecord(accelerator);
      }
    }
    const cancel = () => setRecording(false);
    window.addEventListener("keydown", onKeyDown, true);
    window.addEventListener("blur", cancel);
    return () => {
      window.removeEventListener("keydown", onKeyDown, true);
      window.removeEventListener("blur", cancel);
    };
  }, [recording, onRecord]);

  return (
    <button
      ref={buttonRef}
      type="button"
      id="hotkey"
      aria-label="Launcher shortcut"
      disabled={disabled}
      className="h-9 rounded-08 border border-border-02 bg-background-neutral-00 px-3 text-start font-main-ui-body text-text-04 focus:border-border-05 focus:outline-none disabled:cursor-default disabled:text-text-03"
      onClick={() => {
        buttonRef.current?.focus();
        setRecording(true);
      }}
      // Focus moving to another control ends recording, so a later ⌘C is not taken.
      onBlur={() => setRecording(false)}
    >
      {recording ? "Press the new shortcut… (Esc cancels)" : value ? displayShortcut(value) : ""}
    </button>
  );
}

function Preferences() {
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Each open reads managed policy again.
  useEffect(() => {
    void getPrefs().then(setPrefs);
  }, []);

  async function run(action: () => Promise<void>) {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(errorMessage(e));
      // A failed action can still have changed something (a server change
      // signs out first), so show the app's real state again.
      void getPrefs().then(setPrefs);
    }
  }

  async function onRecordHotkey(accelerator: string) {
    setSaved(false);
    if (accelerator === prefs?.hotkey) return;
    await run(async () => {
      await setHotkey(accelerator);
      // Also refreshes the shortcut notice.
      setPrefs(await getPrefs());
      setSaved(true);
    });
  }

  async function onLaunchAtLogin(enabled: boolean) {
    await run(async () => {
      await setLaunchAtLogin(enabled);
      setPrefs((p) => (p ? { ...p, launchAtLogin: enabled } : p));
    });
  }

  async function onNotifyAnswers(enabled: boolean) {
    await run(async () => {
      await setNotifyAnswers(enabled);
      setPrefs((p) => (p ? { ...p, notifyAnswers: enabled } : p));
    });
  }

  return (
    <WindowFrame title="Preferences" subtitle="Settings for this device">
      <Section gap={4} alignItems="stretch" height="fit">
        {prefs?.policyInvalid ? (
          <ErrorText message="Your organization's Onyx policy is invalid. Some settings are locked. Contact your IT team." />
        ) : null}
        <PrefSection title="Server">
          <Text font="main-ui-body" color="text-04">
            {prefs?.serverUrl ?? "Not connected"}
          </Text>
          {prefs?.serverManaged ? <ManagedNote /> : null}
          {prefs?.serverLocked ? null : (
            <Section flexDirection="row" justifyContent="start" height="fit">
              <Button prominence="secondary" onClick={() => void run(changeServer)}>
                Change server
              </Button>
            </Section>
          )}
        </PrefSection>
        <PrefSection title="Launcher Shortcut">
          {prefs?.launcherDisabled ? (
            <Text font="main-ui-body" color="text-04">
              The launcher is turned off.
            </Text>
          ) : (
            <Field label="Shows the launcher from any app" inputId="hotkey">
              <ShortcutRecorder
                value={prefs?.hotkey ?? null}
                disabled={prefs?.hotkeyManaged ?? false}
                onRecord={(a) => void onRecordHotkey(a)}
              />
            </Field>
          )}
          {prefs?.hotkeyManaged ? <ManagedNote /> : null}
          {prefs?.shortcutNotice ? (
            <Text font="secondary-body" color="text-03">
              {prefs.shortcutNotice}
            </Text>
          ) : null}
          {saved ? (
            <Text font="secondary-body" color="text-03">
              Saved
            </Text>
          ) : null}
        </PrefSection>
        <PrefSection title="Startup">
          <Section
            flexDirection="row"
            justifyContent="between"
            alignItems="center"
            height="fit"
          >
            <label htmlFor="launch-at-login">
              <Text font="main-ui-body" color="text-04">
                Launch at login
              </Text>
            </label>
            <InputSwitch
              id="launch-at-login"
              checked={prefs?.launchAtLogin ?? false}
              disabled={!prefs || prefs.launchAtLoginManaged}
              onCheckedChange={(enabled) => void onLaunchAtLogin(enabled)}
            />
          </Section>
          {prefs?.launchAtLoginManaged ? <ManagedNote /> : null}
          {prefs?.autoUpdateDisabled ? (
            <Text font="secondary-body" color="text-03">
              Automatic updates are turned off by your organization.
            </Text>
          ) : null}
        </PrefSection>
        <PrefSection title="Notifications">
          <Section flexDirection="row" justifyContent="between" height="fit">
            <label htmlFor="notify-answers">
              <Text font="main-ui-body" color="text-04">
                Notify me when an answer is ready
              </Text>
            </label>
            <InputSwitch
              id="notify-answers"
              checked={prefs?.notifyAnswers ?? true}
              disabled={!prefs || prefs.notificationsDisabled}
              onCheckedChange={(enabled) => void onNotifyAnswers(enabled)}
            />
          </Section>
          {prefs?.notificationsDisabled ? <ManagedNote /> : null}
        </PrefSection>
        <PrefSection title="Account">
          <Text font="main-ui-body" color="text-04">
            {prefs?.signedIn
              ? `Signed in. The session token is in the ${IS_MAC ? "macOS keychain" : "system credential store"}.`
              : "Signed out"}
          </Text>
          <Section flexDirection="row" justifyContent="start" height="fit">
            <Button
              variant="danger"
              prominence="secondary"
              disabled={!prefs?.signedIn}
              onClick={() => void run(signOut)}
            >
              Sign out
            </Button>
          </Section>
        </PrefSection>
        <ErrorText message={error} />
      </Section>
    </WindowFrame>
  );
}

mount(<Preferences />);
