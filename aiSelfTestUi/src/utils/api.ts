export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

export async function fetchApi<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  const payload = await response.json().catch(() => null) as ApiResponse<T> | null;

  if (!response.ok || !payload || payload.code !== 0) {
    throw new Error(payload?.message || '请求失败');
  }

  return payload.data;
}
