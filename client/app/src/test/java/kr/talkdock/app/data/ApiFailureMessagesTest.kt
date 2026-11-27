package kr.talkdock.app.data

import kr.talkdock.app.data.ApiFailureMessages.Cause
import kr.talkdock.app.data.ApiFailureMessages.Task
import org.json.JSONException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.FileNotFoundException
import java.io.IOException
import java.io.InterruptedIOException
import java.net.ConnectException
import java.net.SocketTimeoutException

class ApiFailureMessagesTest {
    @Test fun recoveryActionsMatchTheFailureAndCurrentTask() {
        assertEquals("다시 말해 주세요", ApiFailureMessages.actionTitle("voice", 400))
        assertEquals("잠시 후 다시 시도해 주세요", ApiFailureMessages.actionTitle("voice", 503))
        assertEquals("인터넷 연결을 확인해 주세요", ApiFailureMessages.actionTitle("voice", 0, connection = true))
        assertEquals("잠시 후 다시 시도해 주세요", ApiFailureMessages.actionTitle("voice", 0, connection = true, timedOut = true))
        assertEquals("다시 로그인해 주세요", ApiFailureMessages.actionTitle("post", 401))
        assertEquals("소식 내용을 확인해 주세요", ApiFailureMessages.actionTitle("post", 400))
        assertEquals("내 자리를 다시 선택해 주세요", ApiFailureMessages.actionTitle("tree", 400))
        assertEquals("아이디와 비밀번호를 확인해 주세요", ApiFailureMessages.actionTitle("login", 400))
    }

    @Test fun connectionTimeoutAndGenericServerFailuresAreClassified() {
        assertEquals(Cause.CONNECTION, ApiFailureMessages.cause(ApiException(ApiFailureMessages.CONNECTION, cause = ConnectException())))
        assertEquals(Cause.TIMEOUT, ApiFailureMessages.cause(ApiException(ApiFailureMessages.TIMEOUT, cause = SocketTimeoutException())))
        assertEquals(Cause.TIMEOUT, ApiFailureMessages.cause(ApiException("느려요", 408)))
        assertEquals(Cause.SERVER, ApiFailureMessages.cause(ApiException(ApiFailureMessages.UNAVAILABLE, 502)))
        assertEquals(Cause.SERVER, ApiFailureMessages.cause(ApiException(ApiFailureMessages.UNREADABLE, 200)))
        assertEquals(Cause.CONNECTION, ApiFailureMessages.cause(IOException("reset")))
        assertEquals(Cause.TIMEOUT, ApiFailureMessages.cause(SocketTimeoutException()))
        assertEquals(Cause.SERVER, ApiFailureMessages.cause(JSONException("bad")))
    }

    @Test fun serverExplanationsLoginAndMaintenanceKeepTheirOwnWording() {
        assertNull(ApiFailureMessages.cause(ApiException("답변 저장 실패 · 다시 시도해 주세요.", 503)))
        assertNull(ApiFailureMessages.cause(ApiException("이야기를 조금 줄여 주세요.", 400)))
        assertNull(ApiFailureMessages.cause(ApiException(ApiFailureMessages.http(401), 401)))
        assertNull(ApiFailureMessages.cause(ApiException(ApiFailureMessages.UNAVAILABLE, 503, isMaintenance = true)))
        assertNull(ApiFailureMessages.cause(InterruptedIOException()))
        assertNull(ApiFailureMessages.cause(FileNotFoundException()))
        assertNull(ApiFailureMessages.cause(IllegalStateException()))
    }

    @Test fun featureFailuresNameWhatFailedTheCauseAndTheNextStep() {
        val failure = ApiFailureMessages.failure(Task.POST, ApiException(ApiFailureMessages.CONNECTION, cause = ConnectException()))!!
        assertEquals("소식을 올리지 못했어요", failure.title)
        assertEquals("인터넷 연결을 확인해 주세요.\n쓴 내용과 사진은 그대로 있어요. 잠시 후 '다시 시도'를 눌러 주세요.", failure.body)
        assertEquals("소식을 올리지 못했어요\n" + failure.body, failure.text)
        assertEquals("로그인하지 못했어요", ApiFailureMessages.failure(Task.LOGIN, SocketTimeoutException())!!.title)
    }

    @Test fun everyTaskTellsTheUserWhatToDoNext() {
        Task.values().forEach { task ->
            assertTrue("${task.name} must end with a concrete step", task.next.endsWith("주세요."))
            assertTrue(task.title.endsWith("못했어요"))
        }
    }

    @Test fun screensMapToTheirMainTask() {
        assertEquals(Task.LOGIN, ApiFailureMessages.taskFor("login"))
        assertEquals(Task.LOOKUP_ROOM, ApiFailureMessages.taskFor("join"))
        assertEquals(Task.JOIN_ROOM, ApiFailureMessages.taskFor("profile"))
        assertEquals(Task.FEED, ApiFailureMessages.taskFor("home"))
        assertEquals(Task.OTHER, ApiFailureMessages.taskFor("unknown"))
    }
}
