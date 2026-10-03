import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, NavLink, Outlet, createBrowserRouter, RouterProvider } from 'react-router-dom';
import { useApp, json } from './state';
import { cents, money } from './i18n';
import { Empty, ErrorBox, Photo } from './Controls';
import { CheckoutPage } from './CheckoutPage';
import { OrderDetail, OrderList } from './Orders';
import { AuthGate } from './AuthGate';
import type { Product } from './types';

function Shell() {
  const { user, lang, setLang, t, cart } = useApp();
  const count = cart.reduce((n, item) => n + item.quantity, 0);
  return <AuthGate><div className="app-shell">
    <header className="app-header"><Link to="/" className="brand"><span className="brand-mark">S</span><span>{t('title')}<small>{t('subtitle')}</small></span></Link>
      <button className="language" aria-label="Язык / Til" onClick={() => setLang(lang === 'ru' ? 'uz' : 'ru')}>{lang === 'ru' ? 'RU' : 'UZ'} <span>⌄</span></button>
    </header><main><Outlet /></main>
    <nav className="bottom-nav"><NavLink to="/" end><span>▦</span>{t('catalog')}</NavLink><NavLink to="/cart"><span>◡ {count > 0 && <b>{count}</b>}</span>{t('cart')}</NavLink><NavLink to="/orders"><span>≡</span>{t('orders')}</NavLink><NavLink to="/settings"><span>⚙</span>{t('settings')}</NavLink></nav>
    <span className="sr-only">{user?.username}</span>
  </div></AuthGate>;
}

function Catalog() {
  const { api, lang, t, cart, add } = useApp();
  const [search, setSearch] = useState('');
  const [brand, setBrand] = useState('');
  const [category, setCategory] = useState('');
  const [offset, setOffset] = useState(0);
  const query = useQuery({ queryKey: ['products', search, offset, brand, category], queryFn: () => json<Product[]>(api, '/products?q=' + encodeURIComponent(search) + '&offset=' + offset + '&brand=' + encodeURIComponent(brand) + '&category=' + encodeURIComponent(category)) });
  const meta = useQuery({ queryKey: ['catalogMeta'], queryFn: () => json<{ categories: string[] }>(api, '/catalog/meta') });
  const categories = meta.data?.categories ?? [];
  const products = query.data ?? [];
  return <div className="page">
    <section className="hero"><span className="eyebrow">SHIRIN · САДЫ ВОСТОКА</span><h1>{t('greeting')}</h1><p>{t('catalogHint')}</p><div className="hero-fruit" aria-hidden="true">◉<i>❧</i></div></section>
    <div className="search"><span>⌕</span><input value={search} onChange={e => { setSearch(e.target.value); setOffset(0); }} placeholder={t('search')} aria-label={t('search')} /></div>
    <div className="tabs">{['', 'Ширин', 'Сады Востока'].map(value => <button className={brand === value ? 'selected' : ''} key={value} onClick={() => { setBrand(value); setOffset(0); }}>{value || t('all')}</button>)}</div>
    <div className="chips"><button className={!category ? 'selected' : ''} onClick={() => { setCategory(''); setOffset(0); }}>{t('all')}</button>{categories.map(value => <button key={value} className={category === value ? 'selected' : ''} onClick={() => { setCategory(value); setOffset(0); }}>{value}</button>)}</div>
    <div className="section-heading"><h2>{t('catalog')}</h2><span>{products.length}</span></div>
    <ErrorBox error={query.error} lang={lang} />{query.isLoading && <p>{t('loading')}</p>}
    <div className="product-grid">{products.map(product => <article className="product-card" key={product.id}>
      <div className={'product-visual ' + (product.brand === 'Сады Востока' ? 'east' : '')}><Photo key={product.photo_reference} path={product.photo_reference} api={api} alt={product['name_' + lang as 'name_ru']} /><span className="volume">{product.volume_ml ? product.volume_ml + ' ' + t('ml') : product.category}</span></div>
      <div className="product-info"><small>{product.brand} · {product.sku}</small><h3>{product[lang === 'ru' ? 'name_ru' : 'name_uz']}</h3><p>{product[lang === 'ru' ? 'description_ru' : 'description_uz']}</p>
        {(['unit', 'package'] as const).filter(format => product[format === 'unit' ? 'sell_by_unit' : 'sell_by_package']).map(format => {
          const price = product[format === 'unit' ? 'unit_price_uzs' : 'package_price_uzs'] || '0';
          const count = cart.find(i => i.product.id === product.id && i.sale_format === format)?.quantity ?? 0;
          return <div className="sale-row" key={format}><div><span>{t(format)}{format === 'package' && ' · ' + product.units_per_package + ' ' + t('units')}</span><strong>{money(price, lang)}</strong></div>
            {count ? <div className="stepper"><button aria-label={'− ' + product.sku + ' ' + t(format)} onClick={() => add(product, format, -1)}>−</button><b>{count}</b><button aria-label={'+ ' + product.sku + ' ' + t(format)} onClick={() => add(product, format, 1)}>+</button></div> : <button className="add-button" aria-label={t('add') + ' ' + product.sku + ' ' + t(format)} onClick={() => add(product, format, 1)}>+</button>}</div>;
        })}
      </div>
    </article>)}</div>
    {!query.isLoading && !products.length && <Empty title={t('emptyCatalog')} />}
    <div className="actions">{offset > 0 && <button className="secondary" onClick={() => setOffset(v => Math.max(0, v - 200))}>{t('back')}</button>}{query.data?.length === 200 && <button className="secondary" onClick={() => setOffset(v => v + 200)}>{t('loadMore')}</button>}</div>
    {cart.length > 0 && <Link className="floating-cart" to="/cart">{t('cart')} · {cart.reduce((n, i) => n + i.quantity, 0)}<span>→</span></Link>}
  </div>;
}

