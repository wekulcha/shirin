// Run from shirin. Copies only the management module; scopes every CSS rule.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../user_panel/package.json', import.meta.url));
const postcss = require('postcss');
const project = path.resolve(new URL('..', import.meta.url).pathname);
const destination = path.resolve(process.argv[2] || '../market-shirin-integration/superadmin_panel/src/shirin');
await fs.mkdir(destination, { recursive: true });
for (const name of ['AdminWorkspace.tsx', 'Controls.tsx', 'Orders.tsx', 'i18n.ts', 'types.ts', 'state.ts', 'customer.ts']) {
  await fs.copyFile(path.join(project, 'user_panel/src', name), path.join(destination, name));
}
const css = postcss.parse(await fs.readFile(path.join(project, 'user_panel/src/style.css'), 'utf8'));
css.walkRules(rule => {
  rule.selectors = rule.selectors.map(selector => selector === ':root' || selector === 'body' ? '.shirin-admin' : selector.startsWith('.shirin-admin') || selector.startsWith('.admin-') ? '.shirin-admin ' + selector : '.shirin-admin ' + selector);
  if (rule.selector === '.shirin-admin .shirin-admin') rule.selector = '.shirin-admin';
});
await fs.writeFile(path.join(destination, 'style.css'), css.toString());
console.log('Shirin management module copied with scoped styles.');
