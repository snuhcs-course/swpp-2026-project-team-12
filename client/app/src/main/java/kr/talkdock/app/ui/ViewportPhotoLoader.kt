package kr.talkdock.app.ui

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.BitmapRegionDecoder
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
import java.util.concurrent.Future
import java.util.concurrent.ThreadPoolExecutor
import kotlin.math.min
import kotlin.math.roundToInt

/** Load only visible feed images; share downloads but decode each display size separately. */
class ViewportPhotoLoader(private val root: View) : AutoCloseable {
    private data class Source(val server: String, val token: String, val url: String)
    private data class SizeKey(val source: Source, val width: Int, val height: Int, val crop: Boolean)
    private class Binding(view: ImageView, val client: ApiClient, val source: Source, val thumbnail: Boolean) {
        val view = WeakReference(view)
        var requested: SizeKey? = null
    }
    private class Download(val generation: Int) {
        val waiting = mutableListOf<Pair<Binding, SizeKey>>()
        var task: Future<*>? = null
    }
    private class Decode(val generation: Int) {
        val waiting = mutableListOf<Binding>()
        var task: Future<*>? = null
    }
    private val main = Handler(Looper.getMainLooper())
    private val workers = Executors.newFixedThreadPool(2) as ThreadPoolExecutor
    private val bindings = WeakHashMap<ImageView, Binding>()
    private val downloads = mutableMapOf<Source, Download>()
    private val decodes = mutableMapOf<SizeKey, Decode>()
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
            cancelUnusedWork()
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
        cancelUnusedWork()
    }

    fun clearViews() {
        bindings.keys.toList().forEach { release(it) }
    }

    fun clear() {
        generation++
        clearViews()
        downloads.values.forEach { it.task?.cancel(false) }
        decodes.values.forEach { it.task?.cancel(false) }
        downloads.clear(); decodes.clear(); bitmaps.evictAll(); bytes.evictAll()
        workers.purge()
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
        view.isAttachedToWindow && view.windowVisibility == View.VISIBLE && view.width > 0 && view.height > 0 &&
            anchor(view, binding).getGlobalVisibleRect(Rect())

    private fun update() {
        if (closed) return
        for ((view, binding) in bindings.entries.toList()) {
            if (!visible(view, binding)) {
                binding.requested = null
                view.setImageDrawable(null)
                continue
            }
            val key = SizeKey(binding.source, view.width, view.height, binding.thumbnail)
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
            download.task = workers.submit {
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
        cancelUnusedWork()
    }

    private fun current(binding: Binding, key: SizeKey): Boolean {
        val view = binding.view.get() ?: return false
        return bindings[view] === binding && binding.requested == key && visible(view, binding)
    }

    // A view can disappear while another download is blocking the workers. Drop queued
    // work and its byte-array references instead of downloading the previous screen.
    private fun cancelUnusedWork() {
        val downloadIterator = downloads.iterator()
        while (downloadIterator.hasNext()) {
            val (_, work) = downloadIterator.next()
            work.waiting.removeAll { (binding, key) -> !current(binding, key) }
            if (work.waiting.isEmpty()) {
                work.task?.cancel(false)
                downloadIterator.remove()
            }
        }
        val decodeIterator = decodes.iterator()
        while (decodeIterator.hasNext()) {
            val (key, work) = decodeIterator.next()
            work.waiting.removeAll { !current(it, key) }
            if (work.waiting.isEmpty()) {
                work.task?.cancel(false)
                decodeIterator.remove()
            }
        }
        workers.purge()
    }

    private fun decode(binding: Binding, key: SizeKey, data: ByteArray) {
        val existing = decodes[key]
        if (existing != null) { existing.waiting.add(binding); return }
        val work = Decode(generation).apply { waiting.add(binding) }
        decodes[key] = work
        work.task = workers.submit {
            val bitmap = runCatching { displayBitmap(data, key.width, key.height, key.crop) }.getOrNull()
            main.post {
                if (closed || work.generation != generation || decodes[key] !== work) {
                    bitmap?.recycle() // Never published to a view or cache.
                    return@post
                }
                decodes.remove(key)
                if (bitmap != null) bitmaps.put(key, bitmap)
                for (target in work.waiting) if (current(target, key)) {
                    target.view.get()?.let { view ->
                        if (bitmap != null) view.setImageBitmap(bitmap)
                        else view.contentDescription = "사진을 불러오지 못했어요."
                    }
                }
            }
        }
    }

    @Suppress("DEPRECATION") // Byte-array region decoding is also supported on API 26.
    private fun displayBitmap(data: ByteArray, width: Int, height: Int, crop: Boolean): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(data, 0, data.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        val region = Rect(0, 0, bounds.outWidth, bounds.outHeight)
        if (crop) {
            val aspect = width.toDouble() / height
            if (bounds.outWidth.toDouble() / bounds.outHeight > aspect) {
                val cropWidth = (bounds.outHeight * aspect).roundToInt().coerceIn(1, bounds.outWidth)
                region.left = (bounds.outWidth - cropWidth) / 2
                region.right = region.left + cropWidth
            } else {
                val cropHeight = (bounds.outWidth / aspect).roundToInt().coerceIn(1, bounds.outHeight)
                region.top = (bounds.outHeight - cropHeight) / 2
                region.bottom = region.top + cropHeight
            }
        }
        val scale = min(width.toDouble() / region.width(), height.toDouble() / region.height()).coerceAtMost(1.0)
        val targetWidth = (region.width() * scale).roundToInt().coerceIn(1, width)
        val targetHeight = (region.height() * scale).roundToInt().coerceIn(1, height)
        var sample = 1
        while (region.width() / (sample * 2) >= targetWidth && region.height() / (sample * 2) >= targetHeight) sample *= 2
        val options = BitmapFactory.Options().apply { inSampleSize = sample }
        val decoded = if (crop) {
            val decoder = BitmapRegionDecoder.newInstance(data, 0, data.size, false) ?: return null
            try { decoder.decodeRegion(region, options) } finally { decoder.recycle() }
        } else BitmapFactory.decodeByteArray(data, 0, data.size, options)
        if (decoded == null) return null
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
