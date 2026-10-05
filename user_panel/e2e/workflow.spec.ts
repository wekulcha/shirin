import { test, expect } from '@playwright/test';
import { createHmac, randomUUID } from 'node:crypto';
import path from 'node:path';
import { loadEnv } from 'vite';

const root = path.resolve('..');
const env = loadEnv('development', root, 'SHIRIN_');
if (env.SHIRIN_ENVIRONMENT !== 'development' || env.SHIRIN_WORK_GROUP_ID !== '0') throw new Error('Browser tests require an isolated demo with notifications disabled');
const built = Boolean(process.env.SHIRIN_BUILT_PREVIEW);
const mini = 'http://localhost:' + (built ? '8093' : '5183');
const admin = 'http://localhost:' + (built ? '8094' : '5184');
const superadmin = 'http://localhost:' + (built ? '8095' : '5185');
function login(uid: number, role: 'user' | 'admin' | 'superadmin' = 'user') {
  const values: Record<string, string> = { auth_date: String(Math.floor(Date.now() / 1000)), user: JSON.stringify({ id: uid, first_name: 'Demo' }) };
  const secret = createHmac('sha256', 'WebAppData').update(env['SHIRIN_' + role.toUpperCase() + '_BOT_TOKEN']).digest();
  values.hash = createHmac('sha256', secret).update(Object.keys(values).sort().map(key => key + '=' + values[key]).join('\n')).digest('hex');
  return '#tgWebAppData=' + encodeURIComponent(new URLSearchParams(values).toString());
}

