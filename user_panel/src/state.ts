import { createContext, useContext } from 'react';
import type { Api, CartItem, Language, Product, User } from './types';

export interface AppState {
  user: User | null; ready: boolean; authError: string; reloadAuth: () => void;
  lang: Language; setLang: (value: Language) => void; t: (key: string) => string; api: Api;
  cart: CartItem[]; add: (product: Product, format: 'unit' | 'package', delta: number) => void; clearCart: () => void;
  logout: () => Promise<void>;
}
export const AppContext = createContext<AppState | null>(null);
export function useApp() {
  const context = useContext(AppContext);
  if (!context) throw new Error('AppProvider required');
  return context;
}
export async function json<T>(api: Api, path: string, init?: RequestInit): Promise<T> {
  const response = await api(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: 'error' }));
    throw new Error(typeof body.detail === 'string' ? body.detail : 'validation_error');
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}
export const body = (value: unknown, method = 'POST'): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
