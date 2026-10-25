package kr.talkdock.app.ui

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Picture
import android.view.View
import android.widget.ImageView
import com.caverock.androidsvg.SVG

/** TalkDock character artwork packaged locally; no runtime image downloads. */
class TodakArtView(context: Context, private val name: String, widthDp: Int = 300) : ImageView(context) {
    private val maxWidth = (widthDp * resources.displayMetrics.density).toInt()
    private val aspect = if (name == "together") 273f / 300f else 216f / 180f
    init {
        scaleType = ScaleType.FIT_CENTER
        setImageBitmap(bitmap(context, name))
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }
    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val available = View.MeasureSpec.getSize(widthMeasureSpec)
        val width = minOf(maxWidth, if (available > 0) available else maxWidth)
        setMeasuredDimension(width, (width * aspect).toInt())
    }
    companion object {
        private val pictures = mutableMapOf<String, Bitmap>()
        @Synchronized internal fun bitmap(context: Context, name: String): Bitmap = pictures.getOrPut(name) {
            context.assets.open("todak/td_art_$name.png").use { input ->
                requireNotNull(BitmapFactory.decodeStream(input)) { "Missing Todak artwork: $name" }
            }
        }
    }
}

/** Render the original SVGs without redrawing their paths or changing their dimensions. */
object FigmaIcons {
    private val pictures = mutableMapOf<String, Picture>()
    @Synchronized fun picture(context: Context, symbol: String, color: Int): Picture? {
        val variant = if (color == android.graphics.Color.rgb(166, 78, 68)) "active" else "idle"
        val filename = when (symbol) {
            "feed", "home", "family", "settings" -> "td_icon_${if (symbol == "feed") "home" else symbol}_$variant"
            "write", "back", "listen", "mic", "photo", "comment", "next", "close" -> "td_icon_$symbol"
            else -> return null // Existing app-specific controls retain their native icons.
        }
        return pictures.getOrPut(filename) {
            SVG.getFromAsset(context.assets, "todak/$filename.svg").renderToPicture()
        }
    }
}
