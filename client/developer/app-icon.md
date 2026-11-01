# TalkDock launcher icon

## Design and assets

- User-selected illustration: a smiling grandmother and grandson beneath a roof, with a heart between them.
- Colors follow the in-app palette (2026-11-01): roof and heart use `todak_accent` `#BE5239`, cheeks a warm peach `#F2B196`, and the background `todak_blush` `#FFEFE1`. Outlines, hair and faces keep their original colors. The original pink roof, red heart and pink cheeks were recolored in place; the characters were not redrawn.
- Use the supplied image without regenerating or redrawing the characters. It replaces the earlier speech-bubble icon exploration.
- Source supplied on 2026-10-26: 1254 × 1254 PNG. Packaged asset: `app/src/main/res/drawable-nodpi/todak_launcher_mark.png` (648 × 648 PNG), uniformly resized for Android resources.
- Adaptive icon: `app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml`.
- Foreground: `app/src/main/res/drawable/ic_launcher_foreground.xml`, with a 10dp inset to keep the roof and faces inside launcher masks.
- Background: `#FFEFE1` (`todak_launcher_background` in `res/values/launcher_colors.xml`), matching the recolored mark.
- In-app header logo: `app/src/main/res/drawable-nodpi/todak_logo.png`, a transparent-background version of the same artwork with the "토닥" wordmark, recolored the same way. It replaces the text title on the home and daily tabs.
- The web favicon (`web/assets/favicon.svg`) still embeds the original pink artwork.
- The manifest uses `@mipmap/ic_launcher`; the minimum SDK is 26, so all supported devices can use the adaptive icon.
- App icon resources only; no backend or in-app character changes.

## Verification

Verified on 2026-10-26 KST:

- `JAVA_HOME='/Applications/Android Studio.app/Contents/jbr/Contents/Home' client/gradlew -p client :app:assembleDebug :app:lintDebug -PtalkDockApiUrl=https://talkdock.app/api/` passed.
- Installed the debug APK as an update on the Android API 36 emulator, preserving app data.
- Inspected the actual circular launcher icon: the roof, heart, grandmother and grandson are visible without clipping.
- The icon is included in the frontend icons and web usability pull request.
