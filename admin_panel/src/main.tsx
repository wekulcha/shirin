import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import AdminApp from '../../user_panel/src/AdminApp';
import { AppProvider } from '../../user_panel/src/AppProvider';
import '../../user_panel/src/style.css';

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 15000, retry: 1 } } });
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={queryClient}><AppProvider botRole="admin"><AdminApp /></AppProvider></QueryClientProvider>);
