/**
 * Tests for billing action functions.
 */

import {
  createCheckoutSession,
  createCustomerPortalSession,
  updateSeatCount,
  fetchLicense,
  refreshLicenseCache,
  uploadLicense,
} from "./svc";

// Mock NEXT_PUBLIC_CLOUD_ENABLED
jest.mock("@/lib/constants", () => ({
  NEXT_PUBLIC_CLOUD_ENABLED: false,
}));

describe("billing actions", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  describe("createCheckoutSession", () => {
    test("calls correct endpoint with request body", async () => {
      // Mock POST /api/admin/billing/create-checkout-session
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ url: "https://checkout.stripe.com/session123" }),
      } as Response);

      const result = await createCheckoutSession({
        billing_period: "monthly",
        email: "test@example.com",
      });

      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/billing/create-checkout-session",
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
        })
      );

      const callArgs = fetchSpy.mock.calls[0];
      const requestBody = JSON.parse(callArgs[1].body);
      expect(requestBody).toEqual({
        billing_period: "monthly",
        email: "test@example.com",
      });

      expect(result).toEqual({ url: "https://checkout.stripe.com/session123" });
    });

    test("throws error on failed response", async () => {
      // Mock POST /api/admin/billing/create-checkout-session (error)
      fetchSpy.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: "Invalid request" }),
      } as Response);

      await expect(createCheckoutSession()).rejects.toThrow("Invalid request");
    });

    test("throws default error when no detail provided", async () => {
      // Mock POST /api/admin/billing/create-checkout-session (error, no detail)
      fetchSpy.mockResolvedValueOnce({
        ok: false,
        json: async () => ({}),
      } as Response);

      await expect(createCheckoutSession()).rejects.toThrow(
        "Billing request failed"
      );
    });
  });

  describe("createCustomerPortalSession", () => {
    test("calls correct endpoint and returns portal URL", async () => {
      // Mock POST /api/admin/billing/create-customer-portal-session
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ url: "https://billing.stripe.com/portal123" }),
      } as Response);

      const result = await createCustomerPortalSession({
        return_url: "https://example.com/billing",
      });

      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/billing/create-customer-portal-session",
        expect.objectContaining({ method: "POST" })
      );

      expect(result).toEqual({ url: "https://billing.stripe.com/portal123" });
    });
  });

  describe("updateSeatCount", () => {
    test("calls correct endpoint with seat count", async () => {
      // Mock POST /api/admin/billing/seats/update
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          current_seats: 10,
          used_seats: 5,
          message: null,
        }),
      } as Response);

      const result = await updateSeatCount({ new_seat_count: 10 });

      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/billing/seats/update",
        expect.objectContaining({ method: "POST" })
      );

      const callArgs = fetchSpy.mock.calls[0];
      const requestBody = JSON.parse(callArgs[1].body);
      expect(requestBody).toEqual({ new_seat_count: 10 });

      expect(result.current_seats).toBe(10);
    });
  });

  describe("fetchLicense (self-hosted only)", () => {
    test("calls license fetch endpoint", async () => {
      // Mock POST /api/license/fetch
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true, message: "License fetched" }),
      } as Response);

      const result = await fetchLicense();

      expect(fetchSpy).toHaveBeenCalledWith("/api/license/fetch", {
        method: "POST",
      });

      expect(result).toEqual({ success: true, message: "License fetched" });
    });

    test("throws error on failed response", async () => {
      // Mock POST /api/license/fetch (error)
      fetchSpy.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: "License not found" }),
      } as Response);

      await expect(fetchLicense()).rejects.toThrow("License not found");
    });
  });

  describe("refreshLicenseCache (self-hosted only)", () => {
    test("calls license refresh endpoint", async () => {
      // Mock POST /api/license/refresh
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true, message: "Cache refreshed" }),
      } as Response);

      const result = await refreshLicenseCache();

      expect(fetchSpy).toHaveBeenCalledWith("/api/license/refresh", {
        method: "POST",
      });

      expect(result).toEqual({ success: true, message: "Cache refreshed" });
    });
  });

  describe("uploadLicense (self-hosted only)", () => {
    test("calls license upload endpoint with FormData", async () => {
      // Mock POST /api/license/upload
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          message:
            "License uploaded successfully. 10 seats, expires 2025-12-31",
        }),
      } as Response);

      const licenseKey = "test-license-key-12345";
      const result = await uploadLicense(licenseKey);

      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/license/upload",
        expect.objectContaining({
          method: "POST",
        })
      );

      // Verify FormData was used
      const callArgs = fetchSpy.mock.calls[0];
      expect(callArgs[1].body).toBeInstanceOf(FormData);

      expect(result).toEqual({
        success: true,
        message: "License uploaded successfully. 10 seats, expires 2025-12-31",
      });
    });

    test("throws error on failed upload", async () => {
      // Mock POST /api/license/upload (error)
      fetchSpy.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: "Invalid license signature" }),
      } as Response);

      await expect(uploadLicense("invalid-key")).rejects.toThrow(
        "Invalid license signature"
      );
    });
  });
});

describe("billing actions (cloud mode)", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    fetchSpy = jest.spyOn(global, "fetch");
    // Override to cloud mode
    jest.resetModules();
    jest.doMock("@/lib/constants", () => ({
      NEXT_PUBLIC_CLOUD_ENABLED: true,
    }));
  });

  afterEach(() => {
    fetchSpy.mockRestore();
    jest.resetModules();
  });

  test("uses cloud endpoint for checkout session", async () => {
    // Re-import with cloud mode
    const { createCheckoutSession: cloudCheckout } = await import("./svc");

    // Mock POST /api/tenants/create-checkout-session
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ url: "https://checkout.stripe.com/cloud123" }),
    } as Response);

    await cloudCheckout();

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/tenants/create-checkout-session",
      expect.any(Object)
    );
  });

  test("fetchLicense throws error in cloud mode", async () => {
    // Re-import with cloud mode
    const { fetchLicense: cloudFetchLicense } = await import("./svc");

    await expect(cloudFetchLicense()).rejects.toThrow(
      "only available for self-hosted"
    );
  });

  test("uploadLicense throws error in cloud mode", async () => {
    // Re-import with cloud mode
    const { uploadLicense: cloudUploadLicense } = await import("./svc");

    await expect(cloudUploadLicense("test-key")).rejects.toThrow(
      "only available for self-hosted"
    );
  });
});
