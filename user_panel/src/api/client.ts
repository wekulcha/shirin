import { BASE_URL } from './baseUrl';

const FETCH_TIMEOUT_MS = 12_000;

export class ApiError extends Error {
  status: number;
  body: string;

  constructor(status: number, body: string) {
    super(body || `Request failed: ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

interface ApiFetchOptions {
  auth?: boolean;
  retryOn401?: boolean;
  timeoutMs?: number;
}

interface ApiAuthConfig {
  getAccessToken: () => string | null;
  renewAccessToken: () => Promise<string | null>;
  onAuthFailure: () => void;
}

const defaultAuthConfig: ApiAuthConfig = {
  getAccessToken: () => null,
  renewAccessToken: async () => null,
  onAuthFailure: () => {},
};

let authConfig: ApiAuthConfig = defaultAuthConfig;
let renewPromise: Promise<string | null> | null = null;

export function configureApiClient(next: Partial<ApiAuthConfig>): void {
  authConfig = { ...authConfig, ...next };
}

export function resetApiClient(): void {
  authConfig = defaultAuthConfig;
  renewPromise = null;
}

function buildUrl(path: string): string {
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path;
  }
  return `${BASE_URL}${path}`;
}

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number
): Promise<Response> {
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...init,
      signal: ctrl.signal,
      credentials: 'include',
    });
  } finally {
    window.clearTimeout(timer);
  }
}

function buildHeaders(headersInit: HeadersInit | undefined, auth: boolean): Headers {
  const headers = new Headers(headersInit ?? {});
  if (auth) {
    const token = authConfig.getAccessToken();
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }
  }
  return headers;
}

async function renewAccessToken(): Promise<string | null> {
  if (!renewPromise) {
    renewPromise = authConfig.renewAccessToken().finally(() => {
      renewPromise = null;
    });
  }
  return renewPromise;
}

export async function readErrorBody(response: Response): Promise<string> {
  try {
    const text = await response.text();
    return text.trim();
  } catch {
    return '';
  }
}

export async function apiFetch(
  path: string,
  init: RequestInit = {},
  options: ApiFetchOptions = {}
): Promise<Response> {
  const auth = options.auth ?? false;
  const retryOn401 = options.retryOn401 ?? auth;
  const timeoutMs = options.timeoutMs ?? FETCH_TIMEOUT_MS;
  const url = buildUrl(path);

  const doRequest = async (): Promise<Response> => {
    const headers = buildHeaders(init.headers, auth);
    return fetchWithTimeout(
      url,
      {
        ...init,
        headers,
      },
      timeoutMs
    );
  };

  let response = await doRequest();
  if (auth && retryOn401 && response.status === 401) {
    const token = await renewAccessToken();
    if (token) {
      response = await doRequest();
    } else {
      authConfig.onAuthFailure();
    }
  }

  return response;
}

export async function apiFetchJson<T>(
  path: string,
  init: RequestInit = {},
  options: ApiFetchOptions = {}
): Promise<T> {
  const response = await apiFetch(path, init, options);
  if (!response.ok) {
    throw new ApiError(response.status, await readErrorBody(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
