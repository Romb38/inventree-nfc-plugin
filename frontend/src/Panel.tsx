import {
  checkPluginVersion,
  type InvenTreePluginContext,
  ModelType
} from '@inventreedb/ui';
import { t } from '@lingui/core/macro';
import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Box,
  Button,
  Group,
  Loader,
  Modal,
  NumberInput,
  Stack,
  Text,
  Title
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconLink, IconMinus, IconPlus, IconTrash, IconWifi } from '@tabler/icons-react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useCallback, useMemo, useState } from 'react';
import { LocalizedComponent } from './locale';
import { playSound } from './sound';

// Trim trailing zeros: 65.0000 -> "65", 65.5000 -> "65.5"
function fmtQty(v: number | string | null | undefined): string {
  if (v === null || v === undefined) return '—';
  const n = typeof v === 'string' ? parseFloat(v) : v;
  if (Number.isNaN(n)) return String(v);
  return String(Number(n));
}

interface NfcConfig {
  agent_base_url: string;
  scan_timeout_seconds: number;
  auto_redirect: boolean;
  allow_link_from_scan: boolean;
  sound_enabled: boolean;
}

interface TagByPartResponse {
  found: boolean;
  uid?: string;
  part_id?: number;
  linked_at?: string;
  linked_by?: string | null;
}

interface ScanResult {
  // Agent returns { uid: "AABBCCDD" } on success, or { error: "timeout" | "no_reader" }
  uid?: string;
  error?: string;
}

interface Tube {
  id: number;
  quantity: number;
  batch: string | null;
  expiry_date: string | null;
  location: string | null;
  status_label: string | null;
  concentration: string | null;
  measured_ph: string | null;
  received_date: string | null;
  opened_date: string | null;
  purity: string | null;
  manufacturer: string | null;
}

interface PartInfo {
  part_id: number;
  part_name: string;
  part_description: string;
  total_stock: number;
  parameters: Record<string, string>;
}

interface TagLookupResult {
  found: boolean;
  uid?: string;
  part?: PartInfo;
  scanned_tube?: Tube;
  sibling_tubes?: Tube[];
  part_url?: string;
}

interface AgentHealth {
  status: 'ok' | 'unreachable';
  agent_reachable: boolean;
  reader_connected: boolean;
  readers?: string[];
}

class AgentScanError extends Error {
  code: string;

  constructor(code: string, message?: string) {
    super(message ?? code);
    this.code = code;
  }
}

