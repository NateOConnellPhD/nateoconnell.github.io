# Private website workspace

An online editing workspace for `NateOConnellPhD/nateoconnell.github.io`. The public site stays on GitHub Pages; this editor runs separately on Vercel. Jekyll excludes this directory from the website output.

After publishing the login shortcut, open **https://nateoconnell.com/login**. It redirects to https://nateoconnellgithubio-website-editor.vercel.app/, where you sign in with GitHub. No DNS change or new account is needed for that shortcut.

## Working on the website

The opening screen is a conversation about the whole website. You can ask questions, discuss options, change which papers are highlighted and their order, add pages and navigation, change layouts, write posts, edit CSS/JavaScript, change build configuration, or work on the editor itself. Your message appears immediately; assistant replies and progress arrive through an authenticated event stream. You can type your next message while it works, stop the response, and continue the conversation after it finishes. Enter sends; Shift+Enter adds a line. Questions and source changes use direct file tools against GitHub and the private proposed changes. A temporary Linux workspace is requested only for commands, computation, binary processing, or a rendered preview. No additional hosting service is required.

Saved conversations appear in the left sidebar. The conversation scrolls independently of the message composer, which stays at the bottom. Replies follow the scroll position only while you are near the latest message; **Latest message** returns you there after reading earlier text. On phones, the menu button opens conversation history.

Each saved chat has a **Delete** button, including on phones. Confirming removes that conversation, its unpublished file changes, and its saved preview from current private storage and the history list. It does not change the published website or other chats. Stop an active response and finish any pending remote cleanup before deleting its chat. Older versions remain in the private repository's Git history; this action does not rewrite history or purge provider retention records.

**Files & changes** opens a separate project panel with the folder tree, pending changes, file editor, and any built preview. Files can be created, edited, moved, deleted, and uploaded there. The Content and Drafts tabs retain the structured writing forms, formatting buttons, image picker/paste handler, and optional page-specific writing assistant. Those document drafts are separate from the main chat's working changes. The plus button in the message composer attaches a reference PDF; it does not publish an upload.

For visual work, the cloud agent is instructed to build the actual Jekyll source and export affected rendered pages. The editor displays that private preview in a sandboxed iframe. A missing or failed build is not represented as a successful preview. The preview disables forms and outbound script requests; images may load from the public site. It is a review of selected rendered pages, not a separately deployed staging website or a live Vercel preview of editor-code changes.

Every proposal stays in the private draft repository. Review the complete set of file changes, then use **Publish these changes** to create one public commit and request a GitHub Pages build. The model has no publishing credentials. The server rejects stale reviews or changed public files rather than overwriting them. Files in a public repository are public even when their pages have `published: false`.

## Cloud execution, privacy, and limits

