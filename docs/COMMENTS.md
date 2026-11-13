# Blog discussions

Blog comments use [giscus](https://giscus.app), backed by GitHub Discussions. Readers can read without signing in; a GitHub account is required to comment or reply. Nate can reply below a post or in GitHub Discussions and moderate through GitHub. Comments appear without rebuilding the website.

## Connect once

1. Open the website repository's [General settings](https://github.com/NateOConnellPhD/nateoconnell.github.io/settings). Under **Features**, enable **Discussions**.
2. In the repository's **Discussions** tab, create a category named **Blog comments** with the **Announcement** format. This lets giscus and maintainers create the threads, while readers can comment and reply.
3. [Install the giscus GitHub App](https://github.com/apps/giscus) for **only** `NateOConnellPhD/nateoconnell.github.io`.
4. Open [giscus configuration](https://giscus.app), enter `NateOConnellPhD/nateoconnell.github.io`, and select **Blog comments**. From its generated script, copy `data-repo-id` and `data-category-id` into `repo_id` and `category_id` in `_data/comments.yml`. These IDs are public configuration, not secrets. Keep `category` equal to the selected category's name.
5. Set `enabled: true` in `_data/comments.yml`, commit those changes, and push. The post template already supplies the mapping, styling, and other options; do not paste an additional script into individual posts.

Until this is complete, the site deliberately renders no comments widget. Blank IDs do not produce a broken form for readers. No Vercel or OpenAI credentials are needed.

## Use it

Each post gets a separate thread. giscus creates it when the first comment or reaction is submitted. Its identifier is the post's URL path, so changing a display title or domain does not split the conversation. Preserve a published post's path; changing its date, filename, or permalink can start a different thread.

In the website editor, open a blog post and use **Show discussion** to show or hide its comments section, then review and publish. The switch is also available in Pages CMS. Existing posts show discussions by default once the site-wide connection is enabled. Example posts, unpublished posts, and the site's preview mode do not render the widget.

Turning off **Show discussion** hides the embedded discussion; it does not delete comments or lock their thread on GitHub. To stop replies while retaining the discussion, lock the thread in GitHub Discussions. Set `enabled: false` in `_data/comments.yml` to hide all comment sections.

Manage comments, notification preferences, and moderation in the repository's [Discussions](https://github.com/NateOConnellPhD/nateoconnell.github.io/discussions). The comments are public and stored on GitHub. giscus has no ads and does not charge for usage; it does not use the editor's GPT API credits.

## Check after activation

Open a published post on `nateoconnell.com` and confirm that its Discussion box loads. Sign in with GitHub, add a short test comment, reply to it, and reload to confirm both persist. Open a second post to confirm it has a separate discussion. Remove the test comments afterward. These live checks require the GitHub setup and have not yet been performed.

Provider documentation: [configuration and sign-in](https://giscus.app), [thread matching and customization](https://github.com/giscus/giscus/blob/main/ADVANCED-USAGE.md).
