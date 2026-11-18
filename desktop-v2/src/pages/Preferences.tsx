import { useEffect, useState, type KeyboardEvent, type ReactNode } from "react";
import { Button, Card, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { mount } from "@/lib/mount";
import { ErrorText, Field, WindowFrame } from "@/lib/WindowFrame";
import {
  changeServer,
  errorMessage,
  getPrefs,
  setHotkey,
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
function acceleratorFor(event: KeyboardEvent): string | null {
  const code = event.code;
  const key =
    NAMED_KEYS[code] ??
    (/^Key[A-Z]$/.test(code) ? code.slice(3) : null) ??
    (/^Digit[0-9]$/.test(code) ? code.slice(5) : null) ??
    (/^F([1-9]|1[0-9]|2[0-4])$/.test(code) ? code : null);
  if (!key || !(event.metaKey || event.ctrlKey || event.altKey)) return null;
  const parts: string[] = [];
  if (event.metaKey) parts.push("CommandOrControl");
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

// "CommandOrControl+Shift+Space" as macOS shows it: "⌘⇧Space".
function displayShortcut(accelerator: string): string {
  return accelerator
    .split("+")
    .map((part) => SYMBOLS[part] ?? part)
    .join("");
}

interface ShortcutRecorderProps {
  value: string | null;
  onRecord: (accelerator: string) => void;
}

// Like Claude Desktop's shortcut setting: click, then press the new keys.
function ShortcutRecorder({ value, onRecord }: ShortcutRecorderProps) {
  const [recording, setRecording] = useState(false);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (!recording) return;
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

  return (
    <button
      type="button"
      id="hotkey"
      aria-label="Launcher shortcut"
      className="h-9 rounded-08 border border-border-02 bg-background-neutral-00 px-3 text-start font-main-ui-body text-text-04 focus:border-border-05 focus:outline-none"
      onClick={() => setRecording(true)}
      onBlur={() => setRecording(false)}
      onKeyDown={onKeyDown}
    >
      {recording ? "Press the new shortcut… (Esc cancels)" : value ? displayShortcut(value) : ""}
    </button>
  );
}

function Preferences() {
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      setPrefs((p) => (p ? { ...p, hotkey: accelerator } : p));
      setSaved(true);
    });
  }

  return (
    <WindowFrame title="Preferences" subtitle="Settings for this device">
      <Section gap={4} alignItems="stretch" height="fit">
        <PrefSection title="Server">
          <Text font="main-ui-body" color="text-04">
            {prefs?.serverUrl ?? "Not connected"}
          </Text>
          <Section flexDirection="row" justifyContent="start" height="fit">
            <Button prominence="secondary" onClick={() => void run(changeServer)}>
              Change server
            </Button>
          </Section>
        </PrefSection>
        <PrefSection title="Launcher Shortcut">
          <Field label="Shows the launcher from any app" inputId="hotkey">
            <ShortcutRecorder value={prefs?.hotkey ?? null} onRecord={(a) => void onRecordHotkey(a)} />
          </Field>
          {saved ? (
            <Text font="secondary-body" color="text-03">
              Saved
            </Text>
          ) : null}
        </PrefSection>
        <PrefSection title="Account">
          <Text font="main-ui-body" color="text-04">
            {prefs?.signedIn
              ? "Signed in. The session token is in the macOS keychain."
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
