/**
 * Per-workstation NFC agent configuration.
 *
 * The agent runs locally on each workstation and can be configured differently
 * per machine (different port, different scan timeout). Because this is a
 * property of the MACHINE (not the user account, not the server), it is stored
 * in the browser's localStorage on that workstation.
 *
 * Resolution order for each field:
 *   1. Per-workstation override (localStorage), if set
 *   2. Global InvenTree plugin config (fallback / default)
 */

export interface AgentConfig {
  agent_base_url: string;
  scan_timeout_seconds: number;
  sound_enabled: boolean;
  auto_redirect: boolean;
  allow_link_from_scan: boolean;
}

const LS_URL = 'nfc.workstation.agent_base_url';
const LS_TIMEOUT = 'nfc.workstation.scan_timeout_seconds';

export interface WorkstationOverrides {
  agent_base_url: string | null;
  scan_timeout_seconds: number | null;
}

/** Read the per-workstation overrides from localStorage (safe if unavailable). */
export function readWorkstationOverrides(): WorkstationOverrides {
  try {
    const url = localStorage.getItem(LS_URL);
    const timeoutRaw = localStorage.getItem(LS_TIMEOUT);
    const timeout = timeoutRaw != null ? parseInt(timeoutRaw, 10) : null;
    return {
      agent_base_url: url && url.trim() ? url.trim() : null,
      scan_timeout_seconds:
        timeout != null && !Number.isNaN(timeout) ? timeout : null
    };
  } catch {
    return { agent_base_url: null, scan_timeout_seconds: null };
  }
}

/** Save (or clear) per-workstation overrides. Pass null/'' to clear a field. */
export function writeWorkstationOverrides(o: WorkstationOverrides): void {
  try {
    if (o.agent_base_url && o.agent_base_url.trim()) {
      localStorage.setItem(LS_URL, o.agent_base_url.trim());
    } else {
      localStorage.removeItem(LS_URL);
    }
    if (o.scan_timeout_seconds != null && !Number.isNaN(o.scan_timeout_seconds)) {
      localStorage.setItem(LS_TIMEOUT, String(o.scan_timeout_seconds));
    } else {
      localStorage.removeItem(LS_TIMEOUT);
    }
  } catch {
    /* localStorage unavailable — overrides simply won't persist */
  }
}

/**
 * Fetch the effective agent config: global plugin config with any
 * per-workstation overrides applied on top.
 */
export async function getEffectiveConfig(api: any): Promise<AgentConfig> {
  const r = await api.get('/plugin/nfc/config/');
  const base = r.data;
  const ov = readWorkstationOverrides();
  return {
    ...base,
    agent_base_url: ov.agent_base_url ?? base.agent_base_url,
    scan_timeout_seconds: ov.scan_timeout_seconds ?? base.scan_timeout_seconds,
  };
}