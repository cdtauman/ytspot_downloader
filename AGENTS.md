# Project Agent Rules

This is the ytspot_downloader Windows desktop app project.

## Safety rules
- Use computer-control-mcp only for this app window.
- Before interacting with the GUI, always use list_windows and activate_window.
- Do not click, type, drag, or press keys in any other window.
- If the app window is not clearly identified, stop and ask.
- Do not interact with browser, email, Telegram, system settings, file explorer, or unrelated apps.
- Do not delete files.
- Do not modify files outside this workspace.
- Ask before running destructive commands.
- Prefer logs, tests, screenshots, and OCR over blind clicking.

## GUI verification workflow
1. Start the app from this workspace.
2. Use list_windows to find the ytspot_downloader app window.
3. Activate only the app window.
4. Use take_screenshot_with_ocr to inspect the UI.
5. Test only the requested feature inside the app.
6. If something fails, fix the code.
7. Relaunch the app.
8. Verify again with screenshot/OCR.
9. Report exactly what was tested and what changed.