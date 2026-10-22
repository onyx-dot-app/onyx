import { NextRequest } from "next/server";
import { config, proxy } from "@/proxy";

describe("public enterprise logo", () => {
  const request = new NextRequest("https://tutor.example.edu/logo.png");
  let fetchMock: jest.SpyInstance<
    ReturnType<typeof fetch>,
    Parameters<typeof fetch>
  >;

  beforeEach(() => {
    fetchMock = jest.spyOn(globalThis, "fetch");
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("routes the public logo through enterprise branding", () => {
    expect(config.matcher).toContain("/logo.png");
  });

  it("serves the uploaded image without requiring a login", async () => {
    fetchMock
      .mockResolvedValueOnce(Response.json({ use_custom_logo: true }))
      .mockResolvedValueOnce(
        new Response("custom-image", {
          headers: { "Content-Type": "image/svg+xml" },
        })
      );

    const response = await proxy(request);

    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe("image/svg+xml");
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(await response.text()).toBe("custom-image");
  });

  it("uses the bundled logo when custom branding is disabled", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ use_custom_logo: false }));

    const response = await proxy(request);

    expect(response.headers.get("x-middleware-next")).toBe("1");
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each(["settings missing", "logo missing", "backend unavailable"])(
    "falls back to the bundled logo when %s",
    async (failure) => {
      if (failure === "settings missing") {
        fetchMock.mockResolvedValueOnce(new Response(null, { status: 404 }));
      } else if (failure === "logo missing") {
        fetchMock
          .mockResolvedValueOnce(Response.json({ use_custom_logo: true }))
          .mockResolvedValueOnce(new Response(null, { status: 404 }));
      } else {
        fetchMock.mockRejectedValueOnce(new Error("Connection refused"));
      }

      const response = await proxy(request);

      expect(response.headers.get("x-middleware-next")).toBe("1");
      expect(response.headers.get("Cache-Control")).toBe("no-store");
    }
  );
});
