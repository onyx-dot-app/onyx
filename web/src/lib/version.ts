import { buildUrl } from "./utilsSS";

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
  return process.env.ONYX_VERSION || "dev";
};
