# Pipeline

Work through the pages in this order.

## 1. Setup

Create your Google OAuth client. Sign in. Confirm the auth file exists.

See [setup.md](setup.md).

## 2. Import

Pull your YouTube Music library, or import one playlist.

Rules:

- Use a `music.youtube.com` playlist link or a raw playlist ID
- Regular `youtube.com` playlist links are rejected
- Watch Later, Liked videos, uploads, and similar YouTube system lists are skipped
- Your own channel uploads are skipped
- With `YTMUSIC_FETCH_VIDEO_DETAILS=true`, non-music videos are also skipped by category or type

Import resumes after a stop or quota error. Already imported playlists are skipped.

Quota limits: [quota.md](quota.md).

## 3. Select playlists

Choose which source playlists feed Smart Assign. Excluded sources can become pre-designed destinations.

## 4. Design playlists

Create destination playlists by hand when you want fixed themes before Smart Assign.

## 5. Smart Assign

Send unassigned tracks to an LLM. The model assigns tracks to mood themes and can create destination playlists.

Set `LLM_API_KEY` in `.env` first.

## 6. Organize playlists

Merge similar destinations. Edit names and descriptions.

## 7. Review

Check assignments. Reassign tracks that do not fit.

## 8. Publish

Create the destination playlists on YouTube and add the assigned tracks.

## Tools

- **Library**: search tracks and assign by title
- **Export**: CSV/JSON and database backup

Tracks are unique by title and artist. Assignments use track title, not numeric IDs.
