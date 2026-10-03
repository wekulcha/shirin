import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { createBrowserRouter, RouterProvider, useNavigate, useParams } from 'react-router-dom';
import { AdminWorkspace } from './AdminWorkspace';
import { AuthGate } from './AuthGate';
import { Empty, ErrorBox } from './Controls';
import { json, useApp } from './state';
import type { User } from './types';

function Workspace() {
  const { api, user, ready, lang, setLang, t, logout } = useApp();
  const { section, entityId } = useParams();
  const navigate = useNavigate();
  const [logoutError, setLogoutError] = useState<unknown>(null);
  const session = useQuery({
    queryKey: ['shirinSuperadminSession', user?.id],
    queryFn: () => json<User>(api, '/superadmin/me'),
    enabled: ready && Boolean(user), retry: false,
  });
  async function signOut() {
    try { await logout(); navigate('/', { replace: true }); }
    catch (error) { setLogoutError(error); }
  }
  return <AuthGate superadmin>
    <ErrorBox error={logoutError} lang={lang} />
    {session.error ? session.error instanceof Error && session.error.message === 'access_denied' ? <Empty title={t('superadminDenied')} /> : <><ErrorBox error={session.error} lang={lang} /><button onClick={() => void session.refetch()}>{t('retry')}</button></> : session.data ?
      <AdminWorkspace api={api} user={session.data} lang={lang} setLang={setLang} mode="superadmin"
        section={section ?? 'overview'} entityId={entityId} onLogout={signOut}
        navigate={(tab, id) => navigate('/' + tab + (id ? '/' + id : ''))} /> : <p>{t('loading')}</p>}
  </AuthGate>;
}

const router = createBrowserRouter([
  { path: '/', element: <Workspace /> },
  { path: '/:section/:entityId?', element: <Workspace /> },
], { basename: '/shirin/superadmin/' });

export default function SuperadminApp() { return <RouterProvider router={router} />; }
