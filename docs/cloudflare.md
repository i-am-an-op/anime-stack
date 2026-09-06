# Cloudflare administration access

Use one **named, remotely managed Tunnel** with two full-hostname Access applications. Only web administration goes through it; SFTP and BitTorrent do not. Complete private bootstrap before connecting a public route.

Examples use `example.com`, `owner@example.com` and a placeholder team. Replace them with your own values privately. Never commit generated account-specific payloads.

## Protection to configure

| Hostname | Origin | Policy |
| --- | --- | --- |
| `anime.example.com` | `http://autobangumi:7892` | Exact owner email + independent MFA |
| `qb.example.com` | `http://qbittorrent:8080` | Exact owner email + independent MFA |

Change the qBittorrent origin port if `QB_WEB_PORT` differs. Keep the incoming public Host, Origin and Referer intact. Do not disable qBittorrent CSRF or Host validation to work around a proxy error. Its trusted reverse proxy is limited to `PROXY_ADDRESS`.

Use eight-hour Access and MFA sessions, HttpOnly and SameSite Lax Access cookies, and binding cookies. Do not add Everyone, Bypass, Service Auth or preflight bypass policies for interactive administration.

## Organization and MFA

Create a Zero Trust team if needed and configure an identity provider. Email one-time codes can provide initial login. Separately enable independent MFA under **Zero Trust → Access controls → Access settings**. Select authenticator apps, biometrics and/or security keys and an eight-hour authentication duration. Global default enforcement can stay as previously configured; require MFA explicitly on these applications and their owner policy.

Cloudflare account-login MFA is not the same as Access application MFA. [Independent MFA must be enabled at organization level](https://developers.cloudflare.com/cloudflare-one/access-controls/access-settings/independent-mfa/) before a policy can require it. Match application/policy authenticator lists to enabled organization methods. Users enroll through their team's App Launcher or `https://YOUR-TEAM.cloudflareaccess.com/AddMfaDevice`.

## Temporary API permissions

The dashboard is sufficient for setup. For API-assisted setup, use a short-lived token scoped only to the selected account and zone:

| Scope | Permission | Use |
| --- | --- | --- |
| Account | Cloudflare Tunnel Edit | Create/configure the tunnel and retrieve its connector token |
| Account | Access: Apps and Policies Edit | Create applications and an exact-owner Allow policy |
| Account | Access: Organizations, Identity Providers, and Groups Read | Inspect team and login methods |
| Account | The same organization permission, Edit | Needed only when enabling/changing organization MFA via API |
| Zone | Zone Read | Resolve the zone/account |
| Zone | DNS Edit | Create the two proxied CNAME records |
| Zone | Cache Rules Edit | Add the exact-host cache bypass |

Keep this management token outside deployment `.env` and outside the server's runtime directories. Use a private local credential file or secret manager when making API requests. Never pass a token as a literal command-line argument, include it in shell history or print API responses from token-creation endpoints. A global API key is unnecessary. Scoped permission changes may take a short time to propagate.

## Apply in this order

1. Inspect existing DNS, applications (including wildcards/paths), policies, team settings, tunnels and cache rules. Preserve unrelated resources and stop on a name conflict.
2. Enable organization MFA if necessary. For an API update, retain the current organization fields; do not reset unrelated settings.
3. Create one reusable Allow policy containing only your exact email and requiring the selected MFA methods. Create the two full-hostname applications with only that policy. Read back policy, MFA and cookie settings and each application's `aud`.
4. Create a named tunnel with `config_src: cloudflare`. An initial catchall `http_status:404` lets you test connectivity before publishing any application. Retrieve its separate connector token into `DATA_DIR/secrets/cloudflared-token`, owner PUID, mode **0600**.
5. Configure each application ingress with its own required Access JWT validation. Set `teamName` to the team without `.cloudflareaccess.com` and `audTag` to that application's AUD. Keep a final unmatched 404 route. Do not rely on a single global Access setting.
6. Add a cache rule with expression `(http.host in {"anime.example.com" "qb.example.com"})`, action `set_cache_settings` and `cache: false`. Preserve existing rules and place this rule after other matching cache rules. Zone Cache Rules Edit was sufficient in the reference setup.
7. Fill `QB_PUBLIC_HOST` and `AB_PUBLIC_HOST` in `.env`, then run `python3 scripts/manage.py cloudflare`. It reapplies the allowed hostnames, checks the private bootstrap and token file permissions, and starts the connector. It does **not** configure your Cloudflare account or attest that your Access policies are correct.
8. After the protection readback passes, create two **proxied CNAMEs**, each targeting `TUNNEL_ID.cfargotunnel.com`. Verify HTTP redirects to HTTPS. Configure a host-specific HTTPS redirect if your zone does not already provide one.
9. Verify anonymous requests and invalid sessions reach Access rather than either application. Complete owner login, actual MFA enrollment, app login, a harmless qBittorrent mutation and AutoBangumi live event updates. Configuration readback and anonymous tests alone do not prove the complete owner flow.
10. Save effective resource IDs and configuration under `DATA_DIR/cloudflare/current/` for encrypted backup. Revoke the temporary management token after acceptance. Keep the connector token private; it remains necessary to run the tunnel.

## Payload renderer

Copy `cloudflare/settings.example.json` to the ignored `cloudflare/settings.local.json`, fill your settings, and render into an ignored directory:

```sh
python3 scripts/render_cloudflare.py cloudflare/settings.local.json cloudflare/rendered
```

The numbered example payloads show request bodies. The renderer makes no network requests, and response-dependent IDs must be filled after each creation step. Set optional `qbittorrent_port` when using a custom port. Authenticator methods in the supplied examples are TOTP, biometrics and security keys; edit them to match your organization.

Use account endpoints `/accounts/ACCOUNT_ID/access/policies`, `/access/apps`, and `/cfd_tunnel`; tunnel configuration is `PUT /accounts/ACCOUNT_ID/cfd_tunnel/TUNNEL_ID/configurations`. Use zone endpoints for DNS and the `http_request_cache_settings` ruleset. Consult the linked API references for current request schemas instead of treating example placeholders as usable IDs.

## Troubleshooting and withdrawal

The connector needs outbound DNS, HTTPS for token validation, and TCP/UDP 7844 to Cloudflare. No inbound 80/443 ports are required. Use a named tunnel; quick tunnels have different capabilities and are not the deployment target.

To withdraw the public origin immediately, run `docker compose --profile cloudflare stop cloudflared`. SSH and the application containers remain available. Repair the protection/configuration before restarting. Do not introduce a bypass policy as a login diagnostic.

Primary references: [remote Tunnel API](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel-api/), [origin Access validation](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/#access), [connector token file](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/#token-file), [MFA application/policy requirements](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/mfa-requirements/), [cache rule API](https://developers.cloudflare.com/cache/how-to/cache-rules/create-api/).
