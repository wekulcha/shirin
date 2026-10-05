import { useState } from 'react';
import { createBrowserRouter, RouterProvider, useNavigate, useParams } from 'react-router-dom';
import { AuthGate } from './AuthGate';
import { useApp } from './state';
import { AdminWorkspace } from './AdminWorkspace';
import { ErrorBox } from './Controls';

function Workspace() {
  const { api, user, lang, setLang, logout } = useApp();
  const { section, entityId } = useParams();
  const navigate = useNavigate();
  const [logoutError, setLogoutError] = useState<unknown>(null);
  async function signOut() {
    try { await logout(); navigate('/', { replace: true }); }
    catch (error) { setLogoutError(error); }
  }
  return <AuthGate><ErrorBox error={logoutError} lang={lang} />{user && <AdminWorkspace api={api} user={user} lang={lang} setLang={setLang} section={section} entityId={entityId} onLogout={signOut} navigate={(tab, id) => navigate('/' + tab + (id ? '/' + id : ''))} />}</AuthGate>;
}
const router = createBrowserRouter([{ path: '/', element: <Workspace /> }, { path: '/:section/:entityId?', element: <Workspace /> }], { basename: '/shirin' });
export default function AdminApp() { return <RouterProvider router={router} />; }
