import { useEffect, useState, type ReactNode } from "react";
import { Button, Card, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { mount } from "@/lib/mount";
import { ErrorText, WindowFrame } from "@/lib/WindowFrame";
import { changeServer, errorMessage, getPrefs, signOut, type Prefs } from "@/lib/ipc";

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
    }
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
