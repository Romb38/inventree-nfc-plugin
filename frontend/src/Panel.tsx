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
  Paper,
  Stack,
  Text,
  Title
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconAlertTriangle,
  IconChevronRight,
  IconLink,
  IconMinus,
  IconPlayerStop,
  IconTrash,
  IconWifi
} from '@tabler/icons-react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useCallback, useMemo, useState } from 'react';
import { LocalizedComponent } from './locale';
import { CreateTabs } from './CreateForms';
import { playSound } from './sound';
import { getEffectiveConfig } from './agentConfig';
import {
  adjustStock,
  fetchHistory,
  findByTag,
  getTagForStockItem,
  linkTag,
  unlinkTag
} from './api';
import { getAgentHealth } from './agent';
import { useAgentScan } from './hooks';
import type {
  AgentHealth,
  NfcConfig,
  TagByStockResponse,
  TagLookupResult,
  Tube
} from './types';
import { PluginSettingsDisplay } from './Settings';
import { StockItemLink } from './StockLink';

// Trim trailing zeros: 65.0000 -> "65", 65.5000 -> "65.5"
function fmtQty(v: number | string | null | undefined): string {
  if (v === null || v === undefined) return '—';
  const n = typeof v === 'string' ? parseFloat(v) : v;
  if (Number.isNaN(n)) return String(v);
  return String(Number(n));
}



