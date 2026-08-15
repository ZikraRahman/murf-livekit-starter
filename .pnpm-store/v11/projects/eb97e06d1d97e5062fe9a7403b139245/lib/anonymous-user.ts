const STORAGE_KEY = 'bharat-finance-anonymous-user-id';

export function getAnonymousUserId(): string {
  const existing = window.localStorage.getItem(STORAGE_KEY);
  if (existing) return existing;
  const userId = `anon_${crypto.randomUUID()}`;
  window.localStorage.setItem(STORAGE_KEY, userId);
  return userId;
}
