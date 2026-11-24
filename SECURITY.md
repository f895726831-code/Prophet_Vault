# Security policy

## What this tool does with your data

`prophet-vault` is a **local, offline** file translator:

- it **reads** a Prophet workspace (`.PRW`, optional `.RCI`) from your disk;
- it **writes** CSV snapshots, Markdown pages and an HTML page to the folders you pass on
  the command line;
- it makes **no network calls** of its own. The generated HTML page loads ECharts from a
  CDN unless you inline it with `--echarts`;
- it leaves the model untouched - no `.PRW` is ever opened for writing.

## Credentials

The Firebird SYSDBA password is read from `PROPHET_ISQL_PASS` (default `masterkey`, the
Firebird installer default) and passed to `isql.exe` as a command-line argument. It is
never written to disk by this tool. Note that a command-line argument is visible to other
processes on the same machine for the lifetime of the call; on a shared machine, prefer a
local, unshared account.

Snapshots contain model metadata - variable names, formulas and descriptions - which is
commercially sensitive in most insurers. **Do not publish a snapshot or a vault generated
from a real model.** `.gitignore` excludes the common file types and the default output
folders, but the decision is yours.

## Supported versions

Security fixes are applied to the latest release on `main`.

## Reporting a vulnerability

Please **do not open a public issue** for a vulnerability.

Use GitHub's private reporting channel: **Security → Report a vulnerability** on
<https://github.com/f895726831-code/Prophet_Vault/security/advisories/new>.

Include:

- what the issue is and which file or command triggers it;
- a minimal reproduction (a redacted model or a generated page is usually enough);
- the version (`prophet-vault --version`) and platform.

Expect an acknowledgement within a few days. There is no bug bounty.
