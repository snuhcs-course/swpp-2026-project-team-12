package kr.talkdock.app.data

import org.json.JSONException
import java.io.FileNotFoundException
import java.io.IOException
import java.io.InterruptedIOException
import java.net.SocketTimeoutException

/** Shared notices for API failures when the server cannot provide a useful error. */
object ApiFailureMessages {
    const val UNAVAILABLE = "서버를 점검 중이거나 일시적인 문제가 생겼어요.\n잠시 후 다시 이용해 주세요."
    const val CONNECTION = "서버에 연결하지 못했어요.\n인터넷 연결을 확인해 주세요. 서버 점검 중일 수 있으니 잠시 후 다시 시도해 주세요."
    const val TIMEOUT = "서버 응답이 늦어지고 있어요.\n잠시 후 다시 시도해 주세요."
    const val UNREADABLE = "서버 응답을 읽지 못했어요. 잠시 후 다시 시도해 주세요."
    // Android 12+ shows at most two lines of a text toast, so toasts lead with the next step and stay short.
    const val DIGEST_DATES_TOAST = "날짜 목록을 불러오지 못했어요.\n잠시 후 달력을 다시 열어 주세요."
    /** Lead line for a failure on the phone itself (not the server), followed by the task's next step. */
    const val UNEXPECTED = "일시적인 문제가 생겼어요."

    /** Why a request failed, when the server gave no message of its own. */
    enum class Cause(val line: String) {
        CONNECTION("인터넷 연결을 확인해 주세요."),
        TIMEOUT("서버 응답이 늦어지고 있어요."),
        SERVER("서버에 잠시 문제가 생겼어요."),
    }

    /**
     * What failed ([title]) and what the user still has and can do next ([next]).
     * Every [next] names a concrete recovery step, so a failure never leaves the user guessing.
     */
    enum class Task(val title: String, val next: String) {
        LOGIN("로그인하지 못했어요", "입력한 아이디와 비밀번호는 그대로 있어요. 잠시 후 '로그인'을 다시 눌러 주세요."),
        REGISTER("계정을 만들지 못했어요", "입력한 정보는 그대로 있어요. 잠시 후 '계정 만들기'를 다시 눌러 주세요."),
        EDIT_ACCOUNT("계정 정보를 저장하지 못했어요", "바꾼 내용은 그대로 있어요. 잠시 후 '수정 내용 저장하기'를 다시 눌러 주세요."),
        LOGOUT("로그아웃하지 못했어요", "잠시 후 '로그아웃'을 다시 눌러 주세요."),
        ROOM_SYNC("가족방을 확인하지 못했어요", "잠시 후 아래 '다시 연결하기'를 눌러 주세요."),
        ROOM_LIST("가족방 목록을 불러오지 못했어요", "잠시 후 아래 '가족방 다시 불러오기'를 눌러 주세요."),
        ROOM_OPEN("가족방을 열지 못했어요", "잠시 후 가족방 목록에서 다시 골라 주세요."),
        CREATE_ROOM("가족방을 만들지 못했어요", "입력한 내용은 그대로 있어요. 잠시 후 '가족 방 만들기'를 다시 눌러 주세요."),
        LOOKUP_ROOM("초대 코드를 확인하지 못했어요", "입력한 초대 코드와 비밀번호는 그대로 있어요. 잠시 후 '가족 방 확인하기'를 다시 눌러 주세요."),
        JOIN_ROOM("가족방에 들어가지 못했어요", "고른 자리는 그대로 있어요. 잠시 후 '가족 방에 들어가기'를 다시 눌러 주세요."),
        MEMBERS("가족 정보를 불러오지 못했어요", "잠시 후 설정을 다시 열어 주세요."),
        DIGEST_TIME("하루 요약 시간을 바꾸지 못했어요", "시간은 이전 그대로예요. 잠시 후 다시 바꿔 주세요."),
        FEED("소식을 불러오지 못했어요", "잠시 후 아래 '다시 불러오기'를 눌러 주세요."),
        FEED_REFRESH("새 소식을 불러오지 못했어요", "지금 보이는 소식은 그대로 있어요. 잠시 후 아래로 당겨 다시 불러와 주세요."),
        DETAIL("소식을 열지 못했어요", "잠시 후 소식을 다시 눌러 주세요."),
        NOTIFICATION("알림의 소식을 열지 못했어요", "보던 화면은 그대로 있어요. 잠시 후 '다시 열기'를 눌러 주세요."),
        POST("소식을 올리지 못했어요", "쓴 내용과 사진은 그대로 있어요. 잠시 후 '다시 시도'를 눌러 주세요."),
        POST_VOICE("말씀을 글로 바꾸지 못했어요", "잠시 후 '말로 쓰기'를 눌러 다시 말씀해 주세요."),
        VOICE_REPLY("말씀을 글로 바꾸지 못했어요", "녹음은 그대로 있어요. 잠시 후 '다시 시도'를 눌러 주세요."),
        REPLY_PREPARE("댓글을 정리하지 못했어요", "하신 말씀은 그대로 있어요. 잠시 후 '보낼 내용 확인하기'를 다시 눌러 주세요."),
        ELDER_REPLY("답장을 준비하지 못했어요", "잠시 후 '말로 답하기'를 눌러 다시 말씀해 주세요."),
        COMMENT("댓글을 보내지 못했어요", "작성한 댓글은 그대로 있어요. 잠시 후 다시 보내 주세요."),
        SUMMARY("설명을 준비하지 못했어요", "잠시 후 '설명 다시 준비하기'를 눌러 주세요."),
        SPEECH("소리를 준비하지 못했어요", "잠시 후 '음성 다시 준비하기'를 눌러 주세요."),
        DIGEST_DATES("날짜 목록을 불러오지 못했어요", "잠시 후 달력을 다시 열어 주세요."),
        DIGEST("하루 소식을 불러오지 못했어요", "잠시 후 '하루' 화면을 다시 열어 주세요."),
        STORY("하루 이야기를 불러오지 못했어요", "잠시 후 이 날짜를 다시 골라 주세요."),
        MEMORY("추억을 찾지 못했어요", "질문은 그대로 있어요. 잠시 후 '추억 찾기'를 다시 눌러 주세요."),
        POST_QUESTION("답변을 찾지 못했어요", "질문은 그대로 있어요. 잠시 후 다시 물어봐 주세요."),
        DAILY_QUESTION("오늘의 질문을 불러오지 못했어요", "잠시 후 아래 '다시 불러오기'를 눌러 주세요."),
        DAILY_ANSWER("답변을 보내지 못했어요", "작성한 답변은 그대로 있어요. 잠시 후 다시 보내 주세요."),
        DAILY_COMMENT("댓글을 보내지 못했어요", "작성한 댓글은 그대로 있어요. 잠시 후 다시 보내 주세요."),
        DAILY_HISTORY("지난 질문을 불러오지 못했어요", "잠시 후 '다시 불러오기'로 질문을 연 뒤 '지난 질문'을 다시 눌러 주세요."),
        PHOTO_PICK("사진을 가져오지 못했어요", "잠시 후 사진을 다시 골라 주세요."),
        OTHER("요청을 처리하지 못했어요", "잠시 후 다시 시도해 주세요."),
    }

