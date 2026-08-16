const CORRELATION_ID_HEADER = "X-Correlation-ID";

export interface ApiErrorDetails {
  [key: string]: unknown;
}

interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: ApiErrorDetails;
  };
}

export class ApiError extends Error {
  readonly code: string;
  readonly details: ApiErrorDetails;
  readonly status: number;
  readonly correlationId?: string;

  constructor({
    code,
    message,
    details,
    status,
    correlationId,
  }: {
    code: string;
    message: string;
    details: ApiErrorDetails;
    status: number;
    correlationId?: string;
  }) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.details = details;
    this.status = status;
    this.correlationId = correlationId;
  }
}

export interface ApiRequestOptions extends RequestInit {
  correlationId?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isApiErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (!isRecord(value) || !isRecord(value.error)) {
    return false;
  }

  const { code, message, details } = value.error;
  return typeof code === "string" && typeof message === "string" && isRecord(details);
}

function createCorrelationId(): string {
  return crypto.randomUUID();
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  return text ? JSON.parse(text) : undefined;
}

export class ApiClient {
  constructor(private readonly baseUrl: string = "") {}

  async get<T>(path: string, options?: ApiRequestOptions): Promise<T> {
    return this.request<T>(path, { ...options, method: "GET" });
  }

  async post<T>(path: string, options?: ApiRequestOptions): Promise<T> {
    return this.request<T>(path, { ...options, method: "POST" });
  }

  async delete<T>(path: string, options?: ApiRequestOptions): Promise<T> {
    return this.request<T>(path, { ...options, method: "DELETE" });
  }

  async request<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
    const {
      correlationId: requestedCorrelationId,
      headers: requestHeaders,
      ...requestInit
    } = options;
    const headers = new Headers(requestHeaders);
    const correlationId =
      requestedCorrelationId ?? headers.get(CORRELATION_ID_HEADER) ?? createCorrelationId();

    headers.set(CORRELATION_ID_HEADER, correlationId);

    const response = await fetch(this.url(path), {
      ...requestInit,
      headers,
      credentials: "include",
    });
    const body = await parseResponseBody(response);

    if (!response.ok) {
      if (isApiErrorEnvelope(body)) {
        throw new ApiError({
          ...body.error,
          status: response.status,
          correlationId: response.headers.get(CORRELATION_ID_HEADER) ?? correlationId,
        });
      }

      throw new ApiError({
        code: `http_${response.status}`,
        message: response.statusText || "Request failed",
        details: {},
        status: response.status,
        correlationId: response.headers.get(CORRELATION_ID_HEADER) ?? correlationId,
      });
    }

    return body as T;
  }

  private url(path: string): string {
    if (!this.baseUrl) {
      return path;
    }

    return `${this.baseUrl.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;
  }
}

export const apiClient = new ApiClient(import.meta.env.VITE_API_BASE_URL ?? "");
