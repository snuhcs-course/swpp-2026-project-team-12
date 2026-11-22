package kr.talkdock.app.data

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ReplyPromptTest {
    private fun post(relationship: String, author: Int = 1, name: String = "준하") =
        JSONObject().put("author_id", author).put("author_name", name).put("relationship", relationship)

    @Test fun usesTheViewersRelationshipToTheAuthor() {
        assertEquals("손자의 소식에 답장해 보시는 건 어떨까요?", ReplyPrompt.forPost(post("손자"), 7))
        assertEquals("아내의 외할머니의 소식에 답장해 보시는 건 어떨까요?", ReplyPrompt.forPost(post("아내의 외할머니"), 7))
    }

    @Test fun genericRelationshipsFallBackToTheAuthorsName() {
        assertEquals("준하님의 소식에 답장해 보시는 건 어떨까요?", ReplyPrompt.forPost(post("가족"), 7))
        assertEquals("준하님의 소식에 답장해 보시는 건 어떨까요?", ReplyPrompt.forPost(post(""), 7))
        assertNull(ReplyPrompt.forPost(post("인척", name = ""), 7))
    }

    @Test fun ownPostsAndDailyQuestionsAreNotPrompted() {
        assertNull(ReplyPrompt.forPost(post("나", author = 7), 7))
        assertNull(ReplyPrompt.forPost(post("손자", author = 7), 7))
        assertNull(ReplyPrompt.forPost(post("오늘의 질문"), 7))
    }

    @Test fun closingIsAppendedAsItsOwnSentence() {
        val closing = "손자의 소식에 답장해 보시는 건 어떨까요?"
        assertEquals("산책했대요. $closing", ReplyPrompt.spoken("산책했대요.", closing))
        assertEquals("산책했대요 $closing", ReplyPrompt.spoken("산책했대요 ", closing))
        assertEquals("공원 산책. $closing", ReplyPrompt.spoken("공원 산책", closing))
        assertEquals("산책했대요.", ReplyPrompt.spoken("산책했대요.", null))
    }
}