    /** A feature-specific failure: [title] says what failed, [body] the cause and the next step. */
    data class Failure(val task: Task, val cause: Cause) {
        val title get() = task.title
        val body get() = cause.line + "\n" + task.next
        /** Single-block form for inline notes and toasts. */
        val text get() = title + "\n" + body
    }

    /**
     * The cause of a connection, timeout or generic server failure, or null when the server explained
     * the problem itself (validation, login, AI availability, maintenance): those keep their own wording.
     */
    fun cause(error: Throwable?): Cause? {
        if (error is ApiException) {
            if (error.isMaintenance || error.status == 401) return null
            val root = error.cause
            return when {
                root is SocketTimeoutException || error.status == 408 -> Cause.TIMEOUT
                root is IOException && root !is InterruptedIOException && root !is FileNotFoundException -> Cause.CONNECTION
                error.status in 500..599 && error.message in setOf(UNAVAILABLE, http(error.status)) -> Cause.SERVER
                error.message == UNREADABLE -> Cause.SERVER
                else -> null
            }
        }
        return when (error) {
            is SocketTimeoutException -> Cause.TIMEOUT
            is InterruptedIOException, is FileNotFoundException -> null
            is IOException -> Cause.CONNECTION
            is JSONException -> Cause.SERVER
            else -> null
        }
    }

    fun failure(task: Task, error: Throwable?): Failure? = cause(error)?.let { Failure(task, it) }

    /** Which task a generic request on [screen] belongs to, for screens with one main action. */
    fun taskFor(screen: String): Task = when (screen) {
        "login" -> Task.LOGIN
        "register" -> Task.REGISTER
        "editAccount" -> Task.EDIT_ACCOUNT
        "roomSync" -> Task.ROOM_SYNC
        "roomChoice" -> Task.ROOM_LIST
        "accounts" -> Task.ROOM_OPEN
        "create" -> Task.CREATE_ROOM
        "join" -> Task.LOOKUP_ROOM
        "profile" -> Task.JOIN_ROOM
        "members" -> Task.MEMBERS
        "home" -> Task.FEED
        "detail" -> Task.DETAIL
        "voice" -> Task.VOICE_REPLY
        "review" -> Task.REPLY_PREPARE
        "digest" -> Task.DIGEST
        "story" -> Task.STORY
        "post" -> Task.POST
        else -> Task.OTHER
    }

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
