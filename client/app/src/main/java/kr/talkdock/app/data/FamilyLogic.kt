package kr.talkdock.app.data

object FamilyLogic {
    fun shortName(name: String): String = if (name.matches(Regex("[가-힣]{3}"))) name.drop(1) else name
    fun introduction(owner: String, members: List<String>): String {
        val name = shortName(owner)
        if (members.isEmpty()) return name + "님과 가족 방을\n시작해보세요!"
        if (members.size > 1) return members.first() + " 외 " + (members.size - 1) + "명이\n" + name + "님과 함께하고 있어요!"
        val last = members.first().last().code
        val particle = if (last in 0xAC00..0xD7A3 && (last - 0xAC00) % 28 != 0) "이" else "가"
        return members.first() + particle + " " + name + "님과\n함께하고 있어요!"
    }
}
