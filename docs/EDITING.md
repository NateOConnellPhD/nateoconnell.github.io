# Writing and editing

## Connect once

After the source is in your GitHub repository, sign in at [app.pagescms.org](https://app.pagescms.org). Install its GitHub App for this website repository, choose the publishing branch, and open the existing configuration. Routine saves are committed to GitHub by the editor; you do not need to use Git yourself. [Official setup](https://pagescms.org/docs/quick-start/).

## Publish a post

1. Open **Blog posts**, then create an entry.
2. Enter a title, date, short summary, and any topics.
3. Write in the visual editor. Its **Source** mode exposes the Markdown when you want it.
4. Add images through the image picker. Supply useful alt text for images and a cover description when using a cover.
5. Leave **Publish on the website** off to save a draft. Turn it on and save when ready.
6. GitHub Pages rebuilds after the save. Wait for the Pages deployment to finish, then check the site.

The editor generates a dated Markdown filename. The publication date also lives in the entry, and changing the title later need not change an existing filename. Avoid renaming published posts unnecessarily because their URLs depend on the filename and date.

The site excludes unpublished and future-dated posts. A future date is not an automatic schedule: the site must be rebuilt on or after that date. For a quick post, use today's date.

Drafts and uploaded media are still stored in the repository and its history. With a public repository, they are publicly readable even when omitted from the website. Media files are also copied to the published site. Do not upload confidential drafts or images.

## Images on desktop and phone

The supplied configuration enables a named image media folder and Markdown output. Images are stored in `assets/images/` with random upload names to reduce screenshot filename collisions. Supported upload formats are JPEG, PNG, WebP, GIF, and AVIF. HEIC is not enabled; export or share a JPEG/PNG first.

The current Pages CMS source connects clipboard image uploads to its media storage. Copying a screenshot or image file into the visual editor is supported by that implementation. This has **not yet been verified end to end against your connected repository or on a real phone**. Do not treat the editor's mobile layout or a desktop browser resized to phone width as proof of mobile clipboard behavior.

Use the image picker as the phone upload path until paste is verified. The phone browser may present Photos, Files, or camera choices. A copied web image may produce an external image URL instead of a local upload; inspect the saved source if permanent local storage matters.

### Required phone acceptance check

Once connected, create a disposable **unpublished** post using a non-sensitive test image:

| Device/browser | Check | Result |
| --- | --- | --- |
| Desktop Safari or Chrome | Paste a screenshot into the visual editor; save, reopen, confirm image persists | Pending |
| iPhone Safari | Copy an image from Photos; long-press inside the editor and Paste; save and reopen | Pending |
| Android Chrome, if used | Copy an image using that device's app/keyboard; paste, save and reopen | Pending |
| Actual phone | Use image picker, select a photo, add alt text, save and reopen | Pending |
| Actual phone | Format a heading, bold text, and link; switch Editor/Source; save and reopen | Pending |
| Published test | Publish a non-sensitive post and check the image on the final domain | Pending |

For each check, record device, OS, browser version, source app, and whether Markdown contains `/assets/images/...` with a corresponding repository file. Delete the test entry and image afterward. If paste fails but upload succeeds, keep upload as the supported workflow; if phone paste is essential, reconsider the CMS before launch.

## Other updates

- **Name, profile & contact:** name, title, department, division, institution, introduction, portrait, interests, public email, and links. The homepage displays title, department, division, and institution on separate lines. The portrait is shared by the homepage and About page.
- **Homepage text:** the main heading and short section descriptions.
- **Biography:** longer-form biography with the same visual Markdown editor.
- **Research introductions:** separate introductions for **Methods & theory** and **Clinical research**. The shorter homepage version remains in **Homepage text**.
- **Research & work:** choose **Research area** to place an entry in **Methods & theory** or **Clinical research**. An optional **Study label** displays a short name, such as PREVENT or UPBEAT, above the paper title. **Display order** controls ordering within each section and on the homepage.
- **Type of work:** select **Publication**, **Preprint**, or **Manuscript** to distinguish journal publications, public preprints, and work in progress. **Project** and **Other** are also available. The website visibility switch does not imply journal publication. Type filters apply within the methods/theory section; the clinical highlights remain visible.
- **Feature on the homepage:** every visible entry with this enabled appears on the homepage. All five current methodological manuscripts are featured. The pre–post methods publication and the five clinical studies are included on the Research page with homepage featuring off.
- **Talks & seminars:** event date and description; upload PDF or PowerPoint (`.pptx`) slides through **Talk slides** and paste recording/event URLs. Presentations are stored in the `Presentations/` folder and are public website files. Recording links start at the beginning unless you deliberately include a timestamp.
- **Curriculum vitae:** the supplied PDF is already linked. Update the web CV and replace **Downloadable CV PDF** when needed; these are independent versions.

The two existing sample blog posts are unpublished drafts. They can be used as formatting examples, but replace the example text and turn off **Mark as example content** before publishing. Keep **Publish on the website** off until a post is ready.

## Verification sources

Reviewed 2026-09-25:

- [Rich-text options](https://pagescms.org/docs/configuration/fields/rich-text/): Markdown, Editor/Source switching, media folder configuration.
- [CMS rich-text implementation](https://github.com/hunvreus/pagescms/blob/main/fields/core/rich-text/edit-component.tsx): enables image paste/drop when media is configured and supplies an upload callback that saves media to the repository. This is source evidence from `main`, not proof of the version currently deployed at app.pagescms.org.
- [Editor component](https://editor.pagescms.org/): documents image paste/drop and upload callbacks.
- [Pages CMS](https://pagescms.org/): describes responsive mobile support; does not establish clipboard compatibility for every mobile browser/source app.
- [Media configuration](https://pagescms.org/docs/configuration/media/): repository storage, public paths, and upload renaming.
