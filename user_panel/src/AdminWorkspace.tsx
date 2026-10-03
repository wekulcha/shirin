import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { body, json } from './state';
import { CustomerFields, Empty, ErrorBox, Field, Photo } from './Controls';
import { customerBody } from './customer';
import { money, translate } from './i18n';
import { OrderBrowser, OrderDetails } from './Orders';
import type { Api, Customer, Language, Permission, Preview, Product, User } from './types';

interface Props { api: Api; user: User; lang: Language; setLang: (value: Language) => void; section?: string; entityId?: string; navigate: (section: string, id?: string) => void }
const productFields = ['sku', 'brand', 'category', 'name_ru', 'name_uz', 'description_ru', 'description_uz', 'volume_ml', 'sell_by_unit', 'sell_by_package', 'units_per_package', 'unit_price_uzs', 'package_price_uzs', 'is_active'] as const;
const blankProduct = (): Product => ({ id: 0, sku: '', brand: 'Ширин', category: '', name_ru: '', name_uz: '', description_ru: null, description_uz: null, volume_ml: null, sell_by_unit: true, sell_by_package: false, units_per_package: null, unit_price_uzs: null, package_price_uzs: null, is_active: true, photo_reference: null, version: 1 });

export function AdminWorkspace({ api, user, lang, setLang, section = 'orders', entityId, navigate }: Props) {
  const t = (key: string) => translate(key, lang);
  const editor = user.superadmin || user.permissions.includes('CAN_EDIT_MENU');
  const manager = user.superadmin || user.permissions.includes('CAN_LOOK_ORDERS');
  const tabs = [...(manager ? ['orders'] : []), ...(editor ? ['products', 'customers', 'import'] : []), ...(user.superadmin ? ['access'] : []), 'settings'];
  const current = tabs.includes(section) ? section : tabs[0];
  if (!editor && !manager) return <Empty title={t('readOnly')} />;
  return <div className="shirin-admin"><div className="admin-heading"><div className="brand"><span className="brand-mark">S</span><span>{t('title')}<small>{t('admin')} · UZS</small></span></div><div className="admin-user">{user.username}<button className="language" onClick={() => setLang(lang === 'ru' ? 'uz' : 'ru')}>{lang.toUpperCase()}</button></div></div>
    <div className="admin-layout"><nav className="admin-nav">{tabs.map(tab => <button key={tab} className={current === tab ? 'selected' : ''} onClick={() => navigate(tab)}>{t(tab)}</button>)}</nav><div className="admin-main">
      {current === 'orders' && (entityId ? <><button className="text-button" onClick={() => navigate('orders')}>← {t('orders')}</button><OrderDetails id={Number(entityId)} api={api} lang={lang} user={user} /></> : <><h1>{t('orders')}</h1><OrderBrowser api={api} lang={lang} onSelect={id => navigate('orders', String(id))} /></>)}
      {current === 'products' && <Products api={api} lang={lang} />}
      {current === 'customers' && <Customers api={api} lang={lang} />}
      {current === 'import' && <Excel api={api} lang={lang} previewId={entityId} onPreview={id => navigate('import', id)} />}
      {current === 'access' && <Access api={api} lang={lang} />}
      {current === 'settings' && <Settings api={api} lang={lang} />}
    </div></div></div>;
}