function Cart() {
  const { cart, add, api, lang, t } = useApp();
  const total = cart.reduce((sum, item) => sum + cents(item.product[item.sale_format === 'unit' ? 'unit_price_uzs' : 'package_price_uzs']) * BigInt(item.quantity), 0n);
  if (!cart.length) return <div className="page"><Empty title={t('emptyCart')}><p>{t('emptyCartHint')}</p><Link className="button" to="/">{t('continue')}</Link></Empty></div>;
  return <div className="page"><h1>{t('cart')}</h1><div className="cart-list">{cart.map(item => <article className="cart-item" key={item.product.id + item.sale_format}>
    <Photo path={item.product.photo_reference} api={api} alt={item.product[lang === 'ru' ? 'name_ru' : 'name_uz']} />
    <div><small>{item.product.sku}</small><h3>{item.product[lang === 'ru' ? 'name_ru' : 'name_uz']}</h3><p>{t(item.sale_format)}{item.sale_format === 'package' && ' × ' + item.product.units_per_package}</p><strong>{money(cents(item.product[item.sale_format === 'unit' ? 'unit_price_uzs' : 'package_price_uzs']) * BigInt(item.quantity), lang)}</strong></div>
    <div className="cart-quantity"><div className="stepper"><button onClick={() => add(item.product, item.sale_format, -1)}>−</button><b>{item.quantity}</b><button onClick={() => add(item.product, item.sale_format, 1)}>+</button></div><button className="text-button" onClick={() => add(item.product, item.sale_format, -item.quantity)}>{t('remove')}</button></div>
  </article>)}</div><div className="total-card"><span>{t('total')}</span><strong>{money(total, lang)}</strong><Link className="button" to="/checkout">{t('checkout')} →</Link></div></div>;
}

function Settings() {
  const { t, lang, setLang, user } = useApp();
  return <div className="page"><h1>{t('settings')}</h1><div className="card"><h3>{user?.username}</h3><div className="tabs"><button onClick={() => setLang('ru')} className={lang === 'ru' ? 'selected' : ''}>Русский</button><button onClick={() => setLang('uz')} className={lang === 'uz' ? 'selected' : ''}>O‘zbekcha</button></div><p>{t('currency')}: UZS</p>{(user?.permissions.length || user?.superadmin) ? <a className="button" href={import.meta.env.VITE_ADMIN_APP_URL ?? 'https://adminmarket.wekulcha.online/shirin/'}>{t('admin')}</a> : null}</div></div>;
}

const router = createBrowserRouter([{ path: '/', element: <Shell />, children: [
  { index: true, element: <Catalog /> }, { path: 'cart', element: <Cart /> }, { path: 'checkout', element: <CheckoutPage /> },
  { path: 'orders', element: <OrderList /> }, { path: 'orders/:orderId', element: <OrderDetail /> }, { path: 'settings', element: <Settings /> },
  { path: '*', element: <Catalog /> },
]}], { basename: '/shirin' });
export default function App() { return <RouterProvider router={router} />; }
