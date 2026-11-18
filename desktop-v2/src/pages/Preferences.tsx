import { useEffect, useState, type ReactNode } from "react";
import { Button, Card, InputTypeIn, Text } from "@opal/components";
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

function Preferences() {
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [hotkey, setHotkeyDraft] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getPrefs().then((p) => {
      setPrefs(p);
      setHotkeyDraft(p.hotkey);
    });
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

  async function onSaveHotkey() {
    const draft = hotkey.trim();
    setSaved(false);
    await run(async () => {
      await setHotkey(draft);
      setPrefs((p) => (p ? { ...p, hotkey: draft } : p));
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
          <Field label="Global shortcut, for example CommandOrControl+Shift+Space" inputId="hotkey">
            <InputTypeIn
              id="hotkey"
              value={hotkey}
              spellCheck={false}
              onChange={(e) => {
                setHotkeyDraft(e.target.value);
                setSaved(false);
              }}
            />
          </Field>
          <Section flexDirection="row" gap={3} justifyContent="start" height="fit">
            <Button
              prominence="secondary"
              disabled={!prefs || hotkey.trim() === "" || hotkey.trim() === prefs.hotkey}
              onClick={() => void onSaveHotkey()}
            >
              Save shortcut
            </Button>
            {saved && hotkey.trim() === prefs?.hotkey ? (
              <Text font="secondary-body" color="text-03">
                Saved
              </Text>
            ) : null}
          </Section>
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
