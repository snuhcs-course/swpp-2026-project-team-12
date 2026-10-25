package kr.talkdock.app.data

/** Shared notices for API failures when the server cannot provide a useful error. */
object ApiFailureMessages {
    const val UNAVAILABLE = "서버를 점검 중이거나 일시적인 문제가 생겼어요.\n잠시 후 다시 이용해 주세요."
    const val CONNECTION = "서버에 연결하지 못했어요.\n인터넷 연결을 확인해 주세요. 서버 점검 중일 수 있으니 잠시 후 다시 시도해 주세요."
    const val TIMEOUT = "서버 응답이 늦어지고 있어요.\n잠시 후 다시 시도해 주세요."

    fun http(status: Int): String = when (status) {
        in 500..599 -> UNAVAILABLE
        401 -> "로그인이 만료되었어요. 다시 로그인해 주세요."
        else -> "가족 방에 연결하지 못했어요. 다시 시도해 주세요."
    }
}
