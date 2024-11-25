import { buildUrl } from "./utilsSS";
import getConfig from "next/config";

const { publicRuntimeConfig } = getConfig();
const version = publicRuntimeConfig?.version;

// Maybe improve type-safety by creating a 'VersionType' instead of generic string
export const getBackendVersion = async (): Promise<string | null> => {
  try {
    const res = await fetch(buildUrl("/version"));
    if (!res.ok) {
      //throw new Error("Failed to fetch data");
      return null;
    }

    const data: { backend_version: string } = await res.json();
    return data.backend_version as string;
  } catch (e) {
    console.log(`Error fetching backend version info: ${e}`);
    return null;
  }
};

// Frontend?
export const getWebVersion = (): string | null => {

  if (process.env.APP_VERSION) {
    return process.env.APP_VERSION;
  }

  return version;
};
