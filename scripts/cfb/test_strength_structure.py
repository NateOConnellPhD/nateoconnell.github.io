"""Season membership checks; standard library, no fitting or network."""
import unittest
from model import CANONICAL, strength_structure


def roster():
    return [dict(id=i, name=f'Team {i}', classification=division, conference=conference)
            for i, division, conference in [(1,'fbs','ACC'),(2,'fbs','ACC'),
                (3,'fbs','FBS Independents'),(4,'fbs','FBS Independents'),
                (5,'fcs','Ivy'),(6,'fcs','Ivy'),(7,'fcs','FCS Independents')]]


class StrengthStructureTests(unittest.TestCase):
    def test_clusters_use_current_membership_and_independents_are_separate(self):
        structure = strength_structure(roster())
        c = structure['conference']
        self.assertEqual(c[0], c[1]); self.assertEqual(c[4], c[5])
        self.assertEqual(len({c[0],c[2],c[3],c[4],c[6]}), 5)
        self.assertEqual(structure['division'], [0,0,0,0,1,1,1])
        reverse = strength_structure(list(reversed(roster())))
        self.assertEqual(reverse['conference_labels'], structure['conference_labels'])
        self.assertEqual(reverse['conference'], list(reversed(c)))

    def test_missing_metadata_is_not_silently_treated_as_independence(self):
        for key in ('classification', 'conference'):
            teams = roster(); teams[0].pop(key)
            with self.assertRaisesRegex(ValueError, 'Missing division/conference'):
                strength_structure(teams)

    def test_model_identity_changes_with_conference_membership(self):
        from sync_data import digest
        teams = roster(); first = strength_structure(teams)
        teams[0]['conference'] = 'Big Ten'
        self.assertNotEqual(digest(first), digest(strength_structure(teams)))
        self.assertTrue(CANONICAL.hierarchical_strength)
        self.assertTrue(CANONICAL.historical_home)


if __name__ == '__main__':
    unittest.main()
