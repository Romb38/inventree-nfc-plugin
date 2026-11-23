# InvenTree NFC Plugin

An InvenTree plugin for managing pharmaceutical lab stock with NFC tags. Each
physical unit (an ampoule, a septum bag, a powder vial) carries an NFC tag.
Scanning a tag instantly identifies the unit, shows its details, and lets staff
adjust or consume stock, link/unlink tags, and review a full history of who did
what and when.

The plugin is designed for a shared InvenTree server accessed from several
workstations, each with its own USB NFC reader.

---

## What it does

- **Scan a tag** to identify the physical unit and its product, see its lot,
  expiry, reception date, location and remaining quantity, plus the other units
  of the same product.
- **Create products and units** directly from the panel, including creating
  **several identical units at once** (one per scanned tag).
- **Adjust stock**: remove quantity from quantity-tracked units (bags, vials),
  or mark a whole unit (ampoule) as used.
- **Out of stock**: when a unit reaches zero it is kept as an out-of-stock
  record (never auto-deleted) and its tag stays linked until someone unlinks it.
- **Link / unlink tags** from the unit page — available to any logged-in user.
- **History**: every creation, stock change, link and unlink is recorded with
  the user, timestamp and amount, viewable per unit.
- **Per-workstation agent settings**: each machine configures its own local
  agent URL and scan timeout, stored in that browser.

---

## How it works

The plugin has three parts:

```
                  Browser (InvenTree UI + plugin)
                                  ↓
                    Local NFC agent (localhost)
                                  ↓
                            USB reader

        served by the server            runs on each workstation
```


- The **server** runs InvenTree and this plugin. It never talks to the readers.
- The **agent** is a small local process on each workstation that talks to the
  USB reader over PC/SC and exposes a tiny HTTP API on `localhost`.
- The **browser**, on each workstation, calls its *own* local agent at
  `http://localhost:8765` to scan. Because "localhost" is machine-relative, the
  same UI works on every workstation, each reaching its own reader.

---

## Structure

```
nfc/
├── agent/                  # Local NFC agent (runs on each workstation)
│   ├── agent.py            # Flask app: /health and /scan/once, talks to PC/SC
│   └── requirements.txt
├── frontend/               # React UI (built into nfc/static/)
│   └── src/
│       ├── Panel.tsx        # Main panel: scan, stock actions, history
│       ├── CreateForms.tsx  # Create product / create unit(s) forms
│       ├── Dashboard.tsx    # Dashboard scan widget
│       ├── Settings.tsx     # Per-workstation agent settings
│       ├── Spotlight.tsx    # Spotlight scan action
│       ├── agentConfig.ts   # Per-workstation config (localStorage) helper
│       ├── locale.tsx       # i18n provider
│       ├── sound.ts         # Scan sound effects
│       └── locales/         # Translation catalogs
└── nfc/                    # Django / InvenTree plugin package
    ├── core.py              # Plugin entry point (NFC class) + URL routes
    ├── models.py            # NFCTagLink (tag <-> stock item), NFCEvent (history)
    ├── views.py             # API endpoints (scan, link, stock, create, history)
    ├── migrations/          # Database migrations
    └── tests/               # pytest suite
```

The plugin entry point is `nfc.core:NFC`. The frontend build output is written
into `nfc/static/`, which InvenTree serves.

### Data model

- A **Part** is a precise product (molecule + laboratory + dosage + form), e.g.
  "Paracétamol B. Braun 10 mg/ml Solution".
- A **StockItem** is one physical unit of that product, with its own lot,
  expiry, reception date, location, quantity and **container type**.
- An **NFCTagLink** links one tag UID to one StockItem. A tag maps to a single
  active unit; a unit has a single active tag.
- An **NFCEvent** records one action done through the plugin on a unit
  (creation, stock change, consumption, tag link/unlink) with its user and
  date. It is the only source of the history shown in the panel, and is kept
  by the plugin independently from InvenTree's own stock history.

Container types drive behaviour: **Ampoule** (whole unit, consumed at once),
**Poche** (bag, tracked in mL) and **Flacon poudre** (powder vial, tracked in
mg).

---

## Quick installation

There are two things to install: the **plugin** (once, on the server) and the
**agent** (on each workstation with a reader). Full details are in
`docs/installation.md` and `docs/migration.md`.

### Plugin (server)

Requires **InvenTree 1.7.0 or newer** (plugin 0.2.x). The plugin refuses to
activate on older versions.

On the machine running InvenTree via Docker, from the folder that holds
`docker-compose.yml`, add **one** line, pinned on a release tag, to the
persistent plugin list (`plugins.txt` in the `INVENTREE_EXT_VOLUME` folder):

```text
inventree-nfc @ git+https://github.com/Romb38/inventree-nfc-plugin.git@v0.2.0
```

Then install it into the containers:

```bash
docker compose run --rm inventree-server invoke update
docker compose restart inventree-server inventree-worker
```

Then in the browser: **Settings → Plugins**, enable plugins if needed, find the
NFC plugin and activate it. Open any Part or Stock Item — the NFC panel appears.

Upgrading an existing server from InvenTree 1.5.x: follow the ordered procedure
in `docs/migration.md` (backup first — InvenTree's 1.7 migrations cannot be
reverted).

For a development install (editable, from the repo root):

```bash
pip install -e .
cd frontend && npm install && npm run build
```

### Agent (each workstation)

On each Linux workstation that has a USB NFC reader:

```bash
sudo apt-get install -y libpcsclite-dev libpcsclite1 pcscd pcsc-tools libccid
# pyscard needs the Python headers matching your version, e.g. on Debian 13:
sudo apt-get install -y python3.13-dev   # python3.11-dev on Debian 12, etc.
git clone https://github.com/Romb38/inventree-nfc-plugin.git
cd inventree-nfc-plugin/agent
pip install -r requirements.txt
python agent.py        # serves http://127.0.0.1:8765
```

Confirm the reader is seen with `pcsc_scan`. If `pip install` fails to compile
`pyscard`, the matching `python3.X-dev` package is missing. To run the agent
automatically on boot, install it as a systemd service (see
`docs/installation.md`).

**On Windows** the agent works too: the reader uses the built-in Windows Smart
Card service (no extra driver), and you keep the agent alive as a service with
[NSSM](https://nssm.cc/) pointed at a virtualenv's `python.exe` running
`agent.py`. See `docs/installation.md` for the step-by-step Windows setup.

---

## Usage (short)

1. Start the agent on the workstation; make sure the reader status dot is green.
2. Open the NFC panel (on a Part or Stock Item page, or the dashboard widget).
3. **Scan** a tag to identify a unit, or use **Create** to add products/units.
4. On a scanned unit you can **remove stock**, **mark an ampoule as used**,
   **link/unlink** its tag, and **show its history**.

See `docs/usage.md` for the full walkthrough and `docs/troubleshooting.md` if
the reader status stays red.

---

## Development

- Backend: Python / Django (InvenTree plugin). Tests: `pytest nfc/tests/`.
- Frontend: React + Mantine, built with Vite. `npm run build` in `frontend/`
  produces the assets InvenTree serves; rebuild and hard-refresh after changes.
- Translations: edit the `.po` files under `frontend/src/locales/`, then
  `npm run extract && npm run compile && npm run build`.

---

## Notes

- The agent URL and scan timeout are configured **per workstation** in the
  plugin settings (stored in that browser), with a built-in default of
  `http://127.0.0.1:8765` and 30 seconds.
- All stock and tag actions are attributable: the history records the user,
  time and amount for every change.