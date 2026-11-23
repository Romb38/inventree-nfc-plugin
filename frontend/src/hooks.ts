/**
 * Shared React hooks for the NFC plugin.
 */

import type { InvenTreePluginContext } from '@inventreedb/ui';
import { useEffect, useState } from 'react';
import { getEffectiveConfig } from './agentConfig';
import { getReaderConnected } from './agent';

/**
 * Poll the local agent every 5s and report whether a reader is connected.
 * Returns: true (connected), false (not), or null (still checking).
 * The agent URL is resolved once from the effective (per-workstation) config.
 */
export function useReaderStatus(
  context: InvenTreePluginContext
): boolean | null {
  const [connected, setConnected] = useState<boolean | null>(null);

  useEffect(() => {
    let active = true;
    let timer: number;
    let agentUrl: string | null = null;

    async function poll() {
      try {
        if (!agentUrl) {
          const cfg = await getEffectiveConfig(context.api);
          agentUrl = cfg.agent_base_url;
        }
        const ok = await getReaderConnected(agentUrl!);
        if (active) setConnected(ok);
      } catch {
        if (active) setConnected(false);
      }
      if (active) timer = window.setTimeout(poll, 5000);
    }

    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [context.api]);

  return connected;
}