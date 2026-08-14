import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClient, ApiError } from "./client";

describe("ApiClient", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns a typed JSON response and sends a correlation ID", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient("https://api.example.test/api/v1");
    await expect(
      client.get<{ status: string }>("/health", { correlationId: "request-123" }),
    ).resolves.toEqual({
      status: "ok",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/api/v1/health",
      expect.objectContaining({
        method: "GET",
        headers: expect.any(Headers),
      }),
    );
    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(request.headers).get("X-Correlation-ID")).toBe("request-123");
  });

  it("maps the backend error envelope to ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "validation_error",
              message: "Request validation failed",
              details: { errors: [{ loc: ["query", "page"], msg: "Invalid integer" }] },
            },
          }),
          {
            status: 422,
            headers: { "X-Correlation-ID": "backend-456" },
          },
        ),
      ),
    );

    const client = new ApiClient("https://api.example.test");
    await expect(client.get("/documents")).rejects.toEqual(
      expect.objectContaining<ApiError>({
        name: "ApiError",
        code: "validation_error",
        message: "Request validation failed",
        details: { errors: [{ loc: ["query", "page"], msg: "Invalid integer" }] },
        status: 422,
        correlationId: "backend-456",
      }),
    );
  });
});
