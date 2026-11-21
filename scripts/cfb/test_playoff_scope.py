"""Offline regression checks for playoffs mislabelled as regular season."""
import copy
import unittest

from sync_data import normalize
from test_sync_data import NOW, fixture


class PlayoffScopeTests(unittest.TestCase):
    def test_playoff_markers_excluded_but_conference_finals_retained(self):
        source = fixture()
        base = dict(source['/games'][0], homeId=8, awayId=9,
                    homeTeam='FCS A', awayTeam='FCS B',
                    homeClassification='fcs', awayClassification='fcs')
        rows = [dict(base, id=200 + i, **marker) for i, marker in enumerate([
            {'notes': 'FCS Championship – First Round'},
            {'notes': 'FCS Championship - Semifinal'},
            {'playoff_competition': 'FCS'},
            {'playoff': {'competition': 'FCS', 'round': 'First Round'}},
            {'notes': 'SWAC Championship'}, {'notes': None},
        ])]
        source['/games'] += rows
        result = normalize(2026, source['/teams/fbs'], source['/calendar'],
                           source['/games'], NOW, include_fcs=True)
        self.assertEqual([g['id'] for g in result['games'] if g['eligible']], [101, 204, 205])
        self.assertEqual(result['summary']['exclusion_counts'], {'fcs_playoff': 4})
        self.assertTrue(all(g.get('playoff_evidence') for g in result['games'] if not g['eligible']))
        # The FBS reference/history data path is unaffected by FCS annotations.
        fbs = copy.deepcopy(source['/games'][0]); fbs['notes'] = 'Conference Championship'
        self.assertTrue(normalize(2026, source['/teams/fbs'], source['/calendar'], [fbs], NOW)['games'][0]['eligible'])


if __name__ == '__main__':
    unittest.main()