/** Format a 'YYYY-MM' or 'YYYY-MM-DD' date as 'MM/YYYY' (other values unchanged). */
function formatMonthYear(value: string | null | undefined): string {
  const match = /^(\d{4})-(\d{2})/.exec(value ?? '');
  return match ? `${match[2]}/${match[1]}` : (value ?? '');
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
  const stockItemId = useMemo(
    () => (context.model === ModelType.stockitem ? (context.id ?? null) : null),
    [context.model, context.id]
  );

  // Staff

  // Config
  const configQuery = useQuery<NfcConfig>(
    {
      queryKey: ['nfc-config'],
      queryFn: () => getEffectiveConfig(context.api),
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

  // Tag linked to this stock item (tube)
  const tagByStockQuery = useQuery<TagByStockResponse>(
    {
      queryKey: ['nfc-tag-by-stock', stockItemId],
      enabled: !!stockItemId,
      queryFn: () => getTagForStockItem(context.api, stockItemId as number),
      staleTime: 60_000
    },
    context.queryClient
  );

  const linkedTag = tagByStockQuery.data?.found ? tagByStockQuery.data : null;

  // Unlink
  const unlinkMutation = useMutation(
    {
      mutationFn: (uid: string) => unlinkTag(context.api, uid),
      onSuccess: () => {
        context.queryClient.invalidateQueries({
          queryKey: ['nfc-tag-by-stock', stockItemId]
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

  // Link Scan
  const linkScan = useAgentScan();
  const linkScanning = linkScan.scanning;

  const startLinkScan = useCallback(async () => {
    if (!config || !stockItemId || linkScanning) return;

    try {
      playSound(config.sound_enabled, 'click');

      const uid = await linkScan.start(
        config.agent_base_url,
        config.scan_timeout_seconds
      );
      if (uid === null) return;

      await linkTag(context.api, uid, stockItemId as number);

      context.queryClient.invalidateQueries({
        queryKey: ['nfc-tag-by-stock', stockItemId]
      });

      playSound(config.sound_enabled, 'success');

      notifications.show({
        title: t`Tag linked`,
        message: `${uid} → tube #${stockItemId}`,
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
    }
  }, [config, stockItemId, linkScanning, linkScan, context.api, context.queryClient]);

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
      const data: TagLookupResult = await findByTag(context.api, uid);
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
  const findScan = useAgentScan();
  const findScanning = findScan.scanning;
  const [findResult, setFindResult] = useState<TagLookupResult | null>(null);

  const startFindScan = useCallback(async () => {
    if (!config || findScanning) return;

    setFindResult(null);

    try {
      playSound(config.sound_enabled, 'click');
      const uid = await findScan.start(
        config.agent_base_url,
        config.scan_timeout_seconds
      );
      if (uid === null) return;

      const data: TagLookupResult = await findByTag(context.api, uid);
      setFindResult(data);
      if (data.found) {
        setAdjustQty(1);
      }

      playSound(config.sound_enabled, data.found ? 'success' : 'error');
      if (data.found && config.auto_redirect && data.scanned_tube) {
        context.navigate(`/stock/item/${data.scanned_tube.id}/`);
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
    }
  }, [config, findScanning, findScan, context.api, context.navigate]);

  // Stock adjust: the scanned tube is the target (no picker).
  const [adjustQty, setAdjustQty] = useState<number | string>(1);
  const [history, setHistory] = useState<any[] | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  // Confirm popup before navigating to a tube's stock item page
  const [tubeToVisit, setTubeToVisit] = useState<Tube | null>(null);

  const scannedTube = findResult?.scanned_tube ?? null;

  const stockMutation = useMutation(
    {
      mutationFn: (vars: { action: 'add' | 'remove' | 'consume' }) => {
        if (!findResult?.uid || !scannedTube) {
          return Promise.reject({
            response: { data: { error: 'Scan a unit first.' } }
          });
        }
        // Build a single request body (typed so both branches match).
        const body: {
          uid: string;
          stock_item_id: number;
          quantity: number;
          action: string;
        } = {
          uid: findResult.uid,
          stock_item_id: scannedTube.id,
          quantity: scannedTube.quantity,
          action: 'remove'
        };
        if (vars.action === 'consume') {
          // Whole unit: remove its entire current quantity.
          return adjustStock(context.api, body);
        }
        const qty = typeof adjustQty === 'string' ? parseFloat(adjustQty) : adjustQty;
        if (!qty || qty <= 0) {
          return Promise.reject({
            response: { data: { error: 'Enter an amount greater than 0.' } }
          });
        }
        body.quantity = qty;
        body.action = vars.action;
        return adjustStock(context.api, body);
      },
      onSuccess: (res, vars) => {
        const nowOut = !!res.out_of_stock;
        const changed = res.quantity_changed;
        const unit = scannedTube?.unit ? ` ${scannedTube.unit}` : '';
        playSound(config!.sound_enabled, 'success');
        notifications.show({
          title:
            vars.action === 'consume'
              ? t`Unit marked as used`
              : t`Stock removed`,
          message:
            vars.action === 'consume'
              ? `${res.part_name}`
              : `${t`Removed`} ${changed}${unit} · ${t`Remaining:`} ${fmtQty(res.new_stock)}${unit}`,
          color: 'green'
        });
        // If this action brought the unit to zero, announce out of stock.
        if (nowOut) {
          notifications.show({
            title: t`Out of stock`,
            message: t`This unit is now out of stock.`,
            color: 'orange'
          });
        }
        // Update the scanned tube in place (quantity + out-of-stock state)
        if (findResult && scannedTube) {
          setFindResult({
            ...findResult,
            scanned_tube: {
              ...scannedTube,
              quantity: res.new_stock,
              out_of_stock: nowOut,
              used_date: res.used_date ?? scannedTube.used_date
            }
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
        {/* Link / Unlink — any logged-in user, stock item page only */}
        {stockItemId && (
          <Accordion.Item value='link'>
            <Accordion.Control>
              <Title c={context.theme.primaryColor} order={4}>
                {t`NFC Tag`}
              </Title>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap='sm'>
                {tagByStockQuery.isLoading ? (
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
                      {t`No NFC tag linked to this tube.`}
                    </Text>

                    {linkScanning ? (
                      <Button
                        color='red'
                        variant='light'
                        leftSection={<IconPlayerStop size={16} />}
                        onClick={linkScan.stop}
                      >
                        {t`Stop scan`}
                      </Button>
                    ) : (
                      <Button
                        color={context.theme.primaryColor}
                        disabled={!canScan}
                        leftSection={<IconLink size={16} />}
                        onClick={startLinkScan}
                      >
                        {t`Link NFC Tag`}
                      </Button>
                    )}
                    {linkScanning && (
                      <Group gap='xs'>
                        <Loader size={14} />
                        <Text size='xs' c='dimmed'>{t`Waiting for tag...`}</Text>
                      </Group>
                    )}
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
              {findScanning ? (
                <Button
                  color='red'
                  variant='light'
                  leftSection={<IconPlayerStop size={16} />}
                  onClick={findScan.stop}
                >
                  {t`Stop scan`}
                </Button>
              ) : (
                <Button
                  color={context.theme.primaryColor}
                  disabled={!canScan}
                  leftSection={<IconWifi size={16} />}
                  onClick={startFindScan}
                >
                  {t`Scan Tag`}
                </Button>
              )}
              {findScanning && (
                <Group gap='xs'>
                  <Loader size={14} />
                  <Text size='xs' c='dimmed'>{t`Waiting for tag...`}</Text>
                </Group>
              )}

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
                            onClick={() =>
                              findResult.scanned_tube &&
                              setTubeToVisit(findResult.scanned_tube)
                            }
                          >
                            {t`Scanned tube`}
                          </Anchor>
                          <Badge color='teal' variant='light'>
                            {findResult.scanned_tube?.batch ?? t`No lot`}
                          </Badge>
                        </Group>

                        {findResult.scanned_tube?.serial && (
                          <Text size='xs'>{t`Unit no.:`} {findResult.scanned_tube?.serial}</Text>
                        )}
                        {findResult.scanned_tube?.batch && (
                          <Text size='xs'>{t`Lot:`} {findResult.scanned_tube?.batch}</Text>
                        )}
                        {findResult.scanned_tube?.expiry_date && (
                          <Text size='xs'>{t`Expiry:`} {formatMonthYear(findResult.scanned_tube?.expiry_date)}</Text>
                        )}
                        {findResult.scanned_tube?.received_date && (
                          <Text size='xs'>{t`Received:`} {formatMonthYear(findResult.scanned_tube?.received_date)}</Text>
                        )}
                        {findResult.scanned_tube?.location && (
                          <Text size='xs'>{t`Location:`} {findResult.scanned_tube?.location}</Text>
                        )}

                        {findResult.scanned_tube?.out_of_stock ? (
                          <Alert
                            color='orange'
                            variant='light'
                            mt={8}
                            p='xs'
                            icon={<IconAlertTriangle size={16} />}
                          >
                            <Text size='sm' fw={600}>{t`Out of stock`}</Text>
                            {findResult.scanned_tube?.used_date && (
                              <Text size='xs' c='dimmed'>
                                {t`Used on:`} {findResult.scanned_tube?.used_date}
                              </Text>
                            )}
                            <Text size='xs' c='dimmed'>
                              {t`The tag stays linked until someone unlinks it.`}
                            </Text>
                          </Alert>
                        ) : findResult.scanned_tube?.behaviour === 'quantity' ? (
                          <>
                            <NumberInput
                              size='xs'
                              mt={8}
                              label={
                                findResult.scanned_tube?.unit
                                  ? `${t`Amount to remove`} (${findResult.scanned_tube?.unit})`
                                  : t`Amount to remove`
                              }
                              description={`${t`Remaining:`} ${fmtQty(findResult.scanned_tube?.quantity)}${findResult.scanned_tube?.unit ? ` ${findResult.scanned_tube?.unit}` : ''}`}
                              min={0}
                              value={adjustQty}
                              onChange={setAdjustQty}
                            />
                            <Button
                              size='xs'
                              color='red'
                              variant='filled'
                              mt={6}
                              fullWidth
                              leftSection={<IconMinus size={14} />}
                              disabled={stockMutation.isPending}
                              loading={stockMutation.isPending}
                              onClick={() => {
                                const tube = findResult.scanned_tube;
                                if (!tube) return;
                                const qty =
                                  typeof adjustQty === 'string'
                                    ? parseFloat(adjustQty)
                                    : adjustQty;
                                if (!qty || qty <= 0) {
                                  notifications.show({
                                    title: t`Invalid amount`,
                                    message: t`Enter an amount greater than 0.`,
                                    color: 'red'
                                  });
                                  return;
                                }
                                if (qty > tube.quantity) {
                                  const u = tube.unit ? ` ${tube.unit}` : '';
                                  notifications.show({
                                    title: t`Amount too high`,
                                    message: `${t`You can't remove more than what remains. Only`} ${fmtQty(tube.quantity)}${u} ${t`available — choose a lower amount.`}`,
                                    color: 'red'
                                  });
                                  return;
                                }
                                const u = tube.unit ? ` ${tube.unit}` : '';
                                if (
                                  window.confirm(
                                    `${t`Remove`} ${qty}${u} ${t`from this unit?`}`
                                  )
                                ) {
                                  stockMutation.mutate({ action: 'remove' });
                                }
                              }}
                            >
                              {t`Remove`}
                            </Button>
                          </>
                        ) : (
                          // Whole unit (ampoule): consumed entirely, single action.
                          <Button
                            size='xs'
                            color='red'
                            variant='filled'
                            mt={8}
                            fullWidth
                            leftSection={<IconMinus size={14} />}
                            disabled={stockMutation.isPending}
                            loading={stockMutation.isPending}
                            onClick={() => {
                              if (
                                window.confirm(
                                  t`Mark this unit as used and remove it from stock?`
                                )
                              ) {
                                stockMutation.mutate({ action: 'consume' });
                              }
                            }}
                          >
                            {t`Mark as used`}
                          </Button>
                        )}
                      </Box>

                      {/* History — who did what, when, and how much */}
                      <div>
                        <Button
                          size='xs'
                          variant='subtle'
                          mt={4}
                          loading={historyLoading}
                          onClick={async () => {
                            if (history) {
                              setHistory(null); // toggle closed
                              return;
                            }
                            setHistoryLoading(true);
                            try {
                              const data = await fetchHistory(
                                context.api,
                                findResult.scanned_tube?.id as number
                              );
                              setHistory(data?.events ?? []);
                            } catch {
                              setHistory([]);
                            } finally {
                              setHistoryLoading(false);
                            }
                          }}
                        >
                          {history ? t`Hide history` : t`Show history`}
                        </Button>

                        {history && history.length === 0 && (
                          <Text size='xs' c='dimmed'>{t`No history yet.`}</Text>
                        )}
                        {history && history.length > 0 && (
                          <Stack gap={4} mt={4}>
                            {history.map((ev, i) => (
                              <Box
                                key={i}
                                style={{
                                  border: '1px solid var(--mantine-color-gray-3)',
                                  borderRadius: 6,
                                  padding: 6
                                }}
                              >
                                <Text size='xs' fw={600}>
                                  {ev.type === 'stock'
                                    ? t`Stock change`
                                    : ev.type === 'link'
                                      ? t`Tag linked`
                                      : ev.type === 'created'
                                        ? t`Unit created`
                                        : t`Tag unlinked`}
                                </Text>
                                <Text size='xs' c='dimmed'>
                                  {ev.who ? `${t`By`} ${ev.who}` : t`By unknown`}
                                  {ev.when ? ` · ${new Date(ev.when).toLocaleString()}` : ''}
                                </Text>
                                {ev.type === 'stock' && ev.added != null && (
                                  <Text size='xs'>
                                    {t`Change:`} {ev.added} · {t`Result:`} {ev.quantity}
                                  </Text>
                                )}
                                {ev.notes && (
                                  <Text size='xs' c='dimmed'>{ev.notes}</Text>
                                )}
                              </Box>
                            ))}
                          </Stack>
                        )}
                      </div>

                      {/* ZONE 3 — sibling tubes (read-only) */}
                      {findResult.sibling_tubes && findResult.sibling_tubes.length > 0 && (
                        <div>
                          <Text size='xs' fw={600} c='dimmed' mb={6} tt='uppercase'>
                            {t`Other units of this product`} ({findResult.sibling_tubes.length})
                          </Text>
                          <Stack gap={6}>
                            {findResult.sibling_tubes.map((s) => (
                              <Paper
                                key={s.id}
                                withBorder
                                radius='md'
                                p='xs'
                                onClick={() => setTubeToVisit(s)}
                                style={{ cursor: 'pointer', transition: 'background-color 120ms' }}
                                onMouseEnter={(e) => {
                                  e.currentTarget.style.backgroundColor =
                                    'var(--mantine-color-gray-0)';
                                }}
                                onMouseLeave={(e) => {
                                  e.currentTarget.style.backgroundColor = '';
                                }}
                              >
                                <Group justify='space-between' wrap='nowrap' gap='xs'>
                                  <Group gap={6} wrap='wrap' style={{ flex: 1 }}>
                                    {s.serial && (
                                      <Badge size='sm' variant='light' color='blue'>
                                        {t`Unit`} {s.serial}
                                      </Badge>
                                    )}
                                    {s.batch && (
                                      <Badge size='sm' variant='light' color='gray'>
                                        {t`Lot`} {s.batch}
                                      </Badge>
                                    )}
                                    {s.expiry_date && (
                                      <Badge size='sm' variant='light' color='orange'>
                                        {t`Exp`} {formatMonthYear(s.expiry_date)}
                                      </Badge>
                                    )}
                                    {s.location && (
                                      <Badge size='sm' variant='light' color='teal'>
                                        {s.location}
                                      </Badge>
                                    )}
                                    {s.out_of_stock && (
                                      <Badge size='sm' variant='filled' color='red'>
                                        {t`Out of stock`}
                                      </Badge>
                                    )}
                                  </Group>
                                  <IconChevronRight
                                    size={16}
                                    style={{ color: 'var(--mantine-color-gray-5)', flexShrink: 0 }}
                                  />
                                </Group>
                              </Paper>
                            ))}
                          </Stack>
                        </div>
                      )}

                      <StockItemLink stockItemId={findResult.scanned_tube.id} />

                      <Button
                        size='xs'
                        variant='light'
                        color='teal'
                        mt={4}
                        onClick={() =>
                          context.navigate(`/stock/item/${findResult.scanned_tube?.id}/`)
                        }
                      >
                        {t`Go to stock item`}
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
                          onClick={() => context.navigate('/stock/')}
                        >
                          {t`Browse stock items to link`}
                        </Button>
                      )}
                    </Stack>
                  </Alert>
                ))}
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
        <Accordion.Item value='create'>
          <Accordion.Control>
            <Title c={context.theme.primaryColor} order={4}>
              {t`Create product`}
            </Title>
          </Accordion.Control>
          <Accordion.Panel>
            <CreateTabs context={context} />
          </Accordion.Panel>
        </Accordion.Item>

        {/* Agent settings (this workstation) — available to ALL users, since
            the agent config is machine-specific and stored in the browser. */}
        <Accordion.Item value='agent-settings'>
          <Accordion.Control>
            <Title c={context.theme.primaryColor} order={4}>
              {t`Agent settings (this workstation)`}
            </Title>
          </Accordion.Control>
          <Accordion.Panel>
            <PluginSettingsDisplay context={context} />
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
