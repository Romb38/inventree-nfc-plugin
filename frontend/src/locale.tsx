import type { InvenTreePluginContext } from '@inventreedb/ui';
import { I18nProvider } from '@lingui/react';
import { useEffect, useState } from 'react';

// Vite resolves this glob at build time — every messages file in locales/
// is automatically included in the bundle. Adding a new language = zero code changes.
const catalogs = import.meta.glob('./locales/*/messages.ts', { eager: true });

function resolveLocaleKey(locale: string): string | null {
  // Return the catalog key that actually exists for this locale.
  if (catalogs[`./locales/${locale}/messages.ts`]) return locale;
  const base = locale.split(/[-_]/)[0];
  if (catalogs[`./locales/${base}/messages.ts`]) return base;
  return null;
}

function getCatalog(localeKey: string): any {
  const mod = catalogs[`./locales/${localeKey}/messages.ts`] as any;
  return mod?.messages ?? mod?.default ?? mod ?? {};
}

export function LocalizedComponent({
  locale,
  children,
  context
}: {
  locale: string;
  children: React.ReactNode;
  context: InvenTreePluginContext;
}) {
  const [loadedFor, setLoadedFor] = useState<string | null>(null);

  useEffect(() => {
    if (!locale) return;

    // Never load the pseudo test locale in production UI.
    const requested = locale === 'pseudo-LOCALE' ? 'en' : locale;

    const key = resolveLocaleKey(requested) ?? 'en';
    const catalog = getCatalog(key);

    // Load our catalog under the requested locale key, then activate it so
    // the plugin renders in that language regardless of i18n's prior state.
    context.i18n.load(requested, {
      ...((context.i18n as any)._messages?.[requested] ?? {}),
      ...catalog
    });
    context.i18n.activate(requested);

    setLoadedFor(locale);
  }, [locale, context.i18n]);

  // Re-block briefly on each language change so stale text is never shown.
  if (loadedFor !== locale) return null;

  return <I18nProvider i18n={context.i18n}>{children}</I18nProvider>;
}
