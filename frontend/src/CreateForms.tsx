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
import {
  createItem,
  createProduct,
  fetchLocations,
  fetchPartInfo,
  fetchParts,
  findByTag
} from './api';
import type { PartOption } from './types';
import { scanOnce } from './agent';
import { useReaderStatus } from './hooks';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/**
 * Extract a human-readable message from any DRF/InvenTree error payload:
 * a plain string, { error: "..." }, or { field: ["msg", ...] }.
 */
function extractError(err: any, fallback: string): string {
  const data = err?.response?.data;
  if (!data) return fallback;
  if (typeof data === 'string') return data;
  if (typeof data.error === 'string') return data.error;
  // Field-keyed errors like { location: ["..."] } or { detail: "..." }
  const parts: string[] = [];
  for (const key of Object.keys(data)) {
    const val = data[key];
    if (Array.isArray(val)) parts.push(val.join(' '));
    else if (typeof val === 'string') parts.push(val);
  }
  return parts.length ? parts.join(' — ') : fallback;
}

/**
 * Parse a month/year string in any of: mm-yyyy, mm/yyyy, yyyy-mm, yyyy/mm.
 * Returns { ym: 'YYYY-MM' } on success, { error } when invalid, {} when empty.
 * Month must be between 01 and 12.
 */
function parseMonthYear(input: string): { ym?: string; error?: string } {
  const s = (input || '').trim();
  if (!s) return {};

  const parts = s.split(/[-/]/);
  if (parts.length !== 2 || parts.some((p) => !/^\d+$/.test(p))) {
    return { error: 'Use mm-yyyy, mm/yyyy, yyyy-mm or yyyy/mm.' };
  }

  let year: number;
  let month: number;
  if (parts[0].length === 4) {
    year = Number(parts[0]);
    month = Number(parts[1]);
  } else if (parts[1].length === 4) {
    month = Number(parts[0]);
    year = Number(parts[1]);
  } else {
    return { error: 'Year must have 4 digits (e.g. 2027).' };
  }

  if (month < 1 || month > 12) return { error: 'Month must be between 01 and 12.' };
  if (year < 2000 || year > 2100) return { error: 'Year must be between 2000 and 2100.' };
  return { ym: `${year}-${String(month).padStart(2, '0')}` };
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
      const data = await createProduct(context.api, {
        molecule: molecule.trim(),
        dosage: dosage.trim(),
        form,
        laboratory: laboratory.trim(),
        add_unit: false // Part-only; the unit (with its container) is created in the Item tab.
      });
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
        message: extractError(err, t`Could not create the product.`),
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
    fetchParts(context.api)
      .then((opts) => active && setParts(opts))
      .catch(() => active && setParts([]));
    return () => {
      active = false;
    };
  }, [context.api]);

  // Load stock locations.
  useEffect(() => {
    let active = true;
    fetchLocations(context.api)
      .then((opts) => active && setLocations(opts))
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
    fetchPartInfo(context.api, partId)
      .then((data) => {
        if (!active) return;
        const f = data?.form ?? null;
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
        const check = await findByTag(context.api, scanned);
        if (check?.found) {
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

    setSubmitting(true);
    try {
      // Parse & validate the month/year fields (4 formats, month 01–12).
      const expiryParsed = parseMonthYear(expiry);
      if (expiryParsed.error) {
        notifications.show({
          title: t`Invalid expiry date`,
          message: expiryParsed.error,
          color: 'red'
        });
        setSubmitting(false);
        return;
      }
      const receivedParsed = parseMonthYear(received);
      if (receivedParsed.error) {
        notifications.show({
          title: t`Invalid reception date`,
          message: receivedParsed.error,
          color: 'red'
        });
        setSubmitting(false);
        return;
      }
      const expiryDate = expiryParsed.ym ? `${expiryParsed.ym}-01` : null;
      const receivedDate = receivedParsed.ym ? `${receivedParsed.ym}-01` : null;

      // Past-expiry warning (compare parsed YYYY-MM to the current month).
      if (expiryParsed.ym) {
        const nowMonth = new Date().toISOString().slice(0, 7);
        if (expiryParsed.ym < nowMonth) {
          if (!window.confirm(t`This expiry date has already passed. Continue anyway?`)) {
            setSubmitting(false);
            return;
          }
        }
      }

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

      const data = await createItem(context.api, body);
      const n = data?.created_count ?? 0;
      notifications.show({
        title: n > 1 ? t`Units created` : t`Unit created`,
        message: `${data.part_name ?? ''} — ${n}`,
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
        message: extractError(err, t`Could not create the unit(s).`),
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
          <TextInput
            label={t`Expiry`}
            description={t`mm-yyyy, mm/yyyy, yyyy-mm or yyyy/mm`}
            placeholder='mm-yyyy'
            value={expiry}
            onChange={(e) => setExpiry(e.currentTarget.value)}
          />
          <TextInput
            label={t`Reception`}
            description={t`mm-yyyy, mm/yyyy, yyyy-mm or yyyy/mm`}
            placeholder='mm-yyyy'
            value={received}
            onChange={(e) => setReceived(e.currentTarget.value)}
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
