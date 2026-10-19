package kr.talkdock.app.ui

import android.Manifest
import android.app.Activity
import android.content.ClipData
import android.content.ContentUris
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import android.provider.Settings
import android.util.LruCache
import android.util.Size
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.widget.*
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import java.util.concurrent.Executors
import java.util.concurrent.Future

/** Local gallery with explicit selection order; no network or server dependency. */
class PhotoPickerActivity : ComponentActivity() {
    companion object { const val RESULT_URIS = "talkdock.selectedPhotos" }
    private val selection = PhotoSelection()
    private val media = mutableListOf<Media>()
    private val queries = Executors.newSingleThreadExecutor()
    private val thumbnails = Executors.newFixedThreadPool(3)
    private val cache = object : LruCache<String, Bitmap>(12 * 1024 * 1024) {
        override fun sizeOf(key: String, value: Bitmap) = value.byteCount
    }
    private lateinit var ui: Ui
    private lateinit var preview: ImageView
    private lateinit var previewHint: TextView
    private lateinit var next: Button
    private lateinit var toggle: Button
    private lateinit var count: TextView
    private lateinit var status: TextView
    private lateinit var access: Button
    private lateinit var grid: GridView
    private lateinit var adapter: GalleryAdapter
    private var previewTask: Future<*>? = null
    private var previewKey: String? = null
    private var epoch = 0
    private var loading = false
    private var hasMore = true
    private var requested = false
    private var requesting = false
    private var initiallySelected = false
    private var restorePosition = 0
    private var restoreTop = 0
    private val permissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        requesting = false
        refreshGallery()
    }

    private data class Media(val uri: String, val name: String)
    private data class Batch(val items: List<Media>, val more: Boolean, val valid: List<String>)

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        selection.restore(state?.getBoolean("multiple") ?: false,
            state?.getStringArrayList("selected").orEmpty(), state?.getString("preview"))
        requested = state?.getBoolean("requested") ?: false
        initiallySelected = state?.getBoolean("initiallySelected") ?: false
        restorePosition = state?.getInt("position") ?: 0
        restoreTop = state?.getInt("top") ?: 0
        ui = Ui(this)
        val page = ui.column().apply { setBackgroundColor(ui.milk) }
        setContentView(page)
        if (Build.VERSION.SDK_INT >= 30) {
            page.setOnApplyWindowInsetsListener { view, insets ->
                val safe = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                view.setPadding(safe.left, safe.top, safe.right, safe.bottom); insets
            }
        } else page.fitsSystemWindows = true
        val header = ui.row().apply { setPadding(ui.dp(12), ui.dp(8), ui.dp(16), ui.dp(8)); minimumHeight = ui.dp(72) }
        header.addView(ui.iconButton("back", "사진 선택 취소") { finish() })
        header.addView(ui.text("사진 선택", 22f, true), LinearLayout.LayoutParams(0, -2, 1f))
        next = actionButton("다음") { finishSelection() }
        next.setTextColor(ui.ink); next.background = ui.shape(ui.coral)
        header.addView(next, LinearLayout.LayoutParams(ui.dp(88), ui.dp(52)))
        page.addView(header)

        val box = FrameLayout(this).apply { setBackgroundColor(ui.sage) }
        preview = ImageView(this).apply {
            scaleType = ImageView.ScaleType.FIT_CENTER; contentDescription = "선택한 사진 미리보기"
        }
        previewHint = ui.text("아래에서 사진을 골라 주세요", 17f, color = ui.muted).apply { gravity = Gravity.CENTER }
        box.addView(preview, FrameLayout.LayoutParams(-1, -1))
        box.addView(previewHint, FrameLayout.LayoutParams(-1, -1))
        // Keep a usable grid on small devices and when rotated into landscape.
        val previewHeight = minOf(resources.configuration.screenWidthDp, resources.configuration.screenHeightDp / 3, 280)
        page.addView(box, LinearLayout.LayoutParams(-1, ui.dp(previewHeight)))
        val toolbar = ui.row().apply { setPadding(ui.dp(14), ui.dp(4), ui.dp(10), ui.dp(4)) }
        toolbar.addView(ui.text("최근 사진", 18f, true), LinearLayout.LayoutParams(0, -2, 1f))
        count = ui.text("", 15f, color = ui.muted).apply { setPadding(0, 0, ui.dp(10), 0) }
        toolbar.addView(count)
        toggle = actionButton("선택") {
            selection.setMultiple(!selection.isMultiple()); renderSelection()
        }
        toolbar.addView(toggle, LinearLayout.LayoutParams(ui.dp(90), ui.dp(48)))
        page.addView(toolbar)
        status = ui.text("사진을 불러오고 있어요.", 14f, color = ui.muted).apply {
            setPadding(ui.dp(14), ui.dp(4), ui.dp(14), ui.dp(4)); accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        page.addView(status)
        access = actionButton("사진 접근 허용하기") { requestAccess() }
        page.addView(access, LinearLayout.LayoutParams(-1, ui.dp(48)))
        adapter = GalleryAdapter()
        grid = GridView(this).apply {
            numColumns = 3; horizontalSpacing = ui.dp(8); verticalSpacing = ui.dp(8)
            setPadding(ui.dp(24), ui.dp(8), ui.dp(24), ui.dp(16))
            stretchMode = GridView.STRETCH_COLUMN_WIDTH; clipToPadding = false
            adapter = this@PhotoPickerActivity.adapter
            setOnItemClickListener { _, _, position, _ ->
                if (!selection.tap(media[position].uri)) toast("사진은 최대 5장까지 선택할 수 있어요.")
                renderSelection()
            }
            setOnScrollListener(object : AbsListView.OnScrollListener {
                override fun onScrollStateChanged(view: AbsListView?, scrollState: Int) {}
                override fun onScroll(view: AbsListView?, first: Int, visible: Int, total: Int) {
                    if (total > 0 && first + visible >= total - 20) loadPage()
                }
            })
        }
        page.addView(grid, LinearLayout.LayoutParams(-1, 0, 1f))
        renderSelection()
    }

    override fun onResume() {
        super.onResume()
        if (!requesting) refreshGallery()
        if (!hasAccess() && !requested) requestAccess()
    }
    override fun onPause() {
        super.onPause()
        epoch++; loading = false; previewTask?.cancel(true); previewKey = null
    }
    override fun onSaveInstanceState(out: Bundle) {
        out.putBoolean("multiple", selection.isMultiple())
        out.putStringArrayList("selected", ArrayList(selection.getSelected()))
        out.putString("preview", selection.getPreview())
        out.putBoolean("requested", requested); out.putBoolean("initiallySelected", initiallySelected)
        out.putInt("position", grid.firstVisiblePosition); out.putInt("top", grid.getChildAt(0)?.top ?: 0)
        super.onSaveInstanceState(out)
    }
    override fun onDestroy() {
        epoch++; previewTask?.cancel(true); queries.shutdownNow(); thumbnails.shutdownNow(); cache.evictAll()
        super.onDestroy()
    }

    private fun actionButton(label: String, action: () -> Unit) = Button(this).apply {
        text = label; textSize = 16f; typeface = ui.font; isAllCaps = false
        setTextColor(ui.skyDeep); background = ui.shape(ui.sky)
        minWidth = 0; minimumWidth = 0; setPadding(ui.dp(8), 0, ui.dp(8), 0)
        setOnClickListener { action() }
    }
    private fun granted(permission: String) = checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
    private fun fullAccess() = if (Build.VERSION.SDK_INT >= 33) granted(Manifest.permission.READ_MEDIA_IMAGES)
        else granted(Manifest.permission.READ_EXTERNAL_STORAGE)
    private fun hasAccess() = fullAccess() || (Build.VERSION.SDK_INT >= 34 && granted(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED))

    private fun requestAccess() {
        if (requesting) return
        if (requested && !hasAccess() && !shouldShowRequestPermissionRationale(
                if (Build.VERSION.SDK_INT >= 33) Manifest.permission.READ_MEDIA_IMAGES else Manifest.permission.READ_EXTERNAL_STORAGE)) {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
            return
        }
        requested = true; requesting = true
        permissions.launch(when {
            Build.VERSION.SDK_INT >= 34 -> arrayOf(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
            Build.VERSION.SDK_INT >= 33 -> arrayOf(Manifest.permission.READ_MEDIA_IMAGES)
            else -> arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE)
        })
    }

    private fun refreshGallery() {
        epoch++; loading = false; hasMore = true; media.clear(); cache.evictAll()
        previewKey = null; previewTask?.cancel(true); preview.setImageDrawable(null)
        adapter.notifyDataSetChanged()
        access.visibility = if (fullAccess()) View.GONE else View.VISIBLE
        access.text = if (hasAccess()) "보여줄 사진 추가 · 변경" else "사진 접근 허용하기"
        if (!hasAccess()) {
            selection.retainAvailable(emptyList()); renderSelection()
            status.text = "사진 접근을 허용하면 사진 목록이 보여요."
            return
        }
        status.text = "사진을 불러오고 있어요."
        // No cached permission assumptions: a settings change may revoke individual URIs.
        loadPage()
    }

    private fun loadPage() {
        if (loading || !hasMore || !hasAccess() || isDestroyed || isFinishing) return
        loading = true
        val requestEpoch = epoch; val offset = media.size
        val previouslySelected = selection.getSelected()
        queries.execute {
            val result = runCatching {
                val collection = if (Build.VERSION.SDK_INT >= 29) MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL)
                    else MediaStore.Images.Media.EXTERNAL_CONTENT_URI
                val items = mutableListOf<Media>(); var more = false
                contentResolver.query(collection, arrayOf(MediaStore.Images.Media._ID, MediaStore.Images.Media.DISPLAY_NAME),
                    null, null, "${MediaStore.Images.Media.DATE_ADDED} DESC, ${MediaStore.Images.Media._ID} DESC")?.use { cursor ->
                    cursor.moveToPosition(offset - 1)
                    while (items.size < 200 && cursor.moveToNext()) {
                        items.add(Media(ContentUris.withAppendedId(collection, cursor.getLong(0)).toString(), cursor.getString(1) ?: "사진"))
                    }
                    more = cursor.moveToNext()
                } ?: error("사진 목록을 읽지 못했어요.")
                val valid = if (offset == 0) previouslySelected.filter { uri ->
                    runCatching { contentResolver.openFileDescriptor(Uri.parse(uri), "r")?.use { true } ?: false }.getOrDefault(false)
                } else previouslySelected
                Batch(items, more, valid)
            }
            runOnUiThread {
                if (isDestroyed || isFinishing || requestEpoch != epoch) return@runOnUiThread
                loading = false
                result.fold({ batch ->
                    if (offset == 0) selection.retainAvailable(batch.valid)
                    media.addAll(batch.items); hasMore = batch.more
                    if (!initiallySelected && media.isNotEmpty()) {
                        initiallySelected = true
                        if (selection.getSelected().isEmpty()) selection.tap(media.first().uri)
                    }
                    status.text = when {
                        media.isEmpty() -> "보여줄 사진이 없어요. 휴대폰에 사진을 저장하거나 접근할 사진을 추가해 주세요."
                        selection.isMultiple() -> "누른 순서대로 최대 5장 · 다시 누르면 선택 취소"
                        else -> "한 장을 골라 주세요. 여러 장은 ‘선택’을 눌러 주세요."
                    }
                    renderSelection()
                    if (offset == 0 && restorePosition > 0) {
                        // Load only as many pages as needed to restore a rotated gallery.
                        if (restorePosition >= media.size && hasMore) loadPage()
                        else { grid.setSelectionFromTop(restorePosition, restoreTop); restorePosition = 0 }
                    } else if (restorePosition > 0) {
                        if (restorePosition >= media.size && hasMore) loadPage()
                        else { grid.setSelectionFromTop(restorePosition, restoreTop); restorePosition = 0 }
                    }
                }, {
                    hasMore = false; selection.retainAvailable(emptyList()); renderSelection()
                    status.text = "사진 목록을 읽지 못했어요. 접근 권한을 확인한 뒤 다시 열어 주세요."
                    access.visibility = View.VISIBLE
                })
            }
        }
    }

    private fun renderSelection() {
        val selected = selection.getSelected()
        toggle.text = if (selection.isMultiple()) "취소" else "선택"
        toggle.contentDescription = if (selection.isMultiple()) "여러 장 선택 끄기. 미리보기 사진 한 장을 남겨요" else "여러 장 선택 켜기"
        count.text = if (selection.isMultiple()) "${selected.size} / 5" else ""
        next.isEnabled = selected.isNotEmpty(); next.alpha = if (next.isEnabled) 1f else 0.4f
        next.text = if (selection.isMultiple() && selected.isNotEmpty()) "다음 (${selected.size})" else "다음"
        previewHint.visibility = if (selection.getPreview() == null) View.VISIBLE else View.GONE
        if (selection.getPreview() == null) previewHint.text = "아래에서 사진을 골라 주세요"
        val uri = selection.getPreview()
        if (uri != previewKey) {
            previewKey = uri; previewTask?.cancel(true); preview.setImageDrawable(null)
            if (uri != null) {
                val requestEpoch = epoch
                previewTask = thumbnails.submit {
                    val bitmap = runCatching { readBitmap(Uri.parse(uri), 960) }.getOrNull()
                    runOnUiThread {
                        if (!isDestroyed && requestEpoch == epoch && previewKey == uri) {
                            preview.setImageBitmap(bitmap)
                            if (bitmap == null) {
                                previewHint.visibility = View.VISIBLE; previewHint.text = "사진을 읽지 못했어요. 다른 사진을 골라 주세요."
                            }
                        }
                    }
                }
            }
        }
        if (::adapter.isInitialized) adapter.notifyDataSetChanged()
        if (::status.isInitialized && media.isNotEmpty()) status.text = if (selection.isMultiple())
            "누른 순서대로 최대 5장 · 다시 누르면 선택 취소" else "한 장을 골라 주세요. 여러 장은 ‘선택’을 눌러 주세요."
    }

    private fun finishSelection() {
        val chosen = selection.getSelected()
        if (chosen.isEmpty()) return
        val clip = ClipData.newRawUri("선택한 사진", Uri.parse(chosen.first()))
        chosen.drop(1).forEach { clip.addItem(ClipData.Item(Uri.parse(it))) }
        setResult(Activity.RESULT_OK, Intent().apply {
            putStringArrayListExtra(RESULT_URIS, ArrayList(chosen))
            clipData = clip; addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        })
        finish()
    }

    private fun readBitmap(uri: Uri, side: Int): Bitmap? {
        if (Build.VERSION.SDK_INT >= 29) return contentResolver.loadThumbnail(uri, Size(side, side), null)
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / sample > side) sample *= 2
        val bitmap = contentResolver.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample })
        } ?: return null
        val orientation = runCatching {
            contentResolver.openInputStream(uri)?.use {
                android.media.ExifInterface(it).getAttributeInt(android.media.ExifInterface.TAG_ORIENTATION, 1)
            } ?: 1
        }.getOrDefault(1)
        val matrix = Matrix()
        when (orientation) {
            2 -> matrix.setScale(-1f, 1f)
            3 -> matrix.setRotate(180f)
            4 -> matrix.setScale(1f, -1f)
            5 -> { matrix.setRotate(90f); matrix.postScale(-1f, 1f) }
            6 -> matrix.setRotate(90f)
            7 -> { matrix.setRotate(-90f); matrix.postScale(-1f, 1f) }
            8 -> matrix.setRotate(-90f)
        }
        if (matrix.isIdentity) return bitmap
        return Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true).also {
            if (it !== bitmap) bitmap.recycle()
        }
    }

    private inner class Tile : FrameLayout(this@PhotoPickerActivity) {
        val image = ImageView(context).apply { scaleType = ImageView.ScaleType.CENTER_CROP; setBackgroundColor(ui.sage) }
        val shade = View(context).apply { setBackgroundColor(Color.argb(45, 255, 255, 255)) }
        val badge = ui.text("", 14f, true, Color.WHITE).apply { gravity = Gravity.CENTER }
        var uri: String? = null
        var boundEpoch = -1
        var task: Future<*>? = null
        init {
            background = ui.shape(ui.sky); clipToOutline = true
            addView(image, LayoutParams(-1, -1)); addView(shade, LayoutParams(-1, -1))
            addView(badge, LayoutParams(ui.dp(25), ui.dp(25), Gravity.TOP or Gravity.END).apply {
                topMargin = ui.dp(5); marginEnd = ui.dp(5)
            })
            // GridView owns click/focus so TalkBack receives one labelled action per photo.
            image.importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
            badge.importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }
        override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
            super.onMeasure(widthMeasureSpec, View.MeasureSpec.makeMeasureSpec(View.MeasureSpec.getSize(widthMeasureSpec), View.MeasureSpec.EXACTLY))
        }
    }
    private inner class GalleryAdapter : BaseAdapter() {
        override fun getCount() = media.size
        override fun getItem(position: Int): Any = media[position]
        override fun getItemId(position: Int) = position.toLong()
        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            val tile = (convertView as? Tile) ?: Tile()
            val item = media[position]; val number = selection.numberOf(item.uri)
            tile.badge.visibility = if (selection.isMultiple()) View.VISIBLE else View.GONE
            tile.badge.text = if (number > 0) number.toString() else ""
            tile.badge.background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL; setColor(if (number > 0) ui.green else Color.argb(80, 0, 0, 0))
                setStroke(ui.dp(1), Color.WHITE)
            }
            tile.shade.visibility = if (number > 0) View.VISIBLE else View.GONE
            tile.isSelected = number > 0
            tile.contentDescription = item.name + if (number > 0) ", ${number}번째 선택됨. 다시 누르면 취소" else ", 누르면 선택"
            if (tile.uri != item.uri || tile.boundEpoch != epoch) {
                tile.task?.cancel(true); tile.uri = item.uri; tile.boundEpoch = epoch; tile.image.setImageDrawable(null)
                val requestEpoch = epoch
                val cached = cache.get(item.uri)
                if (cached != null) tile.image.setImageBitmap(cached)
                else tile.task = thumbnails.submit {
                    val bitmap = runCatching { readBitmap(Uri.parse(item.uri), 256) }.getOrNull()
                    if (bitmap != null && !Thread.currentThread().isInterrupted) cache.put(item.uri, bitmap)
                    runOnUiThread {
                        if (!isDestroyed && requestEpoch == epoch && tile.uri == item.uri) tile.image.setImageBitmap(bitmap)
                    }
                }
            }
            return tile
        }
    }
    private fun toast(message: String) = Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
}
