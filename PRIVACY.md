# Privacy Policy

**SeaSussed Chrome Extension**
**Last updated:** March 16, 2026

## What SeaSussed Does

SeaSussed is a Chrome extension that provides real-time seafood sustainability scores while you browse grocery websites. It analyzes product pages to identify seafood products and score them on environmental sustainability.

## Data We Collect and Process

When you click "Analyze" on a product page, the extension captures:

- A **screenshot** of the visible browser tab
- **Product images** from the page gallery
- **Page text** (product title, description, details)
- **Related product names** visible on the page

This data is sent to our backend server (hosted on Google Cloud Run) for analysis by Google's Gemini AI model. The AI identifies the seafood product and generates a sustainability score.

### Voice Mode

If you enable voice mode, your **microphone audio** is streamed to Google's Gemini Live API for real-time voice interaction. Audio is processed in real time and is not recorded or stored.

## Data We Do NOT Collect

- No personal information (name, email, account details)
- No browsing history or tracking across sites
- No cookies or persistent identifiers
- No analytics or usage telemetry

## Data Storage and Retention

**We do not store any user data.** Screenshots, page text, and audio are processed in real time and discarded immediately after analysis. No data is saved to any database, log, or file system.

## Third-Party Services

- **Google Cloud Run**: Hosts the backend server that processes analysis requests
- **Google Gemini AI (Vertex AI)**: Analyzes screenshots and page content to identify products and generate scores; processes voice audio in real time
- **NOAA FishWatch / FishBase**: Public fisheries data used for sustainability scoring (no user data is sent to these services)

## Permissions

The extension requests these Chrome permissions:

| Permission | Why |
|---|---|
| `activeTab` | Capture a screenshot of the current tab when you click Analyze |
| `scripting` | Extract product text and images from the page |
| `storage` | Save your extension preferences locally |
| `sidePanel` | Display the sustainability score panel |
| `host_permissions (<all_urls>)` | Allow analysis on any grocery website |

## Your Control

- The extension only activates when **you** click the toolbar icon
- Analysis only runs when **you** click the Analyze button
- Voice mode only activates when **you** grant microphone permission
- You can uninstall the extension at any time to remove all local data

## Open Source

SeaSussed is open source. You can review the full source code at: https://github.com/jordanlynn5/SeaSussed

## Contact

If you have questions about this privacy policy, please open an issue at: https://github.com/jordanlynn5/SeaSussed/issues
