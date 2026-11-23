/**
 * Shared type definitions for the NFC plugin frontend.
 *
 * These interfaces describe the data exchanged with the plugin API and the
 * local agent. Keeping them in one place avoids duplicate (and drifting)
 * definitions across Panel, CreateForms, Dashboard, etc.
 */

/** Effective agent/plugin configuration (global defaults + workstation overrides). */
export interface NfcConfig {
  agent_base_url: string;
  scan_timeout_seconds: number;
  auto_redirect: boolean;
  allow_link_from_scan: boolean;
  sound_enabled: boolean;
}

/** Response from GET /tag/<uid>/ — whether a tag is linked to a stock item. */
export interface TagByStockResponse {
  found: boolean;
  uid?: string;
  stock_item_id?: number;
  linked_at?: string;
  linked_by?: string | null;
}

/** Raw result from the local agent's /scan/once endpoint. */
export interface ScanResult {
  // Agent returns { uid: "AABBCCDD" } on success, or { error: "timeout" | "no_reader" }
  uid?: string;
  error?: string;
}

/** One physical unit (stock item) as returned by the scan/find endpoints. */
export interface Tube {
  id: number;
  serial: string | null;
  batch: string | null;
  expiry_date: string | null;
  received_date: string | null;
  location: string | null;
  quantity: number;
  out_of_stock?: boolean;
  used_date?: string | null;
  container_type?: string;
  behaviour?: 'whole' | 'quantity';
  unit?: string | null;
}

/** Product (Part) information shown for a scanned unit. */
export interface PartInfo {
  part_id: number;
  part_name: string;
  part_description: string;
  total_stock: number;
  parameters: Record<string, string>;
  form?: string | null;
}

/** Full result of scanning/finding a tag: the product, the unit, and siblings. */
export interface TagLookupResult {
  found: boolean;
  uid?: string;
  part?: PartInfo;
  scanned_tube?: Tube;
  sibling_tubes?: Tube[];
  part_url?: string;
}

/** Health status reported by the local agent. */
export interface AgentHealth {
  status: 'ok' | 'unreachable';
  agent_reachable: boolean;
  reader_connected: boolean;
  readers?: string[];
}

/** A history event for a unit (creation, stock change, link, unlink). */
export interface HistoryEvent {
  type: 'created' | 'stock' | 'link' | 'unlink';
  when: string | null;
  who: string | null;
  quantity?: number | null;
  added?: number | null;
  uid?: string;
  notes?: string | null;
}

/** An option in a searchable Select (part or location). */
export interface PartOption {
  value: string;
  label: string;
}