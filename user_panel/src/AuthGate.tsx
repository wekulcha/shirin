import type { ReactNode } from 'react';
import { ErrorBox } from './Controls';
import { useApp } from './state';

export function AuthGate({ children, superadmin = false }: { children: ReactNode; superadmin?: boolean }) {
  const { user, ready, authError, t, lang, reloadAuth, botRole, botLinks } = useApp();
  if (!ready) return <div className="login"><span className="brand-mark">S</span><p>{t('loading')}</p></div>;
  if (!user) return <div className="login"><span className="brand-mark">S</span><h1>{t(superadmin ? 'superadminLogin' : botRole === 'admin' ? 'adminLogin' : 'login')}</h1><p>{t(superadmin ? 'superadminLoginHint' : botRole === 'admin' ? 'adminLoginHint' : 'loginHint')}</p><ErrorBox error={authError} lang={lang} />{botLinks?.[botRole].url && <a className="button" href={botLinks[botRole].url}>{t('openBot')}</a>}<button onClick={reloadAuth}>{t('retry')}</button></div>;
  return children;
}
