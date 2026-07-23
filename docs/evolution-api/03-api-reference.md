# Evolution API Feature Reference

**Version basis**: v2.3.7 stable (Dec 5, 2024). Notes on v2.4.0-rc2 (May 17, 2026) included where behaviour differs.  
**Auth header**: `apikey: <token>` on every request. Two scopes: global key (full admin) and per-instance token (scoped to one instance). Never mix them.  
**Base URL**: `https://<your-evolution-host>`  
**Swagger UI**: `GET /docs` (disable with `SERVER_DISABLE_DOCS=true`)

> **Note — Postman collection version gap**: The official Postman collection on the Evolution API workspace only covers up to v2.2.2. Some endpoint shapes and fields changed between v2.2.2 and v2.3.7. Use the Swagger UI at `/docs` on your running instance as the authoritative interactive reference for v2.3.7.

---

## Number / JID Format Rules

| Recipient type | Format to send | Resolved to |
|---|---|---|
| Individual (phone) | `5511999999999` (digits, country code first, no `+`) | `5511999999999@s.whatsapp.net` |
| Individual (full JID) | `5511999999999@s.whatsapp.net` | passed through unchanged |
| Group | `120363295648424210@g.us` | passed through unchanged |
| LID (hidden-phone, Meta rollout) | `<lid>@lid` — seen in inbound events only | do not send outbound; use phone number |

Strings already containing `@` are not re-converted. Pass the bare phone number for all outbound sends.

---

## Common Message Options (all `/message/*` endpoints except `sendReaction`)

These fields are accepted on every send endpoint alongside the endpoint-specific payload fields.

