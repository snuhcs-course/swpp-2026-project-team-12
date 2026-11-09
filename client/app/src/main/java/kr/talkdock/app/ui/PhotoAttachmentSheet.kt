package kr.talkdock.app.ui

import android.Manifest
import android.app.Dialog
import android.content.ContentUris
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.CancellationSignal
import android.provider.MediaStore
import android.util.Size
import android.view.Gravity
import android.view.View
import android.view.Window
import android.view.WindowManager
import android.widget.*
import java.util.concurrent.Executors

/** Local, bounded recent-photo chooser. The full gallery keeps its existing permission and selection flow. */
class PhotoAttachmentSheet(
    private val ui: Ui,
    private val large: Boolean,
    private val replacing: Boolean,
    private val takePhoto: () -> Unit,
    private val openGallery: () -> Unit,
    private val choosePhotos: (List<Uri>) -> Unit,
) : Dialog(ui.context) {
    private val loader = Executors.newFixedThreadPool(2)
    private val signals = mutableListOf<CancellationSignal>()
    private val selected = linkedSetOf<Uri>()
    private val tiles = mutableListOf<PhotoTile>()
    private lateinit var photos: LinearLayout
    private lateinit var status: TextView
    private lateinit var done: Button
    private var closed = false

    override fun onCreate(state: android.os.Bundle?) {
        super.onCreate(state)
        requestWindowFeature(Window.FEATURE_NO_TITLE)
        val body = ui.column(20).apply { background = ui.shape(ui.paper, 24) }
        val handle = View(context).apply { background = ui.shape(ui.border, 4); importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO }
        body.addView(handle, LinearLayout.LayoutParams(ui.dp(40), ui.dp(4)).apply { gravity = Gravity.CENTER_HORIZONTAL; bottomMargin = ui.dp(18) })
        val header = ui.row()
        header.addView(ui.text("최근 사진", if (large) 25f else 21f, true), LinearLayout.LayoutParams(0, -2, 1f))
        done = Button(context).apply {
            textSize = if (large) 18f else 16f; typeface = ui.font; isAllCaps = false
            elevation = 0f; stateListAnimator = null
            background = ui.shape(ui.coral); setTextColor(ui.ink); minWidth = 0; minimumWidth = 0
            setPadding(ui.dp(12), 0, ui.dp(12), 0)
            setOnClickListener { val chosen = selected.toList(); dismiss(); choosePhotos(chosen) }
        }
        header.addView(done, LinearLayout.LayoutParams(-2, ui.dp(if (large) 56 else 48)))
        body.addView(header); ui.gap(body, 16)
        photos = ui.row().apply { gravity = Gravity.TOP }
        val side = maxOf(if (large) 104 else 72, (context.resources.configuration.screenWidthDp - 64) / 4)
        val camera = ui.column().apply {
            gravity = Gravity.CENTER; background = ui.shape(ui.blush, 16)
            isClickable = true; isFocusable = true; contentDescription = "사진 촬영하기"
            setOnClickListener { dismiss(); takePhoto() }
        }
        camera.addView(IconView(context, "camera", ui.coralDeep), LinearLayout.LayoutParams(ui.dp(48), ui.dp(48)))
        ui.gap(camera, 8)
        ui.label(camera, "촬영", if (large) 18f else 15f, true, ui.coralDeep).gravity = Gravity.CENTER
        camera.importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_YES
        camera.descendantFocusability = android.view.ViewGroup.FOCUS_BLOCK_DESCENDANTS
        photos.addView(camera, LinearLayout.LayoutParams(ui.dp(side), ui.dp(side)).apply { marginEnd = ui.dp(8) })
        val strip = HorizontalScrollView(context).apply { isHorizontalScrollBarEnabled = false; addView(photos) }
        body.addView(strip, LinearLayout.LayoutParams(-1, -2))
        status = ui.label(body, "최근 사진을 불러오고 있어요.", if (large) 17f else 14f, color = ui.muted).apply {
            setPadding(0, ui.dp(12), 0, ui.dp(12)); accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        ui.line(body)
        ui.button(body, "갤러리에서 더 보기", false, if (large) 64 else 56) { dismiss(); openGallery() }
        ui.ghost(body, "닫기", if (large) 56 else 48) { dismiss() }
        val scroll = ScrollView(context).apply { isFillViewport = false; addView(body) }
        setContentView(scroll)
        window?.apply {
            setBackgroundDrawableResource(android.R.color.transparent)
            addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
            setDimAmount(.35f)
            setGravity(Gravity.BOTTOM)
            setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING)
        }
        updateSelection()
        loadRecent(side)
    }

    override fun onStart() {
        super.onStart()
        window?.setLayout(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.WRAP_CONTENT)
    }

    private fun hasPhotoAccess(): Boolean {
        fun granted(permission: String) = context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
        return if (Build.VERSION.SDK_INT >= 33) granted(Manifest.permission.READ_MEDIA_IMAGES) ||
            (Build.VERSION.SDK_INT >= 34 && granted(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED))
        else granted(Manifest.permission.READ_EXTERNAL_STORAGE)
    }

    private fun loadRecent(side: Int) {
        if (!hasPhotoAccess()) {
            status.text = "갤러리에서 사진 접근을 허용하면 최근 사진이 보여요."
            return
        }
        val cancellation = CancellationSignal().also { signals.add(it) }
        loader.execute {
            val result = runCatching {
                val collection = if (Build.VERSION.SDK_INT >= 29) MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL)
                    else MediaStore.Images.Media.EXTERNAL_CONTENT_URI
                val recent = mutableListOf<Pair<Uri, String>>()
                context.contentResolver.query(collection, arrayOf(MediaStore.Images.Media._ID, MediaStore.Images.Media.DISPLAY_NAME),
                    null, null, "${MediaStore.Images.Media.DATE_ADDED} DESC, ${MediaStore.Images.Media._ID} DESC", cancellation)?.use { cursor ->
                    while (recent.size < 3 && cursor.moveToNext()) {
                        recent.add(ContentUris.withAppendedId(collection, cursor.getLong(0)) to (cursor.getString(1) ?: "사진"))
                    }
                } ?: error("Photo query failed")
                recent
            }
            photos.post {
                if (closed) return@post
                result.fold({ recent ->
                    recent.forEach { (uri, name) ->
                        val tile = PhotoTile(uri, name)
                        tiles.add(tile)
                        photos.addView(tile, LinearLayout.LayoutParams(ui.dp(side), ui.dp(side)).apply { marginEnd = ui.dp(8) })
                        loadThumbnail(tile)
                    }
                    status.text = if (recent.isEmpty()) "최근 사진이 없어요. 사진을 촬영하거나 갤러리에서 골라 주세요."
                        else if (replacing) "선택한 사진으로 첨부 사진을 바꿔요."
                        else "사진을 고른 뒤 ‘사진 추가’를 눌러 주세요."
                }, { status.text = "최근 사진을 불러오지 못했어요. 갤러리에서 골라 주세요." })
            }
        }
    }

    private fun loadThumbnail(tile: PhotoTile) {
        val cancellation = CancellationSignal().also { signals.add(it) }
        loader.execute {
            val bitmap = runCatching {
                if (Build.VERSION.SDK_INT >= 29) context.contentResolver.loadThumbnail(tile.uri, Size(256, 256), cancellation)
                else {
                    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                    context.contentResolver.openInputStream(tile.uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
                    require(bounds.outWidth > 0 && bounds.outHeight > 0)
                    var sample = 1
                    while (maxOf(bounds.outWidth, bounds.outHeight) / sample > 256) sample *= 2
                    val source = context.contentResolver.openInputStream(tile.uri)?.use {
                        BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample })
                    } ?: error("Unreadable photo")
                    val orientation = context.contentResolver.openInputStream(tile.uri)?.use {
                        android.media.ExifInterface(it).getAttributeInt(android.media.ExifInterface.TAG_ORIENTATION, 1)
                    } ?: 1
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
                    if (matrix.isIdentity) source else Bitmap.createBitmap(source, 0, 0, source.width, source.height, matrix, true).also { source.recycle() }
                }
            }.getOrNull()
            tile.post {
                if (closed) { bitmap?.recycle(); return@post }
                tile.image.setImageBitmap(bitmap)
                if (bitmap == null) {
                    tile.isEnabled = false
                    tile.contentDescription = "${tile.name}, 읽을 수 없는 사진. 갤러리에서 다시 골라 주세요."
                }
            }
        }
    }

    private fun updateSelection() {
        done.text = (if (replacing) "사진 바꾸기" else "사진 추가") + if (selected.isEmpty()) "" else " (${selected.size})"
        done.isEnabled = selected.isNotEmpty(); done.alpha = if (done.isEnabled) 1f else .4f
        tiles.forEach { tile ->
            val number = selected.indexOf(tile.uri) + 1
            tile.badge.text = if (number > 0) number.toString() else ""
            tile.badge.background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL; setColor(if (number > 0) ui.coralDeep else Color.argb(70, 0, 0, 0))
                setStroke(ui.dp(2), Color.WHITE)
            }
            tile.isSelected = number > 0
            tile.contentDescription = "${tile.name}, " + if (number > 0) "${number}번째 선택됨. 다시 누르면 취소" else "누르면 선택"
        }
    }

    private inner class PhotoTile(val uri: Uri, val name: String) : FrameLayout(this@PhotoAttachmentSheet.context) {
        val image = ImageView(context).apply { scaleType = ImageView.ScaleType.CENTER_CROP; setBackgroundColor(ui.sky) }
        val badge = ui.text("", if (large) 16f else 14f, true, Color.WHITE).apply { gravity = Gravity.CENTER }
        init {
            background = ui.shape(ui.sky, 16); clipToOutline = true; isClickable = true; isFocusable = true
            addView(image, LayoutParams(-1, -1))
            addView(badge, LayoutParams(ui.dp(26), ui.dp(26), Gravity.TOP or Gravity.END).apply { topMargin = ui.dp(5); marginEnd = ui.dp(5) })
            image.importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
            badge.importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
            setOnClickListener { if (!selected.remove(uri)) selected.add(uri); updateSelection() }
            post { updateSelection() }
        }
    }

    override fun dismiss() {
        closed = true
        signals.forEach { it.cancel() }; loader.shutdownNow()
        super.dismiss()
    }
}
