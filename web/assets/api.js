const TOKEN_KEY = 'talkdock.web.token';
let token = sessionStorage.getItem(TOKEN_KEY) || '';

export class ApiError extends Error {
  constructor(message, status = 0) { super(message); this.status = status; }
}

export function hasToken() { return Boolean(token); }
export function setToken(value) {
  token = value || '';
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

export async function api(path, { method = 'GET', data, binary = false } = {}) {
  const headers = {};
  const requestToken = token;
  if (requestToken) headers.Authorization = `Bearer ${requestToken}`;
  let body;
  if (data instanceof FormData) body = data;
  else if (data !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(data);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 150000);
  try {
    const response = await fetch(`/api/${path}`, { method, headers, body, signal: controller.signal, cache: 'no-store', credentials: 'omit' });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      if (response.status === 401 && requestToken && requestToken === token) {
        setToken('');
        window.dispatchEvent(new Event('session-expired'));
      }
      throw new ApiError(result.error || `요청을 처리하지 못했어요. (${response.status})`, response.status);
    }
    return binary ? response.blob() : response.json();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(error.name === 'AbortError' ? '응답이 늦어지고 있어요. 잠시 후 다시 시도해 주세요.' : '서버에 연결하지 못했어요. 연결 상태를 확인해 주세요.');
  } finally { clearTimeout(timer); }
}

// Photos require bearer authentication. Only request local API paths, even if
// PUBLIC_ORIGIN points the Android app at a different server or tunnel.
const images = new Map();
let imageGeneration = 0;
export async function imageURL(photoUrl) {
  const pathname = new URL(photoUrl, window.location.origin).pathname;
  if (!/^\/api\/posts\/\d+\/(?:image|images\/\d+)\/$/.test(pathname)) {
    throw new ApiError('사진 주소를 확인해 주세요.');
  }
  const path = pathname.slice('/api/'.length);
  if (!images.has(path)) {
    const generation = imageGeneration;
    images.set(path, api(path, { binary: true }).then(blob => {
      if (generation !== imageGeneration) throw new ApiError('사진을 다시 열어 주세요.');
      return URL.createObjectURL(blob);
    }).catch(error => { if (generation === imageGeneration) images.delete(path); throw error; }));
  }
  return images.get(path);
}
export function clearImages() {
  imageGeneration++;
  images.forEach(promise => promise.then(url => URL.revokeObjectURL(url)).catch(() => {}));
  images.clear();
}