| Field | Type | Description |
|---|---|---|
| `number` | string | **Required.** Recipient phone or group JID (see format rules above) |
| `delay` | number | Milliseconds to wait server-side before sending (simulates typing pause) |
| `quoted` | object | Reply/quote — pass `{ key: { id, fromMe, remoteJid }, message: {} }` |
| `linkPreview` | boolean | Fetch OG metadata and attach URL preview card (text messages) |
| `mentionsEveryOne` | boolean | `@mention` all group members. **BUG (issue #2431, closed "not planned")**: setting to `false` still triggers the mention — omit the field entirely to suppress |
| `mentioned` | string[] | Explicit list of JIDs to `@mention` (`5511999999999@s.whatsapp.net`) |
| `encoding` | boolean | When true, triggers server-side audio transcoding to opus/ogg before delivery. Applies to all send endpoints except `sendReaction` |

---

## 1. Instances Controller

**Path prefix**: `/instance`  
**Create requires global API key. All other ops accept global key or the matching per-instance token.**

| Endpoint | Method + Path | Purpose | Key body fields | Notes |
|---|---|---|---|---|
| Create instance | `POST /instance/create` | Provision a new WhatsApp instance | `instanceName` (req), `integration`, `token`, `qrcode`, `number`, `rejectCall`, `msgCall`, `groupsIgnore`, `alwaysOnline`, `readMessages`, `readStatus`, `syncFullHistory`, `webhook` object | Returns `hash` (per-instance token) — store it. `integration`: `WHATSAPP-BAILEYS` (default, free) or `WHATSAPP-BUSINESS` (Meta Cloud API) |
| List instances | `GET /instance/fetchInstances` | List all (global key) or own (instance token) instances | — | Query params: `instanceName`, `instanceId`, `page`, `offset`. `apikey` field appears in response only if `AUTHENTICATION_EXPOSE_IN_FETCH_INSTANCES=true` (default true) |
| Connect / get QR | `GET /instance/connect/{instanceName}` | Start connection; returns QR or pairing code | — | Add `?number=5511999999999` for 8-char pairing code instead of QR. QR expires ~45 s; auto-regenerates up to `QRCODE_LIMIT` (default 30) times |
| Connection state | `GET /instance/connectionState/{instanceName}` | Poll current state | — | Returns `{ instance: { instanceName, state } }`. States: `open`, `connecting`, `close`, `refused` *(verify against current docs)* |
| Restart | `PUT /instance/restart/{instanceName}` | Reconnect Baileys without destroying session/DB record | — | Use to recover transient failures or apply config changes |
| Logout | `DELETE /instance/logout/{instanceName}` | End WhatsApp session; preserves instance DB record | — | Instance moves to `close`; new QR/pairing required to reconnect |
| Delete | `DELETE /instance/delete/{instanceName}` | Permanently remove instance, session, and all data | — | Irreversible |
| Set global presence | `POST /instance/setPresence/{instanceName}` | Set online/offline status for the whole instance | `presence`: `available` \| `unavailable` \| `composing` \| `recording` | Distinct from per-chat presence in `/chat/sendPresence` |

### Instance connection state machine

```
create → [close] → GET /instance/connect → [connecting] → QR scanned → [open]
[open]  → codes 408/428/500 → auto-reconnect (exponential backoff) → [connecting]
[open]  → codes 401/403/402/406 → permanent disconnect → must re-scan QR
[open/close] → PUT /restart → [connecting]
[open]  → DELETE /logout → [close]  (session cleared, config retained)
[open/close] → DELETE /delete → (removed)
```

### Instance create body — integration values

| `integration` value | Transport | Auth flow |
|---|---|---|
| `WHATSAPP-BAILEYS` | Baileys / WhatsApp Web (free) | QR scan or pairing code |
| `WHATSAPP-BUSINESS` | Meta Cloud API (paid) | Meta credentials, no QR |
| `EVOLUTION` *(verify against current docs)* | Internal Evolution channel (not confirmed in official docs or source) | — |

### Instance create — webhook sub-object

```json
{
  "webhook": {
    "enabled": true,
    "url": "https://my-server.com/webhook",
    "byEvents": false,
    "base64": false,
    "headers": { "authorization": "Bearer TOKEN" },
    "events": [
      "CONNECTION_UPDATE",
      "MESSAGES_UPSERT",
      "MESSAGES_UPDATE",
      "SEND_MESSAGE"
    ]
  }
}
```

Full event name list: `APPLICATION_STARTUP`, `INSTANCE_CREATE`, `INSTANCE_DELETE`, `QRCODE_UPDATED`, `CONNECTION_UPDATE`, `REMOVE_INSTANCE`, `LOGOUT_INSTANCE`, `MESSAGES_SET`, `MESSAGES_UPSERT`, `MESSAGES_UPDATE`, `MESSAGES_EDITED`, `MESSAGES_DELETE`, `SEND_MESSAGE`, `SEND_MESSAGE_UPDATE`, `CONTACTS_SET`, `CONTACTS_UPSERT`, `CONTACTS_UPDATE`, `PRESENCE_UPDATE`, `CHATS_SET`, `CHATS_UPSERT`, `CHATS_UPDATE`, `CHATS_DELETE`, `GROUPS_UPSERT`, `GROUPS_UPDATE`, `GROUP_PARTICIPANTS_UPDATE`, `LABELS_EDIT`, `LABELS_ASSOCIATION`, `CALL`, `TYPEBOT_START`, `TYPEBOT_CHANGE_STATUS`, `ERRORS`, `NEW_JWT_TOKEN`

---

## 2. Settings Controller

**Path prefix**: `/settings`  
**Auth**: global key or instance token.

| Endpoint | Method + Path | Purpose | Key body fields | Notes |
|---|---|---|---|---|
| Set settings | `POST /settings/set/{instanceName}` | Configure instance behaviour | see table below | All fields optional; send only what changes |
| Get settings | `GET /settings/find/{instanceName}` | Read current settings | — | Returns same shape as POST body |

### Settings fields

| Field | Type | Description |
|---|---|---|
| `rejectCall` | boolean | Auto-reject all incoming WhatsApp calls |
| `msgCall` | string | Message sent to caller on auto-reject (requires `rejectCall: true`) |
| `groupsIgnore` | boolean | Bot/automation ignores group messages |
| `alwaysOnline` | boolean | Keep WhatsApp presence permanently online |
| `readMessages` | boolean | Auto-send read receipts (blue double-check) for all incoming messages |
| `readStatus` | boolean | Auto-mark WhatsApp Stories/status broadcasts as viewed |
| `syncFullHistory` | boolean | Pull full message history on connection (slower connect) |
| `wavoipToken` | string | Token for Wavoip VoIP integration |

---

## 3. Proxy Controller

**Path prefix**: `/proxy`  
**Auth**: global key or instance token.

| Endpoint | Method + Path | Purpose | Key body fields | Notes |
|---|---|---|---|---|
| Set proxy | `POST /proxy/set/{instanceName}` | Configure per-instance outbound proxy | `enabled`, `host`, `port`, `protocol`, `username`, `password` | Protocols: `http`, `https`, `socks`, `socks4`, `socks5`. Falls back to global `PROXY_*` env vars if unset |
| Get proxy | `GET /proxy/find/{instanceName}` | Read current proxy config | — | Returns same shape as POST body |

If `host` contains the string `proxyscrape`, the API fetches a ProxyScrape list and picks one randomly per connection.

---

## 4. Webhook Controller (standalone)

**Path prefix**: `/webhook`

| Endpoint | Method + Path | Purpose | Key body fields | Notes |
|---|---|---|---|---|
| Set webhook | `POST /webhook/set/{instanceName}` | Override or update webhook config | `enabled`, `url`, `webhookByEvents`, `webhookBase64`, `headers`, `events[]` | Can also be set at instance creation time |
| Get webhook | `GET /webhook/find/{instanceName}` | Read current webhook config | — | — |

---

## 5. Messages Controller

**Path prefix**: `/message`  
**Auth**: instance token (or global key).  
**All endpoints return HTTP 201 Created.**  
**Path pattern**: `POST /message/{method}/{instanceName}`

> **BROKEN ON BAILEYS — sendButtons and sendList**: Both return HTTP 200/201 but messages do not deliver to recipients on Baileys as of v2.3.7. Issues #2390 (list) and #2404 (buttons) are closed "not planned". Use Cloud API (`WHATSAPP-BUSINESS`) if you need these features.

| Endpoint | Method + Path | Purpose | Key body fields | Baileys | Cloud API |
|---|---|---|---|---|---|
| Send text | `POST /message/sendText/{instance}` | Plain text, optionally with URL preview | `text` (req) | YES | YES |
| Send media | `POST /message/sendMedia/{instance}` | Image, video, document, or audio file | `mediatype` (req): `image`\|`video`\|`document`\|`audio`; `media` (req): URL or pure base64; `mimetype` (req if base64); `caption`; `fileName` | YES | YES |
| Send PTV | `POST /message/sendPtv/{instance}` | Circular play-to-view video (not downloadable) | `video` (req): URL or base64 | YES | NO |
| Send voice note | `POST /message/sendWhatsAppAudio/{instance}` | Voice note with waveform | `audio` (req): URL or base64; `encoding` (common field — see Common Message Options above): `true` to auto-convert to opus/ogg | YES | NO |
| Send sticker | `POST /message/sendSticker/{instance}` | WebP sticker | `sticker` (req): URL or base64 of WebP file | YES | NO |
| Send location | `POST /message/sendLocation/{instance}` | Map pin | `latitude` (req), `longitude` (req), `name`, `address` | YES | YES |
| Send contact | `POST /message/sendContact/{instance}` | vCard contact(s) | `contact[]` (req): array of `{ fullName, wuid, phoneNumber, organization, email, url }` — `wuid` must be full JID (`5511999999999@s.whatsapp.net`) | YES | YES |
| Send reaction | `POST /message/sendReaction/{instance}` | Emoji reaction on a message | `key`: `{ id, fromMe, remoteJid }` (req); `reaction`: emoji string or `""` to remove | YES | YES |
| Send poll | `POST /message/sendPoll/{instance}` | Multiple-choice poll | `name` (req): question; `selectableCount` (req): max selections; `values[]` (req): answer options | YES | NO |
| **[BROKEN-BAILEYS]** Send list | `POST /message/sendList/{instance}` | Interactive list picker | `title` (req), `buttonText` (req), `sections[]` (req): `{ title, rows[]: { title, description, rowId } }`; `description`, `footerText` | BROKEN | YES |
| **[BROKEN-BAILEYS]** Send buttons | `POST /message/sendButtons/{instance}` | Interactive buttons | `title` (req), `buttons[]` (req): `{ type, displayText, id\|url\|copyCode\|phoneNumber }`; `description`, `footer`, `thumbnailUrl` | BROKEN | YES |
| Send template | `POST /message/sendTemplate/{instance}` | WhatsApp Business message template | `name` (req), `language` (req), `components[]`: `{ type, sub_type, index, parameters[] }` | NO | YES |
| Send status | `POST /message/sendStatus/{instance}` | WhatsApp Story/Status broadcast | `type` (req): `text`\|`image`\|`video`\|`audio`; `content` (req); `caption`; `backgroundColor`; `font`; `allContacts`; `statusJidList[]` | **BROKEN** (hangs, issue #2377) | NO |

### sendMedia — delivery methods

| Method | When to use | How |
|---|---|---|
| URL | Files > 3 MB, or already publicly hosted | Set `media` to a public HTTPS URL |
| Base64 | Files < 3 MB, or private/internal files | Set `media` to pure base64 string (no `data:` prefix); include `mimetype` |
| Form-data | Binary upload from client | `multipart/form-data` with binary `media` field |

### sendButtons — button types (Cloud API)

| `type` | Required extra fields | Description |
|---|---|---|
| `reply` | `id` | Quick-reply button, returns `id` as payload |
| `url` | `url` | Opens URL in browser |
| `copy` | `copyCode` | Copies text to clipboard |
| `call` | `phoneNumber` | Initiates a phone call |
| `pix` | `currency`, `name`, `keyType`, `key` | PIX payment (Brazil) |

### sendStatus — font values (text type only)

`1` = SERIF, `2` = NORICAN_REGULAR, `3` = BRYNDAN_WRITE, `4` = BEBASNEUE_REGULAR, `5` = OSWALD_HEAVY

### sendReaction — note

`sendReaction` does NOT accept the common metadata fields (`delay`, `quoted`, `mentioned`, etc.). It only accepts `key` and `reaction`.

---

## 6. Chat Controller

**Path prefix**: `/chat`  
**Auth**: instance token or global key.

| Endpoint | Method + Path | Purpose | Key body fields | Notes |
|---|---|---|---|---|
| Check WhatsApp numbers | `POST /chat/whatsappNumbers/{instance}` | Verify if phone numbers are registered on WhatsApp | `numbers[]` (req): array of phone strings | Results cached per `DATABASE_SAVE_IS_ON_WHATSAPP_DAYS` (default 7 days). Bulk-checking many numbers without rate limiting risks account ban (issue #2228) |
| Mark messages read | `POST /chat/markMessageAsRead/{instance}` | Send read receipts for specific messages | `readMessages[]`: array of `{ remoteJid, fromMe, id }` | Manual one-off. Distinct from the `readMessages` setting that auto-marks all incoming |
| Archive / unarchive chat | `POST /chat/archiveChat/{instance}` | Archive or restore a conversation | `lastMessage`: `{ key: { remoteJid, fromMe, id }, messageTimestamp }`; `chat`: JID; `archive`: boolean | **BUG (v2.3.7, issue #2495)**: returns `PrismaClientValidationError` — `archiveChat` routes through `whatsappNumber()` which queries `Contact` with an unexposed `remoteJid` filter |
| Mark chat unread | `POST /chat/markChatUnread/{instance}` | Mark conversation as unread | Same shape as `archiveChat` minus the `archive` field | Shares code path with `archiveChat`; affected by same v2.3.7 Prisma bug |
| Delete message | `DELETE /chat/deleteMessageForEveryone/{instance}` | Revoke a sent message for all participants | `id`, `fromMe`, `remoteJid`, `participant` (req for groups) | `participant` required for group messages. Response includes `protocolMessage` with type `REVOKE` |
| Edit message | `POST /chat/updateMessage/{instance}` | Edit an already-sent message | `number`, `key`: `{ remoteJid, fromMe: true, id }`, `text` (new content) | Only works for own messages (`fromMe: true`). **BUG (v2.3.7, issue #2545)**: webhook delivers `secretEncryptedMessage` instead of edited content on `messages.update` event |
| Send typing indicator | `POST /chat/sendPresence/{instance}` | Show composing/recording indicator in a specific chat | `number` (req), `presence` (req): `composing`\|`recording`\|`paused`, `delay` (ms) | Per-chat indicator. Distinct from global `/instance/setPresence` |
| Block / unblock | `POST /chat/updateBlockStatus/{instance}` | Block or unblock a contact | `number` (req), `status` (req): `block`\|`unblock` | **Doc error (v2.3.6, issue #2225)**: official docs incorrectly listed path as `/message/updateBlockStatus`; correct path is `/chat/updateBlockStatus` |
| Find contacts | `POST /chat/findContacts/{instance}` | Query local DB contact records | `where`: `{ id, remoteJid, pushName }` (all optional); `page`; `offset` | Does not call WhatsApp live. Omit `where` to list all. Fixed in v2.3.7 to honour filter fields |
| Find messages | `POST /chat/findMessages/{instance}` | Query local DB message records | `where`: `{ key: { remoteJid, fromMe } }` (optional); `page`; `offset`; `take`; `skip`; `orderBy` | Returns `{ messages: { total, pages, currentPage, records[] } }`. Controlled by `DATABASE_SAVE_DATA_NEW_MESSAGE` |
| Find status/receipts | `POST /chat/findStatusMessage/{instance}` | Query delivery/read receipt records | `where`: `{ _id, id, remoteJid, fromMe }`; `limit` | "Status" here = delivery receipts (`DELIVERY_ACK`, `READ`), not Stories. Controlled by `DATABASE_SAVE_MESSAGE_UPDATE` |
| Find chats | `POST /chat/findChats/{instance}` | Query local DB chat metadata | `{}` or `where` + pagination | Returns chat objects with `remoteJid`, `name`, `labels`, `unreadMessages`. Controlled by `DATABASE_SAVE_DATA_CHATS` |
| Find chat by JID | `GET /chat/findChatByRemoteJid/{instance}` | Fetch single chat record | Query param: `?remoteJid=5511999999999@s.whatsapp.net` | — |
| Get profile picture URL | `POST /chat/fetchProfilePictureUrl/{instance}` | Get a contact's profile photo URL | `number` (req) | — |
| Download media | `POST /chat/getBase64FromMediaMessage/{instance}` | Download a received media message as base64 | `message`: `{ key: { id, fromMe, remoteJid } }` (req); `convertToMp4`: boolean | Set `convertToMp4: true` to receive OGG voice as MP4. Known issue with iOS `ephemeralMessage`-wrapped audio (issue #2550) |
| Fetch business profile | `POST /chat/fetchBusinessProfile/{instance}` | Get WhatsApp Business account details for a number | `number` (req) | Returns name, description, email, websites, address, vertical |

### Labels (mounted at `/label`)

| Endpoint | Method + Path | Purpose | Key body fields | Notes |
|---|---|---|---|---|
| Find labels | `GET /label/findLabels/{instance}` | List WhatsApp Business labels on the account | — | Returns array of `{ id, labelId, name, color, ... }`. `labelId` is a numeric string (e.g. `"16"`) |
| Assign / remove label | `POST /label/handleLabel/{instance}` | Add or remove a label from a contact/chat | `number` (req), `labelId` (req), `action` (req): `add`\|`remove` | **BUG (v2.3.7, issue #2524)**: returns HTTP 200 but label is NOT applied — WhatsApp requires `@lid` JID for label ops; Evolution API always sends `@s.whatsapp.net` which WhatsApp silently ignores. No label-filtering on `findChats`/`findContacts` (issue #2315, closed "not planned") |

---

## 7. Groups Controller

**Path prefix**: `/group`  
**Auth**: instance token or global key. All ops require a connected (logged-in) instance.  
**Group JID format**: `{numeric-id}@g.us` (e.g. `120363123456789012@g.us`)  
**Participant JID format**: `{phone}@s.whatsapp.net`

| Endpoint | Method + Path | Purpose | Key body fields | Notes |
|---|---|---|---|---|
| Create group | `POST /group/create/{instance}` | Create a new WhatsApp group | `subject` (req), `participants[]` (req): bare phone numbers; `description`; `promoteParticipants` | Returns `{ success, group: { id, subject, creation } }`. Max 1,024 participants (WhatsApp limit) |
| Update subject | `POST /group/updateGroupSubject/{instance}` | Rename the group | `groupJid` (req), `subject` (req) | Instance must be group admin |
| Update picture | `POST /group/updateGroupPicture/{instance}` | Set group profile photo | `groupJid` (req), `image` (req): URL or base64 | Instance must be group admin |
| Update description | `POST /group/updateGroupDescription/{instance}` | Change group description | `groupJid` (req), `description` (req) | Instance must be group admin |
| Get group info | `GET /group/findGroupInfos/{instance}` | Fetch metadata for one group | Query param: `?groupJid=...` | Returns id, subject, creation, owner. Note (issue #2124): groups with null `subject` or `creation` may return 404 |
| List all groups | `GET /group/fetchAllGroups/{instance}` | List every group the instance belongs to | — | Query param: `?getParticipants=true` to include participant lists. Includes subject, size, owner, announce/restrict flags |
| List participants | `GET /group/participants/{instance}` | Get participant list for one group | Query param: `?groupJid=...` | Returns `{ participants[]: { id, isAdmin, isSuperAdmin } }` |
| Get invite code | `GET /group/inviteCode/{instance}` | Get current group invite link code | Query param: `?groupJid=...` | Returns the code portion (not full URL) |
| Get invite info | `GET /group/inviteInfo/{instance}` | Preview group metadata from invite code | Query param: `?inviteCode=...` | Does not join the group |
| Join by invite | `GET /group/acceptInviteCode/{instance}` | Join a group using an invite code | Query param: `?inviteCode=...` | State-changing action registered as GET in the router |
| Send invite | `POST /group/sendInvite/{instance}` | Send group invite link as a message | `groupJid` (req), `numbers[]` (req): bare phone numbers, `description` | — |
| Revoke invite code | `POST /group/revokeInviteCode/{instance}` | Invalidate current invite link; generate new one | `groupJid` (req) | Returns new code |
| Update participants | `POST /group/updateParticipant/{instance}` | Add, remove, promote, or demote members | `groupJid` (req), `action` (req): `add`\|`remove`\|`promote`\|`demote`, `participants[]` (req): bare phone numbers | Non-admin attempts return a WhatsApp-level error (403/500). Add large batches in small groups with delays to avoid rate limits |
| Update settings | `POST /group/updateSetting/{instance}` | Set announcement mode or info-edit lock | `groupJid` (req), `action` (req): `announcement`\|`not_announcement`\|`locked`\|`unlocked` | `announcement` = only admins can send. Instance must be admin |
| Toggle ephemeral | `POST /group/toggleEphemeral/{instance}` | Set disappearing messages timer | `groupJid` (req), `expiration` (req): `0`\|`86400`\|`604800`\|`7776000` (seconds) | `0` = disable. Instance must be admin |
| Leave group | `DELETE /group/leaveGroup/{instance}` | Remove instance from a group | `groupJid` (req) (pass as query param `?groupJid=...` if client drops DELETE body) | — |

### Group webhook events

| Event key | Wire string | Trigger |
|---|---|---|
| `GROUPS_UPSERT` | `groups.upsert` | Group created or instance joined a group |
| `GROUPS_UPDATE` | `groups.update` | Group subject, description, or picture changed |
| `GROUP_PARTICIPANTS_UPDATE` | `group-participants.update` | Participant added, removed, promoted, or demoted |

`GROUP_PARTICIPANTS_UPDATE` data payload:

```json
{
  "id": "120363123456789012@g.us",
  "participants": ["5511999999999@s.whatsapp.net"],
  "action": "add"
}
```

`action` values in webhook: `add`, `remove`, `promote`, `demote`. As of v2.3.5, LID identifiers in participant events are automatically converted to phone-based JIDs.

### Baileys constraints on groups

- Groups created via the API may show "The group is no longer available" for API-created groups in some v2.3.6 builds (issue #2165, closed "not planned").
- Message encryption to large groups triggers per-participant key fetches; add a `delay` to group sends and use `cachedGroupMetadata` Baileys option via Evolution API config to reduce ban risk.
- No hard batch limit documented for `updateParticipant`, but WhatsApp throttles bulk adds — use small batches.

---

## 8. Profile Controller

Profile endpoints are mounted on the `/chat` router.  
**Auth**: instance token or global key.

| Endpoint | Method + Path | Purpose | Key body fields | Notes |
|---|---|---|---|---|
| Fetch profile | `POST /chat/fetchProfile/{instance}` | Get WhatsApp profile for any number | `number` (req) | Returns basic profile data |
| Fetch business profile | `POST /chat/fetchBusinessProfile/{instance}` | Get WhatsApp Business details for a number | `number` (req) | Returns `isBusiness`, `name`, `description`, `email`, `websites[]`, `address`, `vertical`, `profilehandle` |
| Update display name | `POST /chat/updateProfileName/{instance}` | Change the instance account's display name | `name` (req) | Changes the WhatsApp name shown to contacts |
| Update about/status | `POST /chat/updateProfileStatus/{instance}` | Change the instance account's "About" text | `status` (req) | WhatsApp "about" field, not a message |
| Update profile picture | `POST /chat/updateProfilePicture/{instance}` | Set the instance account's profile photo | `picture` (req): URL or base64 image | — |
| Remove profile picture | `DELETE /chat/removeProfilePicture/{instance}` | Clear the current profile photo | — | No body required |
| Get privacy settings | `GET /chat/fetchPrivacySettings/{instance}` | Read current account privacy settings | — | Returns all six privacy fields with current values |
| Update privacy settings | `POST /chat/updatePrivacySettings/{instance}` | Update account privacy configuration | see table below | All fields optional per call |

### Privacy settings fields and allowed values

| Field | Allowed values | Controls |
|---|---|---|
| `readreceipts` | `all` \| `none` | Who can see read receipts |
| `profile` | `all` \| `contacts` \| `contact_blacklist` \| `none` | Who can see profile picture |
| `status` | `all` \| `contacts` \| `contact_blacklist` \| `none` | Who can see Stories/status |
| `online` | `all` \| `match_last_seen` | Who can see online status |
| `last` | `all` \| `contacts` \| `contact_blacklist` \| `none` | Who can see "last seen" |
| `groupadd` | `all` \| `contacts` \| `contact_blacklist` | Who can add this number to groups |

---

## Presence: Two Distinct Systems

| System | Endpoint | Body | Scope |
|---|---|---|---|
| Instance-level (global online/offline) | `POST /instance/setPresence/{instance}` | `{ "presence": "available" \| "unavailable" \| "composing" \| "recording" }` | Affects how the whole account appears to all contacts |
| Per-chat indicator (typing/recording) | `POST /chat/sendPresence/{instance}` | `{ "number": "...", "presence": "composing" \| "recording" \| "paused", "delay": 1200 }` | Transient indicator shown in a specific conversation; `delay` = ms to display it |

---

## Channel Feature Matrix

| Feature | Baileys (`WHATSAPP-BAILEYS`) | Cloud API (`WHATSAPP-BUSINESS`) |
|---|---|---|
| sendText | YES | YES |
| sendMedia (image/video/doc/audio) | YES | YES |
| sendLocation | YES | YES |
| sendContact | YES | YES |
| sendReaction | YES | YES |
| sendPoll | YES | NO |
| sendPtv (circular video) | YES | NO |
| sendWhatsAppAudio (voice note) | YES | NO |
| sendSticker | YES | NO |
| sendStatus (Stories) | YES — **BROKEN** v2.3.7 (issue #2377) | NO |
| sendList | **BROKEN** v2.3.7 (issue #2390) | YES |
| sendButtons | **BROKEN** v2.3.7 (issue #2404) | YES |
| sendTemplate | NO | YES |
| QR / pairing-code auth | YES | NO |
| Group operations | YES | Verify against current docs |
| Profile / privacy settings | YES | Verify against current docs |

---

## Known Bugs Summary (v2.3.7)

| Issue | Endpoint | Status |
|---|---|---|
| `sendButtons` delivers HTTP 201 but message never arrives on Baileys | `POST /message/sendButtons` | Closed "not planned" (issue #2404) |
| `sendList` throws `TypeError: this.isZero is not a function` on Baileys | `POST /message/sendList` | Closed "not planned" (issue #2390) |
| `sendStatus` / Stories hangs indefinitely, no response | `POST /message/sendStatus` | Closed "not planned" (issue #2377) |
| `mentionsEveryOne: false` still mentions everyone | All send endpoints | Closed "not planned" (issue #2431) — omit field to suppress |
| `archiveChat` / `markChatUnread` returns `PrismaClientValidationError` | `POST /chat/archiveChat`, `POST /chat/markChatUnread` | Open (issue #2495) |
| `updateMessage` webhook delivers `secretEncryptedMessage` instead of edit | `POST /chat/updateMessage` | Open (issue #2545) |
| `handleLabel` returns success but label is not applied on WhatsApp | `POST /label/handleLabel` | Open (issue #2524) — `@lid` JID mismatch |
| No endpoint to filter chats/contacts by label | `findChats`, `findContacts` | Closed "not planned" (issue #2315) |
| v2.4.0-rc2: all non-public routes return 503 until browser-based license activation completes | All business endpoints | By design in RC. Stay on v2.3.7 for headless/automated deployments |

---

## Key Environment Variables

| Variable | Default | Notes |
|---|---|---|
| `AUTHENTICATION_API_KEY` | (example in `.env.example`) | Global API key — change in production |
| `AUTHENTICATION_EXPOSE_IN_FETCH_INSTANCES` | `true` | Expose per-instance `apikey` in fetch responses |
| `DEL_INSTANCE` | `false` | Minutes before disconnected instances auto-purge; `false` = never |
| `QRCODE_LIMIT` | `30` | Max QR regeneration attempts per connection |
| `QRCODE_COLOR` | `#175197` | QR foreground color (hex) |
| `CONFIG_SESSION_PHONE_CLIENT` | `Evolution API` | Name shown in WhatsApp Linked Devices |
| `CONFIG_SESSION_PHONE_NAME` | `Chrome` | Browser label in Linked Devices |
| `WEBHOOK_GLOBAL_ENABLED` | `false` | Single global webhook for all instances |
| `WEBHOOK_GLOBAL_URL` | (empty) | URL for global webhook |
| `WEBHOOK_RETRY_MAX_ATTEMPTS` | `10` | Retry count for failed webhook deliveries |
| `WEBHOOK_RETRY_USE_EXPONENTIAL_BACKOFF` | `true` | Exponential backoff on webhook retry |
| `WEBHOOK_RETRY_NON_RETRYABLE_STATUS_CODES` | `400,401,403,404,422` | Skip retry for these HTTP status codes |
| `DATABASE_SAVE_DATA_INSTANCE` | `true` | Persist instance credentials and state |
| `DATABASE_SAVE_DATA_NEW_MESSAGE` | `true` | Persist incoming/outgoing messages |
| `DATABASE_SAVE_MESSAGE_UPDATE` | `true` | Persist delivery/read receipt events |
| `DATABASE_SAVE_DATA_CONTACTS` | `true` | Persist contact records |
| `DATABASE_SAVE_DATA_CHATS` | `true` | Persist chat metadata |
| `DATABASE_SAVE_DATA_LABELS` | `true` | Persist label associations |
| `DATABASE_SAVE_IS_ON_WHATSAPP` | `true` | Cache number-verification results |
| `DATABASE_SAVE_IS_ON_WHATSAPP_DAYS` | `7` | Retention days for number-verification cache |
| `CACHE_REDIS_ENABLED` | `true` | Enable Redis cache layer |
| `CACHE_REDIS_SAVE_INSTANCES` | `false` | Store session credentials in Redis |
| `PROVIDER_ENABLED` | `false` | Enable S3/MinIO session storage |
| `PROXY_HOST` / `PROXY_PORT` / `PROXY_PROTOCOL` | (empty) | Global proxy fallback |
| `PROXY_USERNAME` / `PROXY_PASSWORD` | (empty) | Global proxy credentials |

---

## Sources

- https://github.com/evolution-foundation/evolution-api
- https://github.com/EvolutionAPI/evolution-api
- https://docs.evolutionfoundation.com.br/
- https://docs.evolutionfoundation.com.br/llms.txt
- https://deepwiki.com/EvolutionAPI/evolution-api
- https://deepwiki.com/EvolutionAPI/evolution-api/7-api-reference
- https://deepwiki.com/EvolutionAPI/evolution-api/7.1-instance-management-api
- https://deepwiki.com/EvolutionAPI/evolution-api/7.2-message-and-chat-api
- https://deepwiki.com/EvolutionAPI/evolution-api/3-whatsapp-integration
- https://deepwiki.com/EvolutionAPI/evolution-api/1.3-configuration
- https://deepwiki.com/EvolutionAPI/evolution-api/2.3-data-model-and-schema
- https://deepwiki.com/EvolutionAPI/evolution-api/4.2-message-types-and-parsing
- https://evolutionapi-evolution-api-90.mintlify.app/concepts/authentication
- https://evolutionapi-evolution-api-90.mintlify.app/concepts/instances
- https://evolutionapi-evolution-api-90.mintlify.app/concepts/webhooks
- https://raw.githubusercontent.com/evolution-foundation/evolution-api/main/.env.example
- https://raw.githubusercontent.com/evolution-foundation/evolution-api/main/src/api/dto/sendMessage.dto.ts
- https://raw.githubusercontent.com/evolution-foundation/evolution-api/main/src/api/routes/sendMessage.router.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/routes/chat.router.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/dto/chat.dto.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/routes/group.router.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/controllers/group.controller.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/dto/group.dto.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/routes/label.router.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/src/api/types/wa.types.ts
- https://raw.githubusercontent.com/EvolutionAPI/evolution-api/main/prisma/postgresql-schema.prisma
- https://github.com/EvolutionAPI/evolution-api/blob/main/CHANGELOG.md
- https://github.com/evolution-foundation/evolution-api/releases
- https://github.com/EvolutionAPI/evolution-api/issues/2390
- https://github.com/EvolutionAPI/evolution-api/issues/2404
- https://github.com/EvolutionAPI/evolution-api/issues/2431
- https://github.com/EvolutionAPI/evolution-api/issues/2377
- https://github.com/EvolutionAPI/evolution-api/issues/2495
- https://github.com/EvolutionAPI/evolution-api/issues/2524
- https://github.com/EvolutionAPI/evolution-api/issues/2545
- https://github.com/EvolutionAPI/evolution-api/issues/2315
- https://github.com/EvolutionAPI/evolution-api/issues/2225
- https://github.com/EvolutionAPI/evolution-api/issues/2228
- https://github.com/EvolutionAPI/evolution-api/issues/2124
- https://github.com/EvolutionAPI/evolution-api/issues/2165
- https://github.com/evolution-foundation/evolution-api/issues/2534
- https://www.postman.com/agenciadgcode/evolution-api/documentation/jn0bbzv/evolution-api-v2-2-2
- https://baileys.wiki/docs/api/type-aliases/WAPresence/
- https://huggingface.co/spaces/oex2003/evolution-api/blob/main/src/api/dto/settings.dto.ts
- https://docs.evolutionfoundation.com.br/licensing/activation
