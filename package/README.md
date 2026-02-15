# poke

The official [Poke](https://poke.com) developer toolkit — a CLI and Node.js SDK for managing authentication, MCP server connections, and programmatic access to your Poke agent.

Built by [Interaction Company](https://poke.com) in California.

## Installation

```bash
npm install -g poke
```

Requires Node.js >= 18.

## SDK

Use the SDK to interact with your Poke agent programmatically.

```bash
npm install poke
```

### Quick start

```typescript
import { Poke } from "poke";

const poke = new Poke({ apiKey: "pk_..." });

// Send a message to your agent
await poke.sendMessage("Summarize my unread emails");

// Create a webhook trigger
const webhook = await poke.createWebhook({
  condition: "When a deploy fails",
  action: "Send me a summary of the error",
});

// Fire the webhook with data
await poke.sendWebhook({
  webhookUrl: webhook.webhookUrl,
  webhookToken: webhook.webhookToken,
  data: { event: "deploy_failed", repo: "my-app", error: "OOM killed" },
});
```

### Authentication

The SDK resolves credentials in this order:

1. `apiKey` passed to the constructor
2. `POKE_API_KEY` environment variable
3. Credentials from `poke login` (`~/.config/poke/credentials.json`)

```typescript
// Option 1: Pass directly
const poke = new Poke({ apiKey: "pk_..." });

// Option 2: Set POKE_API_KEY in your environment
const poke = new Poke();

// Option 3: Run `poke login` first, then
const poke = new Poke();
```

Get your API key at [poke.com/kitchen/api-keys](https://poke.com/kitchen/api-keys).

### Methods

#### `poke.sendMessage(text)`

Send a text message to your Poke agent.

```typescript
const response = await poke.sendMessage("What meetings do I have today?");
// { success: true, message: "..." }
```

#### `poke.createWebhook({ condition, action })`

Create a webhook trigger. Returns a `webhookUrl` and `webhookToken` that you use with `sendWebhook`.

```typescript
const webhook = await poke.createWebhook({
  condition: "When a new user signs up",
  action: "Send me a welcome summary in Slack",
});
// {
//   triggerId: "...",
//   webhookUrl: "https://poke.com/api/v1/inbound/webhook",
//   webhookToken: "eyJhbG..."
// }
```

#### `poke.sendWebhook({ webhookUrl, webhookToken, data })`

Fire a webhook trigger with data. Use the `webhookUrl` and `webhookToken` returned by `createWebhook`.

```typescript
await poke.sendWebhook({
  webhookUrl: webhook.webhookUrl,
  webhookToken: webhook.webhookToken,
  data: { event: "new_signup", email: "user@example.com", plan: "pro" },
});
// { success: true }
```

### Configuration

| Option | Environment Variable | Default |
|--------|---------------------|---------|
| `apiKey` | `POKE_API_KEY` | &mdash; |
| `baseUrl` | `POKE_API` | `https://poke.com/api/v1` |

## CLI

### `poke login`

Authenticate with your Poke account. Opens a browser for device code login.

```bash
poke login
```

### `poke logout`

Clear stored credentials.

```bash
poke logout
```

### `poke whoami`

Display the currently authenticated user.

```bash
poke whoami
```

### `poke mcp add <url>`

Register a remote MCP server connection.

```bash
poke mcp add https://example.com/mcp --name "My Server"
poke mcp add https://example.com/mcp --name "My Server" --api-key sk-xxx
```

| Option | Description |
|--------|-------------|
| `-n, --name <name>` | Display name for the connection (required) |
| `-k, --api-key <key>` | API key if the server requires one |

### `poke tunnel <url>`

Expose a local MCP server to Poke via a tunnel.

```bash
poke tunnel http://localhost:3000/mcp --name "Local Dev"
```

| Option | Description |
|--------|-------------|
| `-n, --name <name>` | Display name for the connection (required) |
| `--share` | Create a shareable recipe with QR code |

The tunnel stays active until you press Ctrl+C. Tools are synced automatically every 5 minutes.

### `poke wrap`

Analyze your project with AI and generate an MCP server that exposes its capabilities, then tunnel it to Poke.

```bash
poke wrap
poke wrap --name "My Project" --share
```

| Option | Description |
|--------|-------------|
| `--port <port>` | Port for the generated MCP server (default: `8765`) |
| `-n, --name <name>` | Display name for the connection |
| `--share` | Create a shareable recipe with QR code |

Requires [uv](https://docs.astral.sh/uv/) to be installed.

## Configuration

Credentials are stored in `~/.config/poke/credentials.json` (respects `$XDG_CONFIG_HOME`).

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `POKE_API_KEY` | API key for SDK usage | &mdash; |
| `POKE_API` | API base URL | `https://poke.com/api/v1` |
| `POKE_FRONTEND` | Frontend URL | `https://poke.com` |