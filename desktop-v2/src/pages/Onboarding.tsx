import { useState, type FormEvent } from "react";
import { Button, InputTypeIn, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { mount } from "@/lib/mount";
import { ErrorText, Field, WindowFrame } from "@/lib/WindowFrame";
import { checkServer, errorMessage, saveServer, type ServerInfo } from "@/lib/ipc";

const DEFAULT_SERVER = "http://localhost:3000";

function Onboarding() {
  const [url, setUrl] = useState(DEFAULT_SERVER);
  const [checking, setChecking] = useState(false);
  const [info, setInfo] = useState<ServerInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setChecking(true);
    setError(null);
    setInfo(null);
    try {
      setInfo(await checkServer(url));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setChecking(false);
    }
  }

  async function onContinue() {
    if (!info) return;
    try {
      await saveServer(info.url);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <WindowFrame title="Welcome to Onyx" subtitle="Connect to your Onyx server">
      <form onSubmit={onSubmit}>
        <Section gap={4} alignItems="stretch" height="fit">
          <Field label="Server URL">
            <InputTypeIn
              id="server-url"
              value={url}
              autoFocus
              spellCheck={false}
              onChange={(e) => {
                setUrl(e.target.value);
                setInfo(null);
              }}
              placeholder="https://cloud.onyx.app"
            />
          </Field>
          <ErrorText message={error} />
          {info ? (
            <Text font="secondary-body" color="text-04">
              {`Connected to ${info.url}. Server version: ${info.backendVersion}.`}
            </Text>
          ) : null}
          <Section flexDirection="row" gap={2} justifyContent="end" height="fit">
            <Button
              type="submit"
              prominence={info ? "secondary" : "primary"}
              disabled={checking || url.trim() === ""}
            >
              {checking ? "Checking…" : "Check server"}
            </Button>
            <Button disabled={!info} onClick={() => void onContinue()}>
              Continue
            </Button>
          </Section>
        </Section>
      </form>
    </WindowFrame>
  );
}

mount(<Onboarding />);
