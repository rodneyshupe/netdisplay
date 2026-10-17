# Snippets

Page fragments for setups that need metrics the common exporters don't provide. Each file is a **complete config**, so
`netdisplay -c examples/snippets/<file> validate` checks it against your datasource, but you normally copy the
`pages:` entry (plus any `alerts.rules` and `vars:`) into your own config.

| File | Page | Needs |
|---|---|---|
| [`technitium-dns.yaml`](technitium-dns.yaml) | DNS stats and per-node status for Technitium DNS | `technitium_*` series pushed by your own script (the file header lists them) |
| [`authentik-ha.yaml`](authentik-ha.yaml) | Which node is the master of an Authentik HA cluster, and whether everything is healthy | [`contrib/authentik_metrics.sh`](../../contrib/README.md) on each node |

Both use `hide_if_empty: true`, so if the metrics aren't there the page simply doesn't appear.
