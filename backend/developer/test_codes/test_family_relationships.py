from copy import deepcopy

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
                    self.assertEqual(find_relationship(self.tree, "spouse", "grandma"), "아내의 " + expected)

    def test_partnerships_compose_relations_without_assuming_marriage_from_children(self):
        self.assertEqual(find_relationship(self.tree, "me", "spouse"), "배우자")
        self.assertEqual(find_relationship(self.tree, "spouse", "parent"), "장인")
        self.assertEqual(find_relationship(self.tree, "parent", "spouse"), "딸의 배우자")

    def test_missing_disconnected_and_cycles_are_safe(self):
        self.assertEqual(find_relationship(self.tree, "me", "missing"), "가족")
        self.assertEqual(find_relationship(self.tree, "me", "disconnected"), "가족")
        self.tree["parents"].append({"parent_id": "me", "child_id": "grandma"})
        self.assertEqual(find_relationship(self.tree, "me", "disconnected"), "가족")

    def test_long_paths_have_no_generation_cutoff(self):
        for index in range(200):
            key = f"child{index}"
            self.tree["people"].append({"id": key, "gender": "unknown"})
            self.tree["parents"].append({"parent_id": f"child{index - 1}" if index else "me", "child_id": key})
        self.assertEqual(find_relationship(self.tree, "me", "child199"), "200대 후손")
        self.assertEqual(find_relationship(self.tree, "child199", "me"), "200대 조상")

    def test_links_to_people_outside_the_tree_are_ignored(self):
        self.tree["parents"].extend([
            {"parent_id": "outside", "child_id": "me"},
            {"parent_id": "outside", "child_id": "disconnected"},
        ])
        self.tree["partnerships"].append({"first_id": "me", "second_id": "outside"})
        self.assertEqual(find_relationship(self.tree, "me", "disconnected"), "가족")


