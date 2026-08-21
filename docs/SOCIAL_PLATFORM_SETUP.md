# Official social platform setup

ClipForge is intentionally not shipped with client IDs, client secrets, passwords, cookies, or fake OAuth tokens. To enable an integration, create an official developer application with the platform, register the redirect URI, and place the credentials in the backend environment.

```env
SOCIAL_OAUTH_REDIRECT_URI=http://localhost:5173/api/social/oauth/callback
TOKEN_ENCRYPTION_KEY=<Fernet key>
```

For a deployed instance, replace the localhost redirect URI with the exact HTTPS origin registered in the official developer console.

## YouTube

Environment:

```env
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
```

ClipForge requests read-only YouTube scope for metadata import and the upload scope only when the user explicitly starts a publishing connection.

The Data API can list the authenticated account's uploads and metadata. It is intentionally reported as **metadata only** for original-media import in this MVP because ClipForge does not use an unauthorized downloader.

## Meta / Facebook / Instagram

Environment:

```env
META_APP_ID=
META_APP_SECRET=
```

Meta permissions and account type determine the result. Facebook Pages and Instagram professional accounts may expose different fields and capabilities. ClipForge only imports media when the official Graph API returns a permitted media URL.

Instagram publishing is not enabled in local-only Free Mode because the current official flow requires a publicly reachable video URL. The application displays that limitation rather than uploading local content through an unauthorized workaround.

## TikTok

Environment:

```env
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
```

TikTok metadata and publishing require the relevant approved scopes and developer-app review. TikTok original-media import is reported as unavailable in this MVP when the official API does not expose a permitted download method.

## Security rules

- Never request or store social passwords.
- Never ask users to paste access tokens.
- Never accept browser cookies or session exports.
- OAuth tokens are encrypted at rest.
- Disconnect removes the locally encrypted token record.
- Reconnect if a token expires or the provider rejects a request.
- Platform quotas are external; Free Mode does not imply unlimited API usage.

Always confirm current platform API scopes, review requirements, rate limits, and content policies before production launch.
