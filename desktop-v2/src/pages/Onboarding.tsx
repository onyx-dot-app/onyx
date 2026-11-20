import { useRef, useState, type FormEvent } from "react";
import { Button, InputTypeIn } from "@opal/components";
import { Section } from "@opal/layouts";
import { mount } from "@/lib/mount";
import { ErrorText, Field, WindowFrame } from "@/lib/WindowFrame";
import { checkServer, errorMessage, saveServer } from "@/lib/ipc";

function Onboarding() {
  const [url, setUrl] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Each attempt gets an id; editing the URL starts a new one, so a check for
  // the old URL can never save it.
  const attemptId = useRef(0);

  // One step: Enter or Continue checks the server and, if it answers, saves it.
  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const id = ++attemptId.current;
    setChecking(true);
    setError(null);
    try {
      const info = await checkServer(url);
      if (id === attemptId.current) await saveServer(info.url);
    } catch (e) {
      if (id === attemptId.current) setError(errorMessage(e));
    } finally {
      if (id === attemptId.current) setChecking(false);
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
              autoComplete="url"
              onChange={(e) => {
                attemptId.current += 1;
                setUrl(e.target.value);
                setChecking(false);
              }}
              placeholder="https://your-company.onyx.app"
            />
          </Field>
          <ErrorText message={error} />
          <Section flexDirection="row" justifyContent="end" height="fit">
            <Button type="submit" disabled={checking || url.trim() === ""}>
              {checking ? "Connecting…" : "Continue"}
            </Button>
          </Section>
        </Section>
      </form>
    </WindowFrame>
  );
}

mount(<Onboarding />);
