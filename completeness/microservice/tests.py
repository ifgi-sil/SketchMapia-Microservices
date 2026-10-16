import json

from django.test import SimpleTestCase


class CompletenessCompatibilityTests(SimpleTestCase):
    def test_identical_maps_score_one_hundred_percent(self):
        data = {'type': 'FeatureCollection', 'features': [
            {'geometry': {'type': 'Polygon'},
             'properties': {'feat_type': 'Landmark'}},
            {'geometry': {'type': 'LineString'},
             'properties': {'feat_type': 'Street'}},
        ]}
        response = self.client.post('/completeness/analyzeCompleteness/', {
            'sketchFileName': 'test', 'metricFileName': 'test',
            'sketchdata': json.dumps(data), 'metricdata': json.dumps(data),
        })
        self.assertEqual(response.status_code, 200)
        for key in ('landmarkCompleteness', 'streetCompleteness',
                    'overAllCompleteness'):
            self.assertEqual(response.json()[key], 100)
