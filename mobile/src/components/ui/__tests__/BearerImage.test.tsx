import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import { render } from "@testing-library/react-native";

import { BearerImage } from "@/components/ui/BearerImage";

// Mutable `mock*` variables (allowed out-of-scope in a jest.mock factory) drive the token and
// capture the props expo-image would receive. The Image mock returns null (no component) so the
// nativewind babel transform doesn't pull `_ReactNativeCSSInterop` into the factory.
let mockToken: string | null = null;
let mockImageProps: Record<string, unknown> | null = null;

jest.mock("@/api/config", () => ({ getBaseUrl: () => "https://x.test/api" }));
jest.mock("@/hooks/useAuthToken", () => ({ useAuthToken: () => mockToken }));
jest.mock("expo-image", () => ({
  Image: (props: Record<string, unknown>) => {
    mockImageProps = props;
    return null;
  },
}));

describe("BearerImage", () => {
  beforeEach(() => {
    mockToken = null;
    mockImageProps = null;
  });

  it("shows a neutral placeholder (no image) until the bearer resolves", () => {
    mockToken = null;
    render(<BearerImage path="/chat/file/1" size={64} />);
    expect(mockImageProps).toBeNull();
  });

  it("renders the auth'd image with a bearer header and cachePolicy none", () => {
    mockToken = "tok";
    render(<BearerImage path="/persona/7/avatar" size={40} />);

    expect(mockImageProps?.source).toEqual({
      uri: "https://x.test/api/persona/7/avatar",
      headers: { Authorization: "Bearer tok" },
    });
    expect(mockImageProps?.cachePolicy).toBe("none");
  });
});
