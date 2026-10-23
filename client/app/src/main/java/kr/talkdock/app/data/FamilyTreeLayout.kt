package kr.talkdock.app.data

data class TreeAction(val anchor: String, val relation: String, val coParent: String? = null)
data class TreeDisplayNode(val id: String, val label: String, val generation: Int, val gender: String,
                           val occupied: Boolean = false, val action: TreeAction? = null)
data class TreePoint(val x: Float, val y: Float)
data class TreeDrawing(val nodes: List<TreeDisplayNode>, val parents: List<TreeParent>,
                       val pairs: List<TreePair>, val points: Map<String, TreePoint>, val width: Float, val height: Float)

/** Layered layout includes the one-step + frontier, so actions never overlap people. */
object FamilyTreeLayout {
    fun drawing(draft: FamilyTreeDraft, showAdditions: Boolean = true): TreeDrawing {
        val nodes = draft.people.values.map { TreeDisplayNode(it.id, it.name, it.generation, it.gender, it.occupied) }.toMutableList()
        val parents = draft.parents.toMutableList()
        val pairs = draft.partnerships.toMutableList()
        if (!showAdditions) return arrange(nodes, parents, pairs)
        fun marker(id: String, generation: Int, gender: String, action: TreeAction): String {
            nodes.add(TreeDisplayNode(id, "+", generation, gender, action = action)); return id
        }
        val childGroups = mutableSetOf<String>()
        draft.people.values.forEach { p ->
            val existing = draft.parentsOf(p.id)
            val missing = when (existing.size) {
                0 -> listOf("father", "mother")
                1 -> listOf(when (draft.people.getValue(existing.first()).gender) { "male" -> "mother"; "female" -> "father"; else -> "parent" })
                else -> emptyList()
            }
            missing.forEach { role ->
                val id = marker("+${p.id}:$role", p.generation + 1,
                    when (role) { "father" -> "male"; "mother" -> "female"; else -> "unknown" }, TreeAction(p.id, role))
                parents.add(TreeParent(id, p.id))
            }
            val coParents = draft.coParentsOf(p.id)
            // A child's missing second-parent marker already occupies this
            // person's co-parent position. Do not draw a second duplicate +.
            val missingCoParent = draft.parents.any { it.parent == p.id && draft.parentsOf(it.child).size == 1 }
            if (coParents.isEmpty() && !missingCoParent) {
                val spouse = marker("+${p.id}:spouse", p.generation, "unknown", TreeAction(p.id, "spouse"))
                pairs.add(TreePair(p.id, spouse))
            }
            (if (coParents.isEmpty()) listOf<String?>(null) else coParents).forEach { other ->
                val key = listOfNotNull(p.id, other).sorted().joinToString(":")
                if (childGroups.add(key)) {
                    val child = marker("+child:$key", p.generation - 1, "unknown", TreeAction(p.id, "child", other))
                    parents.add(TreeParent(p.id, child)); other?.let { parents.add(TreeParent(it, child)) }
                }
            }
        }
        return arrange(nodes, parents, pairs)
    }

    fun arrange(nodes: List<TreeDisplayNode>, parents: List<TreeParent>, pairs: List<TreePair>): TreeDrawing {
        if (nodes.isEmpty()) return TreeDrawing(nodes, parents, pairs, emptyMap(), 320f, 400f)
        val byId = nodes.associateBy { it.id }
        val groups = nodes.associate { it.id to it.id }.toMutableMap()
        fun root(id: String): String { var cur = id; while (groups.getValue(cur) != cur) cur = groups.getValue(cur); return cur }
        fun union(a: String, b: String) { if (byId[a]?.generation == byId[b]?.generation) groups[root(b)] = root(a) }
        pairs.forEach { union(it.first, it.second) }
        parents.groupBy { it.child }.values.forEach { links -> links.drop(1).forEach { union(links.first().parent, it.parent) } }
        val blocks = nodes.groupBy { root(it.id) }.mapValues { (_, values) ->
            values.sortedBy { when (it.gender) { "male" -> 0; "female" -> 2; else -> 1 } }
        }
        val rows = blocks.keys.groupBy { byId.getValue(it).generation }.toSortedMap(reverseOrder())
        val x = mutableMapOf<String, Float>()
        val neighbors = nodes.associate { it.id to mutableListOf<String>() }
        parents.forEach { neighbors.getValue(it.parent).add(it.child); neighbors.getValue(it.child).add(it.parent) }
        fun place(keys: List<String>) {
            val desired = keys.associateWith { key ->
                val values = blocks.getValue(key).flatMap { neighbors.getValue(it.id) }.mapNotNull { x[it] }
                if (values.isEmpty()) blocks.keys.indexOf(key) * 170f else values.average().toFloat()
            }
            val ordered = keys.sortedBy { desired.getValue(it) }
            var right = Float.NEGATIVE_INFINITY
            val centers = mutableMapOf<String, Float>()
            ordered.forEach { key ->
                val half = blocks.getValue(key).size * 66f
                val center = maxOf(desired.getValue(key), right + 36f + half)
                centers[key] = center; right = center + half
            }
            val shift = ordered.map { centers.getValue(it) - desired.getValue(it) }.average().toFloat()
            ordered.forEach { key ->
                val values = blocks.getValue(key)
                values.forEachIndexed { index, n -> x[n.id] = centers.getValue(key) - shift + (index - (values.size - 1) / 2f) * 132f }
            }
        }
        rows.values.forEach { place(it) }
        repeat(4) { rows.values.reversed().forEach { place(it) }; rows.values.forEach { place(it) } }
        val minX = x.values.minOrNull() ?: 0f
        val top = nodes.maxOf { it.generation }
        val points = nodes.associate { it.id to TreePoint(x.getValue(it.id) - minX + 72f, (top - it.generation) * 205f + 76f) }
        return TreeDrawing(nodes, parents, pairs, points, points.values.maxOf { it.x } + 72f,
            points.values.maxOf { it.y } + 90f)
    }
}
