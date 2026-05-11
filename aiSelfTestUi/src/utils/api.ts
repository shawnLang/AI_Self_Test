export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

export type ApiErrorKind = 'http' | 'business' | 'network' | 'timeout';

export class ApiError extends Error {
  code?: number;
  status?: number;
  kind: ApiErrorKind;
  data?: unknown;

  constructor(message: string, options: { code?: number; status?: number; kind: ApiErrorKind; data?: unknown }) {
    super(message);
    this.name = 'ApiError';
    this.code = options.code;
    this.status = options.status;
    this.kind = options.kind;
    this.data = options.data;
  }
}

export type ApiRequestInit = RequestInit & {
  timeoutMs?: number;
};

const DEFAULT_TIMEOUT_MS = 30_000;

export async function apiRequest(input: RequestInfo | URL, init: ApiRequestInit = {}): Promise<Response> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal, headers, body, ...rest } = init;
  const controller = new AbortController();
  let timedOut = false;

  const abortFromCaller = () => controller.abort(signal?.reason);
  if (signal) {
    if (signal.aborted) {
      abortFromCaller();
    } else {
      signal.addEventListener('abort', abortFromCaller, { once: true });
    }
  }

  const timeoutId = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    return await fetch(input, {
      ...rest,
      body,
      headers: buildHeaders(headers, body),
      signal: controller.signal,
    });
  } catch (error) {
    if (timedOut) {
      throw new ApiError('请求超时，请稍后重试', { kind: 'timeout' });
    }
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError((error as Error).message || '网络请求失败', { kind: 'network' });
  } finally {
    window.clearTimeout(timeoutId);
    signal?.removeEventListener('abort', abortFromCaller);
  }
}

export async function fetchApi<T>(input: RequestInfo | URL, init?: ApiRequestInit): Promise<T> {
  const response = await apiRequest(input, init);
  const payload = await response.json().catch(() => null) as ApiResponse<T> | null;

  if (!response.ok) {
    throw new ApiError(payload?.message || `请求失败（HTTP ${response.status}）`, {
      code: payload?.code,
      status: response.status,
      kind: 'http',
      data: payload?.data,
    });
  }

  if (!payload || payload.code !== 0) {
    throw new ApiError(payload?.message || '业务处理失败', {
      code: payload?.code,
      status: response.status,
      kind: 'business',
      data: payload?.data,
    });
  }

  return payload.data;
}

async function fetchRawJson<T>(input: RequestInfo | URL, init?: ApiRequestInit): Promise<T> {
  const response = await apiRequest(input, init);
  const payload = await response.json().catch(() => null) as unknown;

  if (!response.ok) {
    const errorPayload = isRecord(payload) ? payload : null;
    const message = typeof errorPayload?.message === 'string'
      ? errorPayload.message
      : typeof errorPayload?.error === 'string'
        ? errorPayload.error
        : undefined;
    throw new ApiError(message || `请求失败（HTTP ${response.status}）`, {
      status: response.status,
      kind: 'http',
    });
  }

  return payload as T;
}

export { fetchRawJson };

function buildHeaders(headers: HeadersInit | undefined, body: BodyInit | null | undefined): Headers {
  const nextHeaders = new Headers(headers);
  nextHeaders.set('Accept', 'application/json');

  if (body && !(body instanceof FormData) && !nextHeaders.has('Content-Type')) {
    nextHeaders.set('Content-Type', 'application/json');
  }

  return nextHeaders;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
