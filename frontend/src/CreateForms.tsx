import type { InvenTreePluginContext } from '@inventreedb/ui';
import { t } from '@lingui/core/macro';
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Group,
  Loader,
  Modal,
  NumberInput,
  Select,
  SegmentedControl,
  Stack,
  Text,
  TextInput
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconCheck, IconWifi } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { playSound } from './sound';
import { getEffectiveConfig } from './agentConfig';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

interface ScanResult {
  uid?: string;
  error?: string;
}

interface PartOption {
  value: string; // part id as string
  label: string; // part name
}

async function getReaderConnected(agentBaseUrl: string): Promise<boolean> {
  try {
    const res = await fetch(`${agentBaseUrl}/health`);
    if (!res.ok) return false;
    const data = await res.json();
    return !!data.reader_connected;
  } catch {
    return false;
  }
}

async function scanOnce(agentBaseUrl: string, timeoutSeconds: number): Promise<string> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), (timeoutSeconds + 2) * 1000);
  try {
    const res = await fetch(`${agentBaseUrl}/scan/once`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ timeout: timeoutSeconds }),
      signal: controller.signal
    });
    const data: ScanResult = await res.json().catch(() => ({}));
    if (res.ok && data.uid) return data.uid;
    throw new Error(data.error ?? `http_${res.status}`);
  } finally {
    clearTimeout(timer);
  }
}

// Reader status dot (color only, no text).
// Month + year picker. Value is stored as 'YYYY-MM' (or '' when incomplete).
// Month is a fixed 1–12 dropdown (can't be invalid); year is an editable
// number. The user can click to choose or type the year directly.
function MonthYearPicker({
  label,
  value,
  onChange
}: {
  label: string;
  value: string; // 'YYYY-MM' or ''
  onChange: (v: string) => void;
}) {
  const [yearStr, monthStr] = value && value.includes('-')
    ? value.split('-')
    : ['', ''];

  const months = [
    { value: '01', label: t`01 - January` },
    { value: '02', label: t`02 - February` },
    { value: '03', label: t`03 - March` },
    { value: '04', label: t`04 - April` },
    { value: '05', label: t`05 - May` },
    { value: '06', label: t`06 - June` },
    { value: '07', label: t`07 - July` },
    { value: '08', label: t`08 - August` },
    { value: '09', label: t`09 - September` },
    { value: '10', label: t`10 - October` },
    { value: '11', label: t`11 - November` },
    { value: '12', label: t`12 - December` }
  ];

  function emit(y: string, m: string) {
    if (y && m) onChange(`${y}-${m}`);
    else onChange('');
  }

  return (
    <div>
      <Text size='sm' fw={500} mb={2}>{label}</Text>
      <Text size='xs' c='dimmed' mb={4}>{t`mm-yyyy`}</Text>
      <Group gap='xs' grow>
        <Select
          placeholder={t`Month`}
          data={months}
          value={monthStr || null}
          searchable
          onChange={(m) => emit(yearStr, m || '')}
        />
        <NumberInput
          placeholder={t`Year`}
          min={2000}
          max={2100}
          value={yearStr ? Number(yearStr) : ''}
          hideControls
          onChange={(y) => {
            const yy = y ? String(y) : '';
            emit(yy, monthStr);
          }}
        />
      </Group>
    </div>
  );
}

function ReaderDot({ connected }: { connected: boolean | null }) {
  return (
    <Box
      w={10}
      h={10}
      mb={10}
      style={{
        borderRadius: '999px',
        flexShrink: 0,
        backgroundColor:
          connected === null
            ? 'var(--mantine-color-yellow-6)'
            : connected
              ? 'var(--mantine-color-green-6)'
              : 'var(--mantine-color-red-6)'
      }}
    />
  );
}

