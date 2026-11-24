package kr.talkdock.app

import androidx.test.platform.app.InstrumentationRegistry

/**
 * How long UI waits may take before a test fails. Waits return as soon as their condition holds,
 * so a generous limit only slows down a test that is already failing; it keeps slow CI emulators
 * from failing on timing alone. Override with `-e uiTimeoutMs <ms>` (or the Gradle runner argument).
 */
internal object TestTiming {
    val UI_TIMEOUT_MS: Long = InstrumentationRegistry.getArguments().getString("uiTimeoutMs")?.toLongOrNull() ?: 15_000
}
