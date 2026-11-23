/**
 * Communication with the LOCAL NFC agent.
 *
 * The agent runs on the workstation and is reached at its own base URL
 * (per-workstation, from agentConfig). These functions talk directly to the
 * agent's HTTP API (/health and /scan/once) — NOT to the InvenTree server.
 *
 * Shared by Panel, Dashboard and CreateForms so the scan/health logic exists
 * in exactly one place.
 */

import type { AgentHealth, ScanResult } from './types';

/** Error thrown by scanOnce, carrying a machine-readable `code`. */
export class AgentScanError extends Error {
  code: string;

  constructor(code: string, message?: string) {
    super(message ?? code);
    this.code = code;
  }
}

/** Query the agent's /health endpoint. Never throws — returns an unreachable status on failure. */
export async function getAgentHealth(agentBaseUrl: string): Promise<AgentHealth> {
  try {
    const res = await fetch(`${agentBaseUrl}/health`);

    if (!res.ok) {
      return {
        status: 'unreachable',
        agent_reachable: false,
        reader_connected: false,
        readers: []
      };
    }

    const data = await res.json();

    return {
      status: 'ok',
      agent_reachable: true,
      reader_connected: !!data.reader_connected,
      readers: Array.isArray(data.readers) ? data.readers : []
    };
  } catch {
    return {
      status: 'unreachable',
      agent_reachable: false,
      reader_connected: false,
      readers: []
    };
  }
}

/** Convenience: is a reader currently connected? */
export async function getReaderConnected(agentBaseUrl: string): Promise<boolean> {
  const health = await getAgentHealth(agentBaseUrl);
  return health.reader_connected;
}

/**
 * Ask the agent to wait for a single tag and return its UID.
 * Throws AgentScanError with a code ('timeout', 'no_reader', 'client_timeout',
 * 'network_error', ...) on failure.
 */
export async function scanOnce(
  agentBaseUrl: string,
  timeoutSeconds: number
): Promise<string> {
  const controller = new AbortController();

  const timer = window.setTimeout(
    () => {
      controller.abort();
    },
    (timeoutSeconds + 2) * 1000
  );

  try {
    const res = await fetch(`${agentBaseUrl}/scan/once`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ timeout: timeoutSeconds }),
      signal: controller.signal
    });

    const data: ScanResult = await res.json().catch(() => ({}));

    if (res.ok && data.uid) {
      return data.uid;
    }

    throw new AgentScanError(data.error ?? `http_${res.status}`);
  } catch (err: any) {
    if (err?.name === 'AbortError') {
      throw new AgentScanError('client_timeout');
    }

    if (err instanceof AgentScanError) {
      throw err;
    }

    throw new AgentScanError('network_error');
  } finally {
    clearTimeout(timer);
  }
}