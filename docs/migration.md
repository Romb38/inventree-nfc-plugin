# Install the NFC Plugin on the Existing InvenTree Server

Your InvenTree server is already working. Run these commands on the Debian server.

Repository: `https://github.com/Romb38/inventree-nfc-plugin` (public, no credentials needed)
Required InvenTree version: **1.7.0 or newer** (plugin 0.2.x)

> Upgrading a server that still runs InvenTree 1.5.x with the plugin installed
> from the old `Wassim-dxdydz/InvenTree` fork? Follow
> [Upgrade from InvenTree 1.5.x to 1.7.3](#upgrade-from-inventree-15x-to-173)
> instead: the order of the steps matters.

---

## 1. Go to your InvenTree Docker folder

This is the folder that contains `docker-compose.yml` and `.env`.

```bash
cd /opt/inventree
```

Check that you are in the right place:

```bash
ls -la
```

You must see:

```text
docker-compose.yml
.env
```

> If you used another folder when you installed InvenTree, use that folder instead of `/opt/inventree`.

---

## 2. Find the persistent InvenTree data folder

```bash
grep INVENTREE_EXT_VOLUME .env
```

Example output:

```text
INVENTREE_EXT_VOLUME=/opt/inventree/data
```

In the next commands, replace `/opt/inventree/data` with the path shown by your command if it is different.

---

## 3. Add your plugin to `plugins.txt`

Open the plugin list:

```bash
nano /opt/inventree/data/plugins.txt
```

Add this **single** line at the bottom, pinned on the release tag to install:

```text
inventree-nfc @ git+https://github.com/Romb38/inventree-nfc-plugin.git@v0.2.0
```

Save in nano:

```text
Ctrl+O  → Enter  → Ctrl+X
```

Check the result:

```bash
grep -i nfc /opt/inventree/data/plugins.txt
```

You must see exactly one line:

```text
inventree-nfc @ git+https://github.com/Romb38/inventree-nfc-plugin.git@v0.2.0
```

---

## 4. Install the plugin into the Docker containers

Run from `/opt/inventree`:

```bash
docker compose run --rm inventree-server invoke update
```

Wait until it finishes. This reads `plugins.txt`, installs the plugin from GitHub and applies the database migrations (InvenTree's and the plugin's).

If it succeeds, continue.

---

## 5. Restart InvenTree

```bash
docker compose restart inventree-server inventree-worker
```

---

## 6. Activate the plugin in the browser

1. Open your InvenTree website.
2. Log in as an administrator.
3. Go to **Settings → Plugins → Plugin Settings**.
4. Make sure plugins are enabled.
5. Find your NFC plugin.
6. Activate it.

Then refresh the page and open any Part. Your NFC panel should appear.

---

## 7. If the plugin does not appear

Run these commands:

```bash
cd /opt/inventree
docker compose logs inventree-server | grep -i nfc
docker compose logs inventree-worker | grep -i nfc
```

Also check that InvenTree installed the package:

```bash
docker compose exec inventree-server pip list | grep -i nfc
```

If the logs mention the plugin version requirement, the server runs InvenTree older than 1.7.0: upgrade InvenTree first (see below).

---

## 8. NFC reader agent — separate workstation step

The plugin runs on the company server. The USB NFC reader does not.

On each employee Linux computer that has the USB NFC reader connected:

```bash
git clone https://github.com/Romb38/inventree-nfc-plugin.git
cd inventree-nfc-plugin/agent
pip install -r requirements.txt
python agent.py
```

The browser on that same computer communicates with its local agent at `127.0.0.1` to read NFC tags. See `docs/installation.md` to run the agent as a service.

---

## Upgrade from InvenTree 1.5.x to 1.7.3

InvenTree 1.7.0 removed its legacy stock tracking table, which plugin 0.1.x
wrote its history into. Plugin 0.2.0 keeps its own history and, during the
upgrade, copies the existing NFC history into it. Follow these steps **in this
order**, with a single `invoke update` at the end:

1. **Back up** the database and media (mandatory — InvenTree's 1.7 stock
   migrations are one-way):

   ```bash
   cd /opt/inventree
   docker compose run --rm inventree-server invoke backup
   ```

   Keep a copy of the backup folder and of `.env` and `plugins.txt` outside the server.

2. **Publish the plugin release**: the `v0.2.0` tag must exist on
   `Romb38/inventree-nfc-plugin` before the server installs it.

3. **Switch the plugin source** in `/opt/inventree/data/plugins.txt`: remove
   every line pointing to `Wassim-dxdydz/InvenTree` (there may be two
   duplicated lines) and add the single line:

   ```text
   inventree-nfc @ git+https://github.com/Romb38/inventree-nfc-plugin.git@v0.2.0
   ```

4. **Switch the InvenTree version** in `/opt/inventree/.env`:

   ```text
   INVENTREE_TAG=1.7.3
   ```

5. **Pull the images and update once**:

   ```bash
   docker compose pull
   docker compose run --rm inventree-server invoke update
   docker compose up -d
   ```

   The update applies InvenTree's migrations, then the plugin's
   `nfc.0007_nfcevent` and `nfc.0008_backfill_nfcevent`. The latter prints how
   many history events it copied.

6. **Check**: the plugin is active in **Settings → Plugins**, scanning a tag
   works, the history of an existing unit shows its past events, and removing
   stock from a unit succeeds.

The package name (`inventree-nfc`), plugin slug (`nfc`) and Django app are
unchanged, so the existing NFC tags and links are kept as they are.

### Rollback

There is no rollback through migrations: InvenTree 1.7 has dropped the legacy
tracking table. To go back to 1.5.1, put back `INVENTREE_TAG=1.5.1` in `.env`
and the previous `plugins.txt`, then restore the backup from step 1 with the
1.5.1 image:

```bash
cd /opt/inventree
docker compose down
docker compose pull
docker compose run --rm inventree-server invoke restore
docker compose up -d
```

---

## Updating the plugin later

Push the new version with a new tag (e.g. `v0.2.1`), change the tag at the end
of the line in `plugins.txt`, then run on the server:

```bash
cd /opt/inventree
docker compose run --rm inventree-server invoke update
docker compose restart inventree-server inventree-worker
```

Do not run `pip install` manually inside a Docker container; container-only changes disappear when the container is recreated. `plugins.txt` is the persistent installation source. InvenTree supports Docker plugin installation through `plugins.txt` in the external data directory.
