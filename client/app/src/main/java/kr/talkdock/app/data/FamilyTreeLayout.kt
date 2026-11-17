package kr.talkdock.app.data

data class TreeAction(val anchor: String, val relation: String, val coParent: String? = null)
data class TreeDisplayNode(val id: String, val label: String, val generation: Int, val gender: String,
                           val occupied: Boolean = false, val action: TreeAction? = null)
data class TreePoint(val x: Float, val y: Float)
data class TreeDrawing(val nodes: List<TreeDisplayNode>, val parents: List<TreeParent>,
                       val pairs: List<TreePair>, val points: Map<String, TreePoint>, val width: Float, val height: Float)

/** Each person occupies a fixed grid slot. Appending relatives never reflows earlier people. */
object FamilyTreeLayout {
    fun actions(draft: FamilyTreeDraft, anchor: String): List<TreeAction> {
        val result = mutableListOf<TreeAction>()
        val parents = draft.parentsOf(anchor).map { draft.people.getValue(it) }
        if (parents.size < 2) {
            if (parents.none { it.gender == "male" }) result.add(TreeAction(anchor, "father"))
            if (parents.none { it.gender == "female" }) result.add(TreeAction(anchor, "mother"))
        }
        if (draft.partnersOf(anchor).isEmpty()) result.add(TreeAction(anchor, "spouse"))
        if (draft.childrenOf(anchor).size < FamilyTreeDraft.MAX_CHILDREN) {
            val coParents = draft.coParentsOf(anchor)
            if (coParents.isEmpty()) result.add(TreeAction(anchor, "child"))
            else coParents.filter { draft.childrenOf(it).size < FamilyTreeDraft.MAX_CHILDREN }
                .forEach { result.add(TreeAction(anchor, "child", it)) }
        }
        return result
    }

    @Suppress("UNUSED_PARAMETER")
    fun drawing(draft: FamilyTreeDraft, showAdditions: Boolean = true): TreeDrawing {
        // Put the room owner first once; all other people retain snapshot/addition order.
        val people = listOf(draft.people.getValue(draft.ownerId)) + draft.people.values.filter { it.id != draft.ownerId }
        val nodes = people.map { TreeDisplayNode(it.id, it.name, it.generation, it.gender, it.occupied) }
        return arrange(nodes, draft.parents.toList(), draft.partnerships.toList())
    }

    fun arrange(nodes: List<TreeDisplayNode>, parents: List<TreeParent>, pairs: List<TreePair>): TreeDrawing {
        if (nodes.isEmpty()) return TreeDrawing(nodes, parents, pairs, emptyMap(), 320f, 400f)
        val raw = linkedMapOf<String, TreePoint>()
        val occupied = mutableMapOf<Int, MutableSet<Int>>()
        nodes.forEach { node ->
            val partners = pairs.mapNotNull { pair ->
                when (node.id) { pair.first -> raw[pair.second]; pair.second -> raw[pair.first]; else -> null }
            }
            val parentPoints = parents.filter { it.child == node.id }.mapNotNull { raw[it.parent] }
            val childPoints = parents.filter { it.parent == node.id }.mapNotNull { raw[it.child] }
            val relatives = parentPoints.ifEmpty { childPoints }
            val desired = when {
                partners.isNotEmpty() -> partners.first().x + 1f
                relatives.isNotEmpty() -> relatives.map { it.x }.average().toFloat()
                else -> 0f
            }.let { kotlin.math.floor(it).toInt() }
            val row = occupied.getOrPut(node.generation) { mutableSetOf() }
            var column = desired
            var distance = 0
            while (column in row) {
                distance++
                column = desired + (if (distance % 2 == 1) (distance + 1) / 2 else -distance / 2)
            }
            row.add(column)
            raw[node.id] = TreePoint(column.toFloat(), -node.generation.toFloat())
        }
        val minX = raw.values.minOf { it.x }
        val minY = raw.values.minOf { it.y }
        val points = raw.mapValues { (_, point) -> TreePoint((point.x - minX) * 144f + 72f, (point.y - minY) * 205f + 76f) }
        return TreeDrawing(nodes, parents, pairs, points,
            maxOf(320f, points.values.maxOf { it.x } + 72f), maxOf(300f, points.values.maxOf { it.y } + 90f))
    }
}
