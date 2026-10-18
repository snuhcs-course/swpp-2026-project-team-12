package kr.talkdock.app.ui

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Rect
import android.os.Handler
import android.os.Looper
import android.util.LruCache
import android.view.View
import android.view.ViewTreeObserver
import android.widget.ImageView
import kr.talkdock.app.data.ApiClient
import java.lang.ref.WeakReference
import java.util.WeakHashMap
import java.util.concurrent.Executors
import kotlin.math.max
import kotlin.math.roundToInt

/** Load only visible feed images; share downloads but decode each display size separately. */
class ViewportPhotoLoader(private val root: View) : AutoCloseable {
    private data class Source(val server: String, val token: String, val url: String)
    private data class SizeKey(val source: Source, val width: Int, val height: Int)
    private class Binding(view: ImageView, val client: ApiClient, val source: Source, val thumbnail: Boolean) {
        val view = WeakReference(view)
        var requested: SizeKey? = null
    }
    private class Download(val generation: Int) { val waiting = mutableListOf<Pair<Binding, SizeKey>>() }
    private val main = Handler(Looper.getMainLooper())
    private val workers = Executors.newFixedThreadPool(2)
    private val bindings = WeakHashMap<ImageView, Binding>()
    private val downloads = mutableMapOf<Source, Download>()
    private val decodes = mutableMapOf<SizeKey, MutableList<Binding>>()
    private val bitmaps = object : LruCache<SizeKey, Bitmap>(12 * 1024 * 1024) {
        override fun sizeOf(key: SizeKey, value: Bitmap) = value.allocationByteCount
    }
    private val bytes = object : LruCache<Source, ByteArray>(4 * 1024 * 1024) {
        override fun sizeOf(key: Source, value: ByteArray) = value.size
    }
    private var generation = 0
    private var queued = false
    private var closed = false
    private val updateTask = Runnable { queued = false; update() }
    private val scrollListener = ViewTreeObserver.OnScrollChangedListener { schedule() }
    private val globalListener = ViewTreeObserver.OnGlobalLayoutListener { schedule() }
    private val layoutListener = View.OnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> schedule() }
    private val attachListener = object : View.OnAttachStateChangeListener {
        override fun onViewAttachedToWindow(view: View) = schedule()
        override fun onViewDetachedFromWindow(view: View) {
            (view as? ImageView)?.setImageDrawable(null)
            bindings[view]?.requested = null
        }
    }

    init {
        root.viewTreeObserver.addOnScrollChangedListener(scrollListener)
        root.viewTreeObserver.addOnGlobalLayoutListener(globalListener)
    }

    fun bind(view: ImageView, client: ApiClient, url: String, thumbnail: Boolean = false) {
        release(view)
        if (closed) return
        bindings[view] = Binding(view, client, Source(client.baseUrl, client.token, url), thumbnail)
        view.addOnLayoutChangeListener(layoutListener)
        view.addOnAttachStateChangeListener(attachListener)
        schedule()
    }

    fun release(view: ImageView) {
        bindings.remove(view)
        view.removeOnLayoutChangeListener(layoutListener)
        view.removeOnAttachStateChangeListener(attachListener)
        view.setImageDrawable(null)
    }

    fun clearViews() {
        bindings.keys.toList().forEach { release(it) }
    }

    fun clear() {
        generation++
        clearViews()
        downloads.clear(); decodes.clear(); bitmaps.evictAll(); bytes.evictAll()
    }

    private fun schedule() {
        if (!closed && !queued) { queued = true; main.post(updateTask) }
    }

    private fun anchor(view: ImageView, binding: Binding): View {
        if (!binding.thumbnail) {
            var parent = view.parent
            while (parent is View) {
                if (parent is PhotoCarousel) return parent
                parent = parent.parent
            }
        }
        return view
    }

    private fun visible(view: ImageView, binding: Binding): Boolean =
        view.isAttachedToWindow && view.windowVisibility == View.VISIBLE && view.width > 0 &&
            anchor(view, binding).getGlobalVisibleRect(Rect())

    private fun update() {
        if (closed) return
        for ((view, binding) in bindings.entries.toList()) {
            if (!visible(view, binding)) {
                binding.requested = null
                view.setImageDrawable(null)
                continue
            }
            val key = SizeKey(binding.source, view.width.coerceAtLeast(1),
                if (binding.thumbnail) view.height.coerceAtLeast(1) else 0)
            if (binding.requested == key) continue
            binding.requested = key
            val cached = bitmaps.get(key)
            if (cached != null) { view.setImageBitmap(cached); continue }
            val compressed = bytes.get(key.source)
            if (compressed != null) { decode(binding, key, compressed); continue }
            val active = downloads[key.source]
            if (active != null) { active.waiting.add(binding to key); continue }
            val download = Download(generation).apply { waiting.add(binding to key) }
            downloads[key.source] = download
            workers.execute {
                val result = runCatching { binding.client.image(key.source.url) }
                main.post {
                    if (closed || download.generation != generation || downloads[key.source] !== download) return@post
                    downloads.remove(key.source)
                    result.fold({ data ->
                        bytes.put(key.source, data)
                        download.waiting.forEach { (target, size) ->
                            if (current(target, size)) decode(target, size, data)
                        }
                    }, {
                        download.waiting.forEach { (target, size) ->
                            if (current(target, size)) target.view.get()?.contentDescription = "사진을 불러오지 못했어요."
                        }
                    })
                }
            }
        }
    }

    private fun current(binding: Binding, key: SizeKey): Boolean {
        val view = binding.view.get() ?: return false
        return bindings[view] === binding && binding.requested == key && visible(view, binding)
    }

    private fun decode(binding: Binding, key: SizeKey, data: ByteArray) {
        val existing = decodes[key]
        if (existing != null) { existing.add(binding); return }
        val waiting = mutableListOf(binding)
        decodes[key] = waiting
        val started = generation
        workers.execute {
            val bitmap = runCatching { displayBitmap(data, key.width, key.height) }.getOrNull()
            main.post {
                if (closed || started != generation || decodes[key] !== waiting) return@post
                decodes.remove(key)
                if (bitmap != null) bitmaps.put(key, bitmap)
                for (target in waiting) if (current(target, key)) {
                    target.view.get()?.let { view ->
                        if (bitmap != null) view.setImageBitmap(bitmap)
                        else view.contentDescription = "사진을 불러오지 못했어요."
                    }
                }
            }
        }
    }

    private fun displayBitmap(data: ByteArray, width: Int, height: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(data, 0, data.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        val ratio = if (height == 0) width.toDouble() / bounds.outWidth
            else max(width.toDouble() / bounds.outWidth, height.toDouble() / bounds.outHeight)
        val scale = ratio.coerceAtMost(1.0)
        val targetWidth = (bounds.outWidth * scale).roundToInt().coerceAtLeast(1)
        val targetHeight = (bounds.outHeight * scale).roundToInt().coerceAtLeast(1)
        var sample = 1
        while (bounds.outWidth / (sample * 2) >= targetWidth && bounds.outHeight / (sample * 2) >= targetHeight) sample *= 2
        val decoded = BitmapFactory.decodeByteArray(data, 0, data.size,
            BitmapFactory.Options().apply { inSampleSize = sample }) ?: return null
        if (decoded.width == targetWidth && decoded.height == targetHeight) return decoded
        val scaled = Bitmap.createScaledBitmap(decoded, targetWidth, targetHeight, true)
        if (scaled !== decoded) decoded.recycle() // Not yet published to a view or shared cache.
        return scaled
    }

    override fun close() {
        clear(); closed = true; main.removeCallbacks(updateTask)
        if (root.viewTreeObserver.isAlive) {
            root.viewTreeObserver.removeOnScrollChangedListener(scrollListener)
            root.viewTreeObserver.removeOnGlobalLayoutListener(globalListener)
        }
        workers.shutdownNow()
    }
}
