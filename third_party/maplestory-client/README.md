# HeavenClient

HeavenClient is a custom, made-from-scratch game client for MapleStory. It is a free, open-source project developed for educational and personal use.

## Table of Contents

- [Compatibility](#compatibility)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Required Files](#required-files)
- [Dependencies](#dependencies)
- [Troubleshooting](#troubleshooting)
- [Binaries](#binaries)
- [Donations](#donations)

---

## Compatibility

| Platform | Link |
|----------|------|
| **Server** | Compatible with version 83 servers. Tested with [HeavenMS] using v229.2. |
| **Switch** | [HeavenClientNX][Switch] |
| **Linux** | [Linux branch][Linux] |
| **Web** | [MapleStory WASM][WASM] |

---

## Getting Started

### Prerequisites

- **Visual Studio 2026** Community Edition (tested with v18.2.1)
- **Windows SDK Version:** 8.1 ([Download][Windows 8.1 SDK])
- **Platform Toolset:** v140

### Build Steps

1. Open **MapleStory.sln** in Visual Studio.
2. Verify the SDK and toolset versions are set correctly (see above).
3. Build the solution: **Build** > **Build Solution** (`Ctrl + Shift + B`).
4. Run the client: **Debug** > **Start Debugging** (`F5`).

### BeiDou resource input

This fork reads original BeiDou `Data/**/*.img` directly. Do not convert WZ files to NX or place NX artifacts beside the executable. The [NoLifeWzToNx] derivative retains only IMG metadata decoding and reference resolution.

---

## Configuration

### Build Options

Edit **MapleStory.h** to toggle build-time features:

| Option | Description |
|--------|-------------|
| `USE_ASIO` | Use Asio for networking (requires additional dependency) |
| `USE_CRYPTO` | Enable cryptography for server communication |
| `USE_NX` | Historical name for the `nl::node` resource view; this fork fills it from original IMG directories, not NX files |
| `USE_DEBUG` | Suppress generation of the Settings file |

### Runtime Settings

Default settings are defined in **Configuration.h**. A **Settings** file is generated after a game session with the same options. Editing either file works the same way, but **Settings** will not persist if deleted.

---

## Required Files

- This fork reads the BeiDou client's original `Data/**/*.img` read-only; no WZ-to-NX conversion is used.
- See **ImgFiles.h** and **ImgFiles.cpp** for the IMG category loader.
- The vendored NoLifeNx code now provides only in-memory node views; its NX disk loader has been removed.
- Upstream version information in **Configuration.h** does not identify the configured BeiDou resource version.

---

## Dependencies

| Category | Library |
|----------|---------|
| NX | [NoLifeNx] |
| WZ | TBA |
| Graphics | [GLFW3], [GLEW], [FreeType] |
| Audio | [Bass] |
| Networking | [Asio] *(optional)* |

---

## Troubleshooting

If you experience in-game glitches, UI rendering issues, or other unexpected behavior, try the following:

1. **Clean Solution** in Visual Studio.
2. **Close** Visual Studio.
3. **Delete** the following files and folders:
   - `.vs/`
   - `x64/`
   - `debug.log`
   - `MapleStory.aps`
   - `Settings`
4. **Reopen** the solution.
5. **Rebuild** the solution.

---

## Binaries

The latest build ([e3e97c2][commit]) is available here: [HeavenClient v228.3.zip][archive]

---

## Donations

If you'd like to support the continued development of HeavenClient, you can [donate here][donate].

All donations go directly toward the development of this project. Please also remember to support Nexon — this project is not meant to replace anything they offer.

> **Note:** HeavenClient is and will always be free and open-source. Do **not** pay anyone for services related to this client.

<!-- Link References -->
[HeavenMS]:          https://github.com/ryantpayton/MapleStory
[Switch]:            https://github.com/lain3d/HeavenClientNX
[Linux]:             https://github.com/ryantpayton/HeavenClient/tree/linux
[WASM]:              https://github.com/nmnsnv/maplestory-wasm
[Windows 8.1 SDK]:   https://developer.microsoft.com/en-us/windows/downloads/sdk-archive
[NoLifeWzToNx]:      https://github.com/ryantpayton/NoLifeWzToNx
[NoLifeNx]:          https://github.com/ryantpayton/NoLifeNx
[GLFW3]:             http://www.glfw.org/download.html
[GLEW]:              http://glew.sourceforge.net/
[FreeType]:          http://www.freetype.org/
[Bass]:              http://www.un4seen.com/
[Asio]:              http://think-async.com/
[commit]:            https://github.com/ryantpayton/MapleStory-Client/commit/e3e97c23fc6a92b87356fc2484c7f8b12d71bf19
[archive]:           https://1drv.ms/u/s!Al6eadQnem68on8i7qG62UBsFXpV?e=sumYue
[donate]:            https://www.paypal.com/donate?business=MZDZLUH2UC5FE&no_recurring=0&currency_code=USD
