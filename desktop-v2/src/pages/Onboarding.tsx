import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button, InputTypeIn } from "@opal/components";
import { Section } from "@opal/layouts";
import { mount } from "@/lib/mount";
import { ErrorText, Field, WindowFrame } from "@/lib/WindowFrame";
import { checkServer, errorMessage, getServerLock, saveServer } from "@/lib/ipc";

function Onboarding() {
  const [url, setUrl] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Managed policy can lock the server before the user types anything.
  const [locked, setLocked] = useState<string | null>(null);
  const [policyNotice, setPolicyNotice] = useState<string | null>(null);
  // The server in use when Change server opened this window.
  const [current, setCurrent] = useState<string | null>(null);
  // Each attempt gets an id; editing the URL starts a new one, so a check for
  // the old URL can never save it.
  const attemptId = useRef(0);

  useEffect(() => {
    void getServerLock().then((setup) => {
      setLocked(setup.lock);
      setPolicyNotice(setup.policyNotice);
      setCurrent(setup.current);
      if (setup.current !== null) {
        const server = setup.current;
        setUrl((typed) => (typed === "" ? server : typed));
      }
    });
  }, []);

  // One step: Enter or Continue checks the server and, if it answers, saves it.
  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (locked) return;
    const id = ++attemptId.current;
    setChecking(true);
    setError(null);
    try {
      // The server in use needs no check: the session and windows stay.
      if (current !== null && url.trim() === current) {
        await saveServer(current);
        return;
      }
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
              variant={locked !== null ? "disabled" : "primary"}
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
          <ErrorText message={policyNotice} />
          <ErrorText message={locked ?? error} />
          <Section flexDirection="row" justifyContent="end" height="fit">
            <Button
              type="submit"
              disabled={locked !== null || checking || url.trim() === ""}
            >
              {checking ? "Connecting…" : "Continue"}
            </Button>
          </Section>
        </Section>
      </form>
    </WindowFrame>
  );
}

mount(<Onboarding />);
