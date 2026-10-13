package kr.talkdock.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kr.talkdock.app.data.ApiClient
import kr.talkdock.app.data.ApiException
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.UUID

/** Requires the local Django server. Exercises Android's actual HTTP transport. */
@RunWith(AndroidJUnit4::class)
class ApiRoundTripTest {
    private fun json(vararg values: Pair<String, Any>) = JSONObject().apply { values.forEach { put(it.first, it.second) } }

    @Test fun inviteUploadAndPublicCommentRoundTrip() {
        val anonymous = ApiClient()
        val suffix = UUID.randomUUID().toString().replace("-", "").take(12)
        val ownerName = "android_owner_$suffix"
        val grandmaName = "android_grandma_$suffix"
        val accountPassword = "R9!qT4#vN8@pL2"
        val owner = anonymous.request("accounts/register/", "POST", json(
            "username" to ownerName, "password" to accountPassword, "name" to "준하", "gender" to "male"))
        assertEquals(ownerName, owner.getString("username"))
        val loggedIn = anonymous.request("accounts/login/", "POST", json(
            "username" to ownerName, "password" to accountPassword))
        val member = ApiClient(loggedIn.getString("token"))
        assertEquals("준하", member.request("accounts/me/").getString("name"))
        val created = member.request("families/create/", "POST", json(
            "room_name" to "자동 연결 검사 $suffix", "password" to "test-room-password"))
        val invitation = json("invite_code" to created.getJSONObject("room").getString("invite_code"), "password" to "test-room-password")
        val found = anonymous.request("families/lookup/", "POST", invitation)
        assertEquals("준하", found.getString("owner_name"))
        val grandma = anonymous.request("accounts/register/", "POST", json(
            "username" to grandmaName, "password" to accountPassword, "name" to "경자", "gender" to "female"))
        val elder = ApiClient(grandma.getString("token"))
        elder.request("families/join/", "POST", JSONObject(invitation.toString()).put("slot", "grandma-father"))
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val photo = File.createTempFile("contract-", ".png", context.cacheDir)
        try {
            context.resources.openRawResource(R.drawable.family).use { source ->
                photo.outputStream().use { source.copyTo(it) }
            }
            val uploaded = member.upload(photo, "학교에서 점심 먹었어요")
            val id = uploaded.getInt("id")
            val feed = elder.request("posts/").getJSONArray("posts").getJSONObject(0)
            assertEquals(id, feed.getInt("id"))
            assertEquals("학교에서 점심 먹었어요", feed.getString("caption"))
            assertEquals("손자", feed.getString("relationship"))
            val image = elder.image(feed.getString("image_url"))
            assertTrue(image.size > 100)
            assertEquals(0xff.toByte(), image[0]); assertEquals(0xd8.toByte(), image[1])
            elder.request("posts/" + id + "/comments/", "POST", json("text" to "맛있게 먹었니?"))
            val detail = member.request("posts/" + id + "/")
            assertEquals(1, detail.getInt("comment_count"))
            assertEquals("맛있게 먹었니?", detail.getJSONArray("comments").getJSONObject(0).getString("text"))
            try {
                anonymous.image(feed.getString("image_url"))
                fail("Images must require the room session.")
            } catch (_: ApiException) { /* Expected: an anonymous user cannot fetch family media. */ }
        } finally { photo.delete() }
    }
}
