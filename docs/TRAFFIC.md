# Website traffic

Open **Traffic** in the editor sidebar after signing in at <https://nateoconnell.com/login>. Choose the whole website or blog posts and enter the **number of days** you want, including today. Enter 1 for today only, or another positive whole number such as 14, 45, or 90. Press Enter or select **Reload report**. Select a page to see its daily views. Sort the page list or search for a post by title.

There is no preset 28-day ceiling. The editor reads the account's actual retention and per-query duration from [Cloudflare's settings node](https://developers.cloudflare.com/analytics/graphql-api/features/discovery/settings/), caching those settings for a day. Longer reports are split into non-overlapping requests within those limits and combined. If the requested dates exceed available history, the error states the maximum number of calendar days available. Cloudflare [documents six months of Web Analytics history](https://developers.cloudflare.com/web-analytics/faq/#what-is-the-period-of-time-i-can-access-data-in-web-analytics); the connected account's API settings determine the actual limit. The editor does not archive traffic permanently.

## Connect once

The website stays on GitHub Pages and the domain stays at Namecheap. This uses Cloudflare’s free browser analytics, without moving DNS or proxying the site. Follow the [official manual setup](https://developers.cloudflare.com/web-analytics/get-started/#sites-not-proxied-through-cloudflare):

1. In Cloudflare, open **Web Analytics → Add a site**, enter `nateoconnell.com`, select the hostname and finish.
2. Open **Manage site** and copy the JavaScript snippet. Its `data-cf-beacon` contains a public `token`. Put that value in `_data/analytics.yml` as `beacon_token` and set `enabled: true`. Do not also paste the snippet into another layout: the existing include loads it once.
3. Identify the **account ID** and this Web Analytics property’s **site tag**. The site tag is not the beacon token. If the dashboard does not show the tag clearly, the [List Web Analytics sites API](https://developers.cloudflare.com/api/resources/rum/subresources/site_info/methods/list/) returns `site_tag`, `site_token`, and hostname rules. That lookup requires an account-scoped token with **Account Settings: Read**; it is not needed for routine reports.
4. Create an account-scoped API token with **Account Analytics: Read**, following [Cloudflare’s analytics authentication guide](https://developers.cloudflare.com/analytics/graphql-api/getting-started/authentication/api-token-auth/). Scope it to the account containing this property. Do not use a global API key.
5. Add these **Production** environment variables to the editor project in Vercel:

   | Variable | Value |
   | --- | --- |
   | `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID |
   | `CLOUDFLARE_WEB_ANALYTICS_SITE_TAG` | Web Analytics property’s `site_tag` |
   | `CLOUDFLARE_ANALYTICS_TOKEN` | Read-only reporting API token |

6. Publish the website changes and redeploy the editor after saving its environment variables. Never put the reporting API token in Git, browser code, or chat. Only the beacon token is public.
7. Visit a public page with tracking allowed. After Cloudflare processes the visit, open **Traffic** and compare its report with Cloudflare’s Web Analytics dashboard. Verify both a normal page and a blog post. The live GraphQL query, permissions, collection and bot fields must be verified against the connected account during setup; local fixtures are not a live integration test.

Tracking starts after the configured beacon is deployed. Past traffic cannot be recovered. A missing reporting connection shows setup instructions; a failed provider query shows an error, not zero visits. A successful report with no events shows zero recorded views.

## What is measured

- A view is a recorded browser page load, not a unique person. Your own public-site visits count too.
- **Detected bots** are visits Cloudflare flags. **Not flagged as bots** is not a verified human count. Unknown classification values appear as **Unclassified**.
- Crawlers that never execute JavaScript are absent, as are blocked beacons. Measuring those requests would require a separate edge/server traffic service, not this browser tracker. See [Cloudflare’s collection limitations](https://developers.cloudflare.com/web-analytics/faq/).
- The beacon runs only on the HTTPS public domain, not the editor, local previews, embedded previews, or `/login`. This implementation also honors browser Do Not Track and Global Privacy Control signals. Draft/example pages do not include the beacon.
- Calendar days are in UTC and include the partially completed current day. Reports can be sampled; counts are provider estimates and separately aggregated totals may differ. We do not multiply already-weighted counts by sampling intervals.
- The page list is capped at 1,000 provider groups (a page can have multiple bot classes). A warning appears at that limit; overall and daily totals are queried independently.
- Blog titles come from the public `traffic-posts.json` catalog, generated from published, non-example posts. If it is unavailable, observed URLs still work. The catalog can take up to an hour to refresh in a running editor instance.

## Cost and access

No OpenAI calls, per-visit GitHub writes, new database, or dependency is involved. Visitors send analytics to Cloudflare, not the editor API. Reports are fetched only when opened or changed; there is no automatic polling. Matching requests share an in-flight query and then a five-minute cache. The cache is bounded and in memory per Vercel instance, so cold starts or separate instances can query again. Provider failures are not cached as successful reports.

The server requires the existing owner-only encrypted GitHub session before it reads analytics. Credentials stay server-side, and report responses have `Cache-Control: no-store`. A public visitor can load the empty dashboard shell, but cannot read reports. Publishing/deployment and live account verification are separate from local source checks.
