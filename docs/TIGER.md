# Running Paritty on Tiger Cloud

Local Docker (`FORK_BACKEND=template`) stays the default and is unchanged. This page covers the Tiger Cloud path (`FORK_BACKEND=tiger`).
Checked with Tiger CLI 0.26.0 against a free-plan service (PostgreSQL 18.6, TimescaleDB 2.30.2) on 2026-10-11.

## Setup
1. Install and log in: `brew install --cask timescale/tap/tiger-cli`, then `tiger auth login`.
2. Create a service for Paritty only: `tiger service create --name lockstep-golden --cpu shared --no-set-default`.
   Do not reuse a service that holds other data: every eval fork copies the whole service, and `make reset` truncates Paritty's tables.
3. Create the answer-key login **before** migrating, with your own password:
   `CREATE ROLE eval_admin LOGIN PASSWORD '<strong password>'` (as `tsdbadmin`).
   Migration 009 creates this role with the local-dev password only when it is missing, and a Tiger service is reachable from the internet.
4. `.env` (gitignored):
   ```
   DATABASE_URL=postgresql://tsdbadmin:<password>@<host>:<port>/tsdb?sslmode=require     # tiger db uri <id> --with-password
   EVAL_ADMIN_URL=postgresql://eval_admin:<password>@<host>:<port>/tsdb?sslmode=require
   GOLDEN_SERVICE_ID=<service id>
   FORK_BACKEND=tiger
   ```
5. `make setup migrate seed` (`make db` does nothing when `.env` says `FORK_BACKEND=tiger`), then `make demo`.

## What differs from local Docker
| | Local Docker | Tiger Cloud |
|---|---|---|
| Admin user | `app_admin`, superuser | `tsdbadmin`: not a superuser, may create roles and databases |
| Extensions | shipped in the image | `timescaledb`, `vector`, `vectorscale`, `pg_textsearch` all available; migration 001 installs them unchanged |
| Migrations 001-014 | apply | apply unchanged (role creation, grants, RLS policies, continuous aggregates) |
| Golden source for forks | database `lockstep_golden`, copied by `make golden` | the service itself (`GOLDEN_SERVICE_ID`); `make golden` only restores the seeded state |
| A fork | `CREATE DATABASE ... TEMPLATE`, about 0.2 s | `tiger service fork`: a whole new service with its own host, port and `tsdbadmin` password |
| State a fork starts from | the snapshot taken by `make golden` | the service as it is at fork time, so `TigerForkManager` runs `reset` on the fork first |

## How forks are made (`backend/app/evals/fork_manager.py`)
- Create: `tiger service fork <GOLDEN_SERVICE_ID> --name <name> --no-set-default --with-password --wait-timeout 30m --output json`.
  Without `--with-password` the output has no password; without `--no-set-default` every fork becomes the CLI's default service.
- The connection is built from the JSON keys `host`, `port`, `database`, `role`, `password`; the service is identified by `service_id`.
- The `eval_admin` URL for the fork is `EVAL_ADMIN_URL` with the fork's host and port.
- Delete: `tiger service delete <service_id> --confirm`. If creating a fork fails at any point, the manager deletes by name, so a half-made service is not left behind.
- The harness holds one fork at a time (the control fork is deleted before the injected fork is created).

## Limits and cost
- **The free plan allows two services per project.** The golden service uses one, so a project with any other service has no room for a fork: `tiger service fork` fails with "You have reached your free service limit". An eval needs one free slot.
- On paid plans every fork is a billable service for as long as it exists; an eval run creates two, one after the other.
- Measured on the free plan: a fork took 27.8 s (a local template fork takes 0.14 s) and the smoke eval took 13 minutes end to end (about 1 minute locally), because every query of the simulation is a network round trip. Use Tiger forks for a final measured run and local forks for iteration.

## What was and was not verified
See "Tiger Cloud" in `docs/DECISIONS.md`.
