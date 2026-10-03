import { useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { body, json, useApp } from './state';
import { CustomerFields, ErrorBox, Photo } from './Controls';
import { customerBody } from './customer';
import { money } from './i18n';
import type { Customer, Order, Quote } from './types';

export function CheckoutPage() {
  const { cart, clearCart, user, api, t, lang } = useApp();
  const [customer, setCustomer] = useState<Customer>({ name: '', phone: '', address: '' });
  const [customerId, setCustomerId] = useState<number | null>(null);
  const [search, setSearch] = useState('');
  const [saveCustomer, setSaveCustomer] = useState(false);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [accepted, setAccepted] = useState<Order | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [locationError, setLocationError] = useState('');
  const [candidate, setCandidate] = useState<{ latitude: number; longitude: number } | null>(null);
  const attempt = useRef('');
  const clients = useQuery({ queryKey: ['checkoutCustomers', search], queryFn: () => json<Customer[]>(api, '/customers?q=' + encodeURIComponent(search)) });
  const canEdit = user?.superadmin || user?.permissions.includes('CAN_EDIT_MENU');
  const changeCustomer = (next: Customer) => { setCustomer(next); setQuote(null); };
  const checkout = () => ({ lines: cart.map(i => ({ product_id: i.product.id, sale_format: i.sale_format, quantity: i.quantity })), customer: customerBody(customer), customer_id: customerId, save_customer: saveCustomer });

  async function review(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const data = checkout();
      const result = await json<Quote>(api, '/orders/quote', body(data));
      const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(data)));
      const hash = Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
      const key = 'shirin.checkoutAttempt.v1.' + user?.id;
      const previous = JSON.parse(sessionStorage.getItem(key) || '{}');
      attempt.current = previous.hash === hash ? previous.attempt : crypto.randomUUID();
      sessionStorage.setItem(key, JSON.stringify({ hash, attempt: attempt.current }));
      setQuote(result);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function confirm() {
    if (!quote) return;
    setBusy(true); setError(null);
    try {
      const order = await json<Order>(api, '/orders', body({ ...checkout(), attempt_key: attempt.current, quote_token: quote.quote_token }));
      setAccepted(order); clearCart(); sessionStorage.removeItem('shirin.checkoutAttempt.v1.' + user?.id);
    } catch (e) { setError(e); if (e instanceof Error && ['conditions_changed', 'quote_expired', 'product_unavailable'].includes(e.message)) setQuote(null); }
    finally { setBusy(false); }
  }
  function requestLocation() {
    setLocationError('');
    const manager = window.Telegram?.WebApp?.LocationManager;
    if (manager) manager.init(() => {
      if (!manager.isLocationAvailable) { setLocationError('locationDenied'); return; }
      manager.getLocation(location => location ? setCandidate(location) : setLocationError('locationDenied'));
    });
    else if (navigator.geolocation) navigator.geolocation.getCurrentPosition(position => setCandidate({ latitude: position.coords.latitude, longitude: position.coords.longitude }), () => setLocationError('locationDenied'), { timeout: 12000, enableHighAccuracy: true });
    else setLocationError('locationDenied');
  }
  async function upload(file?: File) {
    if (!file) return;
    setBusy(true); setError(null);
    try {
      const form = new FormData(); form.append('file', file);
      const result = await json<{ path: string }>(api, '/media/upload?kind=store', { method: 'POST', body: form });
      changeCustomer({ ...customer, photo_reference: result.path });
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  if (accepted) return <div className="page"><div className="success-card"><span>✓</span><h1>{t('accepted')}</h1><h2>{accepted.number}</h2><p>{t('acceptedHint')}</p><strong>{money(accepted.total_uzs, lang)}</strong><Link className="button" to={'/orders/' + accepted.id}>{t('details')}</Link><Link to="/">{t('continue')}</Link></div></div>;
  if (!cart.length) return <div className="page"><h1>{t('emptyCart')}</h1><Link to="/">{t('continue')}</Link></div>;
  const duplicates = (clients.data ?? []).filter(c => c.id !== customerId && c.phone.replace(/\D/g, '') === customer.phone.replace(/\D/g, '') && customer.phone.length > 6);
  return <div className="page checkout"><Link className="back-link" to="/cart">← {t('cart')}</Link><h1>{t('checkout')}</h1><ErrorBox error={error} lang={lang} />
    {!quote ? <form onSubmit={review}>
      <section className="card"><h2><span className="step-number">1</span>{t('store')}</h2><input aria-label={t('storeSearch')} placeholder={t('storeSearch')} value={search} onChange={e => setSearch(e.target.value)} />
        <ErrorBox error={clients.error} lang={lang} /><div className="customer-choices">{(clients.data ?? []).slice(0, 6).map(c => <button type="button" key={c.id} className={customerId === c.id ? 'selected' : ''} onClick={() => { setCustomer(customerBody(c)); setCustomerId(c.id!); setSaveCustomer(false); }}><strong>{c.name}</strong><span>{c.code} · {c.phone}<br />{c.address}</span></button>)}</div>
        <button type="button" className="text-button" onClick={() => { setCustomerId(null); setCustomer({ name: '', phone: '', address: '' }); }}>{t('newStore')} +</button>
        <CustomerFields value={customer} onChange={changeCustomer} lang={lang} /><p className="hint">{t('snapshotHint')}</p>
        {duplicates.length > 0 && <p className="alert">{t('duplicateHint')}</p>}
        {canEdit && !customerId && <label className="checkbox"><input type="checkbox" checked={saveCustomer} onChange={e => setSaveCustomer(e.target.checked)} />{t('saveCustomer')}</label>}
      </section>
      <section className="card"><h2><span className="step-number">2</span>{t('location')}</h2><p>{t('locationHint')}</p><button type="button" className="secondary" onClick={requestLocation}>{t('useLocation')} ⌖</button>
        <ErrorBox error={locationError} lang={lang} />{candidate && <div className="location-preview"><p>{candidate.latitude.toFixed(6)}, {candidate.longitude.toFixed(6)}</p><a href={'https://yandex.uz/maps/?pt=' + candidate.longitude + ',' + candidate.latitude + '&z=17&l=map'} target="_blank" rel="noreferrer">{t('map')}</a><button type="button" onClick={() => { changeCustomer({ ...customer, ...candidate, map_url: null }); setCandidate(null); }}>{t('confirmLocation')}</button></div>}
        {customer.latitude != null && customer.longitude != null && <a href={'https://yandex.uz/maps/?pt=' + customer.longitude + ',' + customer.latitude + '&z=17&l=map'} target="_blank" rel="noreferrer">{t('map')} ↗</a>}
      </section>
      <section className="card"><h2><span className="step-number">3</span>{t('photo')}<small>{t('optional')}</small></h2><label className="file-button">{t('uploadPhoto')}<input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={e => void upload(e.target.files?.[0])} /></label>
        {customer.photo_reference && <div className="store-photo"><Photo key={customer.photo_reference} path={customer.photo_reference} api={api} alt={customer.name} /><button className="text-button" type="button" onClick={() => changeCustomer({ ...customer, photo_reference: null })}>{t('cancel')}</button></div>}
      </section><button className="wide" disabled={busy}>{busy ? t('loading') : t('review')} →</button>
    </form> : <section className="card"><h2>{t('review')}</h2><p className="hint">{t('reviewHint')}</p><h3>{customer.name}</h3><p>{customer.code} {customer.contact_name}<br />{customer.phone}<br />{customer.address}</p>
      {customer.latitude != null && <p>{customer.latitude}, {customer.longitude}</p>}{customer.map_url && <a href={customer.map_url} target="_blank" rel="noreferrer">{t('map')}</a>}
      {customer.photo_reference && <div className="store-photo"><Photo path={customer.photo_reference} api={api} alt={customer.name} /></div>}
      {quote.lines.map(line => <div className="review-line" key={line.sku + line.sale_format}><div><strong>{line[lang === 'ru' ? 'name_ru' : 'name_uz']}</strong><p>{line.sku} · {line.quantity} {t(line.sale_format)}{line.sale_format === 'package' && ' × ' + line.units_per_package + ' ' + t('units')}<br />{money(line.price_uzs, lang)} × {line.quantity}</p></div><b>{money(line.amount_uzs, lang)}</b></div>)}
      <div className="total-row"><span>{t('total')}</span><strong>{money(quote.total_uzs, lang)}</strong></div><p>{customer.comment}</p><div className="actions"><button className="secondary" disabled={busy} onClick={() => setQuote(null)}>{t('edit')}</button><button disabled={busy} onClick={() => void confirm()}>{busy ? t('loading') : t('confirm')}</button></div>
    </section>}
  </div>;
}
