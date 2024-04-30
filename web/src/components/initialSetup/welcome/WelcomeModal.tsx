"use client";

import { Button, Divider, Text } from "@tremor/react";
import { Modal } from "../../Modal";
import Link from "next/link";
import Cookies from "js-cookie";
import { useRouter } from "next/navigation";
import { COMPLETED_WELCOME_FLOW_COOKIE } from "./constants";
import { FiCheckCircle, FiMessageSquare, FiShare2 } from "react-icons/fi";
import { useEffect, useState } from "react";
import { BackButton } from "@/components/BackButton";
import { ApiKeyForm } from "@/components/llm/ApiKeyForm";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/models/llm/interfaces";
import { checkLlmProvider } from "./lib";
import { User } from "@/lib/types";

function setWelcomeFlowComplete() {
  Cookies.set(COMPLETED_WELCOME_FLOW_COOKIE, "true", { expires: 365 });
}

export function _CompletedWelcomeFlowDummyComponent() {
  setWelcomeFlowComplete();
  return null;
}

function UsageTypeSection({
  title,
  description,
  callToAction,
  icon,
  onClick,
}: {
  title: string;
  description: string | JSX.Element;
  callToAction: string;
  icon?: React.ElementType;
  onClick: () => void;
}) {
  return (
    <div>
      <Text className="font-bold">{title}</Text>
      <div className="text-base mt-1 mb-3">{description}</div>
      <div
        onClick={(e) => {
          e.preventDefault();
          onClick();
        }}
      >
        <div className="text-link font-medium cursor-pointer select-none">
          {callToAction}
        </div>
      </div>
    </div>
  );
}

export function _WelcomeModal({ user }: { user: User | null }) {
  const router = useRouter();
  const [selectedFlow, setSelectedFlow] = useState<null | "search" | "chat">(
    null
  );
  const [isHidden, setIsHidden] = useState(false);
  const [apiKeyVerified, setApiKeyVerified] = useState<boolean>(false);
  const [providerOptions, setProviderOptions] = useState<
    WellKnownLLMProviderDescriptor[]
  >([]);

  useEffect(() => {
    async function fetchProviderInfo() {
      const { providers, options, defaultCheckSuccessful } =
        await checkLlmProvider(user);
      setApiKeyVerified(providers.length > 0 && defaultCheckSuccessful);
      setProviderOptions(options);
    }

    fetchProviderInfo();
  }, []);

  if (isHidden) {
    return null;
  }

  let title;
  let body;
  switch (selectedFlow) {
    case "search":
      title = undefined;
      body = (
        <div className="max-h-[85vh] overflow-y-auto px-4 pb-4">
          <BackButton behaviorOverride={() => setSelectedFlow(null)} />
          <div className="mt-3">
            <Text className="font-bold flex">
              {apiKeyVerified && (
                <FiCheckCircle className="my-auto mr-2 text-success" />
              )}
              Step 1: Setup an LLM
            </Text>
            <div>
              {apiKeyVerified ? (
                <Text className="mt-2">
                  LLM setup complete!
                  <br /> <br />
                  If you want to change the key later, you&apos;ll be able to
                  easily to do so in the Admin Panel.
                </Text>
              ) : (
                <ApiKeyForm
                  onSuccess={() => setApiKeyVerified(true)}
                  providerOptions={providerOptions}
                />
              )}
            </div>
            <Text className="font-bold mt-6 mb-2">
              Step 2: Connect Data Sources
            </Text>
            <div>
              <Text>
                Connectors are the way that Danswer gets data from your
                organization&apos;s various data sources. Once setup, we&apos;ll
                automatically sync data from your apps and docs into Danswer, so
                you can search through all of them in one place.
              </Text>

              <div className="flex mt-3">
                <Link
                  href="/admin/add-connector"
                  onClick={(e) => {
                    e.preventDefault();
                    setWelcomeFlowComplete();
                    router.push("/admin/add-connector");
                  }}
                  className="w-fit mx-auto"
                >
                  <Button size="xs" icon={FiShare2} disabled={!apiKeyVerified}>
                    Setup your first connector!
                  </Button>
                </Link>
              </div>
            </div>
          </div>
        </div>
      );
      break;
    case "chat":
      title = undefined;
      body = (
        <div className="mt-3 max-h-[85vh] overflow-y-auto px-4 pb-4">
          <BackButton behaviorOverride={() => setSelectedFlow(null)} />

          <div className="mt-3">
            <Text className="font-bold flex">
              {apiKeyVerified && (
                <FiCheckCircle className="my-auto mr-2 text-success" />
              )}
              Step 1: Setup an LLM
            </Text>
            <div>
              {apiKeyVerified ? (
                <Text className="mt-2">
                  LLM setup complete!
                  <br /> <br />
                  If you want to change the key later or choose a different LLM,
                  you&apos;ll be able to easily to do so in the Admin Panel.
                </Text>
              ) : (
                <div>
                  <ApiKeyForm
                    onSuccess={() => setApiKeyVerified(true)}
                    providerOptions={providerOptions}
                  />
                </div>
              )}
            </div>

            <Text className="font-bold mt-6 mb-2 flex">
              Step 2: Start Chatting!
            </Text>

            <Text>
              Click the button below to start chatting with the LLM setup above!
              Don&apos;t worry, if you do decide later on you want to connect
              your organization&apos;s knowledge, you can always do that in the{" "}
              <Link
                className="text-link"
                href="/admin/add-connector"
                onClick={(e) => {
                  e.preventDefault();
                  setWelcomeFlowComplete();
                  router.push("/admin/add-connector");
                }}
              >
                Admin Panel
              </Link>
              .
            </Text>

            <div className="flex mt-3">
              <Link
                href="/chat"
                onClick={(e) => {
                  e.preventDefault();
                  setWelcomeFlowComplete();
                  router.push("/chat");
                  setIsHidden(true);
                }}
                className="w-fit mx-auto"
              >
                <Button size="xs" icon={FiShare2} disabled={!apiKeyVerified}>
                  Start chatting!
                </Button>
              </Link>
            </div>
          </div>
        </div>
      );
      break;
    default:
      title = "🎉 Welcome to Danswer";
      body = (
        <>
          <div>
            <Text>How are you planning on using Danswer?</Text>
          </div>
          <Divider />
          <UsageTypeSection
            title="Search / Chat with Knowledge"
            description={
              <Text>
                If you&apos;re looking to search through, chat with, or ask
                direct questions of your organization&apos;s knowledge, then
                this is the option for you!
              </Text>
            }
            callToAction="Get Started"
            onClick={() => setSelectedFlow("search")}
          />
          <Divider />
          <UsageTypeSection
            title="Secure ChatGPT"
            description={
              <Text>
                If you&apos;re looking for a pure ChatGPT-like experience, then
                this is the option for you!
              </Text>
            }
            icon={FiMessageSquare}
            callToAction="Get Started"
            onClick={() => {
              setSelectedFlow("chat");
            }}
          />

          {/* TODO: add a Slack option here */}
          {/* <Divider />
          <UsageTypeSection
            title="AI-powered Slack Assistant"
            description="If you're looking to setup a bot to auto-answer questions in Slack"
            callToAction="Connect your company knowledge!"
            link="/admin/add-connector"
          /> */}
        </>
      );
  }

  return (
    <Modal title={title} className="max-w-4xl">
      <div className="text-base">{body}</div>
    </Modal>
  );
}
