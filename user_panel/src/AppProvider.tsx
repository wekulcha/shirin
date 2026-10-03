import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { apiFetch, configureApiClient } from './api/client';
import { BASE_URL } from './api/baseUrl';
import { translate } from './i18n';
import { AppContext } from './state';
import { getTelegramInitData, initTelegramWebApp } from './telegram/initTelegram';
import type { CartItem, Language, Product, User } from './types';

let token: string | null = null;
let renew: Promise<{ accessToken: string; user: User } | null> | null = null;
async function refreshSession() {
  if (!renew) renew = fetch(BASE_URL + '/auth/refresh', { method: 'POST', credentials: 'include' })
    .then(async response => response.ok ? await response.json() as { accessToken: string; user: User } : null)
    .finally(() => { renew = null; });
  return renew;
}
const api = (path: string, init?: RequestInit) => apiFetch(path, init, { auth: true });

function readCart(userId: number): CartItem[] {
  try {
    const value = JSON.parse(localStorage.getItem('shirin.cart.v1.' + userId) || '[]');
    if (!Array.isArray(value)) return [];
    return value.filter((item: CartItem) => item.product?.id > 0 && ['unit', 'package'].includes(item.sale_format) && Number.isInteger(item.quantity) && item.quantity > 0 && item.quantity <= 100000);
  } catch { return []; }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [authError, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [lang, setLanguage] = useState<Language>(() => localStorage.getItem('shirin.language.v1') === 'uz' ? 'uz' : 'ru');
  const [cart, setCart] = useState<CartItem[]>([]);
  useEffect(() => {
    let cancelled = false;
    initTelegramWebApp();
    configureApiClient({ getAccessToken: () => token, renewAccessToken: async () => {
      const session = await refreshSession();
      token = session?.accessToken ?? null;
      if (!cancelled) setUser(session?.user ?? null);
      return token;
    }, onAuthFailure: () => { if (!cancelled) setUser(null); } });
    async function login() {
      try {
        const initData = getTelegramInitData();
        const session = initData ? await fetch(BASE_URL + '/auth/telegram', {
          method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ init_data: initData }),
        }).then(async response => {
          const data = await response.json();
          if (!response.ok) throw new Error(data.detail);
          return data as { accessToken: string; user: User };
        }) : await refreshSession();
        if (!cancelled) {
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
  }, [reload]);
  useEffect(() => { if (user) localStorage.setItem('shirin.cart.v1.' + user.id, JSON.stringify(cart)); }, [cart, user]);
  const setLang = useCallback((value: Language) => { setLanguage(value); localStorage.setItem('shirin.language.v1', value); document.documentElement.lang = value; }, []);
  const add = useCallback((product: Product, format: 'unit' | 'package', delta: number) => {
    setCart(items => {
      const index = items.findIndex(item => item.product.id === product.id && item.sale_format === format);
      const quantity = Math.min(100000, (index >= 0 ? items[index].quantity : 0) + delta);
      const next = items.filter((_, i) => i !== index);
      if (quantity > 0) next.push({ product, sale_format: format, quantity });
      return next;
    });
  }, []);
  const value = useMemo(() => ({ user, ready, authError, reloadAuth: () => { setReady(false); setReload(v => v + 1); }, lang, setLang,
    t: (key: string) => translate(key, lang), api, cart, add, clearCart: () => setCart([]) }), [user, ready, authError, lang, setLang, cart, add]);
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
