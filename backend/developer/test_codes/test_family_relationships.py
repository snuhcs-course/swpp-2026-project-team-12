from django.test import SimpleTestCase

from apps.families.utils import find_relationship


class FamilyRelationshipTests(SimpleTestCase):
    def setUp(self):
        # Deliberately misleading generations: only graph edges determine kinship.
        self.tree = {
            "people": [{"id": key, "gender": gender, "generation": 99} for key, gender in (
                ("grandma", "female"), ("parent", "male"), ("me", "female"),
                ("sibling", "male"), ("nephew", "unknown"), ("spouse", "unknown"),
                ("aunt", "female"), ("cousin", "female"), ("disconnected", "unknown"))],
            "parents": [{"parent_id": parent, "child_id": child} for parent, child in (
                ("grandma", "parent"), ("parent", "me"), ("parent", "sibling"),
                ("sibling", "nephew"), ("grandma", "aunt"), ("aunt", "cousin"))],
            "partnerships": [{"first_id": "me", "second_id": "spouse"}],
        }

    def test_searches_both_directions_and_collateral_paths(self):
        for source, target, expected in (
            ("me", "me", "나"), ("me", "parent", "아버지"), ("parent", "me", "딸"),
            ("me", "grandma", "할머니"), ("grandma", "me", "손녀"),
            ("me", "sibling", "형제자매"), ("me", "nephew", "조카"), ("me", "cousin", "사촌"),
        ):
            with self.subTest(source=source, target=target):
                self.assertEqual(find_relationship(self.tree, source, target), expected)

    def test_grandparents_distinguish_the_maternal_side_using_the_intermediate_parent(self):
        people = {person["id"]: person for person in self.tree["people"]}
        for parent_gender, names in (
            ("male", ("할아버지", "할머니", "조부모")),
            ("female", ("외할아버지", "외할머니", "외조부모")),
            ("unknown", ("할아버지", "할머니", "조부모")),
        ):
            people["parent"]["gender"] = parent_gender
            for gender, expected in zip(("male", "female", "unknown"), names):
                with self.subTest(parent_gender=parent_gender, grandparent_gender=gender):
                    people["grandma"]["gender"] = gender
                    self.assertEqual(find_relationship(self.tree, "me", "grandma"), expected)
                    self.assertEqual(find_relationship(self.tree, "spouse", "grandma"), "배우자의 " + expected)

    def test_partnerships_compose_relations_without_assuming_marriage_from_children(self):
        self.assertEqual(find_relationship(self.tree, "me", "spouse"), "배우자")
        self.assertEqual(find_relationship(self.tree, "spouse", "parent"), "배우자의 아버지")
        self.assertEqual(find_relationship(self.tree, "parent", "spouse"), "딸의 배우자")

    def test_missing_disconnected_and_cycles_are_safe(self):
        self.assertEqual(find_relationship(self.tree, "me", "missing"), "가족")
        self.assertEqual(find_relationship(self.tree, "me", "disconnected"), "가족")
        self.tree["parents"].append({"parent_id": "me", "child_id": "grandma"})
        self.assertEqual(find_relationship(self.tree, "me", "disconnected"), "가족")

    def test_long_paths_have_no_six_generation_cutoff(self):
        for index in range(8):
            key = f"child{index}"
            self.tree["people"].append({"id": key, "gender": "unknown"})
            self.tree["parents"].append({"parent_id": f"child{index - 1}" if index else "me", "child_id": key})
        self.assertEqual(find_relationship(self.tree, "me", "child7"), "8대 후손")
        self.assertEqual(find_relationship(self.tree, "child7", "me"), "8대 조상")

    def test_links_to_people_outside_the_tree_are_ignored(self):
        self.tree["parents"].extend([
            {"parent_id": "outside", "child_id": "me"},
            {"parent_id": "outside", "child_id": "disconnected"},
        ])
        self.assertEqual(find_relationship(self.tree, "me", "disconnected"), "가족")