- GitHub sign-in is restricted server-side to your numeric account ID. All private operations require the configured private repository to remain private, non-forked, and owned by NateOConnellPhD. Mutations require same-origin requests and a CSRF token.
- New messages use the **OpenAI Responses API with function tools** to list, read, search, and edit website files. Ordinary conversation allocates no container and uploads no project snapshot. Tools read the current private overlay, use bounded results, and reject edits based on stale file SHAs. Optional execution preserves the preceding Responses context and pending edits, then uses hosted shell. Existing Responses-workspace and Agents requests keep their recovery paths. API keys and GitHub tokens stay on Vercel, outside model context and containers. DNS and external-account settings are not controlled by this application.
- Direct chat sends at most the latest 24 saved messages / 48,000 characters, a list of pending paths, requested file excerpts, and an explicitly attached PDF to OpenAI. Older conversation messages remain available through a tool. A whole source snapshot is sent only for execution. Local private context folders, credentials, Git internals, caches, and generated build output are excluded. The agent can edit website code, configuration, workflows, the publication feed, scripts, and this editor; it is not restricted to content fields.
- Conversations and source proposals are saved under `chats/` in the private repository. Built preview bundles are saved there too. Git history retains earlier saved versions. A reference PDF is provided only to its cloud task, not copied into either GitHub repository or automatically replayed on follow-ups.
- Live replies use a filtered event stream, reconnecting within Vercel's function duration limit. The browser checks saved progress immediately when a response ends, every 30 seconds during a connected stream, and every two seconds while reconnecting or advancing file tools. Reopening a conversation resumes this automatically; **Reconnect** is a fallback. Cursors reset when a tool continuation creates a new response. Only assistant output is forwarded; reasoning, tool arguments, credentials and raw events are excluded.
- Direct tool edits are validated and checkpointed privately between bounded batches. Execution imports only a completed response's exported result. The final reply and changes are saved before deleting provider resources. Conditional Git writes prevent concurrent tabs from advancing the same response twice. A saved submission intent prevents automatic repetition of an ambiguous paid creation. Cleanup and cancellation failures remain recoverable and retry automatically while the conversation is open. Closing the browser does not cancel the task or confirm cleanup; use **Stop response**. Containers are configured to expire after 20 minutes of inactivity.
- The source exporter preserves existing executable files and rejects symlinks rather than following them. Publication retains unrelated repository files and never force-pushes history. Malformed returned changes do not replace earlier private proposals.
- API model and optional hosted-container usage is billed to the OpenAI organization behind the key. Available credits may cover it; this app does not establish credit eligibility. Defaults limit each message to **8 model responses and 12,000 output tokens**, shared across continuations and execution. Missing usage conservatively reserves that response's entire output allowance. Direct calls allow at most 8,000 output tokens and 16 built-in tool calls each; execution allows up to the remaining message budget and 24 built-in tool calls. The daily cap counts accepted messages and writing-assistant requests, including failed attempts. These limits are **not a dollar budget**: input, reasoning, search, and execution can affect charges.
- **Chat details** shows confirmed model requests, provider-reported input/cached-input/output tokens, and container allocations. Missing usage is identified rather than shown as zero cost. No prices or assumed cache savings are hard-coded. Ambiguous creations with no recovered response ID cannot be fully measured here; use OpenAI's billing records for authoritative charges.
- Direct reads allow 12 paths per call, 200 lines / 24,000 characters per excerpt, and 100,000 characters per batched read. Search is paginated and reports omitted matches. Execution snapshots remain limited to 800 text files / 1.5 MB. Other limits are 500 KB per source file, 200 pending changes, 1 MB per changed binary/upload, 1.6 MB of changes, 1.8 MB per conversation, 80 saved messages, and 1.5 MB per reference PDF. Existing public binary assets may be larger: execution preserves unchanged placeholders and can retrieve pinned public bytes through enabled shell networking. Pending uploads contain actual bytes. The PDF stays in Responses context through an execution handoff; it is not automatically materialized as a local file during that handoff. Large existing assets can be viewed or deleted manually; moving/replacing one over 1 MB requires a different upload path.
- Built preview bundles contain at most 12 pages and 1.5 MB. Generated cloud build output is instructed to stay under 500 MB. These are application checks/instructions, not an operating-system disk quota.

The single-document writing assistant uses Responses with `store: false`. Whole-site chat uses `background: true`, `stream: true`, and `store: true` so an individual model response survives a browser disconnect. **This is not an unattended background worker:** file-tool continuations, execution imports, and explicit cleanup resume when the conversation is open. An expired container's unsaved edits may no longer be recoverable. Direct edits already checkpointed in GitHub survive. API data handling follows the organization's applicable policies. This editor does not save drafts in browser localStorage or a service-worker cache.

### Caching and request overhead

Immutable public trees and blobs are cached by Git SHA in a bounded 8 MB warm-instance cache, with simultaneous reads coalesced. A new public revision changes the tree key, while unchanged blobs can be reused. Cold instances work without the cache. Moving branch heads, private drafts, and permission checks always go upstream. The initial chat message fetches no source files; manual file saves fetch only the changed paths. Progress checkpoints use one conditional Contents API write instead of recreating Git objects and the chat index each time. The daily allowance is committed atomically with the initial message. Execution uploads original source once and overlays pending changes locally.

