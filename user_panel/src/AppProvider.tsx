import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { apiFetch, configureApiClient } from './api/client';
import { BASE_URL } from './api/baseUrl';
import { translate } from './i18n';
import { AppContext } from './state';
import { getTelegramInitData, initTelegramWebApp } from './telegram/initTelegram';
import type { BotLinks, BotRole, CartItem, Language, Product, User } from './types';

let token: string | null = null;
const renew: Partial<Record<BotRole, Promise<{ accessToken: string; user: User } | null>>> = {};
async function refreshSession(role: BotRole) {
  if (!renew[role]) renew[role] = fetch(BASE_URL + '/auth/refresh/' + role, { method: 'POST', credentials: 'include' })
    .then(async response => response.ok ? await response.json() as { accessToken: string; user: User } : null)
    .finally(() => { delete renew[role]; });
  return renew[role]!;
}
const api = (path: string, init?: RequestInit) => apiFetch(path, init, { auth: true });
const initDataKey = (role: BotRole) => 'shirin.auth.initData.v1.' + role;
const logoutKey = (role: BotRole) => 'shirin.auth.logout.v1.' + role;

async function fingerprint(initData: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(initData));
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
}

function readCart(userId: number): CartItem[] {
  try {
    const value = JSON.parse(localStorage.getItem('shirin.cart.v1.' + userId) || '[]');
    if (!Array.isArray(value)) return [];
    return value.filter((item: CartItem) => item.product?.id > 0 && ['unit', 'package'].includes(item.sale_format) && Number.isInteger(item.quantity) && item.quantity > 0 && item.quantity <= 100000);
  } catch { return []; }
}

export function AppProvider({ children, botRole = 'user' }: { children: ReactNode; botRole?: BotRole }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [authError, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [lang, setLanguage] = useState<Language>(() => localStorage.getItem('shirin.language.v1') === 'uz' ? 'uz' : 'ru');
  const [cart, setCart] = useState<CartItem[]>([]);
  const [botLinks, setBotLinks] = useState<BotLinks | null>(null);
  const lastInitData = useRef<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    initTelegramWebApp();
    void fetch(BASE_URL + '/auth/bots').then(async response => response.ok ? await response.json() as BotLinks : null)
      .then(links => { if (!cancelled) setBotLinks(links); }).catch(() => {});
    configureApiClient({ getAccessToken: () => token, renewAccessToken: async () => {
      const session = await refreshSession(botRole);
      token = session?.accessToken ?? null;
      if (!cancelled) setUser(session?.user ?? null);
      return token;
    }, onAuthFailure: () => { if (!cancelled) setUser(null); } });
    async function login() {
      try {
        const initData = getTelegramInitData();
        const initDataHash = initData ? await fingerprint(initData) : null;
        // Telegram restores initData from its own sessionStorage even after URL cleanup.
        const loggedOut = initDataHash && sessionStorage.getItem(logoutKey(botRole)) === initDataHash;
        const session = loggedOut ? null : initData ? await fetch(BASE_URL + '/auth/telegram/' + botRole, {
          method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ init_data: initData }),
        }).then(async response => {
          const data = await response.json();
          if (!response.ok) throw new Error(data.detail);
          return data as { accessToken: string; user: User };
        }) : await refreshSession(botRole);
        if (!cancelled) {
          if (session && initDataHash) {
            lastInitData.current = initDataHash;
            sessionStorage.setItem(initDataKey(botRole), initDataHash);
            sessionStorage.removeItem(logoutKey(botRole));
          }
          token = session?.accessToken ?? null;
          setUser(session?.user ?? null);
          if (session) setCart(readCart(session.user.id));
          setError(session ? '' : 'login_required');
          setReady(true);
        }
      } catch (error) { if (!cancelled) { setError(error instanceof Error ? error.message : 'error'); setReady(true); } }
    }
    void login();
    return () => { cancelled = true; };
  }, [reload, botRole]);
  useEffect(() => { if (user) localStorage.setItem('shirin.cart.v1.' + user.id, JSON.stringify(cart)); }, [cart, user]);
  const setLang = useCallback((value: Language) => { setLanguage(value); localStorage.setItem('shirin.language.v1', value); document.documentElement.lang = value; }, []);
  const logout = useCallback(async () => {
    const response = await fetch(BASE_URL + '/auth/logout/' + botRole, { method: 'POST', credentials: 'include' });
    if (!response.ok) throw new Error('error');
    const initDataHash = lastInitData.current || sessionStorage.getItem(initDataKey(botRole));
    if (initDataHash) sessionStorage.setItem(logoutKey(botRole), initDataHash);
    token = null;
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
    queryClient.clear();
    setUser(null);
    setCart([]);
    setError('login_required');
  }, [queryClient, botRole]);
  const reloadAuth = useCallback(() => {
    sessionStorage.removeItem(logoutKey(botRole));
    setReady(false);
    setReload(value => value + 1);
  }, [botRole]);
  const add = useCallback((product: Product, format: 'unit' | 'package', delta: number) => {
    setCart(items => {
      const index = items.findIndex(item => item.product.id === product.id && item.sale_format === format);
      const quantity = Math.min(100000, (index >= 0 ? items[index].quantity : 0) + delta);
      const next = items.filter((_, i) => i !== index);
      if (quantity > 0) next.push({ product, sale_format: format, quantity });
      return next;
    });
  }, []);
  const value = useMemo(() => ({ user, ready, authError, botRole, botLinks, reloadAuth, lang, setLang,
    t: (key: string) => translate(key, lang), api, cart, add, clearCart: () => setCart([]), logout }), [user, ready, authError, botRole, botLinks, reloadAuth, lang, setLang, cart, add, logout]);
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
