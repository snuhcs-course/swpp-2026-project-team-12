const TOKEN_KEY = 'talkdock.web.token';
let token = sessionStorage.getItem(TOKEN_KEY) || '';
// The family room for room-scoped endpoints such as the feed and digests.
let roomId = null;

export class ApiError extends Error {
  constructor(message, status = 0, { unavailable = false, field = null } = {}) {
    super(message); this.status = status; this.unavailable = unavailable; this.field = field;
  }
}

export const availabilityMessages = {
  server: '서버를 점검 중이거나 일시적인 문제가 생겼어요.\n잠시 후 다시 이용해 주세요.',
  connection: '서버에 연결하지 못했어요.\n인터넷 연결을 확인해 주세요. 서버 점검 중일 수 있으니 잠시 후 다시 시도해 주세요.',
  timeout: '서버 응답이 늦어지고 있어요.\n잠시 후 다시 시도해 주세요.',
};

// Confirmation is checked locally and never becomes part of the API payload.
export function registrationPayload(data) {
  if (typeof data.password !== 'string' || data.password.length < 10 || data.password.length > 128 || !/[0-9]/.test(data.password)) {
    throw new ApiError('비밀번호는 10자 이상, 숫자 포함으로 입력해 주세요. 최대 128자예요.', 0, { field: 'password' });
  }
  if (!data.confirm_password) throw new ApiError('비밀번호를 한 번 더 입력해 주세요.', 0, { field: 'confirm_password' });
  if (data.password !== data.confirm_password) throw new ApiError('비밀번호가 일치하지 않아요. 다시 확인해 주세요.', 0, { field: 'confirm_password' });
  const payload = { username: data.username, password: data.password, name: data.name, gender: data.gender };
  if (data.tts_voice) payload.tts_voice = data.tts_voice;
  return payload;
}

export function hasToken() { return Boolean(token); }
export function setToken(value) {
  token = value || '';
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

export function setRoom(id) { roomId = id ?? null; }

export async function api(path, { method = 'GET', data, binary = false, room = roomId } = {}) {
  const headers = {};
  const requestToken = token;
  if (requestToken) headers.Authorization = `Bearer ${requestToken}`;
  if (room !== null) headers['X-Family-Room'] = String(room);
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
      if (response.status === 503 && result?.code === 'maintenance') {
        window.dispatchEvent(new Event('server-maintenance'));
      }
      if (response.status === 401 && requestToken && requestToken === token) {
        setToken('');
        window.dispatchEvent(new Event('session-expired'));
      }
      const detail = typeof result?.error === 'string' ? result.error.trim() : '';
      const unavailable = response.status >= 500 && response.status <= 599 && !detail;
      throw new ApiError(detail || (unavailable ? availabilityMessages.server : `요청을 처리하지 못했어요. (${response.status})`), response.status, { unavailable });
    }
    return binary ? await response.blob() : await response.json().catch(() => {
      throw new ApiError('서버 응답을 확인하지 못했어요. 다시 시도해 주세요.');
    });
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(error.name === 'AbortError' ? availabilityMessages.timeout : availabilityMessages.connection, 0, { unavailable: true });
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
