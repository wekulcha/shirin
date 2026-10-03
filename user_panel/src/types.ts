export type Language = 'ru' | 'uz';
export type Permission = 'CAN_EDIT_MENU' | 'CAN_LOOK_ORDERS';
export interface User { id: number; username: string; permissions: Permission[]; superadmin: boolean }
export interface Product {
  id: number; sku: string; brand: string; category: string; name_ru: string; name_uz: string;
  description_ru: string | null; description_uz: string | null; volume_ml: number | null;
  sell_by_unit: boolean; sell_by_package: boolean; units_per_package: number | null;
  unit_price_uzs: string | null; package_price_uzs: string | null; is_active: boolean;
  photo_reference: string | null; version: number;
}
export interface Customer {
  id?: number; code?: string | null; name: string; contact_name?: string | null; phone: string;
  extra_contacts?: string | null; address: string; latitude?: number | null; longitude?: number | null;
  map_url?: string | null; photo_reference?: string | null; comment?: string | null; is_active?: boolean; version?: number;
}
export interface CartItem { product: Product; sale_format: 'unit' | 'package'; quantity: number }
export interface Line {
  product_id: number; sku: string; name_ru: string; name_uz: string; sale_format: 'unit' | 'package';
  units_per_package: number; quantity: number; base_units: number; price_uzs: string; amount_uzs: string;
}
export interface Quote { lines: Line[]; total_uzs: string; quote_token: string }
export interface Order {
  id: number; number: string; author_id: number; author_snapshot: { name: string; id: number }; customer_id: number | null;
  customer_snapshot: Customer; lines: Line[]; total_uzs: string; status: string; payment_status: string; created_at: string;
  events?: { id: number; actor_id: number; before: Record<string, string>; after: Record<string, string>; created_at: string }[];
  notifications?: { id: number; state: string; attempts: number; last_error: string | null }[];
}
export interface Preview {
  id: string; state: string; expires_at: string;
  payload: { counts: Record<string, number>; errors: { row: number; column: string; code: string }[];
    warnings: { row: number; column: string; code: string }[];
    changes: { row: number; sku: string; kind: string; diff: Record<string, { before: unknown; after: unknown }> }[] }
}
export type Api = (path: string, init?: RequestInit) => Promise<Response>;
