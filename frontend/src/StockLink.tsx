import { getDetailUrl, ModelType } from '@inventreedb/ui';
import { t } from '@lingui/core/macro';
import { Button, Group, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconCheck, IconCopy } from '@tabler/icons-react';
import { useEffect, useState } from 'react';

/** Delay (ms) during which the button shows the "copied" state. */
const COPIED_FEEDBACK_MS = 2000;

/**
 * Build the absolute web UI URL of a stock item, e.g.
 * https://inventree.example.org/web/stock/item/8/
 */
export function stockItemUrl(stockItemId: number): string {
  return `${window.location.origin}${getDetailUrl(ModelType.stockitem, stockItemId, true)}`;
}

/**
 * Copy text with the textarea + execCommand fallback, used when the
 * asynchronous Clipboard API is unavailable (non secure context).
 */
function copyWithFallback(text: string): boolean {
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  try {
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    document.body.removeChild(area);
  }
}

/** Copy text to the clipboard, resolving to true on success. */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      return copyWithFallback(text);
    }
  }
  return copyWithFallback(text);
}

/**
 * Read-only field showing the link to a stock item, with a "Copy" button.
 */
export function StockItemLink({ stockItemId }: { stockItemId: number }) {
  const url = stockItemUrl(stockItemId);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), COPIED_FEEDBACK_MS);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function handleCopy() {
    if (await copyToClipboard(url)) {
      setCopied(true);
    } else {
      notifications.show({
        title: t`Copy failed`,
        message: t`Select the link and copy it manually.`,
        color: 'red'
      });
    }
  }

  return (
    <Group gap='xs' wrap='nowrap' align='end'>
      <TextInput
        size='xs'
        label={t`Stock link`}
        value={url}
        readOnly
        onFocus={(e) => e.currentTarget.select()}
        style={{ flex: 1, minWidth: 0 }}
      />
      <Button
        size='xs'
        variant='light'
        color={copied ? 'teal' : 'gray'}
        leftSection={copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
        onClick={handleCopy}
      >
        {copied ? t`Copied` : t`Copy`}
      </Button>
    </Group>
  );
}
