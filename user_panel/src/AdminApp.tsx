import { createBrowserRouter, RouterProvider, useNavigate, useParams } from 'react-router-dom';
import { AuthGate } from './App';
import { useApp } from './state';
import { AdminWorkspace } from './AdminWorkspace';

function Workspace() {
  const { api, user, lang, setLang } = useApp();
  const { section, entityId } = useParams();
  const navigate = useNavigate();
  return <AuthGate>{user && <AdminWorkspace api={api} user={user} lang={lang} setLang={setLang} section={section} entityId={entityId} navigate={(tab, id) => navigate('/' + tab + (id ? '/' + id : ''))} />}</AuthGate>;
}
const router = createBrowserRouter([{ path: '/', element: <Workspace /> }, { path: '/:section/:entityId?', element: <Workspace /> }], { basename: '/shirin' });
export default function AdminApp() { return <RouterProvider router={router} />; }
