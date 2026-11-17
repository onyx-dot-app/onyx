import { useRef, useState, type FormEvent } from "react";
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
  // Each check gets an id; editing the URL starts a new one, so a check for
  // the old URL can never enable Continue for it.
  const checkId = useRef(0);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const id = ++checkId.current;
    setChecking(true);
    setError(null);
    setInfo(null);
    try {
      const result = await checkServer(url);
      if (id === checkId.current) setInfo(result);
    } catch (e) {
      if (id === checkId.current) setError(errorMessage(e));
    } finally {
      if (id === checkId.current) setChecking(false);
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
          <Field label="Server URL" inputId="server-url">
            <InputTypeIn
              id="server-url"
              value={url}
              autoFocus
              spellCheck={false}
              onChange={(e) => {
                checkId.current += 1;
                setUrl(e.target.value);
                setInfo(null);
                setChecking(false);
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
