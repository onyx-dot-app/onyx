import { ValidAutoSyncSources } from "@/lib/types";

// The first key is the connector type, and the second key is the field name
export const autoSyncConfigBySource: Record<
  ValidAutoSyncSources,
  Record<
    string,
    {
      label: string;
      subtext: JSX.Element;
    }
  >
> = {
  confluence: {},
  google_drive: {
    customer_id: {
      label: "Google Workspace Customer ID",
      subtext: (
        <>
          The unique identifier for your Google Workspace account. To find this,
          checkout the{" "}
          <a
            href="https://support.google.com/cloudidentity/answer/10070793"
            target="_blank"
            className="text-link"
          >
            guide from Google
          </a>
          .
        </>
      ),
    },
    company_domain: {
      label: "Google Workspace Company Domain",
      subtext: (
        <>
          The email domain for your Google Workspace account.
          <br />
          <br />
          For example, if your email provided through Google Workspace looks
          something like chris@danswer.ai, then your company domain is{" "}
          <b>danswer.ai</b>
        </>
      ),
    },
  },
  slack: {},
};
