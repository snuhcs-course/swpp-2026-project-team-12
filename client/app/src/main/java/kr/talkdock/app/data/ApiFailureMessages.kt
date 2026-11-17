package kr.talkdock.app.data

/** Shared notices for API failures when the server cannot provide a useful error. */
object ApiFailureMessages {
    const val UNAVAILABLE = "서버를 점검 중이거나 일시적인 문제가 생겼어요.\n잠시 후 다시 이용해 주세요."
    const val CONNECTION = "서버에 연결하지 못했어요.\n인터넷 연결을 확인해 주세요. 서버 점검 중일 수 있으니 잠시 후 다시 시도해 주세요."
    const val TIMEOUT = "서버 응답이 늦어지고 있어요.\n잠시 후 다시 시도해 주세요."

    fun actionTitle(screen: String, status: Int, connection: Boolean = false, timedOut: Boolean = false): String = when {
        status == 401 -> "다시 로그인해 주세요"
        timedOut || status in 500..599 || status == 408 -> "잠시 후 다시 시도해 주세요"
        connection -> "인터넷 연결을 확인해 주세요"
        screen == "voice" -> "다시 말해 주세요"
        screen == "post" -> "소식 내용을 확인해 주세요"
        screen in setOf("tree", "profile") -> "내 자리를 다시 선택해 주세요"
        screen == "login" -> "아이디와 비밀번호를 확인해 주세요"
        screen == "register" || screen == "editAccount" -> "계정 정보를 확인해 주세요"
        screen == "join" -> "초대 코드와 비밀번호를 확인해 주세요"
        screen == "create" -> "가족방 정보를 확인해 주세요"
        else -> "입력한 내용을 확인해 주세요"
    }

    fun http(status: Int): String = when (status) {
        in 500..599 -> UNAVAILABLE
        401 -> "로그인이 만료되었어요. 다시 로그인해 주세요."
        else -> "가족 방에 연결하지 못했어요. 다시 시도해 주세요."
    }
}