// Hook: poll reader connection every 3s.
function useReaderStatus(context: InvenTreePluginContext) {
  const [connected, setConnected] = useState<boolean | null>(null);
  useEffect(() => {
    let active = true;
    let timer: number;
    let agentUrl: string | null = null;

    async function poll() {
      try {
        // Fetch config only once; the agent URL doesn't change.
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

// ---------------------------------------------------------------------------
// CREATE PART form
// ---------------------------------------------------------------------------

export function CreatePartForm({
  context,
  onCreated
}: {
  context: InvenTreePluginContext;
  // Called after a part is created; receives the new part id + name so the
  // container can offer "add a unit?" and hand off to the item tab.
  onCreated?: (partId: number, partName: string) => void;
}) {
  const [molecule, setMolecule] = useState('');
  const [dosage, setDosage] = useState('');
  const [form, setForm] = useState<string | null>('Solution');
  const [laboratory, setLaboratory] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const previewName = [molecule, laboratory, dosage, form]
    .map((s) => (s || '').trim())
    .filter(Boolean)
    .join(' ');

  const canSubmit =
    !!molecule.trim() && !!dosage.trim() && (form === 'Solution' || form === 'Poudre');

  async function doCreate() {
    setConfirmOpen(false);
    if (!canSubmit || submitting) return;
    setSubmitting(true);
    try {
      const res = await context.api.post('/plugin/nfc/create-product/', {
        molecule: molecule.trim(),
        dosage: dosage.trim(),
        form,
        laboratory: laboratory.trim(),
        add_unit: false // Part-only; the unit (with its container) is created in the Item tab.
      });
      const data = res.data;
      notifications.show({
        title: data.reused_existing_part ? t`Product already exists` : t`Product created`,
        message: data.reused_existing_part
          ? t`This product already exists — no new product was created.`
          : data.part_name,
        color: data.reused_existing_part ? 'yellow' : 'green'
      });
      // Reset product fields
      setMolecule('');
      setDosage('');
      setLaboratory('');
      setForm('Solution');
      // Only offer to add a unit when a NEW product was actually created.
      // If it already existed, the user should use the Unit tab instead;
      // prompting here would reward a mistaken re-entry.
      if (!data.reused_existing_part && onCreated) {
        onCreated(data.part_id, data.part_name);
      }
    } catch (err: any) {
      notifications.show({
        title: t`Creation failed`,
        message: err?.response?.data?.error ?? t`Could not create the product.`,
        color: 'red'
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Stack gap='sm'>
      <Modal
        opened={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={t`Confirm new product`}
        centered
        size='sm'
      >
        <Stack gap='sm'>
          <Text size='sm'>{t`Create this product?`}</Text>
          <Alert color='blue' variant='light' p='xs'>
            <Text size='sm' fw={600}>{previewName}</Text>
            <Text size='xs' c='dimmed'>
              {t`Molecule:`} {molecule} · {t`Dosage:`} {dosage} · {t`Form:`} {form}
              {laboratory ? ` · ${t`Lab:`} ${laboratory}` : ''}
            </Text>
          </Alert>
          <Group justify='flex-end' gap='xs'>
            <Button variant='default' size='xs' onClick={() => setConfirmOpen(false)}>
              {t`Cancel`}
            </Button>
            <Button size='xs' color='teal' loading={submitting} onClick={doCreate}>
              {t`Confirm`}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Text fw={600}>{t`Create product`}</Text>

      <TextInput
        label={t`Molecule (DCI)`}
        placeholder='Paracétamol'
        value={molecule}
        onChange={(e) => setMolecule(e.currentTarget.value)}
        required
      />
      <TextInput
        label={t`Dosage / concentration`}
        placeholder='10 mg/ml'
        value={dosage}
        onChange={(e) => setDosage(e.currentTarget.value)}
        required
      />
      <Select
        label={t`Form`}
        data={['Solution', 'Poudre']}
        value={form}
        onChange={setForm}
        required
      />
      <TextInput
        label={t`Laboratory`}
        placeholder='B. Braun'
        value={laboratory}
        onChange={(e) => setLaboratory(e.currentTarget.value)}
      />

      {previewName && (
        <Alert color='blue' variant='light' p='xs'>
          <Text size='xs' c='dimmed'>{t`Product name will be:`}</Text>
          <Text size='sm' fw={600}>{previewName}</Text>
        </Alert>
      )}

      <Button
        mt='xs'
        leftSection={<IconCheck size={16} />}
        disabled={!canSubmit}
        onClick={() => setConfirmOpen(true)}
      >
        {t`Add product`}
      </Button>
    </Stack>
  );
}

// ---------------------------------------------------------------------------
// CREATE ITEM form
// ---------------------------------------------------------------------------

export function CreateItemForm({
  context,
  presetPartId,
  onRequestCreatePart
}: {
  context: InvenTreePluginContext;
  presetPartId?: number | null;
  onRequestCreatePart?: () => void;
}) {
  const [parts, setParts] = useState<PartOption[]>([]);
  const [partId, setPartId] = useState<string | null>(
    presetPartId ? String(presetPartId) : null
  );
  const [locations, setLocations] = useState<PartOption[]>([]);
  const [locationId, setLocationId] = useState<string | null>(null);
  const [batch, setBatch] = useState('');
  const [expiry, setExpiry] = useState('');   // stored as YYYY-MM (month input)
  const [received, setReceived] = useState('');
  const [quantity, setQuantity] = useState<number | string>(1);

  // Multiple tags -> multiple identical units (one per tag).
  const [tags, setTags] = useState<string[]>([]);
  const [scanning, setScanning] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const [partForm, setPartForm] = useState<string | null>(null);
  const [container, setContainer] = useState<string | null>(null);

  const containerOptions =
    partForm === 'Poudre'
      ? ['Flacon poudre']
      : partForm === 'Solution'
        ? ['Ampoule', 'Poche']
        : ['Ampoule', 'Poche', 'Flacon poudre'];

  const behaviour: 'whole' | 'quantity' =
    container === 'Poche' || container === 'Flacon poudre' ? 'quantity' : 'whole';
  const unitLabel = container === 'Poche' ? 'mL' : container === 'Flacon poudre' ? 'mg' : null;

  const readerConnected = useReaderStatus(context);

  // Load parts.
  useEffect(() => {
    let active = true;
    context.api
      .get('/api/part/?limit=500&ordering=name')
      .then((r) => {
        const results = r.data?.results ?? r.data ?? [];
        if (active)
          setParts(results.map((p: any) => ({ value: String(p.pk), label: p.name })));
      })
      .catch(() => active && setParts([]));
    return () => {
      active = false;
    };
  }, [context.api]);

  // Load stock locations.
  useEffect(() => {
    let active = true;
    context.api
      .get('/api/stock/location/?limit=500&ordering=name')
      .then((r) => {
        const results = r.data?.results ?? r.data ?? [];
        if (active)
          setLocations(
            results.map((l: any) => ({
              value: String(l.pk),
              label: l.pathstring || l.name
            }))
          );
      })
      .catch(() => active && setLocations([]));
    return () => {
      active = false;
    };
  }, [context.api]);

  useEffect(() => {
    if (presetPartId) setPartId(String(presetPartId));
  }, [presetPartId]);

  const CREATE_NEW = '__create_new__';
  const hasPart = !!partId && partId !== CREATE_NEW;
  const ready = hasPart && !!container && !!locationId;

  // Fetch the part's form when chosen.
  useEffect(() => {
    if (!hasPart) {
      setPartForm(null);
      setContainer(null);
      return;
    }
    let active = true;
    context.api
      .get(`/plugin/nfc/part-info/${partId}/`)
      .then((r) => {
        if (!active) return;
        const f = r.data?.form ?? null;
        setPartForm(f);
        if (f === 'Poudre') setContainer('Flacon poudre');
        else setContainer(null);
      })
      .catch(() => {
        if (active) {
          setPartForm(null);
          setContainer(null);
        }
      });
    return () => {
      active = false;
    };
  }, [partId, hasPart, context.api]);

  // Scan a tag and add it to the list (checking it isn't already linked).
  async function handleScan() {
    if (scanning) return;
    setScanning(true);
    try {
      const cfg = await getEffectiveConfig(context.api);
      playSound(cfg.sound_enabled, 'click');
      const scanned = await scanOnce(cfg.agent_base_url, cfg.scan_timeout_seconds);

      // Already in the current list?
      if (tags.includes(scanned)) {
        playSound(cfg.sound_enabled, 'error');
        notifications.show({
          title: t`Already added`,
          message: t`That tag is already in the list.`,
          color: 'orange'
        });
        return;
      }
      // Already linked to another unit?
      try {
        const check = await context.api.get(`/plugin/nfc/tag/${scanned}/`);
        if (check.data?.found) {
          playSound(cfg.sound_enabled, 'error');
          notifications.show({
            title: t`Tag already in use`,
            message: t`This tag is linked to another unit.`,
            color: 'red'
          });
          return;
        }
      } catch {
        /* lookup failed — allow, backend will validate */
      }

      setTags((prev) => [...prev, scanned]);
      playSound(cfg.sound_enabled, 'success');
      notifications.show({ title: t`Tag added`, message: scanned, color: 'green' });
    } catch {
      notifications.show({
        title: t`Scan failed`,
        message: t`Could not read a tag. Try again.`,
        color: 'red'
      });
    } finally {
      setScanning(false);
    }
  }

  function removeTag(uid: string) {
    setTags((prev) => prev.filter((u) => u !== uid));
  }

  async function handleSubmit() {
    if (!ready || submitting) return;
    if (!container) return;

    // Past-expiry warning (expiry is YYYY-MM; compare to current month).
    if (expiry.trim()) {
      const nowMonth = new Date().toISOString().slice(0, 7);
      if (expiry.trim() < nowMonth) {
        if (!window.confirm(t`This expiry date has already passed. Continue anyway?`))
          return;
      }
    }

    setSubmitting(true);
    try {
      // Dates are month inputs (YYYY-MM); store as first day of month.
      // Accept either 'YYYY-MM' (native month input) or 'MM-YYYY' (typed) and
      // normalize to the first day of that month for the backend date field.
      const toDate = (v: string): string | null => {
        const s = v.trim();
        if (!s) return null;
        let year: string, month: string;
        if (/^\d{4}-\d{2}$/.test(s)) {
          [year, month] = s.split('-');
        } else if (/^\d{2}-\d{4}$/.test(s)) {
          [month, year] = s.split('-');
        } else {
          return null; // unrecognized -> treat as empty
        }
        return `${year}-${month}-01`;
      };
      const expiryDate = toDate(expiry);
      const receivedDate = toDate(received);

      const body: Record<string, any> = {
        part_id: Number(partId),
        container_type: container,
        location_id: Number(locationId),
        batch: batch.trim(),
        expiry_date: expiryDate,
        received_date: receivedDate,
        quantity:
          behaviour === 'whole'
            ? 1
            : typeof quantity === 'string'
              ? parseFloat(quantity) || 0
              : quantity,
        uids: tags // may be empty -> creates a single untagged unit
      };

      const res = await context.api.post('/plugin/nfc/create-item/', body);
      const n = res.data?.created_count ?? 0;
      notifications.show({
        title: n > 1 ? t`Units created` : t`Unit created`,
        message: `${res.data.part_name ?? ''} — ${n}`,
        color: 'green'
      });
      // Reset per-unit fields, keep the part selected.
      setBatch('');
      setExpiry('');
      setReceived('');
      setQuantity(1);
      setTags([]);
    } catch (err: any) {
      notifications.show({
        title: t`Creation failed`,
        message: err?.response?.data?.error ?? t`Could not create the unit(s).`,
        color: 'red'
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Stack gap='sm'>
      <Text fw={600}>{t`Create unit`}</Text>

      <Select
        label={t`Product (part)`}
        placeholder={t`Search a product...`}
        searchable
        value={partId}
        onChange={(v) => {
          if (v === CREATE_NEW) {
            if (onRequestCreatePart) onRequestCreatePart();
            return;
          }
          setPartId(v);
        }}
        data={[{ value: CREATE_NEW, label: t`➕ Create new part` }, ...parts]}
        required
      />

      {!hasPart && (
        <Text size='xs' c='dimmed'>
          {t`Choose a product first to enable the unit fields.`}
        </Text>
      )}

      {hasPart && (
        <Select
          label={t`Container type`}
          description={
            partForm === 'Poudre'
              ? t`Powder → Flacon poudre (mg)`
              : partForm === 'Solution'
                ? t`Solution → Ampoule (whole) or Poche (mL)`
                : undefined
          }
          placeholder={t`Choose container`}
          data={containerOptions}
          value={container}
          onChange={setContainer}
          disabled={containerOptions.length === 1}
          required
        />
      )}

      {hasPart && (
        <Select
          label={t`Location`}
          placeholder={t`Choose a location`}
          searchable
          data={locations}
          value={locationId}
          onChange={setLocationId}
          disabled={!container}
          required
        />
      )}

      {ready && (
        <>
          <TextInput
            label={t`Lot number`}
            value={batch}
            onChange={(e) => setBatch(e.currentTarget.value)}
          />
          {behaviour === 'whole' ? (
            <Text size='xs' c='dimmed'>{t`Whole unit (ampoule) → quantity is 1.`}</Text>
          ) : (
            <NumberInput
              label={unitLabel ? `${t`Quantity`} (${unitLabel})` : t`Quantity`}
              min={0}
              value={quantity}
              onChange={setQuantity}
            />
          )}
          <MonthYearPicker
            label={t`Expiry`}
            value={expiry}
            onChange={setExpiry}
          />
          <MonthYearPicker
            label={t`Reception`}
            value={received}
            onChange={setReceived}
          />

          {/* Multiple tags — one unit will be created per tag */}
          <div>
            <Group align='end' gap='xs'>
              <Text size='sm' style={{ flex: 1 }}>
                {t`NFC tags`} ({tags.length})
              </Text>
              <ReaderDot connected={readerConnected} />
              <Button
                variant='light'
                leftSection={scanning ? <Loader size={14} /> : <IconWifi size={16} />}
                loading={scanning}
                disabled={!readerConnected}
                onClick={handleScan}
              >
                {t`Add tag`}
              </Button>
            </Group>
            {tags.length > 0 && (
              <Group gap={6} mt={6}>
                {tags.map((u) => (
                  <Badge
                    key={u}
                    variant='light'
                    rightSection={
                      <ActionIcon
                        size='xs'
                        variant='transparent'
                        onClick={() => removeTag(u)}
                        aria-label={t`Remove`}
                      >
                        ×
                      </ActionIcon>
                    }
                  >
                    {u}
                  </Badge>
                ))}
              </Group>
            )}
            <Text size='xs' c='dimmed' mt={4}>
              {tags.length > 0
                ? t`One identical unit will be created per tag.`
                : t`No tag: a single unit will be created without a tag.`}
            </Text>
          </div>
        </>
      )}

      {hasPart && !ready && (
        <Text size='xs' c='dimmed'>
          {t`Choose a container and a location to continue.`}
        </Text>
      )}

      <Button
        mt='xs'
        leftSection={<IconCheck size={16} />}
        disabled={!ready}
        loading={submitting}
        onClick={handleSubmit}
      >
        {tags.length > 1 ? `${t`Create`} ${tags.length} ${t`units`}` : t`Add unit`}
      </Button>
    </Stack>
  );
}


// ---------------------------------------------------------------------------
// CREATE TABS — container holding both forms with cross-tab handoff.
//   - Product created -> asks "add a unit?" -> switches to Item tab, part preset
//   - Item tab "create new part" -> switches to Product tab (no data carried)
// ---------------------------------------------------------------------------

export function CreateTabs({ context }: { context: InvenTreePluginContext }) {
  const [tab, setTab] = useState<string | null>('part');
  const [presetPartId, setPresetPartId] = useState<number | null>(null);

  // After a product is created, ask whether to add a unit for it.
  const [askUnitFor, setAskUnitFor] = useState<{ id: number; name: string } | null>(null);

  return (
    <>
      <Modal
        opened={!!askUnitFor}
        onClose={() => setAskUnitFor(null)}
        title={t`Product created`}
        centered
        size='sm'
      >
        <Stack gap='sm'>
          <Text size='sm'>
            {t`Add a physical unit for`} <strong>{askUnitFor?.name}</strong>?
          </Text>
          <Group justify='flex-end' gap='xs'>
            <Button variant='default' size='xs' onClick={() => setAskUnitFor(null)}>
              {t`No, done`}
            </Button>
            <Button
              size='xs'
              color='teal'
              onClick={() => {
                if (askUnitFor) {
                  setPresetPartId(askUnitFor.id);
                  setTab('item');
                }
                setAskUnitFor(null);
              }}
            >
              {t`Yes, add a unit`}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Stack gap='sm'>
        <SegmentedControl
          fullWidth
          size='md'
          value={tab ?? 'part'}
          onChange={setTab}
          data={[
            { value: 'part', label: t`Product` },
            { value: 'item', label: t`Unit` }
          ]}
        />

        {tab === 'part' ? (
          <CreatePartForm
            context={context}
            onCreated={(id, name) => setAskUnitFor({ id, name })}
          />
        ) : (
          <CreateItemForm
            context={context}
            presetPartId={presetPartId}
            onRequestCreatePart={() => setTab('part')}
          />
        )}
      </Stack>
    </>
  );
}
