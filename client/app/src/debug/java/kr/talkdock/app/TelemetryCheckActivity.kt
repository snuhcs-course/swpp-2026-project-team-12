package kr.talkdock.app

import android.app.Activity
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import kr.talkdock.app.data.Telemetry

/** Explicitly invoked on the isolated .memorydemo package; never included in release APKs. */
class TelemetryCheckActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!packageName.endsWith(".memorydemo") || !intent.getBooleanExtra("enable", false)) { finish(); return }
        Telemetry.initialize(applicationContext)
        val layout = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(32,48,32,32) }
        layout.addView(TextView(this).apply { text = "Firebase 검수 전용 · 테스트 앱 등록과 수집 설정을 확인하세요." })
        layout.addView(Button(this).apply {
            text = "테스트 이벤트 전송"
            setOnClickListener { Telemetry.start("telemetry_check").stage("check_completed") }
        })
        layout.addView(Button(this).apply {
            text = "테스트 크래시"
            setOnClickListener { throw IllegalStateException("Telemetry verification crash") }
        })
        layout.addView(Button(this).apply {
            text = "테스트 ANR · 20초 정지"
            setOnClickListener { Thread.sleep(20_000) }
        })
        setContentView(layout)
    }
}