class ExtendedFamilyRelationshipTests(SimpleTestCase):
    def setUp(self):
        genders = {
            "me": "male", "wife": "female", "father": "male", "mother": "female",
            "grandpa": "male", "grandma": "female", "maternal_grandpa": "male",
            "maternal_grandma": "female", "brother": "male", "sister": "female",
            "son": "male", "daughter": "female", "grandson": "male", "granddaughter": "female",
            "uncle": "male", "aunt": "female", "maternal_uncle": "male", "maternal_aunt": "female",
            "uncle_wife": "female", "aunt_husband": "male", "maternal_uncle_wife": "female",
            "maternal_aunt_husband": "male", "cousin": "female", "cousin_child": "unknown",
            "nephew": "male", "niece": "female", "nephew_son": "male",
            "son_wife": "female", "daughter_husband": "male", "son_wife_father": "male",
            "daughter_husband_mother": "female", "wife_father": "male", "wife_mother": "female",
            "wife_brother": "male", "wife_brother_wife": "female", "stepchild": "male",
            "great_grandpa": "male", "great_great_grandma": "female", "great_granddaughter": "female",
        }
        self.tree = {
            "people": [{"id": key, "gender": gender, "generation": 99} for key, gender in genders.items()],
            "parents": [{"parent_id": parent, "child_id": child} for parent, child in (
                ("great_great_grandma", "great_grandpa"), ("great_grandpa", "grandpa"),
                ("grandpa", "father"), ("grandma", "father"),
                ("maternal_grandpa", "mother"), ("maternal_grandma", "mother"),
                ("father", "me"), ("mother", "me"), ("father", "brother"), ("mother", "brother"),
                ("father", "sister"), ("mother", "sister"), ("me", "son"), ("wife", "son"),
                ("me", "daughter"), ("wife", "daughter"), ("son", "grandson"),
                ("daughter", "granddaughter"), ("grandson", "great_granddaughter"),
                ("grandpa", "uncle"), ("grandpa", "aunt"), ("maternal_grandpa", "maternal_uncle"),
                ("maternal_grandpa", "maternal_aunt"), ("aunt", "cousin"), ("cousin", "cousin_child"),
                ("brother", "nephew"), ("sister", "niece"), ("nephew", "nephew_son"),
                ("wife_father", "wife"), ("wife_mother", "wife"), ("wife_father", "wife_brother"),
                ("wife", "stepchild"), ("son_wife_father", "son_wife"),
                ("daughter_husband_mother", "daughter_husband"),
            )],
            "partnerships": [{"first_id": first, "second_id": second} for first, second in (
                ("me", "wife"), ("father", "mother"), ("uncle", "uncle_wife"),
                ("aunt", "aunt_husband"), ("maternal_uncle", "maternal_uncle_wife"),
                ("maternal_aunt", "maternal_aunt_husband"), ("son", "son_wife"),
                ("daughter", "daughter_husband"), ("wife_brother", "wife_brother_wife"),
            )],
        }

    def assert_relationships(self, cases):
        for source, target, expected in cases:
            with self.subTest(source=source, target=target):
                self.assertEqual(find_relationship(self.tree, source, target), expected)

    def test_direct_ancestors_descendants_and_siblings(self):
        self.assert_relationships((
            ("me", "wife", "아내"), ("wife", "me", "남편"),
            ("me", "father", "아버지"), ("me", "mother", "어머니"),
            ("me", "grandpa", "할아버지"), ("me", "grandma", "할머니"),
            ("me", "maternal_grandpa", "외할아버지"), ("me", "maternal_grandma", "외할머니"),
            ("me", "great_grandpa", "증조할아버지"), ("me", "great_great_grandma", "고조할머니"),
            ("me", "son", "아들"), ("me", "daughter", "딸"), ("me", "grandson", "손자"),
            ("me", "granddaughter", "손녀"), ("me", "great_granddaughter", "증손녀"),
            ("me", "brother", "형제자매"), ("me", "sister", "형제자매"),
        ))

    def test_collateral_relations_distinguish_parental_sides_without_guessing_ages(self):
        self.assert_relationships((
            ("me", "uncle", "삼촌"), ("me", "aunt", "고모"),
            ("me", "maternal_uncle", "외삼촌"), ("me", "maternal_aunt", "이모"),
            ("me", "cousin", "사촌"), ("me", "cousin_child", "5촌 친척"),
            ("me", "nephew", "조카"), ("me", "niece", "조카"),
            ("me", "nephew_son", "조카의 아들"),
        ))

    def test_in_laws_and_stepchildren(self):
        self.assert_relationships((
            ("me", "wife_father", "장인"), ("me", "wife_mother", "장모"),
            ("wife", "father", "시아버지"), ("wife", "mother", "시어머니"),
            ("father", "wife", "며느리"), ("wife_father", "me", "사위"),
            ("me", "son_wife", "며느리"), ("me", "daughter_husband", "사위"),
            ("me", "son_wife_father", "사돈"), ("me", "daughter_husband_mother", "사돈"),
            ("me", "uncle_wife", "삼촌의 아내"), ("me", "aunt_husband", "고모부"),
            ("me", "maternal_uncle_wife", "외숙모"), ("me", "maternal_aunt_husband", "이모부"),
            ("me", "wife_brother", "아내의 형제자매"),
            ("me", "wife_brother_wife", "아내의 형제자매의 아내"),
            ("me", "stepchild", "아내의 아들"), ("stepchild", "me", "어머니의 남편"),
        ))

    def test_reported_co_parent_labels_are_compact_without_inventing_marriage(self):
        # 현우 -> 아들 <- 지민 <- 어머니 <- 선희, with no partnership registered.
        self.tree = {
            "people": [{"id": key, "gender": gender} for key, gender in (
                ("hyunwoo", "male"), ("son", "male"), ("jimin", "female"),
                ("mother", "female"), ("sunhee", "female"))],
            "parents": [{"parent_id": parent, "child_id": child} for parent, child in (
                ("hyunwoo", "son"), ("jimin", "son"), ("mother", "jimin"), ("sunhee", "mother"))],
            "partnerships": [],
        }
        original = deepcopy(self.tree)
        self.assert_relationships((
            ("hyunwoo", "jimin", "공동 부모"), ("jimin", "hyunwoo", "공동 부모"),
            ("hyunwoo", "sunhee", "공동 부모의 외할머니"),
            ("sunhee", "hyunwoo", "손녀의 공동 부모"),
            ("son", "sunhee", "외증조할머니"),
        ))
        self.assertEqual(self.tree, original)
        self.tree["partnerships"].append({"first_id": "hyunwoo", "second_id": "jimin"})
        self.assert_relationships((
            ("hyunwoo", "jimin", "아내"), ("jimin", "hyunwoo", "남편"),
            ("hyunwoo", "sunhee", "아내의 외할머니"),
        ))

    def test_blood_relations_win_over_shortcuts_through_partners_and_co_parents(self):
        # A shared child's other parent is also a cousin. A down/up shortcut
        # must not hide the established blood relationship.
        self.tree["parents"].append({"parent_id": "cousin", "child_id": "son"})
        self.assert_relationships((("me", "cousin", "사촌"), ("cousin", "me", "사촌")))
        # Explicit direct partnerships take precedence even for blood relatives.
        self.tree["partnerships"].append({"first_id": "me", "second_id": "cousin"})
        self.assert_relationships((("me", "cousin", "아내"),))

    def test_unknown_gender_uses_neutral_labels(self):
        for person in self.tree["people"]:
            person["gender"] = "unknown"
        self.assert_relationships((
            ("me", "wife", "배우자"), ("me", "father", "부모"),
            ("me", "grandma", "조부모"), ("me", "great_grandpa", "증조부모"),
            ("me", "son", "자녀"), ("me", "grandson", "손주"),
            ("me", "great_granddaughter", "증손주"), ("me", "aunt", "부모의 형제자매"),
            ("me", "wife_father", "배우자의 부모"), ("me", "son_wife", "자녀의 배우자"),
            ("me", "aunt_husband", "부모의 형제자매의 배우자"),
        ))

    def test_input_order_does_not_change_labels_or_mutate_the_tree(self):
        original = deepcopy(self.tree)
        expected = {person["id"]: find_relationship(self.tree, "me", person["id"])
                    for person in self.tree["people"]}
        for values in self.tree.values():
            values.reverse()
        for target, label in expected.items():
            with self.subTest(target=target):
                self.assertEqual(find_relationship(self.tree, "me", target), label)
        for values in self.tree.values():
            values.reverse()
        self.assertEqual(self.tree, original)

    def test_many_marriages_have_a_bounded_label(self):
        self.tree = {
            "people": [{"id": str(i), "gender": "unknown"} for i in range(1200)],
            "parents": [],
            "partnerships": [{"first_id": str(i), "second_id": str(i + 1)} for i in range(1199)],
        }
        self.assertEqual(find_relationship(self.tree, "0", "1199"), "인척")

    def test_many_co_parent_connections_do_not_create_a_marriage(self):
        self.tree = {
            "people": [{"id": str(i), "gender": "unknown"} for i in range(10)],
            "parents": [{"parent_id": str(parent), "child_id": str(5 + i)}
                        for i in range(4) for parent in (i, i + 1)],
            "partnerships": [],
        }
        self.assertEqual(find_relationship(self.tree, "0", "4"), "공동 부모 쪽 가족")
