import type { Customer } from './types';
export function customerBody(customer: Customer): Customer {
  const fields: (keyof Customer)[] = ['code', 'name', 'contact_name', 'phone', 'extra_contacts', 'address', 'latitude', 'longitude', 'map_url', 'photo_reference', 'comment', 'is_active'];
  return Object.fromEntries(fields.filter(key => customer[key] !== undefined).map(key => [key, customer[key] === '' && !['name', 'phone', 'address'].includes(key) ? null : customer[key]])) as unknown as Customer;
}