The stable instructions/tools and per-chat `prompt_cache_key` make repeated prefixes eligible for OpenAI prompt caching. Cache hits are not guaranteed; the usage panel reports the actual cached-input count. `previous_response_id` preserves a tool loop's context but does not make previous input free. New user messages use bounded recent history rather than accumulating every earlier file read in a permanent model chain. The configured model is retained; direct chat defaults to low reasoning effort and execution uses medium effort.

## Configure the existing deployment

If the previous editor already signs in, keep its existing Vercel project, private repository, GitHub App, and secrets.

1. Push the new source to the website repository. Vercel's editor project should deploy from `main`, with **Root Directory: website-editor**, **Framework: Other**, Node.js 24, and the checked-in `vercel.json`. The existing pinned `yaml@2.9.1` dependency installs during deployment. No SDK dependency was added for the cloud agent.
2. Keep `OPENAI_API_KEY` set in Vercel Production. Direct chat requires create/read/cancel/delete access to **Responses**. Optional execution additionally needs **Containers** creation, file upload/list/download, deletion, and organization access to hosted shell. Keep Agents access only while recovering or cleaning up older requests. Redeploy after changing environment variables.
3. Whole-project tasks default to `gpt-6-astra`. Set `OPENAI_AGENT_MODEL` if choosing another model that supports Responses and hosted shell. `OPENAI_MODEL` still controls only the individual-document writing assistant. Leave `OPENAI_SHELL_ALLOWED_DOMAINS` empty for ordinary chat/source editing, or configure it as described below for dependency downloads and previews.
4. To publish changes under `.github/workflows/`, add **Workflows: Read and write** to the GitHub App's repository permissions and approve the updated installation permissions. Keep **Contents: Read and write**, **Pages: Read and write**, and **Metadata: Read-only**. Continue installing it only on the website and private draft repositories.
5. Run the connected review below before relying on the cloud workflow. Local mocked checks do not establish that the deployed API key, sandbox, Vercel routing, or GitHub permissions work.

For a fresh installation, create `NateOConnellPhD/nateoconnell-editor-private` as a private non-fork repository initialized with a README on `main`. Register a GitHub App, disable webhooks, leave user tokens expiring, and set:

- Homepage: `https://nateoconnellgithubio-website-editor.vercel.app`
- Redirect URI (also called Callback URL): `https://nateoconnellgithubio-website-editor.vercel.app/api/auth/callback`
- Wildcard redirect matching, Device Flow, and user authorization during installation: off. Setup URL: blank.
- Client secret: GitHub App **Credentials**. Client ID is shown on General. If GitHub requires a private key to install the app, generate one under Credentials and store it securely outside the repository. This editor uses the client secret and short-lived user token; it does not need that PEM or an installation ID uploaded to Vercel.

### Environment variables

| Variable | Value |
| --- | --- |
| `APP_ORIGIN` | `https://nateoconnellgithubio-website-editor.vercel.app`, without a trailing slash. |
| `GITHUB_CLIENT_ID` | GitHub App Client ID. |
| `GITHUB_CLIENT_SECRET` | GitHub App client secret from Credentials. |
| `ALLOWED_GITHUB_USER_ID` | Your numeric GitHub account ID, not an app ID or username. |
| `SESSION_SECRET` | 64 hex characters; generate with `openssl rand -hex 32`. Rotation signs out existing sessions. |
| `DRAFT_REPOSITORY` | `NateOConnellPhD/nateoconnell-editor-private`. |
| `OPENAI_API_KEY` | Server-only project key for the intended OpenAI organization. Manual editing does not require it. |
| `OPENAI_AGENT_MODEL` | Whole-project agent; defaults to `gpt-6-astra`. |
| `OPENAI_CHAT_REASONING_EFFORT` | Direct chat: `low` (default), `medium`, or `high`. Execution uses medium. |
| `MAX_CHAT_MODEL_STEPS` | Model responses per message, including tool continuations/execution. Default 8; range 1–20. |
| `MAX_CHAT_OUTPUT_TOKENS` | Total output-token allowance per message. Default 12,000; range 1,024–32,000. Not a dollar cap. |
| `OPENAI_SHELL_ALLOWED_DOMAINS` | Optional comma-separated hostnames. Empty disables outbound shell networking. Hosts must also be allowed by the OpenAI organization. |
| `OPENAI_MODEL` | Individual-document assistant; defaults to `gpt-5.4-mini`. |
| `MAX_DAILY_AI_REQUESTS` | Defaults to 40; range 1–100. Shared request counter resets by UTC date. |

