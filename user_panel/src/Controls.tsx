import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import type { Api, Customer, Language } from './types';
import { translate } from './i18n';

export function Field({ label, value, onChange, type = 'text', required = false, disabled = false, min, max, step }: {
  label: string; value?: string | number | null; onChange: (value: string) => void; type?: string;
  required?: boolean; disabled?: boolean; min?: number; max?: number; step?: string;
}) {
  return <label className="field"><span>{label}{required && ' *'}</span><input aria-label={label} value={value ?? ''} onChange={e => onChange(e.target.value)} type={type} required={required} disabled={disabled} min={min} max={max} step={step} /></label>;
}
export function ErrorBox({ error, lang }: { error: unknown; lang: Language }) {
  if (!error) return null;
  return <div role="alert" className="alert">{translate(error instanceof Error ? error.message : String(error), lang)}</div>;
}
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><span className="empty-symbol">◌</span><h2>{title}</h2>{children}</div>;
}
export function Photo({ path, api, alt }: { path?: string | null; api: Api; alt: string }) {
  const [source, setSource] = useState('');
  useEffect(() => {
    let cancelled = false;
    let objectUrl = '';
    if (!path) return;
    const promise = path.startsWith('/shirin/api/') ? api(path.replace('/shirin/api', '')) : fetch(path);
    void promise.then(async response => {
      if (!response.ok) return;
      const blob = await response.blob();
      if (!cancelled) { objectUrl = URL.createObjectURL(blob); setSource(objectUrl); }
    }).catch(() => undefined);
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [path, api]);
  return source ? <img className="photo" src={source} alt={alt} /> : <div className="bottle-placeholder" aria-label={alt}>
    <svg viewBox="0 0 100 160" aria-hidden="true"><path d="M39 12h22v25c0 10 14 17 14 33v66c0 9-7 15-15 15H40c-8 0-15-6-15-15V70c0-16 14-23 14-33Z" fill="currentColor" opacity=".16"/><rect x="36" y="8" width="28" height="10" rx="3" fill="currentColor"/><rect x="30" y="73" width="40" height="46" rx="6" fill="currentColor" opacity=".5"/><path d="M50 82c-15 8-14 25 0 27 14-2 15-19 0-27Z" fill="#fff8e9"/></svg>
  </div>;
}
export function CustomerFields({ value, onChange, lang }: { value: Customer; onChange: (value: Customer) => void; lang: Language }) {
  const t = (key: string) => translate(key, lang);
  const change = (key: keyof Customer, next: string) => onChange({ ...value, [key]: ['latitude', 'longitude'].includes(key) ? next === '' ? null : Number(next) : next });
  return <div className="form-grid">
    {['name', 'code', 'contact_name', 'phone', 'address', 'extra_contacts'].map(key => <Field key={key} label={t(key)} value={value[key as keyof Customer] as string} onChange={v => change(key as keyof Customer, v)} required={['name', 'phone', 'address'].includes(key)} type={key === 'phone' ? 'tel' : 'text'} />)}
    <Field label={t('latitude')} value={value.latitude} onChange={v => change('latitude', v)} type="number" min={-90} max={90} step="any" />
    <Field label={t('longitude')} value={value.longitude} onChange={v => change('longitude', v)} type="number" min={-180} max={180} step="any" />
    <Field label={t('map_url')} value={value.map_url} onChange={v => change('map_url', v)} type="url" />
    <Field label={t('comment')} value={value.comment} onChange={v => change('comment', v)} />
  </div>;
}
