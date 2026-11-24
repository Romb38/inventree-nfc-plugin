/**
 * Centralized plugin API calls.
 *
 * All requests to the NFC plugin's own endpoints (and the couple of InvenTree
 * core endpoints we use) live here, so URLs and response shapes are defined
 * once. Each function takes the InvenTree `api` object (context.api).
 *
 * These wrap the plugin's REST endpoints under /plugin/nfc/. Agent calls
 * (scan / health, which go to the local agent, not the server) are handled
 * separately in the scan/agent helpers.
 */

import type {
  NfcConfig,
  PartOption,
  TagByStockResponse,
  TagLookupResult
} from './types';

const BASE = '/plugin/nfc';

/** GET the effective-config raw payload (global defaults). */
export async function fetchConfig(api: any): Promise<NfcConfig> {
  const r = await api.get(`${BASE}/config/`);
  return r.data;
}

/** Look up a tag UID → its product, unit and siblings. */
export async function findByTag(api: any, uid: string): Promise<TagLookupResult> {
  const r = await api.get(`${BASE}/tag/${uid}/`);
  return r.data;
}

/** Get the active tag (if any) linked to a stock item. */
export async function getTagForStockItem(
  api: any,
  stockItemId: number
): Promise<TagByStockResponse> {
  const r = await api.get(`${BASE}/stock-item-tag/${stockItemId}/`);
  return r.data;
}

/** Link a tag to a stock item. */
export async function linkTag(api: any, uid: string, stockItemId: number) {
  const r = await api.post(`${BASE}/link/`, {
    uid,
    stock_item_id: stockItemId
  });
  return r.data;
}

/** Unlink a tag. */
export async function unlinkTag(api: any, uid: string) {
  const r = await api.delete(`${BASE}/link/${uid}/`);
  return r.data;
}

/** Adjust stock (remove / consume). Body is passed through as-is. */
export async function adjustStock(
  api: any,
  body: {
    uid: string;
    stock_item_id: number;
    quantity: number;
    action: string;
  }
) {
  const r = await api.post(`${BASE}/stock/`, body);
  return r.data;
}

/** Fetch a unit's history events. */
export async function fetchHistory(api: any, stockItemId: number) {
  const r = await api.get(`${BASE}/history/${stockItemId}/`);
  return r.data;
}

/** Fetch a part's info (used to read its form when creating units). */
export async function fetchPartInfo(api: any, partId: number | string) {
  const r = await api.get(`${BASE}/part-info/${partId}/`);
  return r.data;
}

/** Create a product (part). Body passed through. */
export async function createProduct(api: any, body: Record<string, any>) {
  const r = await api.post(`${BASE}/create-product/`, body);
  return r.data;
}

/** Create one or more units. Body passed through (supports `uids` list). */
export async function createItem(api: any, body: Record<string, any>) {
  const r = await api.post(`${BASE}/create-item/`, body);
  return r.data;
}

/** Names of the manufacturer companies, for the product form suggestions. */
export async function fetchManufacturers(api: any): Promise<string[]> {
  const r = await api.get(`${BASE}/manufacturers/`);
  return r.data?.results ?? [];
}

/** Load selectable parts for the create form. */
export async function fetchParts(api: any): Promise<PartOption[]> {
  const r = await api.get('/api/part/?limit=500&ordering=name');
  const results = r.data?.results ?? r.data ?? [];
  return results.map((p: any) => ({ value: String(p.pk), label: p.name }));
}

/** Load selectable (non-structural) stock locations for the create form. */
export async function fetchLocations(api: any): Promise<PartOption[]> {
  const r = await api.get(
    '/api/stock/location/?limit=500&ordering=name&structural=false'
  );
  const results = r.data?.results ?? r.data ?? [];
  return results.map((l: any) => ({
    value: String(l.pk),
    label: l.pathstring || l.name
  }));
}