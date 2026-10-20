# iPhone Use

[中文](README.md) · **English**

This project is a fork of [zhongerxin/iPhone-use](https://github.com/zhongerxin/iPhone-use), maintained to customize and improve features for our needs and gradually extend support to more AI agents, so they can use iPhone Use to operate real iPhones. Thank you to the original author for sharing this work as open source.

![iPhone Use controlling a real iPhone in Codex with a live screen preview](assets/iphone-use-demo.png)

Let an AI agent with local MCP and skill support operate your real iPhone over USB. Describe a task in natural language: open apps, read screens, tap, scroll, enter text, collect lists, and watch the phone in a native sidebar or browser panel.

The plugin connects to [WebDriverAgent](https://github.com/appium/WebDriverAgent) (WDA). It includes a local MCP server, setup and usage skills, and a live screen widget. It reuses healthy connections and existing builds; when element targeting fails, it guides the model to inspect a screenshot and try coordinates.

The plugin sends anonymous usage statistics to its own PostHog project and GA4 property by default: usage starts, tool calls, connection results, durations and error categories. It uses a random installation ID and never uploads phone images, input text or device identifiers. Set `IPHONE_USE_ANALYTICS=0` or `DO_NOT_TRACK=1` and restart the MCP server to disable it. See [analytics documentation](ANALYTICS.md).

**Before using iPhone Use, install, sign, and start WDA Runner on your own iPhone.** WDA is the on-device execution service. The prompts and setup workflow below can help your host assistant complete the initial installation; a healthy existing WDA can be reused.

## Recent updates

October 9–13, 2026. See the [changelog](CHANGELOG.md) for details.

- **Direct preview control**: tap the image, drag with the mouse, or scroll with two fingers on a trackpad.
- **WeChat tap improvements**: use screenshots to tap known navigation targets, with lighter reads for contacts and conversation lists.
- **AirDrop file transfer**: new usage-skill guidance for sending phone photos, videos, and documents to your Mac.
- **Screen reading improvements**: leaner trees, a 200-node default output limit, and optional snapshot limits for large lists.
- **Connection recovery improvements**: clearer timeout and disconnect guidance, with automatic restoration of temporary snapshot settings.
- **Safer long-text continuation**: input stays bound to the original field and stops when the app or focus changes.

## Browser phone panel

The native sidebar and browser use the same panel code: live video, taps, mouse drags, trackpad and wheel scrolling, Refresh, Home, and screenshots copied to the Mac clipboard. Device appearance, activity effects, locking and authentication handoff remain the same. The browser service is local to the Mac connected to the phone.

After successful startup or READY, agents provide a clickable phone-screen link from `browser_url`. At the start of each new phone task, proactively show the screen: reuse and reveal an existing native panel or phone page, opening one only if absent or closed. Use a sidebar browser when there is no native panel. Without a sidebar browser, provide the link and open an external browser only when requested. Do not guess the port.

```sh
# Start a configured USB iPhone and open its browser panel
python3 scripts/launch_screen.py
# Start and print the URL without opening an external browser
python3 scripts/launch_screen.py --no-open
# Manage only the browser service; leave WDA running
python3 scripts/browser.py start
python3 scripts/browser.py status
python3 scripts/browser.py stop
```

### Manually start the phone screen after installation

After installing iPhone Use and completing the initial WDA signing setup, connect and unlock the iPhone, then double-click the desktop shortcut `启动iPhone屏幕.command` (Start iPhone Screen). It starts or reuses WDA, verifies READY, opens the browser panel, and prints its actual URL. One USB device is selected automatically; multiple devices prompt for a choice.

This is the everyday manual startup entry. Complete plugin installation and initial signing first. The Codex installer creates or updates the desktop shortcut. For other installation methods, run `python3 scripts/launch_screen.py --install-desktop` from that installation's directory.

The same [launcher](启动iPhone屏幕.command) is included at the project root in both source and plugin packages. It locates `scripts/launch_screen.py` relative to itself, supports paths containing spaces, and contains no fixed username, Codex cache location, or plugin version. Keep the full project directory together, or run from that directory:

```sh
sh ./启动iPhone屏幕.command
```

Each user generates their own desktop shortcut using their `$HOME` and actual installation location. Share the project rather than a personal desktop shortcut. Regenerate the shortcut after moving the installation directory.

The service defaults to `127.0.0.1:18101`, selecting a free port on conflict. The returned URL contains a local access token. Repeated starts reuse the service; closing the page does not stop WDA. Both panels share operation locks and authentication pauses. See [browser commands and recovery](skills/iphone-use/references/browser.md).

The complete itemized real-device, browser, automated, and host acceptance record is in the [0.4.0 acceptance report](ACCEPTANCE-0.4.0.md).

## Universal installation prompt

Paste the same prompt into your current agent. Codex, WorkBuddy, Doubao Work, and other agents with the required integration capabilities share this workflow. The agent selects its host's installation entry below and displays the phone using the capabilities actually available.

```text
Install and configure iPhone Use on this Mac so the current agent can operate
my real iPhone over USB:
https://github.com/jb522185660/iPhone-use

Read the repository README, the current agent's adapter documentation, and the
installer first. Identify the agent's plugin, MCP, skill, and screen display
capabilities, then select the matching installation method. Install the local
service and both skills: iphone-use and iphone-use-setup. If there is no dedicated
adapter, check whether the agent can connect using STDIO MCP and its skill
mechanism. Do not reuse another agent's installer or assume unverified support.

Check Python, Node.js, npm, full Xcode, and the USB-connected iPhone.
Clone or reuse a local checkout, preserving existing changes. Identify missing
dependencies and help resolve them. Give host-specific steps for enabling
connectors, importing skills, or reopening the conversation, and confirm that
the tools and both skills are loaded before continuing.

Read iphone-use-setup and query setup status first. Reuse existing device
configuration, healthy WDA, existing builds, or an active startup job instead of
reinstalling or starting duplicate jobs. For initial setup, use my own iPhone,
Apple development team, and signable Bundle ID. Complete the necessary signing,
build, and startup steps until pua_ready returns ready=true.

When WDA needs to be built, first try the full Xcode already installed here.
Do not infer that an upgrade is required solely from iOS, Xcode, or SDK version
numbers. Only when an actual error identifies a compatibility issue, explain it
and wait for my confirmation before downloading or switching Xcode. Preserve
existing Xcode installations and the system default developer directory.

After READY succeeds and at the start of each subsequent new phone task,
proactively show the screen:
1. Prefer and reuse the native phone panel when supported. If READY does not
   open it automatically, call pua_screen as directed by the adapter documentation.
2. If there is no native panel but a sidebar browser is available, open the
   actual browser_url in that sidebar browser.
3. Without a sidebar browser, provide a clickable link. Open an external
   browser only when I ask.
Always include the actual browser_url as a clickable link in your reply.
Reuse and reveal an existing panel or phone page; open one only if absent or
closed. Confirm the user can see it, rather than relying on background navigation.
Do not repeat READY for display or reopen after every action. Honor explicit
requests not to show the screen. Do not guess ports or hardcode usernames,
installation directories, or plugin versions.

Finally, verify 12×34=408 in the iPhone Calculator and report installation status,
whether both skills are loaded, and the screen display method used.

If Apple account login, device trust, Developer Mode, passwords, unlocking, or
Face ID require my input, give exact steps and wait for me to finish. Never
replay phone operations whose results are uncertain.
```

### Host installation entries

The prompt is shared; choose the installer and connector/skill activation steps for the current host. Run the matching entry from the local source directory:

| Host | Installation entry | Connect after installation |
| --- | --- | --- |
| Codex | `sh scripts/install.sh` (requires Codex CLI) | Installs the plugin, MCP server, and both skills; reconnect or start a new chat and enable them |
| [WorkBuddy](https://github.com/jb522185660/iPhone-use/blob/main/workbuddy/README.md) | `python3 workbuddy/install.py` | Installs the service and both skills; trust `iphone_use` in Connector Management, then start a new chat |
| [Doubao Work](https://github.com/jb522185660/iPhone-use/blob/main/doubao/README.md) | `python3 doubao/install.py` | Add a STDIO connector using the installer output, upload and enable both skills, then start a Local Computer task |
| Other agents | First confirm local STDIO MCP and skill support | Register `iphone_use` using `/bin/sh` and the actual path to `scripts/mcp.sh` in the installation; import `skills/iphone-use` and `skills/iphone-use-setup` |

Other agents must use actual local paths and retain the complete project directory. The server needs access to this Mac's USB devices, Xcode, and loopback network. Validate integration, native panels, and sidebar browsers in the actual host.

Hosts share local device configuration, WDA builds, and the operation lock, so existing phone setup is reused. WorkBuddy and Doubao adapters do not require Codex CLI and disable anonymous usage statistics by default.

If tools or skills are missing, check that the connector and both skills are enabled, then reconnect or start a new chat / Local Computer task as required by the host. Give exact locations for UI steps requiring the user's input and wait for completion. Repository access requires the appropriate permissions; an available source package can also be used.

## Requirements

| Requirement | Purpose |
| --- | --- |
| macOS and an agent supporting local STDIO MCP and skills | Local service and phone panel; only the Codex installer requires Codex CLI |
| Full Xcode with first-launch setup completed | Build, sign, deploy, and run WDA; Command Line Tools alone are insufficient |
| An Apple account and development team available in Xcode | Sign the on-device WDA Runner |
| A real iPhone connected over USB | Trust the Mac, enable Developer Mode when required, and keep it unlocked during installation / startup |
| Python 3.9+ | Run the MCP server using Python's standard library |
| Node.js 20.19+, 22.12+, or 24+; npm 10+ | USB forwarding and screen streaming; see the project engines and doctor checks |

Xcode must support the phone's iOS version. No jailbreak or separate Appium Server is required. Setup uses a verified, pinned WDA 16.14.0 commit and manages downloads, dependencies, signing, and builds locally.

## Install and start WDA on your own iPhone

The phone-side service comes from [Appium's WebDriverAgent](https://github.com/appium/WebDriverAgent). First-time setup signs and installs `WebDriverAgentRunner` using your own Apple account and development team.

The installation prompt and `iphone-use-setup` workflow fetch the project's pinned WDA version, configure signing, build, deploy, and start it. The current agent will explain any steps requiring your input.

For manual Xcode setup:

1. Connect your iPhone over USB, trust the Mac, enable Developer Mode when required, and configure your Apple account in Xcode.
2. Open `WebDriverAgent.xcodeproj`, select the `WebDriverAgentRunner` scheme and your iPhone, and configure your Team and a signable Bundle Identifier in the Runner target's **Signing & Capabilities**.
3. Use **Product → Test** to build, install, and start the runner. Complete any trust prompts on the phone. The WDA service must remain running.

After installing the plugin and configuring USB connectivity, start phone tasks only when `pua_ready` returns `ready=true`. See [Appium's device preparation guide](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/device-setup/) for device and signing requirements.

## Install and connect

```sh
git clone https://github.com/jb522185660/iPhone-use.git
cd iPhone-use
```

Select the installation entry for your host from the table above. The Codex installer validates and stages the source, registers a local Codex marketplace, installs the plugin and skills, and registers the installed server as standard MCP `iphone_use`. Plugin and standard configuration share the same namespace to avoid duplicate tools. An extracted source package uses the matching host entry as well.

Enable the service and both skills, then reconnect or start a new conversation as required by the host and ask:

> Use iphone-use-setup to configure my USB-connected iPhone, install and start WDA, verify READY, and show the phone screen.

Setup covers diagnostics, device discovery, signing configuration, download, background build, and startup. Existing configurations and builds are reused. Phone tasks start only after `pua_ready` returns `ready=true`.

## Features

| Feature | Behavior |
| --- | --- |
| App navigation | Launch apps and navigate search, details, settings, or drafts |
| Screen reading | Compact accessibility trees, text, positions, and actual screenshots |
| Taps and gestures | Element or coordinate taps, swipes, drags, and bounded waits |
| Unicode and long text | Complete text input, chunked long-text entry, and continuation |
| Batch workflows | Combine known actions into one call to reduce model round trips |
| List search and collection | Bounded scrolling, overlap, deduplication, and explicit coverage |
| Visual recovery | Inspect a fresh screenshot when targets are occluded, unfocused, or missing from the tree |
| Live preview | An iPhone frame, status, edge effects, and visible tap / drag indicators |
| Connection recovery | Reuse startup jobs, recreate invalid sessions, and reconnect preview with Refresh |

Example prompts:

```text
Open Notes, create a draft with the following text, verify it, and leave it there.

Open the target app, search for this name, and summarize the first few results.

Read this list while scrolling with overlap. Deduplicate entries and state the
covered range and any remaining uncertainty.

```

Text input and submission are separate; text is not submitted by default. The model checks key screens, recipients, counts, and final results. Passwords, verification codes, and Face ID are handled by the user. While waiting for unlock or authentication, the widget retains the last preview beneath a translucent black overlay with a handoff gesture icon and the prompt “请在手机上接管操作” (take over on your phone). The overlay disappears when the preview resumes.

Repeated preview opens in the same chat reuse the existing widget. Its toolbar offers Refresh, Home, and Screenshot. The appearance follows the connected model: only supported models show a Dynamic Island; other known rounded-screen models keep the rounded corners and frame. Pre-iPhone X models, all iPhone SE models, and unrecognized devices use a plain rectangular screen with no chassis. Without an image, the screen shows a centered status icon; the top badge displays the connection or pause state. The preview is for the user; model decisions use actual tool observations.

## Technical details

- **Local USB transport:** Python accesses WDA through a loopback-only forwarder; runtime and signing data stay on the Mac.
- **Reuse:** persistent HTTP connections, WDA sessions, healthy services, and builds reduce repeated work.
- **Compact observations and compound actions:** omit duplicate tree fields, skip XML for screenshot-only reads, and reduce turns with batch / scroll-search / list collection.
- **Background setup:** downloads, builds, and startup return queryable job IDs; repeated setup reuses matching active jobs.
- **Screenshot fallback:** inspect the image and multiply pixels by `image.pixel_to_point` to obtain iPhone point coordinates for `pua_tap`.
- **Explicit failure semantics:** a shared operation lock guards concurrent processes; uncertain mutations require reading the actual state before retrying.
- **Preview lifecycle:** streamed frames are not saved to disk; lock-induced pauses and explicit pauses are distinguished, and Refresh can reconnect.

These changes reduce duplicate requests and model round trips. Overall task speed still depends on the app, USB / WDA state, and model response time. Engineering regressions and device acceptance checks are recorded separately in local development notes.

## Tools

There are 18 model tools and 2 additional widget-only tools.

| Tools | Purpose |
| --- | --- |
| `pua_doctor`, `pua_setup`, `pua_ready` | Diagnostics, configuration, background installation / startup, readiness |
| `pua_observe`, `pua_find` | Trees, observation screenshots, and target queries |
| `pua_screenshot` | Take an iOS system screenshot into iPhone Photos for use or sharing on the phone |
| `pua_apps`, `pua_launch_app` | App identifiers, installation evidence, app launch |
| `pua_tap`, `pua_swipe`, `pua_press_button` | Taps, swipes, and device buttons |
| `pua_type_text`, `pua_wait` | Unicode input and bounded waits |
| `pua_batch`, `pua_scroll_find`, `pua_collect_list` | Compound actions, search, collection |
| `pua_screen`, `pua_metrics` | Preview controls and bounded timing statistics |

Abnormal UI states return a screenshot for the model to inspect before choosing another action. Scroll search performs at most one swipe per call and stops if the target remains unreachable; occlusion, unproven scroll progress, input mismatch, and failed page expectations use the same fallback. Existing screenshots are reused, without automatic extra gestures or action replay.

## Runtime data and updates

New installations use `~/.local/share/iphone-use/`. Set `IPHONE_USE_STATE_DIR` for another external directory; `WDA_STATE_DIR` remains supported. If the new default directory does not exist, an existing older configuration directory is reused so device configuration and builds are retained.

Runtime directories use mode 700 and private configuration / image files use 600. Explicit screenshots have retention limits; preview streams stay in memory. Signing material, device data, logs, and dependency directories are excluded from source packages. `WDA_URL` accepts a local address; the default forwarded port is 18100, and remote addresses are rejected.

```sh
git pull --ff-only
sh scripts/install.sh
```

Reconnect the chat after updating. For connection failures, check USB, unlocking, Developer Mode, signing, and the specific setup error. Query an existing startup job before restarting again.

## Development and documentation

```sh
npm ci --prefix ui --no-audit --no-fund
npm run build --prefix ui
sh scripts/check.sh
python3 scripts/package.py
```

The UI builds into self-contained HTML. Source packages are written to `dist/iphone-use-<version>-source.zip`; normal installation and use do not require rebuilding the UI. Installed plugins retain the complete widget source, styles, build scripts, configuration, dependency lockfile, and widget tests for local maintenance.

See [screen preview and recovery](skills/iphone-use/references/screen.md), [app identifiers](skills/iphone-use/references/apps.md), [troubleshooting](skills/iphone-use-setup/references/troubleshooting.md), and [changelog](CHANGELOG.md).

## Dependencies and acknowledgements

Special thanks to the original author, [zhongerxin](https://github.com/zhongerxin), for creating and open-sourcing [iPhone Use](https://github.com/zhongerxin/iPhone-use), including phone control, setup workflows, and live screen previews. The feature customization and agent integrations in this fork build on that work.

This project relies on the [Appium](https://github.com/appium/appium) ecosystem and [WebDriverAgent](https://github.com/appium/WebDriverAgent). WDA provides the on-device automation service; [appium-ios-device](https://github.com/appium/appium-ios-device) provides USB device communication, port forwarding, and screen-stream connectivity. iPhone Use adds the Codex plugin, MCP tools, setup guidance, and screen widget. A separate Appium Server is not required.

Thanks to the maintainers and contributors of Appium, WebDriverAgent, and related projects for making real iPhone automation possible.

MIT License. See [third-party notices](THIRD_PARTY_NOTICES.md).

### Direct preview interaction

Click the live phone image to tap, or drag and release to swipe. Coordinates follow the displayed image as the panel resizes. Two-finger trackpad scrolling and mouse wheels scroll or page the phone, following the system scroll direction. Each wheel burst sends one swipe; momentum and input received during an operation are not queued. Long presses, phone multi-touch, pinch zoom, and keyboard input are not supported. Input is disabled while the preview is paused, offline, stale, or busy. Cancelled gestures and releases outside the image do nothing. Timed-out gestures are never replayed automatically; inspect the phone before trying again.
