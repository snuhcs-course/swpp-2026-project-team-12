package kr.talkdock.app.data

import org.json.JSONArray
import org.json.JSONObject

data class TreePerson(val id: String, val name: String, val gender: String, val generation: Int, val occupied: Boolean)
data class TreeParent(val parent: String, val child: String)
data class TreePair(val first: String, val second: String)
data class TreeAddition(val id: String, val anchor: String, val relation: String, val coParent: String? = null) {
    fun json() = JSONObject().put("id", id).put("anchor_id", anchor).put("relation", relation).apply {
        coParent?.let { put("co_parent_id", it) }
    }
}

/** Only additions are editable. Existing people and relationships stay immutable. */
class FamilyTreeDraft(val snapshot: JSONObject) {
    val version = snapshot.getInt("version")
    val ownerId = snapshot.getString("owner_id")
    val people = linkedMapOf<String, TreePerson>()
    val parents = mutableListOf<TreeParent>()
    val partnerships = mutableListOf<TreePair>()
    val additions = mutableListOf<TreeAddition>()
    var selectedId: String? = null

    init { resetGraph() }

    private fun resetGraph() {
        people.clear(); parents.clear(); partnerships.clear()
        val nodes = snapshot.getJSONArray("people")
        repeat(nodes.length()) {
            val n = nodes.getJSONObject(it)
            people[n.getString("id")] = TreePerson(n.getString("id"), n.optString("name"),
                n.optString("gender", "unknown"), n.getInt("generation"), !n.isNull("user_id"))
        }
        val links = snapshot.getJSONArray("parents")
        repeat(links.length()) { val p = links.getJSONObject(it); parents.add(TreeParent(p.getString("parent_id"), p.getString("child_id"))) }
        val pairs = snapshot.getJSONArray("partnerships")
        repeat(pairs.length()) { val p = pairs.getJSONObject(it); partnerships.add(TreePair(p.getString("first_id"), p.getString("second_id"))) }
    }

    fun parentsOf(id: String) = parents.filter { it.child == id }.map { it.parent }
    fun partnersOf(id: String) = partnerships.mapNotNull { if (it.first == id) it.second else if (it.second == id) it.first else null }
    fun coParentsOf(id: String): List<String> {
        val children = parents.filter { it.parent == id }.map { it.child }.toSet()
        return (partnersOf(id) + parents.filter { it.child in children && it.parent != id }.map { it.parent }).distinct()
    }

    fun add(anchor: String, relation: String, coParent: String? = null): String {
        require(additions.size < 200) { "한 번에 추가할 수 있는 가족은 200명까지예요." }
        val a = TreeAddition("new_" + java.util.UUID.randomUUID().toString(), anchor, relation, coParent)
        apply(a); additions.add(a)
        return a.id
    }

    private fun apply(a: TreeAddition) {
        val anchor = people.getValue(a.anchor)
        val shift = when (a.relation) { "father", "mother", "parent" -> 1; "child" -> -1; else -> 0 }
        people[a.id] = TreePerson(a.id, "", when (a.relation) { "father" -> "male"; "mother" -> "female"; else -> "unknown" }, anchor.generation + shift, false)
        when (a.relation) {
            "father", "mother", "parent" -> parents.add(TreeParent(a.id, a.anchor))
            "child" -> { parents.add(TreeParent(a.anchor, a.id)); a.coParent?.let { parents.add(TreeParent(it, a.id)) } }
            "spouse" -> partnerships.add(TreePair(a.anchor, a.id))
        }
    }

    fun undo() {
        if (additions.isEmpty()) return
        val removed = additions.removeAt(additions.lastIndex)
        resetGraph(); additions.forEach { apply(it) }
        if (selectedId == removed.id) selectedId = null
    }

    fun restore(state: JSONObject) {
        val values = state.optJSONArray("additions") ?: JSONArray()
        repeat(values.length()) {
            val a = values.getJSONObject(it)
            val item = TreeAddition(a.getString("id"), a.getString("anchor_id"), a.getString("relation"),
                if (a.has("co_parent_id")) a.getString("co_parent_id") else null)
            apply(item); additions.add(item)
        }
        selectedId = state.optString("person_id").takeIf { people.containsKey(it) }
    }

    fun payload() = JSONObject().put("tree_version", version)
        .put("additions", JSONArray(additions.map { it.json() }))
        .put("person_id", selectedId ?: JSONObject.NULL)
}
