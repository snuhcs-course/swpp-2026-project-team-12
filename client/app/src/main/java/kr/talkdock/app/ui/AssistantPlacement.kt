package kr.talkdock.app.ui

enum class AssistantEdge { LEFT, RIGHT }

data class AssistantBounds(val left: Float, val top: Float, val right: Float, val bottom: Float)
data class AssistantAnchor(val edge: AssistantEdge = AssistantEdge.RIGHT, val fraction: Float = .62f)
data class AssistantPoint(val x: Float, val y: Float)
data class AssistantPostRange(val id: Int, val top: Float, val bottom: Float)

/** Geometry uses the visible feed area, excluding navigation bars and the keyboard. */
object AssistantPlacement {
    fun position(anchor: AssistantAnchor, bounds: AssistantBounds, width: Float, height: Float): AssistantPoint {
        val lastX = maxOf(bounds.left, bounds.right - width)
        val travel = maxOf(0f, bounds.bottom - bounds.top - height)
        return AssistantPoint(if (anchor.edge == AssistantEdge.LEFT) bounds.left else lastX,
            bounds.top + travel * anchor.fraction.coerceIn(0f, 1f))
    }

    fun dropped(x: Float, y: Float, bounds: AssistantBounds, width: Float, height: Float): AssistantAnchor {
        val edge = if (x + width / 2 < (bounds.left + bounds.right) / 2) AssistantEdge.LEFT else AssistantEdge.RIGHT
        val travel = maxOf(0f, bounds.bottom - bounds.top - height)
        return AssistantAnchor(edge, if (travel == 0f) .5f else ((y - bounds.top) / travel).coerceIn(0f, 1f))
    }

    /** The viewport center chooses the post, independently of the character's position. */
    fun currentPost(ranges: List<AssistantPostRange>, viewport: AssistantBounds): Int? {
        val center = (viewport.top + viewport.bottom) / 2
        return ranges.filter { it.bottom > viewport.top && it.top < viewport.bottom && it.bottom > it.top }
            .minByOrNull {
                when {
                    center < it.top -> it.top - center
                    center > it.bottom -> center - it.bottom
                    else -> 0f
                }
            }?.id
    }
}
