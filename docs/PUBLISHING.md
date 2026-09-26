# Publishing and domains

The user pushed the new website to [NateOConnellPhD/nateoconnell.github.io](https://github.com/NateOConnellPhD/nateoconnell.github.io) with a fresh initial commit, `99aaebb`. Local `main` and `origin/main` matched when checked, and the old Hugo upgrade branches were removed. Future updates use ordinary commits and pushes; do not repeat the history-reset commands.

The professional domain is `nateoconnell.com`, registered at Namecheap. The blog is **Out-of-Bag Thoughts**, and the user also owns `outofbagthoughts.com`. Its address behavior (a separate blog deployment or a redirect) is pending the user's choice. No DNS or GitHub settings have been changed by the agent. Public website and DNS checks were blocked by this session's network restrictions.

## Professional domain: nateoconnell.com

The source is prepared with:

- `_config.yml`: `url: "https://nateoconnell.com"` and `baseurl: ""`.
- Root `CNAME`: `nateoconnell.com`.
- The new blog name on the homepage, blog index, post layout, About page, and feed.
- Local preview remains at `http://127.0.0.1:4000/`.

Connect the domain in this order:

1. In [GitHub account Pages settings](https://github.com/settings/pages), add `nateoconnell.com` as a verified domain. GitHub supplies a TXT record name and value. Enter those in the active DNS provider and complete verification. Do not invent the verification value; keep the TXT record afterward. [GitHub verification guide](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages).
2. Push the prepared source from the project directory:

   ```sh
   cd /Users/noconnell/Websites/Professional_Site &&
   git push origin main
   ```

   If the remote has newer edits from GitHub or Pages CMS, reconcile them before retrying; do not force-push.
3. Open [repository Pages settings](https://github.com/NateOConnellPhD/nateoconnell.github.io/settings/pages). The publishing source should be **Deploy from a branch**, `main`, `/ (root)`. Confirm **Custom domain** is `nateoconnell.com` before changing routing records. The committed `CNAME` records this domain for branch publishing. If GitHub creates a separate settings commit, pull it before the next local edit.
4. At Namecheap, open **Domain List → Manage** beside `nateoconnell.com`. Check its **Nameservers** setting. The **Advanced DNS → Host Records** instructions below apply to Namecheap BasicDNS, PremiumDNS, or FreeDNS. If it uses another provider's nameservers, edit records at that provider instead; do not change nameservers just to expose this panel.
5. Set the following records, with TTL **Automatic**:

| Type | Host | Value |
| --- | --- | --- |
| A Record | `@` | `185.199.108.153` |
| A Record | `@` | `185.199.109.153` |
| A Record | `@` | `185.199.110.153` |
| A Record | `@` | `185.199.111.153` |
| CNAME Record | `www` | `nateoconnellphd.github.io` |

Replace conflicting parking, redirect, or old web-host records for these same hosts. Preserve email/MX records, verification TXT records, and unrelated subdomains. Existing IPv6/AAAA records for these hosts must also target GitHub Pages or be removed if obsolete. [Namecheap's GitHub Pages instructions](https://www.namecheap.com/support/knowledgebase/article.aspx/9645/2208/how-do-i-link-my-domain-to-github-pages/), [GitHub domain and address documentation](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site).

6. After GitHub's DNS check and certificate provisioning complete, enable **Enforce HTTPS** in Pages settings. Check `https://nateoconnell.com` and the `www` redirect, navigation, portrait, CV, talk downloads, and RSS.

The old project URL was `https://nateoconnellphd.github.io/nateoconnell.github.io/`. The final domain serves the site at its root, so the repository name must not appear in internal paths or the Namecheap CNAME value.

## Blog domain: outofbagthoughts.com

Do not add a second domain to this repository's `CNAME`. GitHub Pages supports one custom domain per site, plus its corresponding `www` variant. DNS cannot send one domain to a website subdirectory. [GitHub domain limitations](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/troubleshooting-custom-domains-and-github-pages).

The user is choosing between:

- **A separate blog deployment:** `outofbagthoughts.com` stays in the address bar, including while reading posts. With GitHub Pages, this needs its own Pages site/repository and custom domain. Plan the content/editor arrangement before moving posts or creating another repository.
- **A redirect:** `outofbagthoughts.com` sends visitors to `https://nateoconnell.com/blog/`, and the address bar changes to that destination. Use an HTTPS-capable redirect service. Namecheap's basic forwarding documentation does not establish HTTPS support at the source domain; it distinguishes HTTP-to-HTTPS forwarding from HTTPS-to-HTTPS forwarding, which requires a certificate for both domains. [Namecheap redirect documentation](https://www.namecheap.com/support/knowledgebase/article.aspx/385/2237/how-to-set-up-a-url-redirect-for-a-domain/).

The source currently keeps the blog at `/blog/` while that choice is pending. Do not configure a masked/frame redirect.

## Browser editing

Sign in at [Pages CMS](https://app.pagescms.org), authorize its GitHub App for only the website repository, and choose `main`. It reads the existing `.pages.yml`. Connection has not been verified in this session. Complete the actual-device formatting and image checks in `EDITING.md` before treating mobile image pasting as verified.

## Remaining launch checks

- Confirm the domain resolves, GitHub Pages deploys successfully, and HTTPS is enabled.
- Choose and configure the blog's domain behavior.
- Review the layout on desktop and an actual phone.
- Complete Pages CMS draft, formatting, upload, and phone paste checks.
- Keep the two sample blog posts unpublished until replaced with real posts.
- Turn off `preview_mode` when ready for public indexing.
- Confirm drafts are absent from page listings, direct post URLs, and the feed.
- Add public manuscript URLs when available; current entries can remain labeled as work in progress.

The biography, headshot, selected research and clinical studies, three talks with materials, and web/downloadable CV are already supplied. Original reference documents remain in the ignored and Jekyll-excluded `Context_not_for_upload/` folder. Public repository drafts and media are publicly readable even when not listed on the website.
