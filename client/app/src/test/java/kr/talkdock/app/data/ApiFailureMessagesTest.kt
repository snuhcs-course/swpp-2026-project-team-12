package kr.talkdock.app.data

import org.junit.Assert.assertEquals
import org.junit.Test

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
}