test('mobile mixed cart, selected client, confirmed point, server quote and order', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('https://telegram.org/js/telegram-web-app.js', route => route.fulfill({ contentType: 'application/javascript', body: 'window.Telegram={WebApp:{ready(){},expand(){},LocationManager:{isLocationAvailable:true,init(cb){cb()},getLocation(cb){cb({latitude:41.322,longitude:69.283})}}}};' }));
  await page.goto(mini + '/shirin/' + login(202));
  await expect(page.getByRole('heading', { name: 'Хороший вкус. Каждый день.' })).toBeVisible();
  await page.screenshot({ path: '../outputs/mobile-catalog.png', fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: 'Добавить DEMO-001 Ящик', exact: true }).click();
  await page.getByRole('button', { name: '+ DEMO-001 Ящик', exact: true }).click();
  await page.getByRole('button', { name: 'Добавить DEMO-001 Бутылка', exact: true }).click();
  await page.getByRole('button', { name: '+ DEMO-001 Бутылка', exact: true }).click();
  await page.getByRole('button', { name: '+ DEMO-001 Бутылка', exact: true }).click();
  await page.getByRole('link', { name: 'Корзина · 5' }).click();
  await expect(page.getByText('306 000 UZS', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Оформить заказ' }).click();
  await page.getByRole('textbox', { name: 'Название, код, телефон или адрес' }).fill('DEMO-STORE');
  await page.getByRole('button', { name: /Демо магазин/ }).click();
  await expect(page.getByLabel('Название магазина')).toHaveValue('Демо магазин');
  await expect(page.getByLabel('Телефон', { exact: true })).toHaveValue('+998900000001');
  await page.getByRole('button', { name: 'Моё местоположение' }).click();
  await expect(page.getByLabel('Широта')).toHaveValue('41.311');
  await page.getByRole('button', { name: 'Подтвердить эту точку магазина' }).click();
  await expect(page.getByLabel('Широта')).toHaveValue('41.322');
  await page.getByLabel('Адрес доставки').fill('Ташкент · адрес именно этой доставки');
  await page.getByRole('button', { name: 'Проверить заказ' }).click();
  await expect(page.getByText('306 000 UZS', { exact: true })).toBeVisible();
  await page.screenshot({ path: '../outputs/mobile-checkout.png', fullPage: true, animations: 'disabled' });
  const responsePromise = page.waitForResponse(response => response.url().endsWith('/shirin/api/orders') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Подтвердить заказ', exact: true }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(201);
  const order = await response.json();
  expect(order.customer_snapshot.latitude).toBe(41.322);
  expect(order.customer_snapshot.map_url).toContain('69.283%2C41.322');
  expect(order.total_uzs).toBe('306000.00');
  expect(order.customer_snapshot.photo_reference).toBeNull();
  await expect(page.getByRole('heading', { name: 'Заказ принят', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Подробнее', exact: true }).click();
  await page.reload();
  await expect(page.getByRole('heading', { name: order.number })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test('admin catalog edit, client, Excel preview and language', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 980 });
  await page.goto(admin + '/shirin/products' + login(101, 'admin'));
  await expect(page.getByRole('heading', { name: 'Товары', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Изменить', exact: true }).first().click();
  await expect(page.getByLabel('Артикул (SKU)')).toBeDisabled();
  await page.getByLabel('Цена ящика, UZS').fill('135000');
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await page.getByRole('button', { name: 'Клиенты', exact: true }).click();
  await page.getByRole('button', { name: 'Добавить клиента', exact: false }).click();
  const clientName = 'Демо клиент ' + Date.now();
  await page.getByLabel('Название магазина').fill(clientName);
  await page.getByLabel('Телефон', { exact: true }).fill('+998900000002');
  await page.getByLabel('Адрес доставки').fill('Тестовый адрес клиента');
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(page.getByText(clientName, { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Excel', exact: true }).click();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Скачать каталог', exact: false }).click();
  const download = await downloadPromise;
  const filename = await download.path();
  await page.locator('input[type=file]').setInputFiles({ name: 'shirin-catalog.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: await (await import('node:fs/promises')).readFile(filename!) });
  await expect(page.getByRole('heading', { name: 'Проверка импорта' })).toBeVisible();
  await expect(page.getByText('Без изменений', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Применить', exact: true }).click();
  await expect(page.getByText('Импорт применён', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Заказы', exact: true }).click();
  await page.screenshot({ path: '../outputs/admin-orders.png', fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: 'RU', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Buyurtmalar', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Buyurtmalar', exact: true })).toBeVisible();
});

test('nested refresh, unavailable geolocation, own draft and API 404', async ({ page, context }) => {
  await page.goto(mini + '/shirin/' + login(303));
  await expect(page.getByRole('heading', { name: 'Хороший вкус. Каждый день.' })).toBeVisible();
  await page.getByRole('button', { name: 'Добавить DEMO-003 Бутылка', exact: true }).click();
  await page.goto(mini + '/shirin/checkout');
  await expect(page.getByLabel('Название магазина')).toHaveValue('');
  await page.getByLabel('Название магазина').fill('Первый черновик');
  const other = await context.newPage();
  await other.goto(mini + '/shirin/checkout');
  await expect(other.getByLabel('Название магазина')).toHaveValue('');
  await expect(page.getByLabel('Название магазина')).toHaveValue('Первый черновик');
  const result = await page.request.get(mini + '/shirin/api/not-found');
  expect(result.status()).toBe(404);
  expect(result.headers()['content-type']).toContain('application/json');
  await page.goto(mini + '/shirin/orders'); await page.reload();
  await expect(page.getByRole('heading', { name: 'Заказы', exact: true })).toBeVisible();
});


test('independent superadmin overview, permissions, payment and logout', async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 980 });
  await page.route('https://telegram.org/js/telegram-web-app.js', route => route.fulfill({ contentType: 'application/javascript', body: '' }));
  await page.goto(superadmin + '/shirin/superadmin/' + login(101, 'superadmin'));
  await expect(page.getByRole('heading', { name: 'Обзор', exact: true })).toBeVisible();
  await expect(page.locator('.admin-heading small')).toContainText('Суперадмин Shirin');
  await expect(page.getByText('Товаров в продаже', { exact: true })).toBeVisible();
  await page.screenshot({ path: '../outputs/shirin-superadmin.png', fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: 'Доступы', exact: true }).first().click();
  await expect(page.getByLabel('202 Работа с заказами')).toBeChecked();
  const permission = page.getByLabel('202 Редактирование каталога');
  if (await permission.isChecked()) {
    await permission.click();
    await expect(permission).not.toBeChecked();
    await expect(permission).toBeEnabled();
  }
  await permission.click();
  await expect(permission).toBeChecked();
  await page.reload();
  await expect(permission).toBeChecked();
  await permission.click();
  await expect(permission).not.toBeChecked();
  await expect(permission).toBeEnabled();

  const api = 'http://localhost:8083/shirin/api';
  const auth = await request.post(api + '/auth/telegram', { data: { init_data: decodeURIComponent(login(303).split('=')[1]) } });
  const headers = { Authorization: 'Bearer ' + (await auth.json()).accessToken };
  const products = await (await request.get(api + '/products', { headers })).json();
  const product = products.find((item: { sku: string }) => item.sku === 'DEMO-003');
  const checkout = { lines: [{ product_id: product.id, sale_format: 'unit', quantity: 1 }], customer: { name: 'Проверка суперадмина', phone: '+998900000005', address: 'Тестовый адрес доставки' } };
  const quote = await (await request.post(api + '/orders/quote', { headers, data: checkout })).json();
  const response = await request.post(api + '/orders', { headers, data: { ...checkout, quote_token: quote.quote_token, attempt_key: randomUUID() } });
  expect(response.status()).toBe(201);
  const order = await response.json();
  await page.goto(superadmin + '/shirin/superadmin/orders/' + order.id);
  await expect(page.getByRole('heading', { name: order.number, exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Оплачено', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Оплачено', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Готов к доставке', exact: true }).click();
  await page.getByRole('button', { name: 'Доставлен', exact: true }).click();
  await expect(page.locator('.detail-heading').getByText('Завершён', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.locator('.detail-heading').getByText('Завершён', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Выйти', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Суперадмин Shirin', exact: true })).toBeVisible();
  await expect(page).toHaveURL(superadmin + '/shirin/superadmin/');
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Суперадмин Shirin', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Доступы', exact: true })).toHaveCount(0);
});

test('staff cannot enter independent superadmin or load its protected data', async ({ page }) => {
  const protectedCalls: string[] = [];
  page.on('request', request => { if (request.url().includes('/api/access') || request.url().includes('/superadmin/overview')) protectedCalls.push(request.url()); });
  await page.goto(superadmin + '/shirin/superadmin/access' + login(202, 'superadmin'));
  await expect(page.getByText('Недостаточно прав.', { exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox')).toHaveCount(0);
  expect(protectedCalls).toEqual([]);
  const denied = await page.request.get(superadmin + '/shirin/api/access');
  expect(denied.status()).toBe(401);
});

test('admin logout preserves the independent superadmin session on the same host', async ({ page, context }) => {
  await page.goto(admin + '/shirin/products' + login(101, 'admin'));
  await expect(page.getByRole('heading', { name: 'Товары', exact: true })).toBeVisible();
  const other = await context.newPage();
  const superadminOrigin = built ? admin : superadmin;
  await other.goto(superadminOrigin + '/shirin/superadmin/' + login(101, 'superadmin'));
  await expect(other.getByRole('heading', { name: 'Обзор', exact: true })).toBeVisible();
  const cookies = await context.cookies();
  expect(cookies.some(cookie => cookie.name === 'shirin_admin_refresh_token')).toBe(true);
  expect(cookies.some(cookie => cookie.name === 'shirin_superadmin_refresh_token')).toBe(true);
  await page.getByRole('button', { name: 'Выйти', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Админка Shirin', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Админка Shirin', exact: true })).toBeVisible();
  await other.reload();
  await expect(other.getByRole('heading', { name: 'Обзор', exact: true })).toBeVisible();
});
