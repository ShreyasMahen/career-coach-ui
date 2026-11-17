# Career Coach


## Quick Start

### Docker setup

Docker Desktop must be running with Linux containers. The project uses uv and the
existing `uv.lock` inside the image; your Windows `.venv` is excluded from the build.
You do not need to install PostgreSQL or RabbitMQ on Windows.

```powershell
# Optional: copy once to customize the defaults. Do not overwrite an existing .env.
Copy-Item .env.example .env
docker compose config --quiet
docker compose up --build -d
docker compose ps -a
Invoke-RestMethod http://localhost:5000/health
```

Compose waits for database/broker health and successful schema initialization before
starting the application. The initial schema command creates missing tables; it is
not a migration system for future schema changes. Neo4j is not needed until graph
projection is implemented. This is a local development server without authentication.

Do not add `--volumes` to `down` unless you intend to delete stored data. Changing
database/broker passwords in `.env` does not rotate credentials in existing volumes.
Default image tags pin major versions rather than immutable digests; dependency
installation uses the lockfile. No container downloads model weights during a build.

## Local datasets

Download your datasets separately and unzip archives first. The single
`ingest-dataset` command handles both CSV and XLSX, with explicit text/identity
columns rather than guessed field mappings. Example resume dataset import (adjust
column names to the file's header):

```powershell
docker compose run --rm --no-deps --volume C:/datasets:/datasets:ro api career-coach ingest-dataset /datasets/Resume.csv --kind resume --source resumes --text-column Resume_str --id-column ID --limit 20
```

For jobs, use `--kind job` and the description column. For HTML fields, add
`--format html`. For XLSX, pass its path and optionally `--sheet SheetName`.
XLSX formulas use existing cached values; no recalculation is performed.

The importer streams and archives the complete original dataset, then archives
individual selected text fields. Each run points back to the original hash, record
number, text column and worksheet. It emits run IDs for review. Records imported
before a malformed row remain available, and the command reports a partial failure.
Use a stable `--source` and ID column for repeat imports; without an ID column,
record numbers are identities and reordering the dataset changes their meaning.
Dataset imports perform extraction only; they do not evaluate extraction quality.