async function getAgentHealth(agentBaseUrl: string): Promise<AgentHealth> {
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

async function scanOnce(
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

function getScanErrorMessage(code: string): string {
  switch (code) {
    case 'timeout':
    case 'client_timeout':
      return 'No tag detected before timeout.';
    case 'no_reader':
      return 'No NFC reader detected on this workstation.';
    case 'scan_in_progress':
      return 'A scan is already in progress.';
    case 'network_error':
      return 'Cannot reach the local NFC agent.';
    default:
      return 'Scan failed.';
  }
}

/**async function pollForTag(
  agentBaseUrl: string,
  timeoutSeconds: number,
  signal: AbortSignal
): Promise<string | null> {
  const deadline = Date.now() + timeoutSeconds * 1000;
  while (Date.now() < deadline) {
    if (signal.aborted) return null;

    const res = await fetch(`${agentBaseUrl}/scan/once`, {
      method: 'POST', // agent exposes POST /scan/once
      signal
    }).catch(() => null);

    if (!res) return null;

    const data: ScanResult = await res.json();

    // Success — agent returned a UID
    if (data.uid) return data.uid;

    // Hard stop — no reader plugged in, no point retrying
    if (data.error === 'no_reader') return null;

    // Timeout from agent — loop again if we still have budget
    await new Promise((r) => setTimeout(r, 200));
  }

  return null;
}**/

/**
 * Render a custom panel with the provided context.
 * Refer to the InvenTree documentation for the context interface
 * https://docs.inventree.org/en/latest/plugins/mixins/ui/#plugin-context
 */
function NFCPanel({ context }: { context: InvenTreePluginContext }) {
  const partId = useMemo(
    () => (context.model === ModelType.part ? (context.id ?? null) : null),
    [context.model, context.id]
  );

  // Staff
  const isStaff = useMemo(() => !!context.user?.isStaff, [context.user]);

  // Config
  const configQuery = useQuery<NfcConfig>(
    {
      queryKey: ['nfc-config'],
      queryFn: () => context.api.get('/plugin/nfc/config/').then((r) => r.data),
      staleTime: 0,
      refetchOnWindowFocus: true,
    },
    context.queryClient
  );

  const config = configQuery.data;

  const healthQuery = useQuery<AgentHealth>(
    {
      queryKey: ['nfc-agent-health', config?.agent_base_url],
      enabled: !!config?.agent_base_url,
      queryFn: () => getAgentHealth(config!.agent_base_url),
      refetchInterval: 3000,
      retry: false
    },
    context.queryClient
  );

  const health = healthQuery.data;
  const agentReachable = !!health?.agent_reachable;
  const readerReady = !!health?.agent_reachable && !!health?.reader_connected;
  const canScan = !!config && readerReady;

  // Tag linked to this part
  const tagByPartQuery = useQuery<TagByPartResponse>(
    {
      queryKey: ['nfc-tag-by-part', partId],
      enabled: !!partId,
      queryFn: () =>
        context.api
          .get(`/plugin/nfc/tag/by-part/${partId}/`)
          .then((r) => r.data),
      staleTime: 60_000
    },
    context.queryClient
  );

  const linkedTag = tagByPartQuery.data?.found ? tagByPartQuery.data : null;

  // Unlink
  const unlinkMutation = useMutation(
    {
      mutationFn: (uid: string) =>
        context.api.delete(`/plugin/nfc/link/${uid}/`),
      onSuccess: () => {
        // Refresh the tag status for this part
        context.queryClient.invalidateQueries({
          queryKey: ['nfc-tag-by-part', partId]
        });
        notifications.show({
          title: t`Tag unlinked`,
          message: t`NFC tag has been successfully unlinked.`,
          color: 'green'
        });
      },
      onError: () => {
        notifications.show({
          title: t`Unlink failed`,
          message: t`Could not remove the NFC tag. Try again.`,
          color: 'red'
        });
      }
    },
    context.queryClient
  );

  /**const [linkScanning, setLinkScanning] = useState(false);
  const startLinkScan = useCallback(async () => {
    if (!config || !partId) return;
    setLinkScanning(true);

    const uid = await pollForTag(
      config.agent_base_url,
      config.scan_timeout_seconds,
      new AbortController().signal
    );

    if (!uid) {
      notifications.show({
        title: t`No tag detected`,
        message: t`Scan timed out or no reader found.`,
        color: 'yellow'
      });
      setLinkScanning(false);
      return;
    }

    try {
      await context.api.post('/plugin/nfc/link/', { uid, part_id: partId });
      context.queryClient.invalidateQueries({
        queryKey: ['nfc-tag-by-part', partId]
      });
      notifications.show({
        title: t`Tag linked`,
        message: `${uid} → part #${partId}`,
        color: 'green'
      });
    } catch (err: any) {
      notifications.show({
        title: t`Link failed`,
        message:
          err?.response?.data?.error ?? t`Could not link tag. Try again.`,
        color: 'red'
      });
    }

    setLinkScanning(false);
  }, [config, partId, context.api, context.queryClient]);**/

  // Link Scan
  const [linkScanning, setLinkScanning] = useState(false);

  const startLinkScan = useCallback(async () => {
    if (!config || !partId || linkScanning) return;

    setLinkScanning(true);

    try {
      playSound(config.sound_enabled, 'click');

      const uid = await scanOnce(
        config.agent_base_url,
        config.scan_timeout_seconds
      );

      await context.api.post('/plugin/nfc/link/', { uid, part_id: partId });

      context.queryClient.invalidateQueries({
        queryKey: ['nfc-tag-by-part', partId]
      });

      playSound(config.sound_enabled, 'success');

      notifications.show({
        title: t`Tag linked`,
        message: `${uid} → part #${partId}`,
        color: 'green'
      });
    } catch (err: any) {
      const message =
        err?.response?.data?.error ??
        getScanErrorMessage(err?.code ?? 'unknown');

      if (err?.code === 'timeout' || err?.code === 'client_timeout') {
        playSound(config.sound_enabled, 'timeout');
      } else {
        playSound(config.sound_enabled, 'error');
      }

      notifications.show({
        title: t`Link failed`,
        message,
        color:
          err?.code === 'timeout' || err?.code === 'client_timeout'
            ? 'yellow'
            : 'red'
      });
    } finally {
      setLinkScanning(false);
    }
  }, [config, partId, linkScanning, context.api, context.queryClient]);

  /**const [findScanning, setFindScanning] = useState(false);
  const [findResult, setFindResult] = useState<TagLookupResult | null>(null);

  const startFindScan = useCallback(async () => {
    if (!config) return;
    setFindScanning(true);
    setFindResult(null);

    const uid = await pollForTag(
      config.agent_base_url,
      config.scan_timeout_seconds,
      new AbortController().signal
    );

    if (!uid) {
      notifications.show({
        title: t`No tag detected`,
        message: t`Scan timed out or no reader found.`,
        color: 'yellow'
      });
      setFindScanning(false);
      return;
    }

    try {
      const res = await context.api.get(`/plugin/nfc/tag/${uid}/`);
      const data: TagLookupResult = res.data;
      setFindResult(data);

      if (data.found && config.auto_redirect && data.part_url) {
        context.navigate(data.part_url);
      }
    } catch {
      notifications.show({
        title: t`Lookup failed`,
        message: t`Could not check this tag. Try again.`,
        color: 'red'
      });
    }

    setFindScanning(false);
  }, [config, context.api, context.navigate]);**/

  // Find scan
  const [findScanning, setFindScanning] = useState(false);
  const [findResult, setFindResult] = useState<TagLookupResult | null>(null);

  const startFindScan = useCallback(async () => {
    if (!config || findScanning) return;

    setFindScanning(true);
    setFindResult(null);

    try {
      playSound(config.sound_enabled, 'click');
      const uid = await scanOnce(
        config.agent_base_url,
        config.scan_timeout_seconds
      );

      const res = await context.api.get(`/plugin/nfc/tag/${uid}/`);
      const data: TagLookupResult = res.data;
      setFindResult(data);
      if (data.found) {
        setAdjustQty(1);
      }

      playSound(config.sound_enabled, 'success');
      if (data.found && config.auto_redirect && data.part_url) {
        context.navigate(data.part_url);
      }
    } catch (err: any) {
      if (err?.code === 'timeout' || err?.code === 'client_timeout') {
        playSound(config.sound_enabled, 'timeout');
      } else {
        playSound(config.sound_enabled, 'error');
      }

      notifications.show({
        title: t`Scan failed`,
        message: getScanErrorMessage(err?.code ?? 'unknown'),
        color:
          err?.code === 'timeout' || err?.code === 'client_timeout'
            ? 'yellow'
            : 'red'
      });
    } finally {
      setFindScanning(false);
    }
  }, [config, findScanning, context.api, context.navigate]);

  // Stock adjust: the scanned tube is the target (no picker).
  const [adjustQty, setAdjustQty] = useState<number | string>(1);

  // Confirm popup before navigating to a tube's stock item page
  const [tubeToVisit, setTubeToVisit] = useState<Tube | null>(null);

  const scannedTube = findResult?.scanned_tube ?? null;

  const stockMutation = useMutation(
    {
      mutationFn: (vars: { action: 'add' | 'remove' }) => {
        const qty = typeof adjustQty === 'string' ? parseFloat(adjustQty) : adjustQty;
        if (!findResult?.uid || !scannedTube || !qty || qty <= 0) {
          return Promise.reject({
            response: { data: { error: 'Scan a tube and enter a quantity greater than 0.' } }
          });
        }
        return context.api.post('/plugin/nfc/stock/', {
          uid: findResult.uid,
          stock_item_id: scannedTube.id,
          quantity: qty,
          action: vars.action
        });
      },
      onSuccess: (res, vars) => {
        playSound(config!.sound_enabled, 'success');
        notifications.show({
          title: vars.action === 'add' ? t`Stock added` : t`Stock removed`,
          message: `${res.data.part_name}: ${fmtQty(res.data.new_stock)}`,
          color: 'green'
        });
        // Update the scanned tube's quantity in place
        if (findResult && scannedTube) {
          setFindResult({
            ...findResult,
            scanned_tube: { ...scannedTube, quantity: res.data.new_stock }
          });
        }
      },
      onError: (err: any) => {
        playSound(config!.sound_enabled, 'error');
        notifications.show({
          title: t`Stock update failed`,
          message: err?.response?.data?.error ?? t`Could not update stock.`,
          color: 'red'
        });
      }
    },
    context.queryClient
  );

  // Render
  if (configQuery.isLoading) {
    return (
      <Group justify='center' p='md'>
        <Loader size='sm' />
        <Text c='dimmed'>{t`Loading NFC config...`}</Text>
      </Group>
    );
  }

  if (configQuery.isError || !config) {
    return (
      <Alert color='red' title={t`Config error`}>
        {t`Could not load NFC plugin settings.`}
      </Alert>
    );
  }

  return (
    <>
      <Modal
        opened={!!tubeToVisit}
        onClose={() => setTubeToVisit(null)}
        title={t`Go to this tube?`}
        centered
        size='sm'
      >
        <Stack gap='sm'>
          <Text size='sm'>
            {t`Open the stock item page for lot`}{' '}
            <strong>{tubeToVisit?.batch ?? '—'}</strong>?
          </Text>
          <Group justify='flex-end' gap='xs'>
            <Button variant='default' size='xs' onClick={() => setTubeToVisit(null)}>
              {t`Cancel`}
            </Button>
            <Button
              size='xs'
              color='teal'
              onClick={() => {
                if (tubeToVisit) context.navigate(`/stock/item/${tubeToVisit.id}/`);
                setTubeToVisit(null);
              }}
            >
              {t`Go to stock item`}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Group gap='xs' mb='sm'>
        <Box
          w={10}
          h={10}
          style={{
            borderRadius: '999px',
            backgroundColor: healthQuery.isLoading
              ? 'var(--mantine-color-yellow-6)'
              : readerReady
                ? 'var(--mantine-color-green-6)'
                : 'var(--mantine-color-red-6)',
            flexShrink: 0
          }}
        />
        <Text
          size='sm'
          c={healthQuery.isLoading ? 'yellow' : readerReady ? 'green' : 'red'}
        >
          {healthQuery.isLoading
            ? t`Checking reader...`
            : !agentReachable
              ? t`Agent not reachable`
              : readerReady
                ? t`Reader connected`
                : t`Reader not available`}
        </Text>
      </Group>

      <Accordion defaultValue='scan'>
        {/* Link / Unlink — staff + part page only */}
        {partId && isStaff && (
          <Accordion.Item value='link'>
            <Accordion.Control>
              <Title c={context.theme.primaryColor} order={4}>
                {t`NFC Tag`}
              </Title>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap='sm'>
                {tagByPartQuery.isLoading ? (
                  <Group>
                    <Loader size='xs' />
                    <Text size='sm' c='dimmed'>
                      {t`Checking tag...`}
                    </Text>
                  </Group>
                ) : linkedTag ? (
                  <>
                    <Alert
                      color='teal'
                      title={t`Tag linked`}
                      icon={<IconWifi size={16} />}
                    >
                      <Stack gap={4}>
                        <Group gap='xs'>
                          <Text size='sm' fw={600}>
                            {t`UID:`}
                          </Text>
                          <Badge variant='outline' color='teal'>
                            {linkedTag.uid}
                          </Badge>
                        </Group>
                        {linkedTag.linked_by && (
                          <Text size='xs' c='dimmed'>
                            {t`Linked by`} {linkedTag.linked_by}
                            {linkedTag.linked_at &&
                              ` — ${new Date(linkedTag.linked_at).toLocaleDateString()}`}
                          </Text>
                        )}
                      </Stack>
                    </Alert>

                    <Button
                      color='red'
                      variant='light'
                      leftSection={<IconTrash size={16} />}
                      loading={unlinkMutation.isPending}
                      onClick={() => unlinkMutation.mutate(linkedTag.uid!)}
                    >
                      {t`Unlink tag`}
                    </Button>
                  </>
                ) : (
                  <>
                    <Text size='sm' c='dimmed'>
                      {t`No NFC tag linked to this part.`}
                    </Text>

                    <Button
                      color={context.theme.primaryColor}
                      disabled={!canScan}
                      leftSection={
                        linkScanning ? (
                          <Loader size={14} color='white' />
                        ) : (
                          <IconLink size={16} />
                        )
                      }
                      loading={linkScanning}
                      onClick={startLinkScan}
                    >
                      {linkScanning ? t`Waiting for tag...` : t`Link NFC Tag`}
                    </Button>
                  </>
                )}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        )}
        {/* Scan to Find — everyone */}
        <Accordion.Item value='scan'>
          <Accordion.Control>
            <Title c={context.theme.primaryColor} order={4}>
              {t`Scan to Find`}
            </Title>
          </Accordion.Control>
          <Accordion.Panel>
            <Stack gap='sm'>
              <Button
                color={context.theme.primaryColor}
                disabled={!canScan}
                leftSection={
                  findScanning ? (
                    <Loader size={14} color='white' />
                  ) : (
                    <IconWifi size={16} />
                  )
                }
                loading={findScanning}
                onClick={startFindScan}
              >
                {findScanning ? t`Waiting for tag...` : t`Scan Tag`}
              </Button>

              {findResult &&
                (findResult.found && findResult.scanned_tube && findResult.part ? (
                  <Alert color='teal' title={t`Tube found`}>
                    <Stack gap='sm'>
                      {/* ZONE 1 — product (shared info) */}
                      <div>
                        <Anchor
                          fw={600}
                          onClick={() => context.navigate(findResult.part_url!)}
                          style={{ cursor: 'pointer' }}
                        >
                          {findResult.part.part_name}
                        </Anchor>
                        {findResult.part.part_description && (
                          <Text size='sm' c='dimmed'>
                            {findResult.part.part_description}
                          </Text>
                        )}
                        {Object.entries(findResult.part.parameters || {}).map(
                          ([k, v]) => (
                            <Text key={k} size='xs' c='dimmed'>
                              {k}: {v}
                            </Text>
                          )
                        )}
                      </div>

                      {/* ZONE 2 — the scanned tube (the action target) */}
                      <Box
                        style={{
                          border: '1px solid var(--mantine-color-teal-5)',
                          borderRadius: 8,
                          padding: 10
                        }}
                      >
                        <Group justify='space-between' mb={4}>
                          <Anchor
                            fw={600}
                            component='button'
                            type='button'
                            style={{ fontSize: 'var(--mantine-font-size-sm)' }}
                            onClick={() => setTubeToVisit(findResult.scanned_tube!)}
                          >
                            {t`Scanned tube`}
                          </Anchor>
                          <Badge color='teal' variant='light'>
                            {findResult.scanned_tube.batch ?? t`No lot`}
                          </Badge>
                        </Group>

                        <Text size='xs'>{t`Quantity:`} {fmtQty(findResult.scanned_tube.quantity)}</Text>
                        <Text size='xs'>{t`Expiry:`} {findResult.scanned_tube.expiry_date ?? '—'}</Text>
                        <Text size='xs'>{t`Location:`} {findResult.scanned_tube.location ?? '—'}</Text>
                        <Text size='xs'>{t`Concentration:`} {findResult.scanned_tube.concentration ?? '—'}</Text>
                        <Text size='xs'>{t`Measured pH:`} {findResult.scanned_tube.measured_ph ?? '—'}</Text>
                        <Text size='xs'>{t`Purity:`} {findResult.scanned_tube.purity ?? '—'}</Text>
                        <Text size='xs'>{t`Manufacturer:`} {findResult.scanned_tube.manufacturer ?? '—'}</Text>
                        <Text size='xs'>{t`Received:`} {findResult.scanned_tube.received_date ?? '—'}</Text>
                        <Text size='xs'>{t`Opened:`} {findResult.scanned_tube.opened_date ?? '—'}</Text>

                        <NumberInput
                          size='xs'
                          mt={8}
                          label={t`Quantity to add / remove`}
                          description={`${t`Available:`} ${fmtQty(findResult.scanned_tube.quantity)}`}
                          min={1}
                          value={adjustQty}
                          onChange={setAdjustQty}
                        />

                        <Group grow gap='xs' mt={6}>
                          <Button
                            size='xs'
                            color='green'
                            variant='filled'
                            leftSection={<IconPlus size={14} />}
                            disabled={stockMutation.isPending}
                            loading={stockMutation.isPending}
                            onClick={() => stockMutation.mutate({ action: 'add' })}
                          >
                            {t`Add`}
                          </Button>
                          <Button
                            size='xs'
                            color='red'
                            variant='filled'
                            leftSection={<IconMinus size={14} />}
                            disabled={stockMutation.isPending}
                            loading={stockMutation.isPending}
                            onClick={() => stockMutation.mutate({ action: 'remove' })}
                          >
                            {t`Remove`}
                          </Button>
                        </Group>
                      </Box>

                      {/* ZONE 3 — sibling tubes (read-only) */}
                      {findResult.sibling_tubes && findResult.sibling_tubes.length > 0 && (
                        <div>
                          <Text size='xs' fw={600} c='dimmed' mb={4}>
                            {t`Other tubes of this product`}
                          </Text>
                          <Stack gap={4}>
                            {findResult.sibling_tubes.map((s) => (
                              <Box
                                key={s.id}
                                onClick={() => setTubeToVisit(s)}
                                style={{
                                  border: '1px solid var(--mantine-color-gray-4)',
                                  borderRadius: 6,
                                  padding: 6,
                                  cursor: 'pointer'
                                }}
                              >
                                <Text size='xs'>
                                  {t`Lot`} {s.batch ?? '—'} · {t`Qty`} {fmtQty(s.quantity)} ·{' '}
                                  {t`Exp`} {s.expiry_date ?? '—'}
                                </Text>
                              </Box>
                            ))}
                          </Stack>
                        </div>
                      )}

                      <Button
                        size='xs'
                        variant='light'
                        color='teal'
                        mt={4}
                        onClick={() => context.navigate(findResult.part_url!)}
                      >
                        {t`Go to product`}
                      </Button>
                    </Stack>
                  </Alert>
                ) : (
                  <Alert color='yellow' title={t`Unknown tag`}>
                    <Stack gap='xs'>
                      <Text size='sm'>
                        {t`No tube linked to`}{' '}
                        <Badge variant='outline'>{findResult.uid}</Badge>
                      </Text>

                      {config.allow_link_from_scan && (
                        <Button
                          size='xs'
                          variant='light'
                          color='yellow'
                          onClick={() => context.navigate('/part/')}
                        >
                          {t`Browse parts to link`}
                        </Button>
                      )}
                    </Stack>
                  </Alert>
                ))}
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </>
  );
}

// This is the function which is called by InvenTree to render the actual panel component
export function renderNFCPanel(context: InvenTreePluginContext) {
  checkPluginVersion(context);

  return (
    <LocalizedComponent locale={context.locale} context={context}>
      <NFCPanel context={context} />
    </LocalizedComponent>
  );
}