Keep secrets in Vercel environment variables. Do not expose them to the browser, source repository, or untrusted Vercel preview deployments.

### Network access for builds and existing binary assets

Hosted shell includes Python, Node and Ruby, but this editor does not assume Jekyll or its gems are installed. A build that needs dependencies requires both the OpenAI organization's shell network allowlist and `OPENAI_SHELL_ALLOWED_DOMAINS` in Vercel. For this Jekyll site, begin with `rubygems.org,index.rubygems.org` for gems and `raw.githubusercontent.com` for existing public binaries, allowing those same hosts in the OpenAI dashboard. If a dependency uses a different host, inspect the reported failure before adding it. Requests that list hosts outside the organization's allowlist are rejected. Redeploy after changing the Vercel variable.

Without that configuration, direct chat and source editing need no container. Execution requiring missing dependencies reports the limitation instead of claiming a successful preview. Public web search is a separate tool. See the [hosted shell network requirements](https://developers.openai.com/api/docs/guides/tools-shell#network-access).

## Connected review

1. Sign in through `/login` and check the organized project tree on desktop and your phone. Confirm another GitHub account is denied.
2. Ask which papers are highlighted. Verify your message and streamed reply appear without a manual refresh, and Chat details reports **0 temporary workspaces**. Ask a follow-up, then request a changed selection. Inspect the proposed `featured`/`order` values and reopen the conversation. Confirm changes remain private and compare the reported token counts with OpenAI usage.
3. Ask to add a temporary page, link it in navigation, and build a preview. Inspect the actual rendered page, check the reported build results, and verify the cloud task terminates and cleanup is confirmed. Discard the proposal without publishing.
4. Exercise an interrupted connection and a stopped task. Check the saved conversation recovers without starting duplicate model work.
5. Edit a source file directly, save, rename it, and discard. Try a non-sensitive image upload/paste on an actual phone; the implementation alone does not verify mobile clipboard support.
6. Only for an intentional public update, review and publish. Confirm the GitHub commit, Pages build, live page, and any Vercel redeployment separately. Publishing editor code changes may redeploy the editor itself.

The original private cross-validation blog draft has not been copied into this workspace or published by this change.

## Local validation

The November 11 connection diagnosis showed successful direct Responses inference with the same key/model that failed during a minimal Agents turn. That establishes a working direct model connection, not successful execution of the new hosted-shell workflow. New messages now use Responses; **Check progress** on an old failed request still shows its saved failure.

Focused checks with mocked GitHub/OpenAI services:

```sh
node --test --test-concurrency=1 test/repository-chat.test.js test/github-cache.test.js test/response-workspace.test.js test/chat-stream.test.js
```

These targeted JavaScript checks mock GitHub/OpenAI and use no credentials, paid calls, builds, or disk output. They cover selective reads, private edits, SHA conflicts, immutable caching, atomic message/allowance saves, concurrent submissions/polls, token limits, usage accounting, stopped or interrupted requests, resumable tool batches, optional execution handoff, legacy imports, streaming and cleanup. Run `python3 -B test/workspace_test.py` for the exporter: small fixtures stay under `.codex-tmp/editor-efficiency-review/` and are removed afterward. HTML/JSON fixtures do not establish local YAML dependency availability. Deployed chat, actual model tool selection, billed cost/latency, hosted-shell execution, Jekyll builds, browser/mobile behavior and publication still require connected validation.

## Isolating a failed model connection

`scripts/check-agent.mjs` is an optional live diagnostic, never run by the editor or test suite. Run it explicitly with the same `OPENAI_API_KEY` and, if customized, `OPENAI_AGENT_MODEL` as Vercel. It makes one small billed model request without uploading the website or any conversation. It prints request/session/turn IDs and returned errors, then requests session deletion. It writes no local files and requires no downloaded packages.

The model check supplies initial input and streams the first turn in the creation request, as required for conversation-only sessions. It does not submit a second message. A creation rejection with HTTP 400, 401, or 403 needs no session lookup or cleanup; an uncertain creation still attempts recovery by diagnostic metadata before deletion.

For an authentication rejection, run `node scripts/check-agent.mjs --auth-only` from `website-editor/` first. This mode only reads `/v1/models` and `/v1/agents/sessions?limit=1`, reporting status, request IDs, and errors without printing account data. It never creates a session or runs a model. Models and Agents permissions are separate, so a failed models check alone does not establish that the key is invalid. Successful read access does not establish permission to create sessions or run inference.

The default has no sandbox. If that succeeds, `--hosted` checks an empty hosted sandbox without this website's package installs, assets, or preparation script; that check also incurs sandbox usage. A successful probe establishes only that specific path, not that the editor works. A failed cleanup is reported with the session ID; do not ignore it. Keep the API key out of chat and shell history.

If even the no-sandbox turn fails, `--responses` makes one direct Responses API request with the same model and key. It requests only the word `connected`, uses low reasoning effort with a 1,024-token output limit, and sets `store:false`. It creates no Agents session or sandbox, uploads no files, and does not retry automatically. This is a billed model call. A successful reply establishes direct inference access; it does not validate the editor or prove a permanent Agents outage. `--auth-only` always takes precedence over the model-check flags.

## API references

- [Function calling](https://developers.openai.com/api/docs/guides/function-calling) and [prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Responses hosted shell and containers](https://developers.openai.com/api/docs/guides/tools-shell), [background execution and reconnects](https://developers.openai.com/api/docs/guides/background), and [container file uploads](https://developers.openai.com/api/reference/resources/containers/subresources/files/methods/create)
- [OpenAI Agents sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions), [hosted environments](https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted), and [files/artifacts](https://developers.openai.com/api/docs/guides/agents-api/environments/files)
- [Agent-session listing and recovery metadata](https://developers.openai.com/api/reference/resources/beta/subresources/agents/subresources/sessions/methods/list)
- [Conversation events](https://developers.openai.com/api/docs/guides/agents-api/sessions/events), [saved conversation items](https://developers.openai.com/api/reference/resources/beta/subresources/agents/subresources/sessions/subresources/items/methods/list), and [failure details](https://developers.openai.com/api/docs/guides/agents-api/errors)
- [GitHub App user tokens and PKCE](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app)
- [Git tree updates](https://docs.github.com/en/rest/git/trees#create-a-tree) and [non-forced reference updates](https://docs.github.com/en/rest/git/refs#update-a-reference)
- [Vercel Node functions](https://vercel.com/docs/functions/runtimes/node-js)

## Write a post yourself

Choose **Create a blog post** in the sidebar (on a phone, open the menu). **My writing drafts** reopens saved drafts. Write Markdown directly; saving and previewing do not call OpenAI. Equation buttons insert Kramdown’s LaTeX delimiters: `$$x_i^2$$` inside a sentence, or `$$` on separate lines with a blank line before and after the block. For example:

```markdown
The estimate is $$\hat{\theta}$$.

$$
\hat{\theta} = \frac{1}{n} \sum_{i=1}^{n} x_i
$$
```

Preview and published posts render equations with pinned KaTeX 0.19.1 assets from jsDelivr, checked with subresource integrity. TeX remains in Markdown, and code blocks stay literal. The editor loads the renderer only when an equation is previewed; public posts load it only when their rendered content contains math. This supports mathematical TeX, not compiling an entire LaTeX document. Save privately, then review and publish when ready.
