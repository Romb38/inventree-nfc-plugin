/**
 * Shared React hooks for the NFC plugin.
 */

import type { InvenTreePluginContext } from '@inventreedb/ui';
import { useCallback, useEffect, useRef, useState } from 'react';
import { getEffectiveConfig } from './agentConfig';
import { cancelScan, getReaderConnected, scanOnce } from './agent';

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
/**
 * Start and stop scans on the local agent.
 *
 * `start` resolves with the scanned UID, or null when the scan was stopped by
 * the user (no error to report). Other failures reject with an AgentScanError.
 * `stop` aborts the browser request and asks the agent to cancel its scan.
 * Starting a new scan stops the previous one first.
 */
export function useAgentScan(): {
  scanning: boolean;
  start: (agentBaseUrl: string, timeoutSeconds: number) => Promise<string | null>;
  stop: () => void;
} {
  const [scanning, setScanning] = useState(false);
  const current = useRef<{ controller: AbortController; url: string } | null>(null);

  const stop = useCallback(() => {
    const active = current.current;
    if (!active) return;
    current.current = null;
    active.controller.abort();
    cancelScan(active.url);
  }, []);

  const start = useCallback(
    async (agentBaseUrl: string, timeoutSeconds: number) => {
      stop();
      const controller = new AbortController();
      const handle = { controller, url: agentBaseUrl };
      current.current = handle;
      setScanning(true);
      try {
        return await scanOnce(agentBaseUrl, timeoutSeconds, controller.signal);
      } catch (err: any) {
        if (err?.code === 'cancelled') return null;
        throw err;
      } finally {
        if (current.current === handle) current.current = null;
        if (current.current === null) setScanning(false);
      }
    },
    [stop]
  );

  useEffect(() => stop, [stop]);

  return { scanning, start, stop };
}
