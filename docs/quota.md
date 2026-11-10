# YouTube Data API quota

Library import and publish use YouTube Data API v3. Google sets a daily quota on each Cloud project.

## Defaults

- Most new projects get **10,000 units per day** for list-style calls
- The quota resets at **midnight Pacific Time**
- Check usage in Google Cloud Console → **APIs & Services → Quotas**

## How this app uses quota

Each API page costs about **1 unit**.

Import costs grow with:

- Number of playlists
- Number of tracks
- Whether video detail fetch is on

`YTMUSIC_FETCH_VIDEO_DETAILS` is **false** by default. That skips `videos.list` and cuts import cost about in half. Playlist and system-list filters still apply.

Set `YTMUSIC_FETCH_VIDEO_DETAILS=true` only if you need per-video Music category filters.

## If you hit `quotaExceeded`

1. Stop further Import or Publish runs for the day.
2. Wait until after midnight Pacific Time.
3. Run **Import library** again. Already imported playlists are skipped.
4. Or import one playlist at a time with a `music.youtube.com` link.

You can also request a higher quota in Google Cloud Console.

## Tips

- Prefer one full library import per day over many partial retries.
- Keep `YTMUSIC_FETCH_VIDEO_DETAILS=false` unless you need it.
- Do not create a second Cloud project only to dodge the limit if that breaks Google terms for your use case.
