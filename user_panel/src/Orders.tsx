import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { body, json, useApp } from './state';
import { money, translate } from './i18n';
import { Empty, ErrorBox, Photo } from './Controls';
import type { Api, Language, Order, User } from './types';

export function OrderBrowser({ api, lang, onSelect }: { api: Api; lang: Language; onSelect: (id: number) => void }) {
  const t = (key: string) => translate(key, lang);
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [payment, setPayment] = useState('');
  const [offset, setOffset] = useState(0);
  const query = useQuery({ queryKey: ['shirinOrders', q, status, payment, offset], queryFn: () => json<Order[]>(api, '/orders?q=' + encodeURIComponent(q) + '&offset=' + offset + (status ? '&status=' + status : '') + (payment ? '&payment_status=' + payment : '')) });
  return <><div className="filters"><input placeholder={t('searchOrders')} aria-label={t('searchOrders')} value={q} onChange={e => { setQ(e.target.value); setOffset(0); }} />
    <select aria-label={t('status')} value={status} onChange={e => { setStatus(e.target.value); setOffset(0); }}><option value="">{t('status')} · {t('all')}</option>{['ACCEPTED', 'READY', 'DELIVERED', 'COMPLETED'].map(s => <option key={s} value={s}>{t(s)}</option>)}</select>
    <select aria-label={t('payment')} value={payment} onChange={e => { setPayment(e.target.value); setOffset(0); }}><option value="">{t('payment')} · {t('all')}</option>{['UNPAID', 'PAID'].map(s => <option key={s} value={s}>{t(s)}</option>)}</select></div>
    <ErrorBox error={query.error} lang={lang} />{query.isLoading && <p>{t('loading')}</p>}
    <div className="order-list">{query.data?.map(order => <button className="order-card" key={order.id} onClick={() => onSelect(order.id)}><div className="order-top"><strong>{order.number}</strong><span>{new Date(order.created_at).toLocaleDateString(lang === 'ru' ? 'ru-RU' : 'uz-UZ')}</span></div><h3>{order.customer_snapshot.name}</h3><p>{order.customer_snapshot.address}</p><div className="order-bottom"><span className={'badge ' + order.status}>{t(order.status)}</span><span className={'badge ' + order.payment_status}>{t(order.payment_status)}</span><strong>{money(order.total_uzs, lang)}</strong></div></button>)}</div>
    {!query.isLoading && !query.data?.length && <Empty title={t('emptyOrders')} />}
    <div className="actions">{offset > 0 && <button className="secondary" onClick={() => setOffset(v => Math.max(0, v - 200))}>{t('back')}</button>}{query.data?.length === 200 && <button className="secondary" onClick={() => setOffset(v => v + 200)}>{t('loadMore')}</button>}</div>
  </>;
}