function Products({ api, lang }: { api: Api; lang: Language }) {
  const t = (key: string) => translate(key, lang);
  const queryClient = useQueryClient();
  const [q, setQ] = useState('');
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<Product | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const query = useQuery({ queryKey: ['shirinAdminProducts', q, offset], queryFn: () => json<Product[]>(api, '/products?admin=true&q=' + encodeURIComponent(q) + '&offset=' + offset) });
  async function save(event: React.FormEvent) {
    event.preventDefault(); if (!editing) return; setBusy(true); setError(null);
    try {
      const values = Object.fromEntries(productFields.map(key => [key, editing[key] === '' && !['sku', 'category', 'name_ru', 'name_uz', 'brand'].includes(key) ? null : editing[key]]));
      await json<Product>(api, '/products' + (editing.id ? '/' + editing.id : ''), body(editing.id ? { ...values, version: editing.version } : values, editing.id ? 'PUT' : 'POST'));
      setEditing(null); await queryClient.invalidateQueries({ queryKey: ['shirinAdminProducts'] }); await queryClient.invalidateQueries({ queryKey: ['products'] });
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function photo(file?: File) {
    if (!file || !editing?.id) return; setBusy(true); setError(null);
    try { const form = new FormData(); form.append('file', file); setEditing(await json<Product>(api, '/products/' + editing.id + '/photo', { method: 'POST', body: form })); await queryClient.invalidateQueries({ queryKey: ['shirinAdminProducts'] }); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <><div className="section-heading"><h1>{t('products')}</h1><button onClick={() => { setEditing(blankProduct()); setError(null); }}>{t('createProduct')} +</button></div><ErrorBox error={error || query.error} lang={lang} />
    {editing ? <section className="card"><form onSubmit={save}><div className="form-grid">
      <Field label={t('sku')} value={editing.sku} required disabled={Boolean(editing.id)} onChange={v => setEditing({ ...editing, sku: v })} />
      <label className="field"><span>{t('brand')}</span><select value={editing.brand} onChange={e => setEditing({ ...editing, brand: e.target.value })}><option>Ширин</option><option>Сады Востока</option></select></label>
      {(['category', 'name_ru', 'name_uz', 'description_ru', 'description_uz'] as const).map(key => <Field key={key} label={t(key)} value={editing[key]} required={['category', 'name_ru', 'name_uz'].includes(key)} onChange={v => setEditing({ ...editing, [key]: v })} />)}
      <Field label={t('volume_ml')} value={editing.volume_ml} type="number" min={1} step="1" onChange={v => setEditing({ ...editing, volume_ml: v ? Number(v) : null })} />
    </div><div className="sale-editor">{(['sell_by_unit', 'sell_by_package'] as const).map(key => <label className="checkbox" key={key}><input type="checkbox" checked={editing[key]} onChange={e => setEditing({ ...editing, [key]: e.target.checked })} />{t(key)}</label>)}
      <div className="form-grid"><Field label={t('unit_price_uzs')} value={editing.unit_price_uzs} type="number" min={0} step="0.01" required={editing.sell_by_unit} disabled={!editing.sell_by_unit} onChange={v => setEditing({ ...editing, unit_price_uzs: v || null })} />
        <Field label={t('units_per_package')} value={editing.units_per_package} type="number" min={1} step="1" required={editing.sell_by_package} disabled={!editing.sell_by_package} onChange={v => setEditing({ ...editing, units_per_package: v ? Number(v) : null })} />
        <Field label={t('package_price_uzs')} value={editing.package_price_uzs} type="number" min={0} step="0.01" required={editing.sell_by_package} disabled={!editing.sell_by_package} onChange={v => setEditing({ ...editing, package_price_uzs: v || null })} />
      </div><p className="hint">{t('packageHint')}</p></div><label className="checkbox"><input type="checkbox" checked={editing.is_active} onChange={e => setEditing({ ...editing, is_active: e.target.checked })} />{t('active')}</label>
      <div className="actions"><button disabled={busy}>{busy ? t('loading') : t('save')}</button><button type="button" className="secondary" onClick={() => setEditing(null)}>{t('cancel')}</button></div>
    </form>{editing.id > 0 && <div className="product-photo-edit"><h3>{t('productPhoto')}</h3><Photo key={editing.photo_reference} path={editing.photo_reference} api={api} alt={editing.name_ru} /><label className="file-button">{t('productPhoto')}<input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={e => void photo(e.target.files?.[0])} /></label></div>}</section> : <>
      <input value={q} onChange={e => { setQ(e.target.value); setOffset(0); }} placeholder={t('search')} aria-label={t('search')} />
      <div className="table-scroll"><table><thead><tr><th>{t('products')}</th><th>{t('brand')}</th><th>{t('unit')}</th><th>{t('package')}</th><th>{t('status')}</th><th /></tr></thead><tbody>{query.data?.map(p => <tr key={p.id}><td><strong>{p[lang === 'ru' ? 'name_ru' : 'name_uz']}</strong><small>{p.sku} · {p.category}</small></td><td>{p.brand}</td><td>{p.sell_by_unit ? money(p.unit_price_uzs!, lang) : '—'}</td><td>{p.sell_by_package ? <>{money(p.package_price_uzs!, lang)}<small>× {p.units_per_package}</small></> : '—'}</td><td><span className="badge">{t(p.is_active ? 'active' : 'archived')}</span></td><td><button className="secondary" onClick={() => { setEditing(p); setError(null); }}>{t('edit')}</button></td></tr>)}</tbody></table></div>
      {query.isLoading && <p>{t('loading')}</p>}{query.data?.length === 0 && <Empty title={t('emptyCatalog')} />}<Pagination offset={offset} setOffset={setOffset} count={query.data?.length ?? 0} lang={lang} />
    </>}
  </>;
}

function Pagination({ offset, setOffset, count, lang }: { offset: number; setOffset: (value: number) => void; count: number; lang: Language }) {
  return <div className="actions">{offset > 0 && <button className="secondary" onClick={() => setOffset(Math.max(0, offset - 200))}>{translate('back', lang)}</button>}{count === 200 && <button className="secondary" onClick={() => setOffset(offset + 200)}>{translate('loadMore', lang)}</button>}</div>;
}

function Customers({ api, lang }: { api: Api; lang: Language }) {
  const t = (key: string) => translate(key, lang);
  const queryClient = useQueryClient();
  const [q, setQ] = useState('');
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<Customer | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const query = useQuery({ queryKey: ['shirinAdminCustomers', q, offset], queryFn: () => json<Customer[]>(api, '/customers?admin=true&q=' + encodeURIComponent(q) + '&offset=' + offset) });
  async function save(event: React.FormEvent) {
    event.preventDefault(); if (!editing) return; setBusy(true); setError(null);
    try { await json(api, '/customers' + (editing.id ? '/' + editing.id : ''), body({ ...customerBody(editing), ...(editing.id ? { version: editing.version } : {}) }, editing.id ? 'PUT' : 'POST')); setEditing(null); await queryClient.invalidateQueries({ queryKey: ['shirinAdminCustomers'] }); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function photo(file?: File) {
    if (!file || !editing) return; setBusy(true); setError(null);
    try { const form = new FormData(); form.append('file', file); const data = await json<{ path: string }>(api, '/media/upload?kind=store', { method: 'POST', body: form }); setEditing({ ...editing, photo_reference: data.path }); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  const duplicate = editing && query.data?.some(c => c.id !== editing.id && c.phone.replace(/\D/g, '') === editing.phone.replace(/\D/g, '') && editing.phone.length > 6);
  return <><div className="section-heading"><h1>{t('customers')}</h1><button onClick={() => { setEditing({ name: '', phone: '', address: '', is_active: true }); setError(null); }}>{t('createCustomer')} +</button></div><ErrorBox error={error || query.error} lang={lang} />
    {editing ? <section className="card"><form onSubmit={save}><CustomerFields value={editing} onChange={setEditing} lang={lang} />{duplicate && <p className="alert">{t('duplicateHint')}</p>}<label className="checkbox"><input type="checkbox" checked={editing.is_active ?? true} onChange={e => setEditing({ ...editing, is_active: e.target.checked })} />{t('active')}</label>
      <label className="file-button">{t('photo')}<input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={e => void photo(e.target.files?.[0])} /></label>{editing.photo_reference && <div className="store-photo"><Photo path={editing.photo_reference} api={api} alt={editing.name} /></div>}
      <div className="actions"><button disabled={busy}>{busy ? t('loading') : t('save')}</button><button type="button" className="secondary" onClick={() => setEditing(null)}>{t('cancel')}</button></div></form></section> : <>
      <input aria-label={t('storeSearch')} placeholder={t('storeSearch')} value={q} onChange={e => { setQ(e.target.value); setOffset(0); }} />
      <div className="table-scroll"><table><thead><tr><th>{t('store')}</th><th>{t('phone')}</th><th>{t('address')}</th><th>{t('status')}</th><th /></tr></thead><tbody>{query.data?.map(c => <tr key={c.id}><td><strong>{c.name}</strong><small>{c.code} · {c.contact_name}</small></td><td>{c.phone}</td><td>{c.address}</td><td>{t(c.is_active ? 'active' : 'archived')}</td><td><button className="secondary" onClick={() => { setEditing(c); setError(null); }}>{t('edit')}</button></td></tr>)}</tbody></table></div>
      {query.isLoading && <p>{t('loading')}</p>}{query.data?.length === 0 && <Empty title={t('emptyCustomers')} />}<Pagination offset={offset} setOffset={setOffset} count={query.data?.length ?? 0} lang={lang} />
    </>}
  </>;
}

function Excel({ api, lang, previewId, onPreview }: { api: Api; lang: Language; previewId?: string; onPreview: (id?: string) => void }) {
  const t = (key: string) => translate(key, lang);
  const queryClient = useQueryClient();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const preview = useQuery({ queryKey: ['shirinPreview', previewId], queryFn: () => json<Preview>(api, '/catalog/previews/' + previewId), enabled: Boolean(previewId) });
  const logs = useQuery({ queryKey: ['shirinImportLogs'], queryFn: () => json<{ id: number; actor_id: number; created_at: string; summary: Record<string, number> }[]>(api, '/catalog/logs') });
  async function download(template: boolean) {
    setBusy(true); setError(null);
    try { const response = await api('/catalog/export?template=' + template); if (!response.ok) throw new Error('error'); const blob = await response.blob(); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = template ? 'shirin-template.xlsx' : 'shirin-catalog.xlsx'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 5000); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function upload(file?: File) {
    if (!file) return; setBusy(true); setError(null);
    try { const form = new FormData(); form.append('file', file); const result = await json<Preview>(api, '/catalog/preview', { method: 'POST', body: form }); onPreview(result.id); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function apply(cancel = false) {
    setBusy(true); setError(null);
    try { await json(api, '/catalog/previews/' + previewId + (cancel ? '/cancel' : '/apply'), { method: 'POST' }); await queryClient.invalidateQueries({ queryKey: ['shirinPreview'] }); await queryClient.invalidateQueries({ queryKey: ['shirinImportLogs'] }); await queryClient.invalidateQueries({ queryKey: ['shirinAdminProducts'] }); await queryClient.invalidateQueries({ queryKey: ['products'] }); if (cancel) onPreview(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  const data = preview.data;
  return <><h1>{t('import')}</h1><section className="card"><p>{t('importHint')}</p><div className="actions"><button className="secondary" disabled={busy} onClick={() => void download(false)}>{t('export')} ↓</button><button className="secondary" disabled={busy} onClick={() => void download(true)}>{t('template')} ↓</button><label className="file-button">{t('uploadExcel')}<input type="file" accept=".xlsx" disabled={busy} onChange={e => void upload(e.target.files?.[0])} /></label></div></section><ErrorBox error={error || preview.error} lang={lang} />
    {data && <section className="card"><div className="section-heading"><h2>{t('preview')}</h2><span className="badge">{data.state === 'APPLIED' ? t('applied') : new Date(data.expires_at).toLocaleString()}</span></div><div className="metrics">{Object.entries(data.payload.counts).map(([key, value]) => <div key={key}><strong>{value}</strong><span>{t(key)}</span></div>)}</div>
      {data.payload.errors.length > 0 && <><h3>{t('errors')}</h3>{data.payload.errors.map((e, i) => <p className="alert" key={i}>{t('row')} {e.row} · {e.column}: {t(e.code)}</p>)}</>}
      {data.payload.warnings.map((e, i) => <p className="warning" key={i}>{t('row')} {e.row} · {e.column}: {t(e.code)}</p>)}
      <div className="table-scroll"><table><thead><tr><th>SKU</th><th>{t('field')}</th><th>{t('before')}</th><th>{t('after')}</th></tr></thead><tbody>{data.payload.changes.flatMap(c => Object.entries(c.diff).map(([key, change]) => <tr key={c.row + key}><td>{c.sku}<small>{t('row')} {c.row}</small></td><td>{t(key)}</td><td>{String(change.before ?? '—')}</td><td>{String(change.after ?? '—')}</td></tr>))}</tbody></table></div>
      {data.state === 'PENDING' && <div className="actions"><button disabled={busy || data.payload.errors.length > 0 || new Date(data.expires_at).getTime() < Date.now()} onClick={() => void apply()}>{t('apply')}</button><button className="secondary" disabled={busy} onClick={() => void apply(true)}>{t('cancel')}</button></div>}
    </section>}<section className="card"><h2>{t('importLog')}</h2><ErrorBox error={logs.error} lang={lang} />{logs.data?.map(log => <p key={log.id}>{new Date(log.created_at).toLocaleString()} · {log.actor_id} · {Object.entries(log.summary).map(([key, value]) => t(key) + ': ' + value).join(' · ')}</p>)}</section>
  </>;
}

function Access({ api, lang }: { api: Api; lang: Language }) {
  const t = (key: string) => translate(key, lang);
  const queryClient = useQueryClient();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const query = useQuery({ queryKey: ['shirinAccess'], queryFn: () => json<(User & { is_active: boolean })[]>(api, '/access') });
  async function change(user: User, permission: Permission, checked: boolean) {
    setBusy(true); setError(null);
    try { await json(api, '/access', body({ user_id: user.id, permissions: checked ? [...user.permissions, permission] : user.permissions.filter(p => p !== permission) }, 'PUT')); await queryClient.invalidateQueries({ queryKey: ['shirinAccess'] }); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <><h1>{t('access')}</h1><ErrorBox error={error || query.error} lang={lang} /><div className="table-scroll"><table><thead><tr><th>{t('userId')}</th><th>{t('user_name')}</th><th>{t('menuPermission')}</th><th>{t('orderPermission')}</th></tr></thead><tbody>{query.data?.map(user => <tr key={user.id}><td>{user.id}</td><td>{user.username}</td>{(['CAN_EDIT_MENU', 'CAN_LOOK_ORDERS'] as const).map(permission => <td key={permission}><input aria-label={user.id + ' ' + t(permission)} type="checkbox" checked={user.permissions.includes(permission)} disabled={busy} onChange={e => void change(user, permission, e.target.checked)} /></td>)}</tr>)}</tbody></table></div></>;
}

function Settings({ api, lang }: { api: Api; lang: Language }) {
  const t = (key: string) => translate(key, lang);
  const query = useQuery({ queryKey: ['shirinSettings'], queryFn: () => json<Record<string, string | number | boolean>>(api, '/settings') });
  return <><h1>{t('settings')}</h1><ErrorBox error={query.error} lang={lang} /><section className="card"><dl>{query.data && ['currency', 'timezone', 'bot_configured', 'group_configured', 'integration_configured'].map(key => <div className="settings-row" key={key}><dt>{t(key)}</dt><dd>{typeof query.data[key] === 'boolean' ? t(query.data[key] ? 'yes' : 'no') : String(query.data[key])}</dd></div>)}</dl></section></>;
}
