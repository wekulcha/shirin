import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import { AppProvider } from './AppProvider';
import './style.css';

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 15000, retry: 1 } } });
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={queryClient}><AppProvider><App /></AppProvider></QueryClientProvider>);