export function OrderDetails({ id, api, lang, user }: { id: number; api: Api; lang: Language; user: User }) {
  const t = (key: string) => translate(key, lang);
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const query = useQuery({ queryKey: ['shirinOrder', id], queryFn: () => json<Order>(api, '/orders/' + id) });
  const order = query.data;
  const manager = user.superadmin || user.permissions.includes('CAN_LOOK_ORDERS');
  async function change(values: object, link = false) {
    setBusy(true); setError(null);
    try { await json(api, '/orders/' + id + (link ? '/customer' : ''), body(values, link ? 'POST' : 'PATCH')); await queryClient.invalidateQueries({ queryKey: ['shirinOrder', id] }); await queryClient.invalidateQueries({ queryKey: ['shirinOrders'] }); await queryClient.invalidateQueries({ queryKey: ['shirinSuperadminOverview'] }); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  if (!order) return <><ErrorBox error={query.error} lang={lang} /><p>{t('loading')}</p></>;
  const customer = order.customer_snapshot;
  return <div className="order-details"><ErrorBox error={error} lang={lang} /><div className="detail-heading"><div><small>{new Date(order.created_at).toLocaleString(lang === 'ru' ? 'ru-RU' : 'uz-UZ', { timeZone: 'Asia/Tashkent' })}</small><h1>{order.number}</h1></div><span className={'badge ' + order.status}>{t(order.status)}</span></div>
    <section className="card"><div className="section-heading"><h2>{customer.name}</h2><strong>{customer.code}</strong></div><p>{t('author')}: {order.author_snapshot.name}</p><p>{customer.contact_name}<br /><a href={'tel:' + customer.phone}>{customer.phone}</a><br />{customer.address}<br />{customer.extra_contacts}</p>
      {customer.latitude != null && <p>{customer.latitude}, {customer.longitude}</p>}{customer.map_url && <a href={customer.map_url} target="_blank" rel="noreferrer">{t('map')} ↗</a>}
      {customer.photo_reference && <div className="store-photo"><Photo path={customer.photo_reference} api={api} alt={customer.name} /></div>}<p>{customer.comment}</p>
      {!order.customer_id && manager && (user.superadmin || user.permissions.includes('CAN_EDIT_MENU')) && <button className="secondary" disabled={busy} onClick={() => void change({}, true)}>{t('linkCustomer')}</button>}
    </section><section className="card">{order.lines.map(line => <div className="review-line" key={line.sku + line.sale_format}><div><strong>{line[lang === 'ru' ? 'name_ru' : 'name_uz']}</strong><p>{line.sku} · {line.quantity} {t(line.sale_format)}{line.sale_format === 'package' && ' × ' + line.units_per_package + ' ' + t('units')}<br />{money(line.price_uzs, lang)} × {line.quantity} · {line.base_units} {t('units')}</p></div><b>{money(line.amount_uzs, lang)}</b></div>)}<div className="total-row"><span>{t('total')}</span><strong>{money(order.total_uzs, lang)}</strong></div></section>
    <section className="card"><div className="section-heading"><h2>{t('payment')}</h2><span className={'badge ' + order.payment_status}>{t(order.payment_status)}</span></div>{manager && <div className="actions">
      {order.status === 'ACCEPTED' && <button disabled={busy} onClick={() => void change({ status: 'READY' })}>{t('READY')}</button>}
      {order.status === 'READY' && <button disabled={busy} onClick={() => void change({ status: 'DELIVERED' })}>{t('DELIVERED')}</button>}
      {order.payment_status === 'UNPAID' && <button className="secondary" disabled={busy} onClick={() => void change({ payment_status: 'PAID' })}>{t('PAID')}</button>}
    </div>}</section>
    <section className="card"><h2>{t('history')}</h2><div className="timeline">{order.events?.map(event => <div key={event.id}><small>{new Date(event.created_at).toLocaleString(lang === 'ru' ? 'ru-RU' : 'uz-UZ', { timeZone: 'Asia/Tashkent' })} · {event.actor_id}</small><p>{Object.entries(event.after).map(([key, value]) => [t(key), event.before[key] ? t(event.before[key]) + ' → ' : '', key === 'customer_id' ? value : t(value)].join(' ')).join(' · ')}</p></div>)}</div></section>
    {manager && <section className="card"><h2>{t('notifications')}</h2>{order.notifications?.map(n => <p key={n.id}>{t(n.state)} · {t('attempts')}: {n.attempts}{n.last_error && ' · ' + n.last_error}</p>)}</section>}
  </div>;
}

export function OrderList() {
  const { api, lang, t } = useApp();
  const navigate = useNavigate();
  return <div className="page"><h1>{t('orders')}</h1><OrderBrowser api={api} lang={lang} onSelect={id => navigate('/orders/' + id)} /></div>;
}
export function OrderDetail({ id }: { id?: number }) {
  const { orderId } = useParams();
  const { api, lang, user, t } = useApp();
  return user ? <div className="page"><Link className="back-link" to="/orders">← {t('orders')}</Link><OrderDetails id={id ?? Number(orderId)} api={api} lang={lang} user={user} /></div> : null;
}
